import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.access import (
    admin_grant_access_package,
    admin_grant_resource,
    admin_grant_scope,
    admin_list_access,
    admin_list_access_packages,
    admin_revoke_access_package,
    admin_revoke_resource,
    admin_revoke_scope,
    explain_resource_access,
)
from gateway_mcp.services.access_packages import access_package_catalog
from gateway_mcp.services.auth import actor_payload
from gateway_mcp.services.storage import audit_event_summary, list_audit_events
from gateway_mcp.access_context import actor_for_access_explain
from gateway_mcp.tools.runtime import ToolRun


def register_access_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin List Access", readOnlyHint=True))
    async def gateway_admin_list_access(
        subject_type: str = "",
        subject_key: str = "",
        system: str = "",
        include_revoked: bool = False,
        limit: int = 100,
    ) -> str:
        """List DB-backed GatewayMCP scope and resource grants. Requires access:read."""
        tool = "gateway_admin_list_access"
        scope = "access:read"
        run = ToolRun.start(
            tool=tool,
            system="access",
            scope=scope,
            arguments={
                "subject_type": subject_type,
                "subject_key": subject_key,
                "system": system,
                "include_revoked": include_revoked,
                "limit": limit,
            },
        )
        try:
            run.require_scope()
            result = admin_list_access(
                subject_type=subject_type,
                subject_key=subject_key,
                system=system,
                include_revoked=include_revoked,
                limit=limit,
            )
            run.finish()
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
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
    async def gateway_admin_access_package_catalog() -> str:
        """List versioned business access packages. Requires access:read."""
        run = ToolRun.start(
            tool="gateway_admin_access_package_catalog",
            system="access",
            scope="access:read",
            arguments={},
        )
        try:
            run.require_scope()
            packages = access_package_catalog()
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(packages), "packages": packages},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Grant Access Package"))
    async def gateway_admin_grant_access_package(
        subject_type: str,
        subject_key: str,
        package_key: str,
        reason: str,
        ttl_days: int = 0,
        dry_run: bool = True,
    ) -> str:
        """Assign a complete business access package atomically. Requires access:admin."""
        run = ToolRun.start(
            tool="gateway_admin_grant_access_package",
            system="access",
            scope="access:admin",
            arguments={
                "subject_type": subject_type,
                "subject_key": subject_key,
                "package_key": package_key,
                "reason": reason,
                "ttl_days": ttl_days,
                "dry_run": dry_run,
            },
        )
        try:
            actor = run.require_scope()
            result = admin_grant_access_package(
                subject_type=subject_type,
                subject_key=subject_key,
                package_key=package_key,
                reason=reason,
                actor=actor,
                ttl_days=ttl_days or None,
                dry_run=dry_run,
            )
            run.finish(status="dry_run" if dry_run else "ok")
            return json.dumps(
                {"ok": True, **result},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway List Access Packages", readOnlyHint=True
        )
    )
    async def gateway_admin_list_access_packages(
        subject_type: str = "",
        subject_key: str = "",
        include_revoked: bool = False,
        limit: int = 100,
    ) -> str:
        """List assigned access packages. Requires access:read."""
        run = ToolRun.start(
            tool="gateway_admin_list_access_packages",
            system="access",
            scope="access:read",
            arguments={
                "subject_type": subject_type,
                "subject_key": subject_key,
                "include_revoked": include_revoked,
                "limit": limit,
            },
        )
        try:
            run.require_scope()
            result = admin_list_access_packages(
                subject_type=subject_type,
                subject_key=subject_key,
                include_revoked=include_revoked,
                limit=limit,
            )
            run.finish()
            return json.dumps(
                {"ok": True, **result},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Revoke Access Package"))
    async def gateway_admin_revoke_access_package(
        bundle_id: str,
        dry_run: bool = True,
    ) -> str:
        """Revoke a package and only the grants created by it. Requires access:admin."""
        run = ToolRun.start(
            tool="gateway_admin_revoke_access_package",
            system="access",
            scope="access:admin",
            arguments={"bundle_id": bundle_id, "dry_run": dry_run},
        )
        try:
            actor = run.require_scope()
            result = admin_revoke_access_package(
                actor=actor,
                bundle_id=bundle_id,
                dry_run=dry_run,
            )
            run.finish(status="dry_run" if dry_run else "ok")
            return json.dumps(
                {"ok": True, **result},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Admin Audit Search", readOnlyHint=True
        )
    )
    async def gateway_admin_audit_search(
        days: int = 7,
        actor_subject: str = "",
        event: str = "",
        tool_name: str = "",
        system: str = "",
        decision: str = "",
        status: str = "",
        gateway_request_id: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> str:
        """Search redacted GatewayMCP audit metadata. Requires telemetry:read."""
        tool = "gateway_admin_audit_search"
        scope = "telemetry:read"
        run = ToolRun.start(
            tool=tool,
            system="audit",
            scope=scope,
            arguments={
                "days": days,
                "actor_subject": actor_subject,
                "event": event,
                "tool_name": tool_name,
                "system": system,
                "decision": decision,
                "status": status,
                "gateway_request_id": gateway_request_id,
                "limit": limit,
                "offset": offset,
            },
        )
        try:
            run.require_scope()
            events = list_audit_events(
                days=days,
                actor_subject=actor_subject,
                event=event,
                tool=tool_name,
                system=system,
                decision=decision,
                status=status,
                gateway_request_id=gateway_request_id,
                limit=limit,
                offset=offset,
                include_payload=False,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(events), "events": events},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Admin Audit Summary", readOnlyHint=True
        )
    )
    async def gateway_admin_audit_summary(
        days: int = 7,
        actor_subject: str = "",
        system: str = "",
        limit: int = 50,
    ) -> str:
        """Summarize audit events by event, tool, system, decision, and status. Requires telemetry:read."""
        tool = "gateway_admin_audit_summary"
        scope = "telemetry:read"
        run = ToolRun.start(
            tool=tool,
            system="audit",
            scope=scope,
            arguments={
                "days": days,
                "actor_subject": actor_subject,
                "system": system,
                "limit": limit,
            },
        )
        try:
            run.require_scope()
            summary = audit_event_summary(
                days=days,
                actor_subject=actor_subject,
                system=system,
                limit=limit,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(summary), "summary": summary},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin Explain Access", readOnlyHint=True))
    async def gateway_admin_explain_access(
        system: str,
        action: str,
        resource: str,
        resource_type: str = "",
        subject_key: str = "",
        groups_json: str = "[]",
    ) -> str:
        """Explain whether a user/group subject can access one MCP resource. Requires access:read."""
        tool = "gateway_admin_explain_access"
        scope = "access:read"
        run = ToolRun.start(
            tool=tool,
            system="access",
            scope=scope,
            arguments={
                "system": system,
                "action": action,
                "resource": resource,
                "resource_type": resource_type,
                "subject_key": subject_key,
                "groups_json": groups_json,
            },
        )
        try:
            run.require_scope()
            actor = actor_for_access_explain(subject_key, groups_json)
            result = explain_resource_access(
                actor=actor,
                system=system,
                action=action,
                resource=resource,
                resource_type=resource_type,
            )
            run.finish()
            return json.dumps({"ok": True, "actor": actor_payload(actor), **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin Grant Scope"))
    async def gateway_admin_grant_scope(
        subject_type: str,
        subject_key: str,
        scope_name: str,
        effect: str = "allow",
        reason: str = "",
        ttl_days: int = 0,
        dry_run: bool = True,
    ) -> str:
        """Grant or deny a Gateway scope through Postgres. Requires access:admin; dry_run defaults to true."""
        tool = "gateway_admin_grant_scope"
        scope = "access:admin"
        run = ToolRun.start(
            tool=tool,
            system="access",
            scope=scope,
            arguments={
                "subject_type": subject_type,
                "subject_key": subject_key,
                "scope_name": scope_name,
                "effect": effect,
                "reason": reason,
                "ttl_days": ttl_days,
                "dry_run": dry_run,
            },
        )
        try:
            actor = run.require_scope()
            result = admin_grant_scope(
                subject_type=subject_type,
                subject_key=subject_key,
                scope=scope_name,
                effect=effect,
                reason=reason,
                actor=actor,
                ttl_days=ttl_days,
                dry_run=dry_run,
            )
            run.finish(status="dry_run" if dry_run else "ok")
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin Revoke Scope"))
    async def gateway_admin_revoke_scope(
        grant_id: int = 0,
        subject_type: str = "",
        subject_key: str = "",
        scope_name: str = "",
        dry_run: bool = True,
    ) -> str:
        """Revoke DB-backed Gateway scope grants. Requires access:admin; dry_run defaults to true."""
        tool = "gateway_admin_revoke_scope"
        scope = "access:admin"
        run = ToolRun.start(
            tool=tool,
            system="access",
            scope=scope,
            arguments={
                "grant_id": grant_id,
                "subject_type": subject_type,
                "subject_key": subject_key,
                "scope_name": scope_name,
                "dry_run": dry_run,
            },
        )
        try:
            actor = run.require_scope()
            result = admin_revoke_scope(
                actor=actor,
                grant_id=grant_id or None,
                subject_type=subject_type,
                subject_key=subject_key,
                scope=scope_name,
                dry_run=dry_run,
            )
            run.finish(status="dry_run" if dry_run else "ok")
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin Grant Resource"))
    async def gateway_admin_grant_resource(
        subject_type: str,
        subject_key: str,
        system: str,
        resource_pattern: str,
        actions_json: str = '["read"]',
        resource_type: str = "",
        effect: str = "allow",
        priority: int = 100,
        reason: str = "",
        ttl_days: int = 0,
        dry_run: bool = True,
    ) -> str:
        """Grant or deny one MCP resource pattern. Requires access:admin; dry_run defaults to true."""
        tool = "gateway_admin_grant_resource"
        scope = "access:admin"
        run = ToolRun.start(
            tool=tool,
            system="access",
            scope=scope,
            arguments={
                "subject_type": subject_type,
                "subject_key": subject_key,
                "system": system,
                "resource_pattern": resource_pattern,
                "actions_json": actions_json,
                "resource_type": resource_type,
                "effect": effect,
                "priority": priority,
                "reason": reason,
                "ttl_days": ttl_days,
                "dry_run": dry_run,
            },
        )
        try:
            actor = run.require_scope()
            result = admin_grant_resource(
                subject_type=subject_type,
                subject_key=subject_key,
                system=system,
                resource_pattern=resource_pattern,
                actions_json=actions_json,
                resource_type=resource_type,
                effect=effect,
                priority=priority,
                reason=reason,
                actor=actor,
                ttl_days=ttl_days,
                dry_run=dry_run,
            )
            run.finish(status="dry_run" if dry_run else "ok")
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Admin Revoke Resource"))
    async def gateway_admin_revoke_resource(
        grant_id: int = 0,
        subject_type: str = "",
        subject_key: str = "",
        system: str = "",
        resource_pattern: str = "",
        dry_run: bool = True,
    ) -> str:
        """Revoke DB-backed MCP resource grants. Requires access:admin; dry_run defaults to true."""
        tool = "gateway_admin_revoke_resource"
        scope = "access:admin"
        run = ToolRun.start(
            tool=tool,
            system="access",
            scope=scope,
            arguments={
                "grant_id": grant_id,
                "subject_type": subject_type,
                "subject_key": subject_key,
                "system": system,
                "resource_pattern": resource_pattern,
                "dry_run": dry_run,
            },
        )
        try:
            actor = run.require_scope()
            result = admin_revoke_resource(
                actor=actor,
                grant_id=grant_id or None,
                subject_type=subject_type,
                subject_key=subject_key,
                system=system,
                resource_pattern=resource_pattern,
                dry_run=dry_run,
            )
            run.finish(status="dry_run" if dry_run else "ok")
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
