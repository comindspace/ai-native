import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.access_requests import (
    access_profile,
    admin_decide_access_request,
    admin_list_access_requests,
    cancel_my_access_request,
    list_my_access_requests,
    public_access_package_catalog,
    request_access_package,
)
from gateway_mcp.tools.runtime import ToolRun


def register_access_request_tools(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Access Profile", readOnlyHint=True)
    )
    async def gateway_access_profile() -> str:
        """Show the current authenticated identity, effective scopes, access packages, and recent access requests."""
        run = ToolRun.start(
            tool="gateway_access_profile",
            system="access",
            scope="access:request",
            arguments={},
        )
        try:
            actor = run.require_scope()
            result = access_profile(actor)
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Access Package Catalog", readOnlyHint=True
        )
    )
    async def gateway_access_package_catalog() -> str:
        """List business access packages that an employee may request."""
        run = ToolRun.start(
            tool="gateway_access_package_catalog",
            system="access",
            scope="access:request",
            arguments={},
        )
        try:
            run.require_scope()
            packages = public_access_package_catalog()
            run.finish()
            return _json({"ok": True, "count": len(packages), "packages": packages})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Request Access Package"))
    async def gateway_access_request_create(
        package_key: str,
        reason: str,
        ttl_days: int = 0,
        idempotency_key: str = "",
    ) -> str:
        """Request a versioned business access package for the current user. This never grants access automatically."""
        arguments = {
            "package_key": package_key,
            "reason": reason,
            "ttl_days": ttl_days,
            "idempotency_key": idempotency_key,
        }
        run = ToolRun.start(
            tool="gateway_access_request_create",
            system="access",
            scope="access:request",
            arguments=arguments,
        )
        try:
            actor = run.require_scope()
            result = request_access_package(
                actor=actor,
                package_key=package_key,
                reason=reason,
                ttl_days=ttl_days or None,
                idempotency_key=idempotency_key,
            )
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway My Access Requests", readOnlyHint=True
        )
    )
    async def gateway_access_request_list(status: str = "", limit: int = 50) -> str:
        """List access requests created by the current user."""
        run = ToolRun.start(
            tool="gateway_access_request_list",
            system="access",
            scope="access:request",
            arguments={"status": status, "limit": limit},
        )
        try:
            actor = run.require_scope()
            result = list_my_access_requests(actor=actor, status=status, limit=limit)
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Cancel Access Request"))
    async def gateway_access_request_cancel(request_id: str, reason: str = "") -> str:
        """Cancel one pending access request owned by the current user."""
        run = ToolRun.start(
            tool="gateway_access_request_cancel",
            system="access",
            scope="access:request",
            arguments={"request_id": request_id, "reason": reason},
        )
        try:
            actor = run.require_scope()
            result = cancel_my_access_request(
                actor=actor, request_id=request_id, reason=reason
            )
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Admin Access Requests", readOnlyHint=True
        )
    )
    async def gateway_admin_access_request_list(
        requester_subject: str = "",
        status: str = "pending",
        package_key: str = "",
        limit: int = 100,
    ) -> str:
        """List employee access requests. Requires access:read."""
        arguments = {
            "requester_subject": requester_subject,
            "status": status,
            "package_key": package_key,
            "limit": limit,
        }
        run = ToolRun.start(
            tool="gateway_admin_access_request_list",
            system="access",
            scope="access:read",
            arguments=arguments,
        )
        try:
            run.require_scope()
            result = admin_list_access_requests(**arguments)
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin Decide Access Request"))
    async def gateway_admin_access_request_decide(
        request_id: str,
        decision: str,
        reason: str,
        dry_run: bool = True,
    ) -> str:
        """Approve or reject one pending access request. Requires access:admin and defaults to dry-run."""
        arguments = {
            "request_id": request_id,
            "decision": decision,
            "reason": reason,
            "dry_run": dry_run,
        }
        run = ToolRun.start(
            tool="gateway_admin_access_request_decide",
            system="access",
            scope="access:admin",
            arguments=arguments,
        )
        try:
            actor = run.require_scope()
            result = admin_decide_access_request(actor=actor, **arguments)
            run.finish(status="dry_run" if dry_run else "ok")
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
