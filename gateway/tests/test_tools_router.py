import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.tools.router import register_router_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class RouterToolTests(unittest.TestCase):
    def test_gateway_call_returns_compact_payload_and_audits_access(self) -> None:
        fake = FakeMcp()
        register_router_tools(fake)
        route = {
            "name": "yonote.documents.get",
            "backend": "yonote",
            "scope": "yonote:read",
            "status": "implemented",
        }
        decision = {
            "decision": "allow",
            "reason": "matched_allow",
            "mode": "strict",
            "shadow_decision": "allow",
            "system": "yonote",
            "action": "read",
            "actions": ["read"],
            "resource_type": "document",
            "resource": "doc-1",
            "subjects": [{"type": "user", "key": "user@example.com"}],
            "matched": [{"id": 17, "effect": "allow"}],
            "constraint_rules": [{"grant_id": 17, "constraints": {}}],
            "shadow_constraint_rules": [],
        }
        backend_result = {
            "ok": True,
            "status": 200,
            "backend": "yonote",
            "method": "GET",
            "path": "/documents/doc-1",
            "data": {"id": "doc-1", "title": "Architecture"},
        }
        run = Mock()

        with (
            patch("gateway_mcp.tools.router.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.router.read_json", return_value={"tools": [route]}
            ),
            patch(
                "gateway_mcp.tools.router.current_actor",
                return_value=GatewayActor(subject="user:roman"),
            ),
            patch(
                "gateway_mcp.tools.router.require_resource_access",
                return_value=decision,
            ),
            patch(
                "gateway_mcp.tools.router.call_backend",
                new=AsyncMock(return_value=backend_result),
            ),
            patch("gateway_mcp.tools.router.audit_event") as audit,
            patch("gateway_mcp.tools.router.uuid4") as request_id,
        ):
            request_id.return_value.hex = "0123456789abcdef0123456789abcdef"
            raw = asyncio.run(
                fake.tools["gateway_call_tool"](
                    "yonote.documents.get", '{"document_id":"doc-1"}'
                )
            )

        self.assertEqual(
            json.loads(raw),
            {
                "ok": True,
                "status": 200,
                "data": {"id": "doc-1", "title": "Architecture"},
                "gateway_request_id": "0123456789abcdef",
            },
        )
        for hidden in ("access", "backend", "method", "path", "route", "tool_name"):
            self.assertNotIn(hidden, raw)
        self.assertNotIn("subjects", raw)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["event"], "resource_access")
        self.assertEqual(
            audit.call_args.kwargs["arguments"]["matched_grant_ids"], ["17"]
        )
        self.assertNotIn("subjects", audit.call_args.kwargs["arguments"])

    def test_protected_route_requires_approval_reference(self) -> None:
        fake = FakeMcp()
        register_router_tools(fake)
        route = {
            "name": "gitlab.pipeline_jobs.play",
            "backend": "gitlab",
            "http_method": "POST",
            "scope": "gitlab:deploy",
            "requires_approval_ref": True,
            "requires_idempotency_key": True,
        }
        run = Mock()

        with (
            patch("gateway_mcp.tools.router.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.router.read_json", return_value={"tools": [route]}
            ),
            patch(
                "gateway_mcp.tools.router.call_backend", new_callable=AsyncMock
            ) as backend,
            self.assertRaisesRegex(ValueError, "approval_ref is required"),
        ):
            asyncio.run(
                fake.tools["gateway_call_tool"](
                    "gitlab.pipeline_jobs.play",
                    json.dumps({"project_id": 241, "job_id": 100}),
                    "deploy-241-100",
                )
            )

        with (
            patch("gateway_mcp.tools.router.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.router.read_json", return_value={"tools": [route]}
            ),
            patch(
                "gateway_mcp.tools.router.call_backend", new_callable=AsyncMock
            ) as backend_without_key,
            self.assertRaisesRegex(ValueError, "idempotency_key is required"),
        ):
            asyncio.run(
                fake.tools["gateway_call_tool"](
                    "gitlab.pipeline_jobs.play",
                    json.dumps(
                        {
                            "project_id": 241,
                            "job_id": 100,
                            "approval_ref": "chat:2026-09-03:roman",
                        }
                    ),
                )
            )

        backend.assert_not_awaited()
        backend_without_key.assert_not_awaited()
        self.assertEqual(run.error.call_count, 2)

    def test_deploy_scope_route_uses_idempotency_and_audits_approval(self) -> None:
        fake = FakeMcp()
        register_router_tools(fake)
        route = {
            "name": "gitlab.pipeline_jobs.play",
            "backend": "gitlab",
            "http_method": "POST",
            "scope": "gitlab:deploy",
            "requires_approval_ref": True,
            "requires_idempotency_key": True,
        }
        run = Mock()
        actor = GatewayActor(subject="service:release-agent")
        call_arguments = {
            "project_id": 241,
            "job_id": 100,
            "approval_ref": "chat:2026-09-03:roman",
        }

        with (
            patch("gateway_mcp.tools.router.ToolRun.start", return_value=run) as start,
            patch(
                "gateway_mcp.tools.router.read_json", return_value={"tools": [route]}
            ),
            patch("gateway_mcp.tools.router.current_actor", return_value=actor),
            patch(
                "gateway_mcp.tools.router.require_resource_access",
                return_value={"decision": "allow", "action": "deploy"},
            ) as require_access,
            patch(
                "gateway_mcp.tools.router.claim_idempotency",
                return_value={"claimed": True, "replayed": False},
            ) as claim,
            patch(
                "gateway_mcp.tools.router.validate_and_consume_approval",
                return_value={"approval_id": "chat:2026-09-03:roman"},
            ) as consume_approval,
            patch("gateway_mcp.tools.router.complete_idempotency") as complete,
            patch(
                "gateway_mcp.tools.router.call_backend",
                new_callable=AsyncMock,
                return_value={"ok": True, "data": {"status": "pending"}},
            ) as backend,
        ):
            result = asyncio.run(
                fake.tools["gateway_call_tool"](
                    "gitlab.pipeline_jobs.play",
                    json.dumps(call_arguments),
                    "deploy-241-100",
                )
            )

        payload = json.loads(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["idempotency"],
            {"key": "deploy-241-100", "replayed": False},
        )
        audit_arguments = start.call_args.kwargs["arguments"]
        self.assertEqual(
            audit_arguments["arguments"]["approval_ref"],
            "chat:2026-09-03:roman",
        )
        self.assertEqual(audit_arguments["idempotency_key"], "deploy-241-100")
        run.require_scope.assert_any_call(
            "gitlab:deploy", tool="gitlab.pipeline_jobs.play"
        )
        require_access.assert_called_once_with(
            actor=actor,
            route=route,
            arguments=call_arguments,
        )
        claim.assert_called_once()
        consume_approval.assert_called_once()
        backend.assert_awaited_once_with(
            route,
            {"project_id": 241, "job_id": 100},
        )
        complete.assert_called_once()

    def test_replayed_write_call_does_not_call_backend_again(self) -> None:
        fake = FakeMcp()
        register_router_tools(fake)
        route = {
            "name": "bitrix24.deals.update",
            "backend": "bitrix24",
            "scope": "bitrix24:write",
        }
        cached = {"ok": True, "data": {"id": "1753"}}
        run = Mock()

        with (
            patch("gateway_mcp.tools.router.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.router.read_json", return_value={"tools": [route]}
            ),
            patch(
                "gateway_mcp.tools.router.current_actor",
                return_value=GatewayActor(subject="service:notifier"),
            ),
            patch(
                "gateway_mcp.tools.router.require_resource_access",
                return_value={"decision": "allow"},
            ),
            patch(
                "gateway_mcp.tools.router.claim_idempotency",
                return_value={"claimed": False, "replayed": True, "response": cached},
            ),
            patch(
                "gateway_mcp.tools.router.call_backend", new_callable=AsyncMock
            ) as backend,
        ):
            result = asyncio.run(
                fake.tools["gateway_call_tool"](
                    "bitrix24.deals.update",
                    json.dumps({"id": 1753, "fields": {"TITLE": "Updated"}}),
                    "demo-call-1",
                )
            )

        payload = json.loads(result)
        self.assertEqual(payload["data"]["id"], "1753")
        self.assertEqual(
            payload["idempotency"], {"key": "demo-call-1", "replayed": True}
        )
        backend.assert_not_awaited()
        run.finish.assert_called_once_with(status="ok", scope="bitrix24:write")

    def test_successful_write_survives_idempotency_completion_failure(self) -> None:
        fake = FakeMcp()
        register_router_tools(fake)
        route = {
            "name": "bitrix24.deals.update",
            "backend": "bitrix24",
            "scope": "bitrix24:write",
        }
        run = Mock()

        with (
            patch("gateway_mcp.tools.router.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.router.read_json", return_value={"tools": [route]}
            ),
            patch(
                "gateway_mcp.tools.router.current_actor",
                return_value=GatewayActor(subject="service:notifier"),
            ),
            patch(
                "gateway_mcp.tools.router.require_resource_access",
                return_value={"decision": "allow"},
            ),
            patch(
                "gateway_mcp.tools.router.claim_idempotency",
                return_value={"claimed": True, "replayed": False},
            ),
            patch(
                "gateway_mcp.tools.router.call_backend",
                new_callable=AsyncMock,
                return_value={"ok": True, "data": {"id": "1753"}},
            ),
            patch(
                "gateway_mcp.tools.router.complete_idempotency",
                side_effect=RuntimeError("database unavailable"),
            ),
            patch("gateway_mcp.tools.router.fail_idempotency") as fail,
            patch("gateway_mcp.tools.router.record_upstream_error") as record_error,
        ):
            result = asyncio.run(
                fake.tools["gateway_call_tool"](
                    "bitrix24.deals.update",
                    json.dumps({"id": 1753, "fields": {"TITLE": "Updated"}}),
                    "demo-call-2",
                )
            )

        payload = json.loads(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["idempotency"]["stored"], False)
        fail.assert_not_called()
        record_error.assert_called_once_with("gateway", "idempotency_RuntimeError")


if __name__ == "__main__":
    unittest.main()
