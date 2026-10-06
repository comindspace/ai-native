import json
from datetime import datetime, timezone
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled
from gateway_mcp.services.storage_crypto import _decrypt_secret, _encrypt_secret

UTC = timezone.utc

def save_oauth_state(state: str, payload: dict[str, Any], expires_at_epoch: float) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into oauth_states (state, payload, expires_at)
                values (%s, %s::jsonb, to_timestamp(%s))
                on conflict (state)
                do update set payload = excluded.payload, expires_at = excluded.expires_at
                """,
                (state, json.dumps(payload), expires_at_epoch),
            )
        conn.commit()
    return True


def pop_oauth_state(state: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from oauth_states
                where state = %s and expires_at > now()
                returning payload
                """,
                (state,),
            )
            row = cur.fetchone()
            cur.execute("delete from oauth_states where expires_at <= now()")
        conn.commit()

    if not row:
        return None
    payload = row["payload"]
    return dict(payload) if isinstance(payload, dict) else payload


def save_user_oauth_token(
    *,
    provider: str,
    actor_subject: str,
    yandex_id: str,
    login: str,
    email: str,
    access_token: str,
    token_type: str,
    scopes: list[str],
    metadata: dict[str, Any],
    expires_at_epoch: float | None,
) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    expires_at = datetime.fromtimestamp(expires_at_epoch, UTC) if expires_at_epoch else None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into user_oauth_tokens (
                    provider,
                    actor_subject,
                    yandex_id,
                    login,
                    email,
                    access_token_encrypted,
                    token_type,
                    scopes,
                    metadata,
                    expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                on conflict (provider, actor_subject)
                do update set
                    yandex_id = excluded.yandex_id,
                    login = excluded.login,
                    email = excluded.email,
                    access_token_encrypted = excluded.access_token_encrypted,
                    token_type = excluded.token_type,
                    scopes = excluded.scopes,
                    metadata = excluded.metadata,
                    expires_at = excluded.expires_at,
                    revoked_at = null,
                    updated_at = now()
                """,
                (
                    provider,
                    actor_subject,
                    yandex_id,
                    login,
                    email,
                    _encrypt_secret(access_token),
                    token_type,
                    json.dumps(scopes, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    expires_at,
                ),
            )
        conn.commit()
    return True


def get_user_oauth_token(provider: str, actor_subject: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select *
                from user_oauth_tokens
                where provider = %s
                  and actor_subject = %s
                  and revoked_at is null
                  and (expires_at is null or expires_at > now())
                """,
                (provider, actor_subject),
            )
            row = cur.fetchone()
    if not row:
        return None

    result = dict(row)
    result["access_token"] = _decrypt_secret(str(result.pop("access_token_encrypted")))
    return result


def list_user_oauth_tokens(actor_subject: str) -> list[dict[str, Any]]:
    if not postgres_enabled():
        return []

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    provider,
                    actor_subject,
                    yandex_id,
                    login,
                    email,
                    token_type,
                    scopes,
                    metadata,
                    created_at,
                    updated_at,
                    expires_at,
                    revoked_at
                from user_oauth_tokens
                where actor_subject = %s
                order by provider
                """,
                (actor_subject,),
            )
            rows = cur.fetchall()
    return [_credential_row(row) for row in rows]


def list_service_credential_actors() -> list[str]:
    if not postgres_enabled():
        return []

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select actor_subject as subject
                from user_oauth_tokens
                where actor_subject like %s
                union
                select subject_key as subject
                from access_scope_grants
                where subject_type = 'user'
                  and subject_key like %s
                  and revoked_at is null
                order by subject
                """,
                ("service:%", "service:%"),
            )
            rows = cur.fetchall()
    return [str(row["subject"]) for row in rows if row.get("subject")]


def list_service_oauth_tokens(provider: str = "") -> list[dict[str, Any]]:
    if not postgres_enabled():
        return []

    ensure_schema()
    where = ["actor_subject like %s"]
    params: list[Any] = ["service:%"]
    if provider:
        where.append("provider = %s")
        params.append(provider)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    provider,
                    actor_subject,
                    yandex_id,
                    login,
                    email,
                    token_type,
                    scopes,
                    metadata,
                    created_at,
                    updated_at,
                    expires_at,
                    revoked_at
                from user_oauth_tokens
                where {' and '.join(where)}
                order by actor_subject, provider
                """,
                params,
            )
            rows = cur.fetchall()
    return [_credential_row(row) for row in rows]


def revoke_user_oauth_token(provider: str, actor_subject: str) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update user_oauth_tokens
                set revoked_at = now(), updated_at = now()
                where provider = %s and actor_subject = %s and revoked_at is null
                """,
                (provider, actor_subject),
            )
            changed = cur.rowcount
        conn.commit()
    return bool(changed)


def _credential_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}

    result = dict(row)
    for key in ("created_at", "updated_at", "expires_at", "revoked_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    result["connected"] = not bool(result.get("revoked_at"))
    return result
