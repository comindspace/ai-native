from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway_mcp.config import public_url
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage_file_transfers import (
    expire_file_transfer_sessions,
    get_download_session,
    get_upload_session,
    insert_download_session,
    insert_upload_session,
)

SHA256_RE = re.compile(r"[0-9a-f]{64}")
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_UPLOAD_TTL_SECONDS = 3600
DEFAULT_DOWNLOAD_TTL_SECONDS = 300


def create_upload_session(
    *,
    actor: GatewayActor,
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    cleanup_expired_transfers()
    clean_filename = _filename(filename)
    clean_content_type = _content_type(content_type)
    expected_size = int(size_bytes)
    if expected_size <= 0:
        raise ValueError("size_bytes must be positive")
    if expected_size > max_file_bytes():
        raise ValueError("File exceeds the configured transfer limit")
    expected_sha256 = str(sha256 or "").strip().casefold()
    if not SHA256_RE.fullmatch(expected_sha256):
        raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")

    upload_id = str(uuid.uuid4())
    upload_token = secrets.token_urlsafe(32)
    storage_path = upload_root() / upload_id
    row = insert_upload_session(
        upload_id=upload_id,
        actor_subject=actor.subject,
        upload_token_hash=token_hash(upload_token),
        original_filename=clean_filename,
        content_type=clean_content_type,
        expected_size_bytes=expected_size,
        expected_sha256=expected_sha256,
        storage_path=str(storage_path),
        ttl_seconds=upload_ttl_seconds(),
    )
    return {
        "upload_id": upload_id,
        "upload_url": f"{public_url().rstrip('/')}/files/uploads/{upload_id}",
        "upload_token": upload_token,
        "upload_token_header": "X-Gateway-Upload-Token",
        "method": "PUT",
        "content_type": clean_content_type,
        "size_bytes": expected_size,
        "sha256": expected_sha256,
        "max_bytes": max_file_bytes(),
        "expires_at": row.get("expires_at"),
    }


def upload_for_actor(*, actor: GatewayActor, upload_id: str) -> dict[str, Any]:
    cleanup_expired_transfers()
    return public_upload(upload_session_for_actor(actor=actor, upload_id=upload_id))


def upload_session_for_actor(*, actor: GatewayActor, upload_id: str) -> dict[str, Any]:
    normalized = _uuid(upload_id, name="upload_id")
    row = get_upload_session(normalized)
    if not row:
        raise FileNotFoundError("Upload session was not found")
    if str(row.get("actor_subject") or "") != actor.subject and not has_scope(
        actor, "access:admin"
    ):
        raise PermissionError("Upload session is not visible to this actor")
    return row


def ready_file_for_actor(
    *, actor: GatewayActor, upload_id: str
) -> tuple[Path, dict[str, Any]]:
    cleanup_expired_transfers()
    row = upload_session_for_actor(actor=actor, upload_id=upload_id)
    if _is_expired(row):
        raise ValueError("Upload session has expired")
    if str(row.get("state") or "") != "succeeded":
        raise ValueError("Upload session is not ready")
    path = safe_upload_path(row.get("storage_path"))
    if not path.is_file():
        raise FileNotFoundError("Uploaded file is no longer available")
    return path, public_upload(row)


def create_download_session(*, actor: GatewayActor, upload_id: str) -> dict[str, Any]:
    _, upload = ready_file_for_actor(actor=actor, upload_id=upload_id)
    download_id = str(uuid.uuid4())
    download_token = secrets.token_urlsafe(32)
    row = insert_download_session(
        download_id=download_id,
        actor_subject=actor.subject,
        download_token_hash=token_hash(download_token),
        upload_id=upload["upload_id"],
        filename=upload["filename"],
        content_type=upload["content_type"],
        size_bytes=int(upload["size_bytes"] or 0),
        sha256=upload["sha256"],
        ttl_seconds=download_ttl_seconds(),
    )
    return {
        "download_id": download_id,
        "download_url": f"{public_url().rstrip('/')}/files/downloads/{download_id}",
        "download_token": download_token,
        "download_token_header": "X-Gateway-Download-Token",
        "method": "GET",
        "one_time": True,
        "filename": upload["filename"],
        "content_type": upload["content_type"],
        "size_bytes": upload["size_bytes"],
        "sha256": upload["sha256"],
        "expires_at": row.get("expires_at"),
    }


def download_for_actor(*, actor: GatewayActor, download_id: str) -> dict[str, Any]:
    cleanup_expired_transfers()
    normalized = _uuid(download_id, name="download_id")
    row = get_download_session(normalized)
    if not row:
        raise FileNotFoundError("Download session was not found")
    if str(row.get("actor_subject") or "") != actor.subject and not has_scope(
        actor, "access:admin"
    ):
        raise PermissionError("Download session is not visible to this actor")
    return public_download(row)


def public_upload(row: dict[str, Any]) -> dict[str, Any]:
    state = (
        "expired"
        if _is_expired(row)
        and str(row.get("state")) in {"pending", "uploading", "succeeded"}
        else str(row.get("state") or "")
    )
    return {
        "upload_id": str(row.get("upload_id") or ""),
        "state": state,
        "filename": str(row.get("original_filename") or ""),
        "content_type": str(row.get("content_type") or ""),
        "expected_size_bytes": row.get("expected_size_bytes"),
        "expected_sha256": str(row.get("expected_sha256") or ""),
        "size_bytes": row.get("size_bytes"),
        "sha256": str(row.get("sha256") or ""),
        "error_code": str(row.get("error_code") or ""),
        "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
        "expires_at": row.get("expires_at"),
    }


def public_download(row: dict[str, Any]) -> dict[str, Any]:
    state = (
        "expired"
        if _is_expired(row) and str(row.get("state")) in {"pending", "downloading"}
        else str(row.get("state") or "")
    )
    return {
        "download_id": str(row.get("download_id") or ""),
        "upload_id": str(row.get("upload_id") or ""),
        "state": state,
        "filename": str(row.get("filename") or ""),
        "content_type": str(row.get("content_type") or ""),
        "size_bytes": row.get("size_bytes"),
        "sha256": str(row.get("sha256") or ""),
        "error_code": str(row.get("error_code") or ""),
        "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
        "expires_at": row.get("expires_at"),
    }


def cleanup_expired_transfers() -> int:
    removed = 0
    for value in expire_file_transfer_sessions():
        if not value:
            continue
        try:
            path = safe_upload_path(value)
        except RuntimeError:
            continue
        if path.is_file():
            path.unlink(missing_ok=True)
            removed += 1
        path.with_suffix(".part").unlink(missing_ok=True)
    return removed


def configured_upload_root() -> Path:
    return Path(os.getenv("GATEWAY_FILE_TRANSFER_DIR", "/data/gateway/files")).resolve()


def upload_root() -> Path:
    path = configured_upload_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_upload_path(value: Any) -> Path:
    root = configured_upload_root()
    path = Path(str(value or "")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("File path is outside the Gateway transfer root") from exc
    return path


def max_file_bytes() -> int:
    return max(
        1,
        int(os.getenv("GATEWAY_FILE_TRANSFER_MAX_BYTES", str(DEFAULT_MAX_FILE_BYTES))),
    )


def upload_ttl_seconds() -> int:
    return min(
        86400,
        max(
            60,
            int(
                os.getenv(
                    "GATEWAY_FILE_UPLOAD_TTL_SECONDS", str(DEFAULT_UPLOAD_TTL_SECONDS)
                )
            ),
        ),
    )


def download_ttl_seconds() -> int:
    return min(
        3600,
        max(
            60,
            int(
                os.getenv(
                    "GATEWAY_FILE_DOWNLOAD_TTL_SECONDS",
                    str(DEFAULT_DOWNLOAD_TTL_SECONDS),
                )
            ),
        ),
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _filename(value: str) -> str:
    filename = Path(str(value or "")).name.strip()[:255]
    if not filename or filename in {".", ".."}:
        raise ValueError("A valid filename is required")
    return filename


def _content_type(value: str) -> str:
    content_type = str(value or "application/octet-stream").strip()[:128]
    if "\r" in content_type or "\n" in content_type:
        raise ValueError("content_type must not contain line breaks")
    return content_type or "application/octet-stream"


def _uuid(value: str, *, name: str) -> str:
    try:
        return str(uuid.UUID(str(value or "").strip()))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid UUID") from exc


def _is_expired(row: dict[str, Any]) -> bool:
    raw = row.get("expires_at")
    if not raw:
        return False
    parsed = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc)
