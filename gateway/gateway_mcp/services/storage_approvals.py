import json
from datetime import UTC, datetime, timedelta
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def insert_approval_request(
    *,
    approval_id: str,
    approval_type: str,
    subject: str,
    created_by: str,
    required_role: str,
    required_scope: str,
    artifact_hash: str,
    artifact_version: str,
    payload: dict[str, Any],
    source_refs: dict[str, Any],
    metadata: dict[str, Any],
    four_eyes: bool,
    expires_in_days: int | None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into approval_requests (
                    approval_id, approval_type, status, subject, created_by,
                    required_role, required_scope, artifact_hash, artifact_version,
                    payload, source_refs, metadata, four_eyes, expires_at
                )
                values (%s, %s, 'pending', %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                returning *
                """,
                (
                    approval_id,
                    approval_type,
                    subject,
                    created_by,
                    required_role,
                    required_scope,
                    artifact_hash,
                    artifact_version,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(source_refs, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    four_eyes,
                    expires_at,
                ),
            )
            request_row = cur.fetchone()
            cur.execute(
                """
                insert into approval_events (
                    approval_id, event_type, actor_subject, actor_groups,
                    comment, decision_payload
                )
                values (%s, 'created', %s, '[]'::jsonb, '', '{}'::jsonb)
                """,
                (approval_id, created_by),
            )
        conn.commit()
    return _approval_request_row(request_row)


def get_approval_request(approval_id: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from approval_requests where approval_id = %s",
            (approval_id,),
        )
        row = cur.fetchone()
    return _approval_request_row(row) if row else None


def list_approval_requests(
    *,
    status: str,
    approval_type: str,
    created_by: str,
    required_role: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    where = ["(expires_at is null or expires_at > now())"]
    params: list[Any] = []
    for column, value in {
        "status": status,
        "approval_type": approval_type,
        "created_by": created_by,
        "required_role": required_role,
    }.items():
        clean = str(value or "").strip()
        if clean:
            where.append(f"{column} = %s")
            params.append(clean)
    params.append(max(1, min(int(limit or 50), 500)))

    sql = f"""
        select *
        from approval_requests
        where {" and ".join(where)}
        order by created_at desc, approval_id desc
        limit %s
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_approval_request_row(row) for row in rows]


def list_approval_events(approval_id: str) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
                select * from approval_events
                where approval_id = %s
                order by created_at asc, id asc
                """,
            (approval_id,),
        )
        rows = cur.fetchall()
    return [_approval_event_row(row) for row in rows]


def append_approval_event(
    *,
    approval_id: str,
    event_type: str,
    actor_subject: str,
    actor_groups: list[str],
    comment: str,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into approval_events (
                    approval_id, event_type, actor_subject, actor_groups,
                    comment, decision_payload
                )
                values (%s, %s, %s, %s::jsonb, %s, %s::jsonb)
                returning *
                """,
                (
                    approval_id,
                    event_type,
                    actor_subject,
                    json.dumps(actor_groups, ensure_ascii=False),
                    comment,
                    json.dumps(decision_payload, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _approval_event_row(row)


def update_approval_decision(
    *,
    approval_id: str,
    status: str,
    decided_by: str,
    actor_groups: list[str],
    comment: str,
    decision_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update approval_requests
                set status = %s,
                    decided_by = %s,
                    decided_at = now(),
                    updated_at = now()
                where approval_id = %s
                  and status in ('pending', 'need_info')
                  and (expires_at is null or expires_at > now())
                returning *
                """,
                (status, decided_by, approval_id),
            )
            request_row = cur.fetchone()
            if request_row:
                cur.execute(
                    """
                    insert into approval_events (
                        approval_id, event_type, actor_subject, actor_groups,
                        comment, decision_payload
                    )
                    values (%s, %s, %s, %s::jsonb, %s, %s::jsonb)
                    """,
                    (
                        approval_id,
                        status,
                        decided_by,
                        json.dumps(actor_groups, ensure_ascii=False),
                        comment,
                        json.dumps(decision_payload, ensure_ascii=False),
                    ),
                )
        conn.commit()
    return _approval_request_row(request_row) if request_row else None


def consume_approval_request(
    *,
    approval_id: str,
    actor_subject: str,
    action: str,
    consumption_key: str,
    invocation_hash: str,
) -> dict[str, Any] | None:
    """Atomically consume one approval for exactly one protected invocation."""
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP approvals")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select * from approval_requests
                where approval_id = %s
                for update
                """,
                (approval_id,),
            )
            current = cur.fetchone()
            if not current:
                conn.commit()
                return None
            current_key = str(current.get("consumption_key") or "")
            if current_key:
                conn.commit()
                return None
            if str(current.get("status") or "") != "approved":
                conn.commit()
                return None
            expires_at = current.get("expires_at")
            if expires_at is not None and expires_at <= datetime.now(UTC):
                conn.commit()
                return None
            cur.execute(
                """
                update approval_requests
                set consumed_at = now(), consumed_by = %s,
                    consumed_action = %s, consumption_key = %s,
                    updated_at = now()
                where approval_id = %s and consumption_key = ''
                returning *
                """,
                (actor_subject, action, consumption_key, approval_id),
            )
            request_row = cur.fetchone()
            if request_row:
                cur.execute(
                    """
                    insert into approval_events (
                        approval_id, event_type, actor_subject, actor_groups,
                        comment, decision_payload
                    )
                    values (%s, 'consumed', %s, '[]'::jsonb, '', %s::jsonb)
                    """,
                    (
                        approval_id,
                        actor_subject,
                        json.dumps(
                            {
                                "action": action,
                                "invocation_hash": invocation_hash,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
        conn.commit()
    return _approval_request_row(request_row) if request_row else None


def _approval_request_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = dict(row)
    for key in ("payload", "source_refs", "metadata"):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                result[key] = {}
    for key in (
        "created_at",
        "updated_at",
        "expires_at",
        "decided_at",
        "consumed_at",
    ):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _approval_event_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = dict(row)
    for key in ("actor_groups", "decision_payload"):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                result[key] = [] if key == "actor_groups" else {}
    value = result.get("created_at")
    if hasattr(value, "isoformat"):
        result["created_at"] = value.isoformat()
    return result
