import unittest
from pathlib import Path


class NotificationMigrationTests(unittest.TestCase):
    def test_notification_schema_has_durable_inbox_and_postgres_outbox(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0018_employee_notifications.sql"
        ).read_text(encoding="utf-8")

        for table in (
            "notification_events",
            "notification_recipients",
            "notification_receipts",
            "notification_topic_subscriptions",
            "push_subscriptions",
            "notification_deliveries",
        ):
            self.assertIn(f"create table {table}", migration)
        self.assertIn("unique (notification_id, subscription_id)", migration)
        self.assertIn("status in ('pending', 'retry', 'sending')", migration)


if __name__ == "__main__":
    unittest.main()
