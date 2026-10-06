from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from gateway_mcp.services.auth import (
    auth_enabled,
    decode_gateway_token,
)
from gateway_mcp.services.managed_integrations import integration_value
from gateway_mcp.services.observability import (
    audit_event,
    observe_llm_proxy_request,
    observe_privacy_summary,
    record_upstream_error,
)
from gateway_mcp.services.policy import GatewayActor, actor_from_claims, has_scope
from gateway_mcp.services.privacy import (
    PrivacySummary,
    normalize_policy,
    protect_llm_response,
    sanitize_llm_request,
)


def register_llm_proxy_routes(mcp: Any) -> None:
    @mcp.custom_route(
        "/privacy/v1/chat/completions", methods=["POST"], include_in_schema=False
    )
    async def chat_completions(request: Request) -> Response:
        return await _proxy_completion(request, api="chat")

    @mcp.custom_route(
        "/privacy/v1/responses", methods=["POST"], include_in_schema=False
    )
    async def responses(request: Request) -> Response:
        return await _proxy_completion(request, api="responses")

    @mcp.custom_route("/privacy/v1/models", methods=["GET"], include_in_schema=False)
    async def models(request: Request) -> Response:
        actor = _actor_from_request(request)
        if actor is None:
            return _error(401, "unauthorized", "Gateway authentication is required")
        if not has_scope(actor, "llm:proxy"):
            return _error(403, "insufficient_scope", "llm:proxy is required")
        try:
            upstream = await _upstream_get("models")
        except Exception as exc:  # noqa: BLE001 - HTTP boundary emits a safe error
            record_upstream_error("llm-proxy", exc.__class__.__name__)
            return _error(502, "upstream_error", "Model provider is unavailable")
        if upstream.status_code >= 400:
            return _error(
                502,
                "upstream_error",
                f"Model provider returned HTTP {upstream.status_code}",
            )
        try:
            return JSONResponse(upstream.json(), headers=_safe_headers())
        except ValueError:
            return _error(502, "upstream_error", "Model provider returned invalid JSON")


async def _proxy_completion(request: Request, *, api: str) -> Response:
    request_id = uuid4().hex[:16]
    actor = _actor_from_request(request)
    if actor is None:
        return _error(401, "unauthorized", "Gateway authentication is required")
    if not has_scope(actor, "llm:proxy"):
        return _error(403, "insufficient_scope", "llm:proxy is required")
    try:
        payload = await _json_body(request)
        policy = normalize_policy(
            str(request.headers.get("x-gateway-privacy-policy") or "")
        )
        _set_default_model(payload)
        _require_allowed_model(str(payload.get("model") or ""))
        client_stream = bool(payload.get("stream"))
        protected = sanitize_llm_request(
            payload,
            actor_subject=actor.subject,
            policy=policy,
        )
        outbound = dict(protected.value)
        outbound["stream"] = False
        outbound.pop("stream_options", None)
        outbound["store"] = False
        outbound["user"] = _actor_identifier(actor.subject)
        if "safety_identifier" in outbound:
            outbound["safety_identifier"] = _actor_identifier(actor.subject)
    except (TypeError, ValueError) as exc:
        return _error(400, "invalid_request", str(exc), request_id=request_id)

    _audit(
        actor=actor,
        request_id=request_id,
        api=api,
        phase="request",
        status="ok",
        policy=policy,
        summary=protected.summary,
    )
    observe_privacy_summary(surface="llm_request", summary=protected.summary.as_dict())
    started = time.perf_counter()
    try:
        upstream = await _upstream_post(
            "chat/completions" if api == "chat" else "responses",
            outbound,
        )
    except Exception as exc:  # noqa: BLE001 - HTTP boundary emits a safe error
        observe_llm_proxy_request(api=api, status="error", duration_ms=0)
        record_upstream_error("llm-proxy", exc.__class__.__name__)
        _audit(
            actor=actor,
            request_id=request_id,
            api=api,
            phase="upstream",
            status="error",
            policy=policy,
            error=exc.__class__.__name__,
        )
        return _error(
            502,
            "upstream_error",
            "Model provider is unavailable",
            request_id=request_id,
        )
    if upstream.status_code >= 400:
        observe_llm_proxy_request(api=api, status="upstream_error", duration_ms=0)
        _audit(
            actor=actor,
            request_id=request_id,
            api=api,
            phase="upstream",
            status="error",
            policy=policy,
            error=f"http_{upstream.status_code}",
        )
        return _error(
            502,
            "upstream_error",
            f"Model provider returned HTTP {upstream.status_code}",
            request_id=request_id,
        )
    try:
        body = upstream.json()
        restored = protect_llm_response(
            body,
            actor_subject=actor.subject,
            restoration=protected.restoration,
            policy=policy,
        )
    except (TypeError, ValueError) as exc:
        record_upstream_error("llm-proxy", "invalid_json")
        return _error(
            502,
            "upstream_error",
            f"Model provider returned invalid JSON: {exc.__class__.__name__}",
            request_id=request_id,
        )
    _audit(
        actor=actor,
        request_id=request_id,
        api=api,
        phase="response",
        status="ok",
        policy=policy,
        summary=restored.summary,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    observe_privacy_summary(surface="llm_response", summary=restored.summary.as_dict())
    observe_llm_proxy_request(api=api, status="ok", duration_ms=duration_ms)
    headers = {**_safe_headers(), "X-Gateway-Request-Id": request_id}
    if client_stream:
        events = (
            _chat_events(restored.value)
            if api == "chat"
            else _responses_events(restored.value)
        )
        return StreamingResponse(
            _event_stream(events),
            media_type="text/event-stream",
            headers={**headers, "X-Accel-Buffering": "no"},
        )
    return JSONResponse(restored.value, headers=headers)


async def _json_body(request: Request) -> dict[str, Any]:
    limit = max(1024, int(os.getenv("GATEWAY_LLM_PROXY_MAX_BODY_BYTES", "4194304")))
    raw_length = str(request.headers.get("content-length") or "").strip()
    if raw_length and int(raw_length) > limit:
        raise ValueError("Request body exceeds the configured limit")
    raw = await request.body()
    if len(raw) > limit:
        raise ValueError("Request body exceeds the configured limit")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("Request body must contain a JSON object")
    return value


def _set_default_model(payload: dict[str, Any]) -> None:
    if str(payload.get("model") or "").strip():
        return
    model = integration_value("llm-proxy", "GATEWAY_LLM_DEFAULT_MODEL")
    if not model:
        raise ValueError("model is required")
    payload["model"] = model


def _require_allowed_model(model: str) -> None:
    raw = integration_value("llm-proxy", "GATEWAY_LLM_ALLOWED_MODELS")
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    if allowed and model not in allowed:
        raise ValueError("model is not allowed by Gateway policy")


async def _upstream_post(path: str, payload: dict[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_timeout(), follow_redirects=False) as client:
        return await client.post(
            f"{_upstream_base()}/{path}",
            headers=_upstream_headers(),
            json=payload,
        )


async def _upstream_get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_timeout(), follow_redirects=False) as client:
        return await client.get(
            f"{_upstream_base()}/{path}",
            headers=_upstream_headers(),
        )


def _upstream_base() -> str:
    value = integration_value(
        "llm-proxy",
        "GATEWAY_LLM_UPSTREAM_URL",
        "https://openrouter.ai/api/v1",
    ).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise RuntimeError("LLM proxy upstream URL is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(
            "LLM proxy upstream URL must not contain credentials or query data"
        )
    if parsed.scheme == "http" and not _bool_env(
        "GATEWAY_LLM_ALLOW_INSECURE_UPSTREAM", False
    ):
        raise RuntimeError("LLM proxy upstream must use HTTPS")
    return value


def _upstream_headers() -> dict[str, str]:
    key = integration_value("llm-proxy", "GATEWAY_LLM_UPSTREAM_API_KEY")
    if not key:
        raise RuntimeError("LLM proxy upstream is not configured")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _timeout() -> float:
    return max(1.0, float(os.getenv("GATEWAY_LLM_PROXY_TIMEOUT_SECONDS", "180")))


def _actor_identifier(subject: str) -> str:
    return f"gateway-{hashlib.sha256(subject.encode()).hexdigest()[:20]}"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _actor_from_request(request: Request) -> GatewayActor | None:
    if not auth_enabled():
        return GatewayActor(
            subject="dev:local",
            login="local-dev",
            groups=("admins",),
            scopes=("*",),
        )
    header = str(request.headers.get("authorization") or "")
    if not header.casefold().startswith("bearer "):
        return None
    try:
        return actor_from_claims(decode_gateway_token(header[7:].strip(), verify=True))
    except (jwt.PyJWTError, PermissionError, ValueError):
        return None


def _chat_events(payload: dict[str, Any]) -> list[bytes]:
    event = {
        key: value
        for key, value in payload.items()
        if key not in {"choices", "usage", "object"}
    }
    event["object"] = "chat.completion.chunk"
    choices = []
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = (
            choice.get("message") if isinstance(choice.get("message"), dict) else {}
        )
        delta = {key: value for key, value in message.items() if key != "role"}
        delta["role"] = str(message.get("role") or "assistant")
        choices.append(
            {
                "index": int(choice.get("index") or 0),
                "delta": delta,
                "finish_reason": choice.get("finish_reason") or "stop",
            }
        )
    event["choices"] = choices
    if "usage" in payload:
        event["usage"] = payload["usage"]
    return [_sse(event), b"data: [DONE]\n\n"]


def _responses_events(payload: dict[str, Any]) -> list[bytes]:
    created = dict(payload)
    created["status"] = "in_progress"
    created["output"] = []
    events = [_sse({"type": "response.created", "response": created}, named=True)]
    for output_index, item in enumerate(payload.get("output") or []):
        if not isinstance(item, dict):
            continue
        added = dict(item)
        if isinstance(added.get("content"), list):
            added["content"] = []
        if "arguments" in added:
            added["arguments"] = ""
        events.append(
            _sse(
                {
                    "type": "response.output_item.added",
                    "output_index": output_index,
                    "item": added,
                },
                named=True,
            )
        )
        for content_index, part in enumerate(item.get("content") or []):
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or part.get("refusal") or "")
            family = "output_text" if part.get("type") == "output_text" else "refusal"
            events.append(
                _sse(
                    {
                        "type": f"response.{family}.delta",
                        "item_id": item.get("id"),
                        "output_index": output_index,
                        "content_index": content_index,
                        "delta": text,
                    },
                    named=True,
                )
            )
            events.append(
                _sse(
                    {
                        "type": f"response.{family}.done",
                        "item_id": item.get("id"),
                        "output_index": output_index,
                        "content_index": content_index,
                        "text" if family == "output_text" else "refusal": text,
                    },
                    named=True,
                )
            )
        if isinstance(item.get("arguments"), str):
            arguments = item["arguments"]
            events.append(
                _sse(
                    {
                        "type": "response.function_call_arguments.delta",
                        "item_id": item.get("id"),
                        "output_index": output_index,
                        "delta": arguments,
                    },
                    named=True,
                )
            )
            events.append(
                _sse(
                    {
                        "type": "response.function_call_arguments.done",
                        "item_id": item.get("id"),
                        "output_index": output_index,
                        "arguments": arguments,
                    },
                    named=True,
                )
            )
        events.append(
            _sse(
                {
                    "type": "response.output_item.done",
                    "output_index": output_index,
                    "item": item,
                },
                named=True,
            )
        )
    events.append(_sse({"type": "response.completed", "response": payload}, named=True))
    return events


def _sse(value: dict[str, Any], *, named: bool = False) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    event = f"event: {value.get('type')}\n" if named and value.get("type") else ""
    return f"{event}data: {payload}\n\n".encode()


async def _event_stream(events: list[bytes]) -> AsyncIterator[bytes]:
    for event in events:
        yield event


def _safe_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def _error(
    status: int,
    code: str,
    message: str,
    *,
    request_id: str = "",
) -> JSONResponse:
    headers = _safe_headers()
    if request_id:
        headers["X-Gateway-Request-Id"] = request_id
    return JSONResponse(
        {
            "error": {
                "message": message,
                "type": code,
                "param": None,
                "code": code,
            }
        },
        status_code=status,
        headers=headers,
    )


def _audit(
    *,
    actor: GatewayActor,
    request_id: str,
    api: str,
    phase: str,
    status: str,
    policy: str,
    summary: PrivacySummary | None = None,
    duration_ms: int = 0,
    error: str = "",
) -> None:
    audit_event(
        event="llm_privacy_proxy",
        actor=actor,
        tool=f"openai.{api}",
        system="llm-proxy",
        decision="allow" if status == "ok" else "deny",
        status=status,
        scope="llm:proxy",
        arguments={
            "gateway_request_id": request_id,
            "phase": phase,
            "policy": policy,
            "duration_ms": duration_ms,
            "privacy": summary.as_dict() if summary else {},
        },
        error=error,
    )
