import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

ROOT = Path(__file__).resolve().parents[1]


class ApprovalStorageTests(unittest.TestCase):
    def test_consumed_event_is_allowed_by_migration(self) -> None:
        migration = (
            ROOT / "migrations" / "0017_approval_consumed_event.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("approval_events_event_type_check", migration)
        self.assertIn("'consumed'", migration)

    def test_decision_update_is_atomic_and_expiry_safe(self) -> None:
        from gateway_mcp.services import storage_approvals

        cursor = MagicMock()
        cursor.fetchone.return_value = None
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_approvals.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_approvals.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_approvals._connect",
                return_value=connection,
            ),
        ):
            result = storage_approvals.update_approval_decision(
                approval_id="apr-1",
                status="approved",
                decided_by="user:reviewer",
                actor_groups=["architects"],
                comment="ok",
                decision_payload={},
            )

        self.assertIsNone(result)
        sql = cursor.execute.call_args_list[0].args[0]
        self.assertIn("status in ('pending', 'need_info')", sql)
        self.assertIn("expires_at is null or expires_at > now()", sql)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_consumption_locks_and_records_one_execution(self) -> None:
        from gateway_mcp.services import storage_approvals

        approval = {
            "approval_id": "apr-1",
            "status": "approved",
            "consumption_key": "",
            "expires_at": None,
        }
        consumed = {
            **approval,
            "consumption_key": "same-call",
            "consumed_by": "service:release-agent",
        }
        cursor = MagicMock()
        cursor.fetchone.side_effect = [approval, consumed]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_approvals.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_approvals.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_approvals._connect",
                return_value=connection,
            ),
        ):
            result = storage_approvals.consume_approval_request(
                approval_id="apr-1",
                actor_subject="service:release-agent",
                action="gitlab.pipeline_jobs.play",
                consumption_key="same-call",
                invocation_hash="abc",
            )

        self.assertEqual(result["consumption_key"], "same-call")
        self.assertIn("for update", cursor.execute.call_args_list[0].args[0])
        self.assertEqual(cursor.execute.call_count, 3)
        connection.commit.assert_called_once()

    def test_consumed_approval_cannot_execute_again(self) -> None:
        from gateway_mcp.services import storage_approvals

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "approval_id": "apr-1",
            "status": "approved",
            "consumption_key": "first-call",
            "expires_at": None,
        }
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor

        with (
            patch(
                "gateway_mcp.services.storage_approvals.postgres_enabled",
                return_value=True,
            ),
            patch("gateway_mcp.services.storage_approvals.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_approvals._connect",
                return_value=connection,
            ),
        ):
            result = storage_approvals.consume_approval_request(
                approval_id="apr-1",
                actor_subject="service:release-agent",
                action="gitlab.pipeline_jobs.play",
                consumption_key="first-call",
                invocation_hash="abc",
            )

        self.assertIsNone(result)
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
