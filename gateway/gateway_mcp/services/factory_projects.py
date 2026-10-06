from __future__ import annotations

import re
from typing import Any

from gateway_mcp.backends import call_backend
from gateway_mcp.services import storage_factory
from gateway_mcp.services.access import require_resource_access
from gateway_mcp.services.auth import require_scope
from gateway_mcp.services.factory_admin import public_project
from gateway_mcp.services.factory_project_registry import (
    find_project_by_id,
    find_project_by_tracker_project,
    load_factory_project_registry,
    queue_fallback_allowed,
    tracker_project_identity,
)
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.managed_integrations import integration_value
from gateway_mcp.services.work import _require_project_access, get_work

DEFAULT_ALLOWED_ACTIONS = {
    "can_create_worktree": True,
    "can_create_branch": True,
    "can_commit": True,
    "can_push_branch": True,
    "can_create_mr": True,
    "can_comment": True,
    "can_merge": False,
    "can_deploy": False,
    "can_change_secrets": False,
    "can_change_permissions": False,
    "can_run_destructive_migrations": False,
}


async def discover_factory_projects(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    query: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    normalized_limit = _limit(limit)
    errors: list[dict[str, str]] = []
    projects: list[dict[str, Any]] = []

    for row in storage_factory.list_projects():
        config = row["config"]
        if (
            query
            and query.casefold()
            not in f"{row['project_id']} {config.get('name', '')} {config.get('project_path', '')}".casefold()
        ):
            continue
        try:
            _require_project_access(actor, "read", row["project_id"])
        except PermissionError:
            continue
        projects.append(_stored_runtime(row))

    tracker_queues = await _safe_backend(
        actor=actor,
        tools_registry=tools_registry,
        route_name="tracker.queues.list",
        arguments={"perPage": normalized_limit},
        errors=errors,
    )
    for queue in _items(tracker_queues):
        key = str(queue.get("key") or "").strip()
        if not key:
            continue
        title = str(queue.get("display") or queue.get("name") or key).strip()
        if query and query.casefold() not in f"{key} {title}".casefold():
            continue
        projects.append(
            _runtime_config(
                project_id=_slug(key),
                name=title,
                tracker_queue=key,
                source="tracker",
            )
        )

    gitlab_query = query.strip()
    gitlab_projects = await _safe_backend(
        actor=actor,
        tools_registry=tools_registry,
        route_name="gitlab.projects.search",
        arguments={
            "search": gitlab_query,
            "membership": True,
            "simple": True,
            "per_page": normalized_limit,
        },
        errors=errors,
    )
    for project in _items(gitlab_projects):
        path = str(
            project.get("path_with_namespace") or project.get("path") or ""
        ).strip()
        name = str(project.get("name") or path or project.get("id") or "").strip()
        if not name:
            continue
        projects.append(
            _runtime_config(
                project_id=_slug(path or name),
                name=name,
                gitlab_project=project.get("id") or path,
                gitlab_project_path=path,
                gitlab_clone_url=str(project.get("http_url_to_repo") or "").strip(),
                gitlab_web_url=str(project.get("web_url") or "").strip(),
                default_branch=str(project.get("default_branch") or "main"),
                source="gitlab",
            )
        )

    discovered = _dedupe_projects(projects)[:normalized_limit]
    for project in discovered:
        if project.get("source") != "registered":
            project["readiness_gaps"] = _readiness_gaps(project)

    return {
        "projects": discovered,
        "count": len(discovered),
        "errors": errors,
    }


async def resolve_factory_project_by_issue(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    issue_id: str,
    allow_queue_fallback: bool = False,
) -> dict[str, Any]:
    issue_key = str(issue_id or "").strip()
    if not issue_key:
        raise ValueError("issue_id is required")

    issue_result = await _authorized_backend(
        actor=actor,
        tools_registry=tools_registry,
        route_name="tracker.issues.get",
        arguments={"issue_id": issue_key},
    )
    issue = issue_result.get("data") if isinstance(issue_result, dict) else {}
    if not isinstance(issue, dict):
        issue = {}

    queue = _issue_queue(issue, issue_key)
    description = str(issue.get("description") or "")
    summary = str(issue.get("summary") or issue_key)
    tracker_project = tracker_project_identity(issue)
    registry = load_factory_project_registry()
    registered_project = find_project_by_tracker_project(registry, tracker_project)
    if registered_project:
        _require_project_access(
            actor, "read", str(registered_project.get("project_id") or "").casefold()
        )
    if registered_project:
        stored = storage_factory.get_project(
            str(registered_project.get("project_id") or "")
        )
        if stored:
            _require_project_access(actor, "read", stored["project_id"])
            config = _stored_runtime(stored)
            config["tracker_queue"] = config.get("tracker_queue") or queue
            config["reviewer"] = config.get("reviewer") or _reviewer(issue)
            config["issue"] = {
                "key": issue.get("key") or issue_key,
                "summary": summary,
                "status": _display(issue.get("status")),
            }
            config["yonote_links"] = _extract_yonote_links(description)
            config["readiness_gaps"] = list(
                dict.fromkeys(
                    config["readiness_gaps"]
                    + _readiness_gaps(config, tracker_project_required=True)
                )
            )
            _finalize_readiness(config)
            return {"project": config, "errors": []}
    tracker_project_present = bool(tracker_project["id"] or tracker_project["name"])
    use_queue_fallback = (
        allow_queue_fallback
        and registered_project is None
        and not tracker_project_present
        and queue_fallback_allowed(registry, queue)
    )
    if registered_project is not None:
        gitlab_hint = str(
            registered_project.get("gitlab_project")
            or registered_project.get("gitlab_project_path")
            or ""
        ).strip()
    elif use_queue_fallback:
        gitlab_hint = _extract_gitlab_project_hint(description)
    else:
        gitlab_hint = ""
    yonote_links = _merge_links(
        (registered_project or {}).get("yonote_links"),
        _extract_yonote_links(description),
    )

    errors: list[dict[str, str]] = []
    gitlab_project = None
    if gitlab_hint:
        gitlab_project = await _safe_backend(
            actor=actor,
            tools_registry=tools_registry,
            route_name="gitlab.project.get",
            arguments={"project_id": gitlab_hint},
            errors=errors,
        )
    # A registered Tracker Project without a repository mapping stays a gap.
    # Name-based GitLab discovery is allowed only for explicit legacy fallback.
    if not _ok(gitlab_project) and use_queue_fallback:
        search_query = gitlab_hint or summary or queue
        gitlab_search = await _safe_backend(
            actor=actor,
            tools_registry=tools_registry,
            route_name="gitlab.projects.search",
            arguments={
                "search": search_query,
                "membership": True,
                "simple": True,
                "per_page": 5,
            },
            errors=errors,
        )
        gitlab_project = _first_item(gitlab_search)

    gitlab_data = _route_data(gitlab_project)
    if isinstance(gitlab_data, list):
        gitlab_data = gitlab_data[0] if gitlab_data else {}
    if not isinstance(gitlab_data, dict):
        gitlab_data = {}

    if registered_project is not None:
        resolved_project_id = str(registered_project.get("project_id") or "")
        resolved_project_name = str(registered_project.get("name") or "")
    elif use_queue_fallback:
        resolved_project_id = _project_id(queue, gitlab_data, summary)
        resolved_project_name = _project_name(issue, gitlab_data, queue)
    else:
        resolved_project_id = (
            f"tracker-project-{_slug(tracker_project['id'])}"
            if tracker_project["id"]
            else "unresolved-tracker-project"
        )
        resolved_project_name = tracker_project["name"] or summary

    config = _runtime_config(
        project_id=resolved_project_id,
        name=resolved_project_name,
        tracker_queue=str((registered_project or {}).get("tracker_queue") or queue),
        tracker_project_id=tracker_project["id"],
        tracker_project_name=tracker_project["name"],
        tracker_project_status=(
            "mapped"
            if registered_project is not None
            else "unknown"
            if tracker_project["id"] or tracker_project["name"]
            else "missing"
        ),
        project_resolution_source=(
            "tracker_project"
            if registered_project is not None
            else "queue_fallback"
            if use_queue_fallback
            else "unresolved"
        ),
        gitlab_project=gitlab_data.get("id") or gitlab_hint,
        gitlab_project_path=str(
            gitlab_data.get("path_with_namespace") or gitlab_hint or ""
        ).strip(),
        gitlab_clone_url=str(gitlab_data.get("http_url_to_repo") or "").strip(),
        gitlab_web_url=str(gitlab_data.get("web_url") or "").strip(),
        default_branch=str(gitlab_data.get("default_branch") or "main"),
        yonote_project_name=str(
            (registered_project or {}).get("yonote_project_name")
            or _yonote_project_name(yonote_links, queue)
        ),
        reviewer=str((registered_project or {}).get("reviewer") or _reviewer(issue)),
        source="tracker_issue",
    )
    config["issue"] = {
        "key": issue.get("key") or issue_key,
        "summary": summary,
        "status": _display(issue.get("status")),
        "assignee": _display(issue.get("assignee")),
        "created_by": _display(issue.get("createdBy")),
        "updated_by": _display(issue.get("updatedBy")),
    }
    config["yonote_links"] = yonote_links
    config["readiness_gaps"] = _readiness_gaps(config, tracker_project_required=True)
    return {"project": config, "errors": errors}


async def get_factory_runtime_config(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    issue_id: str = "",
    work_id: str = "",
    project_id: str = "",
    tracker_queue: str = "",
    allow_queue_fallback: bool = False,
) -> dict[str, Any]:
    if issue_id.strip():
        return await resolve_factory_project_by_issue(
            actor=actor,
            tools_registry=tools_registry,
            issue_id=issue_id,
            allow_queue_fallback=allow_queue_fallback,
        )

    work: dict[str, Any] = {}
    if work_id.strip():
        work = get_work(actor, work_id.strip(), include_events=False)

    contract = work.get("contract") if isinstance(work.get("contract"), dict) else {}
    metadata = (
        contract.get("metadata") if isinstance(contract.get("metadata"), dict) else {}
    )
    source_refs = (
        work.get("source_refs") if isinstance(work.get("source_refs"), list) else []
    )
    project_path = str(
        contract.get("project_path") or work.get("project_path") or ""
    ).strip()
    logical_project_id = str(work.get("project_id") or project_id).strip().casefold()
    _require_project_access(actor, "read", logical_project_id or "*")
    stored = storage_factory.get_project(logical_project_id)
    if stored:
        _require_project_access(actor, "read", logical_project_id)
        config = _stored_runtime(stored)
        if work.get("execution_mode") == "factory" and work.get("status") == "running":
            from gateway_mcp.services.factory_preflight import lease_readiness_valid

            if lease_readiness_valid(work, stored):
                config["readiness_gaps"] = [
                    gap for gap in config["readiness_gaps"] if gap != "validation_stale"
                ]
            else:
                config["readiness_gaps"].append("lease_preflight_required")
        config["work_id"] = str(work.get("work_id") or "")
        config["scope_id"] = str(work.get("scope_id") or "")
        if work:
            from gateway_mcp.services.factory_git import enabled as factory_git_enabled

            config["git_transport"] = {
                "mode": "gateway" if factory_git_enabled() else "worker_managed",
                "config_tool": "gateway_factory_git_config"
                if factory_git_enabled()
                else "",
                "worker_environment_verified": False,
            }
            config["reviewer"] = str(
                metadata.get("reviewer")
                or metadata.get("reviewer_role")
                or config.get("reviewer")
                or ""
            )
            config["yonote_project_name"] = _project_context_from_work(
                metadata, source_refs
            ) or config.get("yonote_project_name", "")
            config["readiness_gaps"] = list(
                dict.fromkeys(
                    config["readiness_gaps"]
                    + _readiness_gaps(config, tracker_required=False)
                )
            )
            if project_path and project_path != config["project_path"]:
                config["readiness_gaps"].append("repository_mapping")
        _finalize_readiness(config)
        return {"project": config, "errors": []}
    registry = load_factory_project_registry()
    registered_project = find_project_by_id(registry, logical_project_id)
    # project_id is a logical Gateway id, not an implicit GitLab project key.
    project_ref = str(
        project_path
        or (registered_project or {}).get("gitlab_project")
        or (registered_project or {}).get("gitlab_project_path")
        or ""
    ).strip()
    queue = str(
        tracker_queue
        or (registered_project or {}).get("tracker_queue")
        or _tracker_queue_from_work(work, source_refs)
    ).strip()
    reviewer = str(
        metadata.get("reviewer")
        or metadata.get("reviewer_role")
        or (registered_project or {}).get("reviewer")
        or ""
    ).strip()
    project_context = str(
        _project_context_from_work(metadata, source_refs)
        or (registered_project or {}).get("yonote_project_name")
        or ""
    )

    errors: list[dict[str, str]] = []
    gitlab_project = None
    if project_ref:
        gitlab_project = await _safe_backend(
            actor=actor,
            tools_registry=tools_registry,
            route_name="gitlab.project.get",
            arguments={"project_id": project_ref},
            errors=errors,
        )

    gitlab_data = _route_data(gitlab_project)
    if not isinstance(gitlab_data, dict):
        gitlab_data = {}
    config = _runtime_config(
        project_id=str(
            (registered_project or {}).get("project_id")
            or _slug(
                logical_project_id
                or project_ref
                or queue
                or gitlab_data.get("path_with_namespace")
                or "factory-project"
            )
        ),
        name=str(
            (registered_project or {}).get("name")
            or gitlab_data.get("name")
            or queue
            or logical_project_id
            or project_ref
            or "Factory project"
        ),
        tracker_queue=queue,
        tracker_project_id=str(
            (registered_project or {}).get("tracker_project_id") or ""
        ),
        tracker_project_name=str(
            (registered_project or {}).get("tracker_project_name") or ""
        ),
        tracker_project_status="mapped" if registered_project else "not_checked",
        project_resolution_source="runtime_config"
        if registered_project
        else "runtime_request",
        gitlab_project=gitlab_data.get("id") or project_ref or "",
        gitlab_project_path=str(
            gitlab_data.get("path_with_namespace") or project_ref or ""
        ).strip(),
        gitlab_clone_url=str(gitlab_data.get("http_url_to_repo") or "").strip(),
        gitlab_web_url=str(gitlab_data.get("web_url") or "").strip(),
        default_branch=str(gitlab_data.get("default_branch") or "main"),
        yonote_project_name=project_context,
        reviewer=reviewer,
        source="work_contract" if work else "runtime_request",
    )
    config["work_id"] = str(work.get("work_id") or "")
    config["scope_id"] = str(contract.get("scope_id") or work.get("scope_id") or "")
    config["readiness_gaps"] = _readiness_gaps(config, tracker_required=not bool(work))
    return {"project": config, "errors": errors}


async def _authorized_backend(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    route_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    route = _route_by_name(tools_registry, route_name)
    if route is None:
        raise ValueError(f"unknown gateway route: {route_name}")
    route_scope = str(route.get("scope") or "")
    if route_scope:
        require_scope(route_scope, tool=route_name)
    require_resource_access(actor=actor, route=route, arguments=arguments)
    return await call_backend(route, arguments)


async def _safe_backend(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    route_name: str,
    arguments: dict[str, Any],
    errors: list[dict[str, str]],
) -> Any:
    try:
        return await _authorized_backend(
            actor=actor,
            tools_registry=tools_registry,
            route_name=route_name,
            arguments=arguments,
        )
    except Exception as exc:  # noqa: BLE001 - backend failure is a readiness gap
        errors.append(
            {"route": route_name, "error": exc.__class__.__name__, "message": str(exc)}
        )
        return None


def _runtime_config(
    *,
    project_id: str,
    name: str,
    tracker_queue: str = "",
    tracker_project_id: str = "",
    tracker_project_name: str = "",
    tracker_project_status: str = "not_checked",
    project_resolution_source: str = "",
    gitlab_project: Any = "",
    gitlab_project_path: str = "",
    gitlab_clone_url: str = "",
    gitlab_web_url: str = "",
    default_branch: str = "main",
    yonote_project_name: str = "",
    reviewer: str = "",
    source: str = "",
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "name": name,
        "source": source,
        "tracker_queue": tracker_queue,
        "tracker_project": {
            "id": tracker_project_id,
            "name": tracker_project_name,
            "status": tracker_project_status,
        },
        "project_resolution": {
            "source": project_resolution_source or source,
            "queue_fallback": project_resolution_source == "queue_fallback",
        },
        "gitlab_project": str(gitlab_project or ""),
        "gitlab_project_path": gitlab_project_path,
        "gitlab_clone_url": gitlab_clone_url,
        "gitlab_web_url": gitlab_web_url,
        "default_base_branch": default_branch or "main",
        "mr_target_branch": default_branch or "main",
        "reviewer": reviewer,
        "yonote_project_name": yonote_project_name,
        "slack_channel": "#dev-factory",
        "worker": {
            "max_parallel_jobs": 1,
            "timeout_seconds": 3600,
            "test_command": "",
            "lint_command": "",
            "typecheck_command": "",
        },
        "allowed_actions": dict(DEFAULT_ALLOWED_ACTIONS),
    }


def _stored_runtime(row: dict[str, Any]) -> dict[str, Any]:
    public = public_project(row)
    config = _runtime_config(
        project_id=public["project_id"], name=public.get("name") or public["project_id"]
    )
    config.update(public)
    _finalize_readiness(config)
    return config


def _finalize_readiness(config: dict[str, Any]) -> None:
    gaps = [
        gap
        for gap in config.get("readiness_gaps", [])
        if gap not in {"reviewer", "yonote_project_name"}
    ]
    gaps.extend(_readiness_gaps(config, tracker_required=False))
    config["readiness_gaps"] = list(dict.fromkeys(gaps))
    config["ready"] = not config["readiness_gaps"]
    if isinstance(config.get("validation"), dict):
        config["validation"]["ready"] = config["ready"]
        config["validation"]["readiness_gaps"] = config["readiness_gaps"]


def _route_by_name(
    tools_registry: dict[str, Any], route_name: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in tools_registry.get("tools", [])
            if item.get("name") == route_name
        ),
        None,
    )


def _route_data(result: Any) -> Any:
    if isinstance(result, dict) and "data" in result:
        return result.get("data")
    return result


def _items(result: Any) -> list[dict[str, Any]]:
    data = _route_data(result)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "values", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _first_item(result: Any) -> Any:
    items = _items(result)
    return items[0] if items else result


def _ok(result: Any) -> bool:
    if not isinstance(result, dict):
        return bool(result)
    if result.get("ok") is False:
        return False
    data = result.get("data", result)
    return bool(data)


def _issue_queue(issue: dict[str, Any], issue_key: str) -> str:
    queue = issue.get("queue") if isinstance(issue.get("queue"), dict) else {}
    key = str(queue.get("key") or "").strip()
    if key:
        return key
    if "-" in issue_key:
        return issue_key.split("-", 1)[0]
    return ""


def _gitlab_web_base() -> str:
    api_base = integration_value(
        "gitlab", "GITLAB_API_BASE_URL", "https://gitlab.example.com/api/v4"
    )
    return re.sub(r"/api/v4/?$", "", api_base.rstrip("/"))


def _yonote_web_base() -> str:
    return integration_value("yonote", "YONOTE_BASE_URL", "https://wiki.example.com").rstrip("/")


def _extract_gitlab_project_hint(text: str) -> str:
    gitlab_base = _gitlab_web_base()
    patterns = [
        re.escape(gitlab_base) + r"/([\w.-]+/[\w./-]+?)(?:\.git|[\s)`\]]|$)",
        r"Target repo:\s*([^\s`]+)",
        r"GitLab project:\s*([^\s`]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip().rstrip("/")
        value = re.sub(r"/-/.*$", "", value)
        value = value.removeprefix(gitlab_base + "/")
        return value.removesuffix(".git")
    return ""


def _extract_yonote_links(text: str) -> list[str]:
    links = []
    pattern = re.escape(_yonote_web_base()) + r"/[^\s)`\]]+"
    for match in re.finditer(pattern, text):
        links.append(match.group(0).rstrip(".,"))
    return sorted(set(links))


def _yonote_project_name(links: list[str], queue: str) -> str:
    return links[0] if links else queue


def _project_id(queue: str, gitlab_data: dict[str, Any], fallback: str) -> str:
    if queue:
        return _slug(queue)
    path = str(
        gitlab_data.get("path_with_namespace") or gitlab_data.get("path") or ""
    ).strip()
    return _slug(path or fallback or "factory-project")


def _project_name(
    issue: dict[str, Any], gitlab_data: dict[str, Any], queue: str
) -> str:
    project_name = str(gitlab_data.get("name") or "").strip()
    if project_name:
        return project_name
    queue_data = issue.get("queue") if isinstance(issue.get("queue"), dict) else {}
    return str(
        queue_data.get("display") or queue or issue.get("summary") or "Factory project"
    )


def _reviewer(issue: dict[str, Any]) -> str:
    for key in ("assignee", "updatedBy", "createdBy"):
        value = _display(issue.get(key))
        if value:
            return value
    return ""


def _display(value: Any) -> str:
    if isinstance(value, dict):
        return str(
            value.get("display") or value.get("name") or value.get("login") or ""
        ).strip()
    return str(value or "").strip()


def _readiness_gaps(
    config: dict[str, Any],
    *,
    tracker_required: bool = True,
    tracker_project_required: bool = False,
) -> list[str]:
    gaps = []
    if tracker_required and not config.get("tracker_queue"):
        gaps.append("tracker_queue")
    tracker_project = config.get("tracker_project")
    if tracker_project_required and (
        not isinstance(tracker_project, dict)
        or tracker_project.get("status") != "mapped"
    ):
        gaps.append("tracker_project")
    if not (config.get("gitlab_project") or config.get("gitlab_project_path")):
        gaps.append("gitlab_project")
    if not config.get("gitlab_clone_url"):
        gaps.append("gitlab_clone_url")
    if not config.get("reviewer"):
        gaps.append("reviewer")
    if not config.get("yonote_project_name"):
        gaps.append("yonote_project_name")
    return gaps


def _tracker_queue_from_work(work: dict[str, Any], source_refs: list[Any]) -> str:
    if str(work.get("source_type") or "").casefold() == "tracker":
        queue = _queue_from_reference(str(work.get("source_ref") or ""))
        if queue:
            return queue
    for ref in source_refs:
        if (
            not isinstance(ref, dict)
            or str(ref.get("type") or "").casefold() != "tracker"
        ):
            continue
        queue = _queue_from_reference(str(ref.get("uri") or ""))
        if queue:
            return queue
    return ""


def _queue_from_reference(value: str) -> str:
    match = re.search(
        r"(?:^|/)([A-Z][A-Z0-9_]+)-\d+(?:$|[/?#])", value.strip(), flags=re.IGNORECASE
    )
    return match.group(1).upper() if match else ""


def _project_context_from_work(metadata: dict[str, Any], source_refs: list[Any]) -> str:
    explicit = str(
        metadata.get("project_context_ref") or metadata.get("yonote_project_name") or ""
    ).strip()
    if explicit:
        return explicit
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        ref_type = str(ref.get("type") or "").casefold()
        uri = str(ref.get("uri") or "").strip()
        if (
            ref_type in {"yonote", "project_context", "adr", "scope"}
            or uri.startswith(_yonote_web_base() + "/")
        ):
            return str(ref.get("title") or uri).strip()
    return ""


def _dedupe_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for project in projects:
        key = (
            str(project.get("tracker_queue") or "").casefold(),
            str(
                project.get("gitlab_project")
                or project.get("gitlab_project_path")
                or ""
            ).casefold(),
            str(project.get("name") or "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(project)
    return result


def _merge_links(configured: Any, discovered: list[str]) -> list[str]:
    links = (
        [str(item).strip() for item in configured]
        if isinstance(configured, list)
        else []
    )
    links.extend(discovered)
    return list(dict.fromkeys(item for item in links if item))


def _slug(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9а-яё]+", "-", text)
    return text.strip("-") or "factory-project"


def _limit(value: int) -> int:
    return max(1, min(int(value), 50))
