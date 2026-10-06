from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from gateway_mcp.backends import call_backend
from gateway_mcp.backends.tracker import _call_tracker
from gateway_mcp.config import read_json, tools_file
from gateway_mcp.services.factory_project_registry import load_factory_project_registry
from gateway_mcp.services.observability import (
    AUTH_FAILURES_TOTAL,
    LLM_PROXY_REQUESTS_TOTAL,
    MEMORY_EVENTS_TOTAL,
    POLICY_DENIES_TOTAL,
    PRIVACY_ENTITIES_TOTAL,
    TOOL_LATENCY_SECONDS,
    UPSTREAM_ERRORS_TOTAL,
)
from gateway_mcp.services.storage_audit import gateway_activity_metrics
from gateway_mcp.services.storage_work import work_project_metrics
from gateway_mcp.services.telemetry import usage_summary

TRACKER_PROJECT_ID = re.compile(r"^[a-zA-Z0-9_-]{1,60}$")
MAX_TRACKER_ISSUES = 1000
MAX_TRACKER_PROJECTS = 1000
MAX_SALES_DEALS = 500
MOSCOW = ZoneInfo("Europe/Moscow")


def gateway_snapshot(days: int) -> dict[str, Any]:
    return gateway_activity_metrics(days=days)


def runtime_snapshot() -> dict[str, int | float | None]:
    calls = _metric_sum(TOOL_LATENCY_SECONDS, "gateway_mcp_tool_latency_seconds_count")
    duration = _metric_sum(TOOL_LATENCY_SECONDS, "gateway_mcp_tool_latency_seconds_sum")
    return {
        "average_latency_ms": round(1000 * duration / calls) if calls else None,
        "auth_failures": int(
            _metric_sum(AUTH_FAILURES_TOTAL, "gateway_mcp_auth_failures_total")
        ),
        "policy_denials": int(
            _metric_sum(POLICY_DENIES_TOTAL, "gateway_mcp_policy_denies_total")
        ),
        "upstream_errors": int(
            _metric_sum(UPSTREAM_ERRORS_TOTAL, "gateway_mcp_upstream_errors_total")
        ),
        "memory_operations": int(
            _metric_sum(MEMORY_EVENTS_TOTAL, "gateway_mcp_memory_events_total")
        ),
        "privacy_entities": int(
            _metric_sum(PRIVACY_ENTITIES_TOTAL, "gateway_mcp_privacy_entities_total")
        ),
        "llm_proxy_requests": int(
            _metric_sum(
                LLM_PROXY_REQUESTS_TOTAL, "gateway_mcp_llm_proxy_requests_total"
            )
        ),
    }


def project_snapshot(days: int, project_id: str = "") -> dict[str, Any]:
    projects = work_project_metrics(days=days, project_id=project_id)
    return {"projects": projects, "count": len(projects), "days": days}


def agent_snapshot(days: int) -> dict[str, Any]:
    return usage_summary(days=days, limit=200)


def tracker_project_for(project_id: str) -> str:
    registry = load_factory_project_registry()
    for project in registry.get("projects", []):
        if str(project.get("project_id") or "").casefold() == project_id.casefold():
            return str(project.get("tracker_project_id") or "").strip()
    return ""


async def tracker_projects_snapshot(*, actor_subject: str) -> dict[str, Any]:
    route = _route("tracker.projects.search")
    projects: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(1, MAX_TRACKER_PROJECTS // 100 + 1):
        response = await _call_tracker(
            route,
            {
                "page": page,
                "perPage": 100,
                "fields": "summary,entityStatus,end,lead",
                "body": {},
            },
            actor_subject=actor_subject,
        )
        if not response.get("ok"):
            raise RuntimeError(
                f"Tracker project search returned HTTP {response.get('status')}"
            )
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("values"), list):
            raise TypeError("Tracker project search returned an unexpected response")
        total = int(data.get("hits")) if data.get("hits") is not None else total
        for item in data["values"]:
            if not isinstance(item, dict):
                continue
            fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
            lead = fields.get("lead")
            projects.append(
                {
                    "id": str(item.get("id") or ""),
                    "short_id": str(item.get("shortId") or ""),
                    "name": str(fields.get("summary") or "").strip(),
                    "status": _key(fields.get("entityStatus")),
                    "end": str(fields.get("end") or "")[:10],
                    "lead": str(lead.get("display") or "")
                    if isinstance(lead, dict)
                    else "",
                }
            )
        if not data["values"] or (total is not None and len(projects) >= total):
            break
        pages = data.get("pages")
        if pages is not None and page >= int(pages):
            break
    return {
        "projects": projects,
        "total": total if total is not None else len(projects),
        "sampled": len(projects),
        "limited": total > len(projects)
        if total is not None
        else len(projects) >= MAX_TRACKER_PROJECTS,
    }


async def tracker_snapshot(
    *, actor_subject: str, tracker_project_id: str
) -> dict[str, Any]:
    project_id = tracker_project_id.strip()
    if not TRACKER_PROJECT_ID.fullmatch(project_id):
        raise ValueError("Некорректный ID проекта Tracker")
    route = _route("tracker.issues.search")
    now = datetime.now(MOSCOW)
    today = now.date()
    issues: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(1, MAX_TRACKER_ISSUES // 100 + 1):
        response = await _call_tracker(
            route,
            {
                "body": {"filter": {"project": project_id}},
                "page": page,
                "perPage": 100,
                "fields": "key,status,statusType,resolution,assignee,deadline,updatedAt,priority,project",
            },
            actor_subject=actor_subject,
        )
        if not response.get("ok"):
            raise RuntimeError(f"Tracker search returned HTTP {response.get('status')}")
        items = response.get("data")
        if not isinstance(items, list):
            raise TypeError("Tracker search returned an unexpected response")
        count_header = response.get("total_count")
        if count_header is not None:
            try:
                total = int(count_header)
            except (TypeError, ValueError):
                pass
        issues.extend(item for item in items if isinstance(item, dict))
        if len(items) < 100 or (total is not None and len(issues) >= total):
            break

    open_issues = [item for item in issues if not _tracker_resolved(item)]
    due_soon = []
    overdue = []
    paused = []
    unassigned = []
    stale = []
    for item in open_issues:
        deadline = _date(item.get("deadline"))
        if deadline and deadline < today:
            overdue.append(item)
        elif deadline and deadline <= today + timedelta(days=7):
            due_soon.append(item)
        status_type = _key(item.get("statusType"))
        status = _key(item.get("status"))
        if status_type == "paused" or status in {"blocked", "onhold", "waiting"}:
            paused.append(item)
        if not item.get("assignee"):
            unassigned.append(item)
        updated = _datetime(item.get("updatedAt"))
        if updated and updated < now.astimezone(timezone.utc) - timedelta(days=7):
            stale.append(item)

    attention = {
        str(item.get("key") or ""): item for item in overdue + due_soon + paused
    }
    return {
        "project_id": project_id,
        "total": total if total is not None else len(issues),
        "sampled": len(issues),
        "limited": total > len(issues)
        if total is not None
        else len(issues) >= MAX_TRACKER_ISSUES,
        "open": len(open_issues),
        "overdue": len(overdue),
        "due_soon": len(due_soon),
        "paused": len(paused),
        "unassigned": len(unassigned),
        "stale": len(stale),
        "attention": [
            {
                "key": key,
                "deadline": str(item.get("deadline") or ""),
                "status": _display(item.get("status")),
            }
            for key, item in list(attention.items())[:20]
        ],
        "as_of": now.isoformat(),
    }


async def sales_snapshot(
    *, category_id: str, days: int, stale_days: int
) -> dict[str, Any]:
    from gateway_mcp.services.business_economics import crm_deal_url

    if not category_id.isdigit() or len(category_id) > 8:
        raise ValueError("Некорректная воронка Bitrix24")
    now = datetime.now(timezone.utc)
    try:
        fields_result = await _bitrix("bitrix24.deals.fields", {})
        fields = fields_result.get("result")
        fields = fields if isinstance(fields, dict) else {}
    except (RuntimeError, TypeError):
        fields = {}
    next_step_field = os.getenv("BITRIX24_NEXT_STEP_FIELD", "UF_CRM_NEXT_STEP")
    next_step_available = next_step_field in fields
    select = ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID", "DATE_MODIFY"]
    if next_step_available:
        select.append(next_step_field)

    deals: list[dict[str, Any]] = []
    total: int | None = None
    start = 0
    for _ in range(MAX_SALES_DEALS // 50):
        data = await _bitrix(
            "bitrix24.deals.list",
            {
                "params": {
                    "order": {"ID": "ASC"},
                    "filter": {"CATEGORY_ID": category_id, "CLOSED": "N"},
                    "select": select,
                    "start": start,
                }
            },
        )
        items = data.get("result")
        if not isinstance(items, list):
            raise TypeError("Bitrix24 deals.list returned an unexpected response")
        if data.get("total") is not None:
            total = int(data["total"])
        deals.extend(item for item in items if isinstance(item, dict))
        next_start = data.get("next")
        if next_start is None or int(next_start) <= start:
            break
        start = int(next_start)

    entity_id = "DEAL_STAGE" if category_id == "0" else f"DEAL_STAGE_{category_id}"
    try:
        statuses = await _bitrix(
            "bitrix24.statuses.list", {"params": {"filter": {"ENTITY_ID": entity_id}}}
        )
    except (RuntimeError, TypeError):
        statuses = {}
    stage_names = {
        str(item.get("STATUS_ID") or ""): str(item.get("NAME") or "")
        for item in statuses.get("result", [])
        if isinstance(item, dict)
    }
    cutoff = (now - timedelta(days=days)).date().isoformat()
    try:
        recent = await _bitrix(
            "bitrix24.deals.list",
            {
                "params": {
                    "filter": {"CATEGORY_ID": category_id, ">=DATE_CREATE": cutoff},
                    "select": ["ID"],
                    "start": 0,
                }
            },
        )
        new_deals = (
            int(recent["total"])
            if recent.get("total") is not None
            else (
                len(recent["result"])
                if isinstance(recent.get("result"), list) and recent.get("next") is None
                else None
            )
        )
    except (RuntimeError, TypeError):
        new_deals = None

    stages: dict[str, dict[str, Any]] = {}
    currencies: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    no_amount = stale = no_next_step = 0
    stale_amounts: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    attention = []
    for deal in deals:
        stage_id = str(deal.get("STAGE_ID") or "unknown")
        currency = str(deal.get("CURRENCY_ID") or "не указана")
        amount = _decimal(deal.get("OPPORTUNITY"))
        stage = stages.setdefault(
            stage_id,
            {
                "id": stage_id,
                "name": stage_names.get(stage_id) or stage_id,
                "count": 0,
                "amounts": defaultdict(lambda: Decimal(0)),
            },
        )
        stage["count"] += 1
        if amount > 0:
            stage["amounts"][currency] += amount
            currencies[currency] += amount
        if amount <= 0:
            no_amount += 1
        modified = _datetime(deal.get("DATE_MODIFY"))
        is_stale = bool(modified and modified < now - timedelta(days=stale_days))
        reasons = []
        if is_stale:
            stale += 1
            stale_amounts[currency] += amount
            reasons.append(f"Нет обновлений {stale_days} дней")
        if amount <= 0:
            reasons.append("Не указана сумма")
        if next_step_available and not deal.get(next_step_field):
            no_next_step += 1
            reasons.append("Не указан следующий шаг")
        if reasons:
            attention.append(
                {
                    "id": str(deal.get("ID") or ""),
                    "title": str(deal.get("TITLE") or f"Сделка #{deal.get('ID', '')}"),
                    "url": crm_deal_url(str(deal.get("ID") or "")),
                    "amount": amount if amount > 0 else None,
                    "currency": currency,
                    "reasons": reasons,
                    "updated_at": str(deal.get("DATE_MODIFY") or ""),
                }
            )

    return {
        "category_id": category_id,
        "days": days,
        "stale_days": stale_days,
        "total_active": total if total is not None else len(deals),
        "sampled": len(deals),
        "limited": total > len(deals)
        if total is not None
        else len(deals) >= MAX_SALES_DEALS,
        "new_deals": new_deals,
        "no_amount": no_amount,
        "stale": stale,
        "no_next_step": no_next_step if next_step_available else None,
        "currency_amounts": dict(currencies),
        "stale_amounts": dict(stale_amounts),
        "attention": sorted(
            attention, key=lambda item: (item["updated_at"], item["id"])
        )[:50],
        "stages": sorted(
            stages.values(), key=lambda item: (-item["count"], item["name"])
        ),
        "as_of": now.astimezone(MOSCOW).isoformat(),
    }


def _route(name: str) -> dict[str, Any]:
    registry = read_json(tools_file(), {"tools": []})
    for route in registry.get("tools", []):
        if route.get("name") == name and route.get("status") == "implemented":
            return route
    raise RuntimeError(f"Gateway route unavailable: {name}")


async def _bitrix(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await call_backend(_route(name), arguments)
    if not result.get("ok"):
        raise RuntimeError(f"{name} returned HTTP {result.get('status')}")
    data = result.get("data")
    if not isinstance(data, dict):
        raise TypeError(f"{name} returned an unexpected response")
    return data


def _key(value: Any) -> str:
    raw = value.get("key") if isinstance(value, dict) else value
    return str(raw or "").casefold()


def _display(value: Any) -> str:
    raw = value.get("display") or value.get("key") if isinstance(value, dict) else value
    return str(raw or "")


def _tracker_resolved(issue: dict[str, Any]) -> bool:
    return bool(issue.get("resolution")) or _key(issue.get("statusType")) in {
        "resolved",
        "closed",
    }


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value or "0"))
        return number if number.is_finite() and number >= 0 else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _metric_sum(metric: Any, sample_name: str) -> float:
    return sum(
        float(sample.value)
        for family in metric.collect()
        for sample in family.samples
        if sample.name == sample_name
    )
