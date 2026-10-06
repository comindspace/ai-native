from typing import Any

from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.observability import audit_event, observe_tool_call, record_policy_deny


def finish_tool(
    *,
    tool: str,
    system: str,
    started_at: float,
    status: str,
    decision: str,
    scope: str,
    arguments: dict[str, Any],
    error: str = "",
) -> None:
    observe_tool_call(
        tool=tool,
        system=system,
        status=status,
        decision=decision,
        started_at=started_at,
    )
    audit_event(
        event="tool_call",
        actor=current_actor(),
        tool=tool,
        system=system,
        decision=decision,
        status=status,
        scope=scope,
        arguments=arguments,
        error=error,
    )


def deny(tool: str, scope: str, reason: str) -> None:
    record_policy_deny(tool, scope, reason)
