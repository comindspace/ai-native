from dataclasses import dataclass
from typing import Any

from gateway_mcp.audit import deny, finish_tool
from gateway_mcp.services.auth import require_scope
from gateway_mcp.services.observability import start_timer
from gateway_mcp.services.policy import GatewayActor


@dataclass
class ToolRun:
    tool: str
    system: str
    scope: str
    arguments: dict[str, Any]
    started_at: float

    @classmethod
    def start(cls, *, tool: str, system: str, scope: str, arguments: dict[str, Any]) -> "ToolRun":
        return cls(tool=tool, system=system, scope=scope, arguments=arguments, started_at=start_timer())

    def require_scope(self, scope: str | None = None, tool: str | None = None) -> GatewayActor:
        return require_scope(scope or self.scope, tool=tool or self.tool)

    def finish(self, *, status: str = "ok", decision: str = "allow", scope: str | None = None, error: str = "") -> None:
        finish_tool(
            tool=self.tool,
            system=self.system,
            started_at=self.started_at,
            status=status,
            decision=decision,
            scope=scope or self.scope,
            arguments=self.arguments,
            error=error,
        )

    def denied(self, exc: PermissionError, *, deny_tool: str | None = None, scope: str | None = None) -> None:
        effective_scope = scope or self.scope
        deny(deny_tool or self.tool, effective_scope, "missing_scope")
        self.finish(status="denied", decision="deny", scope=effective_scope, error=str(exc))

    def error(self, exc: Exception, *, decision: str = "allow", scope: str | None = None) -> None:
        self.finish(status="error", decision=decision, scope=scope or self.scope, error=exc.__class__.__name__)
