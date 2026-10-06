import unittest
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.storage_notifications import (
    _enqueue_delivery_sql,
    list_notifications,
    mark_notifications_read,
)


class NotificationStorageTests(unittest.TestCase):
    def test_list_visibility_is_parameterized_by_current_actor(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor

        with (
            patch("gateway_mcp.services.storage_notifications._require_postgres"),
            patch("gateway_mcp.services.storage_notifications.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_notifications._connect",
                return_value=connection,
            ),
        ):
            list_notifications(
                actor_subject="yandex:42",
                actor_aliases=["yandex:42", "employee@comind.space"],
                actor_groups=["employees"],
                unread_only=True,
                event_type="work.completed",
                project_id="acme",
                limit=20,
            )

        statement, params = cursor.execute.call_args.args
        normalized = " ".join(statement.split()).casefold()
        self.assertIn("notification_topic_subscriptions", normalized)
        self.assertIn("visible_recipient.recipient_type = 'user'", normalized)
        self.assertIn("receipt.read_at is null", normalized)
        self.assertEqual(
            params,
            [
                "yandex:42",
                ["yandex:42", "employee@comind.space"],
                ["employees"],
                "yandex:42",
                "work.completed",
                "acme",
                20,
            ],
        )

    def test_delivery_outbox_matches_users_groups_and_project_topics(self) -> None:
        cursor = MagicMock()

        _enqueue_delivery_sql(cursor, notification_id="notification-1")

        statement, params = cursor.execute.call_args.args
        normalized = " ".join(statement.split()).casefold()
        self.assertIn("insert into notification_deliveries", normalized)
        self.assertIn("push_subscriptions", normalized)
        self.assertIn("notification_topic_subscriptions", normalized)
        self.assertIn("on conflict do nothing", normalized)
        self.assertEqual(params, ["notification-1"])

    def test_mark_read_updates_only_service_authorized_ids(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.rowcount = 275
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor

        with (
            patch("gateway_mcp.services.storage_notifications._require_postgres"),
            patch("gateway_mcp.services.storage_notifications.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_notifications._connect",
                return_value=connection,
            ),
        ):
            changed = mark_notifications_read(
                actor_subject="yandex:42",
                notification_ids=["n2", "n1", "n2"],
            )

        statement, params = cursor.execute.call_args.args
        normalized = " ".join(statement.split()).casefold()
        self.assertIn("insert into notification_receipts", normalized)
        self.assertIn("n.notification_id = any", normalized)
        self.assertIn("on conflict", normalized)
        self.assertNotIn("limit", normalized)
        self.assertEqual(params, ("yandex:42", ["n1", "n2"]))
        self.assertEqual(changed, 275)
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
