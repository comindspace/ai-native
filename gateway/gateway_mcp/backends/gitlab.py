import os
from typing import Any
from urllib.parse import quote

import httpx

from gateway_mcp.backends.common import (
    BackendRouteError,
    _format_path,
    _gitlab_token,
    _json_or_text,
    _route_body,
    _route_params,
)
from gateway_mcp.services.managed_integrations import integration_value


def _gitlab_headers() -> dict[str, str]:
    return {
        "PRIVATE-TOKEN": _gitlab_token(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _encode_gitlab_args(arguments: dict[str, Any]) -> dict[str, Any]:
    encoded = dict(arguments)
    for key in ("project_id", "group_id", "file_path"):
        if key in encoded and encoded[key] is not None:
            encoded[key] = quote(str(encoded[key]).strip(), safe="")
    return encoded


async def _call_gitlab(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    http_method = str(route.get("http_method", "GET")).upper()
    encoded_arguments = _encode_gitlab_args(arguments)
    path = _format_path(str(route.get("path", "")), encoded_arguments)
    if not path:
        raise BackendRouteError(f"GitLab route {route.get('name')} has no path")

    params = _route_params(route, arguments)
    body = _route_body(route, arguments)
    base_url = integration_value("gitlab", "GITLAB_API_BASE_URL", "https://gitlab.example.com/api/v4").rstrip("/")
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            http_method,
            f"{base_url}/{path.lstrip('/')}",
            headers=_gitlab_headers(),
            params=params or None,
            json=body if http_method in {"POST", "PATCH", "PUT"} else None,
        )

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "gitlab",
        "method": http_method,
        "path": path,
        "data": _json_or_text(response),
    }
