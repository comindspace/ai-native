import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import approvals, policy


class ApprovalServiceTests(unittest.TestCase):
    def test_create_approval_computes_hash_and_stores_creator(self) -> None:
        actor = policy.GatewayActor(
            subject="user:init",
            groups=("architects",),
            scopes=("approvals:write",),
        )

        def insert(**kwargs):
            self.assertEqual(kwargs["created_by"], "user:init")
            self.assertEqual(kwargs["approval_type"], "production_deploy")
            self.assertEqual(kwargs["required_role"], "architects")
            self.assertTrue(kwargs["artifact_hash"].startswith("sha256:"))
            return {"approval_id": kwargs["approval_id"], **kwargs, "status": "pending"}

        with (
            patch(
                "gateway_mcp.services.approvals.insert_approval_request",
                side_effect=insert,
            ),
            patch(
                "gateway_mcp.services.approvals.list_approval_events",
                return_value=[],
            ),
            patch(
                "gateway_mcp.services.approvals.new_approval_id",
                return_value="apr-production-deploy-test",
            ),
        ):
            result = approvals.create_approval(
                actor=actor,
                approval_type="production_deploy",
                subject="Release 1.4",
                required_role="architects",
                required_scope="",
                artifact_hash="",
                artifact_version="commit:abc123",
                payload_json='{"project_id":"demo","environment":"prod"}',
                source_refs_json='{"work_id":"work-1"}',
                metadata_json="{}",
                four_eyes=True,
                expires_in_days=14,
            )

        self.assertEqual(
            result["approval"]["approval_id"], "apr-production-deploy-test"
        )

    def test_decision_rejects_creator_when_four_eyes_enabled(self) -> None:
        actor = policy.GatewayActor(
            subject="user:init",
            groups=("architects",),
            scopes=("approvals:write",),
        )
        approval = {
            "approval_id": "apr-1",
            "status": "pending",
            "created_by": "user:init",
            "required_role": "architects",
            "required_scope": "",
            "four_eyes": True,
        }

        with (
            patch(
                "gateway_mcp.services.approvals.get_approval_request",
                return_value=approval,
            ),
            self.assertRaisesRegex(PermissionError, "four-eyes"),
        ):
            approvals.decide_approval(
                actor=actor,
                approval_id="apr-1",
                decision="approved",
                comment="ok",
                decision_payload_json="{}",
            )

    def test_required_role_can_decide_once(self) -> None:
        actor = policy.GatewayActor(
            subject="user:reviewer",
            groups=("architects",),
            scopes=("approvals:write",),
        )
        approval = {
            "approval_id": "apr-1",
            "status": "pending",
            "created_by": "user:init",
            "required_role": "architects",
            "required_scope": "",
            "four_eyes": True,
        }

        with (
            patch(
                "gateway_mcp.services.approvals.get_approval_request",
                return_value=approval,
            ),
            patch(
                "gateway_mcp.services.approvals.update_approval_decision",
                return_value={
                    **approval,
                    "status": "approved",
                    "decided_by": "user:reviewer",
                },
            ) as update,
            patch(
                "gateway_mcp.services.approvals.list_approval_events",
                return_value=[],
            ),
        ):
            result = approvals.decide_approval(
                actor=actor,
                approval_id="apr-1",
                decision="approved",
                comment="Согласовано",
                decision_payload_json='{"checked":true}',
            )

        self.assertEqual(result["approval"]["status"], "approved")
        self.assertEqual(update.call_args.kwargs["actor_groups"], ["architects"])
        self.assertEqual(update.call_args.kwargs["decision_payload"], {"checked": True})

    def test_atomic_decision_failure_is_reported(self) -> None:
        actor = policy.GatewayActor(
            subject="user:reviewer",
            groups=("architects",),
            scopes=("approvals:write",),
        )
        approval = {
            "approval_id": "apr-1",
            "status": "pending",
            "created_by": "user:init",
            "required_role": "architects",
            "required_scope": "",
            "four_eyes": True,
        }
        with (
            patch(
                "gateway_mcp.services.approvals.get_approval_request",
                return_value=approval,
            ),
            patch(
                "gateway_mcp.services.approvals.update_approval_decision",
                return_value=None,
            ),
            self.assertRaisesRegex(ValueError, "already decided"),
        ):
            approvals.decide_approval(
                actor=actor,
                approval_id="apr-1",
                decision="approved",
                comment="ok",
                decision_payload_json="{}",
            )

    def test_expired_approval_cannot_be_decided(self) -> None:
        actor = policy.GatewayActor(
            subject="user:reviewer",
            groups=("architects",),
            scopes=("approvals:write",),
        )
        approval = {
            "approval_id": "apr-1",
            "status": "pending",
            "created_by": "user:init",
            "required_role": "architects",
            "required_scope": "",
            "four_eyes": True,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
        with (
            patch(
                "gateway_mcp.services.approvals.get_approval_request",
                return_value=approval,
            ),
            self.assertRaisesRegex(ValueError, "expired"),
        ):
            approvals.decide_approval(
                actor=actor,
                approval_id="apr-1",
                decision="approved",
                comment="ok",
                decision_payload_json="{}",
            )

    def test_list_visible_filters_to_assigned_role(self) -> None:
        actor = policy.GatewayActor(
            subject="user:architect",
            groups=("architects",),
            scopes=("approvals:read",),
        )
        rows = [
            {
                "approval_id": "apr-deploy",
                "created_by": "user:init",
                "required_role": "architects",
                "required_scope": "",
            },
            {
                "approval_id": "apr-finance",
                "created_by": "user:init",
                "required_role": "finance",
                "required_scope": "",
            },
        ]
        with patch(
            "gateway_mcp.services.approvals.list_approval_requests",
            return_value=rows,
        ):
            result = approvals.list_visible_approvals(
                actor=actor,
                status="pending",
                approval_type="",
                created_by="",
                required_role="",
                assigned_to_me=True,
                limit=10,
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["approvals"][0]["approval_id"], "apr-deploy")

    def test_approved_reference_is_bound_to_executor_tool_and_arguments(self) -> None:
        actor = policy.GatewayActor(subject="service:release-agent")
        approval = {
            "approval_id": "apr-deploy",
            "approval_type": "production_deploy",
            "status": "approved",
            "created_by": actor.subject,
            "payload": {
                "tool_name": "gitlab.pipeline_jobs.play",
                "arguments": {"project_id": 241, "job_id": 100},
            },
            "metadata": {},
        }
        with (
            patch(
                "gateway_mcp.services.approvals.get_approval_request",
                return_value=approval,
            ),
            patch(
                "gateway_mcp.services.approvals.consume_approval_request",
                return_value={**approval, "consumed_by": actor.subject},
            ) as consume,
        ):
            result = approvals.validate_and_consume_approval(
                actor=actor,
                approval_id="apr-deploy",
                tool_name="gitlab.pipeline_jobs.play",
                arguments={
                    "project_id": 241,
                    "job_id": 100,
                    "approval_ref": "apr-deploy",
                },
                idempotency_key="deploy-241-100",
                expected_type="production_deploy",
            )

        self.assertEqual(result["consumed_by"], actor.subject)
        consume.assert_called_once()
        self.assertEqual(
            consume.call_args.kwargs["action"], "gitlab.pipeline_jobs.play"
        )

    def test_approved_reference_rejects_changed_invocation(self) -> None:
        actor = policy.GatewayActor(subject="service:release-agent")
        approval = {
            "approval_id": "apr-deploy",
            "approval_type": "production_deploy",
            "status": "approved",
            "created_by": actor.subject,
            "payload": {"arguments": {"project_id": 241, "job_id": 100}},
            "metadata": {},
        }
        with (
            patch(
                "gateway_mcp.services.approvals.get_approval_request",
                return_value=approval,
            ),
            patch("gateway_mcp.services.approvals.consume_approval_request") as consume,
            self.assertRaisesRegex(PermissionError, "does not match"),
        ):
            approvals.validate_and_consume_approval(
                actor=actor,
                approval_id="apr-deploy",
                tool_name="gitlab.pipeline_jobs.play",
                arguments={"project_id": 241, "job_id": 999},
                idempotency_key="deploy-241-999",
                expected_type="production_deploy",
            )
        consume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
