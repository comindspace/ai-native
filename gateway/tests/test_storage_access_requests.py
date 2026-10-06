import unittest
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()


class AccessRequestStorageTests(unittest.TestCase):
    def test_insert_reuses_pending_or_processing_request(self) -> None:
        from gateway_mcp.services import storage_access_requests

        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            None,
            {"id": "request-1", "status": "processing"},
        ]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_access_requests.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_access_requests.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_access_requests._connect",
                return_value=connection,
            ),
        ):
            result = storage_access_requests.insert_access_request(
                requester_subject="yandex:42",
                requester_email="employee@comind.space",
                subject_key="employee@comind.space",
                package_key="developer",
                package_version=2,
                reason="Project role",
                requested_ttl_days=90,
                idempotency_key="",
            )

        insert_sql = cursor.execute.call_args_list[0].args[0]
        fallback_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("status in ('pending', 'processing')", insert_sql)
        self.assertIn("do nothing", insert_sql)
        self.assertIn("status in ('pending', 'processing')", fallback_sql)
        self.assertEqual(result["status"], "processing")

    def test_cancel_filters_by_owner_and_pending_status(self) -> None:
        from gateway_mcp.services import storage_access_requests

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "id": "request-1",
            "requester_subject": "yandex:42",
            "status": "cancelled",
        }
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_access_requests.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_access_requests.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_access_requests._connect",
                return_value=connection,
            ),
        ):
            result = storage_access_requests.cancel_access_request(
                request_id="request-1",
                requester_subject="yandex:42",
                reason="No longer needed",
            )

        sql, params = cursor.execute.call_args.args
        self.assertIn("requester_subject = %s", sql)
        self.assertIn("status = 'pending'", sql)
        self.assertEqual(params, ("No longer needed", "request-1", "yandex:42"))
        self.assertEqual(result["status"], "cancelled")

    def test_decision_is_applied_only_to_pending_request(self) -> None:
        from gateway_mcp.services import storage_access_requests

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "id": "request-1",
            "status": "approved",
            "grant_bundle_id": "bundle-1",
        }
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_access_requests.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_access_requests.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_access_requests._connect",
                return_value=connection,
            ),
        ):
            result = storage_access_requests.decide_access_request(
                request_id="request-1",
                decision="approved",
                decided_by="admin:roman",
                decision_reason="Confirmed",
                grant_bundle_id="bundle-1",
            )

        sql = cursor.execute.call_args.args[0]
        self.assertIn("status = 'processing'", sql)
        self.assertIn("decided_by = %s", sql)
        self.assertEqual(result["status"], "approved")


if __name__ == "__main__":
    unittest.main()
