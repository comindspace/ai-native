import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.auth import require_scope
from gateway_mcp.services.company import get_company_item, search_company_index, search_company_sources, source_of_truth
from gateway_mcp.services.context_budget import DEFAULT_CONTEXT_MAX_CHARS, compact_reference, fit_context_payload
from gateway_mcp.services.memory import search_memory
from gateway_mcp.config import read_json, tools_file
from gateway_mcp.tools.runtime import ToolRun


def register_company_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Search", readOnlyHint=True))
    async def gateway_company_search(
        query: str = "",
        kind: str = "",
        limit: int = 10,
        include_sources: bool = True,
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> str:
        """Search company context through the Yonote index and source systems."""
        tool = "gateway_company_search"
        scope = "company:read"
        run = ToolRun.start(
            tool=tool,
            system="company",
            scope=scope,
            arguments={
                "query": query,
                "kind": kind,
                "limit": limit,
                "include_sources": include_sources,
                "max_chars": max_chars,
            },
        )
        try:
            run.require_scope()
            normalized_limit = max(1, min(int(limit), 25))
            tools_registry = read_json(tools_file(), {"tools": []})
            items = await search_company_index(query, kind, normalized_limit, tools_registry)
            sources = []
            if include_sources:
                sources = await search_company_sources(
                    query=query,
                    limit=normalized_limit,
                    tools_registry=tools_registry,
                    include_remote=True,
                )
            run.finish()
            payload = fit_context_payload(
                {
                    "ok": True,
                    "count": len(items),
                    "source_count": len(sources),
                    "items": items,
                    "sources": sources,
                },
                max_chars,
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Get", readOnlyHint=True))
    async def gateway_company_get(
        kind: str,
        item_id: str,
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> str:
        """Resolve one company context item through Yonote or the matching source-of-truth domain."""
        tool = "gateway_company_get"
        scope = "company:read"
        run = ToolRun.start(
            tool=tool,
            system="company",
            scope=scope,
            arguments={"kind": kind, "item_id": item_id, "max_chars": max_chars},
        )
        try:
            run.require_scope()
            tools_registry = read_json(tools_file(), {"tools": []})
            item = await get_company_item(kind, item_id, tools_registry)
            source_map = await source_of_truth(tools_registry)
            run.finish(status="ok" if item else "not_found")
            payload = fit_context_payload(
                {
                    "ok": bool(item),
                    "item": item,
                    "source_of_truth": source_map.get("items", []),
                    "indexes": source_map.get("indexes", []),
                },
                max_chars,
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Source Of Truth", readOnlyHint=True))
    async def gateway_company_get_source_of_truth(
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> str:
        """Return the company source-of-truth map for people, projects, processes, documents, decisions, and operations."""
        tool = "gateway_company_get_source_of_truth"
        scope = "company:read"
        run = ToolRun.start(
            tool=tool,
            system="company",
            scope=scope,
            arguments={"max_chars": max_chars},
        )
        try:
            run.require_scope()
            result = await source_of_truth(read_json(tools_file(), {"tools": []}))
            run.finish()
            payload = fit_context_payload({"ok": True, **result}, max_chars)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise


    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Bootstrap Context", readOnlyHint=True))
    async def gateway_company_bootstrap_context(
        query: str = "",
        limit: int = 5,
        include_sources: bool = False,
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> str:
        """Return a compact startup context: source-of-truth map, company memory, and relevant company search results."""
        tool = "gateway_company_bootstrap_context"
        scope = "company:read"
        run = ToolRun.start(
            tool=tool,
            system="company",
            scope=scope,
            arguments={
                "query": query,
                "limit": limit,
                "include_sources": include_sources,
                "max_chars": max_chars,
            },
        )
        try:
            actor = run.require_scope()
            normalized_limit = max(1, min(int(limit), 10))
            memory_results = []
            try:
                require_scope("memory:read", tool=tool)
                memory_results = search_memory(
                    actor=actor,
                    query=query,
                    tiers_json='["medium"]',
                    scope="company",
                    subject="company",
                    limit=normalized_limit,
                )
            except PermissionError:
                memory_results = []
            tools_registry = read_json(tools_file(), {"tools": []})
            source_map = await source_of_truth(tools_registry)
            items = await search_company_index(query, "", normalized_limit, tools_registry)
            sources = await search_company_sources(
                query=query,
                limit=normalized_limit,
                tools_registry=tools_registry,
                include_remote=include_sources,
            )
            run.finish()
            payload = fit_context_payload(
                {
                    "ok": True,
                    "source_of_truth": source_map.get("items", []),
                    "canonical_index": compact_reference(source_map.get("canonical_index")),
                    "memory": memory_results,
                    "items": items,
                    "sources": sources,
                },
                max_chars,
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
