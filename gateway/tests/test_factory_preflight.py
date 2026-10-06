import asyncio
import copy
import json
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import factory_preflight as service
from gateway_mcp.services import storage_factory, storage_work
from gateway_mcp.services.factory_projects import get_factory_runtime_config
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.work import record_event
from gateway_mcp.tools.work import register_work_tools


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.actor = GatewayActor(subject="worker", scopes=("factory:claim",))
        self.work = {
            "work_id": "work-1",
            "project_id": "demo",
            "project_path": "team/repo",
            "status": "running",
            "execution_mode": "factory",
            "claimed_by": "worker",
            "scope_decision": "within_scope",
            "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        }
        self.project = {
            "project_id": "demo",
            "revision": 2,
            "config": {
                "project_id": "demo",
                "project_path": "team/repo",
                "gitlab_clone_url": "https://git.example/team/repo.git",
                "gitlab_web_url": "https://git.example/team/repo",
                "gitlab_connection_id": "gitlab:example",
                "default_base_branch": "main",
                "mr_target_branch": "main",
                "reviewer": "architect",
                "yonote_project_name": "Project context",
            },
            "readiness": {
                "ready": True,
                "checked_at": (now - timedelta(minutes=20)).isoformat(),
                "connection_version": 3,
                "readiness_gaps": [],
                "checks": {},
            },
        }
        self.connection = {"state": "active", "version": 3}
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.claim = stack.enter_context(
            patch.object(service, "claim_work", return_value=self.work)
        )
        self.access = stack.enter_context(
            patch.object(service, "_require_project_access")
        )
        self.lookup = stack.enter_context(
            patch.object(storage_factory, "get_project", return_value=self.project)
        )
        stack.enter_context(
            patch.object(storage_factory, "list_probes", return_value=[])
        )
        stack.enter_context(
            patch(
                "gateway_mcp.services.storage_service_connections.get_service_connection",
                return_value=self.connection,
            )
        )
        self.current_work = stack.enter_context(
            patch.object(storage_work, "get_work_run", return_value=self.work)
        )
        self.refresh = stack.enter_context(
            patch.object(
                service, "_run_validation", AsyncMock(side_effect=self.refreshed)
            )
        )
        self.admit = stack.enter_context(
            patch.object(storage_factory, "admit_work_lease", return_value=self.work)
        )
        self.block = stack.enter_context(
            patch.object(
                storage_work,
                "block_claim_preflight",
                return_value={"status": "blocked"},
            )
        )

    async def refreshed(self, *_args, **_kwargs):
        self.project["readiness"]["checked_at"] = datetime.now(timezone.utc).isoformat()
        return {"ready": True, "readiness_gaps": []}

    async def test_15_minute_queue_wait_refreshes_without_admin_scopes(self):
        result = await service.claim_with_preflight(actor=self.actor, project_id="demo")
        self.assertEqual(result["status"], "running")
        self.refresh.assert_awaited_once()
        actor, config, operation, _key = self.refresh.call_args.args
        self.assertIs(actor, self.actor)
        self.assertEqual(actor.scopes, ("factory:claim",))
        self.assertEqual(config, self.project["config"])
        self.assertEqual(operation, "claim_preflight")
        self.admit.assert_called_once()
        self.block.assert_not_called()

    async def test_fresh_cache_does_not_push_again(self):
        await self.refreshed()
        await service.claim_with_preflight(actor=self.actor, work_id="work-1")
        self.refresh.assert_not_awaited()
        self.admit.assert_called_once()

    async def test_no_claim_or_unregistered_legacy_does_not_probe(self):
        self.claim.return_value = None
        self.assertIsNone(
            await service.claim_with_preflight(actor=self.actor, project_id="demo")
        )
        self.claim.return_value = self.work
        self.lookup.return_value = None
        self.assertIs(
            await service.claim_with_preflight(actor=self.actor, project_id="demo"),
            self.work,
        )
        self.refresh.assert_not_awaited()

    async def test_missing_scope_cannot_claim_or_probe(self):
        with self.assertRaises(PermissionError):
            await service.claim_with_preflight(
                actor=GatewayActor(subject="reader", scopes=("factory:read",)),
                project_id="demo",
            )
        self.claim.assert_not_called()
        self.refresh.assert_not_awaited()

    async def test_repository_mismatch_does_not_probe(self):
        for mismatch in ["path", "backend"]:
            with self.subTest(mismatch=mismatch):
                self.work["project_path"] = (
                    "team/other" if mismatch == "path" else "team/repo"
                )
                self.work["contract"] = {
                    "metadata": {"gitlab_backend": "https://wrong.example"}
                }
                await service.claim_with_preflight(actor=self.actor, project_id="demo")
                self.block.assert_called_with(self.work, ["repository_mapping"])
        self.refresh.assert_not_awaited()

    async def test_failed_probe_returns_blocked_not_claimed_success(self):
        self.refresh.side_effect = None
        self.refresh.return_value = {
            "ready": False,
            "readiness_gaps": ["authentication"],
        }
        result = await service.claim_with_preflight(actor=self.actor, project_id="demo")
        self.assertEqual(result["status"], "blocked")
        self.admit.assert_not_called()
        self.block.assert_called_once_with(self.work, ["authentication"])

    async def test_revoke_or_storage_race_does_not_leave_successful_claim(self):
        self.admit.side_effect = ValueError("synthetic-secret-must-not-escape")
        result = await service.claim_with_preflight(actor=self.actor, project_id="demo")
        self.assertEqual(result["status"], "blocked")
        self.block.assert_called_once_with(self.work, ["preflight_failed"])
        self.assertNotIn("synthetic-secret", json.dumps(result))

    async def test_cancelled_or_timed_out_probe_blocks_current_lease(self):
        for error in [asyncio.CancelledError, TimeoutError]:
            with self.subTest(error=error):
                self.block.reset_mock()
                self.refresh.side_effect = error
                if error is asyncio.CancelledError:
                    with self.assertRaises(asyncio.CancelledError):
                        await service.claim_with_preflight(
                            actor=self.actor, project_id="demo"
                        )
                    self.block.assert_called_once_with(
                        self.work, ["validation_interrupted"]
                    )
                else:
                    result = await service.claim_with_preflight(
                        actor=self.actor, project_id="demo"
                    )
                    self.assertEqual(result["status"], "blocked")
        self.admit.assert_not_called()

    async def test_project_write_denial_prevents_network_probe(self):
        self.access.side_effect = PermissionError
        await service.claim_with_preflight(actor=self.actor, project_id="demo")
        self.refresh.assert_not_awaited()
        self.admit.assert_not_called()

    async def test_lost_lease_or_out_of_scope_cannot_probe(self):
        for field, value in [
            ("claimed_by", "other"),
            ("status", "blocked"),
            ("scope_decision", "scope_change"),
        ]:
            with self.subTest(field=field):
                self.current_work.return_value = {**self.work, field: value}
                await service.claim_with_preflight(actor=self.actor, project_id="demo")
        self.refresh.assert_not_awaited()

    async def test_two_claims_share_one_project_refresh(self):
        second = {**self.work, "work_id": "work-2"}
        self.claim.side_effect = [self.work, second]
        self.current_work.side_effect = lambda work_id: (
            self.work if work_id == "work-1" else second
        )
        started = False
        probes = 0

        async def slow_refresh(*args, **kwargs):
            nonlocal started, probes
            if started:
                raise storage_factory.ValidationInProgress("busy")
            started = True
            probes += 1
            await asyncio.sleep(0.01)
            return await self.refreshed()

        self.refresh.side_effect = slow_refresh
        results = await asyncio.gather(
            service.claim_with_preflight(actor=self.actor, project_id="demo"),
            service.claim_with_preflight(actor=self.actor, project_id="demo"),
        )
        self.assertEqual(probes, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(self.admit.call_count, 2)
        self.block.assert_not_called()

    async def test_validation_starts_just_before_admission_waits(self):
        self.admit.side_effect = [
            storage_factory.ValidationInProgress("busy"),
            self.work,
        ]
        result = await service.claim_with_preflight(actor=self.actor, project_id="demo")
        self.assertEqual(result["status"], "running")
        self.refresh.assert_awaited_once()
        self.block.assert_not_called()

    def event(self):
        checked = self.project["readiness"]["checked_at"]
        return {
            "actor_subject": "worker",
            "occurred_at": (_time(checked) + timedelta(seconds=1)).isoformat(),
            "payload": {
                "ready": True,
                "project_revision": 2,
                "connection_version": 3,
                "checked_at": checked,
                "lease_expires_at": self.work["lease_expires_at"],
            },
        }

    async def runtime(self, work=None, event=None):
        with (
            patch(
                "gateway_mcp.services.factory_projects.get_work",
                return_value=work or self.work,
            ),
            patch("gateway_mcp.services.factory_projects._require_project_access"),
            patch.object(storage_work, "latest_factory_preflight", return_value=event),
        ):
            return await get_factory_runtime_config(
                actor=self.actor, tools_registry={}, work_id="work-1"
            )

    async def test_live_lease_runtime_outlives_diagnostic_ttl_without_write(self):
        result = await self.runtime(event=self.event())
        self.assertTrue(result["project"]["ready"])
        self.assertNotIn("validation_stale", result["project"]["readiness_gaps"])
        self.refresh.assert_not_awaited()
        self.admit.assert_not_called()

    async def test_stale_runtime_requires_valid_server_admission(self):
        for field, value in [
            ("ready", False),
            ("project_revision", 1),
            ("connection_version", 2),
            ("lease_expires_at", "2020-01-01T00:00:00+00:00"),
        ]:
            with self.subTest(field=field):
                event = self.event()
                event["payload"][field] = value
                result = await self.runtime(event=event)
                self.assertIn("validation_stale", result["project"]["readiness_gaps"])
        result = await self.runtime()
        self.assertFalse(result["project"]["ready"])

    async def test_fresh_project_reconfiguration_invalidates_old_lease(self):
        event = self.event()
        await self.refreshed()
        self.project["revision"] += 1
        result = await self.runtime(event=event)
        self.assertFalse(result["project"]["ready"])
        self.assertIn("lease_preflight_required", result["project"]["readiness_gaps"])

    async def test_runtime_still_denies_rotated_revoked_expired_lease(self):
        for connection, work in [
            ({"state": "inactive", "version": 3}, self.work),
            ({"state": "active", "version": 4}, self.work),
            (
                self.connection,
                {**self.work, "lease_expires_at": "2020-01-01T00:00:00+00:00"},
            ),
            (self.connection, {**self.work, "status": "blocked"}),
        ]:
            with patch(
                "gateway_mcp.services.storage_service_connections.get_service_connection",
                return_value=connection,
            ):
                result = await self.runtime(work=work, event=self.event())
            self.assertFalse(result["project"]["ready"])

    def test_worker_cannot_forge_preflight_event(self):
        with (
            patch("gateway_mcp.services.work.get_work", return_value=self.work),
            patch("gateway_mcp.services.work._require_project_access"),
            self.assertRaises(ValueError),
        ):
            record_event(
                actor=self.actor,
                work_id="work-1",
                event_type="factory_preflight",
                payload={"ready": True},
            )

    async def test_mcp_claim_waits_for_preflight_and_reports_failure(self):
        class MCP:
            def __init__(self):
                self.tools = {}

            def tool(self, **_kwargs):
                def register(fn):
                    self.tools[fn.__name__] = fn
                    return fn

                return register

        mcp = MCP()
        register_work_tools(mcp)
        run = MagicMock()
        run.require_scope.return_value = self.actor
        with (
            patch("gateway_mcp.tools.work.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.work.claim_with_preflight",
                AsyncMock(return_value={"status": "blocked"}),
            ) as claim,
        ):
            result = json.loads(
                await mcp.tools["gateway_work_claim"](project_id="demo")
            )
        claim.assert_awaited_once()
        self.assertFalse(result["claimed"])


def _time(value):
    return datetime.fromisoformat(value)


class StorageAdmissionTests(unittest.TestCase):
    def test_atomic_admission_barrier_rejects_changed_state(self):
        for case in [
            "success",
            "mixed_case",
            "revision",
            "credential",
            "pending",
            "lease",
            "expired",
            "scope",
            "stale",
            "future",
        ]:
            with self.subTest(case=case):
                now = datetime.now(timezone.utc)
                expiry = now + timedelta(minutes=30)
                work = {
                    "work_id": "work-1",
                    "project_id": "demo",
                    "project_path": "team/repo",
                    "claimed_by": "worker",
                    "lease_expires_at": expiry.isoformat(),
                }
                current_work = {
                    **work,
                    "lease_expires_at": expiry,
                    "execution_mode": "factory",
                    "status": "running",
                    "scope_decision": "within_scope",
                }
                project = {
                    "project_id": "demo",
                    "revision": 2,
                    "config": {
                        "project_path": "team/repo",
                        "gitlab_connection_id": "gitlab:private-handle",
                    },
                    "readiness": {
                        "ready": True,
                        "readiness_gaps": [],
                        "connection_version": 3,
                        "checked_at": (now - timedelta(seconds=1)).isoformat(),
                    },
                }
                current = copy.deepcopy(project)
                if case == "mixed_case":
                    current_work["project_id"] = "Demo"
                if case == "revision":
                    current["revision"] = 3
                if case == "lease":
                    current_work["lease_expires_at"] += timedelta(seconds=1)
                if case == "expired":
                    current_work["lease_expires_at"] = now - timedelta(seconds=1)
                if case == "scope":
                    current_work["scope_decision"] = "unresolved"
                if case in {"stale", "future"}:
                    current["readiness"]["checked_at"] = (
                        now + timedelta(seconds=60 if case == "future" else -900)
                    ).isoformat()
                cursor = MagicMock()
                cursor.__enter__.return_value = cursor
                cursor.fetchone.side_effect = [
                    current_work,
                    current,
                    {"pending": True} if case == "pending" else None,
                    {"version": 4 if case == "credential" else 3},
                ]
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.cursor.return_value = cursor
                with (
                    patch.object(storage_factory, "_require_storage"),
                    patch.object(storage_factory, "_connect", return_value=connection),
                ):
                    if case in {"success", "mixed_case"}:
                        result = storage_factory.admit_work_lease(
                            work=work, project=project
                        )
                        self.assertEqual(result["status"], "running")
                        sql, params = cursor.execute.call_args.args
                        self.assertIn("'factory_preflight'", sql)
                        self.assertNotIn("private-handle", params[2])
                        payload = json.loads(params[2])
                        self.assertEqual(payload["project_revision"], 2)
                        self.assertEqual(payload["connection_version"], 3)
                        self.assertEqual(_time(payload["lease_expires_at"]), expiry)
                        connection.commit.assert_called_once()
                    else:
                        with self.assertRaises(
                            (ValueError, storage_factory.ValidationInProgress)
                        ):
                            storage_factory.admit_work_lease(work=work, project=project)
                        connection.commit.assert_not_called()
                        self.assertFalse(
                            any(
                                "insert into work_events" in call.args[0]
                                for call in cursor.execute.call_args_list
                            )
                        )

    def test_block_is_guarded_by_owner_status_and_exact_lease(self):
        for found in [True, False]:
            with self.subTest(found=found):
                cursor = MagicMock()
                cursor.__enter__.return_value = cursor
                cursor.fetchone.return_value = (
                    {"work_id": "work-1", "status": "blocked"} if found else None
                )
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.cursor.return_value = cursor
                work = {
                    "work_id": "work-1",
                    "claimed_by": "worker",
                    "lease_expires_at": "2026-09-17T15:00:00+00:00",
                }
                with (
                    patch.object(storage_work, "_require_postgres"),
                    patch.object(storage_work, "ensure_schema"),
                    patch.object(storage_work, "_connect", return_value=connection),
                ):
                    result = storage_work.block_claim_preflight(
                        work, ["authentication"]
                    )
                sql, params = cursor.execute.call_args_list[0].args
                self.assertIn("status = 'running'", sql)
                self.assertIn("claimed_by = %s", sql)
                self.assertIn("lease_expires_at = %s::timestamptz", sql)
                self.assertEqual(params, tuple(work.values()))
                self.assertEqual(result is not None, found)
                self.assertEqual(cursor.execute.call_count, 2 if found else 1)


if __name__ == "__main__":
    unittest.main()
