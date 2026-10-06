from datetime import datetime, timezone
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

from gateway_mcp.routes.credentials_ui import render_credentials_page
from gateway_mcp.services.auth import (
    YANDEX_VERIFICATION_CODE_URL,
    bind_yandex_code_to_actor,
)
from gateway_mcp.services.credential_checks import (
    check_credential as run_credential_check,
)
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage import (
    list_service_credential_actors,
    list_service_oauth_tokens,
    list_user_oauth_tokens,
    revoke_user_oauth_token,
    save_user_oauth_token,
)
from gateway_mcp.web import login_redirect, web_actor

UTC = timezone.utc


def register_credentials_routes(mcp):
    def _credential_status(actor: GatewayActor) -> dict[str, dict[str, Any]]:
        return {
            item["provider"]: item for item in list_user_oauth_tokens(actor.subject)
        }

    def _check_banner(request: Request) -> str:
        checked = str(request.query_params.get("checked") or "")
        if not checked:
            return ""
        ok = str(request.query_params.get("ok") or "") == "1"
        message = escape(str(request.query_params.get("message") or ""))
        css = "okbox" if ok else "errorbox"
        title = "Проверка пройдена" if ok else "Проверка не пройдена"
        return f'<div class="{css}"><strong>{title}.</strong> {message}</div>'

    def _service_binding_banner(request: Request) -> str:
        if str(request.query_params.get("service_binding") or "") != "ok":
            return ""
        actor_subject = escape(str(request.query_params.get("actor_subject") or ""))
        return f'<div class="okbox"><strong>Сервисный аккаунт привязан.</strong> Yandex OAuth сохранен для {actor_subject}.</div>'

    def _credential_binding_banner(request: Request) -> str:
        if str(request.query_params.get("credential_binding") or "") != "ok":
            return ""
        provider = escape(str(request.query_params.get("provider") or ""))
        return f'<div class="okbox"><strong>Подключение сохранено.</strong> OAuth-токен сохранен для {provider}.</div>'

    def _state_label(connected: bool) -> str:
        return "подключено" if connected else "не подключено"

    def _format_updated_at(value: Any) -> str:
        if not value:
            return ""
        parsed = value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return str(value).split(".")[0].replace("T", " ")
        if isinstance(parsed, datetime):
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone(UTC)
            return parsed.strftime("%d.%m.%Y %H:%M UTC")
        return str(value)

    def _service_credentials_panel(actor: GatewayActor) -> str:
        if not has_scope(actor, "access:admin"):
            return ""

        service_subjects = list_service_credential_actors()
        service_tokens = {
            (item["actor_subject"], item["provider"]): item
            for item in list_service_oauth_tokens()
            if str(item.get("actor_subject") or "").startswith("service:")
        }
        if not service_subjects:
            service_subjects = ["service:hermes-salesbro"]

        rows = []
        for subject in service_subjects:
            core_token = service_tokens.get((subject, "yandex"), {})
            disk_token = service_tokens.get((subject, "yandex-disk"), {})
            core_connected = bool(core_token.get("connected"))
            disk_connected = bool(disk_token.get("connected"))
            core_state = _state_label(core_connected)
            disk_state = _state_label(disk_connected)
            core_state_class = "ok" if core_connected else "missing"
            disk_state_class = "ok" if disk_connected else "missing"
            login_source = disk_token or core_token
            login = escape(
                str(
                    login_source.get("email")
                    or login_source.get("login")
                    or "не привязан"
                )
            )
            login_hint = escape(
                str(login_source.get("email") or login_source.get("login") or "")
            )
            updated = escape(_format_updated_at(login_source.get("updated_at")))
            subject_escaped = escape(subject)
            disk_revoke_form = (
                f"""
                <form method="post" action="/credentials/service/yandex/delete" onsubmit="return confirm('Отозвать сохранённый доступ к Диску?')">
                  <input type="hidden" name="actor_subject" value="{subject_escaped}">
                  <input type="hidden" name="provider" value="yandex-disk">
                  <button class="danger compact" type="submit">Отозвать Disk</button>
                </form>
                """
                if disk_connected
                else ""
            )
            rows.append(
                f"""
                <tr>
                  <td><code>{subject_escaped}</code></td>
                  <td><span class="status {core_state_class}">{core_state}</span></td>
                  <td><span class="status {disk_state_class}">{disk_state}</span></td>
                  <td>{login}{f'<br><span class="muted small">Обновлено: {updated}</span>' if updated else ""}</td>
                  <td class="service-actions">
                    <form class="service-bind-form" method="get" action="/auth/yandex/service-login">
                      <input type="hidden" name="actor_subject" value="{subject_escaped}">
                      <input type="hidden" name="provider" value="yandex-disk">
                      <input type="hidden" name="manual" value="1">
                      <input type="hidden" name="next" value="/credentials">
                      <input class="compact-input" name="login_hint" value="{login_hint}" placeholder="service@yandex.ru" autocomplete="off">
                      <button class="compact" type="submit">Получить код Disk</button>
                    </form>
                    <form class="service-bind-form" method="post" action="/credentials/service/yandex/manual">
                      <input type="hidden" name="actor_subject" value="{subject_escaped}">
                      <input type="hidden" name="provider" value="yandex-disk">
                      <input class="compact-input" name="login_hint" value="{login_hint}" placeholder="service@yandex.ru" autocomplete="off">
                      <input class="compact-input code-input" name="code" placeholder="Код Яндекса" autocomplete="one-time-code" required>
                      <button class="compact" type="submit">Сохранить Disk</button>
                    </form>
                    {disk_revoke_form}
                  </td>
                </tr>
                """
            )

        return f"""
        <section class="panel wide">
          <div class="panel-header">
            <h2>Сервисные аккаунты</h2>
            <span class="status ok">admin</span>
          </div>
          <p class="description">Здесь администратор привязывает OAuth-доступы к автономным агентам. Например, сервисный профиль может использовать Yandex Disk от имени сервисного аккаунта, а не личного пользователя.</p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Профиль</th>
                  <th>Yandex OAuth</th>
                  <th>Yandex Disk</th>
                  <th>Аккаунт Яндекса</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {"".join(rows)}
              </tbody>
            </table>
          </div>
        </section>
        """

    @mcp.custom_route("/credentials", methods=["GET"], include_in_schema=False)
    async def credentials_page(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")

        status = _credential_status(actor)
        calendar = status.get("yandex-caldav", {})
        yandex = status.get("yandex", {})
        yandex_disk = status.get("yandex-disk", {})
        google = status.get("google", {})
        gitlab = status.get("gitlab", {})
        calendar_connected = bool(calendar.get("connected"))
        yandex_connected = bool(yandex.get("connected"))
        yandex_disk_connected = bool(yandex_disk.get("connected"))
        google_connected = bool(google.get("connected"))
        gitlab_connected = bool(gitlab.get("connected"))
        calendar_state = _state_label(calendar_connected)
        yandex_state = _state_label(yandex_connected)
        yandex_disk_state = _state_label(yandex_disk_connected)
        google_state = _state_label(google_connected)
        gitlab_state = _state_label(gitlab_connected)
        yandex_disk_updated = escape(_format_updated_at(yandex_disk.get("updated_at")))
        google_updated = escape(_format_updated_at(google.get("updated_at")))
        calendar_updated = escape(_format_updated_at(calendar.get("updated_at")))
        gitlab_updated = escape(_format_updated_at(gitlab.get("updated_at")))
        banner = (
            _service_binding_banner(request)
            or _credential_binding_banner(request)
            or _check_banner(request)
        )
        service_credentials_panel = _service_credentials_panel(actor)

        return HTMLResponse(
            render_credentials_page(
                actor=actor,
                banner=banner,
                service_panel=service_credentials_panel,
                yandex_connected=yandex_connected,
                yandex_state=yandex_state,
                yandex_disk_connected=yandex_disk_connected,
                yandex_disk_state=yandex_disk_state,
                yandex_disk_updated=yandex_disk_updated,
                google_connected=google_connected,
                google_state=google_state,
                google_updated=google_updated,
                gitlab_connected=gitlab_connected,
                gitlab_state=gitlab_state,
                gitlab_updated=gitlab_updated,
                calendar_connected=calendar_connected,
                calendar_state=calendar_state,
                calendar_updated=calendar_updated,
            )
        )

    @mcp.custom_route(
        "/credentials/check/{provider}", methods=["GET"], include_in_schema=False
    )
    async def check_credential_route(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        provider = str(request.path_params.get("provider") or "")
        result = await run_credential_check(provider, actor)
        audit_event(
            event="credential_check",
            actor=actor,
            system=provider or "unknown",
            decision="allow",
            status="ok" if result["ok"] else "error",
            arguments={"provider": provider},
        )
        query = urlencode(
            {
                "checked": provider,
                "ok": "1" if result["ok"] else "0",
                "message": str(result["message"]),
            }
        )
        return RedirectResponse(f"/credentials?{query}", status_code=303)

    @mcp.custom_route(
        "/credentials/calendar", methods=["POST"], include_in_schema=False
    )
    async def save_calendar_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
        app_password = str((form.get("app_password") or [""])[0]).strip()
        if not app_password:
            return PlainTextResponse(
                "Calendar app password is required.", status_code=400
            )

        save_user_oauth_token(
            provider="yandex-caldav",
            actor_subject=actor.subject,
            yandex_id=actor.yandex_id,
            login=actor.login,
            email=actor.email,
            access_token=app_password,
            token_type="AppPassword",
            scopes=["calendar:read"],
            metadata={"credential_type": "yandex_calendar_app_password"},
            expires_at_epoch=None,
        )
        audit_event(
            event="credential_save",
            actor=actor,
            system="yandex-calendar",
            decision="allow",
            status="ok",
            scope="calendar:read",
            arguments={"provider": "yandex-caldav"},
        )
        return RedirectResponse("/credentials", status_code=303)

    @mcp.custom_route("/credentials/gitlab", methods=["POST"], include_in_schema=False)
    async def save_gitlab_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
        gitlab_token = str((form.get("gitlab_token") or [""])[0]).strip()
        if not gitlab_token:
            return PlainTextResponse("GitLab token is required.", status_code=400)

        save_user_oauth_token(
            provider="gitlab",
            actor_subject=actor.subject,
            yandex_id=actor.yandex_id,
            login=actor.login,
            email=actor.email,
            access_token=gitlab_token,
            token_type="PrivateToken",
            scopes=["gitlab:read", "gitlab:write"],
            metadata={"credential_type": "gitlab_personal_access_token"},
            expires_at_epoch=None,
        )
        audit_event(
            event="credential_save",
            actor=actor,
            system="gitlab",
            decision="allow",
            status="ok",
            scope="gitlab:read",
            arguments={"provider": "gitlab"},
        )
        return RedirectResponse("/credentials", status_code=303)

    @mcp.custom_route(
        "/credentials/yandex-disk/manual", methods=["POST"], include_in_schema=False
    )
    async def save_yandex_disk_manual_code(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
        code = str((form.get("code") or [""])[0]).strip()
        if not code:
            return PlainTextResponse(
                "Yandex confirmation code is required.", status_code=400
            )

        try:
            yandex_actor = await bind_yandex_code_to_actor(
                code=code,
                actor_subject=actor.subject,
                provider="yandex-disk",
                expected_login=actor.email or actor.login,
                redirect_uri=YANDEX_VERIFICATION_CODE_URL,
                metadata={"source": "yandex_disk_manual_code"},
            )
        except PermissionError as exc:
            return PlainTextResponse(str(exc), status_code=403)
        except Exception as exc:  # noqa: BLE001 - OAuth boundary returns an audited error
            return PlainTextResponse(
                f"Failed to save Yandex Disk token: {exc}", status_code=500
            )

        audit_event(
            event="credential_save",
            actor=actor,
            system="yandex-disk",
            decision="allow",
            status="ok",
            scope="yandex_disk:read",
            arguments={
                "provider": "yandex-disk",
                "yandex_actor_subject": yandex_actor.subject,
            },
        )
        return RedirectResponse(
            "/credentials?"
            + urlencode({"credential_binding": "ok", "provider": "yandex-disk"}),
            status_code=303,
        )

    @mcp.custom_route(
        "/credentials/gitlab/delete", methods=["POST"], include_in_schema=False
    )
    async def delete_gitlab_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        deleted = revoke_user_oauth_token("gitlab", actor.subject)
        audit_event(
            event="credential_delete",
            actor=actor,
            system="gitlab",
            decision="allow",
            status="ok" if deleted else "not_found",
            scope="gitlab:read",
            arguments={"provider": "gitlab"},
        )
        return RedirectResponse("/credentials", status_code=303)

    @mcp.custom_route(
        "/credentials/google/delete", methods=["POST"], include_in_schema=False
    )
    async def delete_google_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        deleted = revoke_user_oauth_token("google", actor.subject)
        audit_event(
            event="credential_delete",
            actor=actor,
            system="google",
            decision="allow",
            status="ok" if deleted else "not_found",
            scope="google_drive:read",
            arguments={"provider": "google"},
        )
        return RedirectResponse("/credentials", status_code=303)

    @mcp.custom_route(
        "/credentials/calendar/delete", methods=["POST"], include_in_schema=False
    )
    async def delete_calendar_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        deleted = revoke_user_oauth_token("yandex-caldav", actor.subject)
        audit_event(
            event="credential_delete",
            actor=actor,
            system="yandex-calendar",
            decision="allow",
            status="ok" if deleted else "not_found",
            scope="calendar:read",
            arguments={"provider": "yandex-caldav"},
        )
        return RedirectResponse("/credentials", status_code=303)

    @mcp.custom_route(
        "/credentials/yandex-disk/delete", methods=["POST"], include_in_schema=False
    )
    async def delete_yandex_disk_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        deleted = revoke_user_oauth_token("yandex-disk", actor.subject)
        audit_event(
            event="credential_delete",
            actor=actor,
            system="yandex-disk",
            decision="allow",
            status="ok" if deleted else "not_found",
            scope="yandex_disk:read",
            arguments={"provider": "yandex-disk"},
        )
        return RedirectResponse("/credentials", status_code=303)

    @mcp.custom_route(
        "/credentials/service/yandex/manual", methods=["POST"], include_in_schema=False
    )
    async def save_service_yandex_manual_code(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)

        form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
        actor_subject = str((form.get("actor_subject") or [""])[0]).strip()
        if not actor_subject.startswith("service:"):
            return PlainTextResponse(
                "service actor_subject is required.", status_code=400
            )

        provider = (
            str((form.get("provider") or ["yandex-disk"])[0]).strip() or "yandex-disk"
        )
        if provider != "yandex-disk":
            return PlainTextResponse(
                "manual service binding is supported only for yandex-disk.",
                status_code=400,
            )

        code = str((form.get("code") or [""])[0]).strip()
        if not code:
            return PlainTextResponse(
                "Yandex confirmation code is required.", status_code=400
            )

        expected_login = str((form.get("login_hint") or [""])[0]).strip()
        try:
            yandex_actor = await bind_yandex_code_to_actor(
                code=code,
                actor_subject=actor_subject,
                provider=provider,
                expected_login=expected_login,
                redirect_uri=YANDEX_VERIFICATION_CODE_URL,
                metadata={
                    "source": "yandex_disk_service_manual_code",
                    "admin_subject": actor.subject,
                },
            )
        except PermissionError as exc:
            return PlainTextResponse(str(exc), status_code=403)
        except Exception as exc:  # noqa: BLE001 - OAuth boundary returns an audited error
            return PlainTextResponse(
                f"Failed to save service Yandex Disk token: {exc}", status_code=500
            )

        audit_event(
            event="credential_save",
            actor=actor,
            system="yandex-disk",
            decision="allow",
            status="ok",
            scope="access:admin",
            arguments={
                "provider": provider,
                "actor_subject": actor_subject,
                "yandex_actor_subject": yandex_actor.subject,
            },
        )
        return RedirectResponse(
            "/credentials?"
            + urlencode({"service_binding": "ok", "actor_subject": actor_subject}),
            status_code=303,
        )

    @mcp.custom_route(
        "/credentials/service/yandex/delete", methods=["POST"], include_in_schema=False
    )
    async def delete_service_yandex_credential(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/credentials")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)
        form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
        actor_subject = str((form.get("actor_subject") or [""])[0]).strip()
        if not actor_subject.startswith("service:"):
            return PlainTextResponse(
                "service actor_subject is required.", status_code=400
            )

        provider = str((form.get("provider") or ["yandex"])[0]).strip() or "yandex"
        if provider not in {"yandex", "yandex-disk"}:
            return PlainTextResponse("unsupported provider.", status_code=400)

        deleted = revoke_user_oauth_token(provider, actor_subject)
        audit_event(
            event="credential_delete",
            actor=actor,
            system="yandex",
            decision="allow",
            status="ok" if deleted else "not_found",
            scope="access:admin",
            arguments={"provider": provider, "actor_subject": actor_subject},
        )
        return RedirectResponse("/credentials", status_code=303)
