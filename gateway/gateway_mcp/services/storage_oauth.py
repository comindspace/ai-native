import json
from datetime import datetime, timezone
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def save_gateway_oauth_refresh_token(
    *,
    token_hash: str,
    actor_payload: dict[str, Any],
    client_id: str,
    resource: str,
    scope: str,
    expires_at_epoch: float,
) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    expires_at = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into gateway_oauth_refresh_tokens (
                    token_hash, actor_payload, client_id, resource, scope, expires_at
                )
                values (%s, %s::jsonb, %s, %s, %s, %s)
                """,
                (
                    token_hash,
                    json.dumps(actor_payload, ensure_ascii=False),
                    client_id,
                    resource,
                    scope,
                    expires_at,
                ),
            )
            cur.execute(
                """
                delete from gateway_oauth_refresh_tokens
                where expires_at <= now() or revoked_at < now() - interval '7 days'
                """
            )
        conn.commit()
    return True


def consume_gateway_oauth_refresh_token(token_hash: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None

    ensure_schema()
    with _connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from gateway_oauth_refresh_tokens
                    where token_hash = %s
                      and revoked_at is null
                      and expires_at > now()
                    for update
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    """
                    update gateway_oauth_refresh_tokens
                    set revoked_at = now(), last_used_at = now()
                    where token_hash = %s
                    """,
                    (token_hash,),
                )
    return dict(row)


def revoke_gateway_oauth_refresh_token(token_hash: str) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update gateway_oauth_refresh_tokens
                set revoked_at = coalesce(revoked_at, now())
                where token_hash = %s
                """,
                (token_hash,),
            )
            changed = cur.rowcount > 0
        conn.commit()
    return changed


def revoke_gateway_oauth_access_token(*, jti: str, expires_at_epoch: float) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    expires_at = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into gateway_oauth_revoked_access_tokens (jti, expires_at)
                values (%s, %s)
                on conflict (jti) do nothing
                """,
                (jti, expires_at),
            )
            cur.execute(
                "delete from gateway_oauth_revoked_access_tokens where expires_at <= now()"
            )
        conn.commit()
    return True


def gateway_oauth_access_token_revoked(jti: str) -> bool:
    if not jti or not postgres_enabled():
        return False

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from gateway_oauth_revoked_access_tokens
                where jti = %s and expires_at > now()
                """,
                (jti,),
            )
            return cur.fetchone() is not None
