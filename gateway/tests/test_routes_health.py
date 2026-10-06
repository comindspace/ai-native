import asyncio
import os
import unittest
from unittest.mock import Mock, patch

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


class HealthRouteTests(unittest.TestCase):
    def test_healthz_returns_ok_when_postgres_disabled(self) -> None:
        from gateway_mcp.routes.health import register_health_routes

        fake = FakeMcp()
        register_health_routes(fake)

        with (
            patch(
                "gateway_mcp.routes.health.storage_health",
                return_value={"enabled": False},
            ),
            patch("gateway_mcp.routes.health.auth_enabled", return_value=True),
            patch.dict(os.environ, {"GATEWAY_RELEASE_SHA": "abc123"}),
        ):
            response = asyncio.run(fake.routes["/healthz"]["func"](Mock()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body["ok"], True)
        self.assertEqual(response.body["auth_enabled"], True)
        self.assertEqual(response.body["release_sha"], "abc123")

    def test_healthz_returns_503_when_postgres_unhealthy(self) -> None:
        from gateway_mcp.routes.health import register_health_routes

        fake = FakeMcp()
        register_health_routes(fake)

        with (
            patch(
                "gateway_mcp.routes.health.storage_health",
                return_value={"enabled": True, "ok": False},
            ),
            patch("gateway_mcp.routes.health.auth_enabled", return_value=False),
        ):
            response = asyncio.run(fake.routes["/healthz"]["func"](Mock()))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.body["ok"], False)
