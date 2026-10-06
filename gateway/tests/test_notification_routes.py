import asyncio
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.routes.notifications import register_notification_routes
from gateway_mcp.services.policy import GatewayActor


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods, include_in_schema=False):
        def decorator(func):
            self.routes[path] = {"func": func, "methods": methods}
            return func

        return decorator


class FakeRequest:
    def __init__(
        self,
        *,
        query_params=None,
        path_params=None,
        headers=None,
        json_body=None,
    ) -> None:
        self.query_params = query_params or {}
        self.path_params = path_params or {}
        self.headers = headers or {}
        self.cookies = {}
        self._json_body = json_body or {}

    async def json(self):
        return self._json_body

    async def body(self):
        return b"{}"


class NotificationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeMcp()
        register_notification_routes(self.fake)
        self.actor = GatewayActor(
            subject="yandex:42",
            email="employee@comind.space",
            scopes=("notifications:read",),
        )

    def test_page_redirects_to_login(self) -> None:
        with patch("gateway_mcp.routes.notifications.web_actor", return_value=None):
            response = asyncio.run(
                self.fake.routes["/notifications"]["func"](FakeRequest())
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("next=/notifications", response.url)

    def test_page_renders_only_current_actor_notifications(self) -> None:
        item = {
            "notification_id": "n1",
            "title": "MR готов",
            "body": "Можно проводить ревью",
            "event_type": "work.completed",
            "priority": "normal",
            "project_id": "acme",
            "created_by": "service:factory",
            "created_at": "2026-09-11T10:00:00+00:00",
            "action_url": "https://gitlab.example/mr/1",
            "read_at": None,
        }
        with (
            patch(
                "gateway_mcp.routes.notifications.web_actor", return_value=self.actor
            ),
            patch("gateway_mcp.routes.notifications.has_scope", return_value=True),
            patch(
                "gateway_mcp.routes.notifications.list_visible_notifications",
                return_value={"notifications": [item], "unread_count": 1},
            ),
            patch("gateway_mcp.routes.notifications.push_enabled", return_value=True),
        ):
            response = asyncio.run(
                self.fake.routes["/notifications"]["func"](FakeRequest())
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("MR готов", response.body)
        self.assertIn("employee@comind.space", response.body)
        self.assertIn("от service:factory", response.body)
        self.assertIn("Системные уведомления", response.body)
        self.assertIn(">Включить</button>", response.body)
        self.assertIn('id="push-test"', response.body)
        self.assertIn("registration.showNotification", response.body)
        self.assertIn("[hidden] { display: none !important; }", response.body)
        self.assertIn("max-height: clamp(360px, 58vh, 720px)", response.body)
        self.assertIn("overflow-y: auto", response.body)
        self.assertIn("Comind AI Native", response.body)
        self.assertNotIn("Проектные подписки", response.body)
        self.assertNotIn("/admin/audit", response.body)

    def test_api_rejects_invalid_limit(self) -> None:
        with (
            patch(
                "gateway_mcp.routes.notifications.web_actor", return_value=self.actor
            ),
            patch("gateway_mcp.routes.notifications.has_scope", return_value=True),
        ):
            response = asyncio.run(
                self.fake.routes["/notifications/api"]["func"](
                    FakeRequest(query_params={"limit": "many"})
                )
            )

        self.assertEqual(response.status_code, 400)

    def test_state_change_requires_csrf(self) -> None:
        with (
            patch(
                "gateway_mcp.routes.notifications.web_actor", return_value=self.actor
            ),
            patch("gateway_mcp.routes.notifications.has_scope", return_value=True),
            patch("gateway_mcp.routes.notifications.verify_csrf", return_value=False),
        ):
            response = asyncio.run(
                self.fake.routes["/notifications/{notification_id}/state"]["func"](
                    FakeRequest(
                        path_params={"notification_id": "n1"},
                        json_body={"state": "read"},
                    )
                )
            )

        self.assertEqual(response.status_code, 403)

    def test_invalid_state_returns_bad_request(self) -> None:
        with (
            patch(
                "gateway_mcp.routes.notifications.web_actor", return_value=self.actor
            ),
            patch("gateway_mcp.routes.notifications.has_scope", return_value=True),
            patch("gateway_mcp.routes.notifications.verify_csrf", return_value=True),
            patch(
                "gateway_mcp.routes.notifications.acknowledge_notification",
                side_effect=ValueError("state must be seen, read, or unread"),
            ),
        ):
            response = asyncio.run(
                self.fake.routes["/notifications/{notification_id}/state"]["func"](
                    FakeRequest(
                        path_params={"notification_id": "n1"},
                        json_body={"state": "invalid"},
                    )
                )
            )

        self.assertEqual(response.status_code, 400)

    def test_project_subscription_denial_is_forbidden(self) -> None:
        with (
            patch(
                "gateway_mcp.routes.notifications.web_actor", return_value=self.actor
            ),
            patch("gateway_mcp.routes.notifications.has_scope", return_value=True),
            patch("gateway_mcp.routes.notifications.verify_csrf", return_value=True),
            patch(
                "gateway_mcp.routes.notifications.update_topic_subscription",
                side_effect=PermissionError("resource access denied"),
            ),
        ):
            response = asyncio.run(
                self.fake.routes["/notifications/topics"]["func"](
                    FakeRequest(
                        json_body={
                            "topic_type": "project",
                            "topic_key": "secret-project",
                            "subscribed": True,
                        }
                    )
                )
            )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
