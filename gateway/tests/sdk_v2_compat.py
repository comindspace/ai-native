import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["GATEWAY_AUTH_ENABLED"] = "false"

import mcp.server.auth.settings
from mcp import Client
from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.server import mcp


async def check_client(*, mode: str | None = None) -> tuple[str, set[str]]:
    kwargs = {"mode": mode} if mode else {}
    async with Client(mcp, **kwargs) as client:
        result = await client.list_tools()
        return str(client.protocol_version), {tool.name for tool in result.tools}


async def main() -> None:
    modern_version, modern_tools = await check_client()
    legacy_version, legacy_tools = await check_client(mode="legacy")
    required = {
        "gateway_search_tools",
        "gateway_call_tool",
        "gateway_company_get_source_of_truth",
    }

    if modern_version != "2026-07-28":
        raise RuntimeError(f"unexpected modern MCP version: {modern_version}")
    if legacy_version == modern_version:
        raise RuntimeError(
            f"legacy client did not negotiate a legacy version: {legacy_version}"
        )
    if not required.issubset(modern_tools) or not required.issubset(legacy_tools):
        raise RuntimeError(
            "GatewayMCP tool catalog differs between modern and legacy clients"
        )

    print(
        f"MCP SDK v2 compatibility ok: modern={modern_version}, "
        f"legacy={legacy_version}, tools={len(modern_tools)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
