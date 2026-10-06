import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, generate_latest

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.storage import append_audit_event

LOGGER = logging.getLogger("gateway_mcp")

TOOL_CALLS_TOTAL = Counter(
    "gateway_mcp_tool_calls_total",
    "Gateway MCP tool calls.",
    ["tool", "system", "status", "decision"],
)
TOOL_LATENCY_SECONDS = Histogram(
    "gateway_mcp_tool_latency_seconds",
    "Gateway MCP tool latency in seconds.",
    ["tool", "system"],
)
AUTH_FAILURES_TOTAL = Counter(
    "gateway_mcp_auth_failures_total",
    "Gateway MCP auth failures.",
    ["reason"],
)
POLICY_DENIES_TOTAL = Counter(
    "gateway_mcp_policy_denies_total",
    "Gateway MCP policy denials.",
    ["tool", "scope", "reason"],
)
UPSTREAM_ERRORS_TOTAL = Counter(
    "gateway_mcp_upstream_errors_total",
    "Gateway MCP upstream errors.",
    ["system", "error_class"],
)
MEMORY_EVENTS_TOTAL = Counter(
    "gateway_mcp_memory_events_total",
    "Gateway MCP memory events.",
    ["operation", "tier", "scope", "status"],
)
MEMORY_SEARCH_RESULTS = Histogram(
    "gateway_mcp_memory_search_results",
    "Gateway MCP memory search result counts.",
    ["operation"],
    buckets=(0, 1, 2, 5, 10, 25, 50),
)
ASSISTANT_SKILL_EVENTS_TOTAL = Counter(
    "gateway_mcp_assistant_skill_events_total",
    "Assistant skill lifecycle events reported by agents.",
    ["event_type", "agent", "skill_id", "skill_pack", "status"],
)
ASSISTANT_SKILL_DURATION_SECONDS = Histogram(
    "gateway_mcp_assistant_skill_duration_seconds",
    "Assistant skill execution duration in seconds.",
    ["agent", "skill_id", "skill_pack"],
)
PRIVACY_ENTITIES_TOTAL = Counter(
    "gateway_mcp_privacy_entities_total",
    "Sensitive entities handled by the Gateway privacy boundary.",
    ["surface", "entity_type", "action"],
)
LLM_PROXY_REQUESTS_TOTAL = Counter(
    "gateway_mcp_llm_proxy_requests_total",
    "Requests handled by the privacy-preserving LLM proxy.",
    ["api", "status"],
)
LLM_PROXY_LATENCY_SECONDS = Histogram(
    "gateway_mcp_llm_proxy_latency_seconds",
    "Buffered external LLM request latency in seconds.",
    ["api"],
)
ACTIVE_SESSIONS = Gauge(
    "gateway_mcp_active_sessions",
    "Approximate active Gateway MCP authenticated sessions.",
)

SENSITIVE_KEYS = {
    "credential",
    "connection_id",
    "connection_handle",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
}


def metrics_response() -> bytes:
    return generate_latest()


def now_ms() -> int:
    return int(time.time() * 1000)


def start_timer() -> float:
    return time.perf_counter()


def observe_tool_call(
    *,
    tool: str,
    system: str,
    status: str,
    decision: str,
    started_at: float,
) -> None:
    TOOL_CALLS_TOTAL.labels(
        tool=tool, system=system, status=status, decision=decision
    ).inc()
    TOOL_LATENCY_SECONDS.labels(tool=tool, system=system).observe(
        time.perf_counter() - started_at
    )


def record_auth_failure(reason: str) -> None:
    AUTH_FAILURES_TOTAL.labels(reason=reason).inc()


def record_policy_deny(tool: str, scope: str, reason: str) -> None:
    POLICY_DENIES_TOTAL.labels(tool=tool, scope=scope, reason=reason).inc()


def record_upstream_error(system: str, error_class: str) -> None:
    UPSTREAM_ERRORS_TOTAL.labels(system=system, error_class=error_class).inc()


def record_memory_event(operation: str, tier: str, scope: str, status: str) -> None:
    MEMORY_EVENTS_TOTAL.labels(
        operation=operation, tier=tier or "any", scope=scope or "any", status=status
    ).inc()


def observe_memory_results(operation: str, count: int) -> None:
    MEMORY_SEARCH_RESULTS.labels(operation=operation).observe(count)


def observe_skill_event(
    *,
    event_type: str,
    agent: str,
    skill_id: str,
    skill_pack: str,
    status: str,
    duration_ms: int | None,
) -> None:
    ASSISTANT_SKILL_EVENTS_TOTAL.labels(
        event_type=event_type,
        agent=_metric_label(agent),
        skill_id=_metric_label(skill_id),
        skill_pack=_metric_label(skill_pack or "unknown"),
        status=_metric_label(status),
    ).inc()
    if event_type in {"completed", "failed"} and duration_ms is not None:
        ASSISTANT_SKILL_DURATION_SECONDS.labels(
            agent=_metric_label(agent),
            skill_id=_metric_label(skill_id),
            skill_pack=_metric_label(skill_pack or "unknown"),
        ).observe(max(0, duration_ms) / 1000)


def observe_privacy_summary(*, surface: str, summary: dict[str, Any]) -> None:
    by_type = summary.get("by_type")
    if not isinstance(by_type, dict):
        return
    for raw_type, actions in by_type.items():
        if not isinstance(actions, dict):
            continue
        for action, raw_count in actions.items():
            count = int(raw_count or 0)
            if count <= 0:
                continue
            PRIVACY_ENTITIES_TOTAL.labels(
                surface=_metric_label(surface),
                entity_type=_privacy_metric_type(raw_type),
                action=_metric_label(action),
            ).inc(count)


def observe_llm_proxy_request(*, api: str, status: str, duration_ms: int) -> None:
    LLM_PROXY_REQUESTS_TOTAL.labels(
        api=_metric_label(api), status=_metric_label(status)
    ).inc()
    if duration_ms > 0:
        LLM_PROXY_LATENCY_SECONDS.labels(api=_metric_label(api)).observe(
            duration_ms / 1000
        )


def _audit_log_path() -> Path:
    raw = os.getenv("GATEWAY_AUDIT_LOG", "gateway-audit.jsonl")
    path = Path(raw)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parent / path).resolve()
    return path


def _hash_value(value: str) -> str:
    salt = os.getenv("GATEWAY_AUDIT_HASH_SALT", "gateway-mcp")
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]


def _metric_label(value: str) -> str:
    clean = str(value or "unknown").strip().casefold()
    return clean[:80] or "unknown"


def _privacy_metric_type(value: Any) -> str:
    known = {
        "api_key",
        "bank_account",
        "bearer_token",
        "binary_payload",
        "birth_date",
        "credential",
        "email",
        "financial_value",
        "inn",
        "ip_address",
        "jwt",
        "passport",
        "phone",
        "private_key",
        "snils",
    }
    normalized = _metric_label(str(value))
    return normalized if normalized in known else "custom"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.casefold() in SENSITIVE_KEYS or any(
                sensitive in key.casefold() for sensitive in SENSITIVE_KEYS
            ):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def audit_event(
    *,
    event: str,
    actor: GatewayActor,
    tool: str = "",
    system: str = "",
    decision: str = "",
    status: str = "",
    scope: str = "",
    arguments: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    payload = {
        "ts_ms": now_ms(),
        "event": event,
        "actor": {
            "subject": actor.subject,
            "email_hash": _hash_value(actor.email) if actor.email else "",
            "login_hash": _hash_value(actor.login) if actor.login else "",
            "groups": list(actor.groups),
        },
        "tool": tool,
        "system": system,
        "decision": decision,
        "status": status,
        "scope": scope,
        "arguments": _redact(arguments or {}),
        "error": error,
    }

    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    LOGGER.info(line)

    if append_audit_event(payload):
        return

    path = _audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
