import json
from datetime import datetime, timedelta, timezone
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

UTC = timezone.utc

def cleanup_expired_memory() -> int:
    if not postgres_enabled():
        return 0

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from memory_entries where expires_at is not null and expires_at <= now()")
            deleted = cur.rowcount
        conn.commit()
    return int(deleted or 0)


def insert_memory_entry(
    *,
    tier: str,
    scope: str,
    subject: str,
    kind: str,
    content: str,
    source_type: str,
    source_uri: str,
    source_title: str,
    sensitivity: str,
    confidence: float,
    tags: list[str],
    metadata: dict[str, Any],
    created_by: str,
    ttl_days: int | None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP memory")

    ensure_schema()
    expires_at: datetime | None = None
    if ttl_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into memory_entries (
                    tier,
                    scope,
                    subject,
                    kind,
                    content,
                    source_type,
                    source_uri,
                    source_title,
                    sensitivity,
                    confidence,
                    tags,
                    metadata,
                    created_by,
                    expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                returning *
                """,
                (
                    tier,
                    scope,
                    subject,
                    kind,
                    content,
                    source_type,
                    source_uri,
                    source_title,
                    sensitivity,
                    confidence,
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    created_by,
                    expires_at,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _memory_row(row)


def search_memory_entries(
    *,
    query: str,
    tiers: list[str],
    scope: str,
    subject: str,
    actor_subject: str,
    is_admin: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP memory")

    ensure_schema()
    cleanup_expired_memory()

    where = ["(expires_at is null or expires_at > now())"]
    params: list[Any] = []
    if not is_admin:
        where.append("(scope <> 'user' or subject = %s)")
        params.append(actor_subject)
    if tiers:
        where.append("tier = any(%s)")
        params.append(tiers)
    if scope:
        where.append("scope = %s")
        params.append(scope)
    if subject:
        where.append("subject = %s")
        params.append(subject)
    if query:
        needle = f"%{query}%"
        where.append(
            """
            (
                content ilike %s
                or source_title ilike %s
                or source_uri ilike %s
                or tags::text ilike %s
                or metadata::text ilike %s
            )
            """
        )
        params.extend([needle, needle, needle, needle, needle])

    params.append(limit)
    sql = f"""
        select *
        from memory_entries
        where {' and '.join(where)}
        order by
            case tier when 'short' then 0 else 1 end,
            created_at desc
        limit %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_memory_row(row) for row in rows]


def delete_memory_entry(entry_id: int, *, actor_subject: str, is_admin: bool) -> dict[str, Any] | None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP memory")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            if is_admin:
                cur.execute("delete from memory_entries where id = %s returning *", (entry_id,))
            else:
                cur.execute(
                    """
                    delete from memory_entries
                    where id = %s and (created_by = %s or (scope = 'user' and subject = %s))
                    returning *
                    """,
                    (entry_id, actor_subject, actor_subject),
                )
            row = cur.fetchone()
        conn.commit()
    return _memory_row(row) if row else None


def _memory_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}

    result = dict(row)
    for key in ("created_at", "updated_at", "expires_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    result["confidence"] = float(result.get("confidence") or 0)
    return result
