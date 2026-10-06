import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.notifications import (
    acknowledge_notification,
    get_visible_notification,
    list_visible_notifications,
    publish_notification,
    register_push_subscription,
    update_topic_subscription,
)
from gateway_mcp.services.policy import GatewayActor


class NotificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = GatewayActor(
            subject="yandex:42",
            email="employee@comind.space",
            login="employee",
            yandex_id="42",
            groups=("Employees", "Project-Leads"),
            scopes=("notifications:read", "notifications:write"),
        )

    def test_publish_normalizes_recipients_and_defaults_self(self) -> None:
        with patch(
            "gateway_mcp.services.notifications.storage.insert_notification",
            side_effect=lambda **kwargs: kwargs,
        ):
            result = publish_notification(
                actor=self.actor,
                event_type="work.completed",
                title="MR готов",
                body="Проверки пройдены",
                recipients_json="[]",
                action_url="https://gitlab.example/mr/1",
                project_id="acme",
                priority="high",
                artifact_refs_json="[]",
                metadata_json="{}",
                expires_in_days=30,
                idempotency_key="work-1-completed",
            )

        self.assertEqual(
            result["recipients"],
            [{"type": "user", "key": "yandex:42"}],
        )
        self.assertEqual(result["event_type"], "work.completed")
        self.assertEqual(result["priority"], "high")

    def test_publish_rejects_insecure_action_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            publish_notification(
                actor=self.actor,
                event_type="work.completed",
                title="MR готов",
                body="",
                recipients_json='[{"type":"user","key":"employee"}]',
                action_url="http://gitlab.example/mr/1",
                project_id="",
                priority="normal",
                artifact_refs_json="[]",
                metadata_json="{}",
                expires_in_days=30,
                idempotency_key="",
            )

    def test_publish_requires_broadcast_scope_for_group_recipient(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.storage.insert_notification"
            ) as insert,
            self.assertRaisesRegex(PermissionError, "notifications:broadcast"),
        ):
            publish_notification(
                actor=self.actor,
                event_type="project.updated",
                title="Обновлён контекст",
                body="",
                recipients_json='[{"type":"group","key":"employees"}]',
                action_url="",
                project_id="",
                priority="normal",
                artifact_refs_json="[]",
                metadata_json="{}",
                expires_in_days=30,
                idempotency_key="",
            )
        insert.assert_not_called()

    def test_publish_project_recipient_requires_project_access(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.explain_resource_access",
                return_value={"decision": "deny"},
            ),
            patch(
                "gateway_mcp.services.notifications.storage.insert_notification"
            ) as insert,
            self.assertRaisesRegex(PermissionError, "resource access denied"),
        ):
            publish_notification(
                actor=self.actor,
                event_type="project.updated",
                title="Обновлён контекст",
                body="",
                recipients_json='[{"type":"project","key":"secret-project"}]',
                action_url="",
                project_id="secret-project",
                priority="normal",
                artifact_refs_json="[]",
                metadata_json="{}",
                expires_in_days=30,
                idempotency_key="",
            )
        insert.assert_not_called()

    def test_mark_all_uses_only_current_acl_visible_ids(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.storage.list_notifications",
                return_value=[
                    {
                        "notification_id": "n-direct",
                        "read_at": None,
                        "recipients": [
                            {"type": "user", "key": "employee@comind.space"}
                        ],
                    },
                    {
                        "notification_id": "n-revoked",
                        "read_at": None,
                        "recipients": [
                            {"type": "project", "key": "secret-project"}
                        ],
                    },
                ],
            ),
            patch(
                "gateway_mcp.services.notifications.explain_resource_access",
                return_value={"decision": "deny"},
            ),
            patch(
                "gateway_mcp.services.notifications.storage.mark_notifications_read",
                return_value=1,
            ) as update,
        ):
            from gateway_mcp.services.notifications import (
                acknowledge_all_notifications,
            )

            changed = acknowledge_all_notifications(self.actor)

        self.assertEqual(changed, 1)
        update.assert_called_once_with(
            actor_subject="yandex:42", notification_ids=["n-direct"]
        )

    def test_list_uses_current_actor_aliases_and_groups(self) -> None:
        with patch(
            "gateway_mcp.services.notifications.storage.list_notifications",
            return_value=[
                {
                    "notification_id": "n1",
                    "read_at": None,
                    "recipients": [
                        {"type": "user", "key": "employee@comind.space"}
                    ],
                }
            ],
        ) as search:
            result = list_visible_notifications(
                actor=self.actor,
                unread_only=True,
                event_type="",
                project_id="",
                limit=25,
            )

        self.assertEqual(result["unread_count"], 1)
        call = search.call_args.kwargs
        self.assertEqual(
            call["actor_aliases"],
            ["42", "employee", "employee@comind.space", "yandex:42"],
        )
        self.assertEqual(call["actor_groups"], ["employees", "project-leads"])

    def test_list_filters_project_topic_after_access_is_revoked(self) -> None:
        project_item = {
            "notification_id": "n-project",
            "read_at": None,
            "project_id": "secret-project",
            "recipients": [{"type": "project", "key": "secret-project"}],
        }
        direct_item = {
            "notification_id": "n-direct",
            "read_at": None,
            "project_id": "",
            "recipients": [
                {"type": "project", "key": "secret-project"},
                {"type": "user", "key": "employee@comind.space"},
            ],
        }
        with (
            patch(
                "gateway_mcp.services.notifications.storage.list_notifications",
                return_value=[project_item, direct_item],
            ),
            patch(
                "gateway_mcp.services.notifications.explain_resource_access",
                return_value={"decision": "deny"},
            ),
        ):
            result = list_visible_notifications(
                actor=self.actor,
                unread_only=False,
                event_type="",
                project_id="",
                limit=25,
            )

        self.assertEqual(
            [item["notification_id"] for item in result["notifications"]],
            ["n-direct"],
        )

    def test_direct_recipient_cannot_bypass_event_project_access(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.storage.list_notifications",
                return_value=[
                    {
                        "notification_id": "n-direct-project",
                        "read_at": None,
                        "project_id": "secret-project",
                        "recipients": [
                            {"type": "user", "key": "employee@comind.space"}
                        ],
                    }
                ],
            ),
            patch(
                "gateway_mcp.services.notifications.explain_resource_access",
                return_value={"decision": "deny"},
            ),
        ):
            result = list_visible_notifications(
                actor=self.actor,
                unread_only=False,
                event_type="",
                project_id="",
                limit=25,
            )

        self.assertEqual(result["notifications"], [])

    def test_get_rechecks_project_access(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.storage.get_notification",
                return_value={
                    "notification_id": "n-project",
                    "recipients": [{"type": "project", "key": "secret-project"}],
                },
            ),
            patch(
                "gateway_mcp.services.notifications.explain_resource_access",
                return_value={"decision": "deny"},
            ),
            self.assertRaisesRegex(PermissionError, "not found or not visible"),
        ):
            get_visible_notification(
                actor=self.actor,
                notification_id="n-project",
            )

    def test_subscribe_requires_current_project_access(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.explain_resource_access",
                return_value={"decision": "deny"},
            ),
            patch(
                "gateway_mcp.services.notifications.storage.set_topic_subscription"
            ) as update,
            self.assertRaisesRegex(PermissionError, "resource access denied"),
        ):
            update_topic_subscription(
                actor=self.actor,
                topic_type="project",
                topic_key="secret-project",
                subscribed=True,
            )
        update.assert_not_called()

    def test_unsubscribe_remains_available_after_access_is_revoked(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.explain_resource_access"
            ) as explain,
            patch(
                "gateway_mcp.services.notifications.storage.set_topic_subscription"
            ) as update,
        ):
            update_topic_subscription(
                actor=self.actor,
                topic_type="project",
                topic_key="secret-project",
                subscribed=False,
            )
        explain.assert_not_called()
        update.assert_called_once()

    def test_acknowledge_never_writes_an_invisible_notification(self) -> None:
        with (
            patch(
                "gateway_mcp.services.notifications.storage.get_notification",
                return_value=None,
            ),
            patch(
                "gateway_mcp.services.notifications.storage.set_notification_state"
            ) as update,
            self.assertRaises(PermissionError),
        ):
            acknowledge_notification(
                actor=self.actor,
                notification_id="notification-secret",
                state="read",
            )
        update.assert_not_called()

    def test_push_subscription_requires_https_and_valid_keys(self) -> None:
        payload = {
            "endpoint": "https://push.example/subscription",
            "keys": {"p256dh": "public-key", "auth": "auth-secret"},
        }
        with patch(
            "gateway_mcp.services.notifications.storage.upsert_push_subscription",
            return_value={"subscription_id": "s1"},
        ) as upsert:
            result = register_push_subscription(
                actor=self.actor,
                subscription=payload,
                user_agent="Browser",
            )

        self.assertEqual(result["subscription_id"], "s1")
        self.assertEqual(
            upsert.call_args.kwargs["actor_groups"], ["employees", "project-leads"]
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            register_push_subscription(
                actor=self.actor,
                subscription={
                    **payload,
                    "endpoint": "http://push.example/subscription",
                },
                user_agent="Browser",
            )


if __name__ == "__main__":
    unittest.main()
