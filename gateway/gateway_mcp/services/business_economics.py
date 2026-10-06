from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from gateway_mcp.backends.tracker import _call_tracker
from gateway_mcp.services.admin_metrics import _bitrix, _route
from gateway_mcp.services.managed_integrations import integration_value

DEFAULT_COST_RATE_RUB = Decimal(1800)
MAX_PROJECT_ISSUES = 300
MAX_ISSUE_WORKLOGS = 500
_DURATION = re.compile(
    r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def crm_deal_url(deal_id: str | int) -> str:
    """Expose only the CRM origin, never the webhook path or credentials."""
    if not str(deal_id).isdigit():
        return ""
    try:
        parsed = urlsplit(integration_value("bitrix24", "BITRIX24_WEBHOOK_URL"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}/crm/deal/details/{deal_id}/"
    except (ValueError, RuntimeError):
        return ""


def worklog_hours(raw: object) -> Decimal | None:
    match = _DURATION.fullmatch(str(raw or ""))
    if not match or not any(match.groups()):
        return None
    weeks, days, hours, minutes, seconds = (int(value or 0) for value in match.groups())
    return (
        Decimal(weeks * 40 + days * 8 + hours)
        + Decimal(minutes) / 60
        + Decimal(seconds) / 3600
    )


def calculate_economics(
    *,
    deal: dict[str, Any] | None,
    confirmed: bool,
    logs: list[dict[str, Any]],
    rates: dict[str, dict[str, Any]],
    complete: bool,
) -> dict[str, Any]:
    amount = None
    currency = ""
    if deal:
        try:
            amount = Decimal(str(deal.get("OPPORTUNITY") or ""))
        except InvalidOperation:
            pass
        currency = str(deal.get("CURRENCY_ID") or "")
    by_author: dict[str, dict[str, Any]] = {}
    invalid_durations = 0
    for log in logs:
        author = log.get("createdBy") if isinstance(log.get("createdBy"), dict) else {}
        user_id = str(author.get("id") or "").strip()
        hours = worklog_hours(log.get("duration"))
        if hours is None:
            invalid_durations += 1
            continue
        key = user_id or "unknown"
        row = by_author.setdefault(
            key,
            {
                "user_id": key,
                "display": str(author.get("display") or key),
                "hours": Decimal(0),
            },
        )
        row["hours"] += hours
    cost = Decimal(0)
    reviewed = 0
    for row in by_author.values():
        rate = rates.get(row["user_id"])
        row["rate"] = (
            Decimal(str(rate["hourly_rate_rub"])) if rate else DEFAULT_COST_RATE_RUB
        )
        row["basis"] = str(rate["basis"]) if rate else "market_proxy"
        if rate:
            reviewed += 1
        row["cost"] = (row["hours"] * row["rate"]).quantize(Decimal("0.01"))
        cost += row["cost"]
    hours = sum((row["hours"] for row in by_author.values()), Decimal(0))
    unknown_authors = int("unknown" in by_author)
    valid = complete and bool(logs) and invalid_durations == 0 and unknown_authors == 0
    margin = (
        amount - cost
        if valid and confirmed and currency == "RUB" and amount is not None
        else None
    )
    return {
        "amount": amount,
        "currency": currency,
        "confirmed": confirmed,
        "hours": hours,
        "labor_cost": cost if valid else None,
        "balance_after_logged_labor": margin,
        "authors": sorted(
            by_author.values(), key=lambda row: row["display"].casefold()
        ),
        "reviewed_rates": reviewed,
        "invalid_durations": invalid_durations,
        "unknown_authors": unknown_authors,
        "complete": valid,
        "rate_source": "market_proxy_2026",
    }


async def crm_deal_amount(deal_id: int) -> dict[str, Any]:
    data = await _bitrix("bitrix24.deals.get", {"params": {"id": deal_id}})
    deal = data.get("result")
    if not isinstance(deal, dict) or str(deal.get("ID") or "") != str(deal_id):
        raise TypeError("Bitrix24 deal response is missing the requested deal")
    return {key: deal.get(key) for key in ("ID", "OPPORTUNITY", "CURRENCY_ID")}


async def project_worklogs(
    *, actor_subject: str, tracker_project_id: str
) -> dict[str, Any]:
    issue_route = _route("tracker.issues.search")
    log_route = _route("tracker.worklogs.list")
    issue_keys: list[str] = []
    total: int | None = None
    for page in range(1, MAX_PROJECT_ISSUES // 100 + 1):
        result = await _call_tracker(
            issue_route,
            {
                "body": {"filter": {"project": tracker_project_id}},
                "page": page,
                "perPage": 100,
                "fields": "key",
            },
            actor_subject=actor_subject,
        )
        if not result.get("ok") or not isinstance(result.get("data"), list):
            raise RuntimeError("Tracker issue search is unavailable")
        batch = result["data"]
        issue_keys.extend(
            str(item.get("key"))
            for item in batch
            if isinstance(item, dict) and item.get("key")
        )
        if result.get("total_count") is not None:
            total = int(result["total_count"])
        if len(batch) < 100 or (total is not None and len(issue_keys) >= total):
            break
    limited = (total is not None and total > len(issue_keys)) or (
        total is None and len(issue_keys) >= MAX_PROJECT_ISSUES
    )
    semaphore = asyncio.Semaphore(8)

    async def issue_logs(key: str) -> tuple[list[dict[str, Any]], bool]:
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = ""
        async with semaphore:
            for _ in range(MAX_ISSUE_WORKLOGS // 100):
                args = {"issue_id": key, "perPage": 100}
                if cursor:
                    args["id"] = cursor
                response = await _call_tracker(
                    log_route, args, actor_subject=actor_subject
                )
                if not response.get("ok") or not isinstance(response.get("data"), list):
                    raise RuntimeError("Tracker worklog list is unavailable")
                batch = response["data"]
                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    log_id = str(item.get("id") or "")
                    if log_id and log_id in seen:
                        continue
                    if log_id:
                        seen.add(log_id)
                    found.append(item)
                if len(batch) < 100:
                    return found, False
                next_cursor = (
                    str(batch[-1].get("id") or "")
                    if isinstance(batch[-1], dict)
                    else ""
                )
                if not next_cursor or next_cursor == cursor:
                    return found, True
                cursor = next_cursor
        return found, True

    results = await asyncio.gather(
        *(issue_logs(key) for key in dict.fromkeys(issue_keys))
    )
    return {
        "logs": [log for batch, _ in results for log in batch],
        "issue_count": len(issue_keys),
        "total_issues": total,
        "limited": limited or any(partial for _, partial in results),
    }
