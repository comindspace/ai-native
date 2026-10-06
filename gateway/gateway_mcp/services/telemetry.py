import json
import uuid
from typing import Any

from gateway_mcp.services.observability import audit_event, observe_skill_event
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.storage import (
    assistant_skill_stats,
    assistant_usage_summary,
    insert_assistant_skill_event,
    insert_assistant_usage_event,
    open_assistant_skill_events,
    upsert_assistant_session,
)


VALID_EVENTS = {"started", "completed", "failed"}
PRIVATE_METADATA_KEYS = (
    "argument",
    "authorization",
    "body",
    "content",
    "cookie",
    "credential",
    "connection_id",
    "connection_handle",
    "input",
    "message",
    "output",
    "password",
    "prompt",
    "request",
    "response",
    "result",
    "secret",
    "text",
    "token",
    "transcript",
)
VALID_USAGE_QUALITIES = {"actual", "agent_local_estimate", "estimated", "billing_import"}
VALID_USAGE_CLASSES = {"", "S", "M", "L", "XL"}


def record_skill_event(
    *,
    actor: GatewayActor,
    event_type: str,
    agent: str,
    skill_id: str,
    skill_pack: str = "",
    skill_version: str = "",
    correlation_id: str = "",
    session_id: str = "",
    project: str = "",
    client: str = "",
    status: str = "",
    duration_ms: int = 0,
    mcp_routes_json: str = "[]",
    missing_scopes_json: str = "[]",
    metadata_json: str = "{}",
    error_class: str = "",
) -> dict[str, Any]:
    normalized_event = _normalize_event(event_type)
    normalized_status = _normalize_status(normalized_event, status)
    normalized_agent = _clean(agent or "unknown")
    normalized_skill_id, normalized_skill_pack = _normalize_skill_identity(
        skill_id, skill_pack
    )
    if not normalized_skill_id:
        raise ValueError("skill_id is required")

    correlation = _clean(correlation_id) or str(uuid.uuid4())
    routes = _json_list(mcp_routes_json)
    missing_scopes = _json_list(missing_scopes_json)
    metadata = _json_dict(metadata_json)
    duration = int(duration_ms) if duration_ms and int(duration_ms) > 0 else None

    if session_id:
        upsert_assistant_session(
            session_id=_clean(session_id),
            actor_subject=actor.subject,
            agent=normalized_agent,
            client=_clean(client),
            project=_clean(project),
            metadata=_safe_metadata(metadata),
        )

    row = insert_assistant_skill_event(
        event_type=normalized_event,
        correlation_id=correlation,
        session_id=_clean(session_id),
        actor_subject=actor.subject,
        agent=normalized_agent,
        skill_id=normalized_skill_id,
        skill_pack=normalized_skill_pack,
        skill_version=_clean(skill_version),
        project=_clean(project),
        client=_clean(client),
        status=normalized_status,
        duration_ms=duration,
        mcp_routes=routes,
        missing_scopes=missing_scopes,
        metadata=_safe_metadata(metadata),
        error_class=_clean(error_class),
    )
    inserted = row is None or bool(row.get("inserted", True))
    if inserted:
        observe_skill_event(
            event_type=normalized_event,
            agent=normalized_agent,
            skill_id=normalized_skill_id,
            skill_pack=normalized_skill_pack,
            status=normalized_status,
            duration_ms=duration,
        )

        audit_event(
            event="assistant_skill_event",
            actor=actor,
            tool=f"skill:{normalized_skill_id}",
            system="assistant",
            decision="allow",
            status=normalized_status,
            scope="telemetry:write",
            arguments={
                "event_type": normalized_event,
                "agent": normalized_agent,
                "skill_id": normalized_skill_id,
                "skill_pack": normalized_skill_pack,
                "skill_version": _clean(skill_version),
                "correlation_id": correlation,
                "session_id": _clean(session_id),
                "project": _clean(project),
                "client": _clean(client),
                "duration_ms": duration,
                "mcp_routes": routes,
                "missing_scopes": missing_scopes,
                "metadata": _safe_metadata(metadata),
            },
            error=_clean(error_class),
        )

    return {
        "ok": True,
        "stored": bool(row),
        "duplicate": bool(row) and not inserted,
        "event": {
            "event_type": normalized_event,
            "correlation_id": correlation,
            "session_id": _clean(session_id),
            "agent": normalized_agent,
            "skill_id": normalized_skill_id,
            "skill_pack": normalized_skill_pack,
            "status": normalized_status,
            "duration_ms": duration,
        },
    }


def finish_session_skills(
    *,
    actor: GatewayActor,
    agent: str,
    session_id: str,
    outcome: str = "completed",
    error_class: str = "",
) -> dict[str, Any]:
    normalized_session = _clean(session_id)
    if not normalized_session:
        raise ValueError("session_id is required")
    normalized_agent = _clean(agent or "unknown")
    normalized_outcome = _normalize_event(outcome)
    if normalized_outcome == "started":
        raise ValueError("session outcome must be completed or failed")

    open_events = open_assistant_skill_events(
        actor_subject=actor.subject,
        session_id=normalized_session,
        agent=normalized_agent,
    )
    finished: list[dict[str, Any]] = []
    for event in open_events:
        result = record_skill_event(
            actor=actor,
            event_type=normalized_outcome,
            agent=str(event.get("agent") or normalized_agent),
            skill_id=str(event.get("skill_id") or ""),
            skill_pack=str(event.get("skill_pack") or ""),
            skill_version=str(event.get("skill_version") or ""),
            correlation_id=str(event.get("correlation_id") or ""),
            session_id=normalized_session,
            project=str(event.get("project") or ""),
            client=str(event.get("client") or ""),
            duration_ms=int(event.get("elapsed_ms") or 0),
            mcp_routes_json=json.dumps(event.get("mcp_routes") or []),
            missing_scopes_json=json.dumps(event.get("missing_scopes") or []),
            metadata_json=json.dumps(event.get("metadata") or {}),
            error_class=error_class if normalized_outcome == "failed" else "",
        )
        finished.append(result["event"])
    return {
        "ok": True,
        "session_id": normalized_session,
        "outcome": normalized_outcome,
        "finished_count": len(finished),
        "events": finished,
    }


def skill_stats(
    *,
    days: int,
    limit: int,
    agent: str = "",
    skill_id: str = "",
    skill_pack: str = "",
    skill_version: str = "",
    project: str = "",
    actor_subject: str = "",
) -> dict[str, Any]:
    normalized_skill_id, normalized_skill_pack = _normalize_skill_identity(
        skill_id, skill_pack
    )
    rows = assistant_skill_stats(
        days=days,
        limit=limit,
        agent=_clean(agent),
        skill_id=normalized_skill_id,
        skill_pack=normalized_skill_pack,
        skill_version=_clean(skill_version),
        project=_clean(project),
        actor_subject=_clean(actor_subject),
    )
    return {"ok": True, "days": max(1, min(int(days or 30), 365)), "count": len(rows), "skills": rows}


def record_usage_report(
    *,
    actor: GatewayActor,
    agent: str,
    source: str = "mcp",
    source_quality: str = "estimated",
    event_name: str = "usage_report",
    provider: str = "",
    model: str = "",
    session_id: str = "",
    correlation_id: str = "",
    skill_id: str = "",
    skill_pack: str = "",
    project: str = "",
    client: str = "",
    cwd: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    reasoning_tokens: int = 0,
    duration_ms: int = 0,
    tool_use_count: int = 0,
    usage_class: str = "",
    estimated_cost_usd: float = 0,
    metadata_json: str = "{}",
    raw_event_json: str = "{}",
) -> dict[str, Any]:
    normalized_agent = _clean(agent or "unknown")
    normalized_quality = _normalize_usage_quality(source_quality)
    normalized_usage_class = _normalize_usage_class(usage_class)
    metadata = _json_dict(metadata_json)
    raw_event = _json_dict(raw_event_json)
    input_value = _positive_int(input_tokens)
    output_value = _positive_int(output_tokens)
    total_value = _positive_int(total_tokens) or _sum_tokens(input_value, output_value)
    row = insert_assistant_usage_event(
        event_name=_clean(event_name or "usage_report"),
        source=_clean(source or "mcp"),
        source_quality=normalized_quality,
        actor_subject=actor.subject,
        agent=normalized_agent,
        provider=_clean(provider),
        model=_clean(model),
        session_id=_clean(session_id),
        correlation_id=_clean(correlation_id),
        skill_id=_clean(skill_id),
        skill_pack=_clean(skill_pack),
        project=_clean(project),
        client=_clean(client),
        cwd=_clean(cwd),
        input_tokens=input_value,
        output_tokens=output_value,
        total_tokens=total_value,
        cache_creation_input_tokens=_positive_int(cache_creation_input_tokens),
        cache_read_input_tokens=_positive_int(cache_read_input_tokens),
        reasoning_tokens=_positive_int(reasoning_tokens),
        duration_ms=_positive_int(duration_ms),
        tool_use_count=_positive_int(tool_use_count),
        usage_class=normalized_usage_class,
        estimated_cost_usd=_positive_float(estimated_cost_usd),
        metadata=_safe_metadata(metadata),
        raw_event=_safe_metadata(raw_event),
    )

    audit_event(
        event="assistant_usage_event",
        actor=actor,
        tool="gateway_telemetry_usage_report",
        system="telemetry",
        decision="allow",
        status="ok",
        scope="telemetry:write",
        arguments={
            "agent": normalized_agent,
            "source": _clean(source or "mcp"),
            "source_quality": normalized_quality,
            "event_name": _clean(event_name or "usage_report"),
            "provider": _clean(provider),
            "model": _clean(model),
            "session_id": _clean(session_id),
            "skill_id": _clean(skill_id),
            "project": _clean(project),
            "input_tokens": input_value,
            "output_tokens": output_value,
            "total_tokens": total_value,
            "usage_class": normalized_usage_class,
        },
    )

    return {
        "ok": True,
        "stored": bool(row),
        "usage": {
            "agent": normalized_agent,
            "source": _clean(source or "mcp"),
            "source_quality": normalized_quality,
            "event_name": _clean(event_name or "usage_report"),
            "provider": _clean(provider),
            "model": _clean(model),
            "session_id": _clean(session_id),
            "skill_id": _clean(skill_id),
            "project": _clean(project),
            "input_tokens": input_value,
            "output_tokens": output_value,
            "total_tokens": total_value,
            "usage_class": normalized_usage_class,
        },
    }


def usage_summary(
    *,
    days: int,
    limit: int,
    agent: str = "",
    skill_id: str = "",
    project: str = "",
    source_quality: str = "",
) -> dict[str, Any]:
    quality = _normalize_usage_quality(source_quality) if _clean(source_quality) else ""
    rows = assistant_usage_summary(
        days=days,
        limit=limit,
        agent=_clean(agent),
        skill_id=_clean(skill_id),
        project=_clean(project),
        source_quality=quality,
    )
    return {"ok": True, "days": max(1, min(int(days or 30), 365)), "count": len(rows), "usage": rows}


def _normalize_event(event_type: str) -> str:
    value = _clean(event_type).casefold()
    if value not in VALID_EVENTS:
        raise ValueError(f"unknown skill telemetry event_type: {event_type}")
    return value


def _normalize_status(event_type: str, status: str) -> str:
    value = _clean(status).casefold()
    if value:
        return value
    if event_type == "failed":
        return "error"
    if event_type == "completed":
        return "ok"
    return "started"


def _clean(value: Any) -> str:
    return str(value or "").strip()[:256]


def _normalize_skill_identity(skill_id: Any, skill_pack: Any) -> tuple[str, str]:
    raw_skill_id = _clean(skill_id)
    normalized_pack = _clean(skill_pack)
    if ":" not in raw_skill_id:
        return raw_skill_id, normalized_pack
    inferred_pack, normalized_skill_id = raw_skill_id.rsplit(":", 1)
    return normalized_skill_id, normalized_pack or inferred_pack


def _json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except Exception as exc:
        raise ValueError("expected JSON array") from exc
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return [_clean(item) for item in value if _clean(item)]


def _json_dict(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except Exception as exc:
        raise ValueError("expected JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _normalize_usage_quality(value: str) -> str:
    normalized = _clean(value or "estimated").casefold()
    if normalized not in VALID_USAGE_QUALITIES:
        raise ValueError(f"unknown usage source_quality: {value}")
    return normalized


def _normalize_usage_class(value: str) -> str:
    normalized = _clean(value).upper()
    if normalized not in VALID_USAGE_CLASSES:
        raise ValueError("usage_class must be one of S, M, L, XL")
    return normalized


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _sum_tokens(input_tokens: int | None, output_tokens: int | None) -> int | None:
    total = int(input_tokens or 0) + int(output_tokens or 0)
    return total if total > 0 else None


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        clean_key = _clean(key)
        if not clean_key:
            continue
        if any(
            sensitive in clean_key.casefold()
            for sensitive in PRIVATE_METADATA_KEYS
        ):
            safe[clean_key] = "[redacted]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[clean_key] = value if not isinstance(value, str) else value[:512]
        elif isinstance(value, list):
            safe[clean_key] = [_clean(item) for item in value[:25]]
        else:
            safe[clean_key] = _clean(value)
    return safe
