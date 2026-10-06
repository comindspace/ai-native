from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def insert_upload_session(
    *,
    upload_id: str,
    actor_subject: str,
    upload_token_hash: str,
    original_filename: str,
    content_type: str,
    expected_size_bytes: int,
    expected_sha256: str,
    storage_path: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into gateway_upload_sessions (
                upload_id, actor_subject, upload_token_hash, original_filename,
                content_type, expected_size_bytes, expected_sha256, storage_path, expires_at
            ) values (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                upload_id,
                actor_subject,
                upload_token_hash,
                original_filename,
                content_type,
                expected_size_bytes,
                expected_sha256,
                storage_path,
                expires_at,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError("Gateway upload session was not created")
    return _row(row)


def get_upload_session(upload_id: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from gateway_upload_sessions where upload_id = %s::uuid",
            (upload_id,),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def claim_upload_session(*, upload_id: str, token_hash: str) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_upload_sessions
            set state = 'uploading', upload_token_hash = upload_token_hash || ':used', error_code = ''
            where upload_id = %s::uuid and upload_token_hash = %s
              and state = 'pending' and expires_at > now()
            returning *
            """,
            (upload_id, token_hash),
        )
        row = cur.fetchone()
        conn.commit()
    return _row(row) if row else None


def complete_upload_session(
    *, upload_id: str, size_bytes: int, sha256: str
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_upload_sessions
            set state = 'succeeded', size_bytes = %s, sha256 = %s,
                uploaded_at = now(), completed_at = now(), error_code = ''
            where upload_id = %s::uuid and state = 'uploading'
            returning *
            """,
            (size_bytes, sha256, upload_id),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError("Gateway upload session is no longer writable")
    return _row(row)


def fail_upload_session(upload_id: str, *, error_code: str) -> None:
    if not postgres_enabled():
        return
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_upload_sessions
            set state = 'failed', error_code = %s, completed_at = now(),
                upload_token_hash = upload_token_hash || ':failed'
            where upload_id = %s::uuid and state in ('pending', 'uploading')
            """,
            (str(error_code or "upload_failed")[:128], upload_id),
        )
        conn.commit()


def insert_download_session(
    *,
    download_id: str,
    actor_subject: str,
    download_token_hash: str,
    upload_id: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    _require_postgres()
    ensure_schema()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into gateway_download_sessions (
                download_id, actor_subject, download_token_hash, upload_id,
                filename, content_type, size_bytes, sha256, expires_at
            ) values (%s::uuid, %s, %s, %s::uuid, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                download_id,
                actor_subject,
                download_token_hash,
                upload_id,
                filename,
                content_type,
                size_bytes,
                sha256,
                expires_at,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError("Gateway download session was not created")
    return _row(row)


def get_download_session(download_id: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from gateway_download_sessions where download_id = %s::uuid",
            (download_id,),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def claim_download_session(
    *, download_id: str, token_hash: str
) -> dict[str, Any] | None:
    _require_postgres()
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_download_sessions
            set state = 'downloading', download_token_hash = download_token_hash || ':used',
                claimed_at = now(), error_code = ''
            where download_id = %s::uuid and download_token_hash = %s
              and state = 'pending' and expires_at > now()
            returning *
            """,
            (download_id, token_hash),
        )
        row = cur.fetchone()
        conn.commit()
    return _row(row) if row else None


def complete_download_session(download_id: str) -> None:
    if not postgres_enabled():
        return
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_download_sessions
            set state = 'succeeded', completed_at = now(), error_code = ''
            where download_id = %s::uuid and state = 'downloading'
            """,
            (download_id,),
        )
        conn.commit()


def fail_download_session(download_id: str, *, error_code: str) -> None:
    if not postgres_enabled():
        return
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_download_sessions
            set state = 'failed', error_code = %s, completed_at = now(),
                download_token_hash = download_token_hash || ':failed'
            where download_id = %s::uuid and state in ('pending', 'downloading')
            """,
            (str(error_code or "download_failed")[:128], download_id),
        )
        conn.commit()


def expire_file_transfer_sessions() -> list[str]:
    """Expire stale one-time sessions and return safe-to-delete upload paths."""
    if not postgres_enabled():
        return []
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update gateway_download_sessions
            set state = 'expired', error_code = 'expired', completed_at = now()
            where expires_at <= now() and state = 'pending'
            """
        )
        cur.execute(
            """
            update gateway_upload_sessions as uploads
            set state = 'expired', error_code = 'expired', completed_at = now()
            where uploads.expires_at <= now()
              and uploads.state in ('pending', 'succeeded')
              and not exists (
                  select 1
                  from gateway_download_sessions as downloads
                  where downloads.upload_id = uploads.upload_id
                    and downloads.state in ('pending', 'downloading')
                    and downloads.expires_at > now()
              )
            returning uploads.storage_path
            """
        )
        rows = cur.fetchall()
        conn.commit()
    return [str(row.get("storage_path") or "") for row in rows if row]


def _require_postgres() -> None:
    if not postgres_enabled():
        raise RuntimeError("Postgres is required for Gateway file transfer sessions")


def _row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif key in {"upload_id", "download_id"} and value is not None:
            result[key] = str(value)
    return result
