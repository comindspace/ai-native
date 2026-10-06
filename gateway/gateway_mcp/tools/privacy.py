import json
from typing import Annotated, Any
from uuid import uuid4

from mcp.types import ToolAnnotations
from pydantic import Field

from gateway_mcp.backends import call_backend
from gateway_mcp.config import read_json, tools_file
from gateway_mcp.services.access import require_resource_access
from gateway_mcp.services.observability import (
    audit_event,
    observe_privacy_summary,
    record_upstream_error,
)
from gateway_mcp.services.privacy import (
    normalize_policy,
    public_entities,
    sanitize_text,
    sanitize_value,
)
from gateway_mcp.tools.runtime import ToolRun


def register_privacy_tools(mcp) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Privacy Classify", readOnlyHint=True)
    )
    async def gateway_privacy_classify(text: str, policy: str = "standard") -> str:
        """Classify sensitive text without returning detected source values."""
        run = ToolRun.start(
            tool="gateway_privacy_classify",
            system="privacy",
            scope="privacy:use",
            arguments={"policy": policy, "text_length": len(text)},
        )
        try:
            actor = run.require_scope()
            result = sanitize_text(
                text,
                actor_subject=actor.subject,
                policy=normalize_policy(policy),
            )
            run.arguments["summary"] = result.summary.as_dict()
            observe_privacy_summary(
                surface="mcp_classify", summary=result.summary.as_dict()
            )
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    "policy": normalize_policy(policy),
                    "summary": result.summary.as_dict(),
                    "entities": public_entities(result.entities),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Privacy Sanitize Text"))
    async def gateway_privacy_sanitize_text(text: str, policy: str = "standard") -> str:
        """Pseudonymize personal data and irreversibly redact secrets in text."""
        run = ToolRun.start(
            tool="gateway_privacy_sanitize_text",
            system="privacy",
            scope="privacy:use",
            arguments={"policy": policy, "text_length": len(text)},
        )
        try:
            actor = run.require_scope()
            result = sanitize_text(
                text,
                actor_subject=actor.subject,
                policy=normalize_policy(policy),
            )
            run.arguments["summary"] = result.summary.as_dict()
            observe_privacy_summary(
                surface="mcp_sanitize", summary=result.summary.as_dict()
            )
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    "policy": normalize_policy(policy),
                    "text": result.value,
                    "summary": result.summary.as_dict(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Call Tool Sanitized", readOnlyHint=True
        )
    )
    async def gateway_call_tool_sanitized(
        tool_name: Annotated[str, Field(json_schema_extra={"x-mcp-header": "Route"})],
        arguments_json: str = "{}",
        policy: str = "standard",
    ) -> str:
        """Call a read-only backend route and sanitize its result before agent delivery."""
        gateway_request_id = uuid4().hex[:16]
        run = ToolRun.start(
            tool="gateway_call_tool_sanitized",
            system="gateway",
            scope="tools:call",
            arguments={
                "tool_name": tool_name,
                "policy": policy,
                "gateway_request_id": gateway_request_id,
            },
        )
        try:
            parsed_arguments = _arguments(arguments_json)
            actor = run.require_scope()
            run.require_scope("privacy:use")
            route = _route(tool_name)
            route_scope = str(route.get("scope") or "")
            if route_scope:
                run.require_scope(route_scope, tool=tool_name)
            if _mutating(route):
                raise ValueError(
                    "gateway_call_tool_sanitized accepts read-only routes only"
                )
            access = require_resource_access(
                actor=actor,
                route=route,
                arguments=parsed_arguments,
            )
            audit_event(
                event="sanitized_resource_access",
                actor=actor,
                tool=tool_name,
                system=str(route.get("backend") or "unknown"),
                decision=str(access.get("decision") or "allow"),
                status="allowed",
                scope=route_scope or "tools:call",
                arguments={
                    "gateway_request_id": gateway_request_id,
                    "resource_type": access.get("resource_type"),
                    "resource": access.get("resource"),
                    "policy": normalize_policy(policy),
                },
            )
            result = await call_backend(route, parsed_arguments)
            protected = sanitize_value(
                result,
                actor_subject=actor.subject,
                policy=normalize_policy(policy),
            )
            response = _compact(protected.value)
            response["privacy"] = protected.summary.as_dict()
            response["gateway_request_id"] = gateway_request_id
            run.system = str(route.get("backend") or "unknown")
            run.arguments["summary"] = protected.summary.as_dict()
            observe_privacy_summary(
                surface="backend_result", summary=protected.summary.as_dict()
            )
            run.finish(
                status="ok" if bool(result.get("ok")) else "upstream_error",
                scope=route_scope or "tools:call",
            )
            return json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc, deny_tool=tool_name or run.tool)
            raise
        except Exception as exc:
            record_upstream_error("privacy", exc.__class__.__name__)
            run.error(exc)
            raise


def _arguments(arguments_json: str) -> dict[str, Any]:
    try:
        value = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arguments_json must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError("arguments_json must contain a JSON object")
    return value


def _route(tool_name: str) -> dict[str, Any]:
    registry = read_json(tools_file(), {"tools": []})
    route = next(
        (item for item in registry.get("tools", []) if item.get("name") == tool_name),
        None,
    )
    if route is None:
        raise ValueError(f"unknown gateway route: {tool_name}")
    return route


def _mutating(route: dict[str, Any]) -> bool:
    scope = str(route.get("scope") or "")
    if scope.endswith(":write"):
        return True
    if scope.endswith(":read"):
        return False
    method = str(route.get("http_method") or "").upper()
    return method in {"POST", "PUT", "PATCH", "DELETE"}


def _compact(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"ok": True, "result": result}
    hidden = {"access", "backend", "method", "path", "route", "tool_name"}
    return {key: value for key, value in result.items() if key not in hidden}
