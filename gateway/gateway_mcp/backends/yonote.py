import os
from typing import Any
from uuid import uuid4

import httpx

from gateway_mcp.backends.common import (
    BackendConfigError,
    BackendRouteError,
    _clean_args,
)
from gateway_mcp.services.managed_integrations import integration_value


def _first_argument(arguments: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = arguments.get(name)
        if value is not None and value != "":
            return value
    return None


def _required_argument(arguments: dict[str, Any], *names: str) -> Any:
    value = _first_argument(arguments, *names)
    if value is None:
        raise BackendRouteError(f"Missing required Yonote argument: {'/'.join(names)}")
    return value


def _raw_transaction_body(arguments: dict[str, Any]) -> dict[str, Any]:
    body = _first_argument(arguments, "body", "transactions", "transaction")
    if isinstance(body, dict):
        return body

    cleaned = _clean_args(arguments)
    if cleaned and all(isinstance(value, list) for value in cleaned.values()):
        return cleaned

    raise BackendRouteError(
        "Yonote database transaction requires body, transactions, or a direct database-id-to-operations object"
    )


def _database_id(arguments: dict[str, Any]) -> str:
    return str(_required_argument(arguments, "database_id", "databaseId", "parentDocumentId"))


def _row_id(arguments: dict[str, Any]) -> str:
    return str(_required_argument(arguments, "row_id", "rowId", "id"))


def _transaction(database_id: str, path: str, op: str, value: Any) -> dict[str, Any]:
    return {
        database_id: [
            {
                "path": path,
                "op": op,
                "val": value,
            }
        ]
    }


def _build_yonote_body(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    route_name = str(route.get("name") or "")

    if route_name == "yonote.database.transaction":
        return _raw_transaction_body(arguments)

    if route_name == "yonote.database.rows.update_title":
        database_id = _database_id(arguments)
        row_id = _row_id(arguments)
        title = _required_argument(arguments, "title")
        return _transaction(database_id, f"rows.{row_id}.title", "update", title)

    if route_name == "yonote.database.rows.update_values":
        database_id = _database_id(arguments)
        row_id = _row_id(arguments)
        values = _first_argument(arguments, "values")
        if values is None:
            field_id = _required_argument(arguments, "field_id", "fieldId", "property_id", "propertyId")
            values = {str(field_id): _required_argument(arguments, "value")}
        if not isinstance(values, dict):
            raise BackendRouteError("Yonote database row values must be an object")
        return _transaction(database_id, f"rows.{row_id}.values", "update", values)

    if route_name == "yonote.database.rows.create":
        database_id = _database_id(arguments)
        row = _required_argument(arguments, "row")
        if not isinstance(row, dict):
            raise BackendRouteError("Yonote database row create requires row object")
        row_id = str(_first_argument(arguments, "row_id", "rowId") or row.get("id") or uuid4())
        if "id" not in row:
            row = {**row, "id": row_id}
        return _transaction(database_id, f"rows.{row_id}", "add", row)

    if route_name == "yonote.database.rows.delete":
        database_id = _database_id(arguments)
        row_id = _row_id(arguments)
        return _transaction(database_id, f"rows.{row_id}", "remove", None)

    return _clean_args(arguments)


async def _call_yonote(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    method = route.get("rpc_method")
    if not method:
        raise BackendRouteError(f"Yonote route {route.get('name')} has no rpc_method")

    body = _build_yonote_body(route, arguments)
    base_url = integration_value("yonote", "YONOTE_BASE_URL", "https://wiki.example.com").rstrip("/")
    api_key = integration_value("yonote", "YONOTE_API_KEY")
    if not api_key:
        raise BackendConfigError("Yonote managed integration is not configured")
    url = f"{base_url}/api/{str(method).strip().lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=body)

    try:
        data: Any = response.json()
    except ValueError:
        data = {"raw": response.text}

    return {
        "ok": bool(data.get("ok", response.is_success)) if isinstance(data, dict) else response.is_success,
        "status": response.status_code,
        "backend": "yonote",
        "method": method,
        "data": data,
    }
