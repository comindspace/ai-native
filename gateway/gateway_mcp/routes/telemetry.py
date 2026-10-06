import json
from typing import Any

import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway_mcp.services.auth import auth_enabled, decode_gateway_token
from gateway_mcp.services.policy import GatewayActor, actor_from_claims, has_scope
from gateway_mcp.services.telemetry import record_usage_report


def register_telemetry_routes(mcp):
    @mcp.custom_route("/telemetry/usage", methods=["POST"], include_in_schema=False)
    async def telemetry_usage(request: Request) -> Response:
        actor = _actor_from_request(request)
        if actor is None:
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        if not has_scope(actor, "telemetry:write"):
            return JSONResponse({"ok": False, "error": "missing telemetry:write"}, status_code=403)

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "json_object_required"}, status_code=400)

        try:
            result = record_usage_report(actor=actor, **_usage_kwargs(payload))
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse(result)


def _actor_from_request(request: Request) -> GatewayActor | None:
    if not auth_enabled():
        return GatewayActor(subject="dev:local", login="local-dev", groups=("admins",), scopes=("*",))

    token = _bearer_token(str(request.headers.get("authorization") or ""))
    if not token:
        return None

    try:
        return actor_from_claims(decode_gateway_token(token, verify=True))
    except jwt.PyJWTError:
        return None


def _bearer_token(header: str) -> str:
    prefix = "bearer "
    if not header.casefold().startswith(prefix):
        return ""
    return header[len(prefix):].strip()


def _usage_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    raw_event = payload.get("raw_event") if isinstance(payload.get("raw_event"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "agent": payload.get("agent") or "unknown",
        "source": payload.get("source") or "http_hook",
        "source_quality": payload.get("source_quality") or payload.get("quality") or "estimated",
        "event_name": payload.get("event_name") or payload.get("event") or "usage_report",
        "provider": payload.get("provider") or "",
        "model": payload.get("model") or payload.get("resolvedModel") or "",
        "session_id": payload.get("session_id") or "",
        "correlation_id": payload.get("correlation_id") or "",
        "skill_id": payload.get("skill_id") or "",
        "skill_pack": payload.get("skill_pack") or "",
        "project": payload.get("project") or "",
        "client": payload.get("client") or "",
        "cwd": payload.get("cwd") or "",
        "input_tokens": payload.get("input_tokens") or usage.get("input_tokens") or 0,
        "output_tokens": payload.get("output_tokens") or usage.get("output_tokens") or 0,
        "total_tokens": payload.get("total_tokens") or payload.get("totalTokens") or usage.get("total_tokens") or 0,
        "cache_creation_input_tokens": (
            payload.get("cache_creation_input_tokens") or usage.get("cache_creation_input_tokens") or 0
        ),
        "cache_read_input_tokens": payload.get("cache_read_input_tokens") or usage.get("cache_read_input_tokens") or 0,
        "reasoning_tokens": payload.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0,
        "duration_ms": payload.get("duration_ms") or payload.get("totalDurationMs") or 0,
        "tool_use_count": payload.get("tool_use_count") or payload.get("totalToolUseCount") or 0,
        "usage_class": payload.get("usage_class") or "",
        "estimated_cost_usd": payload.get("estimated_cost_usd") or 0,
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
        "raw_event_json": json.dumps(raw_event, ensure_ascii=False),
    }
