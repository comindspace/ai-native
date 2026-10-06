from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled
from gateway_mcp.services.storage_crypto import _decrypt_secret, _encrypt_secret


def get_service_connection(
    system: str, *, include_payload: bool = False
) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from managed_service_connections where system = %s", (system,)
        )
        row = cur.fetchone()
    return _connection_row(row, include_payload=include_payload)


def list_service_connections() -> list[dict[str, Any]]:
    if not postgres_enabled():
        return []
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select system, configured_fields, state, version, created_by, updated_by,
                   expires_at, last_checked_at, last_check_ok, last_check_message,
                   created_at, updated_at
            from managed_service_connections
            order by system
            """
        )
        rows = cur.fetchall()
    return [_connection_row(row, include_payload=False) or {} for row in rows]


def upsert_service_connection(
    *,
    system: str,
    payload: dict[str, str],
    updated_by: str,
    expires_at: datetime | None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("Postgres is required for managed service connections")
    ensure_schema()
    normalized = {
        str(key): str(value) for key, value in payload.items() if str(value).strip()
    }
    encrypted = _encrypt_secret(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    )
    configured_fields = sorted(normalized)
    with _connect() as conn, conn.cursor() as cur:
        if expected_version is not None:
            cur.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))", (system,)
            )
            cur.execute(
                "select * from managed_service_connections where system = %s for update",
                (system,),
            )
            previous = _connection_row(cur.fetchone(), include_payload=True)
            if int((previous or {}).get("version", 0)) != expected_version:
                raise ValueError("Connection changed; reload before saving")
            expiry = expires_at.isoformat() if expires_at else None
            if previous and (
                previous.get("payload") == normalized
                and previous.get("expires_at") == expiry
                and previous.get("state") == "active"
            ):
                previous.pop("payload", None)
                return previous
        cur.execute(
            """
            insert into managed_service_connections (
                system, payload_encrypted, configured_fields, state, version,
                created_by, updated_by, expires_at
            ) values (%s, %s, %s::jsonb, 'active', 1, %s, %s, %s)
            on conflict (system) do update set
                payload_encrypted = excluded.payload_encrypted,
                configured_fields = excluded.configured_fields,
                state = 'active',
                version = managed_service_connections.version + 1,
                updated_by = excluded.updated_by,
                expires_at = excluded.expires_at,
                last_checked_at = null,
                last_check_ok = null,
                last_check_message = '',
                updated_at = now()
            where %s::bigint is null or managed_service_connections.version = %s
            returning *
            """,
            (
                system,
                encrypted,
                json.dumps(configured_fields, ensure_ascii=False),
                updated_by,
                updated_by,
                expires_at,
                expected_version,
                expected_version,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    result = _connection_row(row, include_payload=False)
    if result is None:
        raise RuntimeError("Managed service connection was not saved")
    return result


def set_service_connection_state(
    system: str, *, state: str, updated_by: str, expected_version: int | None = None
) -> bool:
    if state not in {"active", "disabled"}:
        raise ValueError("Unknown managed service connection state")
    if not postgres_enabled():
        return False
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update managed_service_connections
            set state = %s, version = version + 1, updated_by = %s, updated_at = now()
            where system = %s and (%s::bigint is null or version = %s)
            """,
            (state, updated_by, system, expected_version, expected_version),
        )
        changed = cur.rowcount
        conn.commit()
    return bool(changed)


def delete_service_connection(system: str) -> bool:
    if not postgres_enabled():
        return False
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from managed_service_connections where system = %s", (system,)
        )
        changed = cur.rowcount
        conn.commit()
    return bool(changed)


def record_service_connection_check(
    system: str, *, ok: bool, message: str, expected_version: int | None = None
) -> bool:
    if not postgres_enabled():
        return False
    ensure_schema()
    safe_message = " ".join(str(message or "").split())[:500]
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update managed_service_connections
            set last_checked_at = now(), last_check_ok = %s,
                last_check_message = %s, updated_at = now()
            where system = %s and (%s::bigint is null or version = %s)
            """,
            (bool(ok), safe_message, system, expected_version, expected_version),
        )
        changed = cur.rowcount
        conn.commit()
    return bool(changed)


def _connection_row(
    row: dict[str, Any] | None, *, include_payload: bool
) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    encrypted = str(result.pop("payload_encrypted", "") or "")
    if include_payload:
        try:
            raw_payload = json.loads(_decrypt_secret(encrypted)) if encrypted else {}
        except Exception as exc:
            raise RuntimeError("Managed service connection payload is invalid") from exc
        if not isinstance(raw_payload, dict):
            raise RuntimeError("Managed service connection payload is invalid")
        result["payload"] = {
            str(key): str(value)
            for key, value in raw_payload.items()
            if str(value).strip()
        }
    for key in ("created_at", "updated_at", "expires_at", "last_checked_at"):
        value = result.get(key)
        formatter = getattr(value, "isoformat", None)
        if callable(formatter):
            result[key] = formatter()
    return result
