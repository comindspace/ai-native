import json
import os
from pathlib import Path
from typing import Any

from gateway_mcp.config import root

SOURCE_OF_TRUTH_ITEMS = [
    {
        "domain": "people_roles",
        "sources": ["HR system/table", "Yonote"],
        "description": "Employees, roles, teams, responsibilities, and reporting lines.",
    },
    {
        "domain": "projects_clients",
        "sources": ["Tracker", "Yonote", "Bitrix24"],
        "description": "Active projects, clients, delivery state, client context, and commercial context.",
    },
    {
        "domain": "processes",
        "sources": ["Yonote process index"],
        "description": "Canonical company processes, playbooks, and operating rules.",
    },
    {
        "domain": "documents",
        "sources": ["Yandex Disk", "Yonote"],
        "description": "Working documents, files, presentations, contracts, and document source pages.",
    },
    {
        "domain": "decisions_adr",
        "sources": ["Yonote", "GitLab"],
        "description": "Architecture decisions, process decisions, and repository ADRs.",
    },
    {
        "domain": "operational_activity",
        "sources": ["Tracker", "Telegram", "Calendar"],
        "description": "Current tasks, discussions, meetings, blockers, and operational events.",
    },
]


def company_yonote_index_id() -> str:
    return os.getenv("GATEWAY_COMPANY_YONOTE_INDEX_ID", "").strip()


def company_yonote_index_query() -> str:
    return os.getenv("GATEWAY_COMPANY_YONOTE_INDEX_QUERY", "Company Context Index").strip()


def _route_by_name(tools_registry: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((item for item in tools_registry.get("tools", []) if item.get("name") == name), None)


def _typed_query(query: str, kind: str) -> str:
    normalized_query = str(query or "").strip()
    normalized_kind = _normalized_kind(kind)
    if normalized_kind and normalized_query:
        return f"{normalized_kind} {normalized_query}"
    if normalized_kind:
        return normalized_kind
    return normalized_query


def _normalized_kind(kind: str) -> str:
    return str(kind or "").strip().casefold().replace("_", "-")


def _source_domains_for_kind(kind: str) -> list[dict[str, Any]]:
    domains = _domains_for_kind(kind)
    return [item for item in SOURCE_OF_TRUTH_ITEMS if item["domain"] in domains] if domains else SOURCE_OF_TRUTH_ITEMS


def _domains_for_kind(kind: str) -> list[str]:
    aliases = {
        "person": "people_roles",
        "people": "people_roles",
        "employee": "people_roles",
        "role": "people_roles",
        "team": "people_roles",
        "project": "projects_clients",
        "client": "projects_clients",
        "process": "processes",
        "document": "documents",
        "page": "documents",
        "decision": "decisions_adr",
        "adr": "decisions_adr",
        "task": "operational_activity",
        "meeting": "operational_activity",
        "activity": "operational_activity",
        "operation": "operational_activity",
        "operations": "operational_activity",
    }
    domain = aliases.get(kind)
    return [domain] if domain else []


def _missing_yonote_route(route_name: str) -> dict[str, Any]:
    return {
        "provider": "yonote",
        "source_type": "remote",
        "uri": route_name,
        "title": f"{route_name} is not configured",
        "error": "missing_route",
    }


def _remote_error(provider: str, route_name: str, exc: Exception) -> dict[str, Any]:
    return {
        "provider": provider,
        "source_type": "remote",
        "uri": route_name,
        "title": f"{route_name} failed",
        "error": exc.__class__.__name__,
    }


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
