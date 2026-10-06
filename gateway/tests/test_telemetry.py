import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.telemetry import (
    finish_session_skills,
    record_skill_event,
    record_usage_report,
    skill_stats,
    usage_summary,
)


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods, include_in_schema=False):
        def decorator(func):
            self.routes[path] = {
                "func": func,
                "methods": methods,
                "include_in_schema": include_in_schema,
            }
            return func

        return decorator


class AssistantTelemetryTests(unittest.TestCase):
    def test_record_skill_event_redacts_metadata_and_records_storage(self) -> None:
        actor = GatewayActor(subject="u1", email="user@example.com")

        with (
            patch("gateway_mcp.services.telemetry.upsert_assistant_session") as upsert_session,
            patch("gateway_mcp.services.telemetry.insert_assistant_skill_event", return_value={"id": 1}) as insert_event,
            patch("gateway_mcp.services.telemetry.audit_event") as audit,
            patch("gateway_mcp.services.telemetry.observe_skill_event") as observe,
        ):
            result = record_skill_event(
                actor=actor,
                event_type="completed",
                agent="claude",
                skill_id="kp-draft",
                skill_pack="business-growth",
                skill_version="0.1.0",
                correlation_id="run-1",
                session_id="session-1",
                project="demo",
                duration_ms=1200,
                mcp_routes_json='["yonote.documents.search"]',
                missing_scopes_json='["gitlab:write"]',
                metadata_json=json.dumps(
                    {
                        "token": "secret",
                        "prompt": "customer data",
                        "result_text": "private result",
                        "scenario": "proposal",
                    }
                ),
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["stored"])
        self.assertEqual(result["event"]["correlation_id"], "run-1")
        upsert_session.assert_called_once()
        observe.assert_called_once()
        insert_event.assert_called_once()
        self.assertEqual(insert_event.call_args.kwargs["metadata"]["token"], "[redacted]")
        self.assertEqual(insert_event.call_args.kwargs["metadata"]["prompt"], "[redacted]")
        self.assertEqual(
            insert_event.call_args.kwargs["metadata"]["result_text"], "[redacted]"
        )
        self.assertEqual(insert_event.call_args.kwargs["metadata"]["scenario"], "proposal")
        self.assertEqual(insert_event.call_args.kwargs["mcp_routes"], ["yonote.documents.search"])
        self.assertEqual(insert_event.call_args.kwargs["missing_scopes"], ["gitlab:write"])
        self.assertEqual(audit.call_args.kwargs["event"], "assistant_skill_event")
        self.assertEqual(audit.call_args.kwargs["tool"], "skill:kp-draft")

    def test_record_skill_event_requires_known_event_and_skill_id(self) -> None:
        actor = GatewayActor(subject="u1")

        with self.assertRaises(ValueError):
            record_skill_event(actor=actor, event_type="unknown", agent="codex", skill_id="sales")

        with self.assertRaises(ValueError):
            record_skill_event(actor=actor, event_type="started", agent="codex", skill_id="")

    def test_record_skill_event_is_idempotent_and_normalizes_plugin_skill_name(self) -> None:
        actor = GatewayActor(subject="u1")
        with (
            patch(
                "gateway_mcp.services.telemetry.insert_assistant_skill_event",
                return_value={"id": 1, "inserted": False},
            ) as insert_event,
            patch("gateway_mcp.services.telemetry.audit_event") as audit,
            patch("gateway_mcp.services.telemetry.observe_skill_event") as observe,
        ):
            result = record_skill_event(
                actor=actor,
                event_type="started",
                agent="claude",
                skill_id="acme-core:treasury-payments",
                correlation_id="toolu-1",
            )

        self.assertTrue(result["duplicate"])
        self.assertEqual(result["event"]["skill_id"], "treasury-payments")
        self.assertEqual(insert_event.call_args.kwargs["skill_id"], "treasury-payments")
        audit.assert_not_called()
        observe.assert_not_called()

    def test_finish_session_closes_each_open_skill_with_original_invocation(self) -> None:
        actor = GatewayActor(subject="u1")
        open_event = {
            "agent": "claude",
            "skill_id": "treasury-payments",
            "skill_pack": "acme-core",
            "skill_version": "0.16.0",
            "correlation_id": "toolu-1",
            "project": "acme",
            "elapsed_ms": 3210,
        }
        with (
            patch("gateway_mcp.services.telemetry.open_assistant_skill_events", return_value=[open_event]) as find_open,
            patch(
                "gateway_mcp.services.telemetry.record_skill_event",
                return_value={"event": {"skill_id": "treasury-payments"}},
            ) as record,
        ):
            result = finish_session_skills(
                actor=actor,
                agent="claude",
                session_id="session-1",
            )

        self.assertEqual(result["finished_count"], 1)
        find_open.assert_called_once_with(actor_subject="u1", session_id="session-1", agent="claude")
        self.assertEqual(record.call_args.kwargs["correlation_id"], "toolu-1")
        self.assertEqual(record.call_args.kwargs["duration_ms"], 3210)

    def test_skill_stats_delegates_filters(self) -> None:
        with patch("gateway_mcp.services.telemetry.assistant_skill_stats", return_value=[{"skill_id": "sales"}]) as stats:
            result = skill_stats(days=7, limit=5, agent="codex", skill_pack="business-growth")

        self.assertEqual(result["count"], 1)
        stats.assert_called_once_with(
            days=7,
            limit=5,
            agent="codex",
            skill_id="",
            skill_pack="business-growth",
            skill_version="",
            project="",
            actor_subject="",
        )

    def test_skill_stats_infers_pack_from_namespaced_skill(self) -> None:
        with patch(
            "gateway_mcp.services.telemetry.assistant_skill_stats", return_value=[]
        ) as stats:
            skill_stats(days=30, limit=25, skill_id="acme-core:treasury-payments")

        self.assertEqual(stats.call_args.kwargs["skill_id"], "treasury-payments")
        self.assertEqual(stats.call_args.kwargs["skill_pack"], "acme-core")

    def test_record_usage_report_stores_actual_usage_and_redacts_metadata(self) -> None:
        actor = GatewayActor(subject="u1", email="user@example.com")

        with (
            patch("gateway_mcp.services.telemetry.insert_assistant_usage_event", return_value={"id": 1}) as insert_usage,
            patch("gateway_mcp.services.telemetry.audit_event") as audit,
        ):
            result = record_usage_report(
                actor=actor,
                agent="claude",
                source="claude_hook",
                source_quality="actual",
                event_name="PostToolUse",
                provider="anthropic",
                model="claude-sonnet",
                session_id="session-1",
                skill_id="skill-developer",
                input_tokens=100,
                output_tokens=25,
                cache_read_input_tokens=10,
                metadata_json=json.dumps({"token": "secret", "usage_class_hint": "M"}),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["usage"]["total_tokens"], 125)
        self.assertEqual(insert_usage.call_args.kwargs["metadata"]["token"], "[redacted]")
        self.assertEqual(insert_usage.call_args.kwargs["source_quality"], "actual")
        self.assertEqual(insert_usage.call_args.kwargs["cache_read_input_tokens"], 10)
        self.assertEqual(audit.call_args.kwargs["event"], "assistant_usage_event")

    def test_record_usage_report_validates_quality_and_class(self) -> None:
        actor = GatewayActor(subject="u1")

        with self.assertRaises(ValueError):
            record_usage_report(actor=actor, agent="claude", source_quality="precise")

        with self.assertRaises(ValueError):
            record_usage_report(actor=actor, agent="claude", usage_class="huge")

    def test_usage_summary_delegates_filters(self) -> None:
        with patch("gateway_mcp.services.telemetry.assistant_usage_summary", return_value=[{"agent": "claude"}]) as summary:
            result = usage_summary(days=14, limit=10, agent="claude", project="acme", source_quality="actual")

        self.assertEqual(result["count"], 1)
        summary.assert_called_once_with(
            days=14,
            limit=10,
            agent="claude",
            skill_id="",
            project="acme",
            source_quality="actual",
        )

    def test_usage_http_route_accepts_gateway_jwt(self) -> None:
        from gateway_mcp.routes.telemetry import register_telemetry_routes

        fake = FakeMcp()
        register_telemetry_routes(fake)
        request = Mock()
        request.headers = {"authorization": "Bearer user-jwt"}
        request.json = AsyncMock(
            return_value={
                "agent": "claude",
                "source_quality": "actual",
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        )

        with (
            patch("gateway_mcp.routes.telemetry.auth_enabled", return_value=True),
            patch("gateway_mcp.routes.telemetry.decode_gateway_token", return_value={"sub": "user:roman"}),
            patch(
                "gateway_mcp.routes.telemetry.actor_from_claims",
                return_value=GatewayActor(subject="user:roman", scopes=("telemetry:write",)),
            ),
            patch("gateway_mcp.routes.telemetry.record_usage_report", return_value={"ok": True, "stored": True}) as report,
        ):
            response = asyncio.run(fake.routes["/telemetry/usage"]["func"](request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body["ok"], True)
        self.assertEqual(report.call_args.kwargs["actor"].subject, "user:roman")
        self.assertEqual(report.call_args.kwargs["input_tokens"], 5)
        self.assertEqual(report.call_args.kwargs["output_tokens"], 3)
        self.assertEqual(report.call_args.kwargs["raw_event_json"], "{}")


if __name__ == "__main__":
    unittest.main()
