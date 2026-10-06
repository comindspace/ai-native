import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.file_transfers import (
    create_download_session,
    create_upload_session,
    download_for_actor,
    upload_for_actor,
)
from gateway_mcp.tools.runtime import ToolRun


def register_file_tools(mcp) -> None:
    @mcp.tool(annotations=ToolAnnotations(title="Gateway File Upload Create"))
    async def gateway_file_upload_create(
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> str:
        """Create a short-lived one-time HTTP upload session for a binary file."""
        tool = "gateway_file_upload_create"
        run = ToolRun.start(
            tool=tool,
            system="files",
            scope="files:write",
            arguments={
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "sha256": sha256,
            },
        )
        try:
            actor = run.require_scope()
            upload = create_upload_session(
                actor=actor,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                sha256=sha256,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "upload": upload}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway File Upload Status", readOnlyHint=True
        )
    )
    async def gateway_file_upload_status(upload_id: str) -> str:
        """Get a file upload session owned by the current actor."""
        tool = "gateway_file_upload_status"
        run = ToolRun.start(
            tool=tool,
            system="files",
            scope="files:read",
            arguments={"upload_id": upload_id},
        )
        try:
            actor = run.require_scope()
            upload = upload_for_actor(actor=actor, upload_id=upload_id)
            run.finish()
            return json.dumps(
                {"ok": True, "upload": upload}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway File Download Create", readOnlyHint=True
        )
    )
    async def gateway_file_download_create(upload_id: str) -> str:
        """Create a one-time HTTP download session for a completed upload."""
        tool = "gateway_file_download_create"
        run = ToolRun.start(
            tool=tool,
            system="files",
            scope="files:read",
            arguments={"upload_id": upload_id},
        )
        try:
            actor = run.require_scope()
            download = create_download_session(actor=actor, upload_id=upload_id)
            run.finish()
            return json.dumps(
                {"ok": True, "download": download}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway File Download Status", readOnlyHint=True
        )
    )
    async def gateway_file_download_status(download_id: str) -> str:
        """Get a file download session owned by the current actor."""
        tool = "gateway_file_download_status"
        run = ToolRun.start(
            tool=tool,
            system="files",
            scope="files:read",
            arguments={"download_id": download_id},
        )
        try:
            actor = run.require_scope()
            download = download_for_actor(actor=actor, download_id=download_id)
            run.finish()
            return json.dumps(
                {"ok": True, "download": download}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
