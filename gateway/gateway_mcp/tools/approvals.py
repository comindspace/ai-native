import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.approvals import (
    comment_approval,
    create_approval,
    decide_approval,
    get_approval,
    list_visible_approvals,
)
from gateway_mcp.tools.runtime import ToolRun


def register_approval_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Approval Create"))
    async def gateway_approval_create(
        approval_type: str,
        subject: str,
        required_role: str = "",
        required_scope: str = "",
        artifact_hash: str = "",
        artifact_version: str = "",
        payload_json: str = "{}",
        source_refs_json: str = "{}",
        metadata_json: str = "{}",
        four_eyes: bool = True,
        expires_in_days: int = 14,
    ) -> str:
        """Create an approval request for an agent workflow. Requires approvals:write."""
        tool = "gateway_approval_create"
        scope = "approvals:write"
        run = ToolRun.start(
            tool=tool,
            system="approvals",
            scope=scope,
            arguments={
                "approval_type": approval_type,
                "subject": subject,
                "required_role": required_role,
                "required_scope": required_scope,
                "artifact_hash": artifact_hash,
                "artifact_version": artifact_version,
                "source_refs_json": source_refs_json,
                "metadata_json": metadata_json,
                "four_eyes": four_eyes,
                "expires_in_days": expires_in_days,
            },
        )
        try:
            actor = run.require_scope()
            result = create_approval(
                actor=actor,
                approval_type=approval_type,
                subject=subject,
                required_role=required_role,
                required_scope=required_scope,
                artifact_hash=artifact_hash,
                artifact_version=artifact_version,
                payload_json=payload_json,
                source_refs_json=source_refs_json,
                metadata_json=metadata_json,
                four_eyes=four_eyes,
                expires_in_days=expires_in_days,
            )
            run.finish()
            return _response(result)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Approval Get", readOnlyHint=True)
    )
    async def gateway_approval_get(
        approval_id: str, include_events: bool = True
    ) -> str:
        """Read one visible approval and its event history. Requires approvals:read."""
        tool = "gateway_approval_get"
        run = ToolRun.start(
            tool=tool,
            system="approvals",
            scope="approvals:read",
            arguments={"approval_id": approval_id, "include_events": include_events},
        )
        try:
            actor = run.require_scope()
            result = get_approval(
                actor=actor,
                approval_id=approval_id,
                include_events=include_events,
            )
            run.finish()
            return _response(result)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Approval List", readOnlyHint=True)
    )
    async def gateway_approval_list(
        status: str = "pending",
        approval_type: str = "",
        created_by: str = "",
        required_role: str = "",
        assigned_to_me: bool = True,
        limit: int = 50,
    ) -> str:
        """List visible or assigned approval requests. Requires approvals:read."""
        tool = "gateway_approval_list"
        run = ToolRun.start(
            tool=tool,
            system="approvals",
            scope="approvals:read",
            arguments={
                "status": status,
                "approval_type": approval_type,
                "created_by": created_by,
                "required_role": required_role,
                "assigned_to_me": assigned_to_me,
                "limit": limit,
            },
        )
        try:
            actor = run.require_scope()
            result = list_visible_approvals(
                actor=actor,
                status=status,
                approval_type=approval_type,
                created_by=created_by,
                required_role=required_role,
                assigned_to_me=assigned_to_me,
                limit=limit,
            )
            run.finish()
            return _response(result)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Approval Decide"))
    async def gateway_approval_decide(
        approval_id: str,
        decision: str,
        comment: str = "",
        decision_payload_json: str = "{}",
    ) -> str:
        """Approve, reject, or request information. Requires approvals:write."""
        tool = "gateway_approval_decide"
        run = ToolRun.start(
            tool=tool,
            system="approvals",
            scope="approvals:write",
            arguments={
                "approval_id": approval_id,
                "decision": decision,
                "comment": comment,
            },
        )
        try:
            actor = run.require_scope()
            result = decide_approval(
                actor=actor,
                approval_id=approval_id,
                decision=decision,
                comment=comment,
                decision_payload_json=decision_payload_json,
            )
            run.finish(status=str(result.get("approval", {}).get("status") or "ok"))
            return _response(result)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Approval Comment"))
    async def gateway_approval_comment(
        approval_id: str,
        comment: str,
        decision_payload_json: str = "{}",
    ) -> str:
        """Add a clarification or comment to an approval. Requires approvals:write."""
        tool = "gateway_approval_comment"
        run = ToolRun.start(
            tool=tool,
            system="approvals",
            scope="approvals:write",
            arguments={"approval_id": approval_id, "comment": comment},
        )
        try:
            actor = run.require_scope()
            result = comment_approval(
                actor=actor,
                approval_id=approval_id,
                comment=comment,
                decision_payload_json=decision_payload_json,
            )
            run.finish()
            return _response(result)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


def _response(result: dict) -> str:
    return json.dumps(
        {"ok": True, **result},
        ensure_ascii=False,
        separators=(",", ":"),
    )
