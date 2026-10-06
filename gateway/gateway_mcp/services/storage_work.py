import json
from collections.abc import Callable
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def insert_work_run(values: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into work_runs (
                    work_id, idempotency_key, actor_subject, project_id, project_path,
                    scope_id, scope_decision, source_type, source_ref, intent_summary,
                    work_kind, sdd_level, execution_mode, risk_level, status, priority,
                    source_refs, acceptance_criteria, quality_gates, contract,
                    claimed_by, started_at
                ) values (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s
                )
                on conflict (actor_subject, idempotency_key)
                    where idempotency_key <> ''
                do update set updated_at = work_runs.updated_at
                returning *, (xmax = 0) as _inserted
                """,
                (
                    values["work_id"],
                    values.get("idempotency_key", ""),
                    values["actor_subject"],
                    values["project_id"],
                    values.get("project_path", ""),
                    values.get("scope_id", ""),
                    values.get("scope_decision", "unresolved"),
                    values["source_type"],
                    values.get("source_ref", ""),
                    values["intent_summary"],
                    values.get("work_kind", "code_change"),
                    values["sdd_level"],
                    values["execution_mode"],
                    values.get("risk_level", "normal"),
                    values["status"],
                    int(values.get("priority", 0)),
                    _json(values.get("source_refs", [])),
                    _json(values.get("acceptance_criteria", [])),
                    _json(values.get("quality_gates", [])),
                    _json(values.get("contract", {})),
                    values.get("claimed_by", ""),
                    values.get("started_at"),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row(row)


def get_work_run(work_id: str) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from work_runs where work_id = %s", (work_id,))
            row = cur.fetchone()
    return _row(row) if row else None


def search_work_runs(
    *,
    project_id: str = "",
    status: str = "",
    execution_mode: str = "",
    actor_subject: str = "",
    limit: int = 25,
) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    where = ["true"]
    params: list[Any] = []
    for column, value in (
        ("project_id", project_id),
        ("status", status),
        ("execution_mode", execution_mode),
        ("actor_subject", actor_subject),
    ):
        if value:
            where.append(f"{column} = %s")
            params.append(value)
    params.append(max(1, min(int(limit), 100)))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select * from work_runs
                where {" and ".join(where)}
                order by created_at desc
                limit %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def claim_work_run(
    *,
    claimed_by: str,
    lease_seconds: int,
    work_id: str = "",
    project_id: str = "",
) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    filters = ["status = 'queued'", "execution_mode = 'factory'"]
    params: list[Any] = []
    if work_id:
        filters.append("work_id = %s")
        params.append(work_id)
    if project_id:
        filters.append("project_id = %s")
        params.append(project_id)
    params.extend([claimed_by, max(60, min(int(lease_seconds), 86400))])
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                with candidate as (
                    select work_id
                    from work_runs
                    where {" and ".join(filters)}
                    order by priority desc, created_at
                    for update skip locked
                    limit 1
                )
                update work_runs as target
                set status = 'running',
                    claimed_by = %s,
                    started_at = coalesce(started_at, now()),
                    lease_expires_at = now() + (%s::text || ' seconds')::interval,
                    updated_at = now()
                from candidate
                where target.work_id = candidate.work_id
                returning target.*
                """,
                params,
            )
            row = cur.fetchone()
            if row:
                # Lease admission must commit with the lease, including retries
                # by the same worker after an earlier lease expired.
                cur.execute(
                    """insert into work_events
                    (work_id, actor_subject, event_type, payload)
                    values (%s, %s, 'claimed', %s::jsonb)""",
                    (
                        row["work_id"],
                        claimed_by,
                        _json(
                            {
                                "lease_seconds": max(
                                    60, min(int(lease_seconds), 86400)
                                ),
                                "lease_expires_at": str(row["lease_expires_at"]),
                            }
                        ),
                    ),
                )
        conn.commit()
    return _row(row) if row else None


WORK_RUN_MUTABLE_FIELDS = {
    "status",
    "result_refs",
    "metrics",
    "claimed_by",
    "lease_expires_at",
    "first_verified_at",
    "completed_at",
    "accepted_at",
    "correction_rounds",
    "contract",
}


def _work_run_updates(values: dict[str, Any]) -> tuple[list[str], list[Any]]:
    updates: list[str] = []
    params: list[Any] = []
    for key, value in values.items():
        if key not in WORK_RUN_MUTABLE_FIELDS:
            continue
        if key in {"result_refs", "metrics", "contract"}:
            updates.append(f"{key} = %s::jsonb")
            params.append(_json(value))
        else:
            updates.append(f"{key} = %s")
            params.append(value)
    return updates, params


def update_work_run(work_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    updates, params = _work_run_updates(values)
    if not updates:
        return get_work_run(work_id)
    updates.append("updated_at = now()")
    params.append(work_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update work_runs set {', '.join(updates)} where work_id = %s returning *",
                params,
            )
            row = cur.fetchone()
        conn.commit()
    return _row(row) if row else None


def transition_work_run(
    *,
    work_id: str,
    expected_statuses: set[str],
    values: dict[str, Any],
    actor_subject: str,
    event_type: str,
    event_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Atomically update a work state and append its matching event."""

    _require_postgres()
    ensure_schema()
    if not expected_statuses:
        raise ValueError("expected_statuses is required")
    updates, params = _work_run_updates(values)
    if not updates:
        raise ValueError("work transition must update at least one field")
    updates.append("updated_at = now()")
    statuses = sorted(expected_statuses)
    placeholders = ", ".join("%s" for _ in statuses)
    params.extend([work_id, *statuses])

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                update work_runs
                set {", ".join(updates)}
                where work_id = %s and status in ({placeholders})
                returning *
                """,
                params,
            )
            work_row = cur.fetchone()
            if not work_row:
                conn.rollback()
                return None, None
            cur.execute(
                """
                insert into work_events (work_id, actor_subject, event_type, payload)
                values (%s, %s, %s, %s::jsonb)
                returning *
                """,
                (work_id, actor_subject, event_type, _json(event_payload)),
            )
            event_row = cur.fetchone()
        conn.commit()
    return _row(work_row), _row(event_row)


def latest_work_claim(work_id: str) -> dict[str, Any] | None:
    """Read server-issued lease admission, not user-supplied event metadata."""
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """select actor_subject, occurred_at, payload from work_events
            where work_id = %s and event_type = 'claimed'
            order by occurred_at desc, id desc limit 1""",
            (work_id,),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def latest_factory_preflight(work_id: str) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """select actor_subject, occurred_at, payload from work_events
            where work_id = %s and event_type = 'factory_preflight'
            order by occurred_at desc, id desc limit 1""",
            (work_id,),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def block_claim_preflight(work: dict, gaps: list[str]) -> dict | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """update work_runs set status = 'blocked', updated_at = now()
            where work_id = %s and status = 'running' and claimed_by = %s
            and lease_expires_at = %s::timestamptz returning *""",
            (work["work_id"], work["claimed_by"], work["lease_expires_at"]),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """insert into work_events (work_id, actor_subject, event_type, payload)
                values (%s, %s, 'blocked', %s::jsonb)""",
                (
                    work["work_id"],
                    work["claimed_by"],
                    _json(
                        {
                            "phase": "preflight",
                            "stop_code": "READINESS_GAPS",
                            "readiness_gaps": gaps,
                            "repository_actions_taken": False,
                        }
                    ),
                ),
            )
        conn.commit()
    return _row(row) if row else None


def insert_work_event(
    *, work_id: str, actor_subject: str, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into work_events (work_id, actor_subject, event_type, payload)
                values (%s, %s, %s, %s::jsonb)
                returning *
                """,
                (work_id, actor_subject, event_type, _json(payload)),
            )
            row = cur.fetchone()
        conn.commit()
    return _row(row)


def append_work_event_locked(
    *,
    work_id: str,
    actor_subject: str,
    event_type: str,
    payload_factory: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lock one Work Contract while deriving and appending its next event."""

    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select * from work_runs where work_id = %s for update", (work_id,)
            )
            work_row = cur.fetchone()
            if not work_row:
                raise KeyError(f"unknown work_id: {work_id}")
            cur.execute(
                """
                select payload from work_events
                where work_id = %s and event_type = %s
                order by id desc
                limit 1
                """,
                (work_id, event_type),
            )
            latest_row = cur.fetchone()
            latest_payload = dict(latest_row.get("payload") or {}) if latest_row else {}
            payload = payload_factory(latest_payload)
            cur.execute(
                """
                insert into work_events (work_id, actor_subject, event_type, payload)
                values (%s, %s, %s, %s::jsonb)
                returning *
                """,
                (work_id, actor_subject, event_type, _json(payload)),
            )
            event_row = cur.fetchone()
        conn.commit()
    return _row(work_row), _row(event_row)


def list_work_events(work_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select * from work_events
                where work_id = %s
                order by occurred_at, id
                limit %s
                """,
                (work_id, max(1, min(int(limit), 500))),
            )
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def work_metrics(*, project_id: str = "", days: int = 30) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    where = ["created_at >= now() - (%s::text || ' days')::interval"]
    params: list[Any] = [max(1, min(int(days), 365))]
    if project_id:
        where.append(
            "(project_id = %s or project_path = %s "
            "or right(project_path, char_length(%s) + 1) = '/' || %s)"
        )
        params.extend([project_id, project_id, project_id, project_id])
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    execution_mode,
                    count(*) as runs,
                    count(*) filter (where status = 'accepted') as accepted_runs,
                    count(*) filter (where status = 'blocked') as blocked_runs,
                    count(*) filter (where status = 'blocked')::float
                        / nullif(count(*), 0) as blocked_rate,
                    percentile_cont(0.5) within group (
                        order by extract(epoch from (first_verified_at - signal_at))
                    ) filter (where first_verified_at is not null) as p50_signal_to_verified_seconds,
                    percentile_cont(0.5) within group (
                        order by extract(epoch from (accepted_at - signal_at))
                    ) filter (where accepted_at is not null) as p50_signal_to_accepted_seconds,
                    avg(correction_rounds) filter (
                        where accepted_at is not null
                    ) as avg_correction_rounds,
                    percentile_cont(0.5) within group (
                        order by correction_rounds
                    ) filter (where accepted_at is not null) as p50_correction_rounds,
                    count(*) filter (where accepted_at is not null and correction_rounds = 0)::float
                        / nullif(count(*) filter (where accepted_at is not null), 0)
                        as first_pass_acceptance_rate,
                    count(*) filter (where metrics->>'evidence_state' = 'complete')::float
                        / nullif(count(*), 0) as evidence_complete_rate,
                    percentile_cont(0.5) within group (
                        order by coalesce((metrics->>'admin_actions')::numeric, 0)
                    ) as p50_admin_actions
                from work_runs
                where {" and ".join(where)}
                group by execution_mode
                order by execution_mode
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def work_project_metrics(*, project_id: str = "", days: int = 30) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    where = ["created_at >= now() - (%s::text || ' days')::interval"]
    params: list[Any] = [max(1, min(int(days), 365))]
    if project_id:
        where.append("project_id = %s")
        params.append(project_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    project_id,
                    count(*) as runs,
                    count(*) filter (where status = 'accepted') as accepted_runs,
                    count(*) filter (where status = 'blocked') as blocked_runs,
                    count(*) filter (
                        where status in ('queued', 'running', 'review', 'completed')
                    ) as open_runs,
                    count(*) filter (
                        where status = 'accepted' and correction_rounds = 0
                    ) as first_pass_runs,
                    percentile_cont(0.5) within group (
                        order by extract(epoch from (first_verified_at - signal_at))
                    ) filter (where first_verified_at is not null) as p50_signal_to_verified_seconds,
                    percentile_cont(0.5) within group (
                        order by extract(epoch from (accepted_at - signal_at))
                    ) filter (where accepted_at is not null) as p50_signal_to_accepted_seconds,
                    percentile_cont(0.5) within group (
                        order by correction_rounds
                    ) filter (where accepted_at is not null) as p50_correction_rounds,
                    max(extract(epoch from (now() - updated_at))) filter (
                        where status = 'blocked'
                    ) as oldest_blocked_seconds,
                    max(updated_at) as last_activity_at
                from work_runs
                where {' and '.join(where)}
                group by project_id
                order by count(*) desc, project_id
                limit 200
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def _require_postgres() -> None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for the work ledger")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif hasattr(value, "as_tuple"):
            result[key] = float(value)
    return result
