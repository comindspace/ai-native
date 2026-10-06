import os
from typing import Any
from urllib.parse import quote

import httpx

from gateway_mcp.backends.common import (
    BackendConfigError,
    BackendRouteError,
    _bool_env,
    _json_or_text,
    _route_params,
)


def _webmaster_token() -> str:
    token = os.getenv("YANDEX_WEBMASTER_OAUTH_ACCESS_TOKEN", "")
    if not token:
        # The Metrika token belongs to the same Yandex account and also
        # covers the Webmaster API, so it is a valid shared fallback.
        token = os.getenv("YANDEX_METRIKA_OAUTH_ACCESS_TOKEN", "")
    if token:
        return token
    if _bool_env("GATEWAY_ALLOW_SERVER_YANDEX_TOKENS", False):
        fallback = os.getenv("YANDEX_OAUTH_ACCESS_TOKEN", "")
        if fallback:
            return fallback
    raise BackendConfigError(
        "No Yandex Webmaster token. Set YANDEX_WEBMASTER_OAUTH_ACCESS_TOKEN (or the shared "
        "YANDEX_METRIKA_OAUTH_ACCESS_TOKEN) on the Gateway host."
    )


def _webmaster_headers() -> dict[str, str]:
    return {
        "Authorization": f"OAuth {_webmaster_token()}",
        "Accept": "application/json",
    }


_WEBMASTER_USER_ID: dict[str, str] = {}


async def _webmaster_user_id(
    client: httpx.AsyncClient, base_url: str, headers: dict[str, str]
) -> str:
    cached = _WEBMASTER_USER_ID.get("user_id", "")
    if cached:
        return cached
    response = await client.get(f"{base_url}/v4/user", headers=headers)
    data = _json_or_text(response)
    user_id = str(data.get("user_id") or "") if isinstance(data, dict) else ""
    if not (response.is_success and user_id):
        raise BackendRouteError(
            f"Could not resolve Yandex Webmaster user id: status={response.status_code} data={data}"
        )
    _WEBMASTER_USER_ID["user_id"] = user_id
    return user_id


async def _call_webmaster(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation", "")).strip()
    headers = _webmaster_headers()
    base_url = os.getenv(
        "YANDEX_WEBMASTER_API_BASE_URL", "https://api.webmaster.yandex.net"
    ).rstrip("/")
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))
    params = _route_params(route, arguments)

    async with httpx.AsyncClient(timeout=timeout) as client:
        user_id = await _webmaster_user_id(client, base_url, headers)
        hosts_prefix = f"v4/user/{user_id}/hosts"

        if operation == "list_hosts":
            path = hosts_prefix
        elif operation in {"host_summary", "search_queries_popular"}:
            host_id = str(arguments.get("host_id") or "").strip()
            if not host_id:
                raise BackendRouteError(f"Yandex Webmaster route {route.get('name')} requires host_id")
            quoted_host_id = quote(host_id, safe="")
            if operation == "host_summary":
                path = f"{hosts_prefix}/{quoted_host_id}/summary"
            else:
                path = f"{hosts_prefix}/{quoted_host_id}/search-queries/popular"
        else:
            raise BackendRouteError(f"Unsupported Yandex Webmaster operation: {operation or '<missing>'}")

        response = await client.get(f"{base_url}/{path}", headers=headers, params=params or None)

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "webmaster",
        "method": "GET",
        "path": path,
        "data": _json_or_text(response),
    }
