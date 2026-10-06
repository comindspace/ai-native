from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from asyncio import to_thread
from html import escape
from urllib.parse import parse_qs, urlencode

from starlette.responses import RedirectResponse

from gateway_mcp.routes.admin_access import (
    CSRF_COOKIE,
    _facts,
    _guard,
    _hidden,
    _page,
)
from gateway_mcp.services.access_admin import admin_grant_scope
from gateway_mcp.services.admin_roles import (
    admin_role_state,
    assign_admin_role,
    require_current_admin,
)
from gateway_mcp.services.auth import jwt_secret
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.storage_admin_console import admin_user_get
from gateway_mcp.services.storage_idempotency import (
    claim_idempotency,
    complete_idempotency,
)

TERMS = {0: "Бессрочно", 7: "7 дней", 30: "30 дней", 90: "90 дней", 365: "1 год"}


def role_panel(user, state, csrf):
    label = "Администратор" if state["is_admin"] else "Пользователь"
    body = f'<section class="access-band"><h2>Роль в шлюзе: {label}</h2>'
    if state["is_admin"]:
        return body + "<p>Доступ к админке уже включён.</p></section>"
    if state["denied"]:
        return (
            body
            + "<p>Назначение ограничено действующим запретом. Сначала проверь правила доступа.</p></section>"
        )
    body += (
        "<p>Администратор управляет пользователями, правами и настройками шлюза.</p>"
    )
    body += (
        '<form method="post" action="/admin/users/role/preview" class="access-form">'
    )
    body += _hidden("csrf", csrf) + _hidden("subject", user["subject"])
    body += (
        '<label>Срок<select name="ttl_days">'
        + "".join(
            f'<option value="{days}"{" selected" if days == 30 else ""}>{label}</option>'
            for days, label in TERMS.items()
        )
        + "</select></label>"
    )
    body += '<label>Основание<textarea name="reason" rows="2" required maxlength="500" placeholder="Для чего сотруднику нужен доступ администратора"></textarea></label>'
    return (
        body
        + '<button type="submit">Назначить администратором</button></form></section>'
    )


async def _role_preview(request, actor):
    await to_thread(require_current_admin, actor)
    raw = await request.body()
    if len(raw) > 8000:
        raise ValueError("form too large")
    values = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
    allowed = {"csrf", "subject", "reason", "ttl_days", "confirmation", "confirmed"}
    if set(values) - allowed or any(len(v) != 1 for v in values.values()):
        raise ValueError("invalid fields")
    form = {k: v[0] for k, v in values.items()}
    csrf = str(request.cookies.get(CSRF_COOKIE) or "")
    if not csrf or not secrets.compare_digest(csrf, form.get("csrf", "")):
        raise PermissionError("csrf")
    reason = form.get("reason", "").strip()
    days = int(form.get("ttl_days", "-1"))
    subject = form.get("subject", "")
    if not 1 <= len(reason) <= 500 or days not in TERMS or not 1 <= len(subject) <= 250:
        raise ValueError("invalid role request")
    user = await to_thread(admin_user_get, subject)
    if user is None:
        raise ValueError("unknown user")
    actor_keys = {
        str(x).casefold()
        for x in (actor.subject, actor.email, actor.login, actor.yandex_id)
        if x
    }
    user_keys = {
        str(user.get(k) or "").casefold()
        for k in ("subject", "email", "login", "yandex_id")
    } - {""}
    if actor_keys & user_keys:
        raise PermissionError("self grant")
    state = await to_thread(admin_role_state, user)
    if state["is_admin"] or state["denied"]:
        raise ValueError("role already active or denied")
    preview = await to_thread(
        admin_grant_scope,
        actor=actor,
        subject_type="user",
        subject_key=user["subject"],
        scope="access:admin",
        effect="allow",
        reason=reason,
        ttl_days=days or None,
        dry_run=True,
    )
    form["reason"] = reason
    return form, {
        "kind": "admin-role-v1",
        "user": user,
        "state": state,
        "grant": preview["grant"],
    }


def _signature(actor, preview, csrf, expires):
    payload = json.dumps(
        {
            "purpose": "admin-role-v1",
            "actor": actor.subject,
            "preview": preview,
            "csrf": csrf,
            "expires": expires,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hmac.new(jwt_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def register_admin_user_role_routes(mcp):
    @mcp.custom_route(
        "/admin/users/role/preview", methods=["POST"], include_in_schema=False
    )
    @_guard
    async def preview_role(request, actor):
        form, preview = await _role_preview(request, actor)
        expires = int(time.time()) + 600
        token = f"{expires}.{_signature(actor, preview, form['csrf'], expires)}"
        user = preview["user"]
        body = "<p>Проверь получателя и срок. После подтверждения сотрудник сможет управлять доступами и настройками шлюза.</p>"
        body += _facts(
            [
                ("Пользователь", user.get("email") or user["subject"]),
                ("Роль", "Администратор"),
                ("Срок", TERMS[int(form["ttl_days"])]),
                ("Основание", form["reason"]),
            ]
        )
        body += '<form method="post" action="/admin/users/role/confirm" class="access-form">'
        for key in ("csrf", "subject", "reason", "ttl_days"):
            body += _hidden(key, form[key])
        body += _hidden("confirmation", token)
        back = "/admin/users/detail?" + urlencode({"subject": user["subject"]})
        body += '<label class="access-check"><input type="checkbox" name="confirmed" value="yes" required>Подтверждаю назначение администратора</label>'
        body += f'<div class="access-actions"><button>Подтвердить назначение</button><a class="button secondary" href="{escape(back)}">Назад</a></div></form>'
        audit_event(
            event="admin_role_preview",
            actor=actor,
            system="access",
            status="dry_run",
            arguments={"subject": user["subject"], "scope": "access:admin"},
        )
        return _page(actor, "Назначение администратора", "users", body)

    @mcp.custom_route(
        "/admin/users/role/confirm", methods=["POST"], include_in_schema=False
    )
    @_guard
    async def confirm_role(request, actor):
        form, preview = await _role_preview(request, actor)
        token = form.get("confirmation", "")
        expires_text, _, supplied = token.partition(".")
        expires = int(expires_text)
        if (
            form.get("confirmed") != "yes"
            or not 0 <= expires - int(time.time()) <= 600
            or not secrets.compare_digest(
                supplied, _signature(actor, preview, form["csrf"], expires)
            )
        ):
            raise ValueError("invalid confirmation")
        grant = preview["grant"]
        operation = {
            "actor_subject": actor.subject,
            "tool_name": "admin.users.grant_admin",
            "idempotency_key": hashlib.sha256(token.encode()).hexdigest(),
        }
        claim = await to_thread(claim_idempotency, **operation, request_hash=supplied)
        if not claim.get("claimed"):
            raise ValueError("confirmation already used")
        # Keep an uncertain operation pending: retrying a partially committed grant
        # must never create another grant. A fresh preview rechecks the live role.
        result = await to_thread(assign_admin_role, actor, preview)
        await to_thread(
            complete_idempotency,
            **operation,
            response={"grant_id": result["grant"]["id"]},
        )
        audit_event(
            event="admin_role_granted",
            actor=actor,
            system="access",
            status="ok",
            scope="access:admin",
            arguments={
                "subject": grant["subject_key"],
                "grant_id": result["grant"]["id"],
            },
        )
        return RedirectResponse(
            "/admin/users/detail?" + urlencode({"subject": preview["user"]["subject"]}),
            status_code=303,
        )
