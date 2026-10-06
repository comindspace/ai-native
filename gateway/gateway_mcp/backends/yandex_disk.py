import os
from typing import Any

import httpx

from gateway_mcp.backends.common import _format_path, _json_or_text, _route_body, _route_params, _yandex_user_token

def _yandex_disk_headers() -> dict[str, str]:
    return {
        "Authorization": f"OAuth {_yandex_user_token('yandex-disk')}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _call_yandex_disk(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    http_method = str(route.get("http_method", "GET")).upper()
    path = str(route.get("path", "")).strip()
    if not path:
        raise BackendRouteError(f"Yandex Disk route {route.get('name')} has no path")

    params = _route_params(route, arguments)
    body = _route_body(route, arguments)
    base_url = os.getenv("YANDEX_DISK_API_BASE_URL", "https://cloud-api.yandex.net/v1/disk").rstrip("/")
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            http_method,
            f"{base_url}/{path.lstrip('/')}",
            headers=_yandex_disk_headers(),
            params=params or None,
            json=body if http_method in {"POST", "PATCH", "PUT"} and body else None,
        )

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "yandex-disk",
        "method": http_method,
        "path": path,
        "data": _json_or_text(response),
    }
