"""Server-rendered coMind showcase. Every chart is backed by aggregate telemetry."""

import json
from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode

from gateway_mcp.routes.admin_ui import fmt_time

CSS = """<style>
/* Hallmark: modern-minimal, corporate directory. Function carries the page. */
.showcase { --text-display:clamp(32px,3.4vw,48px); --text-metric:32px; --radius-card:16px; --radius-pill:99px; display:grid; gap:var(--space-8); }
.showcase h1 {font-size:var(--text-display);letter-spacing:-.045em;line-height:1.1;margin:var(--space-2) 0 var(--space-4);}
.showcase h2 {font-size:22px;letter-spacing:-.025em;margin:0;}
.showcase h3 {font-size:18px;letter-spacing:-.015em;margin:0;}
.showcase p {line-height:1.6;} .showcase small {font-size:12px;color:var(--color-muted);}
.showcase a {text-underline-offset:3px;} .showcase :is(a,span,p,strong,h2,h3,small) {overflow-wrap:anywhere;}
.sc-top,.sc-section-head,.sc-person-head,.sc-line {display:flex;justify-content:space-between;align-items:center;gap:var(--space-4);}
.sc-top {align-items:flex-start;} .sc-top p {max-width:600px;color:var(--color-muted);margin:0;}
.sc-eyebrow {font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--color-accent);font-weight:700;}
.sc-period {display:flex;gap:var(--space-1);background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-pill);padding:var(--space-1);flex-shrink:0;}
.sc-period a {padding:var(--space-2) var(--space-3);border-radius:var(--radius-pill);color:var(--color-muted);font-size:12px;text-decoration:none;white-space:nowrap;}
.sc-period a[aria-current="true"] {background:var(--color-ink);color:var(--color-surface);}
.sc-tabs {display:flex;gap:var(--space-6);border-bottom:1px solid var(--color-border);flex-wrap:wrap;}
.sc-tabs a {padding:0 0 var(--space-3);color:var(--color-muted);text-decoration:none;font-weight:600;font-size:13px;}
.sc-tabs a[aria-current="page"] {color:var(--color-accent);border-bottom:2px solid var(--color-accent);}
.sc-metrics {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--color-border);border-radius:var(--radius-card);background:var(--color-surface);}
.sc-metric {padding:var(--space-6);min-width:0;border-right:1px solid var(--color-border);}
.sc-metric:last-child {border:0;} .sc-metric strong {display:block;font-size:var(--text-metric);font-weight:650;letter-spacing:-.04em;line-height:1.2;margin:var(--space-3) 0;}
.sc-metric span {font-size:12px;color:var(--color-muted);} .sc-metric strong.sc-accent {color:var(--color-accent);}
.sc-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-4);}
.sc-card {background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-card);padding:var(--space-6);display:flex;flex-direction:column;gap:var(--space-5);min-width:0;transition:border-color var(--dur-short) var(--ease-out);}
.sc-card:hover {border-color:var(--color-border-strong);} .sc-card h3 a {color:var(--color-ink);text-decoration:none;}
.sc-card h3 a:hover {color:var(--color-accent);text-decoration:underline;}
.sc-person-head {justify-content:flex-start;align-items:flex-start;} .sc-person-head > div:last-child {min-width:0;}
.sc-avatar {width:44px;height:44px;display:grid;place-items:center;flex:0 0 44px;background:var(--color-accent-soft);color:var(--color-accent);border-radius:var(--radius-card);font-size:16px;font-weight:700;}
.sc-avatar.machine {background:var(--color-ink);color:var(--color-surface);font-family:var(--font-mono);}
.sc-avatar.large {width:64px;height:64px;flex-basis:64px;font-size:22px;}
.sc-badges {display:flex;gap:var(--space-2);flex-wrap:wrap;}
.sc-badge {display:inline-flex;align-items:center;gap:var(--space-2);border:1px solid var(--color-border);border-radius:var(--radius-pill);padding:var(--space-1) var(--space-3);font-size:11px;color:var(--color-ink-soft);}
.sc-badge.fav {background:var(--color-accent-soft);border-color:var(--color-accent-soft);color:var(--color-accent);}
.sc-badge mark {color:inherit;background:none;font-family:var(--font-mono);font-weight:700;}
.sc-card-metrics {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-2);border-block:1px solid var(--color-border);padding:var(--space-4) 0;}
.sc-card-metrics strong {font-size:20px;display:block;font-variant-numeric:tabular-nums;} .sc-card-metrics small {font-size:10px;}
.sc-label {display:block;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--color-muted);margin-bottom:var(--space-2);}
.sc-skills {display:grid;gap:var(--space-2);} .sc-skills .sc-line {font-size:12px;} .sc-skills small {flex-shrink:0;}
.sc-card-foot {margin-top:auto;border-top:1px solid var(--color-border);padding-top:var(--space-3);font-size:11px;color:var(--color-muted);}
.sc-card-foot a {float:right;} .sc-section {display:grid;gap:var(--space-5);min-width:0;}
.sc-section-head {align-items:baseline;} .sc-section-head a {font-size:12px;}
.sc-split {display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:var(--space-6);}
.sc-panel {background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-card);padding:var(--space-6);min-width:0;display:grid;gap:var(--space-5);align-content:start;}
.sc-chart {height:120px;display:flex;align-items:end;gap:2px;border-bottom:1px solid var(--color-border);padding-top:var(--space-2);}
.sc-bar {flex:1;min-width:0;background:var(--color-accent);border-radius:2px 2px 0 0;}
.sc-chart-labels {display:flex;justify-content:space-between;font-size:10px;color:var(--color-muted);margin-top:var(--space-2);}
.sc-rank {display:grid;grid-template-columns:24px minmax(0,1fr) auto;gap:var(--space-3);align-items:center;padding:var(--space-3) 0;border-bottom:1px solid var(--color-border);font-size:13px;}
.sc-rank:last-child {border:0;} .sc-rank-number {color:var(--color-muted);font-family:var(--font-mono);font-size:11px;}
.sc-rank small {display:block;margin-top:var(--space-1);font-size:10px;} .sc-rank strong {font-size:15px;}
.sc-empty {padding:var(--space-6);background:var(--color-surface-muted);border-radius:var(--radius-control);color:var(--color-muted);font-size:13px;line-height:1.6;}
.sc-search {display:flex;gap:var(--space-2);align-items:end;} .sc-search label {flex:1;} .sc-search input {width:100%;}
.sc-note {font-size:12px;color:var(--color-muted);line-height:1.6;margin:0;}
.sc-star {background:var(--color-surface);color:var(--color-accent);border:1px solid var(--color-border);border-radius:var(--radius-control);padding:var(--space-2);min-width:40px;min-height:40px;}
.sc-star:hover {background:var(--color-accent-soft);color:var(--color-accent);} .sc-favorite-row {display:flex;gap:var(--space-3);align-items:center;justify-content:space-between;}
.sc-favorite-row form {display:block;flex-shrink:0;}
.sc-config summary {cursor:pointer;color:var(--color-accent);font-size:13px;padding:var(--space-2) 0;}
.sc-config form {display:grid;gap:var(--space-4);margin-top:var(--space-4);} .sc-config input,.sc-config select {width:100%;min-width:0;}
.sc-config label {display:grid;gap:var(--space-2);} .sc-usage {display:grid;gap:var(--space-3);}
.sc-usage-item {border-top:1px solid var(--color-border);padding-top:var(--space-3);font-size:13px;} .sc-usage-item p {margin:var(--space-1) 0;}
.sc-pagination {display:flex;gap:var(--space-4);justify-content:space-between;align-items:center;font-size:12px;}
@media(min-width:1600px){.sc-grid{grid-template-columns:repeat(4,minmax(0,1fr));}}
@media(max-width:1200px){.sc-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:1000px){.sc-split{grid-template-columns:minmax(0,1fr);} .sc-top{flex-direction:column;} .sc-metric{padding:var(--space-4);}}
@media(max-width:650px){.showcase{gap:var(--space-6);} .sc-grid{grid-template-columns:minmax(0,1fr);} .sc-metrics{grid-template-columns:repeat(2,minmax(0,1fr));} .sc-metric:nth-child(2){border-right:0;} .sc-metric:nth-child(n+3){border-top:1px solid var(--color-border);} .sc-metric strong{font-size:26px;} .sc-section-head{align-items:flex-start;flex-direction:column;gap:var(--space-2);} .sc-tabs{gap:var(--space-4);} .sc-card,.sc-panel{padding:var(--space-5);} .sc-search{align-items:stretch;flex-direction:column;}}
</style>"""

CLIENTS = {
    "codex": ("Codex", "CX"),
    "claude": ("Claude", "CL"),
    "claude-code": ("Claude", "CL"),
    "claude_code": ("Claude", "CL"),
    "cursor": ("Cursor", "CU"),
    "opencode": ("OpenCode", "OC"),
    "openclaw": ("OpenClaw", "OW"),
    "hermes": ("Hermes", "HE"),
}
QUALITY = {
    "actual": "Измерено",
    "billing_import": "Импорт биллинга",
    "estimated": "Оценка",
    "agent_local_estimate": "Локальная оценка агента",
}


def e(value):
    return escape(str(value or ""), quote=True)


def number(value):
    return "—" if value is None else f"{int(value):,}".replace(",", " ")


def url(path, **params):
    return path + "?" + urlencode(params)


def client_label(value):
    key = str(value or "").strip().lower()
    return CLIENTS.get(key, (str(value or "Клиент не указан"), "AI"))


def clients_badges(values):
    labels = sorted({client_label(v) for v in values})
    return (
        '<div class="sc-badges">'
        + "".join(
            f'<span class="sc-badge"><mark>{e(mark)}</mark>{e(label)}</span>'
            for label, mark in labels
        )
        + "</div>"
    )


def header(title, description, days, path, tab="showcase", **params):
    period = "".join(
        f'<a href="{e(url(path, days=d, **params))}" aria-current="{str(d == days).lower()}">{d} дней</a>'
        for d in (7, 30, 90)
    )
    tabs = "".join(
        f'<a href="{e(url(p, days=days))}" aria-current="{("page" if key == tab else "false")}">{label}</a>'
        for key, label, p in (
            ("showcase", "Использование AI", "/admin/showcase"),
            ("people", "Люди", "/admin/people"),
            ("agents", "Автономные агенты", "/admin/agents"),
        )
    )
    return f'<div class="sc-top"><div><div class="sc-eyebrow">coMind / AI Native</div><h1>{e(title)}</h1><p>{e(description)}</p></div><nav class="sc-period" aria-label="Период">{period}</nav></div><nav class="sc-tabs" aria-label="Метрики">{tabs}</nav>'


def metrics(items):
    return (
        '<div class="sc-metrics">'
        + "".join(
            f'<div class="sc-metric"><span>{e(label)}</span><strong class="{("sc-accent" if i == 0 else "")}">{e(value)}</strong><small>{e(note)}</small></div>'
            for i, (label, value, note) in enumerate(items)
        )
        + "</div>"
    )


def outcome_metrics(totals):
    finished = totals.get("completed", 0) + totals.get("failed", 0)
    rate = f"{totals['completed'] / finished * 100:.0f}%" if finished else "—"
    return metrics(
        [
            (
                "Запуски навыков",
                number(totals.get("starts")),
                "Начаты в выбранном периоде",
            ),
            (
                "Завершено без ошибки",
                number(totals.get("completed")),
                f"{rate} среди завершённых",
            ),
            ("С ошибкой", number(totals.get("failed")), "Получен сигнал о неуспехе"),
            (
                "Без результата",
                number(totals.get("pending")),
                "Завершение ещё не зарегистрировано",
            ),
        ]
    )


def chart(snapshot):
    today = date.fromisoformat(str(snapshot["today"])[:10])
    days = snapshot["days"]
    values = {row["day"]: row["starts"] for row in snapshot["daily"]}
    dates = [today - timedelta(days=i) for i in range(days, -1, -1)]
    peak = max(values.values(), default=0) or 1
    bars = "".join(
        f'<div class="sc-bar" style="height:{values.get(str(day), 0) / peak * 100:.2f}%" title="{day:%d.%m}: {values.get(str(day), 0)}"></div>'
        for day in dates
    )
    return f'<div><div class="sc-chart" role="img" aria-label="Запуски по дням за {days} дней. Всего {number(snapshot["totals"]["starts"])}.">{bars}</div><div class="sc-chart-labels"><span>{dates[0]:%d.%m}</span><span>По московскому времени</span><span>{today:%d.%m}</span></div></div>'


def skill_ranking(skills):
    if not skills:
        return '<div class="sc-empty">Запусков навыков за этот период пока нет.</div>'
    return (
        "<div>"
        + "".join(
            f'<div class="sc-rank"><span class="sc-rank-number">{i:02}</span><div>{e(s["skill_id"])}<small>{e(s["skill_pack"] or "Пакет не указан")}</small></div><strong>{number(s["starts"])}</strong></div>'
            for i, s in enumerate(skills, 1)
        )
        + "</div>"
    )


def person_card(person, days):
    name = person.get("login") or person.get("email") or "Пользователь шлюза"
    link = url("/admin/people/detail", subject=person["subject"], days=days)
    skills = "".join(
        f'<div class="sc-line"><span>{e(s["skill_id"])}</span><small>{number(s["starts"])} запусков</small></div>'
        for s in person["skills"]
    )
    favs = "".join(
        f'<span class="sc-badge fav">★ {e(s["skill_id"])}</span>'
        for s in person["favorites"][:3]
    )
    if len(person["favorites"]) > 3:
        favs += f"<small>Ещё {len(person['favorites']) - 3}</small>"
    return f'''<article class="sc-card"><div class="sc-person-head"><div class="sc-avatar" aria-hidden="true">{e(name[:2].upper())}</div><div><h3><a href="{e(link)}">{e(name)}</a></h3><small>{e(person.get("email"))}</small></div></div>
        {clients_badges(person["clients"]) if person["clients"] else "<small>Клиенты пока не передавали запуски навыков</small>"}
        <div class="sc-card-metrics"><div><strong>{number(person["starts"])}</strong><small>Запусков</small></div><div><strong>{number(person["completed"])}</strong><small>Без ошибки</small></div><div><strong>{number(person["failed"])}</strong><small>С ошибкой</small></div></div>
        <div><span class="sc-label">Частые навыки</span><div class="sc-skills">{skills or "<small>Пока нет запусков</small>"}</div></div>
        <div><span class="sc-label">Избранное сотрудника</span><div class="sc-badges">{favs or "<small>Ещё не выбрано</small>"}</div></div>
        <div class="sc-card-foot">{e(fmt_time(person.get("last_activity"))) if person.get("last_activity") else "Нет активности за период"}<a href="{e(link)}">Профиль</a></div></article>'''


def agent_card(profile, days):
    bound = bool(profile["actor_subject"])
    link = url("/admin/agents/detail", key=profile["agent_key"], days=days)
    stats = (
        '<div class="sc-card-metrics">'
        + "".join(
            f"<div><strong>{number((profile.get(k) or 0) if bound else None)}</strong><small>{label}</small></div>"
            for k, label in (
                ("starts", "Запусков"),
                ("completed", "Без ошибки"),
                ("failed", "С ошибкой"),
            )
        )
        + "</div>"
    )
    return f'<article class="sc-card"><div class="sc-person-head"><div class="sc-avatar machine" aria-hidden="true">{e(profile["display_name"][:1])}</div><div><span class="sc-label">Автономный агент</span><h3><a href="{e(link)}">{e(profile["display_name"])}</a></h3></div></div><p class="sc-note">{e(profile["description"])}</p>{stats}<small>{"Источник привязан · " + e(client_label(profile["agent"])[0]) if bound else "Телеметрия пока не привязана"}</small><div class="sc-card-foot">{e(fmt_time(profile.get("last_activity"))) if profile.get("last_activity") else "Нет сигнала активности"}<a href="{e(link)}">{"Метрики" if bound else "Подключить источник"}</a></div></article>'


def overview(snapshot, people, profiles):
    days, totals = snapshot["days"], snapshot["totals"]
    body = header(
        "AI в работе команды",
        "Как команда использует AI: инструменты, навыки и результаты запусков в одном месте.",
        days,
        "/admin/showcase",
    )
    body += metrics(
        [
            (
                "Пользователи с активностью",
                number(people["active"]),
                f"Из {number(people['registered'])} учётных записей шлюза",
            ),
            ("Запуски навыков", number(totals["starts"]), "Личные и автономные агенты"),
            (
                "Использовано навыков",
                number(totals["skills"]),
                "Уникальные пары: пакет и навык",
            ),
            (
                "Автономные агенты",
                number(sum(bool(p["actor_subject"]) for p in profiles)),
                f"С привязанным источником из {len(profiles)}",
            ),
        ]
    )
    body += f'<div class="sc-split"><section class="sc-panel"><div class="sc-section-head"><h2>Ритм работы</h2><small>Запуски навыков</small></div>{chart(snapshot)}<p class="sc-note">{number(totals["completed"])} завершено без ошибки · {number(totals["failed"])} с ошибкой · {number(totals["pending"])} без сигнала завершения</p></section><section class="sc-panel"><div class="sc-section-head"><h2>Востребованные навыки</h2><a href="/admin/telemetry/skills">Все метрики</a></div>{skill_ranking(snapshot["skills"][:4])}</section></div>'
    body += (
        f'<section class="sc-section"><div class="sc-section-head"><div><span class="sc-eyebrow">01 / Команда</span><h2>У каждого — свой набор AI</h2></div><a href="{e(url("/admin/people", days=days))}">Все пользователи ({number(people["registered"])})</a></div><div class="sc-grid">'
        + "".join(person_card(p, days) for p in people["people"][:6])
        + "</div></section>"
    )
    if not people["people"]:
        body += '<div class="sc-empty">Здесь появятся учётные записи сотрудников после входа в шлюз.</div>'
    body += (
        f'<section class="sc-section"><div class="sc-section-head"><div><span class="sc-eyebrow">02 / Автономная работа</span><h2>Агенты со своей ролью</h2></div><a href="{e(url("/admin/agents", days=days))}">Каталог агентов</a></div><div class="sc-grid">'
        + "".join(agent_card(p, days) for p in profiles[:3])
        + "</div></section>"
    )
    body += f'<p class="sc-note">Источник: телеметрия GatewayMCP за последние {days} дней. Учтены переданные запуски, а не все установки клиентов. {number(people["unlinked"])} активных источников не связаны с учётными записями пользователей. Завершение навыка подтверждается агентом и не означает приёмку бизнес-результата.</p>'
    return '<div class="showcase">' + body + "</div>"


def people_page(data, days, query, page):
    body = header(
        "Команда с AI",
        "Кто чем пользуется, какие навыки выбирает и как проходят запуски.",
        days,
        "/admin/people",
        "people",
        q=query,
    )
    body += (
        f'<form class="sc-search" method="get"><input type="hidden" name="days" value="{days}"><label>Поиск сотрудника<input name="q" value="{e(query)}" placeholder="Логин или почта" maxlength="120"></label><button type="submit">Найти</button></form><p class="sc-note">Найдено {number(data["matched"])} · Есть запуски у {number(data["active"])} из {number(data["registered"])} пользователей шлюза</p><div class="sc-grid">'
        + "".join(person_card(p, days) for p in data["people"])
        + "</div>"
    )
    if not data["people"]:
        body += '<div class="sc-empty">Никого не нашли. Попробуй другой логин или почту.</div>'
    prev = (
        f'<a href="{e(url("/admin/people", days=days, q=query, page=page - 1))}">Назад</a>'
        if page > 1
        else "<span></span>"
    )
    nxt = (
        f'<a href="{e(url("/admin/people", days=days, q=query, page=page + 1))}">Дальше</a>'
        if page * 12 < data["matched"]
        else ""
    )
    body += f'<nav class="sc-pagination" aria-label="Страницы">{prev}<span>Страница {page}</span>{nxt}</nav><p class="sc-note">Каталог содержит учётные записи шлюза. Частые навыки определяются по запускам; избранное каждый выбирает сам в разделе «Мои навыки».</p>'
    return '<div class="showcase">' + body + "</div>"


def favorite_list(skills, favorites, editable, csrf, days):
    selected = {(s["skill_pack"], s["skill_id"]) for s in favorites}
    all_skills = {(s["skill_pack"], s["skill_id"]): s for s in favorites + skills}
    body = ""
    for (pack, skill), row in sorted(
        all_skills.items(),
        key=lambda s: (s[0] not in selected, -s[1].get("starts", 0), s[0]),
    ):
        chosen = (pack, skill) in selected
        control = '<span class="sc-badge fav">★ Избранное</span>' if chosen else ""
        if editable:
            fields = {
                "csrf": csrf,
                "skill_pack": pack,
                "skill_id": skill,
                "selected": "0" if chosen else "1",
                "days": days,
            }
            control = (
                '<form method="post" action="/my/skills/favorite">'
                + hidden(fields)
                + f'<button class="sc-star" aria-label="{("Убрать из избранного" if chosen else "Добавить в избранное")}: {e(skill)}" aria-pressed="{str(chosen).lower()}">{"★" if chosen else "☆"}</button></form>'
            )
        body += f'<div class="sc-favorite-row"><div>{e(skill)}<br><small>{e(pack or "Пакет не указан")} · {number(row.get("starts", 0))} запусков за период</small></div>{control}</div>'
    return (
        body
        or '<div class="sc-empty">После первого запуска здесь появятся навыки. Их можно добавить в избранное.</div>'
    )


def usage_panel(rows):
    body = '<section class="sc-panel"><h2>Использование моделей</h2><p class="sc-note">Источники приведены отдельно: их записи могут описывать одни и те же запросы. Стоимость в USD, без общего итога.</p><div class="sc-usage">'
    for row in rows:
        cost = "—" if row["cost_usd"] is None else f"${float(row['cost_usd']):,.2f}"
        body += f'<div class="sc-usage-item"><strong>{e(QUALITY.get(row["source_quality"], row["source_quality"]))}</strong><small> · {e(row["source"])} · {e(row["usage_class"])}</small><p>{number(row["tokens"])} токенов · {cost}</p><small>Токены заполнены в {number(row["token_records"])} из {number(row["records"])} записей; стоимость — в {number(row["cost_records"])} из {number(row["records"])}.</small></div>'
    return (
        body
        + (
            ""
            if rows
            else '<div class="sc-empty">Данные об использовании моделей ещё не поступали.</div>'
        )
        + "</div></section>"
    )


def detail(
    snapshot,
    usage,
    name,
    favorites=None,
    editable=False,
    csrf="",
    subject="",
    agent_profile=None,
    personal=False,
):
    days, totals = snapshot["days"], snapshot["totals"]
    path = (
        "/my/skills"
        if personal
        else "/admin/agents/detail"
        if agent_profile
        else "/admin/people/detail"
    )
    params = (
        {}
        if personal
        else {"key": agent_profile["agent_key"]}
        if agent_profile
        else {"subject": subject}
    )
    body = header(
        name,
        "Личная статистика использования AI"
        if not agent_profile
        else agent_profile["description"],
        days,
        path,
        "agents" if agent_profile else "people",
        **params,
    )
    if personal:
        # A personal page must not advertise administrator-only routes.
        body = body[: body.index('<nav class="sc-tabs"')]
    elif not agent_profile:
        body += f'<p class="sc-note"><a href="{e(url("/admin/users/detail", subject=subject))}">Управление доступом сотрудника</a></p>'
    body += outcome_metrics(totals)
    clients = "".join(
        f'<div class="sc-line"><span>{e(client_label(c["agent"])[0])}</span><strong>{number(c["starts"])} <small>запусков</small></strong></div>'
        for c in snapshot["clients"]
    )
    duration = (
        "—" if totals["median_ms"] is None else f"{totals['median_ms'] / 60000:.1f} мин"
    )
    body += f'<div class="sc-split"><section class="sc-panel"><h2>Активность за период</h2>{chart(snapshot)}<p class="sc-note">Медианное время запуска: {duration}. Длительность передана для {number(totals["timed"])} завершённых запусков. Это время выполнения, а не сэкономленное время сотрудника.</p></section><section class="sc-panel"><h2>Используемые клиенты</h2>{clients or "<small>Запусков пока нет</small>"}<p class="sc-note">Последний запуск: {e(fmt_time(totals["last_activity"]))}. Это сигнал телеметрии, а не статус присутствия.</p></section></div>'
    body += (
        '<div class="sc-split"><section class="sc-panel"><h2>Навыки и избранное</h2><p class="sc-note">До 12 самых частых навыков за период и всё личное избранное.</p>'
        + favorite_list(snapshot["skills"], favorites or [], editable, csrf, days)
        + "</section>"
        + usage_panel(usage)
        + "</div>"
    )
    body += f'<p class="sc-note">Источник: телеметрия GatewayMCP за последние {days} дней. Исходы относятся к запускам, начатым в периоде. Завершение сообщается агентом; качество бизнес-результата и экономия денег здесь не оцениваются.</p>'
    return '<div class="showcase">' + body + "</div>"


def hidden(fields):
    return "".join(
        f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k, v in fields.items()
    )


def agent_form(profile, options, csrf):
    profile = profile or {
        "agent_key": "",
        "display_name": "",
        "description": "",
        "actor_subject": "",
        "agent": "",
        "revision": 0,
    }
    pair = [profile["actor_subject"], profile["agent"]]
    pairs = {(o["actor_subject"], o["agent"]) for o in options}
    if pair[0]:
        pairs.add(tuple(pair))
    selects = '<option value="[]">Без источника телеметрии</option>'
    for subject, agent in sorted(pairs):
        selected = " selected" if [subject, agent] == pair else ""
        selects += f'<option value="{e(json.dumps([subject, agent]))}"{selected}>{e(subject)} · {e(agent)}</option>'
    key = (
        hidden({"key": profile["agent_key"]})
        if profile["agent_key"]
        else '<label>Код агента<input name="key" required pattern="[a-z0-9][a-z0-9-]{0,63}" maxlength="64" placeholder="assistant"></label>'
    )
    return (
        '<details class="sc-config"><summary>'
        + (
            "Настроить профиль и источник"
            if profile["agent_key"]
            else "Добавить автономного агента"
        )
        + '</summary><form method="post" action="/admin/agents/save">'
        + hidden({"csrf": csrf, "revision": str(profile["revision"])})
        + key
        + f'<label>Имя<input name="name" value="{e(profile["display_name"])}" required maxlength="80"></label><label>Задача агента<input name="description" value="{e(profile["description"])}" maxlength="300"></label><label>Источник<select name="binding">{selects}</select></label><p class="sc-note">Выбери отдельную учётную запись и имя агента из его телеметрии. Все их запуски за период будут отнесены к этому агенту и исключены из личной статистики. Общая учётная запись с тем же именем клиента смешает работу людей и агента. В списке до 100 последних источников.</p><button type="submit">Сохранить профиль</button></form></details>'
    )


def agents_page(profiles, options, csrf, days):
    body = header(
        "Автономные агенты",
        "Их роли, измеримые запуски и источники данных. Каждый агент имеет отдельный профиль.",
        days,
        "/admin/agents",
        "agents",
    )
    body += (
        '<div class="sc-grid">'
        + "".join(agent_card(p, days) for p in profiles)
        + "</div>"
    )
    body += (
        '<section class="sc-panel">'
        + agent_form(None, options, csrf)
        + '</section><p class="sc-note">Метрики относятся к навыкам, переданным в GatewayMCP. Название клиента Hermes само по себе не означает автономную работу. Для сообщений Фёклы и других действий вне навыков потребуется отдельная телеметрия результатов.</p>'
    )
    return '<div class="showcase">' + body + "</div>"
