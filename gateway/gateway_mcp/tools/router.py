import json
from typing import Annotated, Any
from uuid import uuid4

from mcp.types import ToolAnnotations
from pydantic import Field

from gateway_mcp.backends import call_backend
from gateway_mcp.config import read_json, tools_file
from gateway_mcp.services.access import require_resource_access
from gateway_mcp.services.approvals import validate_and_consume_approval
from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.observability import audit_event, record_upstream_error
from gateway_mcp.services.storage import (
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    request_fingerprint,
)
from gateway_mcp.tools.runtime import ToolRun

MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_AGENT_HIDDEN_RESPONSE_FIELDS = {
    "access",
    "backend",
    "method",
    "path",
    "route",
    "tool_name",
}


def _compact_agent_response(
    result: dict[str, Any], *, gateway_request_id: str
) -> dict[str, Any]:
    response = {
        key: value
        for key, value in result.items()
        if key not in _AGENT_HIDDEN_RESPONSE_FIELDS
    }
    response["gateway_request_id"] = gateway_request_id
    return response


def _audit_resource_access(
    *,
    actor: Any,
    tool_name: str,
    route_scope: str,
    gateway_request_id: str,
    resource_decision: dict[str, Any],
) -> None:
    matched_grant_ids = [
        str(item.get("id"))
        for item in resource_decision.get("matched") or []
        if isinstance(item, dict) and item.get("id") is not None
    ]
    constraint_grant_ids = [
        str(item.get("grant_id"))
        for field in ("constraint_rules", "shadow_constraint_rules")
        for item in resource_decision.get(field) or []
        if isinstance(item, dict) and item.get("grant_id") is not None
    ]
    shadow_denied = resource_decision.get("shadow_decision") == "deny"
    audit_event(
        event="resource_access",
        actor=actor,
        tool=tool_name,
        system=str(resource_decision.get("system") or "unknown"),
        decision=str(resource_decision.get("decision") or "allow"),
        status="shadow_denied" if shadow_denied else "allowed",
        scope=route_scope,
        arguments={
            "gateway_request_id": gateway_request_id,
            "action": resource_decision.get("action"),
            "actions": resource_decision.get("actions") or [],
            "resource_type": resource_decision.get("resource_type"),
            "resource": resource_decision.get("resource"),
            "reason": resource_decision.get("reason"),
            "mode": resource_decision.get("mode"),
            "shadow_decision": resource_decision.get("shadow_decision"),
            "matched_grant_ids": matched_grant_ids,
            "constraint_grant_ids": sorted(set(constraint_grant_ids)),
        },
    )


def _is_mutating_route(route: dict[str, Any]) -> bool:
    http_method = str(route.get("http_method") or "").upper()
    if http_method:
        return http_method in MUTATING_HTTP_METHODS
    return str(route.get("scope") or "").endswith(":write")


def _validate_invocation_controls(
    route: dict[str, Any],
    arguments: dict[str, Any],
    idempotency_key: str,
) -> None:
    if (
        route.get("requires_approval_ref")
        and not str(arguments.get("approval_ref") or "").strip()
    ):
        raise ValueError("approval_ref is required for this route")
    if route.get("requires_idempotency_key") and not idempotency_key.strip():
        raise ValueError("idempotency_key is required for this route")


def register_router_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Call Tool"))
    async def gateway_call_tool(
        tool_name: Annotated[str, Field(json_schema_extra={"x-mcp-header": "Route"})],
        arguments_json: str = "{}",
        idempotency_key: Annotated[
            str,
            Field(json_schema_extra={"x-mcp-header": "Idempotency-Key"}),
        ] = "",
    ) -> str:
        """Call a private backend route through GatewayMCP with auth, scope checks, and audit."""
        tool = "gateway_call_tool"
        base_scope = "tools:call"
        arguments: dict[str, Any] = {"tool_name": tool_name}
        gateway_request_id = uuid4().hex[:16]
        arguments["gateway_request_id"] = gateway_request_id
        idempotency_claimed = False
        idempotency_actor = ""
        run = ToolRun.start(
            tool=tool, system="gateway", scope=base_scope, arguments=arguments
        )
        try:
            try:
                parsed_arguments = json.loads(arguments_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"arguments_json must be valid JSON: {exc}") from exc
            arguments["arguments"] = parsed_arguments
            if idempotency_key:
                arguments["idempotency_key"] = idempotency_key

            run.require_scope()
            registry = read_json(tools_file(), {"tools": []})
            route = next(
                (
                    item
                    for item in registry.get("tools", [])
                    if item.get("name") == tool_name
                ),
                None,
            )
            route_scope = str((route or {}).get("scope") or "")
            if route_scope:
                run.require_scope(route_scope, tool=tool_name)

            if route is None:
                raise ValueError(f"unknown gateway route: {tool_name}")

            _validate_invocation_controls(route, parsed_arguments, idempotency_key)
            actor = current_actor()
            resource_decision = require_resource_access(
                actor=actor, route=route, arguments=parsed_arguments
            )
            _audit_resource_access(
                actor=actor,
                tool_name=tool_name,
                route_scope=route_scope or base_scope,
                gateway_request_id=gateway_request_id,
                resource_decision=resource_decision,
            )
            is_write_route = _is_mutating_route(route)
            if is_write_route and idempotency_key:
                idempotency_actor = actor.subject
                claim = claim_idempotency(
                    actor_subject=idempotency_actor,
                    tool_name=tool_name,
                    idempotency_key=idempotency_key,
                    request_hash=request_fingerprint(parsed_arguments),
                )
                if claim.get("replayed"):
                    cached = claim.get("response")
                    if not isinstance(cached, dict):
                        raise RuntimeError("stored idempotency response is invalid")
                    cached = dict(cached)
                    cached["idempotency"] = {"key": idempotency_key, "replayed": True}
                    run.system = str(route.get("backend") or "unknown")
                    run.finish(status="ok", scope=route_scope or base_scope)
                    return json.dumps(
                        _compact_agent_response(
                            cached, gateway_request_id=gateway_request_id
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                idempotency_claimed = bool(claim.get("claimed"))

            if route.get("requires_approval_ref"):
                validate_and_consume_approval(
                    actor=actor,
                    approval_id=str(parsed_arguments.get("approval_ref") or ""),
                    tool_name=tool_name,
                    arguments=parsed_arguments,
                    idempotency_key=idempotency_key,
                    expected_type=str(route.get("approval_type") or ""),
                )

            backend_arguments = dict(parsed_arguments)
            backend_arguments.pop("approval_ref", None)
            result = await call_backend(route, backend_arguments)
            result["tool_name"] = tool_name
            result["route"] = {
                "name": route.get("name"),
                "backend": route.get("backend"),
                "scope": route.get("scope"),
                "status": route.get("status"),
            }
            result["access"] = resource_decision
            if is_write_route and idempotency_key:
                result["idempotency"] = {"key": idempotency_key, "replayed": False}
            status = "ok" if result.get("ok") else "upstream_error"
            if idempotency_claimed:
                try:
                    if status == "ok":
                        complete_idempotency(
                            actor_subject=idempotency_actor,
                            tool_name=tool_name,
                            idempotency_key=idempotency_key,
                            response=result,
                        )
                    else:
                        fail_idempotency(
                            actor_subject=idempotency_actor,
                            tool_name=tool_name,
                            idempotency_key=idempotency_key,
                        )
                except Exception as exc:  # noqa: BLE001 - preserve an already completed upstream write
                    # The upstream write may already have happened. Keep the record pending
                    # instead of allowing an automatic retry that could duplicate the write.
                    result["idempotency"]["stored"] = False
                    record_upstream_error(
                        "gateway", f"idempotency_{exc.__class__.__name__}"
                    )
                finally:
                    idempotency_claimed = False
            if status == "upstream_error":
                record_upstream_error(
                    str(route.get("backend") or "unknown"),
                    str(result.get("status") or "error"),
                )
            run.system = str(route.get("backend") or "unknown")
            run.finish(status=status, scope=route_scope or base_scope)
            return json.dumps(
                _compact_agent_response(result, gateway_request_id=gateway_request_id),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.system = "gateway"
            run.denied(exc, deny_tool=tool_name or tool)
            raise
        except Exception as exc:
            if idempotency_claimed:
                try:
                    fail_idempotency(
                        actor_subject=idempotency_actor,
                        tool_name=tool_name,
                        idempotency_key=idempotency_key,
                    )
                except Exception as idempotency_exc:  # noqa: BLE001 - preserve the original tool error
                    record_upstream_error(
                        "gateway",
                        f"idempotency_{idempotency_exc.__class__.__name__}",
                    )
            record_upstream_error("gateway", exc.__class__.__name__)
            run.system = "gateway"
            run.error(exc)
            raise
