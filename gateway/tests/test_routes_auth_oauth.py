import asyncio
import base64
import hashlib
import socket
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods, include_in_schema=False):
        def decorator(func):
            self.routes[path] = {
                "func": func,
                "methods": methods,
                "include_in_schema": include_in_schema,
            }
            return func

        return decorator


class FakeRequest:
    method = "GET"

    def __init__(
        self,
        *,
        method: str = "GET",
        body: bytes = b"",
        json_body=None,
        query_params=None,
    ) -> None:
        self.method = method
        self._body = body
        self._json_body = json_body
        self.query_params = query_params or {}
        self.cookies = {}

    async def body(self) -> bytes:
        return self._body

    async def json(self):
        return self._json_body


class AuthOAuthRouteTests(unittest.TestCase):
    def test_authorization_server_metadata_is_json(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)

        with patch.dict("os.environ", {}, clear=True):
            response = asyncio.run(
                fake.routes["/.well-known/oauth-authorization-server"]["func"](
                    FakeRequest()
                )
            )
            openid_response = asyncio.run(
                fake.routes["/.well-known/openid-configuration"]["func"](
                    FakeRequest()
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorization_endpoint", response.body)
        self.assertIn("token_endpoint", response.body)
        self.assertIn("registration_endpoint", response.body)
        self.assertIn("revocation_endpoint", response.body)
        self.assertIn("refresh_token", response.body["grant_types_supported"])
        self.assertNotIn("client_id_metadata_document_supported", response.body)
        self.assertEqual(response.body, openid_response.body)

    def test_cimd_can_be_advertised_explicitly_on_both_discovery_routes(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)

        with patch.dict("os.environ", {"GATEWAY_CIMD_ENABLED": "true"}, clear=True):
            authorization_metadata = asyncio.run(
                fake.routes["/.well-known/oauth-authorization-server"]["func"](
                    FakeRequest()
                )
            )
            openid_metadata = asyncio.run(
                fake.routes["/.well-known/openid-configuration"]["func"](FakeRequest())
            )

        self.assertIs(
            authorization_metadata.body["client_id_metadata_document_supported"],
            True,
        )
        self.assertEqual(authorization_metadata.body, openid_metadata.body)

    def test_gateway_token_ttl_defaults_to_one_year(self) -> None:
        from gateway_mcp.services import auth

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(auth.token_ttl_seconds(), 31536000)

        with patch.dict("os.environ", {"GATEWAY_TOKEN_TTL_SECONDS": "60"}):
            self.assertEqual(auth.token_ttl_seconds(), 60)

    def test_dynamic_client_registration_returns_public_client(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)

        with patch("gateway_mcp.services.auth.jwt.encode", return_value="encoded-client"):
            response = asyncio.run(
                fake.routes["/oauth/register"]["func"](
                    FakeRequest(method="POST", json_body={"redirect_uris": ["http://127.0.0.1/callback"]})
                )
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.body["token_endpoint_auth_method"], "none")
        self.assertEqual(response.body["client_id"], "gateway-client.encoded-client")
        self.assertIn("refresh_token", response.body["grant_types"])

    def test_discovery_dcr_and_authorize_work_as_one_flow(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)
        redirect_uri = "http://127.0.0.1:43110/callback"
        environment = {
            "GATEWAY_CIMD_ENABLED": "false",
            "GATEWAY_JWT_SECRET": "test-secret-long-enough-for-oauth",
            "GATEWAY_PUBLIC_URL": "https://gateway.example",
            "GATEWAY_ISSUER_URL": "https://gateway.example",
            "GATEWAY_RESOURCE_URL": "https://gateway.example/mcp",
        }
        signed_payloads = {}

        def encode(payload, key, algorithm="HS256"):
            token = f"signed-{len(signed_payloads) + 1}"
            signed_payloads[token] = payload
            return token

        def decode(token, key, algorithms=None, options=None):
            return signed_payloads[token]

        with (
            patch.dict("os.environ", environment, clear=True),
            patch("gateway_mcp.services.auth.jwt.encode", side_effect=encode),
            patch("gateway_mcp.services.auth.jwt.decode", side_effect=decode),
            patch(
                "gateway_mcp.services.auth.build_yandex_authorize_url",
                return_value="https://oauth.yandex.example/authorize",
            ),
            patch("gateway_mcp.services.auth.fetch_oauth_client_metadata") as fetch,
        ):
            discovery = asyncio.run(
                fake.routes["/.well-known/oauth-authorization-server"]["func"](
                    FakeRequest()
                )
            )
            registration = asyncio.run(
                fake.routes["/oauth/register"]["func"](
                    FakeRequest(
                        method="POST",
                        json_body={
                            "client_name": "Claude Code",
                            "application_type": "native",
                            "redirect_uris": [redirect_uri],
                        },
                    )
                )
            )
            client_id = registration.body["client_id"]
            authorization_params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": "test-pkce-challenge",
                "code_challenge_method": "S256",
                "resource": "https://gateway.example/mcp",
            }
            authorization = asyncio.run(
                fake.routes["/oauth/authorize"]["func"](
                    FakeRequest(query_params=authorization_params)
                )
            )
            rejected = asyncio.run(
                fake.routes["/oauth/authorize"]["func"](
                    FakeRequest(
                        query_params={
                            **authorization_params,
                            "redirect_uri": "http://127.0.0.1:43111/callback",
                        }
                    )
                )
            )

        self.assertNotIn("client_id_metadata_document_supported", discovery.body)
        self.assertEqual(registration.status_code, 201)
        self.assertTrue(client_id.startswith("gateway-client."))
        self.assertEqual(authorization.status_code, 307, authorization.body)
        self.assertEqual(
            authorization.url, "https://oauth.yandex.example/authorize"
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn(
            "redirect_uri is not registered", rejected.body["error_description"]
        )
        fetch.assert_not_called()

    def test_cimd_client_validates_metadata_redirect_uri(self) -> None:
        from gateway_mcp.services import auth

        client_id = "https://client.example/oauth/metadata.json"
        metadata = {
            "client_id": client_id,
            "client_name": "Example MCP Client",
            "redirect_uris": ["http://127.0.0.1/callback"],
        }

        with (
            patch.dict("os.environ", {"GATEWAY_CIMD_ENABLED": "true"}),
            patch(
                "gateway_mcp.services.auth.fetch_oauth_client_metadata",
                return_value=metadata,
            ),
        ):
            result = asyncio.run(
                auth.validate_oauth_redirect_uri(
                    client_id, "http://127.0.0.1/callback"
                )
            )

        self.assertEqual(result, metadata)

    def test_cimd_client_rejects_unregistered_redirect_uri(self) -> None:
        from gateway_mcp.services import auth

        client_id = "https://client.example/oauth/metadata.json"
        metadata = {
            "client_id": client_id,
            "client_name": "Example MCP Client",
            "redirect_uris": ["http://127.0.0.1/callback"],
        }

        with (
            patch.dict("os.environ", {"GATEWAY_CIMD_ENABLED": "true"}),
            patch(
                "gateway_mcp.services.auth.fetch_oauth_client_metadata",
                return_value=metadata,
            ),
            self.assertRaisesRegex(ValueError, "redirect_uri is not registered"),
        ):
            asyncio.run(
                auth.validate_oauth_redirect_uri(
                    client_id, "http://localhost/callback"
                )
            )

    def test_cimd_client_is_rejected_when_capability_is_disabled(self) -> None:
        from gateway_mcp.services import auth

        with (
            patch.dict(
                "os.environ", {"GATEWAY_CIMD_ENABLED": "false"}, clear=True
            ),
            patch("gateway_mcp.services.auth.fetch_oauth_client_metadata") as fetch,
            self.assertRaisesRegex(ValueError, "CIMD client registration is disabled"),
        ):
            asyncio.run(
                auth.validate_oauth_redirect_uri(
                    "https://client.example/oauth/metadata.json",
                    "http://127.0.0.1/callback",
                )
            )

        fetch.assert_not_called()

    def test_cimd_rejects_private_network_targets(self) -> None:
        from gateway_mcp.services import auth

        address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        with patch("gateway_mcp.services.auth.socket.getaddrinfo", return_value=[address]):
            with self.assertRaisesRegex(ValueError, "public addresses"):
                auth._validate_cimd_host("metadata.example")

    def test_token_endpoint_exchanges_authorization_code(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)
        form = (
            "grant_type=authorization_code&code=code-1&client_id=client-1&"
            "redirect_uri=http%3A%2F%2F127.0.0.1%2Fcallback&code_verifier=verifier"
        ).encode()

        with patch(
            "gateway_mcp.routes.auth.exchange_mcp_authorization_code",
            return_value={"access_token": "token", "token_type": "Bearer", "expires_in": 60, "scope": "skills:read"},
        ) as exchange:
            response = asyncio.run(fake.routes["/oauth/token"]["func"](FakeRequest(method="POST", body=form)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body["access_token"], "token")
        self.assertEqual(exchange.call_args.kwargs["code"], "code-1")
        self.assertEqual(exchange.call_args.kwargs["client_id"], "client-1")

    def test_token_endpoint_rotates_refresh_token(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)
        form = (
            "grant_type=refresh_token&refresh_token=gateway-refresh.old&"
            "client_id=client-1&resource=https%3A%2F%2Fgateway.example%2Fmcp"
        ).encode()

        with patch(
            "gateway_mcp.routes.auth.exchange_mcp_refresh_token",
            return_value={
                "access_token": "access-new",
                "refresh_token": "gateway-refresh.new",
                "token_type": "Bearer",
                "expires_in": 60,
                "scope": "tools:call",
            },
        ) as exchange:
            response = asyncio.run(
                fake.routes["/oauth/token"]["func"](
                    FakeRequest(method="POST", body=form)
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body["refresh_token"], "gateway-refresh.new")
        exchange.assert_called_once_with(
            refresh_token="gateway-refresh.old",
            client_id="client-1",
            resource="https://gateway.example/mcp",
        )

    def test_revocation_endpoint_is_idempotent(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)
        form = "token=gateway-refresh.old".encode()

        with patch("gateway_mcp.routes.auth.revoke_mcp_oauth_token") as revoke:
            response = asyncio.run(
                fake.routes["/oauth/revoke"]["func"](
                    FakeRequest(method="POST", body=form)
                )
            )

        self.assertEqual(response.status_code, 200)
        revoke.assert_called_once_with("gateway-refresh.old")

    def test_mcp_authorization_callback_returns_issuer(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)
        request = FakeRequest()
        request.query_params = {"state": "oauth-state", "code": "yandex-code"}
        oauth_state = {
            "flow": "mcp_oauth_authorize",
            "client_id": "client-1",
            "redirect_uri": "http://127.0.0.1/callback",
            "client_state": "client-state",
            "code_challenge": "challenge",
        }
        actor = GatewayActor(subject="yandex:1", email="user@example.com")

        with (
            patch("gateway_mcp.routes.auth.pop_oauth_state", return_value=oauth_state),
            patch("gateway_mcp.routes.auth.login_with_yandex_code", return_value=(actor, "token")),
            patch("gateway_mcp.routes.auth.create_mcp_authorization_code", return_value="gateway-code"),
            patch("gateway_mcp.routes.auth.issuer_url", return_value="https://gateway.example"),
        ):
            response = asyncio.run(fake.routes["/auth/yandex/callback"]["func"](request))

        location = response.url
        self.assertIn("code=gateway-code", location)
        self.assertIn("state=client-state", location)
        self.assertIn("iss=https%3A%2F%2Fgateway.example", location)

    def test_yandex_login_defaults_to_credentials_page(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)

        with (
            patch("gateway_mcp.routes.auth.create_oauth_state", return_value="state-1") as create_state,
            patch("gateway_mcp.routes.auth.build_yandex_authorize_url", return_value="https://oauth.example/auth") as build_url,
        ):
            response = asyncio.run(fake.routes["/auth/yandex/login"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.url, "https://oauth.example/auth")
        create_state.assert_called_once_with("/credentials")
        self.assertTrue(build_url.call_args.kwargs["force_confirm"])

    def test_logout_clears_gateway_cookie(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)

        response = asyncio.run(fake.routes["/auth/logout"]["func"](FakeRequest(method="POST")))

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.url, "/auth/logged-out")
        self.assertEqual(response.deleted_cookies[0]["key"], "gateway_token")
        self.assertEqual(response.deleted_cookies[0]["path"], "/")
        self.assertEqual(response.deleted_cookies[0]["samesite"], "lax")

    def test_logged_out_page_has_login_link(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes

        fake = FakeMcp()
        register_auth_routes(fake)

        response = asyncio.run(fake.routes["/auth/logged-out"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Вы вышли", response.body)
        self.assertIn("/credentials", response.body)

    def test_yandex_service_login_requires_admin_and_builds_oauth_state(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)

        request = FakeRequest()
        request.query_params = {
            "actor_subject": "service:hermes-salesbro",
            "next": "/credentials",
            "provider": "yandex-disk",
            "login_hint": "sales-assistant@example.com",
        }
        admin = GatewayActor(subject="yandex:1", email="admin@example.com", scopes=("access:admin",))
        with (
            patch("gateway_mcp.routes.auth.web_actor", return_value=admin),
            patch("gateway_mcp.routes.auth.create_oauth_state_payload", return_value="state-1") as create_state,
            patch("gateway_mcp.routes.auth.build_yandex_authorize_url", return_value="https://oauth.example/auth") as build_url,
        ):
            response = asyncio.run(fake.routes["/auth/yandex/service-login"]["func"](request))

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.url, "https://oauth.example/auth")
        self.assertEqual(create_state.call_args.args[0]["flow"], "yandex_service_oauth_bind")
        self.assertEqual(create_state.call_args.args[0]["actor_subject"], "service:hermes-salesbro")
        self.assertEqual(create_state.call_args.args[0]["provider"], "yandex-disk")
        self.assertEqual(create_state.call_args.args[0]["expected_login"], "sales-assistant@example.com")
        self.assertEqual(build_url.call_args.kwargs["provider"], "yandex-disk")
        self.assertEqual(build_url.call_args.kwargs["login_hint"], "sales-assistant@example.com")
        self.assertTrue(build_url.call_args.kwargs["force_confirm"])

    def test_yandex_service_callback_binds_token_to_service_actor(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)

        request = FakeRequest()
        request.query_params = {"state": "state-1", "code": "code-1"}
        yandex_actor = GatewayActor(subject="yandex:2", email="service@example.com")
        with (
            patch(
                "gateway_mcp.routes.auth.pop_oauth_state",
                return_value={
                    "flow": "yandex_service_oauth_bind",
                    "actor_subject": "service:hermes-salesbro",
                    "provider": "yandex-disk",
                    "expected_login": "sales-assistant@example.com",
                    "admin_subject": "yandex:1",
                    "next": "/credentials",
                },
            ),
            patch("gateway_mcp.routes.auth.bind_yandex_code_to_actor", return_value=yandex_actor) as bind,
            patch("gateway_mcp.routes.auth.audit_event"),
        ):
            response = asyncio.run(fake.routes["/auth/yandex/callback"]["func"](request))

        self.assertEqual(response.status_code, 303)
        self.assertIn("service_binding=ok", response.url)
        bind.assert_called_once()
        self.assertEqual(bind.call_args.kwargs["code"], "code-1")
        self.assertEqual(bind.call_args.kwargs["actor_subject"], "service:hermes-salesbro")
        self.assertEqual(bind.call_args.kwargs["provider"], "yandex-disk")
        self.assertEqual(bind.call_args.kwargs["expected_login"], "sales-assistant@example.com")

    def test_yandex_disk_login_binds_current_user_disk_provider(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)
        actor = GatewayActor(subject="yandex:1", email="user@example.com", login="user")

        with (
            patch("gateway_mcp.routes.auth.web_actor", return_value=actor),
            patch("gateway_mcp.routes.auth.create_oauth_state_payload", return_value="state-1") as create_state,
            patch("gateway_mcp.routes.auth.build_yandex_authorize_url", return_value="https://oauth.example/auth") as build_url,
        ):
            response = asyncio.run(fake.routes["/auth/yandex/disk-login"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 307)
        self.assertEqual(create_state.call_args.args[0]["flow"], "yandex_user_provider_bind")
        self.assertEqual(create_state.call_args.args[0]["actor_subject"], "yandex:1")
        self.assertEqual(create_state.call_args.args[0]["provider"], "yandex-disk")
        self.assertEqual(build_url.call_args.kwargs["provider"], "yandex-disk")
        self.assertEqual(build_url.call_args.kwargs["login_hint"], "user@example.com")

    def test_yandex_user_provider_callback_binds_token(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)
        request = FakeRequest()
        request.query_params = {"state": "state-1", "code": "code-1"}
        yandex_actor = GatewayActor(subject="yandex:1", email="user@example.com")

        with (
            patch(
                "gateway_mcp.routes.auth.pop_oauth_state",
                return_value={
                    "flow": "yandex_user_provider_bind",
                    "actor_subject": "yandex:1",
                    "provider": "yandex-disk",
                    "expected_login": "user@example.com",
                    "next": "/credentials",
                },
            ),
            patch("gateway_mcp.routes.auth.bind_yandex_code_to_actor", return_value=yandex_actor) as bind,
            patch("gateway_mcp.routes.auth.audit_event"),
        ):
            response = asyncio.run(fake.routes["/auth/yandex/callback"]["func"](request))

        self.assertEqual(response.status_code, 303)
        self.assertIn("credential_binding=ok", response.url)
        bind.assert_called_once()
        self.assertEqual(bind.call_args.kwargs["actor_subject"], "yandex:1")
        self.assertEqual(bind.call_args.kwargs["provider"], "yandex-disk")

    def test_google_login_binds_current_user_provider(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)
        actor = GatewayActor(subject="yandex:1", email="user@example.com", login="user")

        with (
            patch("gateway_mcp.routes.auth.web_actor", return_value=actor),
            patch("gateway_mcp.routes.auth.create_oauth_state_payload", return_value="state-1") as create_state,
            patch("gateway_mcp.routes.auth.build_google_authorize_url", return_value="https://accounts.example/auth") as build_url,
        ):
            response = asyncio.run(fake.routes["/auth/google/login"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 307)
        self.assertEqual(create_state.call_args.args[0]["flow"], "google_user_provider_bind")
        self.assertEqual(create_state.call_args.args[0]["actor_subject"], "yandex:1")
        self.assertNotIn("expected_login", create_state.call_args.args[0])
        self.assertNotIn("login_hint", build_url.call_args.kwargs)
        self.assertTrue(build_url.call_args.kwargs["force_confirm"])

    def test_google_callback_binds_token(self) -> None:
        from gateway_mcp.routes.auth import register_auth_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_auth_routes(fake)
        request = FakeRequest()
        request.query_params = {"state": "state-1", "code": "code-1"}
        google_actor = GatewayActor(subject="google:1", email="user@example.com")

        with (
            patch(
                "gateway_mcp.routes.auth.pop_oauth_state",
                return_value={
                    "flow": "google_user_provider_bind",
                    "actor_subject": "yandex:1",
                    "next": "/credentials",
                },
            ),
            patch("gateway_mcp.routes.auth.bind_google_code_to_actor", return_value=google_actor) as bind,
            patch("gateway_mcp.routes.auth.audit_event"),
        ):
            response = asyncio.run(fake.routes["/auth/google/callback"]["func"](request))

        self.assertEqual(response.status_code, 303)
        self.assertIn("credential_binding=ok", response.url)
        self.assertIn("provider=google", response.url)
        bind.assert_called_once()
        self.assertEqual(bind.call_args.kwargs["actor_subject"], "yandex:1")
        self.assertNotIn("expected_login", bind.call_args.kwargs)

    def test_google_authorize_url_requests_offline_consent(self) -> None:
        from gateway_mcp.services import auth

        with (
            patch("gateway_mcp.services.auth.os.getenv") as getenv,
            patch("gateway_mcp.services.auth.public_url", return_value="https://gateway.example"),
        ):
            getenv.side_effect = lambda key, default="": {
                "GOOGLE_OAUTH_CLIENT_ID": "client-1",
                "GOOGLE_OAUTH_SCOPES": "openid email profile https://www.googleapis.com/auth/spreadsheets",
            }.get(key, default)
            url = auth.build_google_authorize_url(
                "state-1",
                login_hint="user@example.com",
                force_confirm=True,
            )

        self.assertIn("login_hint=user%40example.com", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertIn("scope=openid+email+profile+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fspreadsheets", url)

    def test_google_binding_stores_refresh_token(self) -> None:
        from gateway_mcp.services import auth

        with (
            patch(
                "gateway_mcp.services.auth.exchange_google_code",
                return_value={
                    "access_token": "google-access-token",
                    "refresh_token": "google-refresh-token",
                    "token_type": "Bearer",
                    "scope": "openid email https://www.googleapis.com/auth/spreadsheets",
                },
            ),
            patch(
                "gateway_mcp.services.auth.fetch_google_user_info",
                return_value={"sub": "42", "email": "user@example.com"},
            ) as fetch_user,
            patch("gateway_mcp.services.auth.save_user_oauth_token") as save_token,
        ):
            actor = asyncio.run(
                auth.bind_google_code_to_actor(
                    code="code-1",
                    actor_subject="yandex:1",
                    expected_login="other-gateway-login@example.com",
                )
            )

        self.assertEqual(actor.subject, "google:42")
        fetch_user.assert_called_once_with("google-access-token")
        self.assertEqual(save_token.call_args.kwargs["provider"], "google")
        self.assertEqual(save_token.call_args.kwargs["actor_subject"], "yandex:1")
        self.assertEqual(save_token.call_args.kwargs["access_token"], "google-refresh-token")
        self.assertEqual(save_token.call_args.kwargs["token_type"], "RefreshToken")

    def test_yandex_authorize_url_can_force_account_selection(self) -> None:
        from gateway_mcp.services import auth

        with (
            patch("gateway_mcp.services.auth.os.getenv") as getenv,
            patch("gateway_mcp.services.auth.public_url", return_value="https://gateway.example"),
        ):
            getenv.side_effect = lambda key, default="": {
                "YANDEX_DISK_OAUTH_CLIENT_ID": "client-1",
                "YANDEX_DISK_OAUTH_SCOPES": "cloud_api:disk.read",
            }.get(key, default)
            url = auth.build_yandex_authorize_url(
                "state-1",
                login_hint="sales-assistant@example.com",
                force_confirm=True,
                provider="yandex-disk",
            )

        self.assertIn("login_hint=sales-assistant%40example.com", url)
        self.assertIn("force_confirm=yes", url)

    def test_service_binding_rejects_unexpected_yandex_account(self) -> None:
        from gateway_mcp.services import auth
        from gateway_mcp.services.policy import GatewayActor

        with (
            patch(
                "gateway_mcp.services.auth.exchange_yandex_code",
                return_value={"access_token": "ya-token", "token_type": "OAuth"},
            ),
            patch(
                "gateway_mcp.services.auth.fetch_yandex_disk_user_info",
                return_value={"id": "1", "login": "roman@example.com", "email": "roman@example.com"},
            ),
            patch("gateway_mcp.services.auth.is_user_allowed", return_value=True),
            patch("gateway_mcp.services.auth.save_user_oauth_token") as save_token,
        ):
            with self.assertRaises(PermissionError):
                asyncio.run(
                    auth.bind_yandex_code_to_actor(
                        code="code-1",
                        actor_subject="service:hermes-salesbro",
                        provider="yandex-disk",
                        expected_login="sales-assistant@example.com",
                    )
                )

        save_token.assert_not_called()

    def test_disk_provider_binding_uses_disk_user_info(self) -> None:
        from gateway_mcp.services import auth

        with (
            patch(
                "gateway_mcp.services.auth.exchange_yandex_code",
                return_value={"access_token": "ya-token", "token_type": "OAuth", "scope": "cloud_api:disk.read"},
            ),
            patch(
                "gateway_mcp.services.auth.fetch_yandex_disk_user_info",
                return_value={"id": "42", "login": "sales-assistant@comind.space", "email": "sales-assistant@comind.space"},
            ) as fetch_disk,
            patch("gateway_mcp.services.auth.fetch_yandex_user_info") as fetch_user,
            patch("gateway_mcp.services.auth.save_user_oauth_token") as save_token,
        ):
            actor = asyncio.run(
                auth.bind_yandex_code_to_actor(
                    code="code-1",
                    actor_subject="service:hermes-salesbro",
                    provider="yandex-disk",
                    expected_login="sales-assistant@comind.space",
                )
            )

        self.assertEqual(actor.subject, "yandex:42")
        fetch_disk.assert_called_once_with("ya-token")
        fetch_user.assert_not_called()
        self.assertEqual(save_token.call_args.kwargs["provider"], "yandex-disk")
        self.assertEqual(save_token.call_args.kwargs["actor_subject"], "service:hermes-salesbro")

    def test_authorization_code_exchange_validates_pkce_and_returns_gateway_token(self) -> None:
        from gateway_mcp.services import auth
        from gateway_mcp.services.policy import GatewayActor

        verifier = "correct-horse-battery-staple"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        actor = GatewayActor(subject="yandex:1", email="user@example.com", scopes=("skills:read", "tools:call"))

        auth._OAUTH_STATES.clear()
        with (
            patch("gateway_mcp.services.auth.save_postgres_oauth_state", return_value=False),
            patch("gateway_mcp.services.auth.pop_postgres_oauth_state", return_value=None),
        ):
            code = auth.create_mcp_authorization_code(
                actor,
                {
                    "client_id": "client-1",
                    "redirect_uri": "http://127.0.0.1/callback",
                    "code_challenge": challenge,
                    "resource": "http://localhost:8000/mcp",
                },
            )
            response = auth.exchange_mcp_authorization_code(
                code=code,
                client_id="client-1",
                redirect_uri="http://127.0.0.1/callback",
                code_verifier=verifier,
                resource="http://localhost:8000/mcp",
            )

        self.assertEqual(response["access_token"], "test.jwt.token")
        self.assertEqual(response["token_type"], "Bearer")
        self.assertEqual(response["scope"], "skills:read tools:call")
        self.assertTrue(response["refresh_token"].startswith("gateway-refresh."))

    def test_refresh_token_rotates_and_cannot_be_reused(self) -> None:
        from gateway_mcp.services import auth
        from gateway_mcp.services.policy import GatewayActor

        actor = GatewayActor(
            subject="yandex:1",
            email="employee@comind.space",
            scopes=("skills:read",),
        )
        auth._OAUTH_REFRESH_TOKENS.clear()
        with (
            patch(
                "gateway_mcp.services.auth.save_gateway_oauth_refresh_token",
                return_value=False,
            ),
            patch(
                "gateway_mcp.services.auth.consume_gateway_oauth_refresh_token",
                return_value=None,
            ),
            patch("gateway_mcp.services.auth.is_user_allowed", return_value=True),
            patch("gateway_mcp.services.auth.actor_from_user_info", return_value=actor),
            patch(
                "gateway_mcp.services.auth.mint_gateway_token",
                side_effect=["access-1", "access-2"],
            ),
        ):
            issued = auth._issue_oauth_tokens(
                actor=actor,
                client_id="client-1",
                resource="http://localhost:8000/mcp",
            )
            refreshed = auth.exchange_mcp_refresh_token(
                refresh_token=issued["refresh_token"],
                client_id="client-1",
                resource="http://localhost:8000/mcp",
            )
            with self.assertRaisesRegex(ValueError, "invalid or expired"):
                auth.exchange_mcp_refresh_token(
                    refresh_token=issued["refresh_token"],
                    client_id="client-1",
                    resource="http://localhost:8000/mcp",
                )

        self.assertEqual(issued["access_token"], "access-1")
        self.assertEqual(refreshed["access_token"], "access-2")
        self.assertNotEqual(issued["refresh_token"], refreshed["refresh_token"])

    def test_revoked_access_token_is_rejected(self) -> None:
        from gateway_mcp.services import auth
        from gateway_mcp.services.policy import GatewayActor

        actor = GatewayActor(subject="yandex:1", email="employee@comind.space")
        claims = {"jti": "jti-1", "exp": 9999999999, "sub": actor.subject}
        auth._REVOKED_ACCESS_TOKENS.clear()
        with (
            patch(
                "gateway_mcp.services.auth.decode_gateway_token",
                return_value=claims,
            ),
            patch(
                "gateway_mcp.services.auth.revoke_gateway_oauth_access_token",
                return_value=False,
            ),
            patch(
                "gateway_mcp.services.auth.gateway_oauth_access_token_revoked",
                return_value=False,
            ),
            patch("gateway_mcp.services.auth.actor_from_claims", return_value=actor),
        ):
            auth.revoke_mcp_oauth_token("access-token")
            with self.assertRaisesRegex(PermissionError, "revoked"):
                auth.verify_gateway_token_claims("access-token")

    def test_dynamic_registration_rejects_non_loopback_http_redirect(self) -> None:
        from gateway_mcp.services import auth

        with self.assertRaisesRegex(ValueError, "HTTPS"):
            auth.register_oauth_client(
                {"redirect_uris": ["http://example.com/oauth/callback"]}
            )

    def test_dynamic_registration_accepts_allowlisted_cursor_redirect(self) -> None:
        from gateway_mcp.services import auth

        redirect_uris = [
            "cursor://anysphere.cursor-mcp/oauth/callback",
            "https://www.cursor.com/agents/mcp/oauth/callback",
            "http://localhost:8787/callback",
        ]
        with patch.dict(
            "os.environ",
            {"GATEWAY_OAUTH_ALLOWED_CUSTOM_SCHEMES": "cursor"},
            clear=True,
        ):
            client = auth.register_oauth_client({"redirect_uris": redirect_uris})

        self.assertEqual(client["redirect_uris"], redirect_uris)

    def test_dynamic_registration_rejects_cursor_redirect_by_default(self) -> None:
        from gateway_mcp.services import auth

        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaisesRegex(ValueError, "HTTPS"),
        ):
            auth.register_oauth_client(
                {"redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"]}
            )

    def test_mcp_auth_metadata_uses_supported_scopes(self) -> None:
        from gateway_mcp.services import auth

        settings = auth.mcp_auth_settings()

        self.assertIsNone(settings)
        with patch("gateway_mcp.services.auth.auth_enabled", return_value=True):
            settings = auth.mcp_auth_settings()

        self.assertEqual(settings.required_scopes, auth.supported_scopes())
        self.assertIn("tools:call", settings.required_scopes)

    def test_gateway_token_verifier_allows_transport_but_keeps_claim_scopes_separate(self) -> None:
        from gateway_mcp.services import auth

        verifier = auth.GatewayJwtVerifier()
        with patch(
            "gateway_mcp.services.auth.decode_gateway_token",
            return_value={
                "sub": "user-1",
                "exp": 9999999999,
                "aud": "http://localhost:8000/mcp",
                "scope": "skills:read",
            },
        ):
            access_token = asyncio.run(verifier.verify_token("token"))

        self.assertEqual(access_token.client_id, "user-1")
        self.assertIn("skills:read", access_token.scopes)
        self.assertIn("tools:call", access_token.scopes)


if __name__ == "__main__":
    unittest.main()
