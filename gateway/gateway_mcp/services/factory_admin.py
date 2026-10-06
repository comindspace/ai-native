from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone

from gateway_mcp.services import storage_factory
from gateway_mcp.services.access_policy import explain_resource_access
from gateway_mcp.services.factory_readiness import clean_url, validate_repository
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.work import _require_project_access, get_work

FIELDS = {
    "project_id",
    "project_path",
    "gitlab_clone_url",
    "gitlab_web_url",
    "default_base_branch",
    "mr_target_branch",
    "gitlab_connection_id",
    "name",
    "tracker_project_id",
    "tracker_project_name",
    "tracker_queue",
    "reviewer",
    "yonote_project_name",
}
REQUIRED = {
    "project_id",
    "project_path",
    "gitlab_clone_url",
    "gitlab_web_url",
    "default_base_branch",
    "mr_target_branch",
    "gitlab_connection_id",
}


def require_project_admin(actor: GatewayActor, project_id: str) -> None:
    if has_scope(actor, "factory:admin"):
        return
    if not has_scope(actor, "factory:projects:write"):
        raise PermissionError("factory:admin or factory:projects:write is required")
    _require_project_access(actor, "write", project_id.strip().casefold())


def normalize_project(values: dict) -> dict:
    if not isinstance(values, dict) or set(values) - FIELDS:
        raise ValueError("unsupported Factory project fields")
    if any(
        not isinstance(value, str) or len(value) > 1000 for value in values.values()
    ):
        raise ValueError("project fields must be bounded strings")
    config = {key: value.strip() for key, value in values.items()}
    if any(not config.get(key) for key in REQUIRED):
        raise ValueError("required Factory project fields are missing")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,199}", config["project_id"]):
        raise ValueError("invalid project_id")
    path = config["project_path"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", path) or any(
        part in {".", ".."} or part.endswith(".git") for part in path.split("/")
    ):
        raise ValueError("invalid project_path")
    for key in ("default_base_branch", "mr_target_branch"):
        branch = config[key]
        if (
            not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}", branch)
            or ".." in branch
            or "//" in branch
            or branch.endswith(("/", ".", ".lock"))
        ):
            raise ValueError("invalid branch name")
    for key in ("gitlab_clone_url", "gitlab_web_url"):
        config[key] = clean_url(config[key])
    if not re.fullmatch(
        r"gitlab(?::[a-z0-9][a-z0-9_.-]{0,100})?", config["gitlab_connection_id"]
    ):
        raise ValueError("invalid GitLab connection reference")
    return config


def request_key(key: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", key):
        raise ValueError("idempotency_key is required and must be a bounded identifier")
    return key


async def upsert_project(
    *,
    actor: GatewayActor,
    config: dict,
    idempotency_key: str,
    expected_revision: int | None = None,
) -> dict:
    project_id = str(config.get("project_id") or "")
    require_project_admin(actor, project_id)
    config = normalize_project(config)
    return await _validate_and_save(
        actor, config, "upsert", idempotency_key, expected_revision=expected_revision
    )


async def validate_project(
    *, actor: GatewayActor, project_id: str, idempotency_key: str
) -> dict:
    require_project_admin(actor, project_id)
    row = storage_factory.get_project(project_id)
    if not row:
        raise KeyError("project must be registered before validation")
    return await _validate_and_save(
        actor, row["config"], "validate", idempotency_key, previous=row
    )


async def _validate_and_save(
    actor: GatewayActor,
    config: dict,
    operation: str,
    key: str,
    *,
    previous: dict | None = None,
    expected_revision: int | None = None,
) -> dict:
    if not has_scope(actor, "factory:admin"):
        for resource_type, resource in (
            ("connection", config["gitlab_connection_id"]),
            ("repository", config["gitlab_web_url"]),
        ):
            access = explain_resource_access(
                actor=actor,
                system="factory",
                action="write",
                resource=resource,
                resource_type=resource_type,
            )
            if access["decision"] != "allow" or access["reason"] != "matched_allow":
                raise PermissionError(
                    "explicit Factory connection and repository grants are required"
                )
    return await _run_validation(
        actor,
        config,
        operation,
        key,
        previous=previous,
        expected_revision=expected_revision,
    )


async def _run_validation(
    actor: GatewayActor,
    config: dict,
    operation: str,
    key: str,
    *,
    previous: dict | None = None,
    expected_revision: int | None = None,
) -> dict:
    """Persist a bounded probe after the caller authorizes its exact destination."""
    key = request_key(key)
    fingerprint = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()
    replay = storage_factory.begin_operation(
        actor.subject, operation, key, fingerprint, config["project_id"]
    )
    if replay:
        return replay
    try:
        if previous is None:
            previous = storage_factory.get_project(config["project_id"])
        if (
            expected_revision is not None
            and int((previous or {}).get("revision", 0)) != expected_revision
        ):
            raise ValueError("Factory project changed; reload before binding")
        report = await asyncio.wait_for(validate_repository(config), timeout=300)
        return storage_factory.save_project(
            config=config,
            readiness=report,
            actor=actor.subject,
            operation=operation,
            key=key,
            fingerprint=fingerprint,
            expected_revision=previous["revision"] if previous else 0,
        )
    except BaseException:
        storage_factory.fail_operation(
            actor.subject, operation, key, config["project_id"]
        )
        raise


def public_project(row: dict) -> dict:
    config = row["config"]
    readiness = dict(row.get("readiness") or {})
    gaps = list(readiness.get("readiness_gaps") or [])
    if not readiness.get("ready") and not gaps:
        gaps.append("validation_required")
    if storage_factory.list_probes(config["project_id"]):
        gaps.append("cleanup")
    checked = readiness.get("checked_at")
    stale = not checked
    if checked:
        stale = (
            datetime.now(timezone.utc) - datetime.fromisoformat(checked)
        ).total_seconds() > 300
    if stale:
        gaps.append("validation_stale")
    # Credentials may have been revoked or rotated since the last validation.
    from gateway_mcp.services.storage_service_connections import get_service_connection

    connection = get_service_connection(
        config["gitlab_connection_id"], include_payload=False
    )
    expired = bool(
        connection
        and connection.get("expires_at")
        and datetime.fromisoformat(str(connection["expires_at"]))
        <= datetime.now(timezone.utc)
    )
    if (
        not connection
        or connection.get("state") != "active"
        or expired
        or connection.get("version") != readiness.get("connection_version")
    ):
        gaps.append("authentication")
    safe = {
        key: value for key, value in config.items() if key != "gitlab_connection_id"
    }
    safe.update(
        revision=row["revision"],
        source="registered",
        gitlab_project_path=config["project_path"],
        gitlab_project=str(
            readiness.get("gitlab_project_id") or config["project_path"]
        ),
        tracker_project={
            "id": config.get("tracker_project_id", ""),
            "name": config.get("tracker_project_name", ""),
            "status": "mapped",
        },
        project_resolution={"source": "runtime_config", "queue_fallback": False},
        readiness_gaps=list(dict.fromkeys(gaps)),
        validation={
            key: value
            for key, value in readiness.items()
            if key != "connection_version"
        },
    )
    safe["validation"]["ready"] = not gaps
    safe["validation"]["readiness_gaps"] = safe["readiness_gaps"]
    return safe


async def retry_work(
    *, actor: GatewayActor, work_id: str, idempotency_key: str
) -> dict:
    work = get_work(actor, work_id, include_events=False)
    project_id = work["project_id"]
    require_project_admin(actor, project_id)
    key = request_key(idempotency_key)
    if storage_factory.retry_receipt(work_id, actor.subject, key):
        return {"work_id": work_id, "status": work["status"], "replayed": True}
    if (
        work["status"] != "blocked"
        or work["execution_mode"] != "factory"
        or work["scope_decision"] not in {"within_scope", "clarification"}
    ):
        raise ValueError("only in-scope blocked Factory work can be retried")
    row = storage_factory.get_project(project_id)
    if not row:
        return {
            "work_id": work_id,
            "status": "blocked",
            "readiness_gaps": ["project_not_registered"],
        }
    from gateway_mcp.services.factory_projects import get_factory_runtime_config

    runtime = await get_factory_runtime_config(
        actor=actor, tools_registry={}, work_id=work_id
    )
    config_gaps = [
        gap
        for gap in runtime["project"]["readiness_gaps"]
        if gap in {"reviewer", "yonote_project_name", "repository_mapping"}
    ]
    validation_key = "retry-" + hashlib.sha256(f"{work_id}:{key}".encode()).hexdigest()
    validation = await _validate_and_save(
        actor, row["config"], "retry_validate", validation_key, previous=row
    )
    report = validation["validation"]
    gaps = list(dict.fromkeys(report["readiness_gaps"] + config_gaps))
    if (
        datetime.now(timezone.utc) - datetime.fromisoformat(report["checked_at"])
    ).total_seconds() > 300:
        gaps.append("validation_stale")
    if gaps:
        return {
            "work_id": work_id,
            "status": "blocked",
            "readiness_gaps": gaps,
            "validation": {**report, "ready": False, "readiness_gaps": gaps},
        }
    return storage_factory.requeue_work(
        work_id=work_id,
        actor=actor.subject,
        key=key,
        project_id=row["project_id"],
        revision=row["revision"],
        connection_id=row["config"]["gitlab_connection_id"],
        connection_version=report["connection_version"],
    )
