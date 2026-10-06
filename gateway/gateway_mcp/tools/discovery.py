import json
import re

from mcp.types import ToolAnnotations

from gateway_mcp.config import read_json, tools_file
from gateway_mcp.tools.runtime import ToolRun


def match_route_declarations(items: list[dict], query: str) -> list[dict]:
    """Match declarations when every whitespace-separated query token is found.

    A single token keeps the historical substring behaviour; several tokens are
    AND-matched so natural-language queries such as "bitrix24 сделки" work.
    """
    tokens = [token for token in re.split(r"\s+", query.casefold().strip()) if token]
    if not tokens:
        return list(items)
    matches = []
    for item in items:
        haystack = json.dumps(item, ensure_ascii=False).casefold()
        if all(token in haystack for token in tokens):
            matches.append(item)
    return matches


def register_discovery_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Search Tools", readOnlyHint=True))
    async def gateway_search_tools(query: str = "") -> str:
        """Search known internal MCP route declarations."""
        tool = "gateway_search_tools"
        scope = "tools:read"
        run = ToolRun.start(tool=tool, system="gateway", scope=scope, arguments={"query": query})
        try:
            run.require_scope()
            registry = read_json(tools_file(), {"tools": []})
            tools = match_route_declarations(registry.get("tools", []), query)
            run.finish()
            return json.dumps({"ok": True, "count": len(tools), "tools": tools}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
