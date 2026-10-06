import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.telemetry import (
    finish_session_skills,
    record_skill_event,
    record_usage_report,
    skill_stats,
    usage_summary,
)
from gateway_mcp.tools.runtime import ToolRun


def register_telemetry_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Skill Started"))
    async def gateway_telemetry_skill_started(
        agent: str,
        skill_id: str,
        skill_pack: str = "",
        skill_version: str = "",
        correlation_id: str = "",
        session_id: str = "",
        project: str = "",
        client: str = "",
        metadata_json: str = "{}",
    ) -> str:
        """Record that a local agent skill started. Do not send raw prompt text or sensitive data."""
        tool = "gateway_telemetry_skill_started"
        scope = "telemetry:write"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "agent": agent,
                "skill_id": skill_id,
                "skill_pack": skill_pack,
                "skill_version": skill_version,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "project": project,
                "client": client,
                "metadata_json": metadata_json,
            },
        )
        try:
            actor = run.require_scope()
            result = record_skill_event(
                actor=actor,
                event_type="started",
                agent=agent,
                skill_id=skill_id,
                skill_pack=skill_pack,
                skill_version=skill_version,
                correlation_id=correlation_id,
                session_id=session_id,
                project=project,
                client=client,
                metadata_json=metadata_json,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Skill Completed"))
    async def gateway_telemetry_skill_completed(
        agent: str,
        skill_id: str,
        skill_pack: str = "",
        skill_version: str = "",
        correlation_id: str = "",
        session_id: str = "",
        project: str = "",
        client: str = "",
        duration_ms: int = 0,
        mcp_routes_json: str = "[]",
        missing_scopes_json: str = "[]",
        metadata_json: str = "{}",
    ) -> str:
        """Record that a local agent skill completed successfully."""
        tool = "gateway_telemetry_skill_completed"
        scope = "telemetry:write"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "agent": agent,
                "skill_id": skill_id,
                "skill_pack": skill_pack,
                "skill_version": skill_version,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "project": project,
                "client": client,
                "duration_ms": duration_ms,
                "mcp_routes_json": mcp_routes_json,
                "missing_scopes_json": missing_scopes_json,
                "metadata_json": metadata_json,
            },
        )
        try:
            actor = run.require_scope()
            result = record_skill_event(
                actor=actor,
                event_type="completed",
                agent=agent,
                skill_id=skill_id,
                skill_pack=skill_pack,
                skill_version=skill_version,
                correlation_id=correlation_id,
                session_id=session_id,
                project=project,
                client=client,
                status="ok",
                duration_ms=duration_ms,
                mcp_routes_json=mcp_routes_json,
                missing_scopes_json=missing_scopes_json,
                metadata_json=metadata_json,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Skill Failed"))
    async def gateway_telemetry_skill_failed(
        agent: str,
        skill_id: str,
        skill_pack: str = "",
        skill_version: str = "",
        correlation_id: str = "",
        session_id: str = "",
        project: str = "",
        client: str = "",
        duration_ms: int = 0,
        mcp_routes_json: str = "[]",
        missing_scopes_json: str = "[]",
        error_class: str = "",
        metadata_json: str = "{}",
    ) -> str:
        """Record that a local agent skill failed. Send error class, not stack traces or secrets."""
        tool = "gateway_telemetry_skill_failed"
        scope = "telemetry:write"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "agent": agent,
                "skill_id": skill_id,
                "skill_pack": skill_pack,
                "skill_version": skill_version,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "project": project,
                "client": client,
                "duration_ms": duration_ms,
                "mcp_routes_json": mcp_routes_json,
                "missing_scopes_json": missing_scopes_json,
                "error_class": error_class,
                "metadata_json": metadata_json,
            },
        )
        try:
            actor = run.require_scope()
            result = record_skill_event(
                actor=actor,
                event_type="failed",
                agent=agent,
                skill_id=skill_id,
                skill_pack=skill_pack,
                skill_version=skill_version,
                correlation_id=correlation_id,
                session_id=session_id,
                project=project,
                client=client,
                status="error",
                duration_ms=duration_ms,
                mcp_routes_json=mcp_routes_json,
                missing_scopes_json=missing_scopes_json,
                metadata_json=metadata_json,
                error_class=error_class,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Session Finished"))
    async def gateway_telemetry_session_finished(
        agent: str,
        session_id: str,
        outcome: str = "completed",
        error_class: str = "",
    ) -> str:
        """Close every open skill invocation for this actor and agent session."""
        tool = "gateway_telemetry_session_finished"
        scope = "telemetry:write"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "agent": agent,
                "session_id": session_id,
                "outcome": outcome,
                "error_class": error_class,
            },
        )
        try:
            actor = run.require_scope()
            result = finish_session_skills(
                actor=actor,
                agent=agent,
                session_id=session_id,
                outcome=outcome,
                error_class=error_class,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Skill Stats", readOnlyHint=True))
    async def gateway_telemetry_skill_stats(
        days: int = 30,
        limit: int = 25,
        agent: str = "",
        skill_id: str = "",
        skill_pack: str = "",
        skill_version: str = "",
        project: str = "",
        actor_subject: str = "",
    ) -> str:
        """Return aggregated assistant skill usage stats. Requires telemetry:read."""
        tool = "gateway_telemetry_skill_stats"
        scope = "telemetry:read"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "days": days,
                "limit": limit,
                "agent": agent,
                "skill_id": skill_id,
                "skill_pack": skill_pack,
                "skill_version": skill_version,
                "project": project,
                "actor_subject": actor_subject,
            },
        )
        try:
            run.require_scope()
            result = skill_stats(
                days=days,
                limit=limit,
                agent=agent,
                skill_id=skill_id,
                skill_pack=skill_pack,
                skill_version=skill_version,
                project=project,
                actor_subject=actor_subject,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Usage Report"))
    async def gateway_telemetry_usage_report(
        agent: str,
        source: str = "mcp",
        source_quality: str = "estimated",
        event_name: str = "usage_report",
        provider: str = "",
        model: str = "",
        session_id: str = "",
        correlation_id: str = "",
        skill_id: str = "",
        skill_pack: str = "",
        project: str = "",
        client: str = "",
        cwd: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        reasoning_tokens: int = 0,
        duration_ms: int = 0,
        tool_use_count: int = 0,
        usage_class: str = "",
        estimated_cost_usd: float = 0,
        metadata_json: str = "{}",
        raw_event_json: str = "{}",
    ) -> str:
        """Record actual or estimated agent token/cost usage. Requires telemetry:write."""
        tool = "gateway_telemetry_usage_report"
        scope = "telemetry:write"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "agent": agent,
                "source": source,
                "source_quality": source_quality,
                "event_name": event_name,
                "provider": provider,
                "model": model,
                "session_id": session_id,
                "skill_id": skill_id,
                "project": project,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "usage_class": usage_class,
            },
        )
        try:
            actor = run.require_scope()
            result = record_usage_report(
                actor=actor,
                agent=agent,
                source=source,
                source_quality=source_quality,
                event_name=event_name,
                provider=provider,
                model=model,
                session_id=session_id,
                correlation_id=correlation_id,
                skill_id=skill_id,
                skill_pack=skill_pack,
                project=project,
                client=client,
                cwd=cwd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                reasoning_tokens=reasoning_tokens,
                duration_ms=duration_ms,
                tool_use_count=tool_use_count,
                usage_class=usage_class,
                estimated_cost_usd=estimated_cost_usd,
                metadata_json=metadata_json,
                raw_event_json=raw_event_json,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Telemetry Usage Summary", readOnlyHint=True))
    async def gateway_telemetry_usage_summary(
        days: int = 30,
        limit: int = 25,
        agent: str = "",
        skill_id: str = "",
        project: str = "",
        source_quality: str = "",
    ) -> str:
        """Return approximate or actual agent usage summary. Requires telemetry:read."""
        tool = "gateway_telemetry_usage_summary"
        scope = "telemetry:read"
        run = ToolRun.start(
            tool=tool,
            system="telemetry",
            scope=scope,
            arguments={
                "days": days,
                "limit": limit,
                "agent": agent,
                "skill_id": skill_id,
                "project": project,
                "source_quality": source_quality,
            },
        )
        try:
            run.require_scope()
            result = usage_summary(
                days=days,
                limit=limit,
                agent=agent,
                skill_id=skill_id,
                project=project,
                source_quality=source_quality,
            )
            run.finish()
            return json.dumps(result, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
