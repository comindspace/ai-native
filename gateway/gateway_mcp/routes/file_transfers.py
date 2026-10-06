from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from gateway_mcp.services.file_transfers import (
    max_file_bytes,
    safe_upload_path,
    token_hash,
)
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.storage_file_transfers import (
    claim_download_session,
    claim_upload_session,
    complete_download_session,
    complete_upload_session,
    fail_download_session,
    fail_upload_session,
    get_upload_session,
)


def register_file_transfer_routes(mcp: Any) -> None:
    @mcp.custom_route(
        "/files/uploads/{upload_id}", methods=["PUT"], include_in_schema=False
    )
    async def upload_file(request: Request) -> Response:
        upload_id = str(request.path_params.get("upload_id") or "")
        token = str(request.headers.get("x-gateway-upload-token") or "").strip()
        if not _valid_uuid(upload_id):
            return _error(401, "invalid_upload_token")
        session = (
            claim_upload_session(upload_id=upload_id, token_hash=token_hash(token))
            if token
            else None
        )
        if not session:
            return _error(401, "invalid_upload_token")
        actor = GatewayActor(subject=str(session.get("actor_subject") or ""))
        expected_size = int(session.get("expected_size_bytes") or 0)
        content_length = _content_length(request)
        if content_length is not None and content_length != expected_size:
            fail_upload_session(upload_id, error_code="size_mismatch")
            _audit_upload(actor, session, status="error", error="size_mismatch")
            return _error(400, "size_mismatch")

        destination: Path | None = None
        temporary: Path | None = None
        try:
            destination = safe_upload_path(session.get("storage_path"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".part")
            temporary.unlink(missing_ok=True)
            size, digest = await _receive(
                request,
                destination=temporary,
                max_bytes=min(expected_size, max_file_bytes()),
            )
            if size != expected_size:
                raise ValueError("size_mismatch")
            if digest != str(session.get("expected_sha256") or ""):
                raise ValueError("sha256_mismatch")
            os.replace(temporary, destination)
            row = complete_upload_session(
                upload_id=upload_id, size_bytes=size, sha256=digest
            )
            _audit_upload(actor, session, status="ok")
            return JSONResponse(
                {
                    "ok": True,
                    "upload_id": upload_id,
                    "state": row.get("state"),
                    "size_bytes": size,
                    "sha256": digest,
                },
                status_code=201,
            )
        except ValueError as exc:
            code = str(exc)
            fail_upload_session(upload_id, error_code=code)
            _audit_upload(actor, session, status="error", error=code)
            return _error(413 if code == "upload_too_large" else 400, code)
        except Exception as exc:  # noqa: BLE001 - HTTP boundary records a safe error class
            code = exc.__class__.__name__
            fail_upload_session(upload_id, error_code=code)
            _audit_upload(actor, session, status="error", error=code)
            return _error(500, "upload_failed")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @mcp.custom_route(
        "/files/downloads/{download_id}", methods=["GET"], include_in_schema=False
    )
    async def download_file(request: Request) -> Response:
        download_id = str(request.path_params.get("download_id") or "")
        token = str(request.headers.get("x-gateway-download-token") or "").strip()
        if not _valid_uuid(download_id):
            return _error(401, "invalid_download_token")
        session = (
            claim_download_session(
                download_id=download_id, token_hash=token_hash(token)
            )
            if token
            else None
        )
        if not session:
            return _error(401, "invalid_download_token")
        actor = GatewayActor(subject=str(session.get("actor_subject") or ""))
        upload = get_upload_session(str(session.get("upload_id") or ""))
        if not upload or str(upload.get("actor_subject") or "") != actor.subject:
            fail_download_session(download_id, error_code="source_not_found")
            return _error(404, "source_not_found")
        try:
            path = safe_upload_path(upload.get("storage_path"))
            if not path.is_file():
                raise FileNotFoundError
            _audit_download(actor, session, status="ok")
            return StreamingResponse(
                _stream_download(download_id, path),
                media_type=str(
                    session.get("content_type") or "application/octet-stream"
                ),
                headers={
                    "Content-Disposition": _content_disposition(
                        str(session.get("filename") or "download.bin")
                    ),
                    "Content-Length": str(
                        session.get("size_bytes") or path.stat().st_size
                    ),
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except FileNotFoundError:
            fail_download_session(download_id, error_code="source_not_found")
            _audit_download(actor, session, status="error", error="source_not_found")
            return _error(404, "source_not_found")
        except Exception as exc:  # noqa: BLE001 - HTTP boundary records a safe error class
            code = exc.__class__.__name__
            fail_download_session(download_id, error_code=code)
            _audit_download(actor, session, status="error", error=code)
            return _error(500, "download_failed")


async def _receive(
    request: Request, *, destination: Path, max_bytes: int
) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with destination.open("xb") as stream:
        async for chunk in request.stream():
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("upload_too_large")
            digest.update(chunk)
            stream.write(chunk)
    if size <= 0:
        raise ValueError("empty_upload")
    return size, digest.hexdigest()


async def _stream_download(download_id: str, path: Path) -> AsyncIterator[bytes]:
    completed = False
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        completed = True
    finally:
        if completed:
            complete_download_session(download_id)
        else:
            fail_download_session(download_id, error_code="stream_interrupted")


def _content_length(request: Request) -> int | None:
    raw = str(request.headers.get("content-length") or "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _content_disposition(filename: str) -> str:
    ascii_name = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\"} else "_"
        for char in filename
    )
    return f"attachment; filename=\"{ascii_name or 'download.bin'}\"; filename*=UTF-8''{quote(filename)}"


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _audit_upload(
    actor: GatewayActor,
    session: dict[str, Any],
    *,
    status: str,
    error: str = "",
) -> None:
    audit_event(
        event="file_upload",
        actor=actor,
        tool="gateway_file_upload_create",
        system="files",
        decision="allow",
        status=status,
        scope="files:write",
        arguments={
            "upload_id": str(session.get("upload_id") or ""),
            "size_bytes": session.get("expected_size_bytes"),
            "sha256": session.get("expected_sha256"),
        },
        error=error,
    )


def _audit_download(
    actor: GatewayActor,
    session: dict[str, Any],
    *,
    status: str,
    error: str = "",
) -> None:
    audit_event(
        event="file_download",
        actor=actor,
        tool="gateway_file_download_create",
        system="files",
        decision="allow",
        status=status,
        scope="files:read",
        arguments={"download_id": str(session.get("download_id") or "")},
        error=error,
    )


def _error(status_code: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": code}, status_code=status_code)
