import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

UTC = timezone.utc

def list_scope_grants(
    *,
    subject_type: str = "",
    subject_key: str = "",
    scope: str = "",
    include_revoked: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP access grants")

    ensure_schema()
    where: list[str] = []
    params: list[Any] = []
    if subject_type:
        where.append("subject_type = %s")
        params.append(subject_type)
    if subject_key:
        where.append("subject_key = %s")
        params.append(subject_key)
    if scope:
        where.append("scope = %s")
        params.append(scope)
    if not include_revoked:
        where.append("revoked_at is null")

    params.append(max(1, min(int(limit), 500)))
    sql = f"""
        select *
        from access_scope_grants
        {'where ' + ' and '.join(where) if where else ''}
        order by created_at desc
        limit %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_access_row(row) for row in rows]


def list_active_scope_grants(subjects: list[tuple[str, str]]) -> list[dict[str, Any]]:
    if not postgres_enabled() or not subjects:
        return []

    ensure_schema()
    subject_clause, params = _subject_filter_sql(subjects)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select *
                from access_scope_grants
                where revoked_at is null
                  and (expires_at is null or expires_at > now())
                  and ({subject_clause})
                order by
                    case effect when 'deny' then 0 else 1 end,
                    created_at desc
                """,
                params,
            )
            rows = cur.fetchall()
    return [_access_row(row) for row in rows]


def insert_scope_grant(
    *,
    subject_type: str,
    subject_key: str,
    scope: str,
    effect: str,
    reason: str,
    created_by: str,
    ttl_days: int | None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP access grants")

    ensure_schema()
    expires_at = _expires_at(ttl_days)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into access_scope_grants (
                    subject_type, subject_key, scope, effect, reason, created_by, expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (subject_type, subject_key, scope, effect, reason, created_by, expires_at),
            )
            row = cur.fetchone()
        conn.commit()
    return _access_row(row)


def revoke_scope_grants(
    *,
    grant_id: int | None = None,
    subject_type: str = "",
    subject_key: str = "",
    scope: str = "",
    actor_subject: str = "",
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP access grants")

    ensure_schema()
    where = ["revoked_at is null"]
    params: list[Any] = []
    if grant_id is not None:
        where.append("id = %s")
        params.append(grant_id)
    if subject_type:
        where.append("subject_type = %s")
        params.append(subject_type)
    if subject_key:
        where.append("subject_key = %s")
        params.append(subject_key)
    if scope:
        where.append("scope = %s")
        params.append(scope)
    sql = f"""
        update access_scope_grants
        set revoked_at = now(), reason = concat(reason, case when reason = '' then '' else ' | ' end, 'revoked by ', %s::text)
        where {' and '.join(where)}
        returning *
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [actor_subject, *params])
            rows = cur.fetchall()
        conn.commit()
    return [_access_row(row) for row in rows]


def list_resource_grants(
    *,
    subject_type: str = "",
    subject_key: str = "",
    system: str = "",
    include_revoked: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP access grants")

    ensure_schema()
    where: list[str] = []
    params: list[Any] = []
    if subject_type:
        where.append("subject_type = %s")
        params.append(subject_type)
    if subject_key:
        where.append("subject_key = %s")
        params.append(subject_key)
    if system:
        where.append("system = %s")
        params.append(system)
    if not include_revoked:
        where.append("revoked_at is null")

    params.append(max(1, min(int(limit), 500)))
    sql = f"""
        select *
        from access_resource_grants
        {'where ' + ' and '.join(where) if where else ''}
        order by priority asc, created_at desc
        limit %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_access_row(row) for row in rows]


def list_active_resource_grants(
    *,
    subjects: list[tuple[str, str]],
    system: str,
) -> list[dict[str, Any]]:
    if not postgres_enabled() or not subjects:
        return []

    ensure_schema()
    subject_clause, params = _subject_filter_sql(subjects)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select *
                from access_resource_grants
                where revoked_at is null
                  and (expires_at is null or expires_at > now())
                  and system = %s
                  and ({subject_clause})
                order by
                    case effect when 'deny' then 0 else 1 end,
                    priority asc,
                    created_at desc
                """,
                [system, *params],
            )
            rows = cur.fetchall()
    return [_access_row(row) for row in rows]


def insert_resource_grant(
    *,
    subject_type: str,
    subject_key: str,
    system: str,
    resource_type: str,
    resource_pattern: str,
    actions: list[str],
    effect: str,
    priority: int,
    reason: str,
    created_by: str,
    ttl_days: int | None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP access grants")

    ensure_schema()
    expires_at = _expires_at(ttl_days)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into access_resource_grants (
                    subject_type, subject_key, system, resource_type, resource_pattern,
                    actions, effect, priority, reason, created_by, expires_at
                )
                values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    subject_type,
                    subject_key,
                    system,
                    resource_type,
                    resource_pattern,
                    json.dumps(actions, ensure_ascii=False),
                    effect,
                    priority,
                    reason,
                    created_by,
                    expires_at,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _access_row(row)


def revoke_resource_grants(
    *,
    grant_id: int | None = None,
    subject_type: str = "",
    subject_key: str = "",
    system: str = "",
    resource_pattern: str = "",
    actor_subject: str = "",
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP access grants")

    ensure_schema()
    where = ["revoked_at is null"]
    params: list[Any] = []
    if grant_id is not None:
        where.append("id = %s")
        params.append(grant_id)
    if subject_type:
        where.append("subject_type = %s")
        params.append(subject_type)
    if subject_key:
        where.append("subject_key = %s")
        params.append(subject_key)
    if system:
        where.append("system = %s")
        params.append(system)
    if resource_pattern:
        where.append("resource_pattern = %s")
        params.append(resource_pattern)
    sql = f"""
        update access_resource_grants
        set revoked_at = now(), reason = concat(reason, case when reason = '' then '' else ' | ' end, 'revoked by ', %s::text)
        where {' and '.join(where)}
        returning *
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [actor_subject, *params])
            rows = cur.fetchall()
        conn.commit()
    return [_access_row(row) for row in rows]


def insert_access_bundle(
    *,
    subject_type: str,
    subject_key: str,
    package_key: str,
    package_version: int,
    title: str,
    scopes: list[str],
    resources: list[dict[str, Any]],
    reason: str,
    created_by: str,
    ttl_days: int | None,
) -> dict[str, Any]:
    """Insert a complete access package in one transaction."""
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for access packages")

    ensure_schema()
    bundle_id = str(uuid4())
    expires_at = _expires_at(ttl_days)
    scope_rows: list[dict[str, Any]] = []
    resource_rows: list[dict[str, Any]] = []
    with _connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id from access_grant_bundles
                    where subject_type = %s and lower(subject_key) = lower(%s)
                      and package_key = %s and package_version = %s
                      and revoked_at is null
                      and (expires_at is null or expires_at > now())
                    limit 1
                    """,
                    (subject_type, subject_key, package_key, package_version),
                )
                existing = cur.fetchone()
                if existing is not None:
                    raise ValueError(f"access package is already assigned: {existing['id']}")
                cur.execute(
                    """
                    insert into access_grant_bundles (
                        id, subject_type, subject_key, package_key, package_version,
                        title, resources, reason, created_by, expires_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    returning *
                    """,
                    (
                        bundle_id,
                        subject_type,
                        subject_key,
                        package_key,
                        package_version,
                        title,
                        json.dumps(resources, ensure_ascii=False),
                        reason,
                        created_by,
                        expires_at,
                    ),
                )
                bundle_row = cur.fetchone()
                for scope in scopes:
                    cur.execute(
                        """
                        insert into access_scope_grants (
                            subject_type, subject_key, scope, effect, reason,
                            created_by, expires_at, bundle_id
                        )
                        values (%s, %s, %s, 'allow', %s, %s, %s, %s)
                        returning *
                        """,
                        (
                            subject_type,
                            subject_key,
                            scope,
                            reason,
                            created_by,
                            expires_at,
                            bundle_id,
                        ),
                    )
                    scope_rows.append(_access_row(cur.fetchone()))
                for resource in resources:
                    cur.execute(
                        """
                        insert into access_resource_grants (
                            subject_type, subject_key, system, resource_type,
                            resource_pattern, actions, effect, priority, reason,
                            created_by, expires_at, bundle_id
                        )
                        values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                        returning *
                        """,
                        (
                            subject_type,
                            subject_key,
                            str(resource.get("system") or ""),
                            str(resource.get("resource_type") or ""),
                            str(resource.get("resource_pattern") or "*"),
                            json.dumps(resource.get("actions") or [], ensure_ascii=False),
                            str(resource.get("effect") or "allow"),
                            int(resource.get("priority") or 100),
                            reason,
                            created_by,
                            expires_at,
                            bundle_id,
                        ),
                    )
                    resource_rows.append(_access_row(cur.fetchone()))
    return {
        "bundle": _access_row(bundle_row),
        "scope_grants": scope_rows,
        "resource_grants": resource_rows,
    }


def list_access_bundles(
    *,
    subject_type: str = "",
    subject_key: str = "",
    include_revoked: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for access packages")

    ensure_schema()
    where: list[str] = []
    params: list[Any] = []
    if subject_type:
        where.append("subject_type = %s")
        params.append(subject_type)
    if subject_key:
        where.append("lower(subject_key) = lower(%s)")
        params.append(subject_key)
    if not include_revoked:
        where.append("revoked_at is null")
    params.append(max(1, min(int(limit), 500)))
    sql = f"""
        select * from access_grant_bundles
        {"where " + " and ".join(where) if where else ""}
        order by created_at desc
        limit %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_access_row(row) for row in rows]


def revoke_access_bundle(*, bundle_id: str, actor_subject: str) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for access packages")

    ensure_schema()
    with _connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update access_scope_grants
                    set revoked_at = now(),
                        reason = concat(reason, case when reason = '' then '' else ' | ' end, 'revoked by ', %s::text)
                    where bundle_id = %s and revoked_at is null
                    returning id
                    """,
                    (actor_subject, bundle_id),
                )
                scope_ids = [int(row["id"]) for row in cur.fetchall()]
                cur.execute(
                    """
                    update access_resource_grants
                    set revoked_at = now(),
                        reason = concat(reason, case when reason = '' then '' else ' | ' end, 'revoked by ', %s::text)
                    where bundle_id = %s and revoked_at is null
                    returning id
                    """,
                    (actor_subject, bundle_id),
                )
                resource_ids = [int(row["id"]) for row in cur.fetchall()]
                cur.execute(
                    """
                    update access_grant_bundles
                    set revoked_at = now()
                    where id = %s and revoked_at is null
                    returning *
                    """,
                    (bundle_id,),
                )
                bundle = cur.fetchone()
                if bundle is None:
                    raise ValueError(f"access package not found: {bundle_id}")
    return {
        "bundle": _access_row(bundle),
        "scope_grant_ids": scope_ids,
        "resource_grant_ids": resource_ids,
    }


def _expires_at(ttl_days: int | None) -> datetime | None:
    if ttl_days is None:
        return None
    if ttl_days <= 0:
        return None
    return datetime.now(UTC) + timedelta(days=ttl_days)


def _access_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}

    result = dict(row)
    for key in ("created_at", "expires_at", "revoked_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _subject_filter_sql(subjects: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for subject_type, subject_key in subjects:
        clauses.append("(subject_type = %s and subject_key = %s)")
        params.extend([subject_type, subject_key])
    return " or ".join(clauses) or "false", params
