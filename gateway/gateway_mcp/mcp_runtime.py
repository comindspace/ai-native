import os
from typing import Any

try:
    from mcp.server import MCPServer
    from mcp.server.caching import CacheHint

    MCP_SDK_V2 = True
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

    CacheHint = None
    MCP_SDK_V2 = False


def create_server(*, name: str, token_verifier: Any, auth: Any) -> Any:
    """Create an MCP server with the constructor expected by the installed SDK."""
    common = {
        "token_verifier": token_verifier,
        "auth": auth,
    }
    if MCP_SDK_V2:
        return MCPServer(
            name,
            version=os.getenv("GATEWAY_SERVER_VERSION", "0.1.0"),
            cache_hints=_cache_hints(),
            **common,
        )
    return MCPServer(
        name,
        host=_host(),
        port=_port(),
        streamable_http_path=_mcp_path(),
        **common,
    )


def run_server(server: Any, *, transport: str) -> None:
    """Run one MCP server while preserving compatibility with SDK v1."""
    if not MCP_SDK_V2 or transport == "stdio":
        server.run(transport=transport)
        return

    kwargs: dict[str, Any] = {
        "host": _host(),
        "port": _port(),
    }
    if transport == "streamable-http":
        kwargs.update(
            {
                "streamable_http_path": _mcp_path(),
                "stateless_http": _bool_env("GATEWAY_STATELESS_LEGACY_HTTP", True),
                "max_request_body_size": int(
                    os.getenv("GATEWAY_MAX_REQUEST_BODY_BYTES", "4194304")
                ),
            }
        )
    server.run(transport=transport, **kwargs)


def _host() -> str:
    return os.getenv("GATEWAY_HOST", "127.0.0.1")


def _port() -> int:
    return int(os.getenv("GATEWAY_PORT", "8000"))


def _mcp_path() -> str:
    return os.getenv("GATEWAY_MCP_PATH", "/mcp")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _cache_hints() -> dict[str, Any]:
    ttl_ms = int(os.getenv("GATEWAY_MCP_CATALOG_TTL_MS", "300000"))
    return {
        "server/discover": CacheHint(ttl_ms=ttl_ms, scope="private"),
        "tools/list": CacheHint(ttl_ms=ttl_ms, scope="private"),
        "resources/list": CacheHint(ttl_ms=ttl_ms, scope="private"),
        "resources/templates/list": CacheHint(ttl_ms=ttl_ms, scope="private"),
        "resources/read": CacheHint(ttl_ms=60000, scope="private"),
    }
