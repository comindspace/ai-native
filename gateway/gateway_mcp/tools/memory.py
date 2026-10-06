import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.memory import compact_session_notes, forget_memory, search_memory, search_source_backed_memory, write_memory
from gateway_mcp.services.observability import observe_memory_results, record_memory_event
from gateway_mcp.config import read_json, tools_file
from gateway_mcp.tools.runtime import ToolRun


def register_memory_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Memory Write"))
    async def gateway_memory_write(
        content: str,
        tier: str = "short",
        scope: str = "user",
        subject: str = "",
        kind: str = "fact",
        source_type: str = "manual",
        source_uri: str = "",
        source_title: str = "",
        sensitivity: str = "internal",
        confidence: float = 1.0,
        tags_json: str = "[]",
        metadata_json: str = "{}",
        ttl_days: int = 0,
    ) -> str:
        """Store short-term session/task memory or medium-term project/team facts in Postgres."""
        tool = "gateway_memory_write"
        scope_required = "memory:write"
        run = ToolRun.start(
            tool=tool,
            system="memory",
            scope=scope_required,
            arguments={
                "tier": tier,
                "scope": scope,
                "subject": subject,
                "kind": kind,
                "source_type": source_type,
                "source_uri": source_uri,
                "source_title": source_title,
                "sensitivity": sensitivity,
                "confidence": confidence,
                "tags_json": tags_json,
                "metadata_json": metadata_json,
                "ttl_days": ttl_days,
            },
        )
        try:
            actor = run.require_scope()
            entry = write_memory(
                actor=actor,
                tier=tier,
                scope=scope,
                subject=subject,
                kind=kind,
                content=content,
                source_type=source_type,
                source_uri=source_uri,
                source_title=source_title,
                sensitivity=sensitivity,
                confidence=confidence,
                tags_json=tags_json,
                metadata_json=metadata_json,
                ttl_days=ttl_days or None,
            )
            record_memory_event("write", str(entry.get("tier", tier)), str(entry.get("scope", scope)), "ok")
            run.finish()
            return json.dumps({"ok": True, "memory": entry}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            record_memory_event("write", tier, scope, "denied")
            run.denied(exc)
            raise
        except Exception as exc:
            record_memory_event("write", tier, scope, "error")
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Memory Search", readOnlyHint=True))
    async def gateway_memory_search(
        query: str = "",
        tiers_json: str = '["short", "medium"]',
        scope: str = "",
        subject: str = "",
        limit: int = 10,
        include_sources: bool = True,
        include_yonote: bool = True,
    ) -> str:
        """Search short/medium Postgres memory and optionally source-backed long-term knowledge."""
        tool = "gateway_memory_search"
        scope_required = "memory:read"
        run = ToolRun.start(
            tool=tool,
            system="memory",
            scope=scope_required,
            arguments={
                "query": query,
                "tiers_json": tiers_json,
                "scope": scope,
                "subject": subject,
                "limit": limit,
                "include_sources": include_sources,
                "include_yonote": include_yonote,
            },
        )
        try:
            actor = run.require_scope()
            memory_results = search_memory(
                actor=actor,
                query=query,
                tiers_json=tiers_json,
                scope=scope,
                subject=subject,
                limit=limit,
            )
            source_results = []
            if include_sources:
                source_results = await search_source_backed_memory(
                    query=query,
                    limit=max(1, min(int(limit), 25)),
                    tools_registry=read_json(tools_file(), {"tools": []}),
                    include_yonote=include_yonote,
                    actor=actor,
                )
            observe_memory_results("search", len(memory_results) + len(source_results))
            record_memory_event("search", "any", scope, "ok")
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    "memory_count": len(memory_results),
                    "source_count": len(source_results),
                    "memory": memory_results,
                    "sources": source_results,
                },
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            record_memory_event("search", "any", scope, "denied")
            run.denied(exc)
            raise
        except Exception as exc:
            record_memory_event("search", "any", scope, "error")
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Memory Sources Search", readOnlyHint=True))
    async def gateway_memory_sources_search(query: str = "", limit: int = 10, include_yonote: bool = True) -> str:
        """Search source-backed long-term knowledge from Yonote/templates/ADR/docs without copying it into memory."""
        tool = "gateway_memory_sources_search"
        scope_required = "memory:read"
        run = ToolRun.start(
            tool=tool,
            system="memory",
            scope=scope_required,
            arguments={"query": query, "limit": limit, "include_yonote": include_yonote},
        )
        try:
            actor = run.require_scope()
            results = await search_source_backed_memory(
                query=query,
                limit=limit,
                tools_registry=read_json(tools_file(), {"tools": []}),
                include_yonote=include_yonote,
                actor=actor,
            )
            observe_memory_results("sources_search", len(results))
            record_memory_event("sources_search", "long", "source", "ok")
            run.finish()
            return json.dumps({"ok": True, "count": len(results), "sources": results}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            record_memory_event("sources_search", "long", "source", "denied")
            run.denied(exc)
            raise
        except Exception as exc:
            record_memory_event("sources_search", "long", "source", "error")
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Memory Summarize Session"))
    async def gateway_memory_summarize_session(
        session_id: str,
        notes: str,
        scope: str = "user",
        subject: str = "",
        ttl_days: int = 0,
        source_uri: str = "",
    ) -> str:
        """Store a compact short-term session/task summary in Postgres memory."""
        tool = "gateway_memory_summarize_session"
        scope_required = "memory:write"
        run = ToolRun.start(
            tool=tool,
            system="memory",
            scope=scope_required,
            arguments={
                "session_id": session_id,
                "scope": scope,
                "subject": subject,
                "ttl_days": ttl_days,
                "source_uri": source_uri,
            },
        )
        try:
            actor = run.require_scope()
            entry = write_memory(
                actor=actor,
                tier="short",
                scope=scope,
                subject=subject,
                kind="session_summary",
                content=compact_session_notes(notes),
                source_type="session",
                source_uri=source_uri,
                source_title=session_id,
                sensitivity="internal",
                confidence=0.8,
                tags_json=json.dumps(["session", "summary"], ensure_ascii=False),
                metadata_json=json.dumps({"session_id": session_id}, ensure_ascii=False),
                ttl_days=ttl_days or None,
            )
            record_memory_event("summarize_session", "short", str(entry.get("scope", scope)), "ok")
            run.finish()
            return json.dumps({"ok": True, "memory": entry}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            record_memory_event("summarize_session", "short", scope, "denied")
            run.denied(exc)
            raise
        except Exception as exc:
            record_memory_event("summarize_session", "short", scope, "error")
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Memory Forget"))
    async def gateway_memory_forget(entry_id: int) -> str:
        """Delete a memory entry created by the current actor. Admins may delete any memory entry."""
        tool = "gateway_memory_forget"
        scope_required = "memory:write"
        run = ToolRun.start(tool=tool, system="memory", scope=scope_required, arguments={"entry_id": entry_id})
        try:
            actor = run.require_scope()
            deleted = forget_memory(entry_id, actor)
            status = "ok" if deleted else "not_found"
            record_memory_event("forget", str((deleted or {}).get("tier", "any")), str((deleted or {}).get("scope", "any")), status)
            run.finish(status=status)
            return json.dumps({"ok": bool(deleted), "memory": deleted}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            record_memory_event("forget", "any", "any", "denied")
            run.denied(exc)
            raise
        except Exception as exc:
            record_memory_event("forget", "any", "any", "error")
            run.error(exc)
            raise
