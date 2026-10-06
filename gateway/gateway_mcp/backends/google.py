import base64
import os
from typing import Any
from urllib.parse import quote

import httpx

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError, _json_or_text, _route_body, _route_params


async def _google_access_token() -> str:
    from gateway_mcp.services.auth import current_actor, refresh_google_access_token
    from gateway_mcp.services.storage import get_user_oauth_token

    actor = current_actor()
    credential = get_user_oauth_token("google", actor.subject)
    if not credential or not credential.get("access_token"):
        raise BackendConfigError("No Google OAuth token for current user. Open /credentials and connect Google.")

    token_payload = await refresh_google_access_token(str(credential["access_token"]))
    return str(token_payload["access_token"])


def _google_api_base(route: dict[str, Any]) -> str:
    api = str(route.get("google_api") or "").strip()
    if api == "sheets":
        return os.getenv("GOOGLE_SHEETS_API_BASE_URL", "https://sheets.googleapis.com/v4/spreadsheets").rstrip("/")
    if api == "drive":
        return os.getenv("GOOGLE_DRIVE_API_BASE_URL", "https://www.googleapis.com/drive/v3").rstrip("/")
    if api == "docs":
        return os.getenv("GOOGLE_DOCS_API_BASE_URL", "https://docs.googleapis.com/v1").rstrip("/")
    raise BackendRouteError(f"Google route {route.get('name')} has unsupported google_api: {api or '<missing>'}")


def _format_google_path(path_template: str, route: dict[str, Any], arguments: dict[str, Any]) -> str:
    path_args = {}
    for key in route.get("path_args", []):
        if key not in arguments or arguments[key] in {None, ""}:
            raise BackendRouteError(f"Missing path argument: {key}")
        path_args[key] = quote(str(arguments[key]), safe="")
    try:
        return path_template.format(**path_args)
    except KeyError as exc:
        raise BackendRouteError(f"Missing path argument: {exc.args[0]}") from exc


async def _call_google(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    http_method = str(route.get("http_method", "GET")).upper()
    path_template = str(route.get("path", "")).strip()
    if not path_template:
        raise BackendRouteError(f"Google route {route.get('name')} has no path")

    path = _format_google_path(path_template, route, arguments)
    params = {**dict(route.get("fixed_query") or {}), **_route_params(route, arguments)}
    body = _route_body(route, arguments)
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))
    token = await _google_access_token()

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            http_method,
            f"{_google_api_base(route)}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            params=params or None,
            json=body if http_method in {"POST", "PATCH", "PUT"} and body else None,
        )

    data: Any
    if route.get("binary_response"):
        data = {
            "content_base64": base64.b64encode(response.content).decode("ascii"),
            "content_type": response.headers.get("content-type", ""),
            "size": len(response.content),
        }
    else:
        data = _json_or_text(response)

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": str(route.get("backend") or "google"),
        "method": http_method,
        "path": path_template,
        "data": data,
    }
