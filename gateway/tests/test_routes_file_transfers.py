import asyncio
import hashlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods, include_in_schema=False):
        def decorator(func):
            self.routes[path] = {"func": func, "methods": methods}
            return func

        return decorator


class UploadRequest:
    def __init__(self, upload_id: str, token: str, content: bytes) -> None:
        self.path_params = {"upload_id": upload_id}
        self.headers = {
            "x-gateway-upload-token": token,
            "content-length": str(len(content)),
        }
        self._content = content

    async def stream(self):
        yield self._content[:3]
        yield self._content[3:]


class DownloadRequest:
    def __init__(self, download_id: str, token: str) -> None:
        self.path_params = {"download_id": download_id}
        self.headers = {"x-gateway-download-token": token}


async def _consume(stream) -> bytes:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


class FileTransferRouteTests(unittest.TestCase):
    def test_upload_stream_verifies_size_and_checksum(self) -> None:
        from gateway_mcp.routes.file_transfers import register_file_transfer_routes

        fake = FakeMcp()
        register_file_transfer_routes(fake)
        upload_id = "4d2f22bd-f4af-41e5-a23e-d95c4e99e0f5"
        content = b"binary-content"
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / upload_id
            session = {
                "upload_id": upload_id,
                "actor_subject": "yandex:1",
                "expected_size_bytes": len(content),
                "expected_sha256": hashlib.sha256(content).hexdigest(),
                "storage_path": str(destination),
            }
            with (
                patch.dict(os.environ, {"GATEWAY_FILE_TRANSFER_DIR": tmp}, clear=False),
                patch(
                    "gateway_mcp.routes.file_transfers.claim_upload_session",
                    return_value=session,
                ),
                patch(
                    "gateway_mcp.routes.file_transfers.complete_upload_session",
                    return_value={"state": "succeeded"},
                ) as complete,
                patch("gateway_mcp.routes.file_transfers.audit_event"),
            ):
                response = asyncio.run(
                    fake.routes["/files/uploads/{upload_id}"]["func"](
                        UploadRequest(upload_id, "one-time-token", content)
                    )
                )
            stored = destination.read_bytes()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(stored, content)
        complete.assert_called_once_with(
            upload_id=upload_id,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def test_upload_rejects_invalid_token_without_writing(self) -> None:
        from gateway_mcp.routes.file_transfers import register_file_transfer_routes

        fake = FakeMcp()
        register_file_transfer_routes(fake)
        upload_id = "4d2f22bd-f4af-41e5-a23e-d95c4e99e0f5"
        with patch(
            "gateway_mcp.routes.file_transfers.claim_upload_session",
            return_value=None,
        ):
            response = asyncio.run(
                fake.routes["/files/uploads/{upload_id}"]["func"](
                    UploadRequest(upload_id, "wrong", b"content")
                )
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.body["error"], "invalid_upload_token")

    def test_download_stream_is_one_time_and_completes_after_read(self) -> None:
        from gateway_mcp.routes.file_transfers import register_file_transfer_routes

        fake = FakeMcp()
        register_file_transfer_routes(fake)
        download_id = "13b940bb-2f40-4e2b-a4fb-3f6264f6f041"
        upload_id = "4d2f22bd-f4af-41e5-a23e-d95c4e99e0f5"
        content = b"download-content"
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / upload_id
            source.write_bytes(content)
            download = {
                "download_id": download_id,
                "upload_id": upload_id,
                "actor_subject": "yandex:1",
                "filename": "result.bin",
                "content_type": "application/octet-stream",
                "size_bytes": len(content),
            }
            upload = {
                "upload_id": upload_id,
                "actor_subject": "yandex:1",
                "storage_path": str(source),
            }
            with (
                patch.dict(os.environ, {"GATEWAY_FILE_TRANSFER_DIR": tmp}, clear=False),
                patch(
                    "gateway_mcp.routes.file_transfers.claim_download_session",
                    return_value=download,
                ),
                patch(
                    "gateway_mcp.routes.file_transfers.get_upload_session",
                    return_value=upload,
                ),
                patch(
                    "gateway_mcp.routes.file_transfers.complete_download_session"
                ) as complete,
                patch("gateway_mcp.routes.file_transfers.audit_event"),
            ):
                response = asyncio.run(
                    fake.routes["/files/downloads/{download_id}"]["func"](
                        DownloadRequest(download_id, "one-time-token")
                    )
                )
                received = asyncio.run(_consume(response.body))

        self.assertEqual(received, content)
        complete.assert_called_once_with(download_id)


if __name__ == "__main__":
    unittest.main()
