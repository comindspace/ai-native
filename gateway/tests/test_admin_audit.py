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

    def __init__(self, query_params=None) -> None:
        self.query_params = query_params or {}


class AdminAuditRouteTests(unittest.TestCase):
    def test_audit_page_requires_access_admin(self) -> None:
        from gateway_mcp.routes.admin_audit import register_admin_audit_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_audit_routes(fake)
        actor = GatewayActor(subject="u1", scopes=("telemetry:read",))

        with patch("gateway_mcp.routes.admin_audit.web_actor", return_value=actor):
            response = asyncio.run(fake.routes["/admin/audit"]["func"](FakeRequest()))

        self.assertEqual(response.status_code, 403)

    def test_audit_page_filters_and_never_renders_payload(self) -> None:
        from gateway_mcp.routes.admin_audit import register_admin_audit_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_audit_routes(fake)
        actor = GatewayActor(subject="admin", scopes=("access:admin",))
        rows = [
            {
                "id": index,
                "created_at": "2026-08-17T10:00:00+00:00",
                "actor_subject": "yandex:<admin>",
                "system": "1c",
                "event": "resource_access",
                "tool": "1c.odata.query",
                "decision": "deny",
                "status": "blocked",
                "scope": "1c:read",
                "gateway_request_id": "0123456789abcdef",
                "payload": {"arguments": {"password": "raw-secret"}},
            }
            for index in range(51)
        ]
        request = FakeRequest(
            {
                "days": "30",
                "actor_subject": "yandex:<admin>",
                "system": "1c",
                "event": "resource_access",
                "tool": "1c.odata.query",
                "decision": "deny",
                "status": "blocked",
                "gateway_request_id": "0123456789abcdef",
                "page": "2",
            }
        )

        with (
            patch("gateway_mcp.routes.admin_audit.web_actor", return_value=actor),
            patch(
                "gateway_mcp.routes.admin_audit.list_audit_events",
                return_value=rows,
            ) as search,
        ):
            response = asyncio.run(fake.routes["/admin/audit"]["func"](request))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Журнал событий", response.body)
        self.assertIn("yandex:&lt;admin&gt;", response.body)
        self.assertIn("0123456789abcdef", response.body)
        self.assertIn("Страница 2", response.body)
        self.assertIn("page=3", response.body)
        self.assertNotIn("raw-secret", response.body)
        self.assertNotIn("password", response.body)
        search.assert_called_once_with(
            days=30,
            actor_subject="yandex:<admin>",
            event="resource_access",
            tool="1c.odata.query",
            system="1c",
            decision="deny",
            status="blocked",
            gateway_request_id="0123456789abcdef",
            limit=51,
            offset=50,
            include_payload=False,
        )


if __name__ == "__main__":
    unittest.main()
