import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.notifications import (
    acknowledge_notification,
    get_visible_notification,
    list_visible_notifications,
    publish_notification,
    topic_subscriptions,
    update_topic_subscription,
)
from gateway_mcp.tools.runtime import ToolRun


def register_notification_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Notification Publish"))
    async def gateway_notification_publish(
        event_type: str,
        title: str,
        recipients_json: str,
        body: str = "",
        action_url: str = "",
        project_id: str = "",
        priority: str = "normal",
        artifact_refs_json: str = "[]",
        metadata_json: str = "{}",
        expires_in_days: int = 30,
        idempotency_key: str = "",
    ) -> str:
        """Publish a durable employee notification. Requires notifications:write."""
        arguments = {
            "event_type": event_type,
            "title": title,
            "project_id": project_id,
            "priority": priority,
            "expires_in_days": expires_in_days,
            "idempotency_key": idempotency_key,
        }
        run = ToolRun.start(
            tool="gateway_notification_publish",
            system="notifications",
            scope="notifications:write",
            arguments=arguments,
        )
        try:
            actor = run.require_scope()
            notification = publish_notification(
                actor=actor,
                event_type=event_type,
                title=title,
                body=body,
                recipients_json=recipients_json,
                action_url=action_url,
                project_id=project_id,
                priority=priority,
                artifact_refs_json=artifact_refs_json,
                metadata_json=metadata_json,
                expires_in_days=expires_in_days,
                idempotency_key=idempotency_key,
            )
            run.finish(status="created" if notification.get("inserted") else "existing")
            return _json({"ok": True, "notification": notification})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Notification List", readOnlyHint=True
        )
    )
    async def gateway_notifications_list(
        unread_only: bool = True,
        event_type: str = "",
        project_id: str = "",
        limit: int = 50,
    ) -> str:
        """List notifications visible to the current employee. Requires notifications:read."""
        arguments = {
            "unread_only": unread_only,
            "event_type": event_type,
            "project_id": project_id,
            "limit": limit,
        }
        run = ToolRun.start(
            tool="gateway_notifications_list",
            system="notifications",
            scope="notifications:read",
            arguments=arguments,
        )
        try:
            actor = run.require_scope()
            result = list_visible_notifications(actor=actor, **arguments)
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Notification Get", readOnlyHint=True)
    )
    async def gateway_notification_get(
        notification_id: str, mark_seen: bool = True
    ) -> str:
        """Read one visible notification. Requires notifications:read."""
        run = ToolRun.start(
            tool="gateway_notification_get",
            system="notifications",
            scope="notifications:read",
            arguments={"notification_id": notification_id, "mark_seen": mark_seen},
        )
        try:
            actor = run.require_scope()
            result = get_visible_notification(
                actor=actor,
                notification_id=notification_id,
                mark_seen=mark_seen,
            )
            run.finish()
            return _json({"ok": True, "notification": result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Notification Acknowledge"))
    async def gateway_notification_ack(
        notification_id: str, state: str = "read"
    ) -> str:
        """Mark one visible notification as seen, read, or unread. Requires notifications:read."""
        run = ToolRun.start(
            tool="gateway_notification_ack",
            system="notifications",
            scope="notifications:read",
            arguments={"notification_id": notification_id, "state": state},
        )
        try:
            actor = run.require_scope()
            result = acknowledge_notification(
                actor=actor,
                notification_id=notification_id,
                state=state,
            )
            run.finish(status=str(result.get("state") or "ok"))
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Notification Topic Update"))
    async def gateway_notification_topic_update(
        topic_key: str,
        topic_type: str = "project",
        subscribed: bool = True,
    ) -> str:
        """Subscribe the current employee to project notifications. Requires notifications:read."""
        run = ToolRun.start(
            tool="gateway_notification_topic_update",
            system="notifications",
            scope="notifications:read",
            arguments={
                "topic_type": topic_type,
                "topic_key": topic_key,
                "subscribed": subscribed,
            },
        )
        try:
            actor = run.require_scope()
            topic = update_topic_subscription(
                actor=actor,
                topic_type=topic_type,
                topic_key=topic_key,
                subscribed=subscribed,
            )
            subscriptions = topic_subscriptions(actor)
            run.finish()
            return _json(
                {
                    "ok": True,
                    "topic": topic,
                    "subscriptions": subscriptions,
                }
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
