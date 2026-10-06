import json
import unittest
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.process_intelligence import (
    build_rebuild_backlog,
    collect_process_events,
    compare_candidates_with_yonote,
    discover_process_candidates,
)


REGISTRY = {
    "tools": [
        {"name": "bitrix24.deals.list", "backend": "bitrix24", "scope": "bitrix24:read"},
        {"name": "bitrix24.leads.list", "backend": "bitrix24", "scope": "bitrix24:read"},
        {"name": "tracker.issues.search", "backend": "yandex-tracker", "scope": "tracker:read"},
        {"name": "gitlab.projects.search", "backend": "gitlab", "scope": "gitlab:read"},
        {"name": "gitlab.merge_requests.list", "backend": "gitlab", "scope": "gitlab:read"},
        {"name": "gitlab.pipelines.list", "backend": "gitlab", "scope": "gitlab:read"},
        {"name": "yonote.documents.search", "backend": "yonote", "scope": "yonote:read"},
    ]
}


async def fake_call_backend(route, arguments):
    route_name = route["name"]
    if route_name == "bitrix24.deals.list":
        return {
            "ok": True,
            "data": {
                "result": [
                    {
                        "ID": "42",
                        "TITLE": "Client roman@example.com +7 999 111-22-33 pilot",
                        "STAGE_ID": "PROPOSAL",
                        "DATE_MODIFY": "2026-05-10T09:00:00+00:00",
                    }
                ]
            },
        }
    if route_name == "bitrix24.leads.list":
        return {"ok": True, "data": {"result": []}}
    if route_name == "tracker.issues.search":
        return {
            "ok": True,
            "data": [
                {
                    "key": "AI-42",
                    "summary": "Start client pilot",
                    "status": {"display": "In Review"},
                    "updatedAt": "2026-05-10T11:00:00+00:00",
                }
            ],
        }
    if route_name == "yonote.documents.search":
        return {
            "ok": True,
            "data": {
                "result": [
                    {
                        "id": "doc-1",
                        "title": "Sales Pipeline process",
                        "updatedAt": "2026-05-09T11:00:00+00:00",
                    }
                ]
            },
        }
    return {"ok": True, "data": []}


class ProcessIntelligenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_process_events_returns_sanitized_events(self) -> None:
        actor = GatewayActor(subject="admin", scopes=("*",))
        with patch("gateway_mcp.services.process_intelligence.call_backend", AsyncMock(side_effect=fake_call_backend)):
            result = await collect_process_events(
                actor=actor,
                tools_registry=REGISTRY,
                systems=["bitrix24", "tracker", "yonote"],
                limit=10,
            )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["count"], 3)
        self.assertIn("sales_pipeline", {item["process_hint"] for item in result["events"]})
        self.assertNotIn("roman@example.com", serialized)
        self.assertNotIn("+7 999 111-22-33", serialized)
        self.assertFalse(result["privacy"]["raw_records_returned"])

    async def test_discover_compare_and_backlog(self) -> None:
        actor = GatewayActor(subject="admin", scopes=("*",))
        with patch("gateway_mcp.services.process_intelligence.call_backend", AsyncMock(side_effect=fake_call_backend)):
            source = await collect_process_events(
                actor=actor,
                tools_registry=REGISTRY,
                systems=["bitrix24", "tracker", "yonote"],
                limit=10,
            )
            candidates_result = discover_process_candidates(source["events"], limit=8)
            compare_result = await compare_candidates_with_yonote(
                actor=actor,
                tools_registry=REGISTRY,
                candidates=candidates_result["candidates"],
                query="Sales Pipeline",
                limit=8,
            )

        names = {candidate["process_hint"] for candidate in candidates_result["candidates"]}
        self.assertIn("sales_to_delivery_handoff", names)
        self.assertGreaterEqual(candidates_result["count"], 3)
        statuses = {item["status"] for item in compare_result["comparisons"]}
        self.assertIn("documented_needs_trace_review", statuses)

        backlog = build_rebuild_backlog(
            candidates=candidates_result["candidates"],
            comparisons=compare_result["comparisons"],
            limit=8,
        )
        self.assertGreaterEqual(backlog["count"], 1)
        self.assertIn(backlog["items"][0]["type"], {"process_update", "new_process_page", "instrumentation_gap"})


if __name__ == "__main__":
    unittest.main()
