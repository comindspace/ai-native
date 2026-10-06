"""Shared business views for the overview and metrics pages."""

from decimal import Decimal
from html import escape
from urllib.parse import urlencode

from gateway_mcp.routes.admin_ui import fmt_time

CSS = """<style>
/* Hallmark · genre: modern-minimal · macrostructure: business workbench · design-system: design.md · designed-as-app */
.pulse-head { display:flex; gap:var(--space-6); justify-content:space-between; align-items:flex-start; }
.pulse-head p { max-width:640px; margin:var(--space-3) 0 0; color:var(--color-muted); }
.pulse-head .button { flex-shrink:0; }
.pulse-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border-block:1px solid var(--color-border-strong); }
.pulse-kpi { padding:var(--space-5); min-width:0; border-right:1px solid var(--color-border); text-decoration:none; color:var(--color-ink); }
.pulse-kpi:last-child { border-right:0; }
.pulse-kpi:hover { background:var(--color-surface-muted); }
.pulse-kpi span,.pulse-kpi small { display:block; color:var(--color-muted); }
.pulse-kpi strong { display:block; font-size:clamp(20px,2.2vw,30px); line-height:1.25; margin:var(--space-3) 0; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.pulse-kpi small { font-size:12px; line-height:1.5; }
.pulse-kpi.attention strong { color:var(--color-danger); }
.pulse-layout { display:grid; grid-template-columns:minmax(0,2fr) minmax(260px,1fr); gap:var(--space-8); align-items:start; }
.pulse-section { display:grid; gap:var(--space-4); min-width:0; }
.pulse-section-head { display:flex; justify-content:space-between; align-items:baseline; gap:var(--space-3); }
.pulse-section-head a { white-space:nowrap; }
.pulse-note { font-size:12px; color:var(--color-muted); line-height:1.6; margin:0; }
.pulse-actions { margin:0; padding:0; list-style:none; border-top:1px solid var(--color-border-strong); }
.pulse-actions li { padding:var(--space-4) 0; border-bottom:1px solid var(--color-border); }
.pulse-actions a { display:block; color:var(--color-ink); font-weight:600; text-decoration:none; }
.pulse-actions a:hover { color:var(--color-accent); text-decoration:underline; }
.pulse-actions p { font-size:12px; color:var(--color-muted); margin:var(--space-2) 0 0; }
.pulse-empty { padding:var(--space-5); background:var(--color-surface-muted); border-radius:var(--radius-control); }
.pulse-empty h3 { margin:0 0 var(--space-2); }
.pulse-empty p { color:var(--color-muted); margin:var(--space-2) 0 var(--space-4); }
.pulse-contracts { table-layout:fixed; width:100%; }
.pulse-contracts th:first-child { width:30%; }
.pulse-contracts th,.pulse-contracts td { overflow-wrap:anywhere; }
.pulse-contracts a { font-weight:600; }
.pulse-contracts small { display:block; color:var(--color-muted); margin-top:var(--space-1); font-size:11px; }
.pulse-meter { display:block; width:100%; height:10px; margin-top:var(--space-2); accent-color:var(--color-accent); }
.pulse-readiness { display:flex; gap:var(--space-4); flex-wrap:wrap; padding:var(--space-4) 0; border-top:1px solid var(--color-border); }
.pulse-stage { display:grid; grid-template-columns:minmax(100px,1fr) auto; gap:var(--space-2); padding:var(--space-3) 0; border-bottom:1px solid var(--color-border); }
.pulse-stage strong { font-size:14px; }
.pulse-stage .pulse-note { grid-column:1/-1; }
.pulse-operations { display:flex; gap:var(--space-4); flex-wrap:wrap; align-items:center; padding-top:var(--space-5); border-top:1px solid var(--color-border); }
@media(max-width:1100px) { .pulse-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } .pulse-kpi:nth-child(2) {border-right:0;} .pulse-kpi:nth-child(n+3){border-top:1px solid var(--color-border);} .pulse-layout {grid-template-columns:minmax(0,1fr);} .pulse-layout > aside {grid-row:1;} }
@media(max-width:650px) { .pulse-head {display:grid;} .pulse-contracts thead{display:none;} .pulse-contracts,.pulse-contracts tbody,.pulse-contracts tr,.pulse-contracts td {display:block;width:100%;} .pulse-contracts tr{padding:var(--space-4) 0;border-bottom:1px solid var(--color-border);} .pulse-contracts td{border:0;padding:var(--space-2) 0;} .pulse-contracts td[data-label]::before{content:attr(data-label);display:block;font-size:11px;color:var(--color-muted);} .pulse-head .button{width:100%;} }
</style>"""

STATES = {
    "duplicate_deal": (
        "Нужно сверить распределение",
        "Проверить распределение договора",
        "Распределение суммы не подтверждено. До сверки договор исключён из итогов.",
    ),
    "over_amount": (
        "Труд дороже договора",
        "Пересмотреть объём и условия",
        "Затраты на труд достигли суммы договора. Проверь оставшиеся работы и допсоглашение.",
    ),
    "check_remaining": (
        "Проверить остаток работ",
        "Оценить затраты до завершения",
        "На труд ушло от 80% суммы договора. Проверь, хватит ли остатка на завершение и другие расходы.",
    ),
    "confirm_contract": (
        "Нужна сверка",
        "Сверить сумму договора",
        "Сумма сделки ещё не подтверждена или изменилась после сверки.",
    ),
    "duplicate_links": (
        "Несколько связей",
        "Проверить связи договора",
        "Один проект связан несколько раз. До сверки суммы исключены из расчёта.",
    ),
    "crm_unavailable": (
        "CRM недоступна",
        "Обновить данные договора",
        "Сумму сделки получить не удалось.",
    ),
    "worklogs_unavailable": (
        "Списания недоступны",
        "Обновить расчёт труда",
        "Списания не получены за отведённое время. Открой подробный расчёт.",
    ),
    "incomplete_worklogs": (
        "Неполные списания",
        "Проверить учёт времени",
        "Есть ограничение выборки или некорректные записи. Денежная оценка скрыта.",
    ),
    "no_worklogs": (
        "Нет списаний",
        "Проверить начало работ",
        "Списаний пока нет. Это не означает нулевые затраты.",
    ),
    "currency": (
        "Другая валюта",
        "Проверить валюту расчёта",
        "Ставки заданы в рублях. Стоимость труда с этой суммой не сравнивается.",
    ),
    "calculated": (
        "Расчёт доступен",
        "Открыть расчёт",
        "По списаниям и оценочным ставкам.",
    ),
}


def money(value, currency=""):
    if value is None:
        return "—"
    label = "₽" if currency == "RUB" else currency
    return f"{Decimal(str(value)):,.0f}".replace(",", " ") + (
        f" {label}" if label else ""
    )


def amounts(values):
    return (
        " · ".join(money(value, currency) for currency, value in sorted(values.items()))
        or "—"
    )


def project_href(project_id):
    return "/admin/metrics?" + urlencode(
        {"section": "business", "tracker_project_id": project_id}
    )


def sales_href(data, anchor=""):
    return (
        "/admin/metrics?"
        + urlencode(
            {"section": "sales", "category_id": (data or {}).get("category_id", "0")}
        )
        + anchor
    )


def _kpi(label, value, note, href, attention=False):
    return f'<a class="pulse-kpi{" attention" if attention else ""}" href="{escape(href)}"><span>{escape(label)}</span><strong>{escape(str(value))}</strong><small>{escape(note)}</small></a>'


def render_overview(data, counts=None):
    p, sales = data["portfolio"], data["sales"]
    ok = p.get("available", False)
    head = '<div class="pulse-head"><div><h1>Метрики</h1><p>Договоры, затраты и продажи. Что требует решения сейчас и откуда взять следующий доход.</p></div><a class="button secondary" href="/admin/metrics">Открыть экономику</a></div>'
    notes = (
        f"Сверено договоров: {p.get('confirmed_count', 0)} из {p.get('linked_count', 0)}"
        if ok
        else "Данные договоров недоступны"
    )
    kpis = _kpi(
        "Договорный портфель", amounts(p.get("totals", {})), notes, "/admin/metrics"
    )
    kpis += _kpi(
        "Оценка труда",
        money(p.get("labor_cost"), "RUB"),
        f"Договоров с полными списаниями: {p.get('calculated_count', 0)}",
        "/admin/metrics",
    )
    kpis += _kpi(
        "Проверить экономику",
        p.get("attention_count", "—"),
        "Труд занял от 80% суммы договора",
        "/admin/metrics",
        bool(p.get("attention_count")),
    )
    kpis += _kpi(
        "Открытые сделки",
        amounts(sales.get("currency_amounts", {})) if sales else "—",
        f"Воронка №{data['category_id']} · {sales['total_active']} сделок"
        if sales
        else "Данные CRM недоступны",
        sales_href(sales),
    )
    body = head + '<div class="pulse-kpis">' + kpis + "</div>"
    body += (
        '<div class="pulse-layout"><div class="pulse-section">'
        + render_portfolio(p, compact=True)
        + render_sales(sales, compact=True)
        + '</div><aside class="pulse-section"><h2>Решения на сегодня</h2>'
        + render_actions(p, sales)
        + "</aside></div>"
    )
    body += '<p class="pulse-note">Суммы договоров и открытых сделок не означают полученную выручку. Труд рассчитан по списаниям и оценочным ставкам; платежи, прочие расходы и оставшаяся работа ещё не учтены.</p>'
    pending = str(counts.get("pending", "—")) if counts else "—"
    users = str(counts.get("users", "—")) if counts else "—"
    body += f'<div class="pulse-operations"><span class="pulse-note">Администрирование</span><a href="/admin/access-requests">Заявки: {escape(pending)}</a><a href="/admin/users">Пользователи: {escape(users)}</a><a href="/admin/integrations">Подключения</a><a href="/admin/audit">Журнал</a></div>'
    return body


def render_actions(portfolio, sales):
    items = []
    if portfolio.get("available"):
        for row in [r for r in portfolio["rows"] if r["status"] != "calculated"][:4]:
            _, action, note = STATES[row["status"]]
            items.append(
                (f"{action}: {row['name']}", note, project_href(row["project_id"]))
            )
        if portfolio["unlinked"]:
            items.append(
                (
                    f"Проектов без связи с договором: {len(portfolio['unlinked'])}",
                    "Выбери сделку CRM и сверь её сумму с договором.",
                    "/admin/metrics#unlinked",
                )
            )
    else:
        items.append(
            (
                "Восстановить данные экономики",
                portfolio.get("reason", "Источник недоступен."),
                "/admin/integrations",
            )
        )
    if sales:
        if sales.get("no_next_step") is None:
            items.append(
                (
                    "Следующий шаг сделок не проверен",
                    "Поле CRM не настроено или недоступно. Уточни, где ведётся следующий шаг.",
                    sales_href(sales),
                )
            )
        if sales["stale"]:
            items.append(
                (
                    f"Сделки без обновлений: {sales['stale']}",
                    f"Нет обновлений {sales['stale_days']} дней. Объём: {amounts(sales.get('stale_amounts', {}))}.",
                    sales_href(sales, "#sales-attention"),
                )
            )
        if sales["no_amount"]:
            items.append(
                (
                    f"Сделки без суммы: {sales['no_amount']}",
                    "Пока их вклад в воронку неизвестен.",
                    sales_href(sales, "#sales-attention"),
                )
            )
    else:
        items.append(
            (
                "Проверить подключение CRM",
                "Сводка продаж сейчас недоступна.",
                "/admin/integrations",
            )
        )
    if not items:
        return '<p class="pulse-note">В доступной выборке нет этих сигналов. Прогноз завершения и платежи требуют отдельных данных.</p>'
    return (
        '<ul class="pulse-actions">'
        + "".join(
            f'<li><a href="{escape(href)}">{escape(title)}</a><p>{escape(note)}</p></li>'
            for title, note, href in items
        )
        + "</ul>"
    )


def render_portfolio(data, compact=False):
    heading = (
        '<div class="pulse-section-head"><h2>Экономика договоров</h2>'
        + ('<a href="/admin/metrics">Все договоры</a>' if compact else "")
        + "</div>"
    )
    if not data.get("available"):
        return (
            heading
            + f'<div class="pulse-empty"><h3>Данные экономики недоступны</h3><p>{escape(data.get("reason", "Проверь источники."))}</p><a href="/admin/integrations">Проверить подключения</a></div>'
        )
    rows = data["rows"][:6] if compact else data["rows"]
    summary = ""
    if not compact:
        summary = (
            '<div class="pulse-kpis">'
            + _kpi(
                "Подтверждённые договоры",
                amounts(data["totals"]),
                f"{data['confirmed_count']} договоров по валютам",
                "#contracts",
            )
            + _kpi(
                "Договоры в расчёте труда",
                money(data["comparable_amount"], "RUB"),
                f"{data['calculated_count']} договоров с полными списаниями",
                "#contracts",
            )
            + _kpi(
                "Оценка труда по ним",
                money(data["labor_cost"], "RUB"),
                "Та же выборка договоров",
                "#contracts",
            )
            + _kpi(
                "Затраты к сумме договоров",
                f"{data['consumed_percent']:.0f}%"
                if data["consumed_percent"] is not None
                else "—",
                "По договорам в расчёте; это не готовность работ",
                "#contracts",
            )
            + "</div>"
        )
    coverage = f"Просмотрены {len(data['rows'])} из {data['linked_count']} связанных проектов. Расчёт труда доступен для {data['calculated_count']}."
    if data["limited"]:
        coverage += " Выборка ограничена; общие суммы относятся только к ней."
    if not rows:
        table = '<div class="pulse-empty"><h3>Начни с одного договора</h3><p>Выбери проект ниже, укажи сделку CRM и подтверди сумму. После этого появятся затраты и доля договора, потраченная на труд.</p></div>'
    else:
        body = ""
        for row in rows:
            percent = row["consumed_percent"]
            ratio = (
                "—"
                if percent is None
                else f'{percent:.0f}%<meter class="pulse-meter" min="0" max="100" low="80" high="99" optimum="0" value="{min(percent, Decimal(100))}" aria-label="Доля суммы договора, потраченная на труд: {percent:.0f}%"></meter>'
            )
            state = STATES[row["status"]][0]
            body += f'<tr><td><a href="{escape(project_href(row["project_id"]))}">{escape(row["name"])}</a><small>{escape(state)}</small></td><td data-label="Сумма договора">{escape(money(row["amount"], row["currency"]))}<small>{"Подтверждена" if row["confirmed"] else "Нужна сверка"}</small></td><td data-label="Оценка труда">{escape(money(row["labor_cost"], "RUB"))}</td><td data-label="Доля затрат">{ratio}</td></tr>'
        table = (
            '<div id="contracts" class="table-wrap"><table class="pulse-contracts"><thead><tr><th>Договор и проект</th><th>Сумма договора</th><th>Оценка труда</th><th>Доля затрат</th></tr></thead><tbody>'
            + body
            + "</tbody></table></div>"
        )
    unlinked = ""
    if not compact and data["unlinked"]:
        entries = "".join(
            f'<li><a href="{escape(project_href(row["project_id"]))}">{escape(row["name"])}</a><p>Связать с договорной сделкой</p></li>'
            for row in data["unlinked"][:30]
        )
        unlinked = f'<details id="unlinked" open><summary>Без связи с договором: {len(data["unlinked"])}</summary><ul class="pulse-actions">{entries}</ul><p class="pulse-note">Показаны первые {min(30, len(data["unlinked"]))}; любой доступный проект можно выбрать в фильтре.</p></details>'
    return (
        '<section class="pulse-section">'
        + heading
        + summary
        + f'<p class="pulse-note">{escape(coverage)}</p>'
        + table
        + unlinked
        + f'<p class="pulse-note">Получено {escape(fmt_time(data["as_of"]))} UTC. Порог внимания — 80% суммы договора; оценка труда не является прогнозом прибыли.</p></section>'
    )


def render_sales(data, compact=False):
    head = (
        '<div class="pulse-section-head"><h2>Продажи и следующий доход</h2>'
        + (f'<a href="{escape(sales_href(data))}">К сделкам</a>' if compact else "")
        + "</div>"
    )
    if data is None:
        return (
            head
            + '<div class="pulse-empty"><p>CRM сейчас недоступна.</p><a href="/admin/integrations">Проверить подключение</a></div>'
        )
    label = f"Воронка №{data['category_id']}. Просмотрено {data['sampled']} из {data['total_active']} открытых сделок."
    if data["limited"]:
        label += " Суммы и сигналы рассчитаны по неполной выборке."
    if data.get("no_next_step") is None:
        label += (
            " Следующий шаг сделок не проверен: поле CRM не настроено или недоступно."
        )
    new = data.get("new_deals")
    label += (
        f" Новых за {data['days']} дней: {new if new is not None else 'нет данных'}."
    )
    stages = "".join(
        f'<div class="pulse-stage"><span>{escape(str(s["name"]))}</span><strong>{s["count"]}</strong><span class="pulse-note">{escape(amounts(s["amounts"]))}</span></div>'
        for s in data["stages"][: (5 if compact else 50)]
    )
    body = (
        head
        + f'<p class="pulse-note">{escape(label)}</p>'
        + (stages or '<p class="pulse-note">Открытых сделок в этой воронке нет.</p>')
    )
    if not compact:
        body += '<h2 id="sales-attention">Сделки, требующие внимания</h2>'
        rows = ""
        for row in data.get("attention", []):
            title = escape(row["title"])
            if row.get("url"):
                title = f'<a href="{escape(row["url"])}" target="_blank" rel="noopener">{title}</a>'
            rows += f'<tr id="deal-{escape(row["id"])}"><td>{title}<small>#{escape(row["id"])}</small></td><td data-label="Сумма">{escape(money(row["amount"], row["currency"]))}</td><td data-label="Действие">{escape(". ".join(row["reasons"]))}</td><td data-label="Обновлена">{escape(fmt_time(row["updated_at"]))}</td></tr>'
        body += (
            (
                '<div class="table-wrap"><table class="pulse-contracts"><thead><tr><th>Сделка</th><th>Сумма</th><th>Что проверить</th><th>Обновлена</th></tr></thead><tbody>'
                + rows
                + '</tbody></table></div><p class="pulse-note">До 50 сделок, сначала давно не обновлявшиеся.</p>'
            )
            if rows
            else '<p class="pulse-note">В доступных показателях эти сигналы не найдены.</p>'
        )
    return '<section class="pulse-section">' + body + "</section>"
