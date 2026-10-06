from urllib.parse import parse_qsl, urlencode

from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from gateway_mcp.services.auth import (
    YANDEX_VERIFICATION_CODE_URL,
    actor_payload,
    auth_enabled,
    bind_google_code_to_actor,
    bind_yandex_code_to_actor,
    build_google_authorize_url,
    build_oauth_authorization_redirect,
    build_redirect_uri_with_params,
    build_yandex_authorize_url,
    create_mcp_authorization_code,
    create_oauth_state,
    create_oauth_state_payload,
    current_actor,
    exchange_mcp_authorization_code,
    exchange_mcp_refresh_token,
    issuer_url,
    login_with_yandex_code,
    oauth_authorization_server_metadata,
    pop_oauth_state,
    register_oauth_client,
    revoke_mcp_oauth_token,
    token_ttl_seconds,
)
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import has_scope
from gateway_mcp.web import (
    clear_gateway_cookie,
    login_redirect,
    web_actor,
    with_gateway_cookie,
)


def register_auth_routes(mcp):
    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"], include_in_schema=False)
    async def oauth_authorization_server(_: Request) -> Response:
        return JSONResponse(oauth_authorization_server_metadata())

    @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"], include_in_schema=False)
    async def openid_configuration(_: Request) -> Response:
        return JSONResponse(oauth_authorization_server_metadata())

    @mcp.custom_route("/oauth/register", methods=["POST"], include_in_schema=False)
    async def oauth_register(request: Request) -> Response:
        try:
            metadata = await request.json()
            if not isinstance(metadata, dict):
                raise ValueError("JSON object is required")
            return JSONResponse(register_oauth_client(metadata), status_code=201)
        except Exception as exc:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": str(exc)}, status_code=400)

    @mcp.custom_route("/oauth/authorize", methods=["GET", "POST"], include_in_schema=False)
    async def oauth_authorize(request: Request) -> Response:
        try:
            if request.method == "POST":
                params = dict(parse_qsl((await request.body()).decode("utf-8"), keep_blank_values=True))
            else:
                params = {key: value for key, value in request.query_params.items()}
            return RedirectResponse(await build_oauth_authorization_redirect(params))
        except Exception as exc:
            return JSONResponse({"error": "invalid_request", "error_description": str(exc)}, status_code=400)

    @mcp.custom_route("/oauth/token", methods=["POST"], include_in_schema=False)
    async def oauth_token(request: Request) -> Response:
        try:
            params = dict(parse_qsl((await request.body()).decode("utf-8"), keep_blank_values=True))
            grant_type = params.get("grant_type")
            if grant_type == "authorization_code":
                token = exchange_mcp_authorization_code(
                    code=params.get("code", ""),
                    client_id=params.get("client_id", ""),
                    redirect_uri=params.get("redirect_uri", ""),
                    code_verifier=params.get("code_verifier", ""),
                    resource=params.get("resource", ""),
                )
            elif grant_type == "refresh_token":
                token = exchange_mcp_refresh_token(
                    refresh_token=params.get("refresh_token", ""),
                    client_id=params.get("client_id", ""),
                    resource=params.get("resource", ""),
                )
            else:
                raise ValueError(
                    "grant_type must be authorization_code or refresh_token"
                )
            return JSONResponse(token)
        except Exception as exc:
            return JSONResponse({"error": "invalid_grant", "error_description": str(exc)}, status_code=400)

    @mcp.custom_route("/oauth/revoke", methods=["POST"], include_in_schema=False)
    async def oauth_revoke(request: Request) -> Response:
        params = dict(
            parse_qsl(
                (await request.body()).decode("utf-8"), keep_blank_values=True
            )
        )
        token = params.get("token", "")
        if token:
            revoke_mcp_oauth_token(token)
        return Response(status_code=200)

    @mcp.custom_route("/auth/yandex/login", methods=["GET"], include_in_schema=False)
    async def yandex_login(request: Request) -> Response:
        next_url = request.query_params.get("next", "/credentials")
        state = create_oauth_state(next_url)
        try:
            return RedirectResponse(build_yandex_authorize_url(state, force_confirm=True))
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @mcp.custom_route("/auth/logout", methods=["GET", "POST"], include_in_schema=False)
    async def logout(request: Request) -> Response:
        token = getattr(request, "cookies", {}).get("gateway_token", "")
        if token:
            revoke_mcp_oauth_token(token)
        return clear_gateway_cookie(RedirectResponse("/auth/logged-out", status_code=303))

    @mcp.custom_route("/auth/logged-out", methods=["GET"], include_in_schema=False)
    async def logged_out(_: Request) -> Response:
        return HTMLResponse(
            """
            <!doctype html>
            <html lang="ru">
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Comind AI Native Auth</title>
            <style>
              body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #f4f6fb;
                color: #172033;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }
              main {
                width: min(440px, calc(100% - 32px));
                border: 1px solid #dbe3ef;
                border-radius: 8px;
                background: #fff;
                padding: 28px;
                box-shadow: 0 16px 40px rgba(45, 58, 86, 0.08);
              }
              h1 {
                margin: 0 0 10px;
                font-size: 28px;
                line-height: 1.15;
              }
              p {
                margin: 0 0 20px;
                color: #5f6f8a;
              }
              a {
                display: inline-flex;
                min-height: 44px;
                align-items: center;
                justify-content: center;
                border-radius: 8px;
                background: #315bdc;
                color: #fff;
                padding: 0 16px;
                font-weight: 600;
                text-decoration: none;
              }
            </style>
            <main>
              <h1>Вы вышли</h1>
              <p>Веб-сессия GatewayMCP завершена. Подключенные токены интеграций остались сохранены.</p>
              <a href="/credentials">Войти снова</a>
            </main>
            </html>
            """
        )

    @mcp.custom_route("/auth/yandex/service-login", methods=["GET"], include_in_schema=False)
    async def yandex_service_login(request: Request) -> Response:
        admin_actor = web_actor(request)
        next_url = request.query_params.get("next", "/credentials")
        if admin_actor is None:
            return login_redirect(
                "/auth/yandex/service-login?"
                + urlencode(
                    {
                        "actor_subject": request.query_params.get("actor_subject", ""),
                        "provider": request.query_params.get("provider", "yandex"),
                        "login_hint": request.query_params.get("login_hint", ""),
                        "next": next_url,
                    }
                )
            )
        if not has_scope(admin_actor, "access:admin"):
            return JSONResponse({"ok": False, "error": "missing required scope: access:admin"}, status_code=403)

        actor_subject = request.query_params.get("actor_subject", "").strip()
        if not actor_subject.startswith("service:"):
            return JSONResponse({"ok": False, "error": "actor_subject must start with service:"}, status_code=400)
        login_hint = request.query_params.get("login_hint", "").strip()
        provider = request.query_params.get("provider", "yandex").strip() or "yandex"
        if provider not in {"yandex", "yandex-disk"}:
            return JSONResponse({"ok": False, "error": "unsupported Yandex credential provider"}, status_code=400)

        state = create_oauth_state_payload(
            {
                "flow": "yandex_service_oauth_bind",
                "actor_subject": actor_subject,
                "provider": provider,
                "expected_login": login_hint,
                "admin_subject": admin_actor.subject,
                "next": next_url,
            },
            ttl_seconds=600,
        )
        try:
            if str(request.query_params.get("manual") or "") == "1":
                return RedirectResponse(
                    build_yandex_authorize_url(
                        "",
                        login_hint=login_hint,
                        force_confirm=True,
                        provider=provider,
                        redirect_uri=YANDEX_VERIFICATION_CODE_URL,
                    )
                )
            return RedirectResponse(
                build_yandex_authorize_url(state, login_hint=login_hint, force_confirm=True, provider=provider)
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @mcp.custom_route("/auth/yandex/disk-login", methods=["GET"], include_in_schema=False)
    async def yandex_disk_login(request: Request) -> Response:
        actor = web_actor(request)
        next_url = request.query_params.get("next", "/credentials")
        if actor is None:
            return login_redirect("/auth/yandex/disk-login?" + urlencode({"next": next_url}))

        state = create_oauth_state_payload(
            {
                "flow": "yandex_user_provider_bind",
                "actor_subject": actor.subject,
                "provider": "yandex-disk",
                "expected_login": actor.email or actor.login,
                "next": next_url,
            },
            ttl_seconds=600,
        )
        try:
            if str(request.query_params.get("manual") or "") == "1":
                return RedirectResponse(
                    build_yandex_authorize_url(
                        "",
                        login_hint=actor.email or actor.login,
                        force_confirm=True,
                        provider="yandex-disk",
                        redirect_uri=YANDEX_VERIFICATION_CODE_URL,
                    )
                )
            return RedirectResponse(
                build_yandex_authorize_url(
                    state,
                    login_hint=actor.email or actor.login,
                    force_confirm=True,
                    provider="yandex-disk",
                )
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @mcp.custom_route("/auth/google/login", methods=["GET"], include_in_schema=False)
    async def google_login(request: Request) -> Response:
        actor = web_actor(request)
        next_url = request.query_params.get("next", "/credentials")
        if actor is None:
            return login_redirect("/auth/google/login?" + urlencode({"next": next_url}))

        state = create_oauth_state_payload(
            {
                "flow": "google_user_provider_bind",
                "actor_subject": actor.subject,
                "next": next_url,
            },
            ttl_seconds=600,
        )
        try:
            return RedirectResponse(
                build_google_authorize_url(
                    state,
                    force_confirm=True,
                )
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @mcp.custom_route("/auth/google/callback", methods=["GET"], include_in_schema=False)
    async def google_callback(request: Request) -> Response:
        error = request.query_params.get("error")
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=400)

        state = request.query_params.get("state", "")
        oauth_state = pop_oauth_state(state) if state else None
        if not state or oauth_state is None:
            return JSONResponse({"ok": False, "error": "invalid or expired OAuth state"}, status_code=400)
        if not isinstance(oauth_state, dict) or oauth_state.get("flow") != "google_user_provider_bind":
            return JSONResponse({"ok": False, "error": "invalid Google OAuth state"}, status_code=400)

        code = request.query_params.get("code", "")
        if not code:
            return JSONResponse({"ok": False, "error": "missing OAuth code"}, status_code=400)

        actor_subject = str(oauth_state.get("actor_subject") or "")
        try:
            google_actor = await bind_google_code_to_actor(
                code=code,
                actor_subject=actor_subject,
            )
        except PermissionError as exc:
            audit_event(
                event="credential_save",
                actor=current_actor(),
                decision="deny",
                status="denied",
                system="google",
                error=str(exc),
                arguments={"actor_subject": actor_subject},
            )
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        except Exception as exc:
            audit_event(
                event="credential_save",
                actor=current_actor(),
                decision="deny",
                status="error",
                system="google",
                error=str(exc),
                arguments={"actor_subject": actor_subject},
            )
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

        audit_event(
            event="credential_save",
            actor=google_actor,
            decision="allow",
            status="ok",
            system="google",
            tool="auth.google.login",
            arguments={"provider": "google", "actor_subject": actor_subject},
        )
        next_url = str(oauth_state.get("next") or "/credentials")
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/credentials"
        separator = "&" if "?" in next_url else "?"
        return RedirectResponse(
            f"{next_url}{separator}" + urlencode({"credential_binding": "ok", "provider": "google"}),
            status_code=303,
        )

    @mcp.custom_route("/auth/yandex/callback", methods=["GET"], include_in_schema=False)
    async def yandex_callback(request: Request) -> Response:
        error = request.query_params.get("error")
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=400)

        state = request.query_params.get("state", "")
        oauth_state = pop_oauth_state(state) if state else None
        if not state or oauth_state is None:
            return JSONResponse({"ok": False, "error": "invalid or expired OAuth state"}, status_code=400)

        code = request.query_params.get("code", "")
        if not code:
            return JSONResponse({"ok": False, "error": "missing OAuth code"}, status_code=400)

        try:
            if isinstance(oauth_state, dict) and oauth_state.get("flow") == "yandex_user_provider_bind":
                actor_subject = str(oauth_state.get("actor_subject") or "")
                provider = str(oauth_state.get("provider") or "yandex")
                yandex_actor = await bind_yandex_code_to_actor(
                    code=code,
                    actor_subject=actor_subject,
                    provider=provider,
                    expected_login=str(oauth_state.get("expected_login") or ""),
                )
                audit_event(
                    event="credential_save",
                    actor=yandex_actor,
                    decision="allow",
                    status="ok",
                    system="yandex",
                    tool="auth.yandex.disk-login",
                    arguments={"provider": provider, "actor_subject": actor_subject},
                )
                next_url = str(oauth_state.get("next") or "/credentials")
                if not next_url.startswith("/") or next_url.startswith("//"):
                    next_url = "/credentials"
                separator = "&" if "?" in next_url else "?"
                return RedirectResponse(
                    f"{next_url}{separator}" + urlencode({"credential_binding": "ok", "provider": provider}),
                    status_code=303,
                )

            if isinstance(oauth_state, dict) and oauth_state.get("flow") == "yandex_service_oauth_bind":
                actor_subject = str(oauth_state.get("actor_subject") or "")
                yandex_actor = await bind_yandex_code_to_actor(
                    code=code,
                    actor_subject=actor_subject,
                    provider=str(oauth_state.get("provider") or "yandex"),
                    expected_login=str(oauth_state.get("expected_login") or ""),
                    metadata={"admin_subject": str(oauth_state.get("admin_subject") or "")},
                )
                audit_event(
                    event="credential_save",
                    actor=yandex_actor,
                    decision="allow",
                    status="ok",
                    system="yandex",
                    tool="auth.yandex.service-login",
                    arguments={"provider": str(oauth_state.get("provider") or "yandex"), "actor_subject": actor_subject},
                )
                next_url = str(oauth_state.get("next") or "/credentials")
                if not next_url.startswith("/") or next_url.startswith("//"):
                    next_url = "/credentials"
                separator = "&" if "?" in next_url else "?"
                return RedirectResponse(
                    f"{next_url}{separator}" + urlencode({"service_binding": "ok", "actor_subject": actor_subject}),
                    status_code=303,
                )

            actor, token = await login_with_yandex_code(code)
        except PermissionError as exc:
            audit_event(
                event="login",
                actor=current_actor(),
                decision="deny",
                status="denied",
                error=str(exc),
            )
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        except Exception as exc:
            audit_event(
                event="login",
                actor=current_actor(),
                decision="deny",
                status="error",
                error=exc.__class__.__name__,
            )
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

        audit_event(event="login", actor=actor, decision="allow", status="ok")
        if isinstance(oauth_state, dict) and oauth_state.get("flow") == "mcp_oauth_authorize":
            code = create_mcp_authorization_code(actor, oauth_state)
            redirect_params = {"code": code, "iss": issuer_url()}
            client_state = str(oauth_state.get("client_state") or "")
            if client_state:
                redirect_params["state"] = client_state
            return RedirectResponse(
                build_redirect_uri_with_params(str(oauth_state["redirect_uri"]), redirect_params),
                status_code=303,
            )

        if request.query_params.get("format") == "json":
            return with_gateway_cookie(JSONResponse(
                {
                    "ok": True,
                    "access_token": token,
                    "token_type": "Bearer",
                    "expires_in": token_ttl_seconds(),
                    "actor": actor_payload(actor),
                }
            ), token)

        next_url = str(oauth_state.get("next") or "") if isinstance(oauth_state, dict) else ""
        if next_url.startswith("/") and not next_url.startswith("//"):
            return with_gateway_cookie(RedirectResponse(next_url, status_code=303), token)

        return with_gateway_cookie(RedirectResponse("/credentials", status_code=303), token)

    @mcp.custom_route("/auth/ping", methods=["GET"], include_in_schema=False)
    async def auth_ping(_: Request) -> Response:
        if not auth_enabled():
            return JSONResponse({"ok": True, "auth_enabled": False, "actor": actor_payload(current_actor())})
        return PlainTextResponse("Use the MCP endpoint with Authorization: Bearer <gateway-token>.", status_code=200)
