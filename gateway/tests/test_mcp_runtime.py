import unittest
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp import mcp_runtime


class McpRuntimeTests(unittest.TestCase):
    def test_v1_constructor_keeps_transport_settings(self) -> None:
        with (
            patch.object(mcp_runtime, "MCP_SDK_V2", False),
            patch.object(mcp_runtime, "MCPServer") as server_type,
            patch.dict(
                "os.environ",
                {
                    "GATEWAY_HOST": "0.0.0.0",
                    "GATEWAY_PORT": "9000",
                    "GATEWAY_MCP_PATH": "/company-mcp",
                },
                clear=True,
            ),
        ):
            mcp_runtime.create_server(
                name="gateway", token_verifier="verifier", auth="auth"
            )

        server_type.assert_called_once_with(
            "gateway",
            host="0.0.0.0",
            port=9000,
            streamable_http_path="/company-mcp",
            token_verifier="verifier",
            auth="auth",
        )

    def test_v2_constructor_moves_transport_settings_to_run(self) -> None:
        server = Mock()
        with (
            patch.object(mcp_runtime, "MCP_SDK_V2", True),
            patch.object(mcp_runtime, "MCPServer") as server_type,
            patch.object(
                mcp_runtime,
                "CacheHint",
                side_effect=lambda **kwargs: kwargs,
            ),
            patch.dict("os.environ", {"GATEWAY_SERVER_VERSION": "2.0.0"}, clear=True),
        ):
            mcp_runtime.create_server(
                name="gateway", token_verifier="verifier", auth="auth"
            )

        server_type.assert_called_once_with(
            "gateway",
            version="2.0.0",
            cache_hints={
                "server/discover": {"ttl_ms": 300000, "scope": "private"},
                "tools/list": {"ttl_ms": 300000, "scope": "private"},
                "resources/list": {"ttl_ms": 300000, "scope": "private"},
                "resources/templates/list": {"ttl_ms": 300000, "scope": "private"},
                "resources/read": {"ttl_ms": 60000, "scope": "private"},
            },
            token_verifier="verifier",
            auth="auth",
        )

        with (
            patch.object(mcp_runtime, "MCP_SDK_V2", True),
            patch.dict(
                "os.environ",
                {
                    "GATEWAY_HOST": "0.0.0.0",
                    "GATEWAY_PORT": "9000",
                    "GATEWAY_MCP_PATH": "/company-mcp",
                    "GATEWAY_STATELESS_LEGACY_HTTP": "true",
                    "GATEWAY_MAX_REQUEST_BODY_BYTES": "8388608",
                },
                clear=True,
            ),
        ):
            mcp_runtime.run_server(server, transport="streamable-http")

        server.run.assert_called_once_with(
            transport="streamable-http",
            host="0.0.0.0",
            port=9000,
            streamable_http_path="/company-mcp",
            stateless_http=True,
            max_request_body_size=8388608,
        )

    def test_stdio_does_not_receive_http_options(self) -> None:
        server = Mock()
        with patch.object(mcp_runtime, "MCP_SDK_V2", True):
            mcp_runtime.run_server(server, transport="stdio")

        server.run.assert_called_once_with(transport="stdio")


if __name__ == "__main__":
    unittest.main()
