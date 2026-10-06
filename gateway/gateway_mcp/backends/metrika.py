import os
from typing import Any

import httpx

from gateway_mcp.backends.common import (
    BackendConfigError,
    BackendRouteError,
    _bool_env,
    _format_path,
    _json_or_text,
    _route_body,
    _route_params,
)


def _metrika_token() -> str:
    token = os.getenv("YANDEX_METRIKA_OAUTH_ACCESS_TOKEN", "")
    if token:
        return token
    if _bool_env("GATEWAY_ALLOW_SERVER_YANDEX_TOKENS", False):
        fallback = os.getenv("YANDEX_OAUTH_ACCESS_TOKEN", "")
        if fallback:
            return fallback
    raise BackendConfigError(
        "No Yandex Metrika token. Set YANDEX_METRIKA_OAUTH_ACCESS_TOKEN (shared read-only) "
        "on the Gateway host, or grant the metrika:read Yandex OAuth scope and re-login."
    )


def _metrika_headers() -> dict[str, str]:
    return {
        "Authorization": f"OAuth {_metrika_token()}",
        "Accept": "application/json",
    }


async def _call_metrika(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    http_method = str(route.get("http_method", "GET")).upper()
    path_template = str(route.get("path", "")).strip()
    if not path_template:
        raise BackendRouteError(f"Yandex Metrika route {route.get('name')} has no path")
    path = _format_path(path_template, arguments)

    params = _route_params(route, arguments)
    body = _route_body(route, arguments)
    headers = _metrika_headers()
    base_url = os.getenv("YANDEX_METRIKA_API_BASE_URL", "https://api-metrika.yandex.ru").rstrip("/")
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            http_method,
            f"{base_url}/{path.lstrip('/')}",
            headers=headers,
            params=params or None,
            json=body if http_method in {"POST", "PATCH", "PUT"} and body else None,
        )

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "metrika",
        "method": http_method,
        "path": path,
        "data": _json_or_text(response),
    }
