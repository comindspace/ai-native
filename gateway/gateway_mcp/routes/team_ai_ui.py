"""People-first AI home using observed Gateway data and explicit preferences."""

from gateway_mcp.routes import showcase_ui as ui

CSS = """<style>
/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5
 * genre: modern-minimal · theme: coMind workbench · macrostructure: directory with agent rail
 */
.team-ai {--radius-card:16px;--radius-pill:99px;display:grid;gap:var(--space-8);}
.team-ai h1 {font-family:var(--font-display);font-size:clamp(34px,4vw,54px);letter-spacing:-.045em;line-height:1.08;margin:0 0 var(--space-4);overflow-wrap:anywhere;}
.team-ai h2 {font-size:22px;letter-spacing:-.025em;margin:0;}
.team-ai h3 {font-size:18px;letter-spacing:-.015em;margin:0;}
.ta-heading {display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-6);}
.ta-heading p {color:var(--color-muted);max-width:620px;line-height:1.6;margin:0;}
.ta-signals {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:var(--space-5) 0;border-block:1px solid var(--color-border);gap:var(--space-6);}
.ta-signal {min-width:0;display:grid;gap:var(--space-2);}
.ta-signal strong {font-family:var(--font-display);font-size:30px;line-height:1;letter-spacing:-.035em;}
.ta-signal span {font-size:13px;color:var(--color-ink-soft);}
.ta-signal small {font-size:11px;color:var(--color-muted);}
.ta-layout {display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,.46fr);gap:var(--space-6);align-items:start;}
.ta-section {min-width:0;display:grid;gap:var(--space-5);}
.ta-section-head {display:flex;gap:var(--space-4);justify-content:space-between;align-items:center;}
.ta-section-head p {color:var(--color-muted);font-size:13px;line-height:1.5;margin:var(--space-2) 0 0;}
.ta-section-head a,.ta-more {font-size:13px;white-space:nowrap;text-underline-offset:3px;}
.ta-people-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-4);}
.ta-agent-list {display:grid;gap:var(--space-4);}
.ta-agent-list .sc-card {background:var(--color-surface-muted);}
.ta-agent-list .sc-avatar.machine {border:1px solid var(--color-accent);}
.ta-library {display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--space-6);}
.ta-library .sc-panel {display:grid;gap:var(--space-5);align-content:start;}
.ta-library .sc-section-head {align-items:center;}
.ta-library .sc-section-head a {font-size:13px;white-space:nowrap;}
.ta-more {justify-self:start;}
.ta-source {margin:0;padding-top:var(--space-4);border-top:1px solid var(--color-border);}
.team-ai :is(a,p,span,strong,h2,h3,small) {min-width:0;overflow-wrap:anywhere;}
@media(max-width:1100px){.ta-layout {grid-template-columns:minmax(0,1fr);}.ta-agent-list {grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:800px){.ta-heading {flex-direction:column;}.ta-library {grid-template-columns:minmax(0,1fr);}}
@media(max-width:680px){.team-ai {gap:var(--space-6);}.ta-signals {grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-6) var(--space-4);}.ta-people-grid,.ta-agent-list {grid-template-columns:minmax(0,1fr);}.ta-section-head,.ta-library .sc-section-head {flex-direction:column;align-items:flex-start;}.ta-heading h1 {font-size:38px;}}
</style>"""


def unavailable(message):
    return f'<div class="sc-empty" role="status">{ui.e(message)} Обнови страницу чуть позже.</div>'


def render(snapshot, people, profiles, days):
    """Render each source independently so an outage does not hide the directory."""
    totals = snapshot["totals"] if snapshot is not None else {}
    period = "".join(
        f'<a href="{ui.e(ui.url("/admin", days=d))}" aria-current="{str(d == days).lower()}">{d} дней</a>'
        for d in (7, 30, 90)
    )
    body = f"""<div class="ta-heading"><div><h1>Команда и AI</h1>
        <p>Люди, их инструменты и навыки. Автономные агенты, которые работают рядом с командой.</p></div>
        <nav class="sc-period" aria-label="Период">{period}</nav></div>"""
    signals = [
        (
            "Пользователи с активностью",
            people["active"] if people is not None else None,
            f"Из {ui.number(people['registered'])} учётных записей шлюза"
            if people is not None
            else "Источник временно недоступен",
        ),
        ("Запуски навыков", totals.get("starts"), f"За последние {days} дней"),
        ("Использовано навыков", totals.get("skills"), "По переданным запускам"),
        (
            "Автономные агенты",
            len(profiles) if profiles is not None else None,
            f"Источник привязан у {sum(bool(p['actor_subject']) for p in profiles)}"
            if profiles is not None
            else "Источник временно недоступен",
        ),
    ]
    body += (
        '<div class="ta-signals">'
        + "".join(
            f'<div class="ta-signal"><strong>{ui.number(value)}</strong><span>{ui.e(label)}</span><small>{ui.e(note)}</small></div>'
            for label, value, note in signals
        )
        + "</div>"
    )
    body += f'''<div class="ta-layout"><section class="ta-section" aria-labelledby="team-title">
        <div class="ta-section-head"><div><h2 id="team-title">Люди и их AI</h2><p>Кто чем пользуется и какие навыки выбирает.</p></div>
        <a href="{ui.e(ui.url("/admin/people", days=days))}">Вся команда</a></div>'''
    if people is None:
        body += unavailable("Не удалось загрузить пользователей.")
    elif people["people"]:
        body += (
            '<div class="ta-people-grid">'
            + "".join(ui.person_card(person, days) for person in people["people"][:4])
            + "</div>"
        )
    else:
        body += '<div class="sc-empty">После входа сотрудников в шлюз здесь появятся их профили. Клиенты и навыки добавятся с первыми переданными запусками.</div>'
    body += f'''<a class="ta-more" href="{ui.e(ui.url("/my/skills", days=days))}">Мои любимые навыки</a></section>
        <section class="ta-section" aria-labelledby="agents-title"><div class="ta-section-head"><div><h2 id="agents-title">Автономные агенты</h2><p>Своя роль, свой источник активности.</p></div></div>'''
    if profiles is None:
        body += unavailable("Не удалось загрузить агентов.")
    elif profiles:
        body += (
            '<div class="ta-agent-list">'
            + "".join(ui.agent_card(profile, days) for profile in profiles[:2])
            + "</div>"
        )
    else:
        body += '<div class="sc-empty">В реестре пока нет автономных агентов.</div>'
    body += f'<a class="ta-more" href="{ui.e(ui.url("/admin/agents", days=days))}">Все агенты</a></section></div>'
    body += '<div class="ta-library"><section class="sc-panel"><div class="sc-section-head"><h2>Навыки в работе</h2><a href="/admin/telemetry/skills">Все навыки</a></div>'
    if snapshot is None:
        body += unavailable("Не удалось загрузить запуски навыков.")
    else:
        body += ui.skill_ranking(snapshot["skills"][:5])
    body += '<p class="sc-note">Частые навыки определяются по запускам. Любимые каждый выбирает в своём профиле.</p></section>'
    body += '<section class="sc-panel"><div class="sc-section-head"><h2>Активность команды</h2><a href="/admin/showcase">Подробнее</a></div>'
    if snapshot is None:
        body += unavailable("Не удалось загрузить активность.")
    else:
        body += ui.chart({**snapshot, "days": days})
        body += f'<p class="sc-note">{ui.number(totals.get("completed"))} завершено без ошибки · {ui.number(totals.get("failed"))} с ошибкой · {ui.number(totals.get("pending"))} без сигнала завершения.</p>'
    body += "</section></div>"
    body += f'<p class="sc-note ta-source">Источник: GatewayMCP за последние {days} дней. Видны переданные запуски и учётные записи шлюза. Последняя активность не подтверждает, что агент сейчас работает. Завершение навыка не означает приёмку результата.</p>'
    return '<div class="team-ai">' + body + "</div>"
