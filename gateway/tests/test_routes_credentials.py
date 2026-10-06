import asyncio
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
    headers = {}
    cookies = {}

    def __init__(self, *, path_params=None, query_params=None, body: bytes = b"") -> None:
        self.path_params = path_params or {}
        self.query_params = query_params or {}
        self._body = body

    async def body(self) -> bytes:
        return self._body


class CredentialsRouteTests(unittest.TestCase):
    def test_credentials_page_is_russian_and_has_check_buttons(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="u1", email="user@example.com")

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch(
                "gateway_mcp.routes.credentials.list_user_oauth_tokens",
                return_value=[
                    {"provider": "yandex", "connected": True},
                    {
                        "provider": "yandex-disk",
                        "connected": True,
                        "updated_at": "2026-05-07T13:58:42.968150+00:00",
                    },
                    {
                        "provider": "gitlab",
                        "connected": True,
                        "updated_at": "2026-05-07T13:58:42.968150+00:00",
                    },
                    {
                        "provider": "google",
                        "connected": True,
                        "updated_at": "2026-05-07T13:58:42.968150+00:00",
                    },
                    {"provider": "yandex-caldav", "connected": False},
                ],
            ),
        ):
            response = asyncio.run(fake.routes["/credentials"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Comind AI Native Auth", response.body)
        self.assertIn("Мои подключения", response.body)
        self.assertIn('class="app-shell"', response.body)
        self.assertIn('class="credential-grid"', response.body)
        self.assertIn("Проверить Yandex OAuth", response.body)
        self.assertIn("Проверить Tracker", response.body)
        self.assertEqual(response.body.count("Проверить Yandex Disk"), 1)
        self.assertIn("Проверить почту", response.body)
        self.assertIn("Проверить GitLab", response.body)
        self.assertIn("Google Drive и Sheets", response.body)
        self.assertIn("Подключить Google", response.body)
        self.assertIn("Проверить Google", response.body)
        self.assertIn("Удалить Google токен", response.body)
        self.assertIn("Проверить календарь", response.body)
        self.assertIn("Выйти", response.body)
        self.assertIn("Получить код Yandex Disk", response.body)
        self.assertIn("Сохранить Yandex Disk", response.body)
        self.assertIn("Удалить Disk токен", response.body)
        self.assertIn("07.05.2026 13:58 UTC", response.body)
        self.assertNotIn("968150", response.body)

    def test_credentials_page_shows_service_credentials_for_admin(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="admin", email="admin@example.com", scopes=("access:admin",))

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch("gateway_mcp.routes.credentials.list_user_oauth_tokens", return_value=[]),
            patch(
                "gateway_mcp.routes.credentials.list_service_credential_actors",
                return_value=["service:hermes-salesbro"],
            ),
            patch(
                "gateway_mcp.routes.credentials.list_service_oauth_tokens",
                return_value=[
                    {
                        "provider": "yandex-disk",
                        "actor_subject": "service:hermes-salesbro",
                        "connected": True,
                        "email": "sales-assistant@example.com",
                        "updated_at": "2026-05-07T13:58:42+00:00",
                    }
                ],
            ),
        ):
            response = asyncio.run(fake.routes["/credentials"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Сервисные аккаунты", response.body)
        self.assertIn("service:hermes-salesbro", response.body)
        self.assertIn("sales-assistant@example.com", response.body)
        self.assertIn("Yandex Disk", response.body)
        self.assertIn("Получить код Disk", response.body)
        self.assertIn("Сохранить Disk", response.body)
        self.assertIn("Отозвать Disk", response.body)

    def test_save_yandex_disk_manual_code_binds_current_user(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="yandex:1", email="user@example.com")
        yandex_actor = GatewayActor(subject="yandex:2", email="user@example.com")

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch("gateway_mcp.routes.credentials.bind_yandex_code_to_actor", return_value=yandex_actor) as bind,
            patch("gateway_mcp.routes.credentials.audit_event"),
        ):
            response = asyncio.run(
                fake.routes["/credentials/yandex-disk/manual"]["func"](FakeRequest(body=b"code=manual-code"))
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("credential_binding=ok", response.url)
        self.assertEqual(bind.call_args.kwargs["code"], "manual-code")
        self.assertEqual(bind.call_args.kwargs["actor_subject"], "yandex:1")
        self.assertEqual(bind.call_args.kwargs["provider"], "yandex-disk")
        self.assertEqual(bind.call_args.kwargs["expected_login"], "user@example.com")

    def test_save_service_yandex_manual_code_requires_admin_and_binds_service(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        admin = GatewayActor(subject="admin", email="admin@example.com", scopes=("access:admin",))
        yandex_actor = GatewayActor(subject="yandex:2", email="sales-assistant@example.com")
        body = (
            b"actor_subject=service%3Ahermes-salesbro&provider=yandex-disk&"
            b"login_hint=sales-assistant%40example.com&code=manual-code"
        )

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=admin),
            patch("gateway_mcp.routes.credentials.bind_yandex_code_to_actor", return_value=yandex_actor) as bind,
            patch("gateway_mcp.routes.credentials.audit_event"),
        ):
            response = asyncio.run(fake.routes["/credentials/service/yandex/manual"]["func"](FakeRequest(body=body)))

        self.assertEqual(response.status_code, 303)
        self.assertIn("service_binding=ok", response.url)
        self.assertEqual(bind.call_args.kwargs["actor_subject"], "service:hermes-salesbro")
        self.assertEqual(bind.call_args.kwargs["provider"], "yandex-disk")
        self.assertEqual(bind.call_args.kwargs["expected_login"], "sales-assistant@example.com")

    def test_delete_service_yandex_credential_requires_admin(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="u1", email="user@example.com")

        with patch("gateway_mcp.routes.credentials.web_actor", return_value=actor):
            response = asyncio.run(
                fake.routes["/credentials/service/yandex/delete"]["func"](
                    FakeRequest(body=b"actor_subject=service%3Ahermes-salesbro")
                )
            )

        self.assertEqual(response.status_code, 403)

    def test_delete_service_yandex_credential_revokes_admin_token(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="admin", email="admin@example.com", scopes=("access:admin",))

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch("gateway_mcp.routes.credentials.revoke_user_oauth_token", return_value=True) as revoke,
            patch("gateway_mcp.routes.credentials.audit_event"),
        ):
            response = asyncio.run(
                fake.routes["/credentials/service/yandex/delete"]["func"](
                    FakeRequest(body=b"actor_subject=service%3Ahermes-salesbro&provider=yandex-disk")
                )
            )

        self.assertEqual(response.status_code, 303)
        revoke.assert_called_once_with("yandex-disk", "service:hermes-salesbro")

    def test_delete_yandex_disk_credential_revokes_current_user_token(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="yandex:1", email="user@example.com")

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch("gateway_mcp.routes.credentials.revoke_user_oauth_token", return_value=True) as revoke,
            patch("gateway_mcp.routes.credentials.audit_event"),
        ):
            response = asyncio.run(fake.routes["/credentials/yandex-disk/delete"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 303)
        revoke.assert_called_once_with("yandex-disk", "yandex:1")

    def test_delete_google_credential_revokes_current_user_token(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="yandex:1", email="user@example.com")

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch("gateway_mcp.routes.credentials.revoke_user_oauth_token", return_value=True) as revoke,
            patch("gateway_mcp.routes.credentials.audit_event"),
        ):
            response = asyncio.run(fake.routes["/credentials/google/delete"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 303)
        revoke.assert_called_once_with("google", "yandex:1")

    def test_check_route_redirects_with_result_message(self) -> None:
        from gateway_mcp.routes.credentials import register_credentials_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_credentials_routes(fake)
        actor = GatewayActor(subject="u1", email="user@example.com")

        with (
            patch("gateway_mcp.routes.credentials.web_actor", return_value=actor),
            patch(
                "gateway_mcp.routes.credentials.run_credential_check",
                return_value={"ok": True, "message": "GitLab токен работает."},
            ),
            patch("gateway_mcp.routes.credentials.audit_event"),
        ):
            response = asyncio.run(
                fake.routes["/credentials/check/{provider}"]["func"](
                    FakeRequest(path_params={"provider": "gitlab"})
                )
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("/credentials?", response.url)
        self.assertIn("checked=gitlab", response.url)
        self.assertIn("ok=1", response.url)

    def test_yandex_check_reports_missing_token(self) -> None:
        from gateway_mcp.services.credential_checks import check_yandex_credential
        from gateway_mcp.services.policy import GatewayActor

        with patch("gateway_mcp.services.credential_checks.get_user_oauth_token", return_value=None):
            result = asyncio.run(check_yandex_credential(GatewayActor(subject="u1")))

        self.assertFalse(result["ok"])
        self.assertIn("Yandex OAuth токен не найден", result["message"])

    def test_google_check_refreshes_token(self) -> None:
        from gateway_mcp.services.credential_checks import check_google_credential
        from gateway_mcp.services.policy import GatewayActor

        with (
            patch(
                "gateway_mcp.services.credential_checks.get_user_oauth_token",
                return_value={"access_token": "google-refresh-token", "email": "user@example.com"},
            ),
            patch(
                "gateway_mcp.services.credential_checks.refresh_google_access_token",
                return_value={"access_token": "google-access-token"},
            ) as refresh,
            patch(
                "gateway_mcp.services.credential_checks.fetch_google_user_info",
                return_value={"email": "user@example.com"},
            ) as user_info,
        ):
            result = asyncio.run(check_google_credential(GatewayActor(subject="yandex:1")))

        self.assertTrue(result["ok"])
        self.assertIn("user@example.com", result["message"])
        refresh.assert_called_once_with("google-refresh-token")
        user_info.assert_called_once_with("google-access-token")


if __name__ == "__main__":
    unittest.main()
