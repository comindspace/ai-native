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
    headers = {}
    cookies = {}

    def __init__(self, query_params=None) -> None:
        self.query_params = query_params or {}


class AdminTelemetryRouteTests(unittest.TestCase):
    def test_page_requires_admin(self) -> None:
        from gateway_mcp.routes.admin_telemetry import register_admin_telemetry_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_telemetry_routes(fake)
        with patch(
            "gateway_mcp.routes.admin_telemetry.web_actor",
            return_value=GatewayActor(subject="u1", scopes=("telemetry:read",)),
        ):
            response = asyncio.run(
                fake.routes["/admin/telemetry/skills"]["func"](FakeRequest())
            )
        self.assertEqual(response.status_code, 403)

    def test_page_renders_filtered_skill_metrics_without_prompt_content(self) -> None:
        from gateway_mcp.routes.admin_telemetry import register_admin_telemetry_routes
        from gateway_mcp.services.policy import GatewayActor

        fake = FakeMcp()
        register_admin_telemetry_routes(fake)
        request = FakeRequest(
            {
                "days": "7",
                "skill_id": "treasury-payments",
                "skill_pack": "acme-core",
                "agent": "claude",
                "actor_subject": "yandex:user",
            }
        )
        rows = [
            {
                "skill_id": "treasury-payments",
                "skill_pack": "acme-core",
                "skill_version": "0.16.0",
                "agent": "claude",
                "project": "acme",
                "started_count": 10,
                "completed_count": 8,
                "failed_count": 2,
                "abandoned_count": 0,
                "running_count": 0,
                "active_users": 3,
                "success_rate": 80.0,
                "p50_duration_ms": 1200,
                "p95_duration_ms": 4200,
                "last_seen_at": "2026-09-02T10:00:00+00:00",
                "prompt": "must-not-render",
            }
        ]
        with (
            patch(
                "gateway_mcp.routes.admin_telemetry.web_actor",
                return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
            ),
            patch(
                "gateway_mcp.routes.admin_telemetry.skill_stats",
                return_value={"skills": rows},
            ) as stats,
        ):
            response = asyncio.run(
                fake.routes["/admin/telemetry/skills"]["func"](request)
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Метрики навыков", response.body)
        self.assertIn("treasury-payments", response.body)
        self.assertIn("80.0%", response.body)
        self.assertNotIn("must-not-render", response.body)
        stats.assert_called_once_with(
            limit=250,
            days=7,
            agent="claude",
            skill_id="treasury-payments",
            skill_pack="acme-core",
            skill_version="",
            project="",
            actor_subject="yandex:user",
        )


if __name__ == "__main__":
    unittest.main()
