import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import notification_worker


class NotificationWorkerTests(unittest.TestCase):
    def test_worker_is_idle_without_private_key(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(notification_worker, "claim_notification_deliveries") as claim,
        ):
            result = notification_worker.run_once()

        self.assertEqual(result, {"claimed": 0, "sent": 0, "retried": 0, "failed": 0})
        claim.assert_not_called()

    def test_worker_completes_successful_delivery(self) -> None:
        delivery = {"id": 7, "notification_id": "n1"}
        with (
            patch.dict(
                os.environ,
                {"GATEWAY_WEB_PUSH_VAPID_PRIVATE_KEY": "private"},
                clear=True,
            ),
            patch.object(
                notification_worker,
                "claim_notification_deliveries",
                return_value=[delivery],
            ),
            patch.object(notification_worker, "_send_delivery") as send,
            patch.object(
                notification_worker, "complete_notification_delivery"
            ) as complete,
        ):
            result = notification_worker.run_once()

        self.assertEqual(result["sent"], 1)
        send.assert_called_once()
        complete.assert_called_once_with(7)

    def test_worker_disables_expired_push_endpoint(self) -> None:
        class GoneError(Exception):
            response = type("Response", (), {"status_code": 410})()

        delivery = {"id": 8, "notification_id": "n2"}
        with (
            patch.dict(
                os.environ,
                {"GATEWAY_WEB_PUSH_VAPID_PRIVATE_KEY": "private"},
                clear=True,
            ),
            patch.object(
                notification_worker,
                "claim_notification_deliveries",
                return_value=[delivery],
            ),
            patch.object(
                notification_worker, "_send_delivery", side_effect=GoneError()
            ),
            patch.object(notification_worker, "fail_notification_delivery") as fail,
        ):
            result = notification_worker.run_once()

        self.assertEqual(result["failed"], 1)
        fail.assert_called_once_with(
            delivery_id=8,
            error_code="http_410",
            permanent=True,
            disable_subscription=True,
        )

    def test_push_payload_contains_unique_tag_without_project_metadata(self) -> None:
        delivery = {
            "notification_id": "n-secret",
            "event_type": "review.requested",
            "project_id": "secret-project",
            "priority": "urgent",
            "endpoint": "https://push.example/subscription",
            "p256dh": "public-key",
            "auth_secret": "auth-secret",
        }
        webpush = Mock()
        with patch.dict(
            "sys.modules", {"pywebpush": SimpleNamespace(webpush=webpush)}
        ):
            notification_worker._send_delivery(
                delivery,
                private_key="private",
                subject="mailto:admin@example.com",
            )

        payload = json.loads(webpush.call_args.kwargs["data"])
        self.assertEqual(
            payload,
            {
                "title": "GatewayMCP",
                "body": "Новое уведомление в рабочем центре.",
                "url": "/notifications",
                "tag": "n-secret",
            },
        )


if __name__ == "__main__":
    unittest.main()
