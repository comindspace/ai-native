from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from gateway_mcp.services import storage_factory, storage_work
from gateway_mcp.services.factory_admin import _run_validation, public_project
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.work import _require_project_access, claim_work


def _time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _owned_lease(actor, work):
    return (
        work.get("execution_mode") == "factory"
        and work.get("status") == "running"
        and work.get("scope_decision") in {"within_scope", "clarification"}
        and work.get("claimed_by") == actor.subject
        and work.get("lease_expires_at")
        and _time(work["lease_expires_at"]) > datetime.now(timezone.utc)
    )


async def _prepare(actor, work):
    while True:
        current = storage_work.get_work_run(work["work_id"])
        if (
            not current
            or not _owned_lease(actor, current)
            or (current["lease_expires_at"] != work["lease_expires_at"])
        ):
            raise PermissionError("Factory lease changed during preflight")
        _require_project_access(actor, "write", work["project_id"])
        row = storage_factory.get_project(work["project_id"])
        if not row or work.get("project_path") != row["config"]["project_path"]:
            return None, ["repository_mapping"]
        backend = ((work.get("contract") or {}).get("metadata") or {}).get(
            "gitlab_backend", ""
        )
        base_url = row["config"]["gitlab_web_url"].removesuffix(
            "/" + row["config"]["project_path"]
        )
        if str(backend).rstrip("/") not in {"", "gitlab", base_url}:
            return None, ["repository_mapping"]
        public = public_project(row)
        if not public["readiness_gaps"]:
            return row, []
        # Only the server-registered destination is probed. No caller-supplied
        # token, URL, connection alias or elevated actor is accepted here.
        key = (
            "claim-"
            + hashlib.sha256(
                f"{work['work_id']}:{work['lease_expires_at']}:{row['revision']}".encode()
            ).hexdigest()
        )
        try:
            result = await _run_validation(
                actor, row["config"], "claim_preflight", key, previous=row
            )
        except storage_factory.ValidationInProgress:
            await asyncio.sleep(0.5)
            continue
        if not result.get("ready"):
            return None, result.get("readiness_gaps") or ["validation_failed"]
        updated = storage_factory.get_project(work["project_id"])
        if not updated or updated["revision"] != row["revision"]:
            return None, ["project_changed"]
        gaps = public_project(updated)["readiness_gaps"]
        return updated, gaps


async def _admit(actor, work):
    while True:
        row, gaps = await _prepare(actor, work)
        if gaps:
            return storage_work.block_claim_preflight(work, gaps)
        _require_project_access(actor, "write", work["project_id"])
        try:
            return storage_factory.admit_work_lease(work=work, project=row)
        except storage_factory.ValidationInProgress:
            await asyncio.sleep(0.5)


async def claim_with_preflight(*, actor: GatewayActor, **kwargs):
    if not has_scope(actor, "factory:claim"):
        raise PermissionError("factory:claim is required")
    work = claim_work(actor=actor, **kwargs)
    if not work:
        return work
    try:
        if not storage_factory.get_project(work["project_id"]):
            return work
        return await asyncio.wait_for(_admit(actor, work), timeout=300)
    except asyncio.CancelledError:
        storage_work.block_claim_preflight(work, ["validation_interrupted"])
        raise
    except Exception:  # noqa: BLE001 - fail closed without echoing upstream secrets
        gaps = ["preflight_failed"]
    return storage_work.block_claim_preflight(work, gaps)


def lease_readiness_valid(work: dict, row: dict) -> bool:
    """A recorded admission outlives diagnostic TTL, never the lease or config."""
    if (
        not work
        or work.get("status") != "running"
        or work.get("execution_mode") != "factory"
    ):
        return False
    if work.get("scope_decision") not in {"within_scope", "clarification"}:
        return False
    if work.get("project_path") != row["config"]["project_path"]:
        return False
    event = storage_work.latest_factory_preflight(work["work_id"])
    if not event or event["actor_subject"] != work.get("claimed_by"):
        return False
    payload = event.get("payload") or {}
    report = row.get("readiness") or {}
    try:
        now = datetime.now(timezone.utc)
        return bool(
            payload.get("ready") is True
            and payload.get("project_revision") == row["revision"]
            and payload.get("connection_version") == report.get("connection_version")
            and _time(payload["lease_expires_at"]) == _time(work["lease_expires_at"])
            and _time(work["lease_expires_at"]) > now
            and _time(payload["checked_at"]) <= _time(event["occurred_at"]) <= now
            and (
                _time(event["occurred_at"]) - _time(payload["checked_at"])
            ).total_seconds()
            <= 300
        )
    except (ValueError, TypeError, KeyError):
        return False
