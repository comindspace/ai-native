import json
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled
from gateway_mcp.services.storage_crypto import _decrypt_secret, _encrypt_secret


def list_infra_servers(*, query: str = "", environment: str = "", limit: int = 50) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP infra registry")

    ensure_schema()
    where = ["revoked_at is null"]
    params: list[Any] = []
    if environment:
        where.append("environment = %s")
        params.append(environment)
    if query:
        like = f"%{query}%"
        where.append("(id ilike %s or hostname ilike %s or address ilike %s or role ilike %s or owner ilike %s)")
        params.extend([like, like, like, like, like])

    params.append(max(1, min(int(limit), 200)))
    sql = f"""
        select id, hostname, address, environment, role, owner, metadata, created_at, updated_at
        from infra_servers
        where {' and '.join(where)}
        order by environment, id
        limit %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_infra_row(row) for row in rows]


def get_infra_server(server_id: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP infra registry")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, hostname, address, environment, role, owner, metadata, created_at, updated_at
                from infra_servers
                where id = %s and revoked_at is null
                """,
                (server_id,),
            )
            row = cur.fetchone()
    return _infra_row(row) if row else None


def get_ssh_credential(handle: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP infra credentials")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select c.handle, c.server_id, c.username, c.private_key_path_encrypted,
                       c.allowlist, c.metadata, s.address, s.hostname
                from infra_ssh_credentials c
                join infra_servers s on s.id = c.server_id
                where c.handle = %s
                  and c.revoked_at is null
                  and s.revoked_at is null
                """,
                (handle,),
            )
            row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    result["private_key_path"] = _decrypt_secret(str(result.pop("private_key_path_encrypted")))
    return result


def upsert_infra_server(
    *,
    server_id: str,
    hostname: str,
    address: str,
    environment: str,
    role: str,
    owner: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP infra registry")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into infra_servers (id, hostname, address, environment, role, owner, metadata)
                values (%s, %s, %s, %s, %s, %s, %s::jsonb)
                on conflict (id)
                do update set
                    hostname = excluded.hostname,
                    address = excluded.address,
                    environment = excluded.environment,
                    role = excluded.role,
                    owner = excluded.owner,
                    metadata = excluded.metadata,
                    updated_at = now(),
                    revoked_at = null
                returning id, hostname, address, environment, role, owner, metadata, created_at, updated_at
                """,
                (
                    server_id,
                    hostname,
                    address,
                    environment,
                    role,
                    owner,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _infra_row(row)


def upsert_ssh_credential(
    *,
    handle: str,
    server_id: str,
    username: str,
    private_key_path: str,
    allowlist: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP infra credentials")

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into infra_ssh_credentials (
                    handle, server_id, username, private_key_path_encrypted, allowlist, metadata
                )
                values (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                on conflict (handle)
                do update set
                    server_id = excluded.server_id,
                    username = excluded.username,
                    private_key_path_encrypted = excluded.private_key_path_encrypted,
                    allowlist = excluded.allowlist,
                    metadata = excluded.metadata,
                    updated_at = now(),
                    revoked_at = null
                returning handle, server_id, username, allowlist, metadata, created_at, updated_at
                """,
                (
                    handle,
                    server_id,
                    username,
                    _encrypt_secret(private_key_path),
                    json.dumps(allowlist or [], ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    result = dict(row)
    for key in ("created_at", "updated_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _infra_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = dict(row)
    for key in ("created_at", "updated_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result
