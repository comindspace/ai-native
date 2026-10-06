from __future__ import annotations

import secrets
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs, urlencode

from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from gateway_mcp.config import public_url
from gateway_mcp.routes.admin_ui import admin_shell
from gateway_mcp.services import factory_connections as service
from gateway_mcp.services import storage_factory
from gateway_mcp.services.factory_admin import public_project, upsert_project
from gateway_mcp.services.observability import audit_event
from gateway_mcp.web import login_redirect, web_actor

PATH = "/admin/factory/connections"
COOKIE = "gateway_factory_csrf"
CSS = """<style>
.factory-band { border-top:1px solid var(--color-border); padding:24px 0; min-width:0; }
.factory-head { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
.factory-table { width:100%; border-collapse:collapse; }
.factory-table td,.factory-table th { text-align:left; padding:14px 10px; border-bottom:1px solid var(--color-border); overflow-wrap:anywhere; }
.factory-table th { font-size:12px; color:var(--color-muted); font-weight:500; }
.factory-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; }
.factory-grid label { display:grid; gap:8px; min-width:0; }
.factory-wide { grid-column:1/-1; }
.factory-grid textarea { min-height:96px; resize:vertical; font:inherit; color:var(--color-ink); background:var(--color-surface); padding:12px; border:1px solid var(--color-border-strong); border-radius:var(--radius-control); }
.factory-grid textarea:focus-visible { outline:2px solid var(--color-focus); outline-offset:1px; }
.factory-band h2 { margin-bottom:20px; }
.factory-band > form + form { margin-top:12px; }
.factory-project form { display:grid; align-content:start; gap:12px; }
.factory-muted { color:var(--color-muted); font-size:13px; }
.factory-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.factory-actions form { margin:0; }
.factory-project { display:grid; grid-template-columns:minmax(0,1fr) minmax(220px,1fr); gap:16px; border-bottom:1px solid var(--color-border); padding:20px 0; }
.factory-project select { width:100%; }
.factory-state { font-size:13px; }
@media(max-width:700px) { .factory-grid,.factory-project { grid-template-columns:minmax(0,1fr); } .factory-table thead { display:none; } .factory-table tr { display:grid; padding:12px 0; border-bottom:1px solid var(--color-border); } .factory-table td { padding:5px 0; border:0; } }
</style>"""
STATES = {
    "active": "Настроено",
    "missing": "Нет токена",
    "expired": "Срок истёк",
    "disabled": "Отключено",
    "invalid": "Ошибка конфигурации",
}


def hidden(name, value):
    return f'<input type="hidden" name="{escape(name)}" value="{escape(str(value))}">'


def action_form(action, label, csrf, reference, version):
    return (
        f'<form method="post" action="{PATH}">{hidden("csrf", csrf)}'
        f"{hidden('action', action)}{hidden('reference', reference)}{hidden('version', version)}"
        f'<button class="secondary" type="submit">{escape(label)}</button></form>'
    )


def render_body(cards, projects, csrf, selected, message="", ok=False):
    banner = (
        f'<div class="banner {"ok" if ok else "error"}" role="status">{escape(message)}</div>'
        if message
        else ""
    )
    rows = []
    for card in cards:
        reference = card["connection_id"]
        query = urlencode({"edit": reference})
        check = card.get("last_check_ok")
        check_text = (
            "Не проверялось"
            if check is None
            else "Авторизация подтверждена"
            if check
            else "Ошибка проверки"
        )
        rows.append(
            f'<tr><td><strong>{escape(reference)}</strong><br><span class="factory-muted">{escape(card.get("api_url", ""))}</span></td>'
            f'<td>{STATES[card["state"]]}<br><span class="factory-muted">{check_text}</span></td>'
            f"<td>{escape(datetime.fromisoformat(card['expires_at']).astimezone(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')) if card.get('expires_at') else 'Без срока'}</td>"
            f'<td><div class="factory-actions"><a class="button secondary" href="{PATH}?{query}#connection">Настроить</a>'
            f"{action_form('check', 'Проверить', csrf, reference, card['version'])}</div></td></tr>"
        )
    current = next((c for c in cards if c["connection_id"] == selected), {})
    reference = current.get("connection_id", "")
    expires = current.get("expires_at")
    expiry_value = (
        datetime.fromisoformat(expires)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M")
        if expires
        else ""
    )
    field = lambda label, name, value="", extra="": (
        f'<label>{label}<input name="{name}" value="{escape(str(value))}" {extra}></label>'
    )
    form = f'''<section class="factory-band" id="connection"><h2>{"Настройка подключения" if current else "Новое подключение"}</h2>
    <form method="post" action="{PATH}" autocomplete="off">
    {hidden("csrf", csrf)}{hidden("action", "save")}{hidden("version", current.get("version", 0))}
    <div class="factory-grid">
    {field("Идентификатор", "reference", reference, 'required placeholder="gitlab:company"' + (" readonly" if current else ""))}
    {field("Адрес API", "api_url", current.get("api_url", ""), 'required type="url" placeholder="https://gitlab.example.com/api/v4"')}
    {field("Служебный логин", "username", current.get("username", "oauth2"), 'required autocomplete="off"')}
    <label>Токен<input type="password" name="token" value="" maxlength="4096" autocomplete="new-password" placeholder="{"Оставь пустым, чтобы сохранить" if current.get("token_configured") else "Служебный токен GitLab"}" {"" if current.get("token_configured") else "required"}></label>
    <label class="factory-wide">Разрешённые репозитории<textarea name="repositories" required placeholder="group/project">{escape(chr(10).join(current.get("repositories") or []))}</textarea></label>
    {field("Срок действия (UTC)", "expires_at", expiry_value, 'type="datetime-local"')}
    <div class="factory-wide factory-actions"><button type="submit">Сохранить подключение</button><a href="{PATH}">Отмена</a></div>
    </div></form>
    {action_form("disable", "Отключить подключение", csrf, reference, current["version"]) if current and current.get("state") != "disabled" else ""}
    </section>'''
    project_rows = []
    for row in projects:
        config = row["config"]
        status = public_project(row)
        options = ['<option value="">Выбери подключение</option>']
        for card in cards:
            value = card["connection_id"]
            options.append(
                f'<option value="{escape(value)}" {"selected" if value == config.get("gitlab_connection_id") else ""} {"disabled" if card["state"] != "active" else ""}>{escape(value)}</option>'
            )
        gaps = status["readiness_gaps"]
        readiness = (
            "Требует проверки: " + ", ".join(gaps)
            if gaps
            else "Репозиторий проверен из Gateway"
        )
        project_rows.append(
            f'<div class="factory-project"><div><strong>{escape(config.get("name") or row["project_id"])}</strong><p class="factory-muted">{escape(config["gitlab_web_url"])}</p><p class="factory-state">{escape(readiness)}</p></div>'
            f'<form method="post" action="{PATH}">{hidden("csrf", csrf)}{hidden("action", "bind")}{hidden("project_id", row["project_id"])}{hidden("version", row["revision"])}{hidden("idempotency_key", secrets.token_hex(20))}'
            f'<label>Подключение<select name="reference" required>{"".join(options)}</select></label><button type="submit">Привязать и проверить</button></form></div>'
        )
    return f'''<div class="page-head"><div><h1>GitLab для фабрики</h1></div><a href="{PATH}#connection" class="button">Добавить подключение</a></div>{banner}
    <section class="factory-band"><table class="factory-table"><thead><tr><th>Подключение</th><th>Состояние</th><th>Действует до</th><th>Действия</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="4">Служебных подключений пока нет.</td></tr>'}</tbody></table></section>
    {form}<section class="factory-band"><h2>Проекты фабрики</h2>{"".join(project_rows) or '<p class="factory-muted">Зарегистрированных проектов пока нет.</p>'}</section>
    <script>document.querySelectorAll('form').forEach(form => form.addEventListener('submit', () => {{ form.setAttribute('aria-busy', 'true'); form.querySelectorAll('button').forEach(button => {{ button.disabled = true; button.textContent = 'Выполняется…'; }}); }}));</script>'''


def register_admin_factory_connection_routes(mcp):
    @mcp.custom_route(PATH, methods=["GET", "POST"], include_in_schema=False)
    async def page(request):
        actor = web_actor(request)
        if actor is None:
            return login_redirect(PATH)
        try:
            service.require_connection_admin(actor)
        except PermissionError:
            return PlainTextResponse(
                "Factory administration is required.", status_code=403
            )
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 32768:
                    return PlainTextResponse("Form too large.", status_code=413)
            parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            form = {k: v[-1] for k, v in parsed.items()}
            cookie = request.cookies.get(COOKIE, "")
            if not cookie or not secrets.compare_digest(cookie, form.get("csrf", "")):
                return PlainTextResponse("CSRF token mismatch.", status_code=403)
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != public_url().rstrip("/"):
                return PlainTextResponse("Origin mismatch.", status_code=403)
            action, reference = form.get("action", ""), form.get("reference", "")
            try:
                version = int(form.get("version", "-1"))
                if not service.REFERENCE.fullmatch(reference):
                    raise ValueError("Некорректный идентификатор подключения.")
                if action == "save":
                    expiry = form.get("expires_at")
                    expires = (
                        datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
                        if expiry
                        else None
                    )
                    service.save_connection(
                        actor=actor,
                        reference=reference,
                        api_url=form.get("api_url", ""),
                        username=form.get("username", ""),
                        token=form.get("token", ""),
                        repositories=form.get("repositories", ""),
                        expires_at=expires,
                        expected_version=version,
                    )
                    result = {
                        "ok": True,
                        "message": "Подключение сохранено. Проверь авторизацию и привязку проекта.",
                    }
                elif action == "disable":
                    service.disable_connection(
                        actor=actor, reference=reference, expected_version=version
                    )
                    result = {"ok": True, "message": "Подключение отключено."}
                elif action == "check":
                    result = await service.check_connection(reference)
                    service._audit(actor, reference, "check")
                elif action == "bind":
                    row = storage_factory.get_project(form.get("project_id", ""))
                    if not row or row["revision"] != version:
                        raise ValueError("Проект изменился. Обнови страницу.")
                    outcome = await upsert_project(
                        actor=actor,
                        config={**row["config"], "gitlab_connection_id": reference},
                        idempotency_key=form.get("idempotency_key", ""),
                        expected_revision=version,
                    )
                    ready = outcome["validation"]["ready"]
                    result = {
                        "ok": ready,
                        "message": "Проект привязан. Проверка репозитория пройдена."
                        if ready
                        else "Проект сохранён, но проверка не пройдена: "
                        + ", ".join(outcome["validation"]["readiness_gaps"]),
                    }
                else:
                    return PlainTextResponse("Unknown action.", status_code=404)
            except Exception as exc:  # noqa: BLE001 - never return storage/upstream secrets
                audit_event(
                    event="factory_connection_change",
                    actor=actor,
                    system="factory",
                    decision="deny" if isinstance(exc, PermissionError) else "allow",
                    status="error",
                    arguments={
                        "action": action
                        if action in {"save", "disable", "check", "bind"}
                        else "unknown",
                        "error_class": type(exc).__name__,
                    },
                )
                result = {
                    "ok": False,
                    "message": "Не удалось выполнить действие. Проверь права, параметры и актуальность страницы.",
                }
            query = urlencode(
                {
                    "ok": "1" if result["ok"] else "0",
                    "message": result["message"],
                    "edit": reference,
                }
            )
            return RedirectResponse(
                PATH + "?" + query,
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )
        csrf = request.cookies.get(COOKIE) or secrets.token_urlsafe(32)
        cards = service.connection_cards(actor)
        selected = request.query_params.get("edit", "")
        body = render_body(
            cards,
            storage_factory.list_projects(),
            csrf,
            selected,
            request.query_params.get("message", "")[:500],
            request.query_params.get("ok") == "1",
        )
        response = HTMLResponse(
            admin_shell(
                title="GitLab для фабрики",
                active="factory-connections",
                actor=actor,
                body=body,
                shell_width="1180px",
                extra_head=CSS,
            ),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin"},
        )
        response.set_cookie(
            COOKIE,
            csrf,
            secure=public_url().startswith("https://"),
            httponly=True,
            samesite="strict",
            path=PATH,
        )
        return response
