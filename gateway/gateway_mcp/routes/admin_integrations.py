from __future__ import annotations

import secrets
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs, urlencode

from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from gateway_mcp.config import public_url
from gateway_mcp.routes.admin_ui import admin_shell, fmt_time
from gateway_mcp.services.managed_integrations import (
    INTEGRATIONS,
    check_integration,
    delete_integration,
    disable_integration,
    integration_statuses,
    safe_field_value,
    save_integration,
)
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import has_scope
from gateway_mcp.web import login_redirect, web_actor

CSRF_COOKIE = "gateway_admin_csrf"

_INTEGRATIONS_CSS = """
<style>
  .integration-summary {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    border: 1px solid var(--color-border);
    border-radius: var(--radius-panel);
    background: var(--color-surface);
  }
  .integration-summary-item {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    padding: var(--space-4) var(--space-5);
    border-right: 1px solid var(--color-border);
  }
  .integration-summary-item:last-child { border-right: 0; }
  .summary-value { font-size: 24px; font-weight: 650; line-height: 1; }
  .summary-value.ok { color: var(--color-success); }
  .summary-value.warning { color: var(--color-warning); }
  .summary-label { color: var(--color-muted); font-size: 12px; }
  .integration-list {
    overflow: hidden;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-panel);
    background: var(--color-surface);
  }
  .integration-item { border-bottom: 1px solid var(--color-border); }
  .integration-item:last-child { border-bottom: 0; }
  .integration-row {
    display: grid;
    grid-template-columns: minmax(240px, 1fr) 132px 150px auto 18px;
    gap: var(--space-4);
    align-items: center;
    min-height: 88px;
    padding: var(--space-4) var(--space-5);
    cursor: pointer;
    list-style: none;
  }
  .integration-row::-webkit-details-marker { display: none; }
  .integration-row:hover { background: var(--color-surface-muted); }
  .integration-row:focus-visible { outline: 2px solid var(--color-focus); outline-offset: -2px; }
  .integration-primary, .integration-meta { display: grid; min-width: 0; }
  .integration-primary { gap: var(--space-1); }
  .integration-name { font-size: 15px; font-weight: 650; }
  .integration-description { color: var(--color-muted); font-size: 13px; line-height: 1.4; }
  .integration-meta { gap: 3px; color: var(--color-ink-soft); font-size: 12px; overflow-wrap: anywhere; }
  .meta-label { color: var(--color-muted); font-size: 11px; }
  .disclosure {
    width: 8px;
    height: 8px;
    border-right: 1.5px solid var(--color-muted);
    border-bottom: 1.5px solid var(--color-muted);
    transform: rotate(45deg);
    transition: transform var(--dur-micro) var(--ease-out);
  }
  .integration-item[open] .disclosure { transform: rotate(225deg); }
  .integration-detail { padding: var(--space-5); border-top: 1px solid var(--color-border); background: var(--color-surface-muted); }
  .integration-context { display: flex; gap: var(--space-4); align-items: baseline; margin-bottom: var(--space-4); color: var(--color-muted); font-size: 12px; }
  .integration-check-note { margin: 0; color: var(--color-ink-soft); }
  .integration-form { display: grid; gap: var(--space-4); }
  .integration-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
  .integration-field { display: grid; align-content: start; gap: var(--space-2); }
  .integration-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-4); }
  .check { grid-template-columns: 18px minmax(0, 1fr); align-items: center; color: var(--color-muted); font-weight: 400; }
  .check input { width: auto; min-height: auto; }
  @media (max-width: 900px) {
    .integration-row { grid-template-columns: minmax(220px, 1fr) 132px auto 18px; }
    .integration-checked { display: none; }
  }
  @media (max-width: 700px) {
    .integration-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .integration-summary-item:nth-child(2) { border-right: 0; }
    .integration-summary-item:nth-child(-n+2) { border-bottom: 1px solid var(--color-border); }
    .integration-row { grid-template-columns: minmax(0, 1fr) auto 18px; min-height: 78px; padding: var(--space-4); }
    .integration-meta { display: none; }
    .integration-detail { padding: var(--space-4); }
    .integration-fields { grid-template-columns: minmax(0, 1fr); }
    .integration-actions { display: grid; grid-template-columns: minmax(0, 1fr); }
    .integration-actions button { width: 100%; }
  }
  @media (max-width: 480px) {
    .integration-description { display: none; }
    .integration-row { min-height: 64px; }
  }
</style>
"""


def register_admin_integration_routes(mcp) -> None:
    @mcp.custom_route("/admin/integrations", methods=["GET"], include_in_schema=False)
    async def integrations_page(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin/integrations")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)

        csrf = secrets.token_urlsafe(32)
        statuses = integration_statuses()
        active_count = sum(
            1 for status in statuses if str(status.get("state")) == "active"
        )
        issue_count = sum(
            1
            for status in statuses
            if status.get("state") == "expired" or status.get("last_check_ok") is False
        )
        checked_count = sum(
            1 for status in statuses if status.get("last_check_ok") is True
        )
        body = f"""
        <div class="page-head"><div><h1>Интеграции</h1>
        <p class="lead">Подключения GatewayMCP к корпоративным системам. Секреты хранятся зашифрованно и не передаются агентам.</p></div><a class="button secondary" href="/admin/factory/connections">GitLab для фабрики</a></div>
        {_banner(request)}
        <section class="integration-summary" aria-label="Состояние интеграций">
          {_summary_item("Всего систем", len(statuses))}
          {_summary_item("Настроено", active_count, "ok")}
          {_summary_item("Требуют внимания", issue_count, "warning" if issue_count else "ok")}
          {_summary_item("Работают после проверки", checked_count)}
        </section>
        <section class="integration-list" aria-label="Корпоративные интеграции">
          {"".join(_integration_card(status, csrf) for status in statuses)}
        </section>
        """
        response = HTMLResponse(
            admin_shell(
                title="Интеграции",
                active="integrations",
                actor=actor,
                body=body,
                shell_width="1180px",
                extra_head=_INTEGRATIONS_CSS,
            )
        )
        set_cookie = getattr(response, "set_cookie", None)
        if callable(set_cookie):
            set_cookie(
                CSRF_COOKIE,
                csrf,
                secure=public_url().startswith("https://"),
                httponly=True,
                samesite="strict",
                path="/admin/integrations",
            )
        return response

    @mcp.custom_route(
        "/admin/integrations/{system}/{action}",
        methods=["POST"],
        include_in_schema=False,
    )
    async def integration_action(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin/integrations")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)
        system = str(request.path_params.get("system") or "").strip().casefold()
        action = str(request.path_params.get("action") or "").strip().casefold()
        if system not in INTEGRATIONS:
            return PlainTextResponse("Unknown integration.", status_code=404)
        form = _form(await request.body())
        if not _csrf_ok(request, form):
            return PlainTextResponse("CSRF token mismatch.", status_code=403)
        try:
            if action == "save":
                definition = INTEGRATIONS[system]
                values = {
                    field.key: form.get(field.key, "") for field in definition.fields
                }
                clear_fields = {
                    field.key
                    for field in definition.fields
                    if form.get(f"clear__{field.key}") == "1"
                }
                save_integration(
                    system,
                    values=values,
                    clear_fields=clear_fields,
                    updated_by=actor.subject,
                    expires_at=_parse_expiry(form.get("expires_at", "")),
                )
                message = "Подключение сохранено."
            elif action == "check":
                result = await check_integration(system)
                message = str(result["message"])
                if not result["ok"]:
                    raise RuntimeError(message)
            elif action == "disable":
                disable_integration(system, updated_by=actor.subject)
                message = "Подключение отключено."
            elif action == "delete":
                delete_integration(system)
                message = "Управляемая конфигурация удалена."
            else:
                return PlainTextResponse("Unknown action.", status_code=404)
        except Exception as exc:  # noqa: BLE001 - HTTP boundary must convert failures into an audited result
            audit_event(
                event="managed_integration_change",
                actor=actor,
                system=system,
                decision="allow",
                status="error",
                arguments={"action": action, "error_class": exc.__class__.__name__},
            )
            return _redirect(False, str(exc))
        audit_event(
            event="managed_integration_change",
            actor=actor,
            system=system,
            decision="allow",
            status="ok",
            arguments={"action": action},
        )
        return _redirect(True, message)


def _integration_card(status: dict[str, object], csrf: str) -> str:
    system = str(status["system"])
    definition = INTEGRATIONS[system]
    state = str(status.get("state") or "missing")
    source = str(status.get("source") or "missing")
    source_label = {
        "admin": "Админка",
        "environment": "Переменные окружения",
        "missing": "Не указан",
    }.get(source, source)
    configured_fields = {str(item) for item in status.get("configured_fields") or []}
    fields = []
    for field in definition.fields:
        configured = field.key in configured_fields or bool(
            safe_field_value(system, field)
        )
        value = "" if field.secret else safe_field_value(system, field)
        placeholder = (
            "оставьте пустым, чтобы сохранить"
            if field.secret and configured
            else field.placeholder
        )
        clear = (
            f'<label class="check"><input type="checkbox" name="clear__{escape(field.key)}" value="1"> удалить сохранённое значение</label>'
            if configured
            else ""
        )
        fields.append(
            '<div class="integration-field">'
            f'<label>{escape(field.label)}<input type="{"password" if field.secret else "text"}" '
            f'name="{escape(field.key)}" value="{escape(value)}" placeholder="{escape(placeholder)}" autocomplete="off"></label>{clear}'
            "</div>"
        )
    check_failed = status.get("last_check_ok") is False
    status_class = (
        "warning"
        if state == "expired" or check_failed
        else "ok"
        if state == "active"
        else "neutral"
    )
    status_label = (
        "срок истёк"
        if state == "expired"
        else "ошибка проверки"
        if check_failed
        else {
            "active": "работает"
            if status.get("last_check_ok") is True
            else "настроено",
            "disabled": "отключено",
        }.get(state, "не настроено")
    )
    checked = str(status.get("last_check_message") or "")
    checked_at = (
        escape(fmt_time(status.get("last_checked_at")))
        if status.get("last_checked_at")
        else "Нет"
    )
    checked_message = (
        f'<p class="integration-check-note">{escape(checked)}</p>' if checked else ""
    )
    return f"""
    <details class="integration-item" id="integration-{escape(system)}">
      <summary class="integration-row">
        <span class="integration-primary">
          <span class="integration-name">{escape(definition.label)}</span>
          <span class="integration-description">{escape(definition.description)}</span>
        </span>
        <span class="integration-meta"><span class="meta-label">Источник</span><span>{escape(source_label)}</span></span>
        <span class="integration-meta integration-checked"><span class="meta-label">Проверено</span><span>{checked_at}</span></span>
        <span class="status {status_class}">{status_label}</span>
        <span class="disclosure" aria-hidden="true"></span>
      </summary>
      <div class="integration-detail">
        <div class="integration-context">
          <span>Версия {int(status.get("version") or 0)}</span>
          {checked_message}
        </div>
        <form class="integration-form" method="post" action="/admin/integrations/{escape(system)}/save">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <div class="integration-fields">{"".join(fields)}</div>
          <label>Действует до<input type="datetime-local" name="expires_at" value="{escape(_expiry_local(status.get("expires_at")))}"></label>
          <div><button type="submit">Сохранить настройки</button></div>
        </form>
        <div class="integration-actions">
          {_action_form(system, "check", "Проверить", csrf, secondary=True)}
          {_action_form(system, "disable", "Отключить", csrf, secondary=True)}
          {_action_form(system, "delete", "Удалить", csrf, danger=True)}
        </div>
      </div>
    </details>
    """


def _summary_item(label: str, value: int, state: str = "") -> str:
    state_class = f" {state}" if state else ""
    return (
        '<div class="integration-summary-item">'
        f'<span class="summary-value{state_class}">{value}</span>'
        f'<span class="summary-label">{escape(label)}</span>'
        "</div>"
    )


def _action_form(
    system: str,
    action: str,
    label: str,
    csrf: str,
    *,
    secondary: bool = False,
    danger: bool = False,
) -> str:
    css = " danger" if danger else " secondary" if secondary else ""
    confirm = (
        " onsubmit=\"return confirm('Удалить сохранённую конфигурацию?')\""
        if danger
        else ""
    )
    return (
        f'<form method="post" action="/admin/integrations/{escape(system)}/{action}"{confirm}>'
        f'<input type="hidden" name="csrf" value="{escape(csrf)}">'
        f'<button class="button{css}" type="submit">{escape(label)}</button></form>'
    )


def _form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="ignore"), keep_blank_values=True)
    return {key: str(values[-1]) for key, values in parsed.items() if values}


def _csrf_ok(request: Request, form: dict[str, str]) -> bool:
    cookie = str(request.cookies.get(CSRF_COOKIE) or "")
    supplied = str(form.get("csrf") or "")
    return bool(cookie and supplied and secrets.compare_digest(cookie, supplied))


def _parse_expiry(raw: str) -> datetime | None:
    if not raw.strip():
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expiry_local(value: object) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return ""
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _redirect(ok: bool, message: str) -> RedirectResponse:
    query = urlencode(
        {"ok": "1" if ok else "0", "message": " ".join(message.split())[:300]}
    )
    return RedirectResponse(f"/admin/integrations?{query}", status_code=303)


def _banner(request: Request) -> str:
    message = str(request.query_params.get("message") or "").strip()
    if not message:
        return ""
    css = "ok" if request.query_params.get("ok") == "1" else "error"
    return f'<div class="banner {css}">{escape(message)}</div>'
