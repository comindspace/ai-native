from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


class ValidationInProgress(RuntimeError):
    pass


def list_projects() -> list[dict[str, Any]]:
    if not postgres_enabled():
        return []
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select * from factory_projects order by project_id")
        return [dict(row) for row in cur.fetchall()]


def get_project(project_id: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from factory_projects where project_id = %s",
            (project_id.strip().casefold(),),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def operation_result(
    actor: str, operation: str, key: str, fingerprint: str
) -> dict | None:
    _require_storage()
    with _connect() as conn, conn.cursor() as cur:
        return _receipt(cur, actor, operation, key, fingerprint)


def begin_operation(
    actor: str, operation: str, key: str, fingerprint: str, project_id: str
) -> dict | None:
    _require_storage()
    with _connect() as conn, conn.cursor() as cur:
        _lock_project(cur, project_id)
        cur.execute(
            """update factory_project_operations set status = 'failed',
            result = %s::jsonb where project_id = %s and status = 'running'
            and created_at < now() - interval '10 minutes'""",
            (json.dumps(_interrupted_result(project_id)), project_id),
        )
        cur.execute(
            """insert into factory_project_operations
            (actor_subject, operation, idempotency_key, project_id, fingerprint, result, status)
            values (%s, %s, %s, %s, %s, '{}'::jsonb, 'running')
            on conflict do nothing returning idempotency_key""",
            (actor, operation, key, project_id, fingerprint),
        )
        created = cur.fetchone()
        result = None if created else _receipt(cur, actor, operation, key, fingerprint)
        if not created and result is None:
            raise ValidationInProgress("another project validation is in progress")
        conn.commit()
    return result


def fail_operation(actor: str, operation: str, key: str, project_id: str) -> None:
    _require_storage()
    result = _interrupted_result(project_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """update factory_project_operations set status = 'failed', result = %s::jsonb
            where actor_subject = %s and operation = %s and idempotency_key = %s and status = 'running'""",
            (json.dumps(result), actor, operation, key),
        )
        conn.commit()


def _interrupted_result(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "ready": False,
        "readiness_gaps": ["validation_interrupted"],
        "validation": {
            "ready": False,
            "checked_at": "1970-01-01T00:00:00+00:00",
            "readiness_gaps": ["validation_interrupted"],
            "connection_version": 0,
        },
    }


def _receipt(
    cur,
    actor: str,
    operation: str,
    key: str,
    fingerprint: str,
    *,
    allow_running: bool = False,
) -> dict | None:
    cur.execute(
        """select fingerprint, result, status from factory_project_operations
        where actor_subject = %s and operation = %s and idempotency_key = %s""",
        (actor, operation, key),
    )
    row = cur.fetchone()
    if row and row["fingerprint"] != fingerprint:
        raise ValueError("idempotency_key was used with a different request")
    if row and row.get("status") == "running":
        if allow_running:
            return None
        raise ValidationInProgress(
            "operation is in progress or was interrupted; inspect pending probes before using a new key"
        )
    return {**row["result"], "replayed": True} if row else None


def save_project(
    *,
    config: dict,
    readiness: dict,
    actor: str,
    operation: str,
    key: str,
    fingerprint: str,
    expected_revision: int,
) -> dict:
    _require_storage()
    project_id = config["project_id"]
    with _connect() as conn, conn.cursor() as cur:
        # Lock the receipt as well as the project, including first insertion.
        cur.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"factory-operation:{actor}:{operation}:{key}",),
        )
        replay = _receipt(cur, actor, operation, key, fingerprint, allow_running=True)
        if replay:
            return replay
        cur.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"factory-project:{project_id}",),
        )
        cur.execute(
            "select * from factory_projects where project_id = %s for update",
            (project_id,),
        )
        previous = cur.fetchone()
        revision = int(previous["revision"]) if previous else 0
        if revision != expected_revision:
            raise ValueError(
                "project changed during validation; retry with a new idempotency_key"
            )
        changed = not previous or previous["config"] != config
        revision += int(changed)
        result = {
            "project_id": project_id,
            "revision": revision,
            "changed": changed,
            "ready": readiness["ready"],
            "readiness_gaps": readiness["readiness_gaps"],
            "validation": readiness,
            "replayed": False,
        }
        cur.execute(
            """insert into factory_projects (project_id, config, revision, readiness, updated_by)
            values (%s, %s::jsonb, %s, %s::jsonb, %s)
            on conflict (project_id) do update set config = excluded.config,
            revision = excluded.revision, readiness = excluded.readiness,
            updated_by = excluded.updated_by, updated_at = now()""",
            (project_id, json.dumps(config), revision, json.dumps(readiness), actor),
        )
        cur.execute(
            """update factory_project_operations set result = %s::jsonb, status = 'complete'
            where actor_subject = %s and operation = %s and idempotency_key = %s and status = 'running'""",
            (json.dumps(result), actor, operation, key),
        )
        conn.commit()
    return result


def reserve_probe(project_id: str, remote_url: str, ref: str, head: str) -> None:
    _require_storage()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into factory_git_probes (ref, project_id, remote_url, head, state)
            values (%s, %s, %s, %s, 'pending')""",
            (ref, project_id, remote_url, head),
        )
        conn.commit()


def finish_probe(ref: str, cleaned: bool) -> None:
    _require_storage()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update factory_git_probes set state = %s, updated_at = now() where ref = %s",
            ("removed" if cleaned else "cleanup_required", ref),
        )
        conn.commit()


def list_probes(project_id: str) -> list[dict]:
    if not postgres_enabled():
        return []
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """select ref, remote_url, head from factory_git_probes
            where project_id = %s and state != 'removed' order by created_at""",
            (project_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def retry_receipt(work_id: str, actor: str, key: str) -> bool:
    _require_storage()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """select 1 from factory_work_retries
            where work_id = %s and actor_subject = %s and idempotency_key = %s""",
            (work_id, actor, key),
        )
        return cur.fetchone() is not None


def requeue_work(
    *,
    work_id: str,
    actor: str,
    key: str,
    project_id: str,
    revision: int,
    connection_id: str,
    connection_version: int,
) -> dict:
    _require_storage()
    project_id = project_id.strip().casefold()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select * from work_runs where work_id = %s for update", (work_id,))
        work = cur.fetchone()
        if not work:
            raise KeyError("unknown work_id")
        cur.execute(
            """select 1 from factory_work_retries
            where work_id = %s and actor_subject = %s and idempotency_key = %s""",
            (work_id, actor, key),
        )
        if cur.fetchone():
            return {"work_id": work_id, "status": work["status"], "replayed": True}
        if (
            work["status"] != "blocked"
            or work["execution_mode"] != "factory"
            or work["project_id"].strip().casefold() != project_id
            or work["scope_decision"] not in {"within_scope", "clarification"}
        ):
            raise ValueError("only in-scope blocked Factory work can be retried")
        _lock_project(cur, project_id)
        cur.execute(
            "select revision, config, readiness from factory_projects where project_id = %s for share",
            (project_id,),
        )
        project = cur.fetchone()
        if (
            not project
            or project["revision"] != revision
            or project["config"].get("gitlab_connection_id") != connection_id
        ):
            raise ValueError("project changed during readiness check")
        current = project.get("readiness") or {}
        checked_at = current.get("checked_at")
        if (
            not current.get("ready")
            or current.get("readiness_gaps")
            or not checked_at
            or current.get("connection_version") != connection_version
            or (
                datetime.now(timezone.utc) - datetime.fromisoformat(checked_at)
            ).total_seconds()
            > 300
        ):
            raise ValueError("current project readiness requires validation")
        cur.execute(
            """select 1 where exists (
            select 1 from factory_project_operations where project_id = %s and status = 'running'
            ) or exists (
            select 1 from factory_git_probes where project_id = %s and state != 'removed'
            )""",
            (project_id, project_id),
        )
        if cur.fetchone():
            raise ValueError("project validation or probe cleanup is pending")
        cur.execute(
            """select version from managed_service_connections where system = %s
            and state = 'active' and (expires_at is null or expires_at > now()) for share""",
            (connection_id,),
        )
        connection = cur.fetchone()
        if not connection or connection["version"] != connection_version:
            raise ValueError("connection changed during readiness check")
        # Keep source, AC, evidence, correction count and original timing intact.
        cur.execute(
            """update work_runs set status = 'queued', claimed_by = '',
            lease_expires_at = null, completed_at = null, updated_at = now()
            where work_id = %s""",
            (work_id,),
        )
        cur.execute(
            """insert into factory_work_retries
            (work_id, idempotency_key, actor_subject, project_revision) values (%s, %s, %s, %s)""",
            (work_id, key, actor, revision),
        )
        cur.execute(
            """insert into work_events (work_id, actor_subject, event_type, payload)
            values (%s, %s, 'readiness_retry', %s::jsonb)""",
            (
                work_id,
                actor,
                json.dumps({"project_revision": revision, "validation": "passed"}),
            ),
        )
        conn.commit()
    return {"work_id": work_id, "status": "queued", "replayed": False}


def _require_storage() -> None:
    if not postgres_enabled():
        raise RuntimeError("Postgres is required for Factory project administration")
    ensure_schema()


def admit_work_lease(*, work: dict, project: dict) -> dict:
    """Record admission only while the lease, configuration and credential match."""
    from gateway_mcp.services.storage_work import _row

    _require_storage()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from work_runs where work_id = %s for update", (work["work_id"],)
        )
        current_work = cur.fetchone()
        now = datetime.now(timezone.utc)
        if (
            not current_work
            or current_work["status"] != "running"
            or current_work["execution_mode"] != "factory"
            or current_work["scope_decision"] not in {"within_scope", "clarification"}
            or current_work["claimed_by"] != work["claimed_by"]
            or str(current_work["project_id"]).strip().lower() != project["project_id"]
            or current_work["project_path"] != project["config"]["project_path"]
            or current_work["lease_expires_at"]
            != datetime.fromisoformat(str(work["lease_expires_at"]))
            or current_work["lease_expires_at"] <= now
        ):
            raise ValueError("Factory lease changed during preflight")
        _lock_project(cur, project["project_id"])
        cur.execute(
            "select * from factory_projects where project_id = %s for share",
            (project["project_id"],),
        )
        current = cur.fetchone()
        if (
            not current
            or current["revision"] != project["revision"]
            or current["config"] != project["config"]
        ):
            raise ValueError("Factory project changed during preflight")
        report = current["readiness"]
        checked = report.get("checked_at")
        if (
            not report.get("ready")
            or report.get("readiness_gaps")
            or not checked
            or not 0
            <= (now - datetime.fromisoformat(str(checked))).total_seconds()
            <= 300
        ):
            raise ValueError("Fresh project readiness is required")
        cur.execute(
            """select 1 where exists (
            select 1 from factory_project_operations where project_id = %s and status = 'running'
            ) or exists (
            select 1 from factory_git_probes where project_id = %s and state != 'removed'
            )""",
            (project["project_id"], project["project_id"]),
        )
        if cur.fetchone():
            raise ValidationInProgress("Project validation or cleanup is pending")
        cur.execute(
            """select version from managed_service_connections where system = %s
            and state = 'active' and (expires_at is null or expires_at > now()) for share""",
            (current["config"]["gitlab_connection_id"],),
        )
        connection = cur.fetchone()
        if not connection or connection["version"] != report.get("connection_version"):
            raise ValueError("Connection changed during preflight")
        cur.execute(
            """insert into work_events (work_id, actor_subject, event_type, payload)
            values (%s, %s, 'factory_preflight', %s::jsonb)""",
            (
                work["work_id"],
                work["claimed_by"],
                json.dumps(
                    {
                        "ready": True,
                        "project_revision": current["revision"],
                        "connection_version": connection["version"],
                        "checked_at": checked,
                        "lease_expires_at": str(current_work["lease_expires_at"]),
                    }
                ),
            ),
        )
        conn.commit()
    return _row(current_work)


def _lock_project(cur, project_id: str) -> None:
    # Admission and requeue share a transaction lock: no new external probe can
    # start between requeue's readiness barrier and the queued-state commit.
    cur.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"factory-project:{project_id}",),
    )
