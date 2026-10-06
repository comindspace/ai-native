import hashlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import file_transfers
from gateway_mcp.services.policy import GatewayActor


class FileTransferTests(unittest.TestCase):
    def test_create_upload_returns_one_time_transport_without_storage_path(
        self,
    ) -> None:
        actor = GatewayActor(subject="yandex:1", scopes=("files:read", "files:write"))
        content = b"proposal"
        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_FILE_TRANSFER_DIR": tmp}, clear=False),
            patch.object(
                file_transfers,
                "insert_upload_session",
                return_value={"expires_at": "2026-09-04T11:00:00+00:00"},
            ) as insert,
        ):
            result = file_transfers.create_upload_session(
                actor=actor,
                filename="../proposal.pdf",
                content_type="application/pdf",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )

        self.assertEqual(result["method"], "PUT")
        self.assertEqual(result["upload_token_header"], "X-Gateway-Upload-Token")
        self.assertNotIn("storage_path", result)
        self.assertNotIn(result["upload_token"], repr(insert.call_args.kwargs))
        self.assertEqual(insert.call_args.kwargs["original_filename"], "proposal.pdf")

    def test_upload_status_is_private_to_owner(self) -> None:
        owner = GatewayActor(subject="yandex:1")
        outsider = GatewayActor(subject="yandex:2")
        row = {
            "upload_id": "4d2f22bd-f4af-41e5-a23e-d95c4e99e0f5",
            "actor_subject": owner.subject,
            "state": "succeeded",
        }
        with (
            patch.object(file_transfers, "get_upload_session", return_value=row),
            self.assertRaises(PermissionError),
        ):
            file_transfers.upload_for_actor(actor=outsider, upload_id=row["upload_id"])

    def test_ready_file_requires_completed_unexpired_session(self) -> None:
        actor = GatewayActor(subject="yandex:1")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "file-id"
            path.write_bytes(b"content")
            row = {
                "upload_id": "4d2f22bd-f4af-41e5-a23e-d95c4e99e0f5",
                "actor_subject": actor.subject,
                "state": "succeeded",
                "storage_path": str(path),
                "original_filename": "file.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 7,
                "sha256": hashlib.sha256(b"content").hexdigest(),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat(),
            }
            with (
                patch.dict(os.environ, {"GATEWAY_FILE_TRANSFER_DIR": tmp}, clear=False),
                patch.object(file_transfers, "get_upload_session", return_value=row),
            ):
                resolved, public = file_transfers.ready_file_for_actor(
                    actor=actor,
                    upload_id=row["upload_id"],
                )
        self.assertEqual(resolved, path.resolve())
        self.assertEqual(public["filename"], "file.bin")

    def test_download_token_is_stored_only_as_hash(self) -> None:
        actor = GatewayActor(subject="yandex:1")
        upload = {
            "upload_id": "4d2f22bd-f4af-41e5-a23e-d95c4e99e0f5",
            "filename": "file.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 7,
            "sha256": hashlib.sha256(b"content").hexdigest(),
        }
        with (
            patch.object(
                file_transfers,
                "ready_file_for_actor",
                return_value=(Path("file"), upload),
            ),
            patch.object(
                file_transfers,
                "insert_download_session",
                return_value={"expires_at": "2026-09-04T11:00:00+00:00"},
            ) as insert,
        ):
            result = file_transfers.create_download_session(
                actor=actor, upload_id=upload["upload_id"]
            )
        self.assertEqual(result["method"], "GET")
        self.assertEqual(result["download_token_header"], "X-Gateway-Download-Token")
        self.assertNotIn(result["download_token"], repr(insert.call_args.kwargs))

    def test_cleanup_removes_only_paths_inside_transfer_root(self) -> None:
        with TemporaryDirectory() as tmp:
            inside = Path(tmp) / "expired-upload"
            outside = Path(tmp).parent / "must-not-delete"
            inside.write_bytes(b"expired")
            outside.write_bytes(b"keep")
            with (
                patch.dict(os.environ, {"GATEWAY_FILE_TRANSFER_DIR": tmp}, clear=False),
                patch.object(
                    file_transfers,
                    "expire_file_transfer_sessions",
                    return_value=[str(inside), str(outside)],
                ),
            ):
                removed = file_transfers.cleanup_expired_transfers()
            self.assertEqual(removed, 1)
            self.assertFalse(inside.exists())
            self.assertTrue(outside.exists())
            outside.unlink()


if __name__ == "__main__":
    unittest.main()
