from __future__ import annotations

import json
import unittest

from gateway_mcp.services.context_budget import compact_reference, fit_context_payload


class ContextBudgetTests(unittest.TestCase):
    def test_large_nested_payload_is_valid_and_bounded(self) -> None:
        payload = {
            "ok": True,
            "sources": [
                {
                    "provider": "example",
                    "data": {"items": [{"text": "x" * 8_000, "secret": "not-a-secret"} for _ in range(30)]},
                }
                for _ in range(20)
            ],
        }

        compacted = fit_context_payload(payload, 4_000)
        encoded = json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))

        self.assertLessEqual(len(encoded), 4_000)
        self.assertTrue(compacted["ok"])
        self.assertTrue(compacted["context_budget"]["truncated"])
        self.assertGreater(compacted["context_budget"]["original_chars"], 100_000)

    def test_small_payload_is_not_marked_truncated(self) -> None:
        payload = {"ok": True, "items": [{"id": "one", "title": "Short"}]}

        compacted = fit_context_payload(payload, 4_000)

        self.assertFalse(compacted["context_budget"]["truncated"])
        self.assertEqual(compacted["items"][0]["id"], "one")

    def test_compact_reference_drops_loaded_data(self) -> None:
        compacted = compact_reference(
            {
                "provider": "yonote",
                "document_id": "doc/architecture",
                "data": {"content": "large" * 10_000},
            }
        )

        self.assertEqual(compacted, {"provider": "yonote", "document_id": "doc/architecture"})

    def test_budget_is_clamped_for_public_tool_parameters(self) -> None:
        payload = {"ok": True, "items": [{"text": "x" * 20_000}]}

        compacted = fit_context_payload(payload, 100)
        encoded = json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))

        self.assertLessEqual(len(encoded), 2_000)
        self.assertEqual(compacted["context_budget"]["max_chars"], 2_000)


if __name__ == "__main__":
    unittest.main()
