import hashlib
import json
import os
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def request_fingerprint(arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def claim_idempotency(
    *,
    actor_subject: str,
    tool_name: str,
    idempotency_key: str,
    request_hash: str,
) -> dict[str, Any]:
    key = _validate_key(idempotency_key)
    if not postgres_enabled():
        raise RuntimeError("idempotent tool calls require GatewayMCP Postgres")

    ensure_schema()
    ttl_seconds = int(os.getenv("GATEWAY_IDEMPOTENCY_TTL_SECONDS", "86400"))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from tool_idempotency_records where expires_at <= now()"
            )
            cur.execute(
                """
                insert into tool_idempotency_records (
                    actor_subject, tool_name, idempotency_key, request_hash, status, expires_at
                )
                values (%s, %s, %s, %s, 'pending', now() + (%s * interval '1 second'))
                on conflict (actor_subject, tool_name, idempotency_key) do nothing
                returning status, request_hash, response
                """,
                (actor_subject, tool_name, key, request_hash, ttl_seconds),
            )
            inserted = cur.fetchone()
            if inserted:
                conn.commit()
                return {"claimed": True, "replayed": False}

            cur.execute(
                """
                select status, request_hash, response
                from tool_idempotency_records
                where actor_subject = %s and tool_name = %s and idempotency_key = %s
                """,
                (actor_subject, tool_name, key),
            )
            existing = cur.fetchone()
            if not existing:
                raise RuntimeError("idempotency record disappeared during claim")
            if str(existing["request_hash"]) != request_hash:
                raise ValueError(
                    "idempotency_key was already used with different arguments"
                )
            if existing["status"] == "completed":
                conn.commit()
                response = existing.get("response") or {}
                return {
                    "claimed": False,
                    "replayed": True,
                    "response": dict(response)
                    if isinstance(response, dict)
                    else response,
                }
            if existing["status"] == "pending":
                raise RuntimeError(
                    "an identical idempotent tool call is already in progress"
                )

            cur.execute(
                """
                update tool_idempotency_records
                set status = 'pending', response = null, updated_at = now(),
                    expires_at = now() + (%s * interval '1 second')
                where actor_subject = %s and tool_name = %s and idempotency_key = %s
                """,
                (ttl_seconds, actor_subject, tool_name, key),
            )
        conn.commit()
    return {"claimed": True, "replayed": False, "retry": True}


def complete_idempotency(
    *,
    actor_subject: str,
    tool_name: str,
    idempotency_key: str,
    response: dict[str, Any],
) -> None:
    _set_status(
        actor_subject=actor_subject,
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status="completed",
        response=response,
    )


def fail_idempotency(
    *, actor_subject: str, tool_name: str, idempotency_key: str
) -> None:
    _set_status(
        actor_subject=actor_subject,
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status="failed",
        response=None,
    )


def _set_status(
    *,
    actor_subject: str,
    tool_name: str,
    idempotency_key: str,
    status: str,
    response: dict[str, Any] | None,
) -> None:
    if not postgres_enabled():
        return
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update tool_idempotency_records
                set status = %s, response = %s::jsonb, updated_at = now()
                where actor_subject = %s and tool_name = %s and idempotency_key = %s
                """,
                (
                    status,
                    json.dumps(response, ensure_ascii=False)
                    if response is not None
                    else None,
                    actor_subject,
                    tool_name,
                    _validate_key(idempotency_key),
                ),
            )
        conn.commit()


def _validate_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 200:
        raise ValueError("idempotency_key must contain 1 to 200 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise ValueError("idempotency_key contains control characters")
    return key
