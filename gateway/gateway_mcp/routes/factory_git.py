from __future__ import annotations

import asyncio
import base64

import httpx
from starlette.responses import Response

from gateway_mcp.services.auth import verify_gateway_token_claims
from gateway_mcp.services.factory_git import authorize_git, validate_push
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import actor_from_claims

MAX_REQUEST = 64 * 1024 * 1024
MAX_RESPONSE = 128 * 1024 * 1024
SLOTS = asyncio.Semaphore(2)
NO_CACHE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def request_actor(request):
    # Git is stateless and does not use browser cookies for authentication.
    authorization = request.headers.get("authorization", "")
    try:
        kind, value = authorization.split(" ", 1)
        if kind.casefold() == "bearer":
            token = value
        elif kind.casefold() == "basic":
            user, token = base64.b64decode(value, validate=True).decode().split(":", 1)
            if user != "factory":
                return None
        else:
            return None
        return actor_from_claims(verify_gateway_token_claims(token))
    except Exception:  # noqa: BLE001 - authentication fails closed
        return None


async def forward_git(request, actor, work_id, service, discovery):
    body = bytearray()
    if request.headers.get("content-encoding", "identity") != "identity":
        return Response(
            "Encoded requests are not supported", status_code=415, headers=NO_CACHE
        )
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST:
            return Response("Git request too large", status_code=413, headers=NO_CACHE)
    # Recheck lease and connection after reading an untrusted/slow request body.
    work, config, connection, branch = authorize_git(actor, work_id)
    if not discovery and service == "git-receive-pack":
        validate_push(bytes(body), branch)
    expected_type = (
        f"application/x-{service}-{'advertisement' if discovery else 'result'}"
    )
    headers = {"Accept-Encoding": "identity", "Accept": expected_type}
    if not discovery:
        if (
            request.headers.get("content-type", "").split(";", 1)[0]
            != f"application/x-{service}-request"
        ):
            return Response("Invalid Git media type", status_code=415, headers=NO_CACHE)
        headers["Content-Type"] = f"application/x-{service}-request"
    suffix = "/info/refs" if discovery else "/" + service
    async with httpx.AsyncClient(  # noqa: SIM117 - client owns the streamed response
        timeout=60,
        follow_redirects=False,
        auth=httpx.BasicAuth(connection["username"], connection["token"]),
    ) as client:
        async with client.stream(
            request.method,
            config["gitlab_clone_url"] + suffix,
            params={"service": service} if discovery else None,
            headers=headers,
            content=bytes(body),
        ) as upstream:
            if upstream.status_code != 200:
                return Response(
                    "GitLab rejected the Git request; ask the administrator to check the service connection.",
                    status_code=502,
                    headers=NO_CACHE,
                )
            if (
                upstream.headers.get("content-type", "").split(";", 1)[0]
                != expected_type
                or upstream.headers.get("content-encoding", "identity") != "identity"
            ):
                return Response(
                    "Unexpected GitLab response", status_code=502, headers=NO_CACHE
                )
            data = bytearray()
            async for chunk in upstream.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_RESPONSE:
                    return Response(
                        "Git response too large; use a shallow clone",
                        status_code=502,
                        headers=NO_CACHE,
                    )
    audit_event(
        event="factory_git_transport",
        actor=actor,
        system="factory",
        decision="allow",
        status="ok",
        arguments={
            "work_id": work["work_id"],
            "project_id": work["project_id"],
            "operation": service,
            "discovery": discovery,
        },
    )
    return Response(bytes(data), media_type=expected_type, headers=NO_CACHE)


def register_factory_git_routes(mcp):
    @mcp.custom_route(
        "/factory/git/{work_id}/repo.git/{operation:path}",
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    async def git_transport(request):
        actor = request_actor(request)
        if actor is None:
            return Response(
                "Gateway authentication required",
                status_code=401,
                headers={**NO_CACHE, "WWW-Authenticate": 'Basic realm="Factory Git"'},
            )
        work_id = request.path_params["work_id"]
        operation = request.path_params["operation"]
        discovery = request.method == "GET" and operation == "info/refs"
        service = request.query_params.get("service", "") if discovery else operation
        if (
            service not in {"git-upload-pack", "git-receive-pack"}
            or (not discovery and request.method != "POST")
            or list(request.query_params.keys()) != (["service"] if discovery else [])
            or (discovery and len(request.query_params.getlist("service")) != 1)
        ):
            return Response(
                "Unsupported Git operation", status_code=404, headers=NO_CACHE
            )
        try:
            authorize_git(actor, work_id)

            async def bounded():
                async with SLOTS:
                    return await forward_git(
                        request, actor, work_id, service, discovery
                    )

            return await asyncio.wait_for(bounded(), timeout=90)
        except Exception as exc:  # noqa: BLE001 - redact upstream details at HTTP boundary
            denied = isinstance(exc, (PermissionError, KeyError))
            audit_event(
                event="factory_git_transport",
                actor=actor,
                system="factory",
                decision="deny" if denied else "allow",
                status="error",
                arguments={"operation": service, "error_class": type(exc).__name__},
            )
            return Response(
                "Factory Git access denied or unavailable; check the active lease and project readiness.",
                status_code=403 if denied else 502,
                headers=NO_CACHE,
            )
