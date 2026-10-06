import os
from typing import Any

import httpx

from gateway_mcp.backends.common import (
    BackendConfigError,
    BackendRouteError,
    _json_or_text,
)


def _wordstat_api_key() -> str:
    key = os.getenv("GATEWAY_WORDSTAT_API_KEY", "")
    if key:
        return key
    raise BackendConfigError(
        "No Yandex Cloud API key for Wordstat. Set GATEWAY_WORDSTAT_API_KEY on the Gateway host."
    )


def _wordstat_headers() -> dict[str, str]:
    return {
        "Authorization": f"Api-Key {_wordstat_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


_VALID_PERIODS = {
    "monthly": "PERIOD_MONTHLY",
    "weekly": "PERIOD_WEEKLY",
    "daily": "PERIOD_DAILY",
    "period_monthly": "PERIOD_MONTHLY",
    "period_weekly": "PERIOD_WEEKLY",
    "period_daily": "PERIOD_DAILY",
}


def _normalize_period(raw: Any) -> str:
    value = str(raw or "").strip().upper()
    if value in _VALID_PERIODS.values():
        return value
    mapped = _VALID_PERIODS.get(str(raw or "").strip().lower(), "")
    if not mapped:
        raise BackendRouteError(
            "Wordstat dynamics requires period: monthly, weekly or daily."
        )
    return mapped


def _normalize_devices(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        items = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(item).strip() for item in raw]
    else:
        raise BackendRouteError("Wordstat devices must be a list or comma-separated string.")
    valid = {"DEVICE_ALL", "DEVICE_DESKTOP", "DEVICE_PHONE", "DEVICE_TABLET"}
    devices: list[str] = []
    for item in items:
        if not item:
            continue
        value = item.upper()
        if not value.startswith("DEVICE_"):
            value = f"DEVICE_{value}"
        if value not in valid:
            raise BackendRouteError(f"Unsupported Wordstat device: {item}")
        devices.append(value)
    return devices


def _normalize_regions(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        items = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(item).strip() for item in raw]
    else:
        raise BackendRouteError("Wordstat regions must be a list or comma-separated string.")
    return [item for item in items if item]


def _require_phrase(arguments: dict[str, Any], route_name: str) -> str:
    phrase = str(arguments.get("phrase") or arguments.get("keyword") or "").strip()
    if not phrase:
        raise BackendRouteError(f"Yandex Wordstat route {route_name} requires phrase.")
    return phrase


async def _call_wordstat(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation", "")).strip()
    base_url = os.getenv(
        "GATEWAY_WORDSTAT_API_BASE_URL", "https://searchapi.api.cloud.yandex.net"
    ).rstrip("/")
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))
    headers = _wordstat_headers()

    body: dict[str, Any] = {}
    if operation in {"top_requests", "dynamics", "regions_distribution"}:
        body["phrase"] = _require_phrase(arguments, str(route.get("name", operation)))
        regions = _normalize_regions(arguments.get("regions"))
        if regions:
            body["regions"] = regions
        devices = _normalize_devices(arguments.get("devices"))
        if devices:
            body["devices"] = devices
    elif operation != "regions_tree":
        raise BackendRouteError(f"Unsupported Yandex Wordstat operation: {operation or '<missing>'}")

    if operation == "top_requests":
        path = "/v2/wordstat/topRequests"
        num_phrases = arguments.get("num_phrases") or arguments.get("numPhrases")
        if num_phrases is not None:
            try:
                body["numPhrases"] = int(num_phrases)
            except (TypeError, ValueError):
                raise BackendRouteError("Wordstat num_phrases must be an integer.")
    elif operation == "dynamics":
        path = "/v2/wordstat/dynamics"
        body["period"] = _normalize_period(arguments.get("period"))
        from_date = str(arguments.get("from_date") or arguments.get("fromDate") or "").strip()
        if not from_date:
            raise BackendRouteError("Wordstat dynamics requires from_date (YYYY-MM-DD).")
        body["fromDate"] = from_date
        to_date = str(arguments.get("to_date") or arguments.get("toDate") or "").strip()
        if to_date:
            body["toDate"] = to_date
    elif operation == "regions_distribution":
        path = "/v2/wordstat/regions"
    else:
        path = "/v2/wordstat/getRegionsTree"

    folder_id = (
        str(arguments.get("folder_id") or arguments.get("folderId") or "").strip()
        or os.getenv("GATEWAY_WORDSTAT_FOLDER_ID", "").strip()
    )
    if folder_id:
        body["folderId"] = folder_id

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}{path}", headers=headers, json=body)

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "wordstat",
        "method": "POST",
        "path": path,
        "request_body": {k: v for k, v in body.items() if k != "phrase"},
        "phrase": body.get("phrase"),
        "data": _json_or_text(response),
    }
