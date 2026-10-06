from typing import Any

from gateway_mcp.services.access_common import normalize_action, normalize_system

def infer_route_access(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, str]:
    scope = str(route.get("scope") or "")
    system = normalize_system(scope.split(":", 1)[0] if ":" in scope else route.get("backend") or "")
    action = normalize_action(scope.split(":", 1)[1] if ":" in scope else "")
    resource_type = ""
    resource = "*"

    route_name = str(route.get("name") or "")
    if system == "yandex_disk":
        resource_type = "path"
        resource = _first_arg(arguments, "path", "from", "to", "src_path", "dst_path") or "*"
    elif system == "google_sheets":
        resource_type = "spreadsheet"
        resource = _first_arg(arguments, "spreadsheet_id") or "*"
    elif system == "google_docs":
        resource_type = "document"
        resource = _first_arg(arguments, "document_id") or "*"
    elif system == "google_drive":
        resource_type = "file"
        resource = _first_arg(arguments, "file_id") or _first_arg(arguments, "q") or "*"
    elif system == "gitlab":
        project_id = _first_arg(arguments, "project_id", "id")
        file_path = _first_arg(arguments, "file_path")
        resource_type = "project"
        resource = str(project_id or "*")
        if file_path:
            resource = f"{resource}:{file_path}"
            resource_type = "file"
    elif system == "tracker":
        resource_type = "issue"
        resource = _first_arg(arguments, "issue_key", "issueId", "key", "queue") or "*"
    elif system == "yonote":
        resource_type = "document"
        resource = _first_arg(arguments, "document_id", "id", "shareId", "query") or "*"
    elif system == "telegram":
        resource_type = "chat"
        resource = _first_arg(arguments, "chat_id") or "*"
    elif system == "bitrix24":
        resource_type = "crm"
        resource = _bitrix_resource(route_name, arguments)
    elif system == "calendar":
        resource_type = "calendar"
        resource = _first_arg(arguments, "calendar_index", "calendar") or "*"
    elif system == "openrouter":
        resource_type = "model"
        resource = _first_arg(arguments, "model") or "*"
    elif system == "notifications":
        resource_type = "channel"
        resource = _first_arg(arguments, "channel") or "comind_skill_update"
    elif system == "skills":
        resource_type = "skill"
        resource = _first_arg(arguments, "skill", "pack") or "*"
    elif system == "infra":
        resource_type = "server"
        resource = _first_arg(arguments, "server_id", "id", "credential_handle") or "*"

    return {
        "system": system,
        "action": action,
        "resource_type": resource_type,
        "resource": str(resource),
    }


def _first_arg(arguments: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = arguments.get(key)
        if value is not None and value != "":
            return value
    body = arguments.get("body") if isinstance(arguments.get("body"), dict) else {}
    params = arguments.get("params") if isinstance(arguments.get("params"), dict) else {}
    for nested in (body, params):
        for key in keys:
            value = nested.get(key)
            if value is not None and value != "":
                return value
    return None


def _bitrix_resource(route_name: str, arguments: dict[str, Any]) -> str:
    entity = route_name.split(".")[1] if "." in route_name else "crm"
    params = arguments.get("params") if isinstance(arguments.get("params"), dict) else {}
    filters = params.get("filter") if isinstance(params.get("filter"), dict) else {}
    identifier = _first_arg(arguments, "id", "ID") or filters.get("ID") or "*"
    return f"{entity}:{identifier}"
