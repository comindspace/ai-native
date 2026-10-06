import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.routes import admin_factory_connections as ui
from gateway_mcp.services.policy import GatewayActor

ADMIN = GatewayActor(subject="admin", scopes=("factory:admin",))


class Mcp:
    def custom_route(self, *args, **kwargs):
        def register(func):
            self.page = func
            return func

        return register


class Request:
    def __init__(self, method="GET", values=None, cookies=None):
        self.method = method
        self.headers = {}
        self.cookies = cookies or {}
        self.query_params = {}
        self.data = urlencode(values or {}).encode()

    async def stream(self):
        yield self.data


class AdminFactoryTests(unittest.TestCase):
    def setUp(self):
        self.mcp = Mcp()
        ui.register_admin_factory_connection_routes(self.mcp)

    def test_missing_admin_denied(self):
        with patch.object(
            ui,
            "web_actor",
            return_value=GatewayActor(subject="employee", scopes=("factory:write",)),
        ):
            response = asyncio.run(self.mcp.page(Request()))
            self.assertEqual(response.status_code, 403)

    def test_post_csrf_denied(self):
        with (
            patch.object(ui, "web_actor", return_value=ADMIN),
            patch.object(ui.service, "save_connection") as save,
        ):
            response = asyncio.run(self.mcp.page(Request("POST", {"action": "save"})))
            self.assertEqual(response.status_code, 403)
            save.assert_not_called()

    def test_cross_origin_denied_even_with_csrf(self):
        request = Request("POST", {"csrf": "test"}, {ui.COOKIE: "test"})
        request.headers = {"origin": "https://untrusted.example"}
        with (
            patch.object(ui, "web_actor", return_value=ADMIN),
            patch.object(ui.service, "save_connection") as save,
        ):
            response = asyncio.run(self.mcp.page(request))
            self.assertEqual(response.status_code, 403)
            save.assert_not_called()

    def test_secret_only_received_on_post(self):
        values = {
            "csrf": "test",
            "action": "save",
            "reference": "gitlab:test",
            "version": "0",
            "api_url": "https://git.example/api/v4",
            "username": "oauth2",
            "token": "no-leak-secret",
            "repositories": "a/b",
        }
        with (
            patch.object(ui, "web_actor", return_value=ADMIN),
            patch.object(ui.service, "save_connection") as save,
        ):
            response = asyncio.run(
                self.mcp.page(Request("POST", values, {ui.COOKIE: "test"}))
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(save.call_args.kwargs["token"], "no-leak-secret")
            self.assertNotIn("no-leak-secret", str(response.headers))

    def test_failure_never_echoes_exception(self):
        values = {
            "csrf": "test",
            "action": "save",
            "reference": "gitlab:test",
            "version": "0",
        }
        with (
            patch.object(ui, "web_actor", return_value=ADMIN),
            patch.object(
                ui.service,
                "save_connection",
                side_effect=RuntimeError("secret-in-driver-error"),
            ),
            patch.object(ui, "audit_event") as audit,
        ):
            response = asyncio.run(
                self.mcp.page(Request("POST", values, {ui.COOKIE: "test"}))
            )
            self.assertNotIn("secret-in-driver-error", str(response.headers))
            self.assertNotIn("secret-in-driver-error", str(audit.call_args))

    def test_bind_calls_existing_registration_workflow(self):
        values = {
            "csrf": "test",
            "action": "bind",
            "reference": "gitlab:test",
            "version": "3",
            "project_id": "p",
            "idempotency_key": "test-key",
        }
        row = {"revision": 3, "config": {"project_id": "p", "project_path": "a/b"}}
        with (
            patch.object(ui, "web_actor", return_value=ADMIN),
            patch.object(ui.storage_factory, "get_project", return_value=row),
            patch.object(
                ui,
                "upsert_project",
                new=AsyncMock(
                    return_value={
                        "validation": {
                            "ready": False,
                            "readiness_gaps": ["authentication"],
                        }
                    }
                ),
            ) as upsert,
        ):
            response = asyncio.run(
                self.mcp.page(Request("POST", values, {ui.COOKIE: "test"}))
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(
                upsert.call_args.kwargs["config"]["gitlab_connection_id"], "gitlab:test"
            )
            self.assertIn("authentication", str(response.headers))
            self.assertEqual(upsert.call_args.kwargs["expected_revision"], 3)

    def test_render_has_blank_secret_and_escaped_values(self):
        card = {
            "connection_id": "gitlab:test",
            "api_url": "https://git.example/api/v4",
            "username": "<script>alert(1)</script>",
            "version": 2,
            "state": "active",
            "token_configured": True,
            "payload": {"GITLAB_TOKEN": "never-render-me"},
            "repositories": ["a/b"],
        }
        html = ui.render_body([card], [], "csrf", "gitlab:test")
        self.assertNotIn("never-render-me", html)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn('type="password" name="token" value=""', html)
        self.assertIn("Настроить", html)
        self.assertIn("Проверить", html)
