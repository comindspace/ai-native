# Dependency stubs must be installed before importing Gateway modules.
# ruff: noqa: E402
import asyncio
import json
import socket
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import factory_admin as admin
from gateway_mcp.services import factory_readiness as readiness
from gateway_mcp.services import storage_factory
from gateway_mcp.services.factory_projects import (
    discover_factory_projects,
    get_factory_runtime_config,
)
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.work import _safe_metadata, record_event
from gateway_mcp.tools.factory import register_factory_tools

CONFIG = {
    "project_id": "tracker-project-279",
    "project_path": "prompter/sale_service",
    "gitlab_clone_url": "https://customer.example/prompter/sale_service.git",
    "gitlab_web_url": "https://customer.example/prompter/sale_service",
    "default_base_branch": "dev",
    "mr_target_branch": "dev",
    "gitlab_connection_id": "gitlab:customer",
}
CONNECTION = {
    "api_url": "https://customer.example/api/v4",
    "base_url": "https://customer.example",
    "token": "DO-NOT-EXPOSE",
    "username": "oauth2",
    "version": 3,
}
ACTOR = GatewayActor(subject="admin", scopes=("factory:admin", "*"))


def report():
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ready": True,
        "readiness_gaps": [],
        "connection_version": 3,
        "gitlab_project_id": "114",
        "checks": {key: {"status": "pass"} for key in readiness.CHECKS},
    }


def row():
    return {
        "project_id": CONFIG["project_id"],
        "config": {
            **CONFIG,
            "reviewer": "architect",
            "yonote_project_name": "Project context",
        },
        "revision": 2,
        "readiness": report(),
    }


class FactoryAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegated_project_writer_needs_explicit_connection_and_repository_grants(
        self,
    ):
        actor = GatewayActor(subject="writer", scopes=("factory:projects:write",))
        for denied_type in ("connection", "repository"):

            def access(**kwargs):
                return {
                    "decision": "allow",
                    "reason": "no_policy_permissive"
                    if kwargs["resource_type"] == denied_type
                    else "matched_allow",
                }

            with (
                patch.object(admin, "_require_project_access"),
                patch.object(admin, "explain_resource_access", side_effect=access),
                patch.object(storage_factory, "begin_operation") as begin,
                patch.object(admin, "validate_repository", AsyncMock()) as probe,
            ):
                with self.assertRaises(PermissionError):
                    await admin.upsert_project(
                        actor=actor, config=CONFIG, idempotency_key="one"
                    )
            begin.assert_not_called()
            probe.assert_not_awaited()

    async def test_delegated_writer_with_both_explicit_grants_can_register(self):
        actor = GatewayActor(subject="writer", scopes=("factory:projects:write",))
        with (
            patch.object(admin, "_require_project_access"),
            patch.object(
                admin,
                "explain_resource_access",
                return_value={"decision": "allow", "reason": "matched_allow"},
            ) as access,
            patch.object(
                storage_factory, "begin_operation", return_value={"replayed": True}
            ),
        ):
            await admin.upsert_project(
                actor=actor, config=CONFIG, idempotency_key="one"
            )
        self.assertEqual(
            [call.kwargs["resource_type"] for call in access.call_args_list],
            ["connection", "repository"],
        )

    async def test_pending_duplicate_does_not_start_second_external_probe(self):
        with (
            patch.object(
                storage_factory,
                "begin_operation",
                side_effect=RuntimeError("in progress"),
            ),
            patch.object(admin, "validate_repository", AsyncMock()) as probe,
        ):
            with self.assertRaisesRegex(RuntimeError, "in progress"):
                await admin.upsert_project(
                    actor=ACTOR, config=CONFIG, idempotency_key="one"
                )
        probe.assert_not_awaited()

    async def test_cancelled_validation_marks_operation_failed(self):
        with (
            patch.object(storage_factory, "begin_operation", return_value=None),
            patch.object(storage_factory, "get_project", return_value=row()),
            patch.object(
                admin,
                "validate_repository",
                AsyncMock(side_effect=asyncio.CancelledError),
            ),
            patch.object(storage_factory, "fail_operation") as fail,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await admin.upsert_project(
                    actor=ACTOR, config=CONFIG, idempotency_key="one"
                )
        fail.assert_called_once_with(
            ACTOR.subject, "upsert", "one", CONFIG["project_id"]
        )

    async def test_uppercase_project_id_cannot_bypass_read_policy(self):
        with (
            patch(
                "gateway_mcp.services.factory_projects._require_project_access",
                side_effect=PermissionError,
            ) as access,
            patch.object(storage_factory, "get_project") as get,
        ):
            with self.assertRaises(PermissionError):
                await get_factory_runtime_config(
                    actor=ACTOR,
                    tools_registry={},
                    project_id=CONFIG["project_id"].upper(),
                )
        access.assert_called_once_with(ACTOR, "read", CONFIG["project_id"])
        get.assert_not_called()

    async def test_context_gaps_match_runtime_validation_and_work_can_fill_them(self):
        stored = {**row(), "config": dict(CONFIG)}
        work = {
            "work_id": "work-1",
            "project_id": CONFIG["project_id"],
            "contract": {
                "metadata": {"reviewer": "architect", "project_context_ref": "context"}
            },
        }
        with (
            patch.object(storage_factory, "get_project", return_value=stored),
            patch(
                "gateway_mcp.services.storage_service_connections.get_service_connection",
                return_value={"state": "active", "version": 3},
            ),
            patch("gateway_mcp.services.factory_projects.get_work", return_value=work),
        ):
            bare = (
                await get_factory_runtime_config(
                    actor=ACTOR, tools_registry={}, project_id=CONFIG["project_id"]
                )
            )["project"]
            filled = (
                await get_factory_runtime_config(
                    actor=ACTOR, tools_registry={}, work_id="work-1"
                )
            )["project"]
        self.assertEqual(
            set(bare["readiness_gaps"]), {"reviewer", "yonote_project_name"}
        )
        self.assertFalse(bare["ready"])
        self.assertFalse(bare["validation"]["ready"])
        self.assertEqual(bare["readiness_gaps"], bare["validation"]["readiness_gaps"])
        self.assertTrue(filled["ready"])
        self.assertEqual(filled["validation"]["readiness_gaps"], [])

    async def test_validation_pins_configuration_revision_read_before_probe(self):
        snapshot = row()
        with (
            patch.object(storage_factory, "get_project", return_value=snapshot) as get,
            patch.object(storage_factory, "begin_operation", return_value=None),
            patch.object(
                admin, "validate_repository", AsyncMock(return_value=report())
            ),
            patch.object(storage_factory, "save_project", return_value={}) as save,
        ):
            await admin.validate_project(
                actor=ACTOR, project_id=CONFIG["project_id"], idempotency_key="one"
            )
        get.assert_called_once()
        self.assertEqual(
            save.call_args.kwargs["expected_revision"], snapshot["revision"]
        )

    async def test_upsert_denies_normal_factory_writer_before_storage_or_probe(self):
        with patch.object(admin, "validate_repository", AsyncMock()) as probe:
            with self.assertRaises(PermissionError):
                await admin.upsert_project(
                    actor=GatewayActor(subject="u", scopes=("factory:write",)),
                    config=CONFIG,
                    idempotency_key="one",
                )
        probe.assert_not_awaited()

    async def test_upsert_authorized_project_writer_still_checks_resource_access(self):
        actor = GatewayActor(subject="u", scopes=("factory:projects:write",))
        with patch.object(
            admin, "_require_project_access", side_effect=PermissionError
        ) as access:
            with self.assertRaises(PermissionError):
                await admin.upsert_project(
                    actor=actor, config=CONFIG, idempotency_key="one"
                )
        access.assert_called_once_with(actor, "write", CONFIG["project_id"])

    async def test_upsert_replay_performs_no_probe(self):
        with (
            patch.object(
                storage_factory, "begin_operation", return_value={"replayed": True}
            ),
            patch.object(admin, "validate_repository", AsyncMock()) as probe,
        ):
            result = await admin.upsert_project(
                actor=ACTOR, config=CONFIG, idempotency_key="one"
            )
        self.assertTrue(result["replayed"])
        probe.assert_not_awaited()

    async def test_upsert_saves_gaps_and_expected_revision_without_auto_requeue(self):
        failed = {**report(), "ready": False, "readiness_gaps": ["authentication"]}
        with (
            patch.object(storage_factory, "begin_operation", return_value=None),
            patch.object(storage_factory, "get_project", return_value=row()),
            patch.object(admin, "validate_repository", AsyncMock(return_value=failed)),
            patch.object(
                storage_factory, "save_project", return_value={"ready": False}
            ) as save,
            patch.object(storage_factory, "requeue_work") as requeue,
        ):
            await admin.upsert_project(
                actor=ACTOR, config=CONFIG, idempotency_key="one"
            )
        self.assertEqual(save.call_args.kwargs["expected_revision"], 2)
        self.assertEqual(
            save.call_args.kwargs["readiness"]["readiness_gaps"], ["authentication"]
        )
        requeue.assert_not_called()

    async def test_runtime_uses_registered_dev_and_never_default_gitlab(self):
        with (
            patch.object(storage_factory, "get_project", return_value=row()),
            patch(
                "gateway_mcp.services.storage_service_connections.get_service_connection",
                return_value={"state": "active", "version": 3},
            ),
            patch(
                "gateway_mcp.services.factory_projects.call_backend", AsyncMock()
            ) as backend,
        ):
            result = await get_factory_runtime_config(
                actor=ACTOR, tools_registry={}, project_id=CONFIG["project_id"]
            )
        self.assertEqual(result["project"]["default_base_branch"], "dev")
        self.assertEqual(result["project"]["mr_target_branch"], "dev")
        self.assertEqual(
            result["project"]["gitlab_clone_url"], CONFIG["gitlab_clone_url"]
        )
        self.assertEqual(result["project"]["readiness_gaps"], [])
        self.assertNotIn("gitlab:customer", json.dumps(result))
        self.assertNotIn("gitlab_connection_id", json.dumps(result))
        backend.assert_not_awaited()

    async def test_discover_registered_project_first_even_if_backends_unavailable(self):
        with (
            patch.object(storage_factory, "list_projects", return_value=[row()]),
            patch(
                "gateway_mcp.services.storage_service_connections.get_service_connection",
                return_value={"state": "active", "version": 3},
            ),
        ):
            result = await discover_factory_projects(
                actor=ACTOR, tools_registry={}, query="sale_service"
            )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["projects"][0]["project_id"], CONFIG["project_id"])

    async def test_retry_checks_live_readiness_and_passes_revision_to_atomic_transition(
        self,
    ):
        work = {
            "work_id": "work-1",
            "project_id": CONFIG["project_id"].upper(),
            "project_path": CONFIG["project_path"],
            "status": "blocked",
            "execution_mode": "factory",
            "scope_decision": "within_scope",
        }
        with (
            patch.object(admin, "get_work", return_value=work),
            patch.object(storage_factory, "retry_receipt", return_value=False),
            patch.object(storage_factory, "get_project", return_value=row()),
            patch(
                "gateway_mcp.services.factory_projects.get_factory_runtime_config",
                AsyncMock(return_value={"project": {"readiness_gaps": []}}),
            ),
            patch.object(
                admin,
                "_validate_and_save",
                AsyncMock(return_value={"validation": report()}),
            ) as probe,
            patch.object(
                storage_factory, "requeue_work", return_value={"status": "queued"}
            ) as requeue,
        ):
            result = await admin.retry_work(
                actor=ACTOR, work_id="work-1", idempotency_key="one"
            )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(probe.await_count, 1)
        self.assertEqual(requeue.call_args.kwargs["revision"], 2)
        self.assertEqual(requeue.call_args.kwargs["project_id"], CONFIG["project_id"])
        self.assertEqual(requeue.call_args.kwargs["connection_version"], 3)

    async def test_retry_fails_closed_for_context_gap(self):
        work = {
            "project_id": CONFIG["project_id"],
            "status": "blocked",
            "execution_mode": "factory",
            "scope_decision": "within_scope",
        }
        with (
            patch.object(admin, "get_work", return_value=work),
            patch.object(storage_factory, "retry_receipt", return_value=False),
            patch.object(storage_factory, "get_project", return_value=row()),
            patch(
                "gateway_mcp.services.factory_projects.get_factory_runtime_config",
                AsyncMock(return_value={"project": {"readiness_gaps": ["reviewer"]}}),
            ),
            patch.object(
                admin,
                "_validate_and_save",
                AsyncMock(return_value={"validation": report()}),
            ),
            patch.object(storage_factory, "requeue_work") as requeue,
        ):
            result = await admin.retry_work(
                actor=ACTOR, work_id="work-1", idempotency_key="one"
            )
        self.assertEqual(result["readiness_gaps"], ["reviewer"])
        requeue.assert_not_called()

    async def test_retry_replay_never_requeues_newly_blocked_run_again(self):
        with (
            patch.object(
                admin,
                "get_work",
                return_value={"project_id": CONFIG["project_id"], "status": "blocked"},
            ),
            patch.object(storage_factory, "retry_receipt", return_value=True),
            patch.object(admin, "validate_repository", AsyncMock()) as probe,
        ):
            result = await admin.retry_work(
                actor=ACTOR, work_id="work-1", idempotency_key="one"
            )
        self.assertTrue(result["replayed"])
        probe.assert_not_awaited()

    async def test_retry_rejects_running_completed_and_local_work(self):
        for status, mode in (
            ("running", "factory"),
            ("completed", "factory"),
            ("blocked", "local"),
        ):
            with (
                patch.object(
                    admin,
                    "get_work",
                    return_value={
                        "project_id": CONFIG["project_id"],
                        "status": status,
                        "execution_mode": mode,
                        "scope_decision": "within_scope",
                    },
                ),
                patch.object(storage_factory, "retry_receipt", return_value=False),
            ):
                with self.assertRaises(ValueError):
                    await admin.retry_work(
                        actor=ACTOR, work_id="work-1", idempotency_key="one"
                    )

    async def test_new_tools_are_registered_and_audit_omits_handles(self):
        registry = {}

        class MCP:
            def tool(self, **kwargs):
                def register(fn):
                    registry[fn.__name__] = fn
                    return fn

                return register

        register_factory_tools(MCP())
        self.assertTrue(
            {
                "gateway_factory_project_upsert",
                "gateway_factory_project_validate",
                "gateway_work_retry",
            }
            <= set(registry)
        )
        with (
            patch("gateway_mcp.tools.factory.current_actor", return_value=ACTOR),
            patch(
                "gateway_mcp.tools.factory.upsert_project",
                AsyncMock(return_value={"ready": True}),
            ),
            patch("gateway_mcp.tools.factory.ToolRun.start") as start,
        ):
            await registry["gateway_factory_project_upsert"](
                **CONFIG, idempotency_key="one"
            )
        self.assertEqual(
            start.call_args.kwargs["arguments"], {"project_id": CONFIG["project_id"]}
        )


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_waits_for_durable_cleanup(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def deletion(*args, **kwargs):
            started.set()
            await release.wait()
            return True

        with (
            patch.object(readiness, "_git", AsyncMock(side_effect=deletion)),
            patch.object(storage_factory, "finish_probe") as finish,
        ):
            task = asyncio.create_task(
                readiness._protected_cleanup("ref", "head", "repo", {})
            )
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finish.assert_called_once_with("ref", True)

    async def test_failed_cleanup_is_durable_unless_remote_proves_ref_absent(self):
        for code in (0, 2, 128):
            with (
                patch.object(readiness, "_git", AsyncMock(return_value=False)),
                patch.object(readiness, "_git_status", AsyncMock(return_value=code)),
                patch.object(storage_factory, "finish_probe") as finish,
            ):
                result = await readiness._cleanup_probe("ref", "head", "repo", {})
            self.assertEqual(result, code == 2)
            finish.assert_called_once_with("ref", code == 2)

    async def test_push_is_never_attempted_without_persisting_recovery_record(self):
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"a" * 40, None)), returncode=0
        )
        with (
            patch.object(readiness, "_git", AsyncMock(return_value=True)) as git,
            patch.object(
                asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
            ),
            patch.object(
                storage_factory,
                "reserve_probe",
                side_effect=RuntimeError("storage unavailable"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                await readiness._probe_git(CONFIG, CONNECTION, {})
        self.assertEqual(git.await_count, 1)
        self.assertEqual(git.await_args.args[0], "clone")

    async def test_pending_probe_on_changed_remote_blocks_new_push(self):
        with (
            patch.object(readiness, "_git", AsyncMock(return_value=True)) as git,
            patch.object(
                storage_factory,
                "list_probes",
                return_value=[{"remote_url": "https://old.example/repo.git"}],
            ),
        ):
            with self.assertRaisesRegex(
                readiness.ProbeFailure, "previous_probe_requires_operator_cleanup"
            ):
                await readiness._probe_git(CONFIG, CONNECTION, {})
        self.assertEqual(git.await_count, 1)

    async def run_probe(self, responses=None, dns_error=None):
        def response(status, body):
            return SimpleNamespace(status_code=status, json=lambda: body)

        replies = responses or [
            response(200, {}),
            response(200, {"id": 114, "path_with_namespace": CONFIG["project_path"]}),
            response(200, {"name": "dev"}),
        ]

        async def git(config, connection, checks):
            for key in ("clone", "push_permissions", "cleanup"):
                checks[key] = {"status": "pass", "code": "test"}

        with (
            patch.object(readiness, "connection_settings", return_value=CONNECTION),
            patch.object(readiness, "_resolve", AsyncMock(side_effect=dns_error)),
            patch.object(readiness, "_get", AsyncMock(side_effect=replies)) as get,
            patch.object(readiness, "_probe_git", AsyncMock(side_effect=git)),
        ):
            result = await readiness.validate_repository(CONFIG)
        self.assertNotIn(CONNECTION["token"], json.dumps(result))
        self.assertNotIn(CONFIG["gitlab_connection_id"], json.dumps(result))
        return result, get

    async def test_full_readiness_targets_customer_instance(self):
        result, get = await self.run_probe()
        self.assertTrue(result["ready"])
        self.assertFalse(result["worker_environment_verified"])
        self.assertEqual(result["readiness_gaps"], [])
        self.assertTrue(
            all(
                call.args[1].startswith(CONNECTION["api_url"])
                for call in get.await_args_list
            )
        )

    async def test_dns_failure_is_not_ready_and_no_http(self):
        result, get = await self.run_probe(dns_error=socket.gaierror("private details"))
        self.assertEqual(result["checks"]["dns"]["code"], "dns_failed")
        self.assertFalse(result["ready"])
        get.assert_not_awaited()

    async def test_missing_branch_and_auth_have_distinct_gaps(self):
        ok = SimpleNamespace(
            status_code=200,
            json=lambda: {"id": 114, "path_with_namespace": CONFIG["project_path"]},
        )
        for responses, expected in (
            ([readiness.ProbeFailure("authentication", "denied")], "authentication"),
            ([ok, ok, SimpleNamespace(status_code=404)], "branch"),
        ):
            result, _ = await self.run_probe(responses=responses)
            self.assertEqual(result["checks"][expected]["status"], "fail")

    async def test_wrong_host_never_receives_credentials(self):
        with (
            patch.object(
                readiness,
                "connection_settings",
                return_value={**CONNECTION, "base_url": "https://different.example"},
            ),
            patch.object(readiness, "_resolve", AsyncMock()) as dns,
        ):
            result = await readiness.validate_repository(CONFIG)
        self.assertFalse(result["ready"])
        dns.assert_not_awaited()

    async def test_redirect_rejected(self):
        client = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(status_code=302))
        )
        with self.assertRaises(readiness.ProbeFailure):
            await readiness._get(client, "https://customer.example/api/v4/user")

    async def test_push_probe_uses_unique_branch_and_cas_cleanup(self):
        calls = []

        async def git(*args, **kwargs):
            calls.append((args, kwargs))
            return True

        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"a" * 40 + b"\n", None)), returncode=0
        )
        checks = {}
        with (
            patch.object(readiness, "_git", AsyncMock(side_effect=git)),
            patch.object(storage_factory, "reserve_probe") as reserve,
            patch.object(storage_factory, "finish_probe") as finish,
            patch.object(
                asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
            ),
        ):
            await readiness._probe_git(CONFIG, CONNECTION, checks)
        self.assertEqual(checks["push_permissions"]["status"], "pass")
        self.assertEqual(checks["cleanup"]["status"], "pass")
        self.assertIn("ci.skip", calls[1][0])
        self.assertTrue(
            any(
                arg.startswith("--force-with-lease=refs/heads/codex/readiness-")
                for arg in calls[2][0]
            )
        )
        self.assertNotIn(CONNECTION["token"], str([args for args, _ in calls]))
        reserve.assert_called_once()
        finish.assert_called_once_with(reserve.call_args.args[2], True)


class FactorySecurityTests(unittest.TestCase):
    def test_project_admin_permission_normalizes_project_id(self):
        actor = GatewayActor(subject="writer", scopes=("factory:projects:write",))
        with patch.object(admin, "_require_project_access") as access:
            admin.require_project_admin(actor, CONFIG["project_id"].upper())
        access.assert_called_once_with(actor, "write", CONFIG["project_id"])

    def test_unfinished_probe_invalidates_previous_ready_report(self):
        with (
            patch.object(
                storage_factory, "list_probes", return_value=[{"ref": "pending"}]
            ),
            patch(
                "gateway_mcp.services.storage_service_connections.get_service_connection",
                return_value={"state": "active", "version": 3},
            ),
        ):
            result = admin.public_project(row())
        self.assertEqual(result["readiness_gaps"], ["cleanup"])
        self.assertFalse(result["validation"]["ready"])

    def test_expired_report_and_revoked_connection_are_gaps(self):
        stored = row()
        stored["readiness"]["checked_at"] = "2020-01-01T00:00:00+00:00"
        with patch(
            "gateway_mcp.services.storage_service_connections.get_service_connection",
            return_value={"state": "disabled", "version": 3},
        ):
            result = admin.public_project(stored)
        self.assertIn("validation_stale", result["readiness_gaps"])
        self.assertIn("authentication", result["readiness_gaps"])

    def test_audit_redacts_credentials_recursively(self):
        from gateway_mcp.services.observability import _redact

        result = _redact(
            {
                "config": {
                    "gitlab_connection_id": "gitlab:hidden",
                    "token": "secret-value",
                }
            }
        )
        self.assertNotIn("hidden", json.dumps(result))
        self.assertNotIn("secret-value", json.dumps(result))

    def test_urls_and_branch_inputs_fail_closed(self):
        for url in (
            "http://customer.example/repo",
            "https://token@customer.example/repo",
            "https://customer.example/repo?token=secret",
            "https://customer.example/%2e%2e/repo",
            "https://customer.example/../repo",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                admin.normalize_project({**CONFIG, "gitlab_clone_url": url})
        for branch in (
            "--upload-pack=bad",
            "dev..prod",
            "dev;run",
            "../dev",
            "refs/a.lock",
        ):
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                admin.normalize_project({**CONFIG, "default_base_branch": branch})

    def test_runtime_drops_handles_and_invalidates_rotated_connection(self):
        with patch(
            "gateway_mcp.services.storage_service_connections.get_service_connection",
            return_value={"state": "active", "version": 4},
        ):
            result = admin.public_project(row())
        self.assertIn("authentication", result["readiness_gaps"])
        self.assertNotIn(CONFIG["gitlab_connection_id"], json.dumps(result))

    def test_work_metadata_redacts_nested_handles(self):
        result = _safe_metadata(
            {
                "connection_id": "gitlab:hidden",
                "nested": {"credential_handle": "hidden"},
                "items": [[{"gitlab_token": "hidden"}]],
            }
        )
        self.assertNotIn("hidden", json.dumps(result))

    def test_registered_work_cannot_bypass_retry_via_resumed(self):
        with (
            patch(
                "gateway_mcp.services.work.get_work",
                return_value={"project_id": "demo", "execution_mode": "factory"},
            ),
            patch("gateway_mcp.services.work._require_project_access"),
            patch.object(storage_factory, "get_project", return_value=row()),
        ):
            with self.assertRaisesRegex(ValueError, "gateway_work_retry"):
                record_event(
                    actor=ACTOR, work_id="work-1", event_type="resumed", payload={}
                )

    def test_git_environment_disables_credentials_helpers_and_redirects(self):
        env = readiness._git_env(CONNECTION)
        settings = {
            env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        }
        self.assertEqual(settings["http.followRedirects"], "false")
        self.assertEqual(settings["credential.helper"], "")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")


class StorageFactoryTests(unittest.TestCase):
    def test_pending_receipt_and_project_reservation_reject_concurrent_probes(self):
        for receipt in (
            None,
            {"fingerprint": "same", "status": "running", "result": {}},
        ):
            conn, cur = self.database([None, receipt])
            with (
                patch.object(storage_factory, "_require_storage"),
                patch.object(storage_factory, "_connect", return_value=conn),
            ):
                with self.assertRaisesRegex(RuntimeError, "in progress"):
                    storage_factory.begin_operation(
                        "a", "upsert", "one", "same", "project"
                    )

    def test_reservation_is_committed_before_probe(self):
        conn, cur = self.database([{"idempotency_key": "one"}])
        with (
            patch.object(storage_factory, "_require_storage"),
            patch.object(storage_factory, "_connect", return_value=conn),
        ):
            result = storage_factory.begin_operation(
                "a", "upsert", "one", "same", "project"
            )
        self.assertIsNone(result)
        conn.commit.assert_called_once()
        self.assertIn("on conflict do nothing", cur.execute.call_args.args[0])

    def test_unchanged_configuration_preserves_revision_and_stores_safe_receipt(self):
        conn, cur = self.database([None, row()])
        with (
            patch.object(storage_factory, "_require_storage"),
            patch.object(storage_factory, "_connect", return_value=conn),
        ):
            result = storage_factory.save_project(
                config=row()["config"],
                readiness=report(),
                actor="a",
                operation="validate",
                key="one",
                fingerprint="hash",
                expected_revision=2,
            )
        self.assertFalse(result["changed"])
        self.assertEqual(result["revision"], 2)
        self.assertNotIn(CONFIG["gitlab_connection_id"], json.dumps(result))
        audit_params = cur.execute.call_args.args[1]
        self.assertNotIn(CONFIG["gitlab_connection_id"], json.dumps(audit_params))
        conn.commit.assert_called_once()

    def database(self, rows):
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchone.side_effect = rows
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = cur
        return conn, cur

    def test_requeue_atomically_checks_revision_connection_and_clears_lease(self):
        work = {
            "status": "blocked",
            "execution_mode": "factory",
            "project_id": CONFIG["project_id"].upper(),
            "scope_decision": "within_scope",
        }
        conn, cur = self.database([work, None, row(), None, {"version": 3}])
        with (
            patch.object(storage_factory, "_require_storage"),
            patch.object(storage_factory, "_connect", return_value=conn),
        ):
            result = storage_factory.requeue_work(
                work_id="work-1",
                actor="a",
                key="one",
                project_id=CONFIG["project_id"],
                revision=2,
                connection_id=CONFIG["gitlab_connection_id"],
                connection_version=3,
            )
        self.assertEqual(result["status"], "queued")
        sql = " ".join(call.args[0] for call in cur.execute.call_args_list)
        self.assertIn("for update", sql)
        self.assertIn("for share", sql)
        self.assertIn("lease_expires_at = null", sql)
        self.assertNotIn("correction_rounds =", sql)
        event_args = cur.execute.call_args.args[1]
        self.assertNotIn(CONFIG["gitlab_connection_id"], json.dumps(event_args))
        conn.commit.assert_called_once()

    def test_retry_receipt_cannot_bypass_new_pending_probe_or_validation(self):
        work = {
            "status": "blocked",
            "execution_mode": "factory",
            "project_id": CONFIG["project_id"],
            "scope_decision": "within_scope",
        }
        conn, cur = self.database([work, None, row(), {"pending": 1}])
        with (
            patch.object(storage_factory, "_require_storage"),
            patch.object(storage_factory, "_connect", return_value=conn),
        ):
            with self.assertRaisesRegex(ValueError, "probe cleanup is pending"):
                storage_factory.requeue_work(
                    work_id="work-1",
                    actor="a",
                    key="one",
                    project_id=CONFIG["project_id"],
                    revision=2,
                    connection_id=CONFIG["gitlab_connection_id"],
                    connection_version=3,
                )
        conn.commit.assert_not_called()
        sql = " ".join(call.args[0] for call in cur.execute.call_args_list)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("factory_project_operations", sql)
        self.assertIn("factory_git_probes", sql)
        self.assertNotIn("update work_runs", sql)

    def test_retry_receipt_cannot_bypass_later_failed_or_stale_readiness(self):
        work = {
            "status": "blocked",
            "execution_mode": "factory",
            "project_id": CONFIG["project_id"],
            "scope_decision": "within_scope",
        }
        for current in (
            {**report(), "ready": False, "readiness_gaps": ["clone"]},
            {**report(), "checked_at": "2020-01-01T00:00:00+00:00"},
        ):
            conn, cur = self.database([work, None, {**row(), "readiness": current}])
            with (
                patch.object(storage_factory, "_require_storage"),
                patch.object(storage_factory, "_connect", return_value=conn),
            ):
                with self.assertRaisesRegex(ValueError, "current project readiness"):
                    storage_factory.requeue_work(
                        work_id="work-1",
                        actor="a",
                        key="one",
                        project_id=CONFIG["project_id"],
                        revision=2,
                        connection_id=CONFIG["gitlab_connection_id"],
                        connection_version=3,
                    )
            conn.commit.assert_not_called()

    def test_changed_revision_aborts_before_requeue(self):
        work = {
            "status": "blocked",
            "execution_mode": "factory",
            "project_id": CONFIG["project_id"],
            "scope_decision": "within_scope",
        }
        conn, cur = self.database([work, None, {**row(), "revision": 4}])
        with (
            patch.object(storage_factory, "_require_storage"),
            patch.object(storage_factory, "_connect", return_value=conn),
        ):
            with self.assertRaisesRegex(ValueError, "project changed"):
                storage_factory.requeue_work(
                    work_id="work-1",
                    actor="a",
                    key="one",
                    project_id=CONFIG["project_id"],
                    revision=2,
                    connection_id=CONFIG["gitlab_connection_id"],
                    connection_version=3,
                )
        conn.commit.assert_not_called()

    def test_receipt_key_payload_conflict_is_rejected(self):
        conn, cur = self.database([{"fingerprint": "old", "result": {}}])
        with (
            patch.object(storage_factory, "_require_storage"),
            patch.object(storage_factory, "_connect", return_value=conn),
        ):
            with self.assertRaisesRegex(ValueError, "different request"):
                storage_factory.operation_result("a", "upsert", "one", "new")


if __name__ == "__main__":
    unittest.main()
