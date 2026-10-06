import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def insert_notification(
    *,
    notification_id: str,
    event_type: str,
    title: str,
    body: str,
    action_url: str,
    project_id: str,
    priority: str,
    created_by: str,
    recipients: list[dict[str, str]],
    artifact_refs: list[dict[str, str]],
    metadata: dict[str, Any],
    idempotency_key: str,
    expires_at: datetime | None,
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_events (
                    notification_id, event_type, title, body, action_url,
                    project_id, priority, created_by, artifact_refs, metadata,
                    idempotency_key, expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                        %s::jsonb, %s, %s)
                on conflict (created_by, idempotency_key)
                    where idempotency_key <> ''
                do nothing
                returning *
                """,
                (
                    notification_id,
                    event_type,
                    title,
                    body,
                    action_url,
                    project_id,
                    priority,
                    created_by,
                    json.dumps(artifact_refs, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    idempotency_key,
                    expires_at,
                ),
            )
            row = cur.fetchone()
            inserted = bool(row)
            if not row and idempotency_key:
                cur.execute(
                    """
                    select * from notification_events
                    where created_by = %s and idempotency_key = %s
                    """,
                    (created_by, idempotency_key),
                )
                row = cur.fetchone()
            if not row:
                raise RuntimeError("notification insert did not return a row")

            actual_id = str(row["notification_id"])
            if inserted:
                for recipient in recipients:
                    cur.execute(
                        """
                        insert into notification_recipients (
                            notification_id, recipient_type, recipient_key
                        )
                        values (%s, %s, %s)
                        on conflict do nothing
                        """,
                        (
                            actual_id,
                            recipient["type"],
                            recipient["key"],
                        ),
                    )
                _enqueue_delivery_sql(cur, notification_id=actual_id)
                cur.execute(
                    "select pg_notify('gateway_notifications', %s)", (actual_id,)
                )
        conn.commit()
    return {**_notification_row(row), "inserted": inserted}


def list_notifications(
    *,
    actor_subject: str,
    actor_aliases: list[str],
    actor_groups: list[str],
    unread_only: bool,
    event_type: str,
    project_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    where = [
        "(n.expires_at is null or n.expires_at > now())",
        _visibility_sql(),
    ]
    params: list[Any] = [
        actor_aliases,
        actor_groups,
        actor_subject,
    ]
    if unread_only:
        where.append("receipt.read_at is null")
    if event_type:
        where.append("n.event_type = %s")
        params.append(event_type)
    if project_id:
        where.append("n.project_id = %s")
        params.append(project_id)
    params.append(max(1, min(int(limit or 50), 200)))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            select n.*, receipt.seen_at, receipt.read_at,
                   coalesce(
                       jsonb_agg(
                           jsonb_build_object('type', recipients.recipient_type,
                                              'key', recipients.recipient_key)
                           order by recipients.id
                       ) filter (where recipients.id is not null),
                       '[]'::jsonb
                   ) as recipients
            from notification_events n
            left join notification_receipts receipt
              on receipt.notification_id = n.notification_id
             and receipt.actor_subject = %s
            left join notification_recipients recipients
              on recipients.notification_id = n.notification_id
            where {" and ".join(where)}
            group by n.notification_id, receipt.seen_at, receipt.read_at
            order by
                case n.priority
                    when 'urgent' then 1 when 'high' then 2
                    when 'normal' then 3 else 4
                end,
                n.created_at desc
            limit %s
            """,
            [actor_subject, *params],
        )
        rows = cur.fetchall()
    return [_notification_row(row) for row in rows]


def get_notification(
    *,
    notification_id: str,
    actor_subject: str,
    actor_aliases: list[str],
    actor_groups: list[str],
) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            select n.*, receipt.seen_at, receipt.read_at,
                   coalesce(
                       jsonb_agg(
                           jsonb_build_object('type', recipients.recipient_type,
                                              'key', recipients.recipient_key)
                           order by recipients.id
                       ) filter (where recipients.id is not null),
                       '[]'::jsonb
                   ) as recipients
            from notification_events n
            left join notification_receipts receipt
              on receipt.notification_id = n.notification_id
             and receipt.actor_subject = %s
            left join notification_recipients recipients
              on recipients.notification_id = n.notification_id
            where n.notification_id = %s
              and (n.expires_at is null or n.expires_at > now())
              and {_visibility_sql()}
            group by n.notification_id, receipt.seen_at, receipt.read_at
            """,
            (
                actor_subject,
                notification_id,
                actor_aliases,
                actor_groups,
                actor_subject,
            ),
        )
        row = cur.fetchone()
    return _notification_row(row) if row else None


def set_notification_state(
    *, notification_id: str, actor_subject: str, state: str
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            if state == "unread":
                cur.execute(
                    """
                    insert into notification_receipts (
                        notification_id, actor_subject, seen_at, read_at
                    ) values (%s, %s, now(), null)
                    on conflict (notification_id, actor_subject)
                    do update set read_at = null, updated_at = now()
                    returning *
                    """,
                    (notification_id, actor_subject),
                )
            else:
                read_expression = "now()" if state == "read" else "null"
                cur.execute(
                    f"""
                    insert into notification_receipts (
                        notification_id, actor_subject, seen_at, read_at
                    ) values (%s, %s, now(), {read_expression})
                    on conflict (notification_id, actor_subject)
                    do update set seen_at = coalesce(notification_receipts.seen_at, now()),
                                  read_at = coalesce({read_expression}, notification_receipts.read_at),
                                  updated_at = now()
                    returning *
                    """,
                    (notification_id, actor_subject),
                )
            row = cur.fetchone()
        conn.commit()
    return _receipt_row(row)


def mark_notifications_read(
    *, actor_subject: str, notification_ids: list[str]
) -> int:
    _require_postgres()
    ensure_schema()
    identifiers = sorted({str(value) for value in notification_ids if str(value)})
    if not identifiers:
        return 0
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_receipts (
                    notification_id, actor_subject, seen_at, read_at
                )
                select n.notification_id, %s, now(), now()
                from notification_events n
                where n.notification_id = any(%s)
                  and (n.expires_at is null or n.expires_at > now())
                on conflict (notification_id, actor_subject)
                do update set
                    seen_at = coalesce(notification_receipts.seen_at, now()),
                    read_at = now(),
                    updated_at = now()
                """,
                (actor_subject, identifiers),
            )
            changed = cur.rowcount
        conn.commit()
    return max(0, int(changed or 0))


def set_topic_subscription(
    *, actor_subject: str, topic_type: str, topic_key: str, subscribed: bool
) -> bool:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            if subscribed:
                cur.execute(
                    """
                    insert into notification_topic_subscriptions (
                        actor_subject, topic_type, topic_key
                    ) values (%s, %s, %s)
                    on conflict do nothing
                    """,
                    (actor_subject, topic_type, topic_key),
                )
            else:
                cur.execute(
                    """
                    delete from notification_topic_subscriptions
                    where actor_subject = %s and topic_type = %s and topic_key = %s
                    """,
                    (actor_subject, topic_type, topic_key),
                )
        conn.commit()
    return subscribed


def list_topic_subscriptions(actor_subject: str) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select topic_type, topic_key, created_at
            from notification_topic_subscriptions
            where actor_subject = %s
            order by topic_type, topic_key
            """,
            (actor_subject,),
        )
        rows = cur.fetchall()
    return [_serialize_times(dict(row)) for row in rows]


def upsert_push_subscription(
    *,
    actor_subject: str,
    actor_email: str,
    actor_login: str,
    actor_yandex_id: str,
    actor_groups: list[str],
    endpoint: str,
    p256dh: str,
    auth_secret: str,
    user_agent: str,
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    subscription_id = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into push_subscriptions (
                    subscription_id, actor_subject, actor_email, actor_login,
                    actor_yandex_id, actor_groups, endpoint, p256dh,
                    auth_secret, user_agent
                ) values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                on conflict (endpoint) do update set
                    actor_subject = excluded.actor_subject,
                    actor_email = excluded.actor_email,
                    actor_login = excluded.actor_login,
                    actor_yandex_id = excluded.actor_yandex_id,
                    actor_groups = excluded.actor_groups,
                    p256dh = excluded.p256dh,
                    auth_secret = excluded.auth_secret,
                    user_agent = excluded.user_agent,
                    enabled = true,
                    failure_count = 0,
                    updated_at = now()
                returning *
                """,
                (
                    subscription_id,
                    actor_subject,
                    actor_email,
                    actor_login,
                    actor_yandex_id,
                    json.dumps(actor_groups, ensure_ascii=False),
                    endpoint,
                    p256dh,
                    auth_secret,
                    user_agent,
                ),
            )
            row = cur.fetchone()
            _enqueue_delivery_sql(
                cur,
                subscription_id=str(row["subscription_id"]),
            )
            cur.execute(
                "select pg_notify('gateway_notifications', %s)", (subscription_id,)
            )
        conn.commit()
    return _push_subscription_row(row)


def disable_push_subscription(*, actor_subject: str, endpoint: str) -> bool:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update push_subscriptions
                set enabled = false, updated_at = now()
                where actor_subject = %s and endpoint = %s and enabled = true
                """,
                (actor_subject, endpoint),
            )
            changed = cur.rowcount > 0
        conn.commit()
    return changed


def claim_notification_deliveries(
    *, limit: int, lease_seconds: int
) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    lease = max(30, min(int(lease_seconds or 120), 1800))
    batch = max(1, min(int(limit or 25), 100))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_deliveries
                set status = 'retry', locked_at = null, updated_at = now()
                where status = 'sending'
                  and locked_at < now() - (%s * interval '1 second')
                """,
                (lease,),
            )
            cur.execute(
                """
                with claimed as (
                    select d.id
                    from notification_deliveries d
                    join notification_events n
                      on n.notification_id = d.notification_id
                    join push_subscriptions s
                      on s.subscription_id = d.subscription_id
                    where d.status in ('pending', 'retry')
                      and d.next_attempt_at <= now()
                      and s.enabled = true
                      and (n.expires_at is null or n.expires_at > now())
                    order by d.next_attempt_at, d.id
                    for update of d skip locked
                    limit %s
                )
                update notification_deliveries d
                set status = 'sending', attempts = attempts + 1,
                    locked_at = now(), updated_at = now()
                from claimed, notification_events n, push_subscriptions s
                where d.id = claimed.id
                  and n.notification_id = d.notification_id
                  and s.subscription_id = d.subscription_id
                returning d.id, d.attempts, n.notification_id, n.event_type,
                          n.title, n.body, n.action_url, n.project_id,
                          n.priority, s.subscription_id, s.endpoint,
                          s.p256dh, s.auth_secret
                """,
                (batch,),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(row) for row in rows]


def complete_notification_delivery(delivery_id: int) -> None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_deliveries d
                set status = 'sent', sent_at = now(), locked_at = null,
                    last_error_code = '', updated_at = now()
                where d.id = %s
                returning d.subscription_id
                """,
                (delivery_id,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    update push_subscriptions
                    set failure_count = 0, last_success_at = now(), updated_at = now()
                    where subscription_id = %s
                    """,
                    (row["subscription_id"],),
                )
        conn.commit()


def fail_notification_delivery(
    *,
    delivery_id: int,
    error_code: str,
    permanent: bool,
    disable_subscription: bool = False,
) -> None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_deliveries d
                set status = case when %s then 'failed' else 'retry' end,
                    next_attempt_at = case
                        when %s then next_attempt_at
                        else now() + (least(3600, power(2, least(attempts, 10))) * interval '1 second')
                    end,
                    locked_at = null, last_error_code = %s, updated_at = now()
                where d.id = %s
                returning d.subscription_id
                """,
                (permanent, permanent, error_code[:80], delivery_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    update push_subscriptions
                    set enabled = case when %s then false else enabled end,
                        failure_count = failure_count + 1,
                        last_failure_at = now(), updated_at = now()
                    where subscription_id = %s
                    """,
                    (disable_subscription, row["subscription_id"]),
                )
        conn.commit()


def _enqueue_delivery_sql(
    cur: Any,
    *,
    notification_id: str = "",
    subscription_id: str = "",
) -> None:
    filters = ["s.enabled = true", "(n.expires_at is null or n.expires_at > now())"]
    params: list[Any] = []
    if notification_id:
        filters.append("n.notification_id = %s")
        params.append(notification_id)
    if subscription_id:
        filters.append("s.subscription_id = %s")
        params.append(subscription_id)
    cur.execute(
        f"""
        insert into notification_deliveries (notification_id, subscription_id)
        select n.notification_id, s.subscription_id
        from notification_events n
        cross join push_subscriptions s
        where {" and ".join(filters)}
          and exists (
              select 1 from notification_recipients r
              where r.notification_id = n.notification_id
                and (
                    (r.recipient_type = 'user' and lower(r.recipient_key) in (
                        lower(s.actor_subject), lower(s.actor_email),
                        lower(s.actor_login), lower(s.actor_yandex_id)
                    ))
                    or (r.recipient_type in ('group', 'role', 'team')
                        and s.actor_groups ? lower(r.recipient_key))
                    or (r.recipient_type = 'project' and exists (
                        select 1 from notification_topic_subscriptions topics
                        where topics.actor_subject = s.actor_subject
                          and topics.topic_type = 'project'
                          and lower(topics.topic_key) = lower(r.recipient_key)
                    ))
                )
          )
        on conflict do nothing
        """,
        params,
    )


def _visibility_sql() -> str:
    return """
        exists (
            select 1 from notification_recipients visible_recipient
            where visible_recipient.notification_id = n.notification_id
              and (
                  (visible_recipient.recipient_type = 'user'
                   and lower(visible_recipient.recipient_key) = any(%s))
                  or (visible_recipient.recipient_type in ('group', 'role', 'team')
                      and lower(visible_recipient.recipient_key) = any(%s))
                  or (visible_recipient.recipient_type = 'project' and exists (
                      select 1 from notification_topic_subscriptions visible_topic
                      where visible_topic.actor_subject = %s
                        and visible_topic.topic_type = 'project'
                        and lower(visible_topic.topic_key) = lower(visible_recipient.recipient_key)
                  ))
              )
        )
    """


def _require_postgres() -> None:
    if not postgres_enabled():
        raise RuntimeError(
            "GATEWAY_DATABASE_URL is required for GatewayMCP notifications"
        )


def _notification_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = dict(row)
    for key, fallback in (("artifact_refs", []), ("metadata", {}), ("recipients", [])):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                result[key] = fallback
    return _serialize_times(result)


def _receipt_row(row: dict[str, Any] | None) -> dict[str, Any]:
    return _serialize_times(dict(row or {}))


def _push_subscription_row(row: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(row or {})
    result.pop("p256dh", None)
    result.pop("auth_secret", None)
    result.pop("endpoint", None)
    value = result.get("actor_groups")
    if isinstance(value, str):
        try:
            result["actor_groups"] = json.loads(value)
        except json.JSONDecodeError:
            result["actor_groups"] = []
    return _serialize_times(result)


def _serialize_times(result: dict[str, Any]) -> dict[str, Any]:
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            result[key] = value.isoformat()
    return result
