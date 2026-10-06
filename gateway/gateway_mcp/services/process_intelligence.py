import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from gateway_mcp.backends import call_backend
from gateway_mcp.services.access import require_resource_access
from gateway_mcp.services.company_common import _route_by_name
from gateway_mcp.services.policy import GatewayActor


DEFAULT_SYSTEMS = ("yonote", "bitrix24", "tracker", "gitlab")
MAX_EVENTS = 250
MAX_CANDIDATES = 12

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
TOKEN_RE = re.compile(r"\b(?:ya29|y0__|glpat-|xox[baprs]-|[A-Za-z0-9_-]{32,})\b")


def parse_json_array(value: str, default: list[str] | None = None) -> list[str]:
    fallback = list(default or [])
    if not str(value or "").strip():
        return fallback
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("expected JSON array")
    return [str(item).strip() for item in parsed if str(item).strip()]


def parse_json_object_or_array(value: str) -> Any:
    if not str(value or "").strip():
        return None
    return json.loads(value)


def sanitize_text(value: Any, *, max_length: int = 160) -> str:
    text = str(value or "").strip()
    text = EMAIL_RE.sub("[email]", text)
    text = PHONE_RE.sub("[phone]", text)
    text = TOKEN_RE.sub("[secret]", text)
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "..."
    return text


def stable_ref(system: str, kind: str, value: Any) -> str:
    raw = f"{system}:{kind}:{value or ''}"
    digest = sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{system}:{kind}:{digest}"


def normalize_period_days(period_days: int | str) -> int:
    try:
        value = int(period_days)
    except (TypeError, ValueError):
        value = 14
    return max(1, min(value, 120))


def normalize_limit(limit: int | str, *, maximum: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = maximum
    return max(1, min(value, maximum))


def period_window(period_days: int | str) -> dict[str, str | int]:
    days = normalize_period_days(period_days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return {
        "days": days,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _items_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("result", "items", "documents", "data", "values"):
        nested = payload.get(key)
        items = _items_from_payload(nested)
        if items:
            return items
    return []


def _payload_items(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not result:
        return []
    return _items_from_payload(result.get("data", result))


def _source_ref(route_name: str, item_id: Any) -> dict[str, Any]:
    return {
        "route": route_name,
        "id": str(item_id or ""),
    }


def _event(
    *,
    system: str,
    event_type: str,
    process_hint: str,
    case_kind: str,
    case_id: Any,
    occurred_at: Any,
    status: Any = "",
    artifact_kind: str,
    artifact_id: Any,
    artifact_title: Any,
    route_name: str,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    source_id = str(artifact_id or case_id or "")
    return {
        "id": stable_ref(system, event_type, source_id),
        "system": system,
        "event_type": event_type,
        "process_hint": process_hint,
        "case_id": f"{system}:{case_kind}:{source_id}" if source_id else f"{system}:{case_kind}:unknown",
        "occurred_at": str(occurred_at or ""),
        "status": sanitize_text(status, max_length=80),
        "artifact": {
            "kind": artifact_kind,
            "id": source_id,
            "title": sanitize_text(artifact_title),
        },
        "source_ref": _source_ref(route_name, source_id),
        "signals": signals or [],
    }


async def _call_process_route(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    route_name: str,
    arguments: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    route = _route_by_name(tools_registry, route_name)
    if route is None:
        errors.append({"route": route_name, "error": "missing_route"})
        return None

    try:
        require_resource_access(actor=actor, route=route, arguments=arguments)
    except PermissionError as exc:
        errors.append({"route": route_name, "error": "resource_denied", "message": str(exc)})
        return None

    try:
        result = await call_backend(route, arguments)
    except Exception as exc:
        errors.append({"route": route_name, "error": exc.__class__.__name__})
        return None

    if not result.get("ok", False):
        errors.append(
            {
                "route": route_name,
                "error": "upstream_error",
                "status": result.get("status"),
                "backend": result.get("backend"),
            }
        )
        return None
    return result


def _normalize_bitrix_events(route_name: str, entity: str, result: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if entity == "deal":
        process_hint = "sales_pipeline"
        event_type = "crm.deal_stage"
        status_keys = ("STAGE_ID", "stageId", "stage")
    else:
        process_hint = "lead_qualification"
        event_type = "crm.lead_status"
        status_keys = ("STATUS_ID", "statusId", "status")

    for item in _payload_items(result):
        item_id = _first(item, "ID", "id")
        events.append(
            _event(
                system="bitrix24",
                event_type=event_type,
                process_hint=process_hint,
                case_kind=entity,
                case_id=item_id,
                occurred_at=_first(item, "DATE_MODIFY", "dateModify", "UPDATED_TIME", "DATE_CREATE", "dateCreate"),
                status=_first(item, *status_keys),
                artifact_kind=entity,
                artifact_id=item_id,
                artifact_title=_first(item, "TITLE", "title"),
                route_name=route_name,
                signals=["crm_stage", "commercial_context"],
            )
        )
    return events


def _normalize_tracker_events(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in _payload_items(result):
        issue_key = _first(item, "key", "id")
        status = _first(item, "status", "statusDisplay", "state")
        if isinstance(status, dict):
            status = _first(status, "display", "name", "key", "id")
        events.append(
            _event(
                system="tracker",
                event_type="tracker.issue_status",
                process_hint="delivery_task_flow",
                case_kind="issue",
                case_id=issue_key,
                occurred_at=_first(item, "updatedAt", "updated", "createdAt", "created"),
                status=status,
                artifact_kind="issue",
                artifact_id=issue_key,
                artifact_title=_first(item, "summary", "title", "name"),
                route_name="tracker.issues.search",
                signals=["status_transition", "handoff_marker"],
            )
        )
    return events


def _normalize_gitlab_project_events(result: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    project_ids: list[str] = []
    for item in _payload_items(result):
        project_id = _first(item, "id")
        if project_id is not None:
            project_ids.append(str(project_id))
        events.append(
            _event(
                system="gitlab",
                event_type="gitlab.project_visible",
                process_hint="development_context",
                case_kind="project",
                case_id=project_id,
                occurred_at=_first(item, "last_activity_at", "created_at"),
                status=_first(item, "visibility"),
                artifact_kind="project",
                artifact_id=project_id,
                artifact_title=_first(item, "path_with_namespace", "name_with_namespace", "name"),
                route_name="gitlab.projects.search",
                signals=["repository_context"],
            )
        )
    return events, project_ids


def _normalize_gitlab_mr_events(project_id: str, result: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in _payload_items(result):
        iid = _first(item, "iid", "id")
        events.append(
            _event(
                system="gitlab",
                event_type="gitlab.merge_request",
                process_hint="development_review_release",
                case_kind="merge_request",
                case_id=f"{project_id}:{iid}",
                occurred_at=_first(item, "updated_at", "created_at", "merged_at", "closed_at"),
                status=_first(item, "state", "merge_status", "detailed_merge_status"),
                artifact_kind="merge_request",
                artifact_id=f"{project_id}:{iid}",
                artifact_title=_first(item, "title"),
                route_name="gitlab.merge_requests.list",
                signals=["review", "branch", "handoff_marker"],
            )
        )
    return events


def _normalize_gitlab_pipeline_events(project_id: str, result: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in _payload_items(result):
        pipeline_id = _first(item, "id")
        events.append(
            _event(
                system="gitlab",
                event_type="gitlab.pipeline",
                process_hint="development_review_release",
                case_kind="pipeline",
                case_id=f"{project_id}:{pipeline_id}",
                occurred_at=_first(item, "updated_at", "created_at"),
                status=_first(item, "status"),
                artifact_kind="pipeline",
                artifact_id=f"{project_id}:{pipeline_id}",
                artifact_title=_first(item, "ref", "sha"),
                route_name="gitlab.pipelines.list",
                signals=["ci", "release_gate"],
            )
        )
    return events


def _normalize_yonote_events(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in _payload_items(result):
        document_id = _first(item, "id", "document_id", "shareId", "share_id")
        title = _first(item, "title", "name")
        events.append(
            _event(
                system="yonote",
                event_type="yonote.process_document",
                process_hint="process_source_of_truth",
                case_kind="document",
                case_id=document_id,
                occurred_at=_first(item, "updatedAt", "updated_at", "createdAt", "created_at"),
                status="source_of_truth_candidate",
                artifact_kind="document",
                artifact_id=document_id,
                artifact_title=title,
                route_name="yonote.documents.search",
                signals=["written_process", "source_of_truth"],
            )
        )
    return events


async def collect_process_events(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    query: str = "",
    period_days: int | str = 14,
    systems: list[str] | None = None,
    project_ids: list[str] | None = None,
    limit: int | str = 100,
) -> dict[str, Any]:
    normalized_systems = {str(system).strip().casefold() for system in (systems or DEFAULT_SYSTEMS)}
    normalized_limit = normalize_limit(limit, maximum=MAX_EVENTS)
    window = period_window(period_days)
    errors: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    query_text = str(query or "").strip()

    if "bitrix24" in normalized_systems:
        bitrix_select = ["ID", "TITLE", "STAGE_ID", "STATUS_ID", "DATE_CREATE", "DATE_MODIFY"]
        deal_args = {
            "params": {
                "order": {"DATE_MODIFY": "DESC"},
                "filter": {">=DATE_MODIFY": window["start"]},
                "select": bitrix_select,
                "start": 0,
            }
        }
        lead_args = {
            "params": {
                "order": {"DATE_MODIFY": "DESC"},
                "filter": {">=DATE_MODIFY": window["start"]},
                "select": bitrix_select,
                "start": 0,
            }
        }
        deal_result = await _call_process_route(
            actor=actor,
            tools_registry=tools_registry,
            route_name="bitrix24.deals.list",
            arguments=deal_args,
            errors=errors,
        )
        lead_result = await _call_process_route(
            actor=actor,
            tools_registry=tools_registry,
            route_name="bitrix24.leads.list",
            arguments=lead_args,
            errors=errors,
        )
        events.extend(_normalize_bitrix_events("bitrix24.deals.list", "deal", deal_result))
        events.extend(_normalize_bitrix_events("bitrix24.leads.list", "lead", lead_result))

    if "tracker" in normalized_systems:
        tracker_query = query_text or f'Updated: >= "{str(window["start"])[:10]}"'
        tracker_result = await _call_process_route(
            actor=actor,
            tools_registry=tools_registry,
            route_name="tracker.issues.search",
            arguments={"body": {"query": tracker_query}, "perPage": min(normalized_limit, 50)},
            errors=errors,
        )
        events.extend(_normalize_tracker_events(tracker_result))

    if "gitlab" in normalized_systems:
        ids = [str(item).strip() for item in (project_ids or []) if str(item).strip()]
        if not ids:
            project_result = await _call_process_route(
                actor=actor,
                tools_registry=tools_registry,
                route_name="gitlab.projects.search",
                arguments={
                    "search": query_text,
                    "membership": True,
                    "simple": True,
                    "per_page": int(os.getenv("GATEWAY_PROCESS_GITLAB_PROJECT_LIMIT", "5")),
                },
                errors=errors,
            )
            project_events, ids = _normalize_gitlab_project_events(project_result)
            events.extend(project_events)

        for project_id in ids[: int(os.getenv("GATEWAY_PROCESS_GITLAB_PROJECT_LIMIT", "5"))]:
            mr_result = await _call_process_route(
                actor=actor,
                tools_registry=tools_registry,
                route_name="gitlab.merge_requests.list",
                arguments={"project_id": project_id, "state": "all", "per_page": min(normalized_limit, 50)},
                errors=errors,
            )
            pipeline_result = await _call_process_route(
                actor=actor,
                tools_registry=tools_registry,
                route_name="gitlab.pipelines.list",
                arguments={"project_id": project_id, "per_page": min(normalized_limit, 50)},
                errors=errors,
            )
            events.extend(_normalize_gitlab_mr_events(project_id, mr_result))
            events.extend(_normalize_gitlab_pipeline_events(project_id, pipeline_result))

    if "yonote" in normalized_systems:
        yonote_query = query_text or os.getenv("GATEWAY_PROCESS_YONOTE_QUERY", "процесс")
        yonote_result = await _call_process_route(
            actor=actor,
            tools_registry=tools_registry,
            route_name="yonote.documents.search",
            arguments={"query": yonote_query, "limit": min(normalized_limit, 25)},
            errors=errors,
        )
        events.extend(_normalize_yonote_events(yonote_result))

    events = sorted(events, key=lambda item: str(item.get("occurred_at") or ""), reverse=True)[:normalized_limit]
    return {
        "period": window,
        "query": query_text,
        "systems": sorted(normalized_systems),
        "count": len(events),
        "events": events,
        "collection_errors": errors,
        "privacy": {
            "mode": "sanitized_process_events",
            "raw_records_returned": False,
        },
    }


def _candidate_confidence(evidence_count: int, systems_count: int) -> str:
    if evidence_count >= 8 and systems_count >= 2:
        return "high"
    if evidence_count >= 3:
        return "medium"
    return "low"


def _confidence_score(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _candidate_classification(process_hint: str, systems: set[str], evidence_count: int) -> str:
    if process_hint == "process_source_of_truth":
        return "documented_candidate"
    if evidence_count < 3:
        return "instrumentation_gap"
    if "yonote" in systems:
        return "documented_and_observed"
    return "emergent_or_undocumented"


def _candidate_trigger(process_hint: str) -> str:
    return {
        "sales_pipeline": "CRM deal changed stage or state",
        "lead_qualification": "CRM lead changed status",
        "delivery_task_flow": "Tracker issue changed status",
        "development_review_release": "GitLab merge request or pipeline changed",
        "development_context": "GitLab project activity appeared in the selected scope",
        "process_source_of_truth": "Yonote process or playbook page matched the query",
        "sales_to_delivery_handoff": "Commercial CRM activity and delivery task activity coexist in the same period",
        "delivery_to_engineering_flow": "Tracker delivery activity and GitLab review/release activity coexist in the same period",
    }.get(process_hint, "Repeated operating event")


def _observed_path(events: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for event in events:
        label = str(event.get("event_type") or "")
        status = str(event.get("status") or "")
        if status:
            label = f"{label}:{status}"
        if label and label not in labels:
            labels.append(label)
    return labels[:8]


def _candidate_from_events(process_hint: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    systems = {str(event.get("system") or "") for event in events if event.get("system")}
    event_types = Counter(str(event.get("event_type") or "") for event in events)
    cases = {str(event.get("case_id") or "") for event in events if event.get("case_id")}
    evidence = [
        {
            "event_id": event.get("id"),
            "system": event.get("system"),
            "event_type": event.get("event_type"),
            "status": event.get("status"),
            "source_ref": event.get("source_ref"),
        }
        for event in events[:10]
    ]
    return {
        "id": stable_ref("process", process_hint, "|".join(sorted(cases))[:200]),
        "name": process_hint.replace("_", " ").title(),
        "process_hint": process_hint,
        "classification": _candidate_classification(process_hint, systems, len(events)),
        "confidence": _candidate_confidence(len(events), len(systems)),
        "trigger": _candidate_trigger(process_hint),
        "systems": sorted(systems),
        "evidence_count": len(events),
        "case_count": len(cases),
        "event_type_counts": dict(event_types),
        "observed_path": _observed_path(events),
        "evidence": evidence,
        "management_move_needed": _management_move_for(process_hint, systems, len(events)),
    }


def _management_move_for(process_hint: str, systems: set[str], evidence_count: int) -> str:
    if evidence_count < 3:
        return "Improve instrumentation before changing the official process."
    if process_hint == "process_source_of_truth":
        return "Link this written process to observable systems and owner roles."
    if "yonote" not in systems:
        return "Check whether this observed flow has an official Yonote process page."
    return "Compare the observed path with the written process and update roles, templates, or exit criteria."


def discover_process_candidates(events: list[dict[str, Any]], *, limit: int | str = 8) -> dict[str, Any]:
    normalized_limit = normalize_limit(limit, maximum=MAX_CANDIDATES)
    by_hint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        hint = str(event.get("process_hint") or "unknown")
        by_hint[hint].append(event)

    candidates = [_candidate_from_events(hint, hint_events) for hint, hint_events in by_hint.items()]

    if by_hint.get("sales_pipeline") and by_hint.get("delivery_task_flow"):
        candidates.append(_candidate_from_events("sales_to_delivery_handoff", by_hint["sales_pipeline"] + by_hint["delivery_task_flow"]))
    if by_hint.get("delivery_task_flow") and by_hint.get("development_review_release"):
        candidates.append(
            _candidate_from_events(
                "delivery_to_engineering_flow",
                by_hint["delivery_task_flow"] + by_hint["development_review_release"],
            )
        )

    candidates = sorted(
        candidates,
        key=lambda item: (_confidence_score(str(item["confidence"])), item["evidence_count"]),
        reverse=True,
    )
    return {
        "count": len(candidates[:normalized_limit]),
        "candidates": candidates[:normalized_limit],
        "method": "heuristic_event_chain_discovery",
    }


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-zА-Яа-я0-9]{3,}", value.casefold()) if token}


async def compare_candidates_with_yonote(
    *,
    actor: GatewayActor,
    tools_registry: dict[str, Any],
    candidates: list[dict[str, Any]],
    query: str = "",
    limit: int | str = 8,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    normalized_limit = normalize_limit(limit, maximum=MAX_CANDIDATES)
    search_query = str(query or "").strip() or os.getenv("GATEWAY_PROCESS_YONOTE_QUERY", "процесс")
    yonote_result = await _call_process_route(
        actor=actor,
        tools_registry=tools_registry,
        route_name="yonote.documents.search",
        arguments={"query": search_query, "limit": 25},
        errors=errors,
    )
    process_docs = _normalize_yonote_events(yonote_result)
    doc_tokens = [
        {
            "document": doc,
            "tokens": _tokens(str((doc.get("artifact") or {}).get("title") or "")),
        }
        for doc in process_docs
    ]

    comparisons: list[dict[str, Any]] = []
    for candidate in candidates[:normalized_limit]:
        candidate_tokens = _tokens(str(candidate.get("name") or "")) | _tokens(str(candidate.get("process_hint") or ""))
        matches = [item["document"] for item in doc_tokens if candidate_tokens & item["tokens"]]
        if matches:
            status = "documented_needs_trace_review"
            move = "Open the matched Yonote process page and compare its stages with the observed path."
        elif candidate.get("classification") == "instrumentation_gap":
            status = "instrumentation_gap"
            move = "Add system links, status transitions, or owner fields before changing the process."
        else:
            status = "undocumented_or_missing_index"
            move = "Create or link a Yonote process page after staff validates the candidate."
        comparisons.append(
            {
                "candidate_id": candidate.get("id"),
                "candidate_name": candidate.get("name"),
                "status": status,
                "confidence": candidate.get("confidence"),
                "observed_path": candidate.get("observed_path", []),
                "matched_yonote_refs": [
                    {
                        "id": (doc.get("artifact") or {}).get("id"),
                        "title": (doc.get("artifact") or {}).get("title"),
                        "source_ref": doc.get("source_ref"),
                    }
                    for doc in matches[:3]
                ],
                "recommended_move": move,
            }
        )

    return {
        "count": len(comparisons),
        "comparisons": comparisons,
        "written_process_ref_count": len(process_docs),
        "collection_errors": errors,
    }


def build_rebuild_backlog(
    *,
    candidates: list[dict[str, Any]],
    comparisons: list[dict[str, Any]] | None = None,
    limit: int | str = 8,
) -> dict[str, Any]:
    normalized_limit = normalize_limit(limit, maximum=MAX_CANDIDATES)
    comparison_by_id = {str(item.get("candidate_id")): item for item in (comparisons or [])}
    backlog: list[dict[str, Any]] = []
    for candidate in candidates[:normalized_limit]:
        comparison = comparison_by_id.get(str(candidate.get("id")), {})
        status = str(comparison.get("status") or candidate.get("classification") or "")
        if status == "documented_needs_trace_review":
            item_type = "process_update"
        elif status == "instrumentation_gap":
            item_type = "instrumentation_gap"
        elif status == "undocumented_or_missing_index":
            item_type = "new_process_page"
        else:
            item_type = "process_review"
        backlog.append(
            {
                "type": item_type,
                "title": f"Review {candidate.get('name')}",
                "candidate_id": candidate.get("id"),
                "confidence": candidate.get("confidence"),
                "evidence_count": candidate.get("evidence_count"),
                "systems": candidate.get("systems", []),
                "why": comparison.get("recommended_move") or candidate.get("management_move_needed"),
                "staff_decision_needed": _staff_decision_for(item_type),
                "safe_next_step": "Write or update a Yonote proposal page; do not change official process pages automatically.",
            }
        )
    return {"count": len(backlog), "items": backlog}


def _staff_decision_for(item_type: str) -> str:
    return {
        "process_update": "Approve the process page update, owner, and exit criteria.",
        "instrumentation_gap": "Approve the minimal fields/events needed for future discovery.",
        "new_process_page": "Confirm that the emergent flow is real and assign a process owner.",
    }.get(item_type, "Decide whether this candidate should become an official process change.")
