from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from gateway_mcp.services import storage_work
from gateway_mcp.services.access_policy import explain_resource_access
from gateway_mcp.services.company_search import search_company_index
from gateway_mcp.services.policy import GatewayActor, has_scope

SDD_LEVELS = {"S0", "S1", "S2", "S3"}
EXECUTION_MODES = {"local", "factory"}
SCOPE_DECISIONS = {
    "within_scope",
    "clarification",
    "scope_change",
    "new_scope_candidate",
    "unresolved",
}
EVENT_TYPES = {
    "context_resolved",
    "context_usage",
    "implementation_started",
    "quality_gate_passed",
    "quality_gate_failed",
    "mr_created",
    "review_started",
    "correction_requested",
    "blocked",
    "resumed",
    "note",
}
ARTIFACT_PHASES = {
    "planning",
    "implementation",
    "verification",
    "review",
    "delivery",
    "production_feedback",
}
ARTIFACT_PHASE_TRANSITIONS: dict[str, set[str]] = {
    "": {"planning"},
    "planning": {"implementation"},
    "implementation": {"verification"},
    "verification": {"review"},
    "review": {"implementation", "delivery"},
    "delivery": {"production_feedback"},
    "production_feedback": {"production_feedback"},
}
ARTIFACT_CHECK_STATUSES = {"pass", "fail", "skip", "not_applicable"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TRACKER_CLOSE_CONDITIONS = {
    "acceptance_tests_passed",
    "deployed_and_verified",
    "manual",
    "not_applicable",
}
DEFAULT_TRACKER_EVIDENCE = [
    "successful_pipeline",
    "merge_commit",
    "deployment_ref",
    "acceptance_test_result",
]


def intake_work(
    *,
    actor: GatewayActor,
    project_id: str,
    source_type: str,
    intent_summary: str,
    execution_mode: str,
    sdd_level: str,
    scope_decision: str,
    project_path: str = "",
    scope_id: str = "",
    source_ref: str = "",
    source_refs: list[dict[str, Any]] | None = None,
    acceptance_criteria: list[str] | None = None,
    quality_gates: list[str] | None = None,
    risk_level: str = "normal",
    work_kind: str = "code_change",
    priority: int = 0,
    idempotency_key: str = "",
    contract_metadata: dict[str, Any] | None = None,
    tracker_completion_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_id = _required(project_id, "project_id", 200)
    _require_project_access(actor, "write", project_id)
    source_type = _required(source_type, "source_type", 80)
    intent_summary = _required(intent_summary, "intent_summary", 1000)
    execution_mode = _choice(execution_mode, EXECUTION_MODES, "execution_mode")
    sdd_level = _choice(sdd_level.upper(), SDD_LEVELS, "sdd_level")
    scope_decision = _choice(scope_decision, SCOPE_DECISIONS, "scope_decision")
    if scope_decision in {"within_scope", "clarification"} and not scope_id:
        raise ValueError("scope_id is required for executable in-scope work")
    acceptance = _strings(
        acceptance_criteria or [], "acceptance_criteria", required=True
    )
    gates = _strings(quality_gates or [], "quality_gates", required=True)
    now = datetime.now(timezone.utc)
    work_id = f"work-{uuid4()}"
    local = execution_mode == "local"
    normalized_priority = _work_priority(priority)
    tracker_policy = _tracker_completion_policy(tracker_completion_policy or {})
    contract = {
        "schema_version": "1.1",
        "project_id": project_id,
        "project_path": _text(project_path, 300),
        "scope_id": _text(scope_id, 200),
        "scope_decision": scope_decision,
        "intent": intent_summary,
        "acceptance_criteria": acceptance,
        "quality_gates": gates,
        "sdd_level": sdd_level,
        "execution_mode": execution_mode,
        "priority": normalized_priority,
        "risk_level": _choice(
            risk_level, {"low", "normal", "high", "critical"}, "risk_level"
        ),
        "allowed_actions": [
            "edit",
            "test",
            "commit",
            "push_branch",
            "create_mr",
            "comment",
        ],
        "forbidden_actions": [
            "merge",
            "deploy",
            "change_secrets",
            "change_permissions",
            "destructive_migration",
        ],
        "tracker_completion_policy": tracker_policy,
        "metadata": _safe_metadata(contract_metadata or {}),
    }
    row = storage_work.insert_work_run(
        {
            "work_id": work_id,
            "idempotency_key": _text(idempotency_key, 200),
            "actor_subject": actor.subject,
            "project_id": project_id,
            "project_path": _text(project_path, 300),
            "scope_id": _text(scope_id, 200),
            "scope_decision": scope_decision,
            "source_type": source_type,
            "source_ref": _text(source_ref, 1000),
            "intent_summary": intent_summary,
            "work_kind": _text(work_kind, 80) or "code_change",
            "sdd_level": sdd_level,
            "execution_mode": execution_mode,
            "risk_level": contract["risk_level"],
            "status": "running" if local else "queued",
            "priority": normalized_priority,
            "source_refs": _safe_refs(source_refs or []),
            "acceptance_criteria": acceptance,
            "quality_gates": gates,
            "contract": contract,
            "claimed_by": actor.subject if local else "",
            "started_at": now if local else None,
        }
    )
    inserted = bool(row.pop("_inserted", True))
    if inserted:
        storage_work.insert_work_event(
            work_id=row["work_id"],
            actor_subject=actor.subject,
            event_type="intake_created",
            payload={
                "execution_mode": execution_mode,
                "sdd_level": sdd_level,
                "scope_decision": scope_decision,
                "tracker_issue_key": tracker_policy["issue_key"],
                "tracker_auto_close": False,
            },
        )
    return row


def get_work(
    actor: GatewayActor, work_id: str, *, include_events: bool = True
) -> dict[str, Any]:
    row = storage_work.get_work_run(_required(work_id, "work_id", 100))
    if not row:
        raise KeyError(f"unknown work_id: {work_id}")
    _require_project_access(actor, "read", str(row.get("project_id") or ""))
    if include_events:
        row["events"] = storage_work.list_work_events(work_id)
    return row


def search_work(*, actor: GatewayActor, **filters: Any) -> list[dict[str, Any]]:
    _require_project_access(actor, "read", str(filters.get("project_id") or "*"))
    return storage_work.search_work_runs(**filters)


def claim_work(
    *,
    actor: GatewayActor,
    work_id: str = "",
    project_id: str = "",
    lease_seconds: int = 1800,
) -> dict[str, Any] | None:
    if work_id:
        candidate = storage_work.get_work_run(_text(work_id, 100))
        if not candidate:
            return None
        _require_project_access(actor, "write", str(candidate.get("project_id") or ""))
    else:
        if not project_id:
            raise ValueError("work_id or project_id is required")
        _require_project_access(actor, "write", _text(project_id, 200))
    row = storage_work.claim_work_run(
        claimed_by=actor.subject,
        work_id=_text(work_id, 100),
        project_id=_text(project_id, 200),
        lease_seconds=lease_seconds,
    )
    return row


def record_event(
    *, actor: GatewayActor, work_id: str, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    row = get_work(actor, work_id, include_events=False)
    _require_project_access(actor, "write", str(row.get("project_id") or ""))
    event_type = _choice(event_type, EVENT_TYPES, "event_type")
    safe_payload = _safe_metadata(payload)
    updates: dict[str, Any] = {}
    expected_statuses: set[str] = set()
    if event_type == "mr_created":
        updates["status"] = "review"
        expected_statuses = {"running"}
    elif event_type == "correction_requested":
        updates["status"] = "running"
        updates["correction_rounds"] = int(row.get("correction_rounds") or 0) + 1
        expected_statuses = {"review"}
    elif event_type == "blocked" or event_type == "quality_gate_failed":
        updates["status"] = "blocked"
        expected_statuses = {"running", "review"}
    elif event_type == "resumed":
        factory_work = str(row.get("execution_mode") or "").casefold() == "factory"
        if factory_work:
            from gateway_mcp.services import storage_factory

            if storage_factory.get_project(str(row.get("project_id") or "")):
                raise ValueError("registered Factory projects require gateway_work_retry")
        updates["status"] = "queued" if factory_work else "running"
        if factory_work:
            updates["claimed_by"] = ""
            updates["lease_expires_at"] = None
        expected_statuses = {"blocked"}
    if updates:
        transitioned, event = storage_work.transition_work_run(
            work_id=work_id,
            expected_statuses=expected_statuses,
            values=updates,
            actor_subject=actor.subject,
            event_type=event_type,
            event_payload=safe_payload,
        )
        if not transitioned or not event:
            raise ValueError(
                f"event {event_type} is invalid for work status {row.get('status') or '<empty>'}"
            )
        return {"work": transitioned, "event": event}
    event = storage_work.insert_work_event(
        work_id=work_id,
        actor_subject=actor.subject,
        event_type=event_type,
        payload=safe_payload,
    )
    return {"work": row, "event": event}


def record_artifact_manifest(
    *,
    actor: GatewayActor,
    work_id: str,
    phase: str,
    refs: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    producer: str,
    previous_digest: str = "",
) -> dict[str, Any]:
    """Append one metadata-only phase record to a hash-linked artifact chain."""

    work = get_work(actor, work_id, include_events=False)
    _require_project_access(actor, "write", str(work.get("project_id") or ""))
    phase = _choice(phase, ARTIFACT_PHASES, "phase")
    producer = _required(producer, "producer", 120)
    safe_refs = _safe_refs(refs)
    if not safe_refs or any(
        not ref.get("type") or not ref.get("uri") for ref in safe_refs
    ):
        raise ValueError("artifact refs must contain at least one type and uri")
    safe_checks = _safe_artifact_checks(checks)
    previous_digest = _text(previous_digest, 64).casefold()
    if previous_digest and not SHA256_PATTERN.fullmatch(previous_digest):
        raise ValueError("previous_digest must be a lowercase SHA-256 digest")

    def next_manifest(latest: dict[str, Any]) -> dict[str, Any]:
        expected_previous = str(latest.get("digest") or "")
        if expected_previous and not SHA256_PATTERN.fullmatch(expected_previous):
            raise RuntimeError("stored artifact manifest has an invalid digest")
        if expected_previous:
            if previous_digest != expected_previous:
                raise ValueError(
                    "previous_digest does not match the latest artifact manifest"
                )
        elif previous_digest:
            raise ValueError(
                "previous_digest must be empty for the first artifact manifest"
            )

        previous_phase = str(latest.get("phase") or "")
        if phase not in ARTIFACT_PHASE_TRANSITIONS.get(previous_phase, set()):
            raise ValueError(
                f"invalid artifact phase transition: {previous_phase or '<start>'} -> {phase}"
            )
        manifest = {
            "schema_version": "1.0",
            "work_id": work_id,
            "sequence": int(latest.get("sequence") or 0) + 1,
            "phase": phase,
            "previous_digest": expected_previous,
            "producer": producer,
            "refs": safe_refs,
            "checks": safe_checks,
        }
        manifest["digest"] = _artifact_digest(manifest)
        return manifest

    locked_work, event = storage_work.append_work_event_locked(
        work_id=work_id,
        actor_subject=actor.subject,
        event_type="artifact_manifest",
        payload_factory=next_manifest,
    )
    return {
        "work": locked_work,
        "event": event,
    }


def set_tracker_completion_policy(
    *, actor: GatewayActor, work_id: str, policy: dict[str, Any]
) -> dict[str, Any]:
    existing = get_work(actor, work_id, include_events=False)
    _require_project_access(actor, "write", str(existing.get("project_id") or ""))
    contract = dict(existing.get("contract") or {})
    tracker_policy = _tracker_completion_policy(policy)
    contract["schema_version"] = "1.1"
    contract["tracker_completion_policy"] = tracker_policy
    row = storage_work.update_work_run(work_id, {"contract": contract}) or existing
    storage_work.insert_work_event(
        work_id=work_id,
        actor_subject=actor.subject,
        event_type="tracker_policy_updated",
        payload={
            "issue_key": tracker_policy["issue_key"],
            "close_when": tracker_policy["close_when"],
            "auto_close": False,
        },
    )
    return row


def complete_work(
    *,
    actor: GatewayActor,
    work_id: str,
    success: bool,
    result_refs: list[dict[str, Any]],
    evidence_state: str,
    admin_actions: int = 0,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = get_work(actor, work_id, include_events=False)
    _require_project_access(actor, "write", str(existing.get("project_id") or ""))
    now = datetime.now(timezone.utc)
    safe_metrics = _safe_metrics(metrics or {})
    safe_metrics.update(
        {
            "evidence_state": _choice(
                evidence_state,
                {"complete", "partial", "missing", "not_applicable"},
                "evidence_state",
            ),
            "admin_actions": max(0, min(int(admin_actions), 1000)),
        }
    )
    status = str(existing.get("status") or "")
    if success and status in {"completed", "accepted"}:
        return existing
    if not success and status == "blocked":
        return existing
    if status not in {"running", "review"}:
        raise ValueError(f"work cannot be completed from status {status or '<empty>'}")
    final_status = "completed" if success else "blocked"
    row, _event = storage_work.transition_work_run(
        work_id=work_id,
        expected_statuses={"running", "review"},
        values={
            "status": final_status,
            "result_refs": _safe_refs(result_refs),
            "metrics": safe_metrics,
            "first_verified_at": (existing.get("first_verified_at") or now)
            if success
            else None,
            "completed_at": existing.get("completed_at") or now,
            "lease_expires_at": None,
        },
        actor_subject=actor.subject,
        event_type="completed" if success else "failed",
        event_payload={"evidence_state": safe_metrics["evidence_state"]},
    )
    if not row:
        raise ValueError("work status changed during completion")
    return row or {}


def accept_work(
    *, actor: GatewayActor, work_id: str, accepted: bool, decision_ref: str = ""
) -> dict[str, Any]:
    existing = get_work(actor, work_id, include_events=False)
    _require_project_access(actor, "write", str(existing.get("project_id") or ""))
    status = str(existing.get("status") or "")
    if accepted and status == "accepted":
        return existing
    if not accepted and status == "running":
        return existing
    if accepted:
        if status != "completed" or not existing.get("first_verified_at"):
            raise ValueError(
                "work must be completed with verification evidence before acceptance"
            )
        expected_statuses = {"completed"}
    else:
        if status not in {"completed", "review"}:
            raise ValueError(
                f"work cannot request changes from status {status or '<empty>'}"
            )
        expected_statuses = {"completed", "review"}
    now = datetime.now(timezone.utc)
    accepted_at = (existing.get("accepted_at") or now) if accepted else None
    row, _event = storage_work.transition_work_run(
        work_id=work_id,
        expected_statuses=expected_statuses,
        values={
            "status": "accepted" if accepted else "running",
            "accepted_at": accepted_at,
        },
        actor_subject=actor.subject,
        event_type="accepted" if accepted else "changes_requested",
        event_payload={
            "decision_ref": _text(decision_ref, 1000),
            "tracker_action": "none",
            "tracker_reason": "Work acceptance does not close or transition Tracker issues",
        },
    )
    if not row:
        raise ValueError("work status changed during acceptance")
    return row or {}


async def resolve_project_scope(
    *,
    project_id: str,
    signal_summary: str,
    scope_id: str,
    tools_registry: dict[str, Any],
    limit: int = 5,
) -> dict[str, Any]:
    project_id = _required(project_id, "project_id", 200)
    signal_summary = _required(signal_summary, "signal_summary", 500)
    candidates = await search_company_index(
        query=f"{project_id} {signal_summary}",
        kind="projects",
        limit=max(1, min(int(limit), 10)),
        tools_registry=tools_registry,
    )
    return {
        "project_id": project_id,
        "requested_scope_id": _text(scope_id, 200),
        "decision": "scope_ref_provided" if scope_id else "needs_agent_classification",
        "candidates": candidates,
        "rule": "Only within_scope or clarification may execute automatically; scope changes require a project decision.",
    }


def metrics(
    *, actor: GatewayActor, project_id: str = "", days: int = 30
) -> list[dict[str, Any]]:
    _require_project_access(actor, "read", _text(project_id, 200) or "*")
    return storage_work.work_metrics(project_id=_text(project_id, 200), days=days)


def _require_project_access(actor: GatewayActor, action: str, project_id: str) -> None:
    if has_scope(actor, "*"):
        return
    explanation = explain_resource_access(
        actor=actor,
        system="factory",
        action=action,
        resource=project_id or "*",
        resource_type="project",
    )
    if explanation["decision"] != "allow":
        raise PermissionError(
            f"resource access denied: factory:{action} project {project_id or '*'}"
        )


def _required(value: Any, name: str, limit: int) -> str:
    cleaned = _text(value, limit)
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _choice(value: str, choices: set[str], name: str) -> str:
    cleaned = _text(value, 100)
    if cleaned not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return cleaned


def _strings(values: list[Any], name: str, *, required: bool = False) -> list[str]:
    result = [_text(value, 500) for value in values[:50] if _text(value, 500)]
    if required and not result:
        raise ValueError(f"{name} must contain at least one item")
    return result


def _safe_refs(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in values[:50]:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "type": _text(item.get("type") or item.get("ref_type"), 80),
                "uri": _text(
                    item.get("uri") or item.get("url") or item.get("ref"), 1000
                ),
                "title": _text(
                    item.get("title") or item.get("name") or item.get("label"), 300
                ),
            }
        )
    return refs


def _safe_artifact_checks(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for item in values[:50]:
        if not isinstance(item, dict):
            continue
        name = _required(item.get("name"), "artifact check name", 120)
        status = _choice(
            str(item.get("status") or ""),
            ARTIFACT_CHECK_STATUSES,
            "artifact check status",
        )
        checks.append(
            {
                "name": name,
                "status": status,
                "evidence_ref": _text(item.get("evidence_ref"), 1000),
            }
        )
    return checks


def _artifact_digest(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_metadata(values: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    if depth >= 8:
        return {"truncated": True}
    safe: dict[str, Any] = {}
    for raw_key, value in list(values.items())[:50]:
        key = _text(raw_key, 80)
        if not key:
            continue
        if any(
            part in key.casefold()
            for part in (
                "token",
                "secret",
                "password",
                "cookie",
                "authorization",
                "prompt",
                "content",
                "credential",
                "connection_id",
                "connection_handle",
            )
        ):
            safe[key] = "[redacted]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = _text(value, 500) if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[key] = _safe_metadata_list(value, depth + 1)
        elif isinstance(value, dict):
            safe[key] = _safe_metadata(value, depth=depth + 1)
        else:
            safe[key] = _text(value, 500)
    return safe


def _safe_metadata_list(values: list[Any], depth: int) -> list[Any]:
    if depth >= 8:
        return ["[truncated]"]
    return [
        _safe_metadata(item, depth=depth + 1) if isinstance(item, dict)
        else _safe_metadata_list(item, depth + 1) if isinstance(item, list)
        else _text(item, 200)
        for item in values[:25]
    ]


def _tracker_completion_policy(values: dict[str, Any]) -> dict[str, Any]:
    auto_close = values.get("auto_close", False)
    if not isinstance(auto_close, bool):
        raise TypeError("tracker completion policy auto_close must be a boolean")
    if auto_close:
        raise ValueError("tracker completion policy auto_close must remain false")

    close_when = _text(values.get("close_when") or "acceptance_tests_passed", 100)
    if close_when not in TRACKER_CLOSE_CONDITIONS:
        raise ValueError(
            "tracker completion policy close_when must be one of: "
            + ", ".join(sorted(TRACKER_CLOSE_CONDITIONS))
        )

    raw_evidence = values.get("required_evidence", DEFAULT_TRACKER_EVIDENCE)
    if not isinstance(raw_evidence, list):
        raise TypeError("tracker completion policy required_evidence must be an array")

    return {
        "issue_key": _text(values.get("issue_key"), 100),
        "on_work_accept": _text(values.get("on_work_accept") or "ready_for_merge", 100),
        "on_merge": _text(values.get("on_merge") or "ready_for_test", 100),
        "on_deploy": _text(values.get("on_deploy") or "testing", 100),
        "close_when": close_when,
        "required_evidence": _strings(raw_evidence, "required_evidence"),
        "auto_close": False,
    }


def _safe_metrics(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "duration_seconds",
        "implementation_seconds",
        "verification_seconds",
        "review_seconds",
        "input_tokens",
        "output_tokens",
        "estimated_cost",
        "tests_passed",
        "tests_failed",
    }
    return {
        key: value
        for key, value in values.items()
        if key in allowed and isinstance(value, (int, float, bool))
    }


def _work_priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("priority must be an integer")
    return max(-100, min(value, 100))
