"""AI directory, personal preferences and explicitly attributed autonomous agents."""

import json
import re
import secrets
from asyncio import gather, to_thread
from functools import wraps
from urllib.parse import parse_qs

from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from gateway_mcp.routes import showcase_ui as ui
from gateway_mcp.routes.admin_access import CSRF_COOKIE
from gateway_mcp.routes.admin_ui import admin_shell
from gateway_mcp.services import storage_showcase as storage
from gateway_mcp.services.admin_roles import require_current_admin
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.storage_admin_console import admin_user_get
from gateway_mcp.web import login_redirect, web_actor


def _page(actor, title, body, active="showcase", status=200, csrf=""):
    response = HTMLResponse(
        admin_shell(
            title=title,
            active=active,
            actor=actor,
            body=body,
            shell_width="1440px",
            extra_head=ui.CSS,
        ),
        status_code=status,
    )
    if csrf:
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
            max_age=3600,
        )
    return response


def _guard(*, admin=True):
    def decorate(handler):
        @wraps(handler)
        async def guarded(request):
            actor = web_actor(request)
            if actor is None:
                return login_redirect("/admin/showcase" if admin else "/my/skills")
            try:
                if admin:
                    await to_thread(require_current_admin, actor)
                response = await handler(request, actor)
            except PermissionError:
                response = PlainTextResponse(
                    "Нет доступа к этому действию.", status_code=403
                )
            except (ValueError, KeyError, UnicodeError):
                response = _page(
                    actor,
                    "Проверь параметры",
                    '<div class="banner error" role="alert">Не удалось сохранить или открыть данные. Проверь поля и открой страницу заново. Один источник может принадлежать только одному агенту.</div>',
                    status=409,
                )
            except Exception as exc:  # noqa: BLE001 - storage details never enter HTML
                if getattr(exc, "sqlstate", "") == "23505":
                    response = _page(
                        actor,
                        "Источник уже используется",
                        '<div class="banner error" role="alert">Этот источник уже привязан к другому агенту. Выбери отдельный источник или сначала измени существующую привязку.</div>',
                        status=409,
                    )
                else:
                    audit_event(
                        event="admin_showcase_error",
                        actor=actor,
                        system="telemetry",
                        status="error",
                        error=type(exc).__name__,
                    )
                    response = _page(
                        actor,
                        "Данные временно недоступны",
                        '<div class="banner error" role="alert">Не удалось загрузить метрики. Повтори запрос позже.</div><a href="/admin">Метрики</a>',
                        status=503,
                    )
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "same-origin",
                    "X-Frame-Options": "DENY",
                    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                }
            )
            return response

        return guarded

    return decorate


def _days(request):
    raw = request.query_params.get("days", "30")
    return int(raw) if raw in {"7", "30", "90"} else 30


def _csrf(request):
    return request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)


async def _form(request, fields):
    raw = await request.body()
    if len(raw) > 8000:
        raise ValueError("form too large")
    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=10)
    if set(parsed) - fields or any(len(v) != 1 for v in parsed.values()):
        raise ValueError("invalid fields")
    values = {k: v[0] for k, v in parsed.items()}
    token = str(request.cookies.get(CSRF_COOKIE) or "")
    if not token or not secrets.compare_digest(token, values.get("csrf", "")):
        raise PermissionError("csrf")
    return values


async def _snapshot(days, **params):
    result = await to_thread(storage.showcase_snapshot, days, **params)
    return {**result, "days": days}


def register_admin_showcase_routes(mcp):
    @mcp.custom_route("/admin/showcase", methods=["GET"], include_in_schema=False)
    @_guard()
    async def showcase(request, actor):
        days = _days(request)
        snapshot, people, profiles = await gather(
            _snapshot(days),
            to_thread(storage.showcase_people, days, limit=6),
            to_thread(storage.agent_profiles, days),
        )
        return _page(
            actor, "Метрики использования AI", ui.overview(snapshot, people, profiles)
        )

    @mcp.custom_route("/admin/people", methods=["GET"], include_in_schema=False)
    @_guard()
    async def people(request, actor):
        days, query = _days(request), request.query_params.get("q", "")[:120]
        raw = request.query_params.get("page", "1")
        page = min(max(int(raw), 1), 10000) if raw.isdigit() and len(raw) <= 6 else 1
        data = await to_thread(storage.showcase_people, days, query, (page - 1) * 12)
        return _page(actor, "Люди", ui.people_page(data, days, query, page), "people")

    async def person_detail(request, actor, personal):
        subject = actor.subject if personal else request.query_params.get("subject", "")
        user = (
            {"login": actor.display}
            if personal
            else await to_thread(admin_user_get, subject)
        )
        if not user:
            return PlainTextResponse("Пользователь не найден.", status_code=404)
        days = _days(request)
        snapshot, usage, favorites = await gather(
            _snapshot(days, subject=subject, people_only=True),
            to_thread(storage.showcase_usage, days, subject),
            to_thread(storage.skill_favorites, subject, days),
        )
        csrf = _csrf(request)
        body = ui.detail(
            snapshot,
            usage,
            user.get("login") or user.get("email") or "Пользователь шлюза",
            favorites=favorites,
            editable=personal,
            csrf=csrf,
            subject=subject,
            personal=personal,
        )
        if not personal and subject == actor.subject:
            body += '<a href="/my/skills">Выбрать мои любимые навыки</a>'
        return _page(
            actor,
            "Профиль AI",
            body,
            "my-skills" if personal else "people",
            csrf=csrf if personal else "",
        )

    @mcp.custom_route("/admin/people/detail", methods=["GET"], include_in_schema=False)
    @_guard()
    async def person(request, actor):
        return await person_detail(request, actor, False)

    @mcp.custom_route("/my/skills", methods=["GET"], include_in_schema=False)
    @_guard(admin=False)
    async def my_skills(request, actor):
        return await person_detail(request, actor, True)

    @mcp.custom_route("/my/skills/favorite", methods=["POST"], include_in_schema=False)
    @_guard(admin=False)
    async def favorite(request, actor):
        form = await _form(
            request, {"csrf", "skill_pack", "skill_id", "selected", "days"}
        )
        skill, pack = form.get("skill_id", ""), form.get("skill_pack", "")
        if (
            not 1 <= len(skill) <= 160
            or len(pack) > 160
            or form.get("selected") not in {"0", "1"}
        ):
            raise ValueError("invalid preference")
        # Subject is always the authenticated caller; it is never accepted from a form.
        await to_thread(
            storage.set_skill_favorite,
            actor.subject,
            pack,
            skill,
            form["selected"] == "1",
        )
        audit_event(
            event="assistant_favorite_updated",
            actor=actor,
            system="telemetry",
            status="ok",
        )
        days = form.get("days") if form.get("days") in {"7", "30", "90"} else "30"
        return RedirectResponse(ui.url("/my/skills", days=days), status_code=303)

    @mcp.custom_route("/admin/agents", methods=["GET"], include_in_schema=False)
    @_guard()
    async def agents(request, actor):
        days, csrf = _days(request), _csrf(request)
        profiles, options = await gather(
            to_thread(storage.agent_profiles, days),
            to_thread(storage.agent_binding_options),
        )
        return _page(
            actor,
            "Автономные агенты",
            ui.agents_page(profiles, options, csrf, days),
            "agents",
            csrf=csrf,
        )

    @mcp.custom_route("/admin/agents/detail", methods=["GET"], include_in_schema=False)
    @_guard()
    async def agent_detail(request, actor):
        days, csrf = _days(request), _csrf(request)
        profiles, options = await gather(
            to_thread(storage.agent_profiles, days),
            to_thread(storage.agent_binding_options),
        )
        profile = next(
            (p for p in profiles if p["agent_key"] == request.query_params.get("key")),
            None,
        )
        if profile is None:
            return PlainTextResponse("Агент не найден.", status_code=404)
        if profile["actor_subject"]:
            snapshot, usage = await gather(
                _snapshot(
                    days, subject=profile["actor_subject"], agent=profile["agent"]
                ),
                to_thread(
                    storage.showcase_usage,
                    days,
                    profile["actor_subject"],
                    profile["agent"],
                    False,
                ),
            )
            body = ui.detail(
                snapshot, usage, profile["display_name"], agent_profile=profile
            )
        else:
            body = (
                '<div class="showcase">'
                + ui.header(
                    profile["display_name"],
                    profile["description"],
                    days,
                    "/admin/agents/detail",
                    "agents",
                    key=profile["agent_key"],
                )
                + '<div class="sc-empty">Источник телеметрии ещё не привязан. Выбери его ниже, чтобы появились метрики. Статус работы и результаты пока неизвестны.</div></div>'
            )
        body += (
            '<div class="showcase"><section class="sc-panel">'
            + ui.agent_form(profile, options, csrf)
            + '</section><p class="sc-note">Текущая привязка определяет метрики за весь выбранный период. Смена привязки пересчитает историю отображения.</p></div>'
        )
        return _page(actor, profile["display_name"], body, "agents", csrf=csrf)

    @mcp.custom_route("/admin/agents/save", methods=["POST"], include_in_schema=False)
    @_guard()
    async def save_agent(request, actor):
        form = await _form(
            request, {"csrf", "key", "name", "description", "binding", "revision"}
        )
        key, name, description = (
            form.get("key", ""),
            form.get("name", "").strip(),
            form.get("description", "").strip(),
        )
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", key)
            or not 1 <= len(name) <= 80
            or len(description) > 300
        ):
            raise ValueError("invalid profile")
        pair = json.loads(form.get("binding", "[]"))
        if pair == []:
            pair = ["", ""]
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(v, str) or len(v) > 250 for v in pair)
            or bool(pair[0]) != bool(pair[1])
        ):
            raise ValueError("invalid binding")
        revision = int(form.get("revision", "0"))
        if not 0 <= revision <= 2147483646:
            raise ValueError("invalid revision")
        await to_thread(
            storage.save_agent_profile,
            key=key,
            name=name,
            description=description,
            subject=pair[0],
            agent=pair[1],
            revision=revision,
            updated_by=actor.subject,
        )
        audit_event(
            event="assistant_agent_profile_updated",
            actor=actor,
            system="telemetry",
            status="ok",
            arguments={"agent_key": key, "binding_present": bool(pair[0])},
        )
        return RedirectResponse(
            ui.url("/admin/agents/detail", key=key), status_code=303
        )
