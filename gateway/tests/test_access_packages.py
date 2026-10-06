import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.access_admin import (
    admin_grant_access_package,
    admin_revoke_access_package,
)
from gateway_mcp.services.access_packages import access_package_catalog
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.tools.access import register_access_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class AccessPackageTests(unittest.TestCase):
    def test_catalog_has_versioned_roles_without_wildcard_scope(self) -> None:
        packages = access_package_catalog()

        self.assertGreaterEqual(len(packages), 5)
        self.assertIn("project-manager", {item["key"] for item in packages})
        self.assertTrue(all(int(item["version"]) >= 1 for item in packages))
        self.assertTrue(all("*" not in item["scopes"] for item in packages))

    def test_grant_dry_run_expands_role_without_storage_write(self) -> None:
        actor = GatewayActor(subject="admin:roman", scopes=("access:admin",))
        with patch(
            "gateway_mcp.services.access_admin.insert_access_bundle"
        ) as insert:
            result = admin_grant_access_package(
                subject_type="user",
                subject_key="Employee@Comind.Space",
                package_key="developer",
                reason="Project onboarding",
                actor=actor,
                ttl_days=90,
                dry_run=True,
            )

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["package"]["subject_key"], "employee@comind.space")
        self.assertIn("gitlab:write", result["package"]["scopes"])
        insert.assert_not_called()

    def test_revoke_dry_run_does_not_touch_individual_grants(self) -> None:
        actor = GatewayActor(subject="admin:roman", scopes=("access:admin",))
        with patch(
            "gateway_mcp.services.access_admin.revoke_access_bundle"
        ) as revoke:
            result = admin_revoke_access_package(
                actor=actor,
                bundle_id="bundle-1",
                dry_run=True,
            )

        self.assertEqual(result, {"dry_run": True, "bundle_id": "bundle-1"})
        revoke.assert_not_called()

    def test_catalog_tool_requires_access_scope_and_returns_packages(self) -> None:
        fake = FakeMcp()
        register_access_tools(fake)
        run = Mock()

        with patch("gateway_mcp.tools.access.ToolRun.start", return_value=run):
            raw = asyncio.run(
                fake.tools["gateway_admin_access_package_catalog"]()
            )

        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["count"], 0)
        run.require_scope.assert_called_once()


if __name__ == "__main__":
    unittest.main()
