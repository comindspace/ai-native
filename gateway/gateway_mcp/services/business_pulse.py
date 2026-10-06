"""Business-facing, request-scoped projections. Never merge currencies or actors."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from gateway_mcp.services.admin_metrics import sales_snapshot, tracker_projects_snapshot
from gateway_mcp.services.business_economics import (
    calculate_economics,
    crm_deal_amount,
    project_worklogs,
)
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage_business import cost_rates, list_project_links

MAX_CONTRACTS = 30
WORKLOG_TIMEOUT = 7


def money_value(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else None
    except (ValueError, TypeError, InvalidOperation):
        return None


async def portfolio_snapshot(
    actor: GatewayActor,
    *,
    projects: dict | None = None,
    links: list | None = None,
) -> dict[str, Any]:
    """Compare visible Tracker projects to confirmed CRM amounts, within a bounded read."""
    if not all(has_scope(actor, scope) for scope in ("tracker:read", "bitrix24:read")):
        return {"available": False, "reason": "Нужен доступ к Tracker и CRM."}
    try:
        if projects is None:
            projects = await asyncio.wait_for(
                tracker_projects_snapshot(actor_subject=actor.subject), 6
            )
        if links is None:
            links = await asyncio.wait_for(asyncio.to_thread(list_project_links), 4)
        rates = await asyncio.wait_for(asyncio.to_thread(cost_rates), 4)
    except Exception:  # noqa: BLE001 - upstream details must not enter the page
        return {
            "available": False,
            "reason": "Не удалось прочитать проекты или настройки договоров.",
        }

    catalog: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for project in projects.get("projects", []):
        key = str(project.get("short_id") or project.get("id") or "")
        if not key:
            continue
        catalog[key] = project
        for alias in (project.get("id"), project.get("short_id")):
            if alias:
                aliases[str(alias)] = key
    grouped: dict[str, list] = defaultdict(list)
    for link in links:
        key = aliases.get(str(link["tracker_project_id"]))
        if key:
            grouped[key].append(link)
    crm_slots = asyncio.Semaphore(6)
    labor_slots = asyncio.Semaphore(2)

    async def fetch_deal(deal_id):
        async with crm_slots:
            return await crm_deal_amount(deal_id)

    async def fetch_logs(project_id):
        async with labor_slots:
            return await project_worklogs(
                actor_subject=actor.subject, tracker_project_id=project_id
            )

    async def read_contract(key, link):
        row = {
            "project_id": str(link["tracker_project_id"]),
            "name": str(catalog[key].get("name") or key),
            "deal_id": int(link["crm_deal_id"]),
            "amount": None,
            "currency": "",
            "confirmed": False,
            "labor_cost": None,
            "hours": None,
            "consumed_percent": None,
            "status": "crm_unavailable",
            "reviewed_rates": 0,
            "author_count": 0,
        }
        try:
            deal = await asyncio.wait_for(fetch_deal(row["deal_id"]), 4)
            amount = money_value(deal.get("OPPORTUNITY"))
            currency = str(deal.get("CURRENCY_ID") or "")
            confirmed = (
                bool(link["contract_confirmed"])
                and amount is not None
                and amount > 0
                and bool(currency)
                and (
                    amount == money_value(link.get("confirmed_amount"))
                    and currency == link.get("confirmed_currency")
                )
            )
            row.update(amount=amount, currency=currency, confirmed=confirmed)
        except Exception:  # noqa: BLE001
            return row
        if not confirmed:
            row["status"] = "confirm_contract"
            return row
        if currency != "RUB":
            row["status"] = "currency"
            return row
        try:
            work = await asyncio.wait_for(
                fetch_logs(row["project_id"]), WORKLOG_TIMEOUT
            )
            economics = calculate_economics(
                deal=deal,
                confirmed=True,
                logs=work["logs"],
                rates=rates,
                complete=not work["limited"],
            )
            row.update(
                labor_cost=economics["labor_cost"],
                hours=economics["hours"],
                reviewed_rates=economics["reviewed_rates"],
                author_count=len(economics["authors"]),
            )
            if economics["labor_cost"] is None:
                row["status"] = (
                    "no_worklogs" if not work["logs"] else "incomplete_worklogs"
                )
            else:
                percent = economics["labor_cost"] / amount * 100
                row["consumed_percent"] = percent
                row["status"] = (
                    "over_amount"
                    if percent >= 100
                    else "check_remaining"
                    if percent >= 80
                    else "calculated"
                )
        except Exception:  # noqa: BLE001
            row["status"] = "worklogs_unavailable"
        return row

    unique = [
        (key, group[0]) for key, group in sorted(grouped.items()) if len(group) == 1
    ]
    deal_projects: dict[str, set[str]] = defaultdict(set)
    for link in links:
        project = str(link["tracker_project_id"])
        deal_projects[str(link["crm_deal_id"])].add(aliases.get(project, project))
    duplicated = {
        key for keys in deal_projects.values() if len(keys) > 1 for key in keys
    }
    unique = [(key, link) for key, link in unique if key not in duplicated]
    rows = await asyncio.gather(
        *(read_contract(key, link) for key, link in unique[:MAX_CONTRACTS])
    )
    for key, group in grouped.items():
        if len(group) > 1 or key in duplicated:
            rows.append(
                {
                    "project_id": key,
                    "name": str(catalog[key].get("name") or key),
                    "deal_id": None,
                    "amount": None,
                    "currency": "",
                    "confirmed": False,
                    "labor_cost": None,
                    "hours": None,
                    "consumed_percent": None,
                    "status": "duplicate_deal"
                    if key in duplicated
                    else "duplicate_links",
                }
            )
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for row in rows:
        if row["confirmed"]:
            totals[row["currency"]] += row["amount"]
    comparable = [
        row for row in rows if row["confirmed"] and row["labor_cost"] is not None
    ]
    comparable_amount = sum((r["amount"] for r in comparable), Decimal(0))
    labor = sum((r["labor_cost"] for r in comparable), Decimal(0))
    rank = {
        "over_amount": 0,
        "check_remaining": 1,
        "confirm_contract": 2,
        "duplicate_links": 2,
        "duplicate_deal": 2,
        "incomplete_worklogs": 3,
        "worklogs_unavailable": 3,
        "crm_unavailable": 3,
        "no_worklogs": 4,
        "currency": 5,
        "calculated": 6,
    }
    rows.sort(
        key=lambda r: (
            rank[r["status"]],
            -(r["consumed_percent"] or 0),
            r["name"].casefold(),
        )
    )
    return {
        "available": True,
        "rows": rows,
        "totals": dict(totals),
        "linked_count": len(grouped),
        "project_count": len(catalog),
        "unlinked": [
            {"project_id": key, "name": str(p.get("name") or key)}
            for key, p in catalog.items()
            if key not in grouped
        ],
        "confirmed_count": sum(r["confirmed"] for r in rows),
        "calculated_count": len(comparable),
        "comparable_amount": comparable_amount if comparable else None,
        "labor_cost": labor if comparable else None,
        "consumed_percent": labor / comparable_amount * 100
        if comparable_amount > 0
        else None,
        "attention_count": sum(
            r["status"] in {"over_amount", "check_remaining"} for r in rows
        ),
        "limited": bool(projects.get("limited")) or len(unique) > MAX_CONTRACTS,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


async def business_pulse(actor: GatewayActor, *, category_id="0", days=30) -> dict:
    """Load independent business sources; one failed backend leaves the others usable."""

    async def sales():
        if not has_scope(actor, "bitrix24:read"):
            return None
        try:
            return await asyncio.wait_for(
                sales_snapshot(category_id=category_id, days=days, stale_days=7), 8
            )
        except Exception:  # noqa: BLE001
            return None

    portfolio, sales_data = await asyncio.gather(portfolio_snapshot(actor), sales())
    return {
        "portfolio": portfolio,
        "sales": sales_data,
        "category_id": category_id,
        "days": days,
    }
