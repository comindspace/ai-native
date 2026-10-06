import json

from mcp.types import ToolAnnotations

from gateway_mcp.config import read_json, tools_file
from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.process_intelligence import (
    build_rebuild_backlog,
    collect_process_events,
    compare_candidates_with_yonote,
    discover_process_candidates,
    parse_json_array,
    parse_json_object_or_array,
)
from gateway_mcp.tools.runtime import ToolRun


def _events_from_json(events_json: str) -> list[dict]:
    parsed = parse_json_object_or_array(events_json)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("events", [])
    if not isinstance(parsed, list):
        raise ValueError("events_json must be a JSON array or an object with events")
    return [item for item in parsed if isinstance(item, dict)]


def _candidates_from_json(candidates_json: str) -> list[dict]:
    parsed = parse_json_object_or_array(candidates_json)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("candidates", [])
    if not isinstance(parsed, list):
        raise ValueError("candidates_json must be a JSON array or an object with candidates")
    return [item for item in parsed if isinstance(item, dict)]


def _comparisons_from_json(comparisons_json: str) -> list[dict]:
    parsed = parse_json_object_or_array(comparisons_json)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("comparisons", [])
    if not isinstance(parsed, list):
        raise ValueError("comparisons_json must be a JSON array or an object with comparisons")
    return [item for item in parsed if isinstance(item, dict)]


def register_process_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Process Events Search", readOnlyHint=True))
    async def gateway_process_events_search(
        query: str = "",
        period_days: int = 14,
        systems_json: str = "",
        project_ids_json: str = "",
        limit: int = 100,
    ) -> str:
        """Return sanitized process events from Yonote, Bitrix24, Tracker, and GitLab."""
        tool = "gateway_process_events_search"
        scope = "process:read"
        run = ToolRun.start(
            tool=tool,
            system="process",
            scope=scope,
            arguments={
                "query": query,
                "period_days": period_days,
                "systems_json": systems_json,
                "project_ids_json": project_ids_json,
                "limit": limit,
            },
        )
        try:
            actor = run.require_scope()
            registry = read_json(tools_file(), {"tools": []})
            systems = parse_json_array(systems_json, default=[])
            project_ids = parse_json_array(project_ids_json, default=[])
            result = await collect_process_events(
                actor=actor,
                tools_registry=registry,
                query=query,
                period_days=period_days,
                systems=systems or None,
                project_ids=project_ids,
                limit=limit,
            )
            run.finish()
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Process Candidates Discover", readOnlyHint=True))
    async def gateway_process_candidates_discover(
        events_json: str = "",
        query: str = "",
        period_days: int = 14,
        systems_json: str = "",
        project_ids_json: str = "",
        limit: int = 8,
    ) -> str:
        """Discover repeated process candidates from sanitized process events."""
        tool = "gateway_process_candidates_discover"
        scope = "process:read"
        run = ToolRun.start(
            tool=tool,
            system="process",
            scope=scope,
            arguments={
                "has_events_json": bool(events_json.strip()),
                "query": query,
                "period_days": period_days,
                "systems_json": systems_json,
                "project_ids_json": project_ids_json,
                "limit": limit,
            },
        )
        try:
            actor = run.require_scope()
            registry = read_json(tools_file(), {"tools": []})
            events = _events_from_json(events_json)
            source: dict = {}
            if not events:
                systems = parse_json_array(systems_json, default=[])
                project_ids = parse_json_array(project_ids_json, default=[])
                source = await collect_process_events(
                    actor=actor,
                    tools_registry=registry,
                    query=query,
                    period_days=period_days,
                    systems=systems or None,
                    project_ids=project_ids,
                    limit=200,
                )
                events = source.get("events", [])
            result = discover_process_candidates(events, limit=limit)
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    **result,
                    "source_event_count": len(events),
                    "collection_errors": source.get("collection_errors", []),
                },
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Process Compare With Yonote", readOnlyHint=True))
    async def gateway_process_compare_with_yonote(
        candidates_json: str = "",
        query: str = "",
        period_days: int = 14,
        systems_json: str = "",
        project_ids_json: str = "",
        limit: int = 8,
    ) -> str:
        """Compare discovered process candidates with Yonote process/source-of-truth pages."""
        tool = "gateway_process_compare_with_yonote"
        scope = "process:read"
        run = ToolRun.start(
            tool=tool,
            system="process",
            scope=scope,
            arguments={
                "has_candidates_json": bool(candidates_json.strip()),
                "query": query,
                "period_days": period_days,
                "systems_json": systems_json,
                "project_ids_json": project_ids_json,
                "limit": limit,
            },
        )
        try:
            actor = run.require_scope()
            registry = read_json(tools_file(), {"tools": []})
            candidates = _candidates_from_json(candidates_json)
            source_errors: list[dict] = []
            if not candidates:
                systems = parse_json_array(systems_json, default=[])
                project_ids = parse_json_array(project_ids_json, default=[])
                source = await collect_process_events(
                    actor=actor,
                    tools_registry=registry,
                    query=query,
                    period_days=period_days,
                    systems=systems or None,
                    project_ids=project_ids,
                    limit=200,
                )
                source_errors = source.get("collection_errors", [])
                candidates = discover_process_candidates(source.get("events", []), limit=limit).get("candidates", [])
            result = await compare_candidates_with_yonote(
                actor=actor,
                tools_registry=registry,
                candidates=candidates,
                query=query,
                limit=limit,
            )
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    **result,
                    "candidate_count": len(candidates),
                    "source_collection_errors": source_errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Process Rebuild Backlog", readOnlyHint=True))
    async def gateway_process_rebuild_backlog(
        candidates_json: str = "",
        comparisons_json: str = "",
        query: str = "",
        period_days: int = 14,
        systems_json: str = "",
        project_ids_json: str = "",
        limit: int = 8,
    ) -> str:
        """Build a staff-reviewed Process Rebuild Backlog from process candidates and Yonote comparison."""
        tool = "gateway_process_rebuild_backlog"
        scope = "process:read"
        run = ToolRun.start(
            tool=tool,
            system="process",
            scope=scope,
            arguments={
                "has_candidates_json": bool(candidates_json.strip()),
                "has_comparisons_json": bool(comparisons_json.strip()),
                "query": query,
                "period_days": period_days,
                "systems_json": systems_json,
                "project_ids_json": project_ids_json,
                "limit": limit,
            },
        )
        try:
            actor = run.require_scope()
            registry = read_json(tools_file(), {"tools": []})
            candidates = _candidates_from_json(candidates_json)
            comparisons = _comparisons_from_json(comparisons_json)
            source_errors: list[dict] = []
            comparison_errors: list[dict] = []

            if not candidates:
                systems = parse_json_array(systems_json, default=[])
                project_ids = parse_json_array(project_ids_json, default=[])
                source = await collect_process_events(
                    actor=actor,
                    tools_registry=registry,
                    query=query,
                    period_days=period_days,
                    systems=systems or None,
                    project_ids=project_ids,
                    limit=200,
                )
                source_errors = source.get("collection_errors", [])
                candidates = discover_process_candidates(source.get("events", []), limit=limit).get("candidates", [])

            if not comparisons and candidates:
                comparison_result = await compare_candidates_with_yonote(
                    actor=actor,
                    tools_registry=registry,
                    candidates=candidates,
                    query=query,
                    limit=limit,
                )
                comparisons = comparison_result.get("comparisons", [])
                comparison_errors = comparison_result.get("collection_errors", [])

            result = build_rebuild_backlog(candidates=candidates, comparisons=comparisons, limit=limit)
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    **result,
                    "candidate_count": len(candidates),
                    "comparison_count": len(comparisons),
                    "source_collection_errors": source_errors,
                    "comparison_collection_errors": comparison_errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
