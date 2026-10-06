import base64
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from gateway_mcp.backends.common import (
    BackendConfigError,
    BackendRouteError,
    _clean_args,
)
from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.file_transfers import ready_file_for_actor
from gateway_mcp.services.managed_integrations import integration_value

DEAL_OWNER_TYPE_ID = 2
DEFAULT_EXPECTED_CURRENCY = "RUB"
DEFAULT_NEXT_STEP_FIELD = "UF_CRM_NEXT_STEP"
DEFAULT_NEXT_TOUCH_DATE_FIELD = "UF_CRM_NEXT_TOUCH_DATE"
DEFAULT_PROPOSAL_LINK_FIELD = "UF_CRM_PROPOSAL_LINK"
DEFAULT_CONTRACT_LINK_FIELD = "UF_CRM_CONTRACT_LINK"
DEFAULT_DISCOVERY_LINK_FIELD = "UF_CRM_DISCOVERY_LINK"


def _bitrix_base_url() -> str:
    value = integration_value("bitrix24", "BITRIX24_WEBHOOK_URL").rstrip("/")
    if not value:
        raise BackendConfigError("Bitrix24 managed integration is not configured")
    return value


def _append_bitrix_form(pairs: list[tuple[str, str]], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            _append_bitrix_form(pairs, f"{key}[{nested_key}]", nested_value)
        return
    if isinstance(value, list):
        for index, nested_value in enumerate(value):
            _append_bitrix_form(pairs, f"{key}[{index}]", nested_value)
        return
    pairs.append((key, str(value)))


async def _bitrix_request(client: httpx.AsyncClient, base_url: str, method: str, params: dict[str, Any]) -> httpx.Response:
    url = f"{base_url}/{method}"
    if params:
        form_pairs: list[tuple[str, str]] = []
        for key, value in params.items():
            _append_bitrix_form(form_pairs, key, value)
        form_body = urlencode(form_pairs).encode("utf-8")
        return await client.post(
            url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=form_body,
        )
    return await client.get(url, headers={"Accept": "application/json"})


def _response_data(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


async def _call_bitrix24(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    if route.get("name") == "bitrix24.sales_funnel.health":
        return await _call_sales_funnel_health(arguments)
    if route.get("name") == "bitrix24.timeline.comment.add_with_files":
        return await _call_timeline_comment_with_files(arguments)
    if route.get("name") == "bitrix24.deals.attach_file":
        return await _call_deal_attach_file(arguments)
    if route.get("name") == "bitrix24.companies.upsert":
        return await _call_company_upsert(arguments)

    method = route.get("bitrix_method")
    if not method:
        raise BackendRouteError(f"Bitrix24 route {route.get('name')} has no bitrix_method")

    if isinstance(arguments.get("params"), dict):
        params = dict(arguments["params"])
    elif isinstance(arguments.get("body"), dict):
        params = dict(arguments["body"])
    else:
        params = _clean_args(arguments)

    base_url = _bitrix_base_url()
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await _bitrix_request(client, base_url, str(method), params)

    data = _response_data(response)

    has_bitrix_error = isinstance(data, dict) and bool(data.get("error"))
    return {
        "ok": response.is_success and not has_bitrix_error,
        "status": response.status_code,
        "backend": "bitrix24",
        "method": method,
        "data": data,
    }


async def _call_timeline_comment_with_files(arguments: dict[str, Any]) -> dict[str, Any]:
    params = _timeline_comment_params(arguments)
    base_url = _bitrix_base_url()
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await _bitrix_request(client, base_url, "crm.timeline.comment.add", params)

    data = _response_data(response)
    has_bitrix_error = isinstance(data, dict) and bool(data.get("error"))
    return {
        "ok": response.is_success and not has_bitrix_error,
        "status": response.status_code,
        "backend": "bitrix24",
        "method": "crm.timeline.comment.add",
        "data": data,
    }


async def _call_deal_attach_file(arguments: dict[str, Any]) -> dict[str, Any]:
    source = dict(arguments.get("params") if isinstance(arguments.get("params"), dict) else arguments)
    deal_id = source.get("deal_id") or source.get("DEAL_ID") or source.get("entity_id") or source.get("ENTITY_ID")
    if not deal_id:
        raise BackendRouteError("deal_id is required")

    params = _timeline_comment_params(
        {
            "entity_type": "deal",
            "entity_id": deal_id,
            "comment": source.get("COMMENT") or source.get("comment") or "Файл прикреплен к сделке.",
            "files": source.get("FILES")
            or source.get("files")
            or source.get("fileData")
            or source.get("file_data")
            or source.get("fileContent")
            or source.get("file_content"),
        }
    )
    base_url = _bitrix_base_url()
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await _bitrix_request(client, base_url, "crm.timeline.comment.add", params)

    data = _response_data(response)
    has_bitrix_error = isinstance(data, dict) and bool(data.get("error"))
    return {
        "ok": response.is_success and not has_bitrix_error,
        "status": response.status_code,
        "backend": "bitrix24",
        "method": "crm.timeline.comment.add",
        "data": data,
    }


async def _call_company_upsert(arguments: dict[str, Any]) -> dict[str, Any]:
    params = dict(arguments.get("params") if isinstance(arguments.get("params"), dict) else arguments)
    company_id = params.get("company_id") or params.get("COMPANY_ID") or params.get("id") or params.get("ID")
    deal_id = params.get("deal_id") or params.get("DEAL_ID")
    title = params.get("title") or params.get("name") or params.get("TITLE")
    website = params.get("website") or params.get("web") or params.get("url") or params.get("WEB")
    update_existing = _bool_value(params.get("update_existing"), default=True)
    create_if_missing = _bool_value(params.get("create_if_missing"), default=True)

    fields = dict(params.get("fields") if isinstance(params.get("fields"), dict) else {})
    if title and "TITLE" not in fields:
        fields["TITLE"] = title
    if website and "WEB" not in fields:
        fields["WEB"] = _company_web_field(website)

    if not company_id and not title and not website:
        raise BackendRouteError("company_id, title, or website is required")
    if not fields and update_existing:
        raise BackendRouteError("fields, title, or website is required for company upsert")

    base_url = _bitrix_base_url()
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))
    actions: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        if not company_id:
            found = await _find_company(client, base_url, title=title, website=website)
            if found:
                company_id = found.get("ID") or found.get("id")
                actions.append({"action": "matched", "company": found})

        if company_id:
            if update_existing and fields:
                update_response = await _bitrix_request(
                    client,
                    base_url,
                    "crm.company.update",
                    {"id": company_id, "fields": fields},
                )
                actions.append(
                    {
                        "action": "updated",
                        "ok": update_response.is_success and not _has_bitrix_error(update_response),
                        "status": update_response.status_code,
                        "data": _response_data(update_response),
                    }
                )
        elif create_if_missing:
            if not fields.get("TITLE"):
                raise BackendRouteError("title or fields.TITLE is required to create a company")
            create_response = await _bitrix_request(client, base_url, "crm.company.add", {"fields": fields})
            create_data = _response_data(create_response)
            company_id = _bitrix_result_id(create_data)
            actions.append(
                {
                    "action": "created",
                    "ok": create_response.is_success and not (isinstance(create_data, dict) and bool(create_data.get("error"))),
                    "status": create_response.status_code,
                    "data": create_data,
                }
            )
        else:
            raise BackendRouteError("Company was not found and create_if_missing is false")

        if deal_id and company_id:
            deal_response = await _bitrix_request(
                client,
                base_url,
                "crm.deal.update",
                {"id": deal_id, "fields": {"COMPANY_ID": company_id}},
            )
            actions.append(
                {
                    "action": "deal_linked",
                    "deal_id": str(deal_id),
                    "ok": deal_response.is_success and not _has_bitrix_error(deal_response),
                    "status": deal_response.status_code,
                    "data": _response_data(deal_response),
                }
            )

    ok = bool(company_id) and all(action.get("ok", True) for action in actions)
    return {
        "ok": ok,
        "status": 200 if ok else 502,
        "backend": "bitrix24",
        "method": "companies.upsert",
        "data": {
            "ok": ok,
            "company_id": str(company_id) if company_id else None,
            "deal_id": str(deal_id) if deal_id else None,
            "actions": actions,
        },
    }


async def _find_company(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    title: Any = None,
    website: Any = None,
) -> dict[str, Any] | None:
    filters: list[dict[str, Any]] = []
    if title:
        filters.append({"=TITLE": title})
        filters.append({"%TITLE": title})
    if website:
        filters.append({"%WEB": website})

    for filter_params in filters:
        response = await _bitrix_request(
            client,
            base_url,
            "crm.company.list",
            {
                "filter": filter_params,
                "select": ["ID", "TITLE", "WEB"],
                "start": 0,
            },
        )
        data = _response_data(response)
        if not response.is_success or (isinstance(data, dict) and data.get("error")):
            continue
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, list) and result:
            return dict(result[0])
    return None


def _company_web_field(website: Any) -> list[dict[str, str]]:
    if isinstance(website, list):
        values = website
    else:
        values = [website]
    web_fields: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, dict):
            web_value = value.get("VALUE") or value.get("value")
            value_type = value.get("VALUE_TYPE") or value.get("value_type") or "WORK"
        else:
            web_value = value
            value_type = "WORK"
        if web_value:
            web_fields.append({"VALUE": str(web_value), "VALUE_TYPE": str(value_type)})
    return web_fields


def _has_bitrix_error(response: httpx.Response) -> bool:
    data = _response_data(response)
    return isinstance(data, dict) and bool(data.get("error"))


def _bitrix_result_id(data: Any) -> Any:
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict):
            return result.get("ID") or result.get("id")
        return result
    return None


def _timeline_comment_params(arguments: dict[str, Any]) -> dict[str, Any]:
    source = dict(arguments.get("params") if isinstance(arguments.get("params"), dict) else arguments)
    if isinstance(source.get("fields"), dict):
        fields = dict(source["fields"])
    else:
        fields = {
            "ENTITY_TYPE": source.get("ENTITY_TYPE") or source.get("entity_type"),
            "ENTITY_ID": source.get("ENTITY_ID") or source.get("entity_id"),
            "COMMENT": source.get("COMMENT") or source.get("comment"),
        }

    raw_files = (
        fields.get("FILES")
        or source.get("FILES")
        or source.get("files")
        or source.get("fileData")
        or source.get("file_data")
        or source.get("fileContent")
        or source.get("file_content")
    )
    files = _normalize_timeline_files(raw_files)
    if files:
        fields["FILES"] = files

    missing = [key for key in ("ENTITY_TYPE", "ENTITY_ID", "COMMENT") if fields.get(key) in {None, ""}]
    if missing:
        raise BackendRouteError(f"Missing timeline comment field(s): {', '.join(missing)}")
    return {"fields": _clean_args(fields)}


def _normalize_timeline_files(raw_files: Any) -> list[list[str]]:
    if raw_files is None or raw_files == "":
        return []
    if isinstance(raw_files, dict):
        raw_items: list[Any] = [raw_files]
    elif isinstance(raw_files, list):
        if len(raw_files) == 2 and all(not isinstance(item, (dict, list)) for item in raw_files):
            raw_items = [raw_files]
        else:
            raw_items = raw_files
    else:
        raise BackendRouteError("Timeline files must be a list, pair, or object")

    files: list[list[str]] = []
    for item in raw_items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("file_name") or item.get("filename") or item.get("NAME")
            content = item.get("content_base64") or item.get("base64") or item.get("content") or item.get("data")
            upload_id = str(item.get("upload_id") or "").strip()
            if upload_id:
                path, upload = ready_file_for_actor(actor=current_actor(), upload_id=upload_id)
                name = name or upload["filename"]
                content = base64.b64encode(path.read_bytes()).decode("ascii")
        elif isinstance(item, list) and len(item) >= 2:
            name, content = item[0], item[1]
        else:
            raise BackendRouteError(
                "Each timeline file must be {name, content_base64}, {upload_id}, or [name, base64]"
            )
        if not name or not content:
            raise BackendRouteError("Each timeline file requires name and base64 content")
        files.append([str(name), str(content)])
    return files


async def _call_sales_funnel_health(arguments: dict[str, Any]) -> dict[str, Any]:
    params = dict(arguments.get("params") if isinstance(arguments.get("params"), dict) else arguments)
    category_id = str(params.get("category_id", params.get("CATEGORY_ID", "0")))
    include_executing = _bool_value(params.get("include_executing"), default=True)
    stale_days = _int_value(params.get("stale_days"), default=7, minimum=1)
    require_next_step = _bool_value(params.get("require_next_step"), default=True)
    dry_run = _bool_value(params.get("dry_run"), default=True)
    max_deals = _int_value(params.get("max_deals"), default=100, minimum=1, maximum=500)
    expected_currency = str(params.get("expected_currency") or os.getenv("BITRIX24_EXPECTED_CURRENCY_ID") or DEFAULT_EXPECTED_CURRENCY)
    field_names = _sales_field_names(params)

    base_url = _bitrix_base_url()
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        statuses = await _load_stage_statuses(client, base_url, category_id)
        deals = await _load_active_deals(
            client,
            base_url,
            category_id=category_id,
            include_executing=include_executing,
            field_names=field_names,
            max_deals=max_deals,
        )
        users = await _load_users(client, base_url, _deal_user_ids(deals))
        health_items = []
        now = datetime.now(timezone.utc)
        for deal in deals:
            activities = await _load_deal_activities(client, base_url, str(deal.get("ID") or ""))
            health_items.append(
                _deal_health_item(
                    deal=deal,
                    activities=activities,
                    users=users,
                    statuses=statuses,
                    field_names=field_names,
                    now=now,
                    stale_days=stale_days,
                    require_next_step=require_next_step,
                    expected_currency=expected_currency,
                )
            )

    return {
        "ok": True,
        "status": 200,
        "backend": "bitrix24",
        "method": "sales_funnel.health",
        "data": {
            "ok": True,
            "dry_run": dry_run,
            "category_id": category_id,
            "stale_days": stale_days,
            "require_next_step": require_next_step,
            "expected_currency": expected_currency,
            "count": len(health_items),
            "summary": _health_summary(health_items),
            "deals": health_items,
        },
    }


async def _load_active_deals(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    category_id: str,
    include_executing: bool,
    field_names: dict[str, str],
    max_deals: int,
) -> list[dict[str, Any]]:
    select = [
        "ID",
        "TITLE",
        "STAGE_ID",
        "CATEGORY_ID",
        "CLOSED",
        "OPPORTUNITY",
        "CURRENCY_ID",
        "ASSIGNED_BY_ID",
        "CONTACT_ID",
        "COMPANY_ID",
        "DATE_CREATE",
        "DATE_MODIFY",
        "BEGINDATE",
        "CLOSEDATE",
        "SOURCE_ID",
        "COMMENTS",
        field_names["next_step"],
        field_names["next_touch_date"],
        field_names["proposal_link"],
        field_names["contract_link"],
        field_names["discovery_link"],
    ]
    response = await _bitrix_request(
        client,
        base_url,
        "crm.deal.list",
        {
            "order": {"DATE_MODIFY": "ASC"},
            "filter": {"CATEGORY_ID": category_id, "CLOSED": "N"},
            "select": select,
            "start": 0,
        },
    )
    deals = _result_items(_response_data(response))[:max_deals]
    if include_executing:
        return deals
    return [deal for deal in deals if "EXECUT" not in str(deal.get("STAGE_ID") or "").upper()]


async def _load_stage_statuses(client: httpx.AsyncClient, base_url: str, category_id: str) -> dict[str, dict[str, Any]]:
    entity_ids = ["DEAL_STAGE"]
    if category_id not in {"", "0"}:
        entity_ids.append(f"DEAL_STAGE_{category_id}")
    statuses: dict[str, dict[str, Any]] = {}
    for entity_id in entity_ids:
        response = await _bitrix_request(
            client,
            base_url,
            "crm.status.list",
            {"filter": {"ENTITY_ID": entity_id}},
        )
        for item in _result_items(_response_data(response)):
            status_id = str(item.get("STATUS_ID") or item.get("ID") or "")
            if status_id:
                statuses[status_id] = item
    return statuses


async def _load_users(client: httpx.AsyncClient, base_url: str, user_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not user_ids:
        return {}
    response = await _bitrix_request(client, base_url, "user.get", {"ID": user_ids})
    return {
        str(item.get("ID")): item
        for item in _result_items(_response_data(response))
        if item.get("ID") is not None
    }


async def _load_deal_activities(client: httpx.AsyncClient, base_url: str, deal_id: str) -> list[dict[str, Any]]:
    if not deal_id:
        return []
    response = await _bitrix_request(
        client,
        base_url,
        "crm.activity.list",
        {
            "order": {"LAST_UPDATED": "DESC"},
            "filter": {"OWNER_TYPE_ID": DEAL_OWNER_TYPE_ID, "OWNER_ID": deal_id},
            "select": [
                "ID",
                "OWNER_TYPE_ID",
                "OWNER_ID",
                "TYPE_ID",
                "SUBJECT",
                "DESCRIPTION",
                "RESPONSIBLE_ID",
                "DEADLINE",
                "COMPLETED",
                "CREATED",
                "LAST_UPDATED",
            ],
            "start": 0,
        },
    )
    return _result_items(_response_data(response))


def _deal_health_item(
    *,
    deal: dict[str, Any],
    activities: list[dict[str, Any]],
    users: dict[str, dict[str, Any]],
    statuses: dict[str, dict[str, Any]],
    field_names: dict[str, str],
    now: datetime,
    stale_days: int,
    require_next_step: bool,
    expected_currency: str,
) -> dict[str, Any]:
    date_modify = _parse_datetime(deal.get("DATE_MODIFY"))
    days_since_update = (now - date_modify).days if date_modify else None
    stage_id = str(deal.get("STAGE_ID") or "")
    stage_meta = statuses.get(stage_id, {})
    amount = _float_value(deal.get("OPPORTUNITY"))
    currency = str(deal.get("CURRENCY_ID") or "")
    last_activity_date, next_activity_date = _activity_dates(activities, now)
    next_step = _string_value(deal.get(field_names["next_step"]))
    proposal_link = _string_value(deal.get(field_names["proposal_link"]))

    flags = {
        "no_amount": amount <= 0,
        "no_next_step": require_next_step and not next_step,
        "stale": days_since_update is not None and days_since_update >= stale_days,
        "no_activity": last_activity_date is None and next_activity_date is None,
        "late_stage_zero_amount": amount <= 0 and _is_late_stage(stage_id, stage_meta),
        "missing_proposal_link": not proposal_link and _is_late_stage(stage_id, stage_meta),
        "wrong_currency": bool(currency) and currency != expected_currency,
    }
    active_flags = [name for name, enabled in flags.items() if enabled]
    responsible_id = str(deal.get("ASSIGNED_BY_ID") or "")

    return {
        "id": deal.get("ID"),
        "title": deal.get("TITLE"),
        "stage": {"id": stage_id, "name": stage_meta.get("NAME") or stage_id},
        "amount": amount,
        "currency": currency,
        "responsible": _responsible(users.get(responsible_id), responsible_id),
        "date_modify": _format_datetime(date_modify),
        "days_since_update": days_since_update,
        "last_activity_date": _format_datetime(last_activity_date),
        "next_activity_date": _format_datetime(next_activity_date),
        "next_step": next_step,
        "hygiene_flags": active_flags,
        "suggested_nudge_text": _suggested_nudge(deal, active_flags, days_since_update),
    }


def _sales_field_names(params: dict[str, Any]) -> dict[str, str]:
    return {
        "next_step": str(params.get("next_step_field") or os.getenv("BITRIX24_NEXT_STEP_FIELD") or DEFAULT_NEXT_STEP_FIELD),
        "next_touch_date": str(params.get("next_touch_date_field") or os.getenv("BITRIX24_NEXT_TOUCH_DATE_FIELD") or DEFAULT_NEXT_TOUCH_DATE_FIELD),
        "proposal_link": str(params.get("proposal_link_field") or os.getenv("BITRIX24_PROPOSAL_LINK_FIELD") or DEFAULT_PROPOSAL_LINK_FIELD),
        "contract_link": str(params.get("contract_link_field") or os.getenv("BITRIX24_CONTRACT_LINK_FIELD") or DEFAULT_CONTRACT_LINK_FIELD),
        "discovery_link": str(params.get("discovery_link_field") or os.getenv("BITRIX24_DISCOVERY_LINK_FIELD") or DEFAULT_DISCOVERY_LINK_FIELD),
    }


def _result_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        nested = result.get("tasks") or result.get("items")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def _deal_user_ids(deals: list[dict[str, Any]]) -> list[str]:
    return sorted({str(deal.get("ASSIGNED_BY_ID")) for deal in deals if deal.get("ASSIGNED_BY_ID") not in {None, ""}})


def _activity_dates(activities: list[dict[str, Any]], now: datetime) -> tuple[datetime | None, datetime | None]:
    last_dates: list[datetime] = []
    next_dates: list[datetime] = []
    for activity in activities:
        for key in ("LAST_UPDATED", "CREATED"):
            value = _parse_datetime(activity.get(key))
            if value:
                last_dates.append(value)
        deadline = _parse_datetime(activity.get("DEADLINE"))
        completed = str(activity.get("COMPLETED") or "").upper() in {"Y", "YES", "TRUE", "1"}
        if deadline and not completed and deadline >= now:
            next_dates.append(deadline)
    return (max(last_dates) if last_dates else None, min(next_dates) if next_dates else None)


def _responsible(user: dict[str, Any] | None, fallback_id: str) -> dict[str, Any]:
    if not user:
        return {"id": fallback_id, "name": fallback_id}
    name = " ".join(part for part in [str(user.get("NAME") or "").strip(), str(user.get("LAST_NAME") or "").strip()] if part)
    return {
        "id": str(user.get("ID") or fallback_id),
        "name": name or str(user.get("EMAIL") or fallback_id),
        "email": user.get("EMAIL"),
        "active": user.get("ACTIVE"),
        "work_position": user.get("WORK_POSITION"),
    }


def _is_late_stage(stage_id: str, stage_meta: dict[str, Any]) -> bool:
    early_ids = {item.strip().upper() for item in os.getenv("BITRIX24_EARLY_STAGE_IDS", "NEW,PREPARATION,PREPAYMENT_INVOICE").split(",")}
    normalized_stage = stage_id.rsplit(":", 1)[-1].upper()
    if normalized_stage in early_ids:
        return False
    sort = _int_or_none(stage_meta.get("SORT"))
    if sort is not None:
        return sort > _int_value(os.getenv("BITRIX24_EARLY_STAGE_SORT_MAX"), default=20, minimum=0)
    return bool(stage_id)


def _suggested_nudge(deal: dict[str, Any], flags: list[str], days_since_update: int | None) -> str:
    if not flags:
        return ""
    details = ", ".join(flags)
    stale = f", не обновлялась {days_since_update} дн." if days_since_update is not None and "stale" in flags else ""
    return (
        f"Проверьте сделку #{deal.get('ID')} \"{deal.get('TITLE')}\"{stale}; "
        f"признаки: {details}. Нужен следующий шаг и актуализация CRM."
    )


def _health_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    flag_counts: dict[str, int] = {}
    for item in items:
        for flag in item.get("hygiene_flags", []):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    return {
        "total_active": len(items),
        "with_flags": sum(1 for item in items if item.get("hygiene_flags")),
        "flag_counts": dict(sorted(flag_counts.items())),
    }


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on"}


def _int_value(value: Any, *, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    parsed = _int_or_none(value)
    if parsed is None:
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
