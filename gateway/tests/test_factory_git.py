import asyncio
import base64
import unittest
from datetime import datetime, timedelta, timezone
from typing import ClassVar
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import factory_git as service
from gateway_mcp.services import storage_work
from gateway_mcp.services.policy import GatewayActor

ID = "work-11111111-1111-1111-1111-111111111111"
BRANCH = "codex/" + ID
ACTOR = GatewayActor(subject="worker", scopes=("factory:git", "factory:claim"))


def packet(value):
    return f"{len(value) + 4:04x}".encode() + value


def push(
    ref=None,
    old=b"0" * 40,
    new=b"1" * 40,
    caps=b"report-status side-band-64k agent=git/2.50.0",
):
    return (
        packet(
            old
            + b" "
            + new
            + b" "
            + (ref or "refs/heads/" + BRANCH).encode()
            + b"\x00"
            + caps
            + b"\n"
        )
        + b"0000"
    )


def work():
    return {
        "work_id": ID,
        "project_id": "p",
        "project_path": "team/repo",
        "status": "running",
        "execution_mode": "factory",
        "scope_decision": "within_scope",
        "claimed_by": "worker",
        "lease_expires_at": (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat(),
        "contract": {"metadata": {"gitlab_backend": "https://git.example"}},
    }


def row():
    return {
        "revision": 2,
        "config": {
            "gitlab_connection_id": "gitlab:test",
            "project_path": "team/repo",
            "gitlab_clone_url": "https://git.example/team/repo.git",
            "gitlab_web_url": "https://git.example/team/repo",
            "default_base_branch": "main",
            "mr_target_branch": "main",
        },
        "readiness": {
            "ready": True,
            "connection_version": 2,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    }


class FactoryGitTests(unittest.TestCase):
    def test_valid_push(self):
        service.validate_push(push(), BRANCH)
        service.validate_push(push() + b"PACKtest", BRANCH)
        service.validate_push(
            packet(b"shallow " + b"2" * 40 + b"\n") + push(caps=b" report-status"),
            BRANCH,
        )

    def test_other_ref_delete_and_push_options_denied(self):
        for body in [
            push("refs/heads/main"),
            push("refs/tags/v1"),
            push(new=b"0" * 40),
            push(caps=b"push-options"),
            push(caps=b"push-cert"),
            push(caps=b"report-status\x00push-options"),
            push() + b"0005x",
            b"0000",
        ]:
            with (
                self.subTest(body=body),
                self.assertRaises((PermissionError, ValueError)),
            ):
                service.validate_push(body, BRANCH)

    def test_multiple_updates_and_malformed_packets(self):
        duplicate = push()[:-4] + push()
        for body in [
            duplicate,
            b"ffffshort",
            b"0001",
            b"zzzz",
            b"0008abc",
            b"0004",
            b"",
            b"0000PACK",
        ]:
            with (
                self.subTest(body=body),
                self.assertRaises((PermissionError, ValueError)),
            ):
                service.validate_push(body, BRANCH)

    def authorize(
        self, candidate=None, stored=None, actor=ACTOR, version=2, admission=None
    ):
        candidate = candidate or work()
        stored = stored or row()
        with (
            patch.object(service, "enabled", return_value=True),
            patch.object(service, "get_work", return_value=candidate),
            patch.object(service, "_require_project_access"),
            patch.object(
                service.storage_factory, "get_project", return_value=stored
            ),
            patch.object(service.storage_factory, "list_probes", return_value=[]),
            patch.object(
                storage_work,
                "latest_factory_preflight",
                return_value=admission
                or {
                    "actor_subject": "worker",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "lease_expires_at": candidate["lease_expires_at"],
                        "ready": True,
                        "project_revision": stored["revision"],
                        "connection_version": stored["readiness"]["connection_version"],
                        "checked_at": stored["readiness"].get("checked_at"),
                    },
                },
            ),
            patch.object(
                service,
                "connection_settings",
                return_value={"base_url": "https://git.example", "version": version},
            ),
            patch.object(service, "check_destination"),
        ):
            return service.authorize_git(actor, ID)

    def test_active_owned_lease(self):
        self.assertEqual(self.authorize()[3], BRANCH)

    def test_stale_admission_rejected_but_valid_long_lease_continues(self):
        now = datetime.now(timezone.utc)
        stored = row()
        stored["readiness"]["checked_at"] = (now - timedelta(minutes=20)).isoformat()
        with self.assertRaises(PermissionError):
            self.authorize(stored=stored)
        admission = {
            "actor_subject": "worker",
            "occurred_at": (now - timedelta(minutes=19)).isoformat(),
        }
        candidate = work()
        admission["payload"] = {
            "lease_expires_at": candidate["lease_expires_at"],
            "ready": True,
            "project_revision": 2,
            "connection_version": 2,
            "checked_at": stored["readiness"]["checked_at"],
        }
        self.assertEqual(
            self.authorize(candidate, stored=stored, admission=admission)[3], BRANCH
        )
        stored["readiness"].pop("checked_at")
        with self.assertRaises(PermissionError):
            self.authorize(stored=stored)

    def test_same_worker_previous_lease_or_legacy_event_denied(self):
        for payload in [
            {},
            {
                "lease_expires_at": (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat()
            },
        ]:
            with self.subTest(payload=payload), self.assertRaises(PermissionError):
                self.authorize(
                    admission={
                        "actor_subject": "worker",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "payload": payload,
                    }
                )

    def test_claim_alone_and_old_project_revision_cannot_authorize_git(self):
        candidate, stored = work(), row()
        payload = {
            "ready": True,
            "lease_expires_at": candidate["lease_expires_at"],
            "project_revision": 2,
            "connection_version": 2,
            "checked_at": stored["readiness"]["checked_at"],
        }
        stored["revision"] = 3
        for admission in [
            {"actor_subject": "worker", "payload": {}},
            {
                "actor_subject": "worker",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            },
        ]:
            with self.subTest(admission=admission), self.assertRaises(PermissionError):
                self.authorize(candidate, stored=stored, admission=admission)

    def test_wrong_owner_status_expired_lease_and_mode_denied(self):
        for field, value in [
            ("claimed_by", "other"),
            ("status", "completed"),
            ("execution_mode", "local"),
            ("scope_decision", "unresolved"),
            ("lease_expires_at", None),
            (
                "lease_expires_at",
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            ),
        ]:
            candidate = {**work(), field: value}
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(PermissionError),
            ):
                self.authorize(candidate)

    def test_repo_identity_and_rotated_connection_denied(self):
        for candidate in [
            {**work(), "project_path": "other/repo"},
            {**work(), "contract": {"metadata": {}}},
        ]:
            with self.assertRaises(PermissionError):
                self.authorize(candidate)
        with self.assertRaises(PermissionError):
            self.authorize(version=3)

    def test_base_branch_never_writable(self):
        stored = row()
        stored["config"]["mr_target_branch"] = BRANCH
        with self.assertRaises(PermissionError):
            self.authorize(stored=stored)

    def test_scope_and_disabled_transport(self):
        for scopes in [("factory:claim",), ("factory:git",), ()]:
            with self.assertRaises(PermissionError):
                self.authorize(actor=GatewayActor(subject="worker", scopes=scopes))
        with (
            patch.object(service, "enabled", return_value=False),
            self.assertRaises(PermissionError),
        ):
            service.authorize_git(ACTOR, ID)

    def test_public_transport_contains_no_upstream_credentials(self):
        with (
            patch.object(
                service,
                "authorize_git",
                return_value=(
                    work(),
                    row()["config"],
                    {"token": "secret", "connection_id": "gitlab:test"},
                    BRANCH,
                ),
            ),
            patch.object(service, "public_url", return_value="https://gateway.example"),
        ):
            result = service.transport_config(ACTOR, ID)
            self.assertNotIn("gitlab:test", str(result))
            self.assertNotIn("secret", str(result))
            self.assertIn(ID, result["clone_url"])

    def test_git_auth_ignores_browser_cookie(self):
        from gateway_mcp.routes.factory_git import request_actor

        class Request:
            headers: ClassVar = {}
            cookies: ClassVar = {"gateway_token": "cookie"}

        self.assertIsNone(request_actor(Request()))

    def test_git_basic_uses_gateway_verifier(self):
        from gateway_mcp.routes import factory_git as route

        class Request:
            headers: ClassVar = {
                "authorization": "Basic "
                + base64.b64encode(b"factory:gateway-test-token").decode()
            }

        with (
            patch.object(
                route, "verify_gateway_token_claims", return_value={}
            ) as verify,
            patch.object(route, "actor_from_claims", return_value=ACTOR),
        ):
            self.assertEqual(route.request_actor(Request()), ACTOR)
            verify.assert_called_once_with("gateway-test-token")

    def test_forbidden_push_never_reaches_upstream(self):
        from gateway_mcp.routes import factory_git as route

        class Request:
            headers: ClassVar = {}

            async def stream(self):
                yield push("refs/heads/main")

        with (
            patch.object(
                route,
                "authorize_git",
                return_value=(work(), row()["config"], {}, BRANCH),
            ),
            patch.object(route.httpx, "AsyncClient") as client,
        ):
            with self.assertRaises(PermissionError):
                asyncio.run(
                    route.forward_git(Request(), ACTOR, ID, "git-receive-pack", False)
                )
            client.assert_not_called()
