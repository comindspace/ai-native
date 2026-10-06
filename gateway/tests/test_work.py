import unittest
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.work import (
    accept_work,
    claim_work,
    complete_work,
    intake_work,
    record_artifact_manifest,
    record_event,
    resolve_project_scope,
    set_tracker_completion_policy,
)


class WorkServiceTests(unittest.TestCase):
    def test_claim_does_not_write_a_second_non_atomic_admission(self):
        actor = GatewayActor(subject="worker")
        row = {"work_id": "work-1", "project_id": "demo", "status": "running"}
        with (
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.claim_work_run",
                return_value=row,
            ),
            patch("gateway_mcp.services.work.storage_work.insert_work_event") as insert,
        ):
            self.assertEqual(claim_work(actor=actor, project_id="demo"), row)
        insert.assert_not_called()

    def test_generic_event_cannot_bypass_artifact_chain_validation(self) -> None:
        actor = GatewayActor(subject="service:factory")
        running = {"work_id": "work-1", "project_id": "demo", "status": "running"}
        with (
            patch("gateway_mcp.services.work.get_work", return_value=running),
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            with self.assertRaisesRegex(ValueError, "event_type must be one of"):
                record_event(
                    actor=actor,
                    work_id="work-1",
                    event_type="artifact_manifest",
                    payload={"digest": "forged"},
                )

    def test_artifact_manifest_builds_a_hash_linked_phase_chain(self) -> None:
        actor = GatewayActor(subject="service:factory")
        running = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "running",
        }
        latest = {}

        def append_event(**kwargs):
            payload = kwargs["payload_factory"](latest)
            latest.clear()
            latest.update(payload)
            event = {"event_type": kwargs["event_type"], "payload": payload}
            return running, event

        with (
            patch("gateway_mcp.services.work.get_work", return_value=running),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.append_work_event_locked",
                side_effect=append_event,
            ),
        ):
            planning = record_artifact_manifest(
                actor=actor,
                work_id="work-1",
                phase="planning",
                refs=[{"type": "work_contract", "uri": "gateway-work://work-1"}],
                checks=[{"name": "scope", "status": "pass"}],
                producer="hermes",
            )

        digest = planning["event"]["payload"]["digest"]
        self.assertEqual(len(digest), 64)
        self.assertEqual(planning["event"]["payload"]["sequence"], 1)

        with (
            patch("gateway_mcp.services.work.get_work", return_value=running),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.append_work_event_locked",
                side_effect=append_event,
            ),
        ):
            implementation = record_artifact_manifest(
                actor=actor,
                work_id="work-1",
                phase="implementation",
                refs=[{"type": "commit", "uri": "https://gitlab.example/commit/abc"}],
                checks=[],
                producer="codex",
                previous_digest=digest,
            )

        self.assertEqual(implementation["event"]["payload"]["sequence"], 2)
        self.assertEqual(implementation["event"]["payload"]["previous_digest"], digest)

    def test_artifact_manifest_rejects_a_stale_or_invalid_phase(self) -> None:
        actor = GatewayActor(subject="service:factory")
        prior = {
            "event_type": "artifact_manifest",
            "payload": {
                "phase": "planning",
                "sequence": 1,
                "digest": "a" * 64,
            },
        }
        work = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "running",
        }

        def append_event(**kwargs):
            payload = kwargs["payload_factory"](prior["payload"])
            return work, {"event_type": kwargs["event_type"], "payload": payload}

        with (
            patch("gateway_mcp.services.work.get_work", return_value=work),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.append_work_event_locked",
                side_effect=append_event,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "previous_digest"):
                record_artifact_manifest(
                    actor=actor,
                    work_id="work-1",
                    phase="implementation",
                    refs=[{"type": "commit", "uri": "https://example/commit/1"}],
                    checks=[],
                    producer="codex",
                    previous_digest="b" * 64,
                )

            with self.assertRaisesRegex(
                ValueError, "invalid artifact phase transition"
            ):
                record_artifact_manifest(
                    actor=actor,
                    work_id="work-1",
                    phase="delivery",
                    refs=[{"type": "mr", "uri": "https://example/mr/1"}],
                    checks=[],
                    producer="hermes",
                    previous_digest="a" * 64,
                )

    def test_local_intake_starts_immediately_and_builds_portable_contract(self) -> None:
        actor = GatewayActor(subject="user:roman", email="roman@example.com")
        stored = {}

        def fake_insert(values):
            stored.update(values)
            return values

        with (
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_run",
                side_effect=fake_insert,
            ),
            patch("gateway_mcp.services.work.storage_work.insert_work_event") as event,
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            result = intake_work(
                actor=actor,
                project_id="demo",
                project_path="ai-factory/demo",
                scope_id="scope-1",
                scope_decision="within_scope",
                source_type="chat",
                source_ref="codex-task:123",
                intent_summary="Add deterministic priority validation",
                acceptance_criteria=["Invalid priority is rejected"],
                quality_gates=["python -m unittest"],
                execution_mode="local",
                sdd_level="S1",
            )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["claimed_by"], actor.subject)
        self.assertEqual(result["contract"]["scope_id"], "scope-1")
        self.assertIn("merge", result["contract"]["forbidden_actions"])
        self.assertEqual(result["contract"]["schema_version"], "1.1")
        self.assertFalse(result["contract"]["tracker_completion_policy"]["auto_close"])
        self.assertEqual(
            result["contract"]["tracker_completion_policy"]["close_when"],
            "acceptance_tests_passed",
        )
        event.assert_called_once()

    def test_intake_persists_explicit_tracker_completion_policy(self) -> None:
        actor = GatewayActor(subject="user:roman", email="roman@example.com")
        with (
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_run",
                side_effect=lambda values: values,
            ),
            patch("gateway_mcp.services.work.storage_work.insert_work_event"),
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            result = intake_work(
                actor=actor,
                project_id="demo",
                project_path="ai-factory/demo",
                scope_id="scope-1",
                scope_decision="within_scope",
                source_type="tracker",
                source_ref="DEMO-1",
                intent_summary="Implement and verify the requested change",
                acceptance_criteria=["Change is verified in the test environment"],
                quality_gates=["pytest"],
                execution_mode="local",
                sdd_level="S1",
                tracker_completion_policy={
                    "issue_key": "DEMO-1",
                    "close_when": "deployed_and_verified",
                    "required_evidence": [
                        "merge_commit",
                        "deployment_ref",
                        "acceptance_test_result",
                    ],
                    "auto_close": False,
                },
            )

        policy = result["contract"]["tracker_completion_policy"]
        self.assertEqual(policy["issue_key"], "DEMO-1")
        self.assertEqual(policy["close_when"], "deployed_and_verified")
        self.assertEqual(policy["required_evidence"][0], "merge_commit")

    def test_idempotent_intake_does_not_duplicate_created_event(self) -> None:
        actor = GatewayActor(subject="service:factory")

        def existing(values):
            return {**values, "work_id": "work-existing", "_inserted": False}

        with (
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_run",
                side_effect=existing,
            ),
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_event"
            ) as insert_event,
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            result = intake_work(
                actor=actor,
                project_id="demo",
                project_path="ai-factory/demo",
                scope_id="scope-1",
                scope_decision="within_scope",
                source_type="pipeline",
                source_ref="pipeline:42",
                intent_summary="Investigate a failed pipeline",
                acceptance_criteria=["Failure is reproduced and fixed"],
                quality_gates=["pipeline passes"],
                execution_mode="factory",
                sdd_level="S1",
                idempotency_key="pipeline:42",
            )

        self.assertEqual(result["work_id"], "work-existing")
        self.assertNotIn("_inserted", result)
        insert_event.assert_not_called()

    def test_intake_rejects_tracker_auto_close(self) -> None:
        with self.assertRaisesRegex(ValueError, "auto_close must remain false"):
            intake_work(
                actor=GatewayActor(subject="u1"),
                project_id="demo",
                scope_id="scope-1",
                scope_decision="within_scope",
                source_type="tracker",
                source_ref="DEMO-1",
                intent_summary="Do work",
                acceptance_criteria=["Done"],
                quality_gates=["test"],
                execution_mode="local",
                sdd_level="S1",
                tracker_completion_policy={"issue_key": "DEMO-1", "auto_close": True},
            )

    def test_factory_intake_is_queued(self) -> None:
        actor = GatewayActor(subject="user:roman")
        with (
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_run",
                side_effect=lambda values: values,
            ),
            patch("gateway_mcp.services.work.storage_work.insert_work_event"),
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            result = intake_work(
                actor=actor,
                project_id="demo",
                scope_id="scope-1",
                scope_decision="clarification",
                source_type="meeting",
                intent_summary="Clarify validation behavior",
                acceptance_criteria=["Behavior is covered by a test"],
                quality_gates=["pytest"],
                execution_mode="factory",
                sdd_level="S3",
            )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["claimed_by"], "")

    def test_resumed_factory_work_returns_to_claimable_queue(self) -> None:
        actor = GatewayActor(subject="service:factory")
        existing = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "blocked",
            "execution_mode": "factory",
            "claimed_by": actor.subject,
        }
        transitioned = {
            **existing,
            "status": "queued",
            "claimed_by": "",
            "lease_expires_at": None,
        }
        event = {"event_type": "resumed"}
        with (
            patch("gateway_mcp.services.work.get_work", return_value=existing),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.transition_work_run",
                return_value=(transitioned, event),
            ) as transition,
        ):
            result = record_event(
                actor=actor,
                work_id="work-1",
                event_type="resumed",
                payload={"reason": "dependency restored"},
            )

        self.assertEqual(result["work"]["status"], "queued")
        self.assertEqual(result["work"]["claimed_by"], "")
        transition.assert_called_once_with(
            work_id="work-1",
            expected_statuses={"blocked"},
            values={"status": "queued", "claimed_by": "", "lease_expires_at": None},
            actor_subject=actor.subject,
            event_type="resumed",
            event_payload={"reason": "dependency restored"},
        )

    def test_intake_normalizes_priority_and_rejects_ambiguous_types(self) -> None:
        actor = GatewayActor(subject="user:roman")
        base = {
            "actor": actor,
            "project_id": "demo",
            "scope_id": "scope-1",
            "scope_decision": "within_scope",
            "source_type": "chat",
            "intent_summary": "Prioritize work",
            "acceptance_criteria": ["Priority is deterministic"],
            "quality_gates": ["test"],
            "execution_mode": "factory",
            "sdd_level": "S1",
        }
        with (
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_run",
                side_effect=lambda values: values,
            ),
            patch("gateway_mcp.services.work.storage_work.insert_work_event"),
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            result = intake_work(**base, priority=1000)
            self.assertEqual(result["priority"], 100)
            self.assertEqual(result["contract"]["priority"], 100)
            for value in (True, "10", 1.5):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        TypeError, "priority must be an integer"
                    ):
                        intake_work(**base, priority=value)

    def test_executable_work_requires_scope_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "scope_id"):
            intake_work(
                actor=GatewayActor(subject="u1"),
                project_id="demo",
                scope_decision="within_scope",
                source_type="chat",
                intent_summary="Do work",
                acceptance_criteria=["Done"],
                quality_gates=["test"],
                execution_mode="local",
                sdd_level="S0",
            )

    def test_complete_is_idempotent_after_acceptance(self) -> None:
        actor = GatewayActor(subject="service:factory")
        accepted = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "accepted",
            "accepted_at": "2026-08-13T20:00:00+00:00",
            "first_verified_at": "2026-08-13T19:58:00+00:00",
            "completed_at": "2026-08-13T19:59:00+00:00",
        }
        with (
            patch("gateway_mcp.services.work.get_work", return_value=accepted),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.transition_work_run"
            ) as transition,
        ):
            result = complete_work(
                actor=actor,
                work_id="work-1",
                success=True,
                result_refs=[
                    {
                        "ref_type": "gitlab_mr",
                        "url": "https://gitlab.example/project/-/merge_requests/1",
                        "name": "MR !1",
                    }
                ],
                evidence_state="complete",
            )

        self.assertEqual(result["status"], "accepted")
        transition.assert_not_called()

    def test_complete_atomically_records_state_and_event(self) -> None:
        actor = GatewayActor(subject="service:factory")
        running = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "review",
            "first_verified_at": None,
            "completed_at": None,
        }

        def fake_transition(**kwargs):
            return {**running, **kwargs["values"]}, {"event_type": kwargs["event_type"]}

        with (
            patch("gateway_mcp.services.work.get_work", return_value=running),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.transition_work_run",
                side_effect=fake_transition,
            ) as transition,
        ):
            result = complete_work(
                actor=actor,
                work_id="work-1",
                success=True,
                result_refs=[
                    {
                        "ref_type": "gitlab_mr",
                        "url": "https://gitlab.example/project/-/merge_requests/1",
                        "name": "MR !1",
                    }
                ],
                evidence_state="complete",
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            transition.call_args.kwargs["expected_statuses"], {"running", "review"}
        )
        self.assertEqual(transition.call_args.kwargs["event_type"], "completed")
        self.assertEqual(result["result_refs"][0]["type"], "gitlab_mr")

    def test_accept_preserves_the_first_acceptance_timestamp(self) -> None:
        actor = GatewayActor(subject="service:factory")
        existing = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "completed",
            "accepted_at": "2026-08-13T20:00:00+00:00",
            "first_verified_at": "2026-08-13T19:59:00+00:00",
        }
        with (
            patch("gateway_mcp.services.work.get_work", return_value=existing),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.transition_work_run",
                side_effect=lambda **kwargs: (
                    {**existing, **kwargs["values"]},
                    {"event_type": "accepted"},
                ),
            ) as transition,
        ):
            result = accept_work(
                actor=actor,
                work_id="work-1",
                accepted=True,
                decision_ref="https://gitlab.example/project/-/merge_requests/1",
            )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(
            transition.call_args.kwargs["values"]["accepted_at"],
            existing["accepted_at"],
        )

    def test_accept_requires_completed_status(self) -> None:
        actor = GatewayActor(subject="service:factory")
        review = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "review",
            "first_verified_at": "2026-08-13T19:59:00+00:00",
        }
        with (
            patch("gateway_mcp.services.work.get_work", return_value=review),
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            with self.assertRaisesRegex(
                ValueError, "completed with verification evidence"
            ):
                accept_work(actor=actor, work_id="work-1", accepted=True)

    def test_context_usage_is_a_supported_metadata_event(self) -> None:
        actor = GatewayActor(subject="service:factory")
        running = {"work_id": "work-1", "project_id": "demo", "status": "running"}
        with (
            patch("gateway_mcp.services.work.get_work", return_value=running),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.insert_work_event",
                return_value={"event_type": "context_usage"},
            ) as insert_event,
        ):
            result = record_event(
                actor=actor,
                work_id="work-1",
                event_type="context_usage",
                payload={"phase": "routing", "budget_tokens": 1200},
            )

        self.assertEqual(result["work"]["status"], "running")
        insert_event.assert_called_once()

    def test_accept_rejects_work_without_verification_evidence(self) -> None:
        actor = GatewayActor(subject="service:factory")
        queued = {
            "work_id": "work-1",
            "project_id": "demo",
            "status": "in_progress",
            "first_verified_at": None,
        }
        with (
            patch("gateway_mcp.services.work.get_work", return_value=queued),
            patch("gateway_mcp.services.work._require_project_access"),
        ):
            with self.assertRaisesRegex(ValueError, "verification evidence"):
                accept_work(
                    actor=actor,
                    work_id="work-1",
                    accepted=True,
                    decision_ref="https://gitlab.example/project/-/merge_requests/1",
                )

    def test_tracker_policy_can_be_added_to_an_existing_contract(self) -> None:
        actor = GatewayActor(subject="service:factory")
        existing = {
            "work_id": "work-1",
            "project_id": "demo",
            "contract": {"schema_version": "1.0", "intent": "Do work"},
        }
        with (
            patch("gateway_mcp.services.work.get_work", return_value=existing),
            patch("gateway_mcp.services.work._require_project_access"),
            patch(
                "gateway_mcp.services.work.storage_work.update_work_run",
                side_effect=lambda _work_id, values: {**existing, **values},
            ) as update,
            patch("gateway_mcp.services.work.storage_work.insert_work_event") as event,
        ):
            result = set_tracker_completion_policy(
                actor=actor,
                work_id="work-1",
                policy={"issue_key": "DEMO-1", "auto_close": False},
            )

        contract = update.call_args.args[1]["contract"]
        self.assertEqual(contract["schema_version"], "1.1")
        self.assertEqual(contract["tracker_completion_policy"]["issue_key"], "DEMO-1")
        self.assertFalse(result["contract"]["tracker_completion_policy"]["auto_close"])
        event.assert_called_once()


class ScopeResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolver_returns_sources_for_agent_classification(self) -> None:
        with patch(
            "gateway_mcp.services.work.search_company_index",
            AsyncMock(return_value=[{"source": "yonote", "data": {"id": "scope-1"}}]),
        ):
            result = await resolve_project_scope(
                project_id="demo",
                signal_summary="priority validation",
                scope_id="",
                tools_registry={"tools": []},
            )

        self.assertEqual(result["decision"], "needs_agent_classification")
        self.assertEqual(result["candidates"][0]["source"], "yonote")


if __name__ == "__main__":
    unittest.main()
