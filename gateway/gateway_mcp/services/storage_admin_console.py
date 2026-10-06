"""Read-only projections for the admin console; never select credential payloads."""

from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

_USERS = """
with identities as (
    select actor_subject as subject, email, login, yandex_id, updated_at, 0 as rank
    from user_oauth_tokens where provider = 'yandex'
    union all
    select requester_subject, requester_email, '', '', updated_at, 1
    from access_requests
), known_users as (
    select distinct on (subject) subject, email, login, yandex_id, updated_at
    from identities where subject <> ''
    order by subject, rank, updated_at desc
)
"""


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("admin console requires PostgreSQL")
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in row.items()
        }
        for row in rows
    ]


def admin_overview_counts() -> dict[str, Any]:
    return _rows(
        _USERS
        + """
        select (select count(*) from known_users) as users,
            (select count(*) from access_requests where status = 'pending') as pending,
            (select count(*) from access_requests where status = 'processing') as processing,
            (select count(*) from audit_events
             where created_at >= now() - interval '24 hours'
             and status = 'error') as errors,
            (select count(*) from audit_events
             where created_at >= now() - interval '24 hours'
             and decision = 'deny') as denied
    """
    )[0]


def admin_users_page(
    *, query: str = "", offset: int = 0, limit: int = 26
) -> list[dict[str, Any]]:
    return _rows(
        _USERS
        + """
        select subject, email, login, yandex_id, updated_at from known_users
        where strpos(lower(subject || ' ' || email || ' ' || login), lower(%s)) > 0
        order by lower(coalesce(nullif(email, ''), subject)), subject
        limit %s offset %s
    """,
        (query, min(max(limit, 1), 101), max(offset, 0)),
    )


def admin_user_get(subject: str) -> dict[str, Any] | None:
    rows = _rows(
        _USERS
        + """
        select subject, email, login, yandex_id, updated_at
        from known_users where subject = %s
    """,
        (subject,),
    )
    return rows[0] if rows else None


def admin_user_grants(
    user: dict[str, Any], *, offset: int = 0, limit: int = 26
) -> dict[str, list]:
    keys = sorted(
        {
            str(user.get(key) or "").strip().casefold()
            for key in ("subject", "email", "login", "yandex_id")
        }
        - {""}
    )
    tables = {
        "packages": ("access_grant_bundles", "id, title, package_key, package_version"),
        "scopes": ("access_scope_grants", "id, scope, effect"),
        "resources": (
            "access_resource_grants",
            "id, system, resource_type, resource_pattern, actions, effect",
        ),
    }
    result = {}
    for name, (table, columns) in tables.items():
        result[name] = _rows(
            f"""
            select {columns}, created_at, expires_at, revoked_at
            from {table}
            where subject_type = 'user' and lower(subject_key) = any(%s)
            order by created_at desc, id desc limit %s offset %s
        """,
            (keys, min(max(limit, 1), 101), max(offset, 0)),
        )
    return result
