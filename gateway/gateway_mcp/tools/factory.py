import json

from mcp.types import ToolAnnotations

from gateway_mcp.config import read_json, tools_file
from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.factory_admin import (
    retry_work,
    upsert_project,
    validate_project,
)
from gateway_mcp.services.factory_projects import (
    discover_factory_projects,
    get_factory_runtime_config,
    resolve_factory_project_by_issue,
)
from gateway_mcp.tools.runtime import ToolRun


def register_factory_tools(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Factory Git Config", readOnlyHint=True
        )
    )
    async def gateway_factory_git_config(work_id: str) -> str:
        """Return a credential-free Git transport URL and assigned work branch.

        Requires factory:git, factory:claim and an active lease owned by this actor.
        The worker authenticates Git to Gateway with its own Gateway token, never a GitLab token.
        """
        from gateway_mcp.services.factory_git import transport_config

        run = ToolRun.start(
            tool="gateway_factory_git_config",
            system="factory",
            scope="factory:git",
            arguments={"work_id": work_id},
        )
        try:
            result = transport_config(current_actor(), work_id)
            run.finish()
            return json.dumps({"ok": True, "transport": result}, ensure_ascii=False)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Factory Connections List", readOnlyHint=True
        )
    )
    async def gateway_factory_connections_list(
        project_id: str, repository_url: str
    ) -> str:
        """List permitted service connection aliases for an exact repository URL.

        Requires Factory project administration. Select connection_id for project_upsert.
        No tokens are returned. Missing connections are managed at /admin/factory/connections.
        """
        from gateway_mcp.services.factory_connections import discover_connections

        run = ToolRun.start(
            tool="gateway_factory_connections_list",
            system="factory",
            scope="factory:projects:write",
            arguments={"project_id": project_id},
        )
        try:
            items = discover_connections(
                actor=current_actor(),
                project_id=project_id,
                repository_url=repository_url,
            )
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    "connections": items,
                    "admin_path": "/admin/factory/connections",
                },
                ensure_ascii=False,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Factory Project Upsert",
            readOnlyHint=False,
            idempotentHint=True,
        )
    )
    async def gateway_factory_project_upsert(
        project_id: str,
        project_path: str,
        gitlab_clone_url: str,
        gitlab_web_url: str,
        default_base_branch: str,
        mr_target_branch: str,
        gitlab_connection_id: str,
        idempotency_key: str,
        metadata_json: str = "{}",
    ) -> str:
        """Register/replace a project; probes clone and push to a disposable codex/readiness-* branch.

        Metadata may contain name, Tracker project/queue, reviewer and Yonote context.
        Requires factory:admin or factory:projects:write. Never returns credentials.
        """
        run = ToolRun.start(
            tool="gateway_factory_project_upsert",
            system="factory",
            scope="factory:projects:write",
            arguments={"project_id": project_id},
        )
        try:
            metadata = json.loads(metadata_json)
            if not isinstance(metadata, dict) or set(metadata) - {
                "name",
                "tracker_project_id",
                "tracker_project_name",
                "tracker_queue",
                "reviewer",
                "yonote_project_name",
            }:
                raise ValueError("unsupported project metadata")
            result = await upsert_project(
                actor=current_actor(),
                idempotency_key=idempotency_key,
                config={
                    **metadata,
                    "project_id": project_id,
                    "project_path": project_path,
                    "gitlab_clone_url": gitlab_clone_url,
                    "gitlab_web_url": gitlab_web_url,
                    "default_base_branch": default_base_branch,
                    "mr_target_branch": mr_target_branch,
                    "gitlab_connection_id": gitlab_connection_id,
                },
            )
            run.finish()
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Factory Project Validate",
            readOnlyHint=False,
            idempotentHint=True,
        )
    )
    async def gateway_factory_project_validate(
        project_id: str, idempotency_key: str
    ) -> str:
        """Recheck a registered project, including temporary branch push and cleanup."""
        run = ToolRun.start(
            tool="gateway_factory_project_validate",
            system="factory",
            scope="factory:projects:write",
            arguments={"project_id": project_id},
        )
        try:
            result = await validate_project(
                actor=current_actor(),
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            run.finish()
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Work Retry", readOnlyHint=False, idempotentHint=True
        )
    )
    async def gateway_work_retry(work_id: str, idempotency_key: str) -> str:
        """Explicitly requeue blocked Factory work after fresh repository readiness checks."""
        run = ToolRun.start(
            tool="gateway_work_retry",
            system="factory",
            scope="factory:projects:write",
            arguments={"work_id": work_id},
        )
        try:
            result = await retry_work(
                actor=current_actor(), work_id=work_id, idempotency_key=idempotency_key
            )
            run.finish()
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Factory Projects Discover", readOnlyHint=True
        )
    )
    async def gateway_factory_projects_discover(
        query: str = "", limit: int = 20
    ) -> str:
        """Discover projects that can be onboarded or executed by the autonomous development factory."""
        tool = "gateway_factory_projects_discover"
        scope = "factory:read"
        run = ToolRun.start(
            tool=tool,
            system="factory",
            scope=scope,
            arguments={"query": query, "limit": limit},
        )
        try:
            actor = run.require_scope()
            result = await discover_factory_projects(
                actor=actor,
                tools_registry=read_json(tools_file(), {"tools": []}),
                query=query,
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
            title="Gateway Factory Resolve By Issue", readOnlyHint=True
        )
    )
    async def gateway_factory_project_resolve_by_issue(
        issue_id: str,
        allow_queue_fallback: bool = False,
    ) -> str:
        """Resolve one Tracker issue to a factory runtime project config."""
        tool = "gateway_factory_project_resolve_by_issue"
        scope = "factory:read"
        run = ToolRun.start(
            tool=tool,
            system="factory",
            scope=scope,
            arguments={
                "issue_id": issue_id,
                "allow_queue_fallback": allow_queue_fallback,
            },
        )
        try:
            actor = run.require_scope()
            result = await resolve_factory_project_by_issue(
                actor=actor,
                tools_registry=read_json(tools_file(), {"tools": []}),
                issue_id=issue_id,
                allow_queue_fallback=allow_queue_fallback,
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
            title="Gateway Factory Runtime Config", readOnlyHint=True
        )
    )
    async def gateway_factory_project_get_runtime_config(
        issue_id: str = "",
        work_id: str = "",
        project_id: str = "",
        tracker_queue: str = "",
        allow_queue_fallback: bool = False,
    ) -> str:
        """Return normalized factory runtime config; prefer work_id for queued Work Contracts."""
        tool = "gateway_factory_project_get_runtime_config"
        scope = "factory:read"
        run = ToolRun.start(
            tool=tool,
            system="factory",
            scope=scope,
            arguments={
                "issue_id": issue_id,
                "work_id": work_id,
                "project_id": project_id,
                "tracker_queue": tracker_queue,
                "allow_queue_fallback": allow_queue_fallback,
            },
        )
        try:
            actor = run.require_scope()
            result = await get_factory_runtime_config(
                actor=actor,
                tools_registry=read_json(tools_file(), {"tools": []}),
                issue_id=issue_id,
                work_id=work_id,
                project_id=project_id,
                tracker_queue=tracker_queue,
                allow_queue_fallback=allow_queue_fallback,
            )
            run.finish()
            return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
