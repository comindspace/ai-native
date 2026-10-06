import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.tools.privacy import register_privacy_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class PrivacyToolTests(unittest.TestCase):
    def test_sanitized_backend_call_returns_no_raw_personal_data(self) -> None:
        fake = FakeMcp()
        register_privacy_tools(fake)
        run = Mock()
        run.tool = "gateway_call_tool_sanitized"
        run.arguments = {}
        run.require_scope.return_value = GatewayActor(
            subject="yandex:1",
            scopes=("tools:call", "privacy:use", "yonote:read"),
        )
        registry = {
            "tools": [
                {
                    "name": "yonote.documents.get",
                    "backend": "yonote",
                    "scope": "yonote:read",
                    "http_method": "POST",
                }
            ]
        }
        with (
            patch("gateway_mcp.tools.privacy.ToolRun.start", return_value=run),
            patch("gateway_mcp.tools.privacy.read_json", return_value=registry),
            patch(
                "gateway_mcp.tools.privacy.require_resource_access",
                return_value={"decision": "allow", "resource": "doc-1"},
            ),
            patch(
                "gateway_mcp.tools.privacy.call_backend",
                new=AsyncMock(
                    return_value={
                        "ok": True,
                        "status": 200,
                        "data": {"contact": "roman@example.com"},
                    }
                ),
            ),
            patch("gateway_mcp.tools.privacy.audit_event"),
        ):
            raw = asyncio.run(
                fake.tools["gateway_call_tool_sanitized"](
                    "yonote.documents.get", '{"id":"doc-1"}'
                )
            )

        payload = json.loads(raw)
        self.assertNotIn("roman@example.com", raw)
        self.assertEqual(payload["privacy"]["pseudonymized"], 1)
        run.finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
