import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from gateway_mcp.services import storage_notifications as storage
from gateway_mcp.services.access_policy import explain_resource_access
from gateway_mcp.services.auth import jwt_secret
from gateway_mcp.services.policy import GatewayActor, has_scope

RECIPIENT_TYPES = {"user", "group", "role", "team", "project"}
PRIORITIES = {"low", "normal", "high", "urgent"}
STATES = {"seen", "read", "unread"}
EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,99}$")


def publish_notification(
    *,
    actor: GatewayActor,
    event_type: str,
    title: str,
    body: str,
    recipients_json: str,
    action_url: str,
    project_id: str,
    priority: str,
    artifact_refs_json: str,
    metadata_json: str,
    expires_in_days: int,
    idempotency_key: str,
) -> dict[str, Any]:
    normalized_event_type = _event_type(event_type)
    normalized_priority = str(priority or "normal").strip().casefold()
    if normalized_priority not in PRIORITIES:
        raise ValueError("priority must be low, normal, high, or urgent")
    recipients = _recipients(actor, recipients_json)
    normalized_project_id = _text(project_id, "project_id", 160).casefold()
    _require_recipient_access(actor, recipients, normalized_project_id)
    refs = _artifact_refs(artifact_refs_json)
    metadata = _object(metadata_json, "metadata_json")
    if len(json.dumps(metadata, ensure_ascii=False)) > 4000:
        raise ValueError("metadata_json is too large")
    ttl_days = max(1, min(int(expires_in_days or 30), 365))
    return storage.insert_notification(
        notification_id=f"notification-{uuid.uuid4()}",
        event_type=normalized_event_type,
        title=_text(title, "title", 180, required=True),
        body=_text(body, "body", 1200),
        action_url=_action_url(action_url),
        project_id=normalized_project_id,
        priority=normalized_priority,
        created_by=actor.subject,
        recipients=recipients,
        artifact_refs=refs,
        metadata=metadata,
        idempotency_key=_text(idempotency_key, "idempotency_key", 180),
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
    )


def list_visible_notifications(
    *,
    actor: GatewayActor,
    unread_only: bool,
    event_type: str,
    project_id: str,
    limit: int,
) -> dict[str, Any]:
    requested_limit = max(1, min(int(limit or 50), 200))
    items = storage.list_notifications(
        actor_subject=actor.subject,
        actor_aliases=_actor_aliases(actor),
        actor_groups=_actor_groups(actor),
        unread_only=bool(unread_only),
        event_type=_event_type(event_type, required=False),
        project_id=_text(project_id, "project_id", 160),
        limit=200,
    )
    project_access: dict[str, bool] = {}
    items = [
        item
        for item in items
        if _visible_under_project_acl(actor, item, project_access)
    ][:requested_limit]
    return {
        "count": len(items),
        "unread_count": sum(1 for item in items if not item.get("read_at")),
        "notifications": items,
    }


def get_visible_notification(
    *, actor: GatewayActor, notification_id: str, mark_seen: bool = True
) -> dict[str, Any]:
    identifier = _text(notification_id, "notification_id", 100, required=True)
    item = storage.get_notification(
        notification_id=identifier,
        actor_subject=actor.subject,
        actor_aliases=_actor_aliases(actor),
        actor_groups=_actor_groups(actor),
    )
    if not item:
        raise PermissionError("notification not found or not visible")
    if not _visible_under_project_acl(actor, item, {}):
        raise PermissionError("notification not found or not visible")
    if mark_seen and not item.get("seen_at"):
        receipt = storage.set_notification_state(
            notification_id=identifier,
            actor_subject=actor.subject,
            state="seen",
        )
        item["seen_at"] = receipt.get("seen_at")
    return item


def acknowledge_notification(
    *, actor: GatewayActor, notification_id: str, state: str
) -> dict[str, Any]:
    item = get_visible_notification(
        actor=actor,
        notification_id=notification_id,
        mark_seen=False,
    )
    normalized_state = str(state or "read").strip().casefold()
    if normalized_state not in STATES:
        raise ValueError("state must be seen, read, or unread")
    receipt = storage.set_notification_state(
        notification_id=item["notification_id"],
        actor_subject=actor.subject,
        state=normalized_state,
    )
    return {"notification": item, "receipt": receipt, "state": normalized_state}


def acknowledge_all_notifications(actor: GatewayActor) -> int:
    visible = list_visible_notifications(
        actor=actor,
        unread_only=True,
        event_type="",
        project_id="",
        limit=200,
    )
    return storage.mark_notifications_read(
        actor_subject=actor.subject,
        notification_ids=[
            str(item["notification_id"])
            for item in visible["notifications"]
            if item.get("notification_id")
        ],
    )


def update_topic_subscription(
    *, actor: GatewayActor, topic_type: str, topic_key: str, subscribed: bool
) -> dict[str, Any]:
    normalized_type = str(topic_type or "project").strip().casefold()
    if normalized_type != "project":
        raise ValueError("only project notification topics are supported")
    normalized_key = _text(topic_key, "topic_key", 160, required=True).casefold()
    if subscribed and not _can_read_project(actor, normalized_key):
        raise PermissionError(
            f"resource access denied: factory:read project {normalized_key}"
        )
    storage.set_topic_subscription(
        actor_subject=actor.subject,
        topic_type=normalized_type,
        topic_key=normalized_key,
        subscribed=bool(subscribed),
    )
    return {
        "topic_type": normalized_type,
        "topic_key": normalized_key,
        "subscribed": bool(subscribed),
    }


def topic_subscriptions(actor: GatewayActor) -> list[dict[str, Any]]:
    return storage.list_topic_subscriptions(actor.subject)


def register_push_subscription(
    *, actor: GatewayActor, subscription: dict[str, Any], user_agent: str
) -> dict[str, Any]:
    endpoint = _text(subscription.get("endpoint"), "endpoint", 2000, required=True)
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("push endpoint must use HTTPS")
    keys = subscription.get("keys")
    if not isinstance(keys, dict):
        raise TypeError("push subscription keys are required")
    p256dh = _text(keys.get("p256dh"), "p256dh", 512, required=True)
    auth_secret = _text(keys.get("auth"), "auth", 256, required=True)
    return storage.upsert_push_subscription(
        actor_subject=actor.subject,
        actor_email=actor.email,
        actor_login=actor.login,
        actor_yandex_id=actor.yandex_id,
        actor_groups=_actor_groups(actor),
        endpoint=endpoint,
        p256dh=p256dh,
        auth_secret=auth_secret,
        user_agent=_text(user_agent, "user_agent", 500),
    )


def unregister_push_subscription(*, actor: GatewayActor, endpoint: str) -> bool:
    return storage.disable_push_subscription(
        actor_subject=actor.subject,
        endpoint=_text(endpoint, "endpoint", 2000, required=True),
    )


def push_public_key() -> str:
    return os.getenv("GATEWAY_WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()


def push_enabled() -> bool:
    return bool(push_public_key())


def csrf_token(actor: GatewayActor) -> str:
    value = f"notifications:{actor.subject}".encode()
    return hmac.new(jwt_secret().encode("utf-8"), value, hashlib.sha256).hexdigest()


def verify_csrf(actor: GatewayActor, token: str) -> bool:
    return hmac.compare_digest(csrf_token(actor), str(token or ""))


def _recipients(actor: GatewayActor, raw: str) -> list[dict[str, str]]:
    values = _array(raw, "recipients_json")
    if not values:
        values = [{"type": "user", "key": actor.subject}]
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, dict):
            raise TypeError("each recipient must be an object")
        recipient_type = str(value.get("type") or "user").strip().casefold()
        recipient_key = _text(value.get("key"), "recipient.key", 180, required=True)
        if recipient_type == "self" or recipient_key.casefold() in {"self", "me"}:
            recipient_type = "user"
            recipient_key = actor.subject
        if recipient_type not in RECIPIENT_TYPES:
            raise ValueError(
                "recipient type must be user, group, role, team, or project"
            )
        normalized = (recipient_type, recipient_key.casefold())
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append({"type": recipient_type, "key": recipient_key.casefold()})
    if len(result) > 50:
        raise ValueError("at most 50 recipients are allowed")
    return result


def _artifact_refs(raw: str) -> list[dict[str, str]]:
    values = _array(raw, "artifact_refs_json")
    if len(values) > 20:
        raise ValueError("at most 20 artifact references are allowed")
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise TypeError("each artifact reference must be an object")
        uri = _action_url(value.get("uri") or value.get("url"))
        if not uri:
            raise ValueError("artifact reference uri is required")
        result.append(
            {
                "type": _text(value.get("type"), "artifact.type", 80),
                "title": _text(value.get("title"), "artifact.title", 180),
                "uri": uri,
            }
        )
    return result


def _actor_aliases(actor: GatewayActor) -> list[str]:
    return sorted(
        {
            str(value).strip().casefold()
            for value in (actor.subject, actor.email, actor.login, actor.yandex_id)
            if str(value or "").strip()
        }
    )


def _actor_groups(actor: GatewayActor) -> list[str]:
    return sorted(
        {str(value).strip().casefold() for value in actor.groups if str(value).strip()}
    )


def _require_recipient_access(
    actor: GatewayActor,
    recipients: list[dict[str, str]],
    project_id: str,
) -> None:
    broad_types = {"group", "role", "team"}
    if any(item["type"] in broad_types for item in recipients) and not has_scope(
        actor, "notifications:broadcast"
    ):
        raise PermissionError(
            "notifications:broadcast is required for group, role, or team recipients"
        )
    project_keys = {
        item["key"] for item in recipients if item["type"] == "project"
    }
    if project_id:
        project_keys.add(project_id)
    for key in project_keys:
        if not _can_read_project(actor, key):
            raise PermissionError(
                f"resource access denied: factory:read project {key}"
            )


def _visible_under_project_acl(
    actor: GatewayActor,
    item: dict[str, Any],
    project_access: dict[str, bool],
) -> bool:
    recipients = item.get("recipients")
    if not isinstance(recipients, list):
        return False
    project_id = str(item.get("project_id") or "").strip().casefold()
    if project_id:
        if project_id not in project_access:
            project_access[project_id] = _can_read_project(actor, project_id)
        if not project_access[project_id]:
            return False
    aliases = set(_actor_aliases(actor))
    groups = set(_actor_groups(actor))
    project_keys: list[str] = []
    for recipient in recipients:
        if not isinstance(recipient, dict):
            continue
        recipient_type = str(recipient.get("type") or "").strip().casefold()
        recipient_key = str(recipient.get("key") or "").strip().casefold()
        if recipient_type == "user" and recipient_key in aliases:
            return True
        if recipient_type in {"group", "role", "team"} and recipient_key in groups:
            return True
        if recipient_type == "project" and recipient_key:
            project_keys.append(recipient_key)
    for key in project_keys:
        if key not in project_access:
            project_access[key] = _can_read_project(actor, key)
        if project_access[key]:
            return True
    return False


def _can_read_project(actor: GatewayActor, project_id: str) -> bool:
    if has_scope(actor, "*"):
        return True
    explanation = explain_resource_access(
        actor=actor,
        system="factory",
        action="read",
        resource=project_id,
        resource_type="project",
    )
    return explanation["decision"] == "allow"


def _event_type(value: Any, *, required: bool = True) -> str:
    result = str(value or "").strip().casefold()
    if not result and not required:
        return ""
    if not EVENT_TYPE_PATTERN.fullmatch(result):
        raise ValueError("event_type must be a dotted lowercase identifier")
    return result


def _action_url(value: Any) -> str:
    result = _text(value, "action_url", 1000)
    if not result:
        return ""
    if result.startswith("/") and not result.startswith("//"):
        return result
    parsed = urlparse(result)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("action and artifact URLs must use HTTPS or a relative path")
    return result


def _array(raw: str, field: str) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be a JSON array: {exc}") from exc
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a JSON array")
    return value


def _object(raw: str, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be a JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a JSON object")
    return value


def _text(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > limit:
        raise ValueError(f"{field} is too long")
    return result
