import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.access_requests import (
    admin_decide_access_request,
    request_access_package,
)
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.tools.access_requests import register_access_request_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class AccessRequestTests(unittest.TestCase):
    def test_employee_request_uses_email_as_stable_grant_key(self) -> None:
        actor = GatewayActor(
            subject="yandex:42",
            email="Employee@Comind.Space",
            groups=("employees",),
            scopes=("access:request",),
        )
        with patch(
            "gateway_mcp.services.access_requests.insert_access_request",
            return_value={"id": "request-1", "status": "pending"},
        ) as insert:
            result = request_access_package(
                actor=actor,
                package_key="developer",
                reason="Need project repository access",
                ttl_days=90,
                idempotency_key="onboarding-developer",
            )

        self.assertEqual(result["request"]["status"], "pending")
        insert.assert_called_once_with(
            requester_subject="yandex:42",
            requester_email="Employee@Comind.Space",
            subject_key="employee@comind.space",
            package_key="developer",
            package_version=2,
            reason="Need project repository access",
            requested_ttl_days=90,
            idempotency_key="onboarding-developer",
        )

    def test_approval_uses_existing_access_package_service(self) -> None:
        actor = GatewayActor(subject="admin:roman", scopes=("access:admin",))
        request = {
            "id": "request-1",
            "status": "pending",
            "subject_key": "employee@comind.space",
            "package_key": "developer",
            "package_version": 2,
            "requested_ttl_days": 90,
        }
        grant = {"dry_run": False, "bundle": {"id": "bundle-1"}}
        decided = {**request, "status": "approved", "grant_bundle_id": "bundle-1"}
        with (
            patch(
                "gateway_mcp.services.access_requests.get_access_request",
                return_value=request,
            ),
            patch(
                "gateway_mcp.services.access_requests.claim_access_request_decision",
                return_value={**request, "status": "processing"},
            ),
            patch(
                "gateway_mcp.services.access_requests.admin_grant_access_package",
                side_effect=[{"dry_run": True}, grant],
            ) as grant_package,
            patch(
                "gateway_mcp.services.access_requests.decide_access_request",
                return_value=decided,
            ) as decide,
        ):
            result = admin_decide_access_request(
                actor=actor,
                request_id="request-1",
                decision="approved",
                reason="Role confirmed by manager",
                dry_run=False,
            )

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["request"]["status"], "approved")
        self.assertEqual(grant_package.call_count, 2)
        decide.assert_called_once_with(
            request_id="request-1",
            decision="approved",
            decided_by="admin:roman",
            decision_reason="Role confirmed by manager",
            grant_bundle_id="bundle-1",
        )

    def test_rejection_never_creates_grants(self) -> None:
        actor = GatewayActor(subject="admin:roman", scopes=("access:admin",))
        request = {
            "id": "request-1",
            "status": "pending",
            "subject_key": "employee@comind.space",
            "package_key": "developer",
            "package_version": 2,
            "requested_ttl_days": None,
        }
        with (
            patch(
                "gateway_mcp.services.access_requests.get_access_request",
                return_value=request,
            ),
            patch(
                "gateway_mcp.services.access_requests.claim_access_request_decision",
                return_value={**request, "status": "processing"},
            ),
            patch(
                "gateway_mcp.services.access_requests.admin_grant_access_package"
            ) as grant_package,
            patch(
                "gateway_mcp.services.access_requests.decide_access_request",
                return_value={**request, "status": "rejected"},
            ),
        ):
            result = admin_decide_access_request(
                actor=actor,
                request_id="request-1",
                decision="rejected",
                reason="Role does not require repository access",
                dry_run=False,
            )

        self.assertEqual(result["request"]["status"], "rejected")
        grant_package.assert_not_called()

    def test_failed_grant_releases_decision_claim(self) -> None:
        actor = GatewayActor(subject="admin:roman", scopes=("access:admin",))
        request = {
            "id": "request-1",
            "status": "pending",
            "subject_key": "employee@comind.space",
            "package_key": "developer",
            "package_version": 2,
            "requested_ttl_days": 90,
        }
        with (
            patch(
                "gateway_mcp.services.access_requests.get_access_request",
                return_value=request,
            ),
            patch(
                "gateway_mcp.services.access_requests.claim_access_request_decision",
                return_value={**request, "status": "processing"},
            ),
            patch(
                "gateway_mcp.services.access_requests.admin_grant_access_package",
                side_effect=[{"dry_run": True}, RuntimeError("grant failed")],
            ),
            patch(
                "gateway_mcp.services.access_requests.release_access_request_decision"
            ) as release,
            self.assertRaisesRegex(RuntimeError, "grant failed"),
        ):
            admin_decide_access_request(
                actor=actor,
                request_id="request-1",
                decision="approved",
                reason="Role confirmed by manager",
                dry_run=False,
            )

        release.assert_called_once_with(
            request_id="request-1", decided_by="admin:roman"
        )

    def test_public_create_tool_requires_access_request_scope(self) -> None:
        fake = FakeMcp()
        register_access_request_tools(fake)
        run = Mock()
        actor = GatewayActor(subject="yandex:42", scopes=("access:request",))
        run.require_scope.return_value = actor

        with (
            patch("gateway_mcp.tools.access_requests.ToolRun.start", return_value=run),
            patch(
                "gateway_mcp.tools.access_requests.request_access_package",
                return_value={"request": {"id": "request-1", "status": "pending"}},
            ),
        ):
            raw = asyncio.run(
                fake.tools["gateway_access_request_create"](
                    package_key="developer",
                    reason="Project role",
                    idempotency_key="onboarding-developer",
                )
            )

        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        run.require_scope.assert_called_once()


if __name__ == "__main__":
    unittest.main()
