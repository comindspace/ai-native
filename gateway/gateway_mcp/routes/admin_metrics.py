from __future__ import annotations

import re
import secrets
from asyncio import gather, wait_for
from asyncio import to_thread as run_in_threadpool
from decimal import Decimal
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlencode

from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from gateway_mcp.routes.admin_ui import admin_shell, empty_row, fmt_time
from gateway_mcp.routes.business_pulse_ui import render_portfolio, render_sales
from gateway_mcp.services.admin_metrics import (
    agent_snapshot,
    gateway_snapshot,
    project_snapshot,
    runtime_snapshot,
    sales_snapshot,
    tracker_project_for,
    tracker_projects_snapshot,
    tracker_snapshot,
)
from gateway_mcp.services.business_economics import (
    DEFAULT_COST_RATE_RUB,
    calculate_economics,
    crm_deal_amount,
    project_worklogs,
)
from gateway_mcp.services.business_pulse import portfolio_snapshot
from gateway_mcp.services.factory_project_registry import load_factory_project_registry
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import has_scope
from gateway_mcp.services.storage_business import (
    cost_rates,
    delete_cost_rate,
    delete_project_link,
    list_project_links,
    project_link,
    save_cost_rate,
    save_project_link,
)
from gateway_mcp.web import login_redirect, web_actor

PERIODS = ((7, "7 дней"), (30, "30 дней"), (90, "90 дней"), (365, "365 дней"))
SECTIONS = (("gateway", "Шлюз"),)
CSRF_COOKIE = "gateway_business_csrf"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

METRICS_CSS = """
<style>
  .metrics-tabs { display: flex; gap: 20px; overflow-x: auto; border-bottom: 1px solid var(--color-border); }
  .metrics-tab { flex: 0 0 auto; padding: 11px 2px; color: var(--color-muted); text-decoration: none; font-size: 14px; border-bottom: 2px solid transparent; }
  .metrics-tab:hover { color: var(--color-ink); }
  .metrics-tab.active { border-color: var(--color-accent); color: var(--color-ink); font-weight: 600; }
  .metrics-controls { display: flex; align-items: end; flex-wrap: wrap; gap: 12px; }
  .metrics-controls label { min-width: 150px; }
  .metrics-controls .wide-control { flex: 1 1 220px; }
  .metrics-controls input { min-width: 0; }
  .metrics-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
  .metric { min-width: 0; padding: 18px 16px; border-right: 1px solid var(--color-border); }
  .metric:first-child { padding-left: 0; }
  .metric:last-child { border-right: 0; }
  .metric-name { color: var(--color-muted); font-size: 12px; }
  .metric-value { display: block; margin: 5px 0 3px; font-size: 24px; font-weight: 650; line-height: 1.1; overflow-wrap: anywhere; }
  .metric-note, .source-note { color: var(--color-muted); font-size: 12px; line-height: 1.5; }
  .source-note { margin: 0; }
  .metric-section { display: grid; gap: 12px; }
  .metric-section .panel { padding: 20px; }
  .metric-section .table-wrap { margin-top: 6px; }
  .metric-empty { padding: 22px 0; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
  .metric-empty p { max-width: 680px; margin: 8px 0 0; color: var(--color-muted); }
  .metrics-inline { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }
  .metrics-inline p { margin: 0; }
  .metric-link { color: var(--color-accent); text-decoration: none; }
  .metric-link:hover { text-decoration: underline; }
  .nowrap { white-space: nowrap; }
  .business-link-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 12px; align-items: end; }
  .business-link-form .access-check { align-self: center; }
  .business-link-form input[type="checkbox"] { width: 18px; min-height: 18px; flex: 0 0 18px; }
  .business-unlink-form { margin-top: 12px; }
  .business-rate-form { display: flex; align-items: center; gap: 8px; }
  .business-rate-form + .business-rate-form { margin-top: 8px; }
  .business-rate-form input { max-width: 132px; }
  .business-rate-form button { min-height: 40px; }
  .business-note { max-width: 920px; }
  .business-portfolio { display: grid; gap: 10px; }
  @media (max-width: 1000px) { .metrics-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); } .metric:nth-child(3) { border-right: 0; } .metric:nth-child(n+4) { border-top: 1px solid var(--color-border); } }
  @media (max-width: 650px) {
    .metrics-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metric:nth-child(3) { border-right: 1px solid var(--color-border); }
    .metric:nth-child(even) { border-right: 0; }
    .metric:nth-child(n+3) { border-top: 1px solid var(--color-border); }
    .metric:first-child { padding-left: 16px; }
    .metric-value { font-size: 20px; }
    .business-summary .metric:first-child, .business-summary .metric:nth-child(4) { grid-column: 1 / -1; border-right: 0; }
    .business-summary .metric:nth-child(2) { padding-left: 16px; }
    .metrics-controls { display: grid; grid-template-columns: 1fr; }
    .metrics-controls label, .metrics-controls button { width: 100%; }
    .business-link-form { grid-template-columns: 1fr; }
    .business-rate-table thead, .business-contract-table thead { display: none; }
    .business-rate-table, .business-rate-table tbody, .business-rate-table tr, .business-rate-table td,
    .business-contract-table, .business-contract-table tbody, .business-contract-table tr, .business-contract-table td { display: block; width: 100%; }
    .business-rate-table tr, .business-contract-table tr { padding: 12px 0; border-bottom: 1px solid var(--color-border); }
    .business-rate-table td, .business-contract-table td { padding: 4px 0; border: 0; }
    .business-rate-table td[data-label]::before, .business-contract-table td[data-label]::before { content: attr(data-label); display: block; margin-bottom: 2px; color: var(--color-muted); font-size: 11px; }
    .business-rate-form input { max-width: 160px; }
  }
</style>
"""


def register_admin_metrics_routes(mcp) -> None:
    @mcp.custom_route("/admin/metrics", methods=["GET"], include_in_schema=False)
    async def admin_metrics_page(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin/metrics")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)

        params = request.query_params
        section = str(params.get("section") or "gateway")
        if section not in {key for key, _ in SECTIONS}:
            section = "gateway"
        days = _choice_int(params.get("days"), {7, 30, 90, 365}, 30)
        header = f"""
        <div class="page-head"><div><h1>Состояние шлюза</h1>
        <p class="lead">Вызовы инструментов, ошибки и доступность корпоративных систем.</p></div></div>
        <nav class="metrics-tabs" aria-label="Разделы метрик">
          {"".join(_tab(key, label, section, days) for key, label in SECTIONS)}
          <a class="metrics-tab" href="/admin/showcase">Использование AI</a>
          <a class="metrics-tab" href="/admin/telemetry/skills">Навыки</a>
        </nav>
        """
        content = await _gateway(days)
        response = HTMLResponse(
            admin_shell(
                title="Метрики",
                active="metrics",
                actor=actor,
                body=header + content,
                shell_width="1440px",
                extra_head=METRICS_CSS,
            )
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @mcp.custom_route(
        "/admin/metrics/business", methods=["POST"], include_in_schema=False
    )
    async def business_action(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin/metrics?section=business")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)
        form = {
            key: values[-1]
            for key, values in parse_qs(
                (await request.body()).decode("utf-8"), keep_blank_values=True
            ).items()
        }
        cookie = str(request.cookies.get(CSRF_COOKIE) or "")
        if not cookie or not secrets.compare_digest(cookie, form.get("csrf", "")):
            return PlainTextResponse("CSRF token mismatch.", status_code=403)
        project_id = form.get("tracker_project_id", "").strip()
        if not _IDENTIFIER.fullmatch(project_id):
            return PlainTextResponse("Invalid Tracker project ID.", status_code=400)
        action = form.get("action")
        try:
            if action == "link":
                if not has_scope(actor, "tracker:read") or not has_scope(
                    actor, "bitrix24:read"
                ):
                    return PlainTextResponse(
                        "Tracker and CRM read scopes required.", status_code=403
                    )
                deal_id = int(form.get("crm_deal_id") or "")
                if deal_id <= 0:
                    raise ValueError("deal_id")
                projects = await tracker_projects_snapshot(actor_subject=actor.subject)
                if project_id not in {
                    str(row.get("short_id") or row.get("id"))
                    for row in projects["projects"]
                }:
                    raise ValueError("project_id")
                deal = await crm_deal_amount(deal_id)
                raw_amount = str(deal.get("OPPORTUNITY") or "").strip()
                amount = Decimal(raw_amount) if raw_amount else None
                currency = str(deal.get("CURRENCY_ID") or "")
                if form.get("contract_confirmed") == "1" and (
                    amount is None
                    or not amount.is_finite()
                    or amount <= 0
                    or not currency
                ):
                    raise ValueError("contract_amount")
                await run_in_threadpool(
                    save_project_link,
                    project_id=project_id,
                    deal_id=deal_id,
                    confirmed=form.get("contract_confirmed") == "1",
                    amount=amount,
                    currency=currency,
                    actor_subject=actor.subject,
                )
            elif action == "rate":
                user_id = form.get("tracker_user_id", "").strip()
                if not _IDENTIFIER.fullmatch(user_id):
                    raise ValueError("tracker_user_id")
                rate = Decimal(form.get("hourly_rate_rub") or "")
                if not rate.is_finite() or not 0 <= rate <= 100000:
                    raise ValueError("hourly_rate_rub")
                await run_in_threadpool(
                    save_cost_rate,
                    user_id=user_id,
                    rate=rate,
                    basis="estimate",
                    actor_subject=actor.subject,
                )
            elif action in {"unlink", "rate_delete"}:
                if action == "unlink":
                    await run_in_threadpool(delete_project_link, project_id=project_id)
                else:
                    user_id = form.get("tracker_user_id", "").strip()
                    if not _IDENTIFIER.fullmatch(user_id):
                        raise ValueError("tracker_user_id")
                    await run_in_threadpool(delete_cost_rate, user_id=user_id)
            else:
                raise ValueError("action")
        except (ValueError, TypeError, ArithmeticError):
            return PlainTextResponse("Invalid business configuration.", status_code=400)
        except Exception as exc:  # noqa: BLE001 - don't render backend data or secrets
            audit_event(
                event="business_config_change",
                actor=actor,
                system="business",
                status="error",
                arguments={"action": action, "error_class": type(exc).__name__},
            )
            return PlainTextResponse("Business source unavailable.", status_code=503)
        audit_event(
            event="business_config_change",
            actor=actor,
            system="business",
            status="ok",
            arguments={"action": action, "tracker_project_id": project_id},
        )
        return RedirectResponse(
            "/admin/metrics?"
            + urlencode({"section": "business", "tracker_project_id": project_id}),
            status_code=303,
        )


async def _business(request: Request, actor: Any, csrf: str) -> str:
    if not has_scope(actor, "tracker:read") or not has_scope(actor, "bitrix24:read"):
        return '<div class="banner error">Для экономики нужны права tracker:read и bitrix24:read.</div>'
    try:
        projects = await wait_for(
            tracker_projects_snapshot(actor_subject=actor.subject), timeout=8
        )
        links = await run_in_threadpool(list_project_links)
    except Exception as exc:  # noqa: BLE001 - preserve privacy at HTTP boundary
        return _error("Tracker / конфигурация", exc)
    selected = _text(request.query_params.get("tracker_project_id"), 100)
    controls = _controls(
        "business", 30, _tracker_project_control(selected, projects), show_period=False
    )
    intro = (
        '<p class="source-note business-note">Источник суммы: подтверждённая связка проекта с CRM-сделкой. '
        "Источник часов: списания Tracker за всё время проекта. Ставки пока оценочные, "
        "прочие расходы и оплата по договору не учитываются.</p>"
    )
    if not selected:
        snapshot = await portfolio_snapshot(actor, projects=projects, links=links)
        return controls + intro + render_portfolio(snapshot)
    portfolio = '<p><a href="/admin/metrics">К экономике всех договоров</a></p>'
    if not _IDENTIFIER.fullmatch(selected):
        return (
            controls
            + portfolio
            + '<div class="banner error">Некорректный ID проекта.</div>'
        )
    selected_project = next(
        (
            row
            for row in projects["projects"]
            if selected in {str(row.get("short_id") or ""), str(row.get("id") or "")}
        ),
        None,
    )
    if selected_project is None:
        return (
            controls
            + portfolio
            + '<div class="banner error">Проект не найден в доступном списке Tracker.</div>'
        )
    try:
        link = await run_in_threadpool(project_link, selected)
    except Exception as exc:  # noqa: BLE001
        return controls + portfolio + _error("Конфигурация договоров", exc)
    link_form = _business_link_form(selected, link, csrf)
    if not link:
        return controls + intro + portfolio + link_form
    try:
        deal, worklogs, rates = await wait_for(
            asyncio_gather_business(actor.subject, selected, int(link["crm_deal_id"])),
            timeout=35,
        )
        amount_unchanged = (
            link.get("confirmed_amount") is not None
            and Decimal(str(link["confirmed_amount"]))
            == Decimal(str(deal.get("OPPORTUNITY") or "0"))
            and str(link.get("confirmed_currency") or "")
            == str(deal.get("CURRENCY_ID") or "")
        )
        result = calculate_economics(
            deal=deal,
            confirmed=bool(link["contract_confirmed"]) and amount_unchanged,
            logs=worklogs["logs"],
            rates=rates,
            complete=not worklogs["limited"],
        )
    except Exception as exc:  # noqa: BLE001
        return (
            controls
            + intro
            + portfolio
            + link_form
            + _error("CRM / списания Tracker", exc)
        )
    amount = (
        f"{_money(result['amount'])} {result['currency']}"
        if result["amount"] is not None
        else None
    )
    labor = (
        f"{_money(result['labor_cost'])} ₽"
        if result["labor_cost"] is not None
        else None
    )
    balance = (
        f"{_money(result['balance_after_logged_labor'])} ₽"
        if result["balance_after_logged_labor"] is not None
        else None
    )
    summary = _summary(
        (
            "Сумма сделки CRM",
            amount,
            "подтверждена договором"
            if result["confirmed"]
            else "не подтверждена договором",
        ),
        (
            "Списано часов",
            f"{_money(result['hours'])} ч",
            f"{worklogs['issue_count']} задач Tracker",
        ),
        ("Оценка труда", labor, "по списаниям и расчётным ставкам"),
        ("Остаток после труда", balance, "не прибыль: без прочих расходов"),
        (
            "Ставки настроены",
            f"{result['reviewed_rates']} из {len(result['authors'])}",
            "остальным применена общая оценка",
        ),
    ).replace('class="metrics-summary"', 'class="metrics-summary business-summary"', 1)
    incomplete = ""
    if not result["complete"]:
        incomplete = (
            '<div class="banner error">Списаний по проекту пока нет. Денежный итог скрыт.</div>'
            if not worklogs["logs"]
            else '<div class="banner error">Выборка Tracker неполная или есть неизвестные длительности. Денежный итог скрыт.</div>'
        )
    if link["contract_confirmed"] and not amount_unchanged:
        incomplete += '<div class="banner error">Сумма сделки изменилась после сверки с договором. Подтверди её заново.</div>'
    rate_rows = "".join(
        _business_rate_row(row, selected, csrf) for row in result["authors"]
    ) or empty_row(4, "Списаний по проекту пока нет")
    return (
        controls
        + intro
        + portfolio
        + incomplete
        + summary
        + link_form
        + '<section class="panel wide"><div class="panel-header"><h2>Авторы списаний и расчётные ставки</h2></div>'
        + f'<p class="source-note">Общая ставка {_money(DEFAULT_COST_RATE_RUB)} ₽/ч — временная модель: <a href="https://habr.com/ru/specials/1060148/" target="_blank" rel="noopener">медиана рынка 191 000 ₽/мес</a>, 160 часов и расчётный коэффициент затрат 1,5. Это не зарплаты сотрудников. День Tracker принят равным 8 часам, неделя — 40 часам. Ставка применяется ко всем прошлым списаниям.</p>'
        + '<div class="table-wrap"><table class="business-rate-table"><thead><tr><th>Автор списания Tracker</th><th>Часы</th><th>Оценка труда</th><th>Ставка, ₽/ч</th></tr></thead>'
        + f"<tbody>{rate_rows}</tbody></table></div></section>"
        + f'<p class="source-note">Охват: {worklogs["issue_count"]} из {worklogs["total_issues"] if worklogs["total_issues"] is not None else "неизвестно"} задач. Неизвестных длительностей: {result["invalid_durations"]}; списаний без автора: {result["unknown_authors"]}. Прогноз до завершения требует оценку оставшейся работы.</p>'
    )


async def asyncio_gather_business(actor_subject: str, project_id: str, deal_id: int):
    return await gather(
        crm_deal_amount(deal_id),
        project_worklogs(actor_subject=actor_subject, tracker_project_id=project_id),
        run_in_threadpool(cost_rates),
    )


def _business_link_form(project_id: str, link: dict[str, Any] | None, csrf: str) -> str:
    deal_id = str(link["crm_deal_id"]) if link else ""
    checked = " checked" if link and link["contract_confirmed"] else ""
    delete_form = ""
    if link:
        delete_form = f'''<form method="post" action="/admin/metrics/business" class="business-unlink-form">
          <input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="action" value="unlink">
          <input type="hidden" name="tracker_project_id" value="{escape(project_id)}">
          <button type="submit" class="secondary">Удалить связь</button>
        </form>'''
    return f'''<section class="panel wide"><h2>Связь с договором</h2>
      <p class="source-note">Укажи ID сделки, сумма которой соответствует договору проекта. Подтверждение ставится после сверки с документом.</p>
      <form method="post" action="/admin/metrics/business" class="business-link-form">
        <input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="action" value="link">
        <input type="hidden" name="tracker_project_id" value="{escape(project_id)}">
        <label>ID сделки Bitrix24<input name="crm_deal_id" type="number" min="1" value="{escape(deal_id)}" required></label>
        <label class="access-check"><input type="checkbox" name="contract_confirmed" value="1"{checked}>Сумма сверена с договором</label>
        <button type="submit">Сохранить связь</button>
      </form>
      {delete_form}</section>'''


def _business_rate_row(row: dict[str, Any], project_id: str, csrf: str) -> str:
    user_id = str(row["user_id"])
    form = '<span class="source-note">Неизвестный пользователь</span>'
    if _IDENTIFIER.fullmatch(user_id):
        form = f'''<form method="post" action="/admin/metrics/business" class="business-rate-form">
          <input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="action" value="rate">
          <input type="hidden" name="tracker_project_id" value="{escape(project_id)}">
          <input type="hidden" name="tracker_user_id" value="{escape(user_id)}">
          <input aria-label="Ставка для {escape(str(row["display"]))}" name="hourly_rate_rub" type="number" min="0" max="100000" step="0.01" value="{escape(str(row["rate"]))}" required>
          <button type="submit" class="secondary" title="Сохранить расчётную ставку">Сохранить</button>
        </form>'''
        if row["basis"] != "market_proxy":
            form += f'''<form method="post" action="/admin/metrics/business" class="business-rate-form">
              <input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="action" value="rate_delete">
              <input type="hidden" name="tracker_project_id" value="{escape(project_id)}"><input type="hidden" name="tracker_user_id" value="{escape(user_id)}">
              <button type="submit" class="secondary">Вернуть общую ставку</button>
            </form>'''
    return (
        "<tr>"
        f'<td>{escape(str(row["display"]))}<span class="table-sub">{escape("Рыночная оценка" if row["basis"] == "market_proxy" else "Настроенная оценка")}</span></td>'
        f'<td data-label="Часы">{_money(row["hours"])}</td><td data-label="Оценка труда">{_money(row["cost"])} ₽</td><td data-label="Ставка, ₽/ч">{form}</td></tr>'
    )


async def _projects(request: Request, actor: Any, days: int) -> str:
    project_id = _text(request.query_params.get("project_id"), 120)
    explicit_tracker_id = _text(request.query_params.get("tracker_project_id"), 60)
    tracker_id = explicit_tracker_id or (
        tracker_project_for(project_id) if project_id else ""
    )
    tracker_projects = None
    tracker_list_note = ""
    if has_scope(actor, "tracker:read"):
        try:
            tracker_projects = await wait_for(
                tracker_projects_snapshot(actor_subject=actor.subject), timeout=8
            )
        except Exception:  # noqa: BLE001 - retain manual project entry when Tracker is unavailable
            tracker_list_note = '<p class="source-note">Список проектов Tracker недоступен. Можно указать ID вручную.</p>'
    controls = _controls(
        "projects",
        days,
        _project_control(project_id)
        + _tracker_project_control(tracker_id, tracker_projects),
    )
    if tracker_projects and tracker_projects.get("limited"):
        tracker_list_note = '<p class="source-note">Список проектов Tracker неполный. Все проекты доступны в Tracker.</p>'
    try:
        data = await run_in_threadpool(project_snapshot, days, project_id)
        rows = data["projects"]
        totals = {
            key: sum(_int(row.get(key)) for row in rows)
            for key in (
                "runs",
                "accepted_runs",
                "blocked_runs",
                "open_runs",
                "first_pass_runs",
            )
        }
        accepted = totals["accepted_runs"]
        summary = _summary(
            ("Работ поступило", totals["runs"], "Work Contract за период"),
            ("Принято", accepted, "текущий статус работ периода"),
            ("Заблокировано", totals["blocked_runs"], "нужен разбор причины"),
            ("В работе", totals["open_runs"], "включая ожидание приёмки"),
            (
                "С первого прохода",
                _percent(totals["first_pass_runs"], accepted),
                "среди принятых",
            ),
        )
        ledger = f"""
        <section class="metric-section"><div class="metrics-inline"><h2>Исполнение по проектам</h2><p class="source-note">Источник: Gateway Work Contract · период поступления: {days} дней</p></div>
          <div class="panel wide"><div class="table-wrap"><table>
            <thead><tr><th>Проект</th><th>Поступило</th><th>Принято</th><th>Блок</th><th>Открыто</th><th>Первый проход</th><th>До проверки, медиана</th><th>До приёмки, медиана</th><th>Блок длится</th><th>Активность</th></tr></thead>
            <tbody>{_project_rows(rows, days)}</tbody>
          </table></div></div>
        </section>
        """
        if len(rows) == 200:
            ledger += '<p class="source-note">Показаны первые 200 проектов по числу работ; общие итоги относятся к этой выборке.</p>'
    except Exception as exc:  # noqa: BLE001 - keep independent sources from breaking the dashboard
        summary = ""
        ledger = _error("Work Contract", exc)

    if tracker_id and not has_scope(actor, "tracker:read"):
        tracker_body = '<div class="banner error">Для метрик Tracker требуется право tracker:read.</div>'
    elif tracker_id:
        try:
            tracker = await tracker_snapshot(
                actor_subject=actor.subject, tracker_project_id=tracker_id
            )
            tracker_body = _tracker_panel(tracker)
        except Exception as exc:  # noqa: BLE001 - report source outage without exposing response data
            tracker_body = _error("Tracker", exc, "/credentials")
    else:
        tracker_body = '<section class="metric-empty"><h2>Сроки и риски задач</h2><p>Выбери проект с привязкой к Tracker или укажи ID проекта Tracker.</p></section>'

    return (
        controls
        + tracker_list_note
        + summary
        + tracker_body
        + ledger
        + '<p class="source-note">Риски, решения и контрольные точки из Yonote пока не входят в числовой расчёт. Блокировка Work Contract и просрочка задачи Tracker показаны отдельно.</p>'
    )


def _tracker_panel(data: dict[str, Any]) -> str:
    summary = _summary(
        ("Открыто", data["open"], "из задач проекта"),
        ("Просрочено", data["overdue"], "срок раньше сегодня"),
        ("Срок ≤ 7 дней", data["due_soon"], "ещё не просрочены"),
        ("Пауза / блок", data["paused"], "по статусу задачи"),
        ("Без исполнителя", data["unassigned"], "открытые задачи"),
    )
    attention = "".join(
        "<tr>"
        f'<td><a class="metric-link" href="https://tracker.yandex.ru/{escape(str(item["key"]))}" target="_blank" rel="noopener">{escape(str(item["key"]))}</a></td>'
        f"<td>{escape(str(item['deadline'] or '—'))}</td>"
        f"<td>{escape(str(item['status'] or '—'))}</td>"
        "</tr>"
        for item in data["attention"]
        if str(item["key"]).replace("-", "").isalnum()
    ) or empty_row(3, "Задач с ближайшими сроками или паузой нет")
    coverage = f"{data['sampled']} из {data['total']}"
    limited = (
        " · выборка ограничена, показатели могут быть неполными"
        if data["limited"]
        else ""
    )
    return f"""
    <section class="metric-section"><div class="metrics-inline"><h2>Сроки и риски задач</h2><p class="source-note">Tracker · проект {escape(data["project_id"])} · охват {coverage}{limited}</p></div>
      {summary}
      <p class="source-note">Не обновлялись более 7 дней: {data["stale"]}. Сроки сравниваются с датой в Москве. Статус «Пауза» трактуется как сигнал для проверки, а не как подтверждённый риск.</p>
      <div class="panel wide"><div class="panel-header"><h2>Требуют внимания</h2><span class="status neutral">до 20 задач</span></div><div class="table-wrap"><table>
        <thead><tr><th>Задача</th><th>Срок</th><th>Статус</th></tr></thead><tbody>{attention}</tbody>
      </table></div></div>
    </section>
    """


async def _sales(request: Request, actor: Any, days: int) -> str:
    category_id = _text(request.query_params.get("category_id"), 8) or "0"
    stale_days = _choice_int(request.query_params.get("stale_days"), {7, 14, 30}, 7)
    controls = _controls(
        "sales",
        days,
        f'<label>Воронка Bitrix24<input name="category_id" value="{escape(category_id)}" inputmode="numeric" placeholder="0"></label>'
        f'<label>Без движения<select name="stale_days">{_options(((7, "7 дней"), (14, "14 дней"), (30, "30 дней")), stale_days)}</select></label>',
    )
    if not has_scope(actor, "bitrix24:read"):
        return (
            controls
            + '<div class="banner error">Для метрик продаж требуется право bitrix24:read.</div>'
        )
    try:
        data = await sales_snapshot(
            category_id=category_id, days=days, stale_days=stale_days
        )
    except Exception as exc:  # noqa: BLE001 - report source outage without exposing response data
        return controls + _error("Bitrix24", exc, "/admin/integrations")
    return controls + render_sales(data)


async def _gateway(days: int) -> str:
    controls = _controls("gateway", days)
    try:
        data = await run_in_threadpool(gateway_snapshot, days)
    except Exception as exc:  # noqa: BLE001 - keep the dashboard available during DB outages
        return controls + _error("Журнал Gateway", exc)
    totals = data["totals"]
    calls = _int(totals.get("tool_calls"))
    summary = _summary(
        ("Вызовы", calls, "инструменты Gateway"),
        (
            "Ошибки",
            totals.get("tool_errors"),
            _percent(totals.get("tool_errors"), calls) + " вызовов",
        ),
        ("Отказы", totals.get("tool_denials"), "по правам доступа"),
        ("Пользователи", totals.get("active_actors"), "вызывали инструменты"),
        ("Входы", totals.get("logins"), "успешные авторизации"),
    )
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row.get('tool') or '—'))}</code></td>"
        f"<td>{escape(str(row.get('system') or '—'))}</td>"
        f"<td>{_int(row.get('calls'))}</td><td>{_int(row.get('errors'))}</td><td>{_int(row.get('denials'))}</td>"
        "</tr>"
        for row in data["routes"]
    ) or empty_row(5, "Вызовов за период нет")
    live = runtime_snapshot()
    live_summary = _summary(
        (
            "Среднее время",
            f"{live['average_latency_ms']} мс"
            if live["average_latency_ms"] is not None
            else None,
            "вызовы инструментов",
        ),
        ("Ошибки входа", live["auth_failures"], "причины в /metrics"),
        ("Ошибки систем", live["upstream_errors"], "внешние API"),
        ("Память", live["memory_operations"], "операции поиска и записи"),
        ("Приватность", live["privacy_entities"], "обработанные сущности"),
    )
    return f"""
    {controls}
    <p class="source-note">Источник: журнал Gateway в Postgres · период: {days} дней. Счётчики Prometheus на /metrics показывают технические события с момента запуска процесса.</p>
    {summary}
    <section class="panel wide"><div class="panel-header"><h2>Чаще всего вызывают</h2><span class="status neutral">до 20 инструментов</span></div><div class="table-wrap"><table>
      <thead><tr><th>Инструмент</th><th>Система</th><th>Вызовы</th><th>Ошибки</th><th>Отказы</th></tr></thead><tbody>{rows}</tbody>
    </table></div></section>
    <section class="metric-section"><h2>Текущий процесс Gateway</h2>
      <p class="source-note">Prometheus · с последнего запуска процесса. В многопроцессном развёртывании это показатели обслужившего запрос процесса.</p>
      {live_summary}
      <p class="source-note">Отказы политик: {live["policy_denials"]}; запросы приватного LLM proxy: {live["llm_proxy_requests"]}.</p>
    </section>
    """


async def _agents(days: int) -> str:
    controls = _controls("agents", days)
    try:
        data = await run_in_threadpool(agent_snapshot, days)
    except Exception as exc:  # noqa: BLE001 - keep the dashboard available during DB outages
        return controls + _error("Телеметрия агентов", exc)
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('agent') or '—'))}</td>"
        f"<td>{escape(str(item.get('provider') or '—'))} / {escape(str(item.get('model') or '—'))}</td>"
        f"<td>{escape(str(item.get('project') or '—'))}</td>"
        f"<td>{escape(str(item.get('source_quality') or '—'))}</td>"
        f"<td>{_int(item.get('event_count'))}</td>"
        f"<td>{_int(item.get('total_tokens')):,}</td>"
        f"<td>{_money(item.get('estimated_cost_usd') or 0)} $</td>"
        "</tr>"
        for item in data.get("usage", [])
    ) or empty_row(7, "Агенты не передавали данные об использовании за период")
    return f"""
    {controls}
    <p class="source-note">Источник: отчёты агентов через Gateway · до 200 строк. `actual`, `estimated` и импорт биллинга показаны отдельно; суммы между ними не складываются.</p>
    <section class="panel wide"><div class="panel-header"><h2>Модели и расход</h2><a class="metric-link" href="/admin/telemetry/skills">Использование навыков</a></div>
      <div class="table-wrap"><table><thead><tr><th>Агент</th><th>Модель</th><th>Проект</th><th>Качество данных</th><th>События</th><th>Токены</th><th>Оценка, USD</th></tr></thead><tbody>{rows}</tbody></table></div>
    </section>
    """


def _tab(key: str, label: str, current: str, days: int) -> str:
    href = "/admin/metrics?" + urlencode({"section": key, "days": days})
    active = " active" if key == current else ""
    return f'<a class="metrics-tab{active}" href="{href}">{label}</a>'


def _project_control(current: str) -> str:
    try:
        projects = load_factory_project_registry().get("projects", [])
    except Exception:  # noqa: BLE001 - the free-text fallback still works without the registry
        projects = []
    choices = {
        str(item.get("project_id") or ""): str(
            item.get("name") or item.get("project_id") or ""
        )
        for item in projects
        if isinstance(item, dict) and item.get("project_id")
    }
    if not choices:
        return f'<label class="wide-control">Проект в журнале работ<input name="project_id" value="{escape(current)}" placeholder="Код проекта"></label>'
    if current and current not in choices:
        choices[current] = current
    options = '<option value="">Все проекты Work Contract</option>' + "".join(
        f'<option value="{escape(key)}"{" selected" if key == current else ""}>{escape(label)}</option>'
        for key, label in sorted(choices.items(), key=lambda pair: pair[1].casefold())
    )
    return f'<label class="wide-control">Проект в журнале работ<select name="project_id">{options}</select></label>'


def _tracker_project_control(current: str, snapshot: dict[str, Any] | None) -> str:
    projects = snapshot.get("projects", []) if snapshot else []
    choices = {
        str(row.get("short_id") or row.get("id") or ""): str(row.get("name") or "")
        for row in projects
        if row.get("short_id") or row.get("id")
    }
    if not choices:
        return f'<label>Проект Tracker<input name="tracker_project_id" value="{escape(current)}" placeholder="ID проекта"></label>'
    if current and current not in choices:
        choices[current] = current
    options = '<option value="">Не выбран</option>' + "".join(
        f'<option value="{escape(key)}"{" selected" if key == current else ""}>{escape(label or key)}</option>'
        for key, label in sorted(choices.items(), key=lambda pair: pair[1].casefold())
    )
    return f'<label>Проект Tracker<select name="tracker_project_id">{options}</select></label>'


def _controls(
    section: str, days: int, fields: str = "", *, show_period: bool = True
) -> str:
    return f"""
    <form class="metrics-controls" method="get" action="/admin/metrics">
      <input type="hidden" name="section" value="{escape(section)}">
      {f'<label>Период<select name="days">{_options(PERIODS, days)}</select></label>' if show_period else ""}
      {fields}<button type="submit">Показать</button>
    </form>
    """


def _options(items: tuple[tuple[int, str], ...], selected: int) -> str:
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{escape(label)}</option>'
        for value, label in items
    )


def _summary(*metrics: tuple[str, Any, str]) -> str:
    return (
        '<div class="metrics-summary">'
        + "".join(
            '<div class="metric">'
            f'<span class="metric-name">{escape(label)}</span>'
            f'<strong class="metric-value">{escape(_value(value))}</strong>'
            f'<span class="metric-note">{escape(note)}</span>'
            "</div>"
            for label, value, note in metrics
        )
        + "</div>"
    )


def _project_rows(rows: list[dict[str, Any]], days: int) -> str:
    if not rows:
        return empty_row(10, "За выбранный период Work Contract не создавались")
    return "".join(
        "<tr>"
        f'<td><a class="metric-link" href="/admin/metrics?{urlencode({"section": "projects", "days": days, "project_id": str(row.get("project_id") or "")})}">{escape(str(row.get("project_id") or "—"))}</a></td>'
        f"<td>{_int(row.get('runs'))}</td><td>{_int(row.get('accepted_runs'))}</td>"
        f"<td>{_int(row.get('blocked_runs'))}</td><td>{_int(row.get('open_runs'))}</td>"
        f"<td>{escape(_percent(row.get('first_pass_runs'), row.get('accepted_runs')))}</td>"
        f"<td>{escape(_duration(row.get('p50_signal_to_verified_seconds')))}</td>"
        f"<td>{escape(_duration(row.get('p50_signal_to_accepted_seconds')))}</td>"
        f"<td>{escape(_duration(row.get('oldest_blocked_seconds')))}</td>"
        f'<td class="nowrap">{escape(fmt_time(row.get("last_activity_at")))}</td>'
        "</tr>"
        for row in rows
    )


def _error(source: str, exc: Exception, action: str = "") -> str:
    if isinstance(exc, ValueError):
        detail = "проверь указанный идентификатор"
    elif source in {"Work Contract", "Журнал Gateway", "Телеметрия агентов"}:
        detail = "проверь подключение к базе данных"
    else:
        detail = "проверь права и подключение к исходной системе"
    link = (
        f' <a class="metric-link" href="{action}">Проверить подключение</a>'
        if action
        else ""
    )
    return f'<div class="banner error">Источник {escape(source)} недоступен: {detail}.{link}</div>'


def _choice_int(value: Any, allowed: set[int], default: int) -> int:
    try:
        parsed = int(str(value or default))
    except ValueError:
        return default
    return parsed if parsed in allowed else default


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _value(value: Any) -> str:
    return "—" if value is None else str(value)


def _percent(numerator: Any, denominator: Any) -> str:
    total = _int(denominator)
    return f"{100 * _int(numerator) / total:.0f}%" if total else "—"


def _duration(value: Any) -> str:
    if value is None:
        return "—"
    seconds = max(0, float(value))
    if seconds < 3600:
        return f"{seconds / 60:.0f} мин"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} ч"
    return f"{seconds / 86400:.1f} дн"


def _money(value: Any) -> str:
    amount = Decimal(str(value or 0))
    return f"{amount:,.2f}".replace(",", " ")


def _amounts(values: dict[str, Any]) -> str:
    return "; ".join(
        f"{_money(amount)} {currency}" for currency, amount in sorted(values.items())
    )
