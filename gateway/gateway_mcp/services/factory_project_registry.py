from __future__ import annotations

from pathlib import Path
from typing import Any

from gateway_mcp.config import factory_projects_file, read_json
from gateway_mcp.services import storage_factory


def load_factory_project_registry(path: Path | None = None) -> dict[str, Any]:
    data = read_json(path or factory_projects_file(), {})
    if not isinstance(data, dict):
        return {"projects": [], "queue_fallback": {}}
    projects = data.get("projects")
    fallback = data.get("queue_fallback")
    result = {
        "schema_version": str(data.get("schema_version") or "1.0"),
        "projects": [dict(item) for item in projects if isinstance(item, dict)]
        if isinstance(projects, list)
        else [],
        "queue_fallback": dict(fallback) if isinstance(fallback, dict) else {},
    }
    if path is None:
        stored = {
            row["project_id"]: dict(row["config"])
            for row in storage_factory.list_projects()
        }
        result["projects"] = [
            item for item in result["projects"] if item.get("project_id") not in stored
        ]
        result["projects"] = list(stored.values()) + result["projects"]
    return result


def tracker_project_identity(issue: dict[str, Any]) -> dict[str, str]:
    project = issue.get("project") if isinstance(issue.get("project"), dict) else {}
    primary = project.get("primary")
    if isinstance(primary, dict):
        return {
            "id": str(primary.get("id") or primary.get("shortId") or "").strip(),
            "name": str(primary.get("display") or primary.get("name") or "").strip(),
        }
    if primary:
        return {"id": str(primary).strip(), "name": ""}
    return {"id": "", "name": ""}


def find_project_by_tracker_project(
    registry: dict[str, Any],
    tracker_project: dict[str, str],
) -> dict[str, Any] | None:
    tracker_id = tracker_project.get("id", "").casefold()
    tracker_name = tracker_project.get("name", "").casefold()
    if not tracker_id and not tracker_name:
        return None
    key = "tracker_project_id" if tracker_id else "tracker_project_name"
    needle = tracker_id or tracker_name
    for project in registry.get("projects", []):
        candidate = str(project.get(key) or "").strip().casefold()
        if candidate == needle:
            return dict(project)
    return None


def find_project_by_id(
    registry: dict[str, Any], project_id: str
) -> dict[str, Any] | None:
    needle = str(project_id or "").strip().casefold()
    if not needle:
        return None
    for project in registry.get("projects", []):
        if str(project.get("project_id") or "").strip().casefold() == needle:
            return dict(project)
    return None


def queue_fallback_allowed(registry: dict[str, Any], tracker_queue: str) -> bool:
    policy = registry.get("queue_fallback")
    if (
        not isinstance(policy, dict)
        or str(policy.get("mode") or "").casefold() != "allowlist"
    ):
        return False
    queue = str(tracker_queue or "").strip().casefold()
    allowed = policy.get("queues")
    if not queue or not isinstance(allowed, list):
        return False
    return queue in {str(item).strip().casefold() for item in allowed}
