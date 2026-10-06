from typing import Any
from uuid import uuid4

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def insert_access_request(
    *,
    requester_subject: str,
    requester_email: str,
    subject_key: str,
    package_key: str,
    package_version: int,
    reason: str,
    requested_ttl_days: int | None,
    idempotency_key: str,
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    request_id = str(uuid4())
    with _connect() as conn:
        with conn.cursor() as cur:
            if idempotency_key:
                cur.execute(
                    """
                    select * from access_requests
                    where requester_subject = %s and idempotency_key = %s
                    """,
                    (requester_subject, idempotency_key),
                )
                existing = cur.fetchone()
                if existing:
                    return _request_row(existing)
            cur.execute(
                """
                insert into access_requests (
                    id, requester_subject, requester_email, subject_key,
                    package_key, package_version, reason, requested_ttl_days,
                    idempotency_key
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (requester_subject, package_key)
                    where status in ('pending', 'processing')
                do nothing
                returning *
                """,
                (
                    request_id,
                    requester_subject,
                    requester_email,
                    subject_key,
                    package_key,
                    package_version,
                    reason,
                    requested_ttl_days,
                    idempotency_key,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    select * from access_requests
                    where requester_subject = %s and package_key = %s
                      and status in ('pending', 'processing')
                    order by created_at desc
                    limit 1
                    """,
                    (requester_subject, package_key),
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError("active access request could not be loaded")
        conn.commit()
    return _request_row(row)


def get_access_request(request_id: str) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select * from access_requests where id = %s", (request_id,))
        row = cur.fetchone()
    return _request_row(row) if row else None


def list_access_requests(
    *,
    requester_subject: str = "",
    status: str = "",
    package_key: str = "",
    limit: int = 100,
    offset: int = 0,
    query: str = "",
) -> list[dict[str, Any]]:
    _require_postgres()
    ensure_schema()
    where: list[str] = []
    params: list[Any] = []
    if requester_subject:
        where.append("requester_subject = %s")
        params.append(requester_subject)
    if status:
        where.append("status = %s")
        params.append(status)
    if package_key:
        where.append("package_key = %s")
        params.append(package_key)
    if query:
        where.append("strpos(lower(requester_subject || ' ' || requester_email || ' ' || subject_key || ' ' || id::text), lower(%s)) > 0")
        params.append(query)
    params.append(max(1, min(int(limit), 500)))
    params.append(max(0, int(offset)))
    sql = f"""
        select * from access_requests
        {"where " + " and ".join(where) if where else ""}
        order by created_at desc, id desc
        limit %s offset %s
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_request_row(row) for row in rows]


def cancel_access_request(
    *, request_id: str, requester_subject: str, reason: str
) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update access_requests
                set status = 'cancelled',
                    decision_reason = %s,
                    updated_at = now(),
                    decided_at = now()
                where id = %s and requester_subject = %s and status = 'pending'
                returning *
                """,
                (reason, request_id, requester_subject),
            )
            row = cur.fetchone()
        conn.commit()
    return _request_row(row) if row else None


def decide_access_request(
    *,
    request_id: str,
    decision: str,
    decided_by: str,
    decision_reason: str,
    grant_bundle_id: str | None,
) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update access_requests
                set status = %s,
                    decision_reason = %s,
                    grant_bundle_id = %s,
                    updated_at = now(),
                    decided_at = now()
                where id = %s and status = 'processing' and decided_by = %s
                returning *
                """,
                (
                    decision,
                    decision_reason,
                    grant_bundle_id,
                    request_id,
                    decided_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _request_row(row) if row else None


def claim_access_request_decision(
    *, request_id: str, decided_by: str
) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update access_requests
                set status = 'processing', decided_by = %s, updated_at = now()
                where id = %s and status = 'pending'
                returning *
                """,
                (decided_by, request_id),
            )
            row = cur.fetchone()
        conn.commit()
    return _request_row(row) if row else None


def release_access_request_decision(*, request_id: str, decided_by: str) -> None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update access_requests
                set status = 'pending', decided_by = '', updated_at = now()
                where id = %s and status = 'processing' and decided_by = %s
                """,
                (request_id, decided_by),
            )
        conn.commit()


def _request_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = dict(row)
    for key in ("created_at", "updated_at", "decided_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    for key in ("id", "grant_bundle_id"):
        value = result.get(key)
        if value is not None:
            result[key] = str(value)
    return result


def _require_postgres() -> None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for access requests")
