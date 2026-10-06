import unittest
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()


class AccessPackageStorageTests(unittest.TestCase):
    def test_revoke_package_updates_only_linked_grants_in_one_transaction(self) -> None:
        from gateway_mcp.services import storage_access

        cursor = MagicMock()
        cursor.fetchall.side_effect = [[{"id": 1}], [{"id": 2}]]
        cursor.fetchone.return_value = {"id": "bundle-1", "package_key": "developer"}
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.transaction.return_value.__enter__.return_value = None
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_access.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_access.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_access._connect",
                return_value=connection,
            ),
        ):
            result = storage_access.revoke_access_bundle(
                bundle_id="bundle-1",
                actor_subject="admin:roman",
            )

        self.assertEqual(result["scope_grant_ids"], [1])
        self.assertEqual(result["resource_grant_ids"], [2])
        sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertEqual(sql.count("where bundle_id = %s"), 2)
        self.assertIn("where id = %s and revoked_at is null", sql)


if __name__ == "__main__":
    unittest.main()
