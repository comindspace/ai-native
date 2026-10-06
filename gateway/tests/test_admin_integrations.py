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
            self.routes[path] = {"func": func, "methods": methods}
            return func

        return decorator


class FakeRequest:
    def __init__(self, query_params=None) -> None:
        self.query_params = query_params or {}
        self.headers = {}
        self.cookies = {}
        self.path_params = {}

    async def body(self) -> bytes:
        return b""


class AdminIntegrationRouteTests(unittest.TestCase):
    def test_page_requires_admin(self) -> None:
        from gateway_mcp.routes.admin_integrations import (
            register_admin_integration_routes,
        )
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_integration_routes(fake)
        with patch(
            "gateway_mcp.routes.admin_integrations.web_actor",
            return_value=GatewayActor(subject="u1", scopes=("tools:read",)),
        ):
            response = asyncio.run(
                fake.routes["/admin/integrations"]["func"](FakeRequest())
            )
        self.assertEqual(response.status_code, 403)

    def test_page_renders_status_without_secret_payload(self) -> None:
        from gateway_mcp.routes.admin_integrations import (
            register_admin_integration_routes,
        )
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_integration_routes(fake)
        statuses = [
            {
                "system": "bitrix24",
                "label": "Bitrix24",
                "description": "CRM",
                "state": "active",
                "source": "admin",
                "configured": True,
                "configured_fields": ["BITRIX24_WEBHOOK_URL"],
                "version": 2,
                "last_check_message": "Подключение работает.",
                "last_checked_at": "2026-09-04T10:00:00+00:00",
                "raw_secret": "must-not-render",
            }
        ]
        with (
            patch(
                "gateway_mcp.routes.admin_integrations.web_actor",
                return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
            ),
            patch(
                "gateway_mcp.routes.admin_integrations.integration_statuses",
                return_value=statuses,
            ),
            patch(
                "gateway_mcp.routes.admin_integrations.safe_field_value",
                return_value="https://crm.example/rest/1/***",
            ),
        ):
            response = asyncio.run(
                fake.routes["/admin/integrations"]["func"](FakeRequest())
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Интеграции", response.body)
        self.assertIn('class="integration-list"', response.body)
        self.assertIn('class="integration-item"', response.body)
        self.assertNotIn('class="integration-grid"', response.body)
        self.assertIn("Bitrix24", response.body)
        self.assertNotIn("must-not-render", response.body)
        self.assertNotIn("top-secret", response.body)

    def test_optional_missing_is_not_an_issue_and_unchecked_is_not_verified(
        self,
    ) -> None:
        from gateway_mcp.routes.admin_integrations import (
            register_admin_integration_routes,
        )
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_integration_routes(fake)
        statuses = [
            {
                "system": "bitrix24",
                "state": "active",
                "source": "environment",
                "last_check_ok": None,
            },
            {
                "system": "gitlab",
                "state": "missing",
                "source": "missing",
                "last_check_ok": None,
            },
        ]
        with (
            patch(
                "gateway_mcp.routes.admin_integrations.web_actor",
                return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
            ),
            patch(
                "gateway_mcp.routes.admin_integrations.integration_statuses",
                return_value=statuses,
            ),
            patch(
                "gateway_mcp.routes.admin_integrations.safe_field_value",
                return_value="",
            ),
        ):
            response = asyncio.run(
                fake.routes["/admin/integrations"]["func"](FakeRequest())
            )
        self.assertIn("Настроено", response.body)
        self.assertIn("не настроено", response.body)
        self.assertIn("Требуют внимания", response.body)
        self.assertIn('<span class="status neutral">не настроено</span>', response.body)
        self.assertNotIn('<span class="status ok">работает</span>', response.body)


if __name__ == "__main__":
    unittest.main()
