import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.tools.access import register_access_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class AuditToolTests(unittest.TestCase):
    def test_search_uses_request_id_and_never_returns_payload(self) -> None:
        fake = FakeMcp()
        register_access_tools(fake)
        run = Mock()
        events = [
            {
                "event": "resource_access",
                "gateway_request_id": "request-1",
                "payload": {"secret": "must-not-leak"},
            }
        ]
        # Storage omits payload when include_payload is false; model that boundary here.
        events[0].pop("payload")

        with (
            patch("gateway_mcp.tools.access.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.access.list_audit_events", return_value=events
            ) as search,
        ):
            raw = asyncio.run(
                fake.tools["gateway_admin_audit_search"](
                    gateway_request_id="request-1", limit=20
                )
            )

        self.assertNotIn("must-not-leak", raw)
        self.assertEqual(json.loads(raw)["events"], events)
        search.assert_called_once_with(
            days=7,
            actor_subject="",
            event="",
            tool="",
            system="",
            decision="",
            status="",
            gateway_request_id="request-1",
            limit=20,
            offset=0,
            include_payload=False,
        )
        run.require_scope.assert_called_once()

    def test_summary_delegates_filters(self) -> None:
        fake = FakeMcp()
        register_access_tools(fake)
        run = Mock()
        rows = [{"event": "resource_access", "count": 4}]

        with (
            patch("gateway_mcp.tools.access.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.access.audit_event_summary", return_value=rows
            ) as summary,
        ):
            raw = asyncio.run(
                fake.tools["gateway_admin_audit_summary"](
                    days=30, actor_subject="user:roman", system="gitlab", limit=25
                )
            )

        self.assertEqual(json.loads(raw)["summary"], rows)
        summary.assert_called_once_with(
            days=30,
            actor_subject="user:roman",
            system="gitlab",
            limit=25,
        )


if __name__ == "__main__":
    unittest.main()
