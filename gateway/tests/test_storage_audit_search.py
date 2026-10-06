import unittest
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()


class AuditSearchStorageTests(unittest.TestCase):
    def test_request_id_offset_and_payload_projection_are_safe(self) -> None:
        from gateway_mcp.services import storage_audit

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "id": 8,
                "gateway_request_id": "0123456789abcdef",
                "event": "resource_access",
            }
        ]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_audit.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_audit.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_audit._connect",
                return_value=connection,
            ),
        ):
            result = storage_audit.list_audit_events(
                days=30,
                gateway_request_id="0123456789abcdef",
                limit=51,
                offset=100,
                include_payload=False,
            )

        self.assertEqual(result[0]["gateway_request_id"], "0123456789abcdef")
        sql, params = cursor.execute.call_args.args
        self.assertIn("payload #>> '{arguments,gateway_request_id}' = %s", sql)
        self.assertIn("as gateway_request_id", sql)
        self.assertNotIn(", payload\n", sql)
        self.assertIn("limit %s offset %s", sql)
        self.assertEqual(params, [30, "0123456789abcdef", 51, 100])


if __name__ == "__main__":
    unittest.main()
