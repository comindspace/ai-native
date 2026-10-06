import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.tools.notifications import register_notification_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class NotificationToolTests(unittest.TestCase):
    def test_publish_requires_scope_and_returns_notification(self) -> None:
        fake = FakeMcp()
        register_notification_tools(fake)
        run = Mock()
        run.require_scope.return_value = GatewayActor(
            subject="u1", scopes=("notifications:write",)
        )
        with (
            patch(
                "gateway_mcp.tools.notifications.ToolRun.start",
                return_value=run,
            ),
            patch(
                "gateway_mcp.tools.notifications.publish_notification",
                return_value={"notification_id": "n1", "inserted": True},
            ),
        ):
            raw = asyncio.run(
                fake.tools["gateway_notification_publish"](
                    event_type="work.completed",
                    title="Готово",
                    recipients_json='[{"type":"user","key":"u2"}]',
                )
            )

        self.assertEqual(json.loads(raw)["notification"]["notification_id"], "n1")
        run.require_scope.assert_called_once()
        run.finish.assert_called_once_with(status="created")

    def test_list_returns_only_service_result(self) -> None:
        fake = FakeMcp()
        register_notification_tools(fake)
        run = Mock()
        run.require_scope.return_value = GatewayActor(
            subject="u1", scopes=("notifications:read",)
        )
        with (
            patch(
                "gateway_mcp.tools.notifications.ToolRun.start",
                return_value=run,
            ),
            patch(
                "gateway_mcp.tools.notifications.list_visible_notifications",
                return_value={"count": 1, "unread_count": 1, "notifications": []},
            ),
        ):
            raw = asyncio.run(fake.tools["gateway_notifications_list"]())

        self.assertEqual(json.loads(raw)["count"], 1)
        run.require_scope.assert_called_once()


if __name__ == "__main__":
    unittest.main()
