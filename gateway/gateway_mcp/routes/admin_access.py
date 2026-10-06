from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from asyncio import gather
from asyncio import to_thread as run_in_threadpool
from datetime import datetime, timezone
from functools import wraps
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlencode
from uuid import UUID

from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from gateway_mcp.config import public_url
from gateway_mcp.routes import showcase_ui, team_ai_ui
from gateway_mcp.routes.admin_ui import admin_shell, empty_row, fmt_time
from gateway_mcp.services import storage_showcase
from gateway_mcp.services.access_packages import access_package, access_package_catalog
from gateway_mcp.services.access_requests import admin_decide_access_request
from gateway_mcp.services.admin_roles import admin_role_state, require_current_admin
from gateway_mcp.services.auth import jwt_secret
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import has_scope
from gateway_mcp.services.storage import (
    get_access_request,
    list_access_requests,
)
from gateway_mcp.services.storage_admin_console import (
    admin_user_get,
    admin_user_grants,
    admin_users_page,
)
from gateway_mcp.web import login_redirect, web_actor

PAGE_SIZE = 25
CSRF_COOKIE = "gateway_access_csrf"
STATUS = {
    "pending": "Ожидает решения",
    "processing": "Обрабатывается",
    "approved": "Согласована",
    "rejected": "Отклонена",
    "cancelled": "Отменена",
}
CSS = """<style>
/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4. Existing Comind tokens. */
.access-band { border-top: 1px solid var(--color-border); padding-top: var(--space-6); min-width: 0; }
.access-summary { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: var(--space-5); }
.access-summary strong { display: block; font-size: 26px; margin-bottom: var(--space-1); }
.access-actions { display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center; }
.access-filters { display: grid; grid-template-columns: minmax(140px,2fr) minmax(140px,1fr) minmax(140px,1fr) auto; gap: var(--space-3); align-items: end; }
.access-facts { display: grid; grid-template-columns: 180px minmax(0,1fr); gap: var(--space-3) var(--space-5); margin: var(--space-5) 0; }
.access-facts dt { color: var(--color-muted); font-size: 13px; }
.access-facts dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.access-copy { white-space: pre-wrap; overflow-wrap: anywhere; }
.access-tags { display: flex; gap: var(--space-2); flex-wrap: wrap; padding: var(--space-4) 0; }
.access-tags code { background: var(--color-surface-muted); padding: 4px 6px; overflow-wrap: anywhere; }
.access-form { display: grid; gap: var(--space-4); max-width: 720px; }
.access-form textarea { font: inherit; width: 100%; padding: var(--space-3); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); resize: vertical; }
.access-form textarea:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 1px; }
.access-table { table-layout: fixed; }
.access-table td, .access-table th { overflow-wrap: anywhere; }
.access-table a { color: var(--color-accent); }
.access-table .status { white-space: normal; }
.access-check { display: flex; align-items: flex-start; gap: var(--space-2); }
.access-check input { width: 18px; min-height: 18px; flex: 0 0 18px; }
@media(max-width: 1100px) { .access-filters { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media(max-width: 700px) {
 .access-summary { grid-template-columns: repeat(2,minmax(0,1fr)); }
 .access-filters, .access-facts { grid-template-columns: minmax(0,1fr); }
 .access-facts { gap: var(--space-2); }
 .access-facts dd { margin-bottom: var(--space-3); }
 .access-table thead { display: none; }
 .access-table, .access-table tbody, .access-table tr, .access-table td { display: block; width: 100%; }
 .access-table tr { padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border); }
 .access-table td { border: 0; padding: 5px 0; }
 .access-table td[data-label]::before { content: attr(data-label); display: block; font-size: 11px; color: var(--color-muted); margin-bottom: 3px; }
 .access-actions { display: grid; grid-template-columns: minmax(0,1fr); }
 .access-actions > * { width: 100%; }
}
</style>"""


def _guard(handler):
    @wraps(handler)
    async def guarded(request):
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)
        try:
            response = await handler(request, actor)
        except PermissionError:
            response = _page(
                actor,
                "Действие недоступно",
                "access-requests",
                '<div class="banner error" role="alert">Нет права выполнить действие. Проверь получателя и права доступа.</div>',
                403,
            )
        except (ValueError, KeyError):
            response = _page(
                actor,
                "Проверь данные",
                "access-requests",
                '<div class="banner error" role="alert">Параметры неверны или состояние уже изменилось. Открой страницу заново.</div>',
                409,
            )
        except Exception as exc:  # noqa: BLE001 - never expose storage or credential errors in HTML
            audit_event(
                event="admin_console_error",
                actor=actor,
                system="access",
                status="error",
                error=type(exc).__name__,
            )
            response = _page(
                actor,
                "Данные недоступны",
                "overview",
                '<div class="banner error" role="alert">Не удалось получить данные. Повтори запрос позже. Сведения об ошибке записаны в журнал.</div>',
                503,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    return guarded


def register_admin_access_routes(mcp):
    @mcp.custom_route("/admin", methods=["GET"], include_in_schema=False)
    @_guard
    async def overview(request, actor):
        await run_in_threadpool(require_current_admin, actor)
        raw_days = request.query_params.get("days", "30")
        days = int(raw_days) if raw_days in {"7", "30", "90"} else 30
        jobs = [
            run_in_threadpool(storage_showcase.showcase_snapshot, days),
            run_in_threadpool(storage_showcase.showcase_people, days, limit=4),
            run_in_threadpool(storage_showcase.agent_profiles, days),
        ]
        results = await gather(*jobs, return_exceptions=True)
        for name, result in zip(("skills", "people", "agents"), results):
            if isinstance(result, Exception):
                audit_event(
                    event="admin_dashboard_source_error",
                    actor=actor,
                    system=name,
                    status="error",
                    error=type(result).__name__,
                )
        snapshot = results[0] if isinstance(results[0], dict) else None
        people = results[1] if isinstance(results[1], dict) else None
        profiles = results[2] if isinstance(results[2], list) else None
        body = team_ai_ui.render(snapshot, people, profiles, days)
        return HTMLResponse(
            admin_shell(
                title="Команда и AI",
                active="overview",
                actor=actor,
                body=body,
                shell_width="1440px",
                extra_head=showcase_ui.CSS + team_ai_ui.CSS,
            )
        )

    @mcp.custom_route(
        "/admin/access-requests", methods=["GET"], include_in_schema=False
    )
    @_guard
    async def requests_page(request, actor):
        offset = _offset(request)
        status = str(request.query_params.get("status", "pending"))
        if status and status not in STATUS:
            raise ValueError("invalid status")
        query = str(request.query_params.get("q", ""))[:200]
        package_key = str(request.query_params.get("package", ""))
        if package_key:
            access_package(package_key)
        rows = await run_in_threadpool(
            list_access_requests,
            status=status,
            query=query,
            package_key=package_key,
            offset=offset,
            limit=PAGE_SIZE + 1,
        )
        filters = '<form class="access-filters" method="get">'
        filters += f'<label>Сотрудник или номер заявки<input name="q" value="{escape(query)}" maxlength="200"></label>'
        filters += _select(
            "status", "Статус", [("", "Все статусы"), *STATUS.items()], status
        )
        filters += _select(
            "package",
            "Пакет",
            [
                ("", "Все пакеты"),
                *[(p["key"], p["title"]) for p in access_package_catalog()],
            ],
            package_key,
        )
        filters += '<button type="submit">Найти</button></form>'
        body = filters + _request_table(rows[:PAGE_SIZE])
        body += _pager(
            "/admin/access-requests",
            offset,
            len(rows) > PAGE_SIZE,
            {"q": query, "status": status, "package": package_key},
        )
        return _page(actor, "Заявки на доступ", "access-requests", body)

    @mcp.custom_route(
        "/admin/access-requests/{request_id}", methods=["GET"], include_in_schema=False
    )
    @_guard
    async def request_page(request, actor):
        row = await _load_request(request)
        if row is None:
            return PlainTextResponse("Заявка не найдена.", status_code=404)
        body = _request_details(row)
        body += _user_link(row["requester_subject"], "Карточка сотрудника")
        csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        if row["status"] == "pending":
            package = access_package(row["package_key"])
            if int(row["package_version"]) != int(package["version"]):
                body += '<div class="banner error">Пакет изменился. Сотруднику нужно отменить заявку и подать новую.</div>'
            elif _is_self(actor, row):
                body += '<div class="banner">Для решения по собственной заявке нужен другой администратор.</div>'
            else:
                body += _package_details(package)
                body += f'<form method="post" action="/admin/access-requests/{escape(str(row["id"]))}/preview" class="access-form">'
                body += _hidden("csrf", csrf)
                body += '<label>Обоснование решения<textarea name="reason" required maxlength="2000" rows="3"></textarea></label>'
                body += '<div class="access-actions"><button name="decision" value="approved">Согласовать</button><button class="danger" name="decision" value="rejected">Отклонить</button></div></form>'
        else:
            body += _facts(
                [
                    ("Решение принял", row.get("decided_by", "")),
                    ("Дата решения", fmt_time(row.get("decided_at"))),
                    ("Обоснование", row.get("decision_reason", "")),
                ]
            )
        response = _page(actor, "Заявка на доступ", "access-requests", body)
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            httponly=True,
            secure=public_url().startswith("https://"),
            samesite="strict",
            path="/admin",
            max_age=3600,
        )
        return response

    @mcp.custom_route(
        "/admin/access-requests/{request_id}/preview",
        methods=["POST"],
        include_in_schema=False,
    )
    @_guard
    async def preview_page(request, actor):
        form = await _read_form(request)
        preview = await _preview(request, actor, form)
        confirmation = _sign_preview(actor, preview, form)
        body = _request_details(preview["request"])
        if form["decision"] == "approved":
            body += _package_details(preview["grant"]["package"])
        body += _facts(
            [("Решение", STATUS[form["decision"]]), ("Обоснование", form["reason"])]
        )
        rid = str(preview["request"]["id"])
        body += f'<form method="post" action="/admin/access-requests/{escape(rid)}/confirm" class="access-form">'
        for key in ("csrf", "decision", "reason"):
            body += _hidden(key, form[key])
        body += _hidden("confirmation", confirmation)
        label = (
            "Подтвердить выдачу"
            if form["decision"] == "approved"
            else "Подтвердить отказ"
        )
        body += '<label class="access-check"><input type="checkbox" name="confirmed" value="yes" required>Получатель, права и срок проверены</label>'
        body += f'<div class="access-actions"><button type="submit">{label}</button><a class="button secondary" href="/admin/access-requests/{escape(rid)}">Назад</a></div></form>'
        audit_event(
            event="admin_access_request_preview",
            actor=actor,
            system="access",
            status="dry_run",
            arguments={"request_id": rid, "decision": form["decision"]},
        )
        return _page(actor, "Подтверждение решения", "access-requests", body)

    @mcp.custom_route(
        "/admin/access-requests/{request_id}/confirm",
        methods=["POST"],
        include_in_schema=False,
    )
    @_guard
    async def confirm_page(request, actor):
        form = await _read_form(request)
        preview = await _preview(request, actor, form)
        if form.get("confirmed") != "yes" or not _verify_preview(actor, preview, form):
            raise ValueError("missing or stale confirmation")
        rid = str(preview["request"]["id"])
        await run_in_threadpool(
            admin_decide_access_request,
            actor=actor,
            request_id=rid,
            decision=form["decision"],
            reason=form["reason"],
            dry_run=False,
        )
        audit_event(
            event="admin_access_request_decided",
            actor=actor,
            system="access",
            status="ok",
            scope="access:admin",
            arguments={"request_id": rid, "decision": form["decision"]},
        )
        return RedirectResponse(f"/admin/access-requests/{rid}", status_code=303)

    @mcp.custom_route("/admin/users", methods=["GET"], include_in_schema=False)
    @_guard
    async def users_page(request, actor):
        query = str(request.query_params.get("q", ""))[:200]
        offset = _offset(request)
        users = await run_in_threadpool(
            admin_users_page, query=query, offset=offset, limit=PAGE_SIZE + 1
        )
        body = f'<form method="get" class="access-form"><label>Почта или учётная запись<input name="q" value="{escape(query)}" maxlength="200"></label><div><button type="submit">Найти</button></div></form>'
        rows = []
        for user in users[:PAGE_SIZE]:
            link = _user_link(user["subject"], user.get("email") or user["subject"])
            rows.append(
                [
                    link,
                    escape(str(user.get("login") or "")),
                    escape(fmt_time(user.get("updated_at"))),
                ]
            )
        body += _table(
            ["Пользователь", "Логин", "Данные обновлены"], rows, trusted=True
        )
        body += _pager("/admin/users", offset, len(users) > PAGE_SIZE, {"q": query})
        return _page(actor, "Пользователи шлюза", "users", body)

    @mcp.custom_route("/admin/users/detail", methods=["GET"], include_in_schema=False)
    @_guard
    async def user_page(request, actor):
        from gateway_mcp.routes.admin_user_roles import role_panel

        subject = str(request.query_params.get("subject", ""))
        user = await run_in_threadpool(admin_user_get, subject)
        if user is None:
            return PlainTextResponse("Пользователь не найден.", status_code=404)
        offset = _offset(request)
        grants = await run_in_threadpool(
            admin_user_grants, user, offset=offset, limit=PAGE_SIZE + 1
        )
        requests = await run_in_threadpool(
            list_access_requests,
            requester_subject=subject,
            offset=offset,
            limit=PAGE_SIZE + 1,
        )
        body = _facts(
            [
                ("Учётная запись", user["subject"]),
                ("Почта", user["email"]),
                ("Логин", user["login"]),
            ]
        )
        csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        state = await run_in_threadpool(admin_role_state, user)
        body += role_panel(user, state, csrf)
        body += '<section class="access-band"><h2>Назначенные пакеты</h2>'
        body += (
            _table(
                ["Пакет", "Состояние", "Срок"],
                [
                    [p["title"], _grant_state(p), _expiry(p)]
                    for p in grants["packages"][:PAGE_SIZE]
                ],
            )
            + "</section>"
        )
        body += '<section class="access-band"><h2>Прямые назначения прав</h2>'
        body += (
            _table(
                ["Scope", "Правило", "Состояние", "Срок"],
                [
                    [p["scope"], p["effect"], _grant_state(p), _expiry(p)]
                    for p in grants["scopes"][:PAGE_SIZE]
                ],
            )
            + "</section>"
        )
        body += '<section class="access-band"><h2>Прямые назначения ресурсов</h2>'
        body += (
            _table(
                ["Система и ресурс", "Действия", "Состояние", "Срок"],
                [
                    [
                        f"{p['system']} · {p['resource_type']} · {p['resource_pattern']}",
                        f"{p['effect']}: {', '.join(p['actions'])}",
                        _grant_state(p),
                        _expiry(p),
                    ]
                    for p in grants["resources"][:PAGE_SIZE]
                ],
            )
            + "</section>"
        )
        body += (
            '<section class="access-band"><h2>История заявок</h2>'
            + _request_table(requests[:PAGE_SIZE])
            + "</section>"
        )
        more = any(len(rows) > PAGE_SIZE for rows in [*grants.values(), requests])
        body += _pager("/admin/users/detail", offset, more, {"subject": subject})
        response = _page(actor, "Доступ сотрудника", "users", body)
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            httponly=True,
            secure=public_url().startswith("https://"),
            samesite="strict",
            path="/admin",
            max_age=3600,
        )
        return response


async def _load_request(request):
    rid = str(UUID(request.path_params["request_id"]))
    return await run_in_threadpool(get_access_request, rid)


def _is_self(actor, row):
    keys = {
        str(v).strip().casefold()
        for v in (actor.subject, actor.email, actor.login, actor.yandex_id)
        if v
    }
    return any(
        str(row.get(key) or "").casefold() in keys
        for key in ("requester_subject", "requester_email", "subject_key")
    )


async def _read_form(request):
    raw = await request.body()
    if len(raw) > 16000:
        raise ValueError("form too large")
    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=10)
    if any(len(values) != 1 for values in parsed.values()):
        raise ValueError("duplicate form field")
    form = {key: values[0] for key, values in parsed.items()}
    csrf = str(request.cookies.get(CSRF_COOKIE) or "")
    if not csrf or not secrets.compare_digest(csrf, form.get("csrf", "")):
        raise PermissionError("CSRF mismatch")
    if form.get("decision") not in {"approved", "rejected"}:
        raise ValueError("invalid decision")
    form["reason"] = form.get("reason", "").strip()
    if not 1 <= len(form["reason"]) <= 2000:
        raise ValueError("reason required")
    return form


async def _preview(request, actor, form):
    row = await _load_request(request)
    if row is None:
        raise ValueError("request not found")
    if _is_self(actor, row):
        raise PermissionError("second administrator required")
    return await run_in_threadpool(
        admin_decide_access_request,
        actor=actor,
        request_id=str(row["id"]),
        decision=form["decision"],
        reason=form["reason"],
        dry_run=True,
    )


def _sign_preview(actor, preview, form, *, expires=None):
    expires = int(time.time()) + 600 if expires is None else expires
    payload = json.dumps(
        {
            "purpose": "admin-access-confirm-v1",
            "actor": actor.subject,
            "preview": preview,
            "reason": form["reason"],
            "csrf": form["csrf"],
            "expires": expires,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    signature = hmac.new(
        jwt_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{expires}.{signature}"


def _verify_preview(actor, preview, form):
    try:
        supplied = form.get("confirmation", "")
        expires = int(supplied.split(".", 1)[0])
        if not 0 <= expires - int(time.time()) <= 600:
            return False
        return secrets.compare_digest(
            supplied, _sign_preview(actor, preview, form, expires=expires)
        )
    except (ValueError, TypeError):
        return False


def _page(actor, title, active, body, status=200):
    heading = f'<header class="page-head"><h1>{escape(title)}</h1></header>'
    return HTMLResponse(
        admin_shell(
            title=title, active=active, actor=actor, body=heading + body, extra_head=CSS
        ),
        status_code=status,
    )


def _integration_state(row: dict[str, Any]) -> str:
    if row.get("state") == "expired":
        return "Срок истёк"
    if row.get("last_check_ok") is False:
        return "Ошибка проверки"
    return {
        "active": "Работает" if row.get("last_check_ok") is True else "Настроено",
        "disabled": "Отключено",
        "missing": "Не настроено",
    }.get(str(row.get("state") or ""), "Проверить")


def _integration_status_class(row: dict[str, Any]) -> str:
    if row.get("state") == "expired" or row.get("last_check_ok") is False:
        return "warning"
    if row.get("state") == "active":
        return "ok"
    return "neutral"


def _hidden(key, value):
    return f'<input type="hidden" name="{escape(key)}" value="{escape(str(value))}">'


def _facts(items):
    return (
        '<dl class="access-facts">'
        + "".join(
            f'<dt>{escape(key)}</dt><dd class="access-copy">{escape(str(value or "—"))}</dd>'
            for key, value in items
        )
        + "</dl>"
    )


def _request_details(row):
    return _facts(
        [
            ("Заявка", str(row["id"])),
            ("Сотрудник", row.get("requester_email") or row["requester_subject"]),
            ("Получатель прав", row["subject_key"]),
            ("Пакет", f"{row['package_key']}, версия {row['package_version']}"),
            ("Состояние", STATUS.get(row["status"], row["status"])),
            (
                "Срок",
                f"{row['requested_ttl_days']} дней с момента выдачи"
                if row.get("requested_ttl_days")
                else "Бессрочно",
            ),
            ("Создана", fmt_time(row.get("created_at"))),
            ("Основание заявки", row["reason"]),
        ]
    )


def _package_details(package):
    body = '<section class="access-band"><h2>Права пакета</h2><div class="access-tags">'
    body += (
        "".join(f"<code>{escape(scope)}</code>" for scope in package.get("scopes", []))
        + "</div>"
    )
    resources = package.get("resources", [])
    if any(r.get("resource_pattern") == "*" for r in resources):
        body += '<div class="banner">Пакет содержит доступ ко всем ресурсам указанных типов (*).</div>'
    body += _table(
        ["Система", "Тип ресурса", "Ресурс", "Действия"],
        [
            [
                r["system"],
                r["resource_type"],
                r["resource_pattern"],
                ", ".join(r["actions"]),
            ]
            for r in resources
        ],
    )
    return body + "</section>"


def _request_table(rows):
    titles = {p["key"]: p["title"] for p in access_package_catalog()}
    items = []
    for row in rows:
        rid = escape(str(row["id"]))
        person = escape(str(row.get("requester_email") or row["requester_subject"]))
        items.append(
            [
                f'<a href="/admin/access-requests/{rid}">{person}</a><span class="table-sub">{rid}</span>',
                escape(titles.get(row["package_key"], row["package_key"])),
                escape(STATUS.get(row["status"], row["status"])),
                escape(fmt_time(row.get("created_at"))),
            ]
        )
    return _table(["Заявка", "Пакет", "Статус", "Создана"], items, trusted=True)


def _table(headers, rows, *, trusted=False):
    body = "".join(
        "<tr>"
        + "".join(
            f'<td data-label="{escape(label)}">{str(value) if trusted else escape(str(value))}</td>'
            for label, value in zip(headers, row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table class="access-table"><thead><tr>'
        + "".join(f'<th scope="col">{escape(label)}</th>' for label in headers)
        + "</tr></thead><tbody>"
        + (body or empty_row(len(headers)))
        + "</tbody></table></div>"
    )


def _select(name, label, choices, value):
    return (
        f'<label>{label}<select name="{name}">'
        + "".join(
            f'<option value="{escape(key)}"{" selected" if key == value else ""}>{escape(title)}</option>'
            for key, title in choices
        )
        + "</select></label>"
    )


def _offset(request):
    return max(0, min(int(request.query_params.get("offset", "0")), 1000000))


def _pager(path, offset, more, query):
    links = []
    for label, target, enabled in (
        ("Назад", max(0, offset - PAGE_SIZE), offset > 0),
        ("Далее", offset + PAGE_SIZE, more),
    ):
        if enabled:
            url = escape(path + "?" + urlencode({**query, "offset": target}))
            links.append(f'<a class="button secondary" href="{url}">{label}</a>')
    return (
        '<nav class="audit-pager" aria-label="Страницы"><span class="muted small">Страница '
        + str(offset // PAGE_SIZE + 1)
        + "</span>"
        + "".join(links)
        + "</nav>"
    )


def _user_link(subject, label):
    return f'<a href="/admin/users/detail?{escape(urlencode({"subject": subject}))}">{escape(str(label))}</a>'


def _grant_state(row):
    if row.get("revoked_at"):
        return "Отозвано"
    if row.get("expires_at"):
        expiry = datetime.fromisoformat(str(row["expires_at"]))
        if expiry <= datetime.now(timezone.utc):
            return "Истекло"
    return "Действует"


def _expiry(row):
    return fmt_time(row["expires_at"]) if row.get("expires_at") else "Бессрочно"
