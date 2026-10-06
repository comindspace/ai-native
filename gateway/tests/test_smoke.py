import json
import unittest
from unittest.mock import patch

from gateway_mcp import smoke


class SmokeProtocolTests(unittest.TestCase):
    def test_modern_smoke_sends_required_protocol_metadata_headers(self) -> None:
        requests: list[tuple[str, dict[str, str], dict]] = []

        def fake_request(method, url, *, json_payload=None, headers=None, timeout):
            requests.append((url, dict(headers or {}), dict(json_payload or {})))
            rpc_method = json_payload["method"]
            if rpc_method == "server/discover":
                body = {
                    "jsonrpc": "2.0",
                    "id": "discover-1",
                    "result": {
                        "resultType": "complete",
                        "supportedVersions": [smoke.MODERN_PROTOCOL_VERSION],
                    },
                }
            else:
                body = {
                    "jsonrpc": "2.0",
                    "id": "tools-1",
                    "result": {
                        "resultType": "complete",
                        "tools": [{"name": "gateway_search_tools"}],
                    },
                }
            return 200, {}, json.dumps(body)

        with patch("gateway_mcp.smoke._request", side_effect=fake_request):
            results = smoke._check_mcp_modern(
                "https://gateway.example", token="token", timeout=5
            )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(
            requests[0][1]["MCP-Protocol-Version"], smoke.MODERN_PROTOCOL_VERSION
        )
        self.assertEqual(requests[0][1]["Mcp-Method"], "server/discover")
        self.assertEqual(requests[1][1]["Mcp-Method"], "tools/list")
        for _, _, payload in requests:
            self.assertEqual(
                payload["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"],
                smoke.MODERN_PROTOCOL_VERSION,
            )

    def test_default_smoke_mode_keeps_legacy_production_check(self) -> None:
        with (
            patch(
                "gateway_mcp.smoke._check_json",
                return_value=smoke.SmokeResult("metadata", True, "ok"),
            ),
            patch(
                "gateway_mcp.smoke._check_client_registration",
                return_value=smoke.SmokeResult("dcr", True, "ok"),
            ),
            patch("gateway_mcp.smoke._check_mcp_legacy", return_value=[]) as legacy,
            patch("gateway_mcp.smoke._check_mcp_modern", return_value=[]) as modern,
        ):
            smoke.run_smoke("https://gateway.example", token="token")

        legacy.assert_called_once()
        modern.assert_not_called()


if __name__ == "__main__":
    unittest.main()
