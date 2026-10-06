import json
import os
from typing import Any

import httpx

from gateway_mcp.backends.common import (
    BackendConfigError,
    BackendRouteError,
    _bool_env,
    _yandex_user_token,
)
from gateway_mcp.services.managed_integrations import integration_value


def _tracker_headers(actor_subject: str | None = None) -> dict[str, str]:
    iam_token = os.getenv("TRACKER_IAM_TOKEN", "")

    try:
        if actor_subject is None:
            token = _yandex_user_token()
        else:
            from gateway_mcp.services.storage import get_user_oauth_token

            credential = get_user_oauth_token("yandex", actor_subject)
            token = str((credential or {}).get("access_token") or "")
            if not token:
                raise BackendConfigError("No Yandex OAuth token for current user. Open /credentials.")
        authorization = f"OAuth {token}"
    except BackendConfigError:
        if not (_bool_env("GATEWAY_ALLOW_SERVER_YANDEX_TOKENS", False) and iam_token):
            raise
        authorization = f"Bearer {iam_token}"

    headers = {
        "Authorization": authorization,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    org_id = integration_value("tracker", "TRACKER_ORG_ID")
    cloud_org_id = integration_value("tracker", "TRACKER_CLOUD_ORG_ID")
    if org_id and cloud_org_id:
        raise BackendConfigError("Only one of TRACKER_ORG_ID or TRACKER_CLOUD_ORG_ID should be set")
    if org_id:
        headers["X-Org-ID"] = org_id
    elif cloud_org_id:
        headers["X-Cloud-Org-ID"] = cloud_org_id
    else:
        raise BackendConfigError("Missing TRACKER_ORG_ID or TRACKER_CLOUD_ORG_ID")
    return headers


def _format_path(path_template: str, arguments: dict[str, Any]) -> str:
    path_args = {key: str(value) for key, value in arguments.items() if value is not None}
    try:
        return path_template.format(**path_args)
    except KeyError as exc:
        raise BackendRouteError(f"Missing path argument: {exc.args[0]}") from exc


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        text = response.text
        try:
            return json.loads(text)
        except ValueError:
            return text


def _route_params(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    query_arg_names = set(route.get("query_args", []))
    return {
        key: value
        for key, value in arguments.items()
        if key in query_arg_names and value is not None and value != ""
    }


def _route_body(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    query_arg_names = set(route.get("query_args", []))
    path_arg_names = set(route.get("path_args", []))
    body_arg_name = route.get("body_arg")
    if body_arg_name and isinstance(arguments.get(body_arg_name), dict):
        return dict(arguments[body_arg_name])
    excluded = query_arg_names | path_arg_names
    return {
        key: value
        for key, value in arguments.items()
        if key not in excluded and value is not None and value != ""
    }


async def _call_tracker(
    route: dict[str, Any], arguments: dict[str, Any], *, actor_subject: str | None = None
) -> dict[str, Any]:
    http_method = str(route.get("http_method", "GET")).upper()
    path = _format_path(str(route.get("path", "")), arguments)
    if not path:
        raise BackendRouteError(f"Tracker route {route.get('name')} has no path")

    query_arg_names = set(route.get("query_args", []))
    path_arg_names = set(route.get("path_args", []))
    body_arg_name = route.get("body_arg")

    params = {
        key: value
        for key, value in arguments.items()
        if key in query_arg_names and value is not None and value != ""
    }

    if body_arg_name and isinstance(arguments.get(body_arg_name), dict):
        body = dict(arguments[body_arg_name])
    else:
        excluded = query_arg_names | path_arg_names
        body = {
            key: value
            for key, value in arguments.items()
            if key not in excluded and value is not None and value != ""
        }

    base_url = integration_value("tracker", "TRACKER_API_BASE_URL", "https://api.tracker.yandex.net").rstrip("/")
    url = f"{base_url}/{path.lstrip('/')}"
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            http_method,
            url,
            headers=_tracker_headers(actor_subject),
            params=params or None,
            json=body if http_method in {"POST", "PATCH", "PUT"} else None,
        )

    try:
        data: Any = response.json()
    except ValueError:
        text = response.text
        try:
            data = json.loads(text)
        except ValueError:
            data = text

    response_headers = getattr(response, "headers", {})
    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "yandex-tracker",
        "method": http_method,
        "path": path,
        "data": data,
        "total_count": response_headers.get("X-Total-Count"),
        "total_pages": response_headers.get("X-Total-Pages"),
    }
