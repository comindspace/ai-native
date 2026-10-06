import asyncio
import copy
import re
import unittest
from contextlib import ExitStack
from html import unescape
from unittest.mock import patch
from urllib.parse import urlencode

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.routes import admin_access as ui
from gateway_mcp.services.policy import GatewayActor

RID = "e4614552-e8a7-4c30-84de-1c16bb0066da"
ROW = {
    "id": RID,
    "requester_subject": "yandex:42",
    "requester_email": "employee@example.test",
    "subject_key": "employee@example.test",
    "package_key": "developer",
    "package_version": 2,
    "status": "pending",
    "requested_ttl_days": 90,
    "reason": "Project work",
    "created_at": "2026-09-16T09:00:00+00:00",
    "updated_at": "2026-09-16T09:00:00+00:00",
}
ADMIN = GatewayActor(
    subject="admin:1", email="admin@example.test", scopes=("access:admin",)
)


class FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, **kwargs):
        def register(func):
            self.routes[path] = func
            return func

        return register


class Request:
    def __init__(self, *, query=None, form=None, csrf="csrf-value", path=None):
        self.query_params = query or {}
        self.path_params = path or {"request_id": RID}
        self.cookies = {ui.CSRF_COOKIE: csrf}
        self.headers = {}
        self.form = form or {}

    async def body(self):
        return urlencode(self.form).encode()


def body(response):
    return response.body.decode() if isinstance(response.body, bytes) else response.body


def hidden(response):
    return {
        k: unescape(v)
        for k, v in re.findall(
            r'type="hidden" name="([^"]+)" value="([^"]*)"', body(response)
        )
    }


class AdminAccessTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mcp = FakeMcp()
        ui.register_admin_access_routes(self.mcp)
        self.actor = self.stack.enter_context(
            patch.object(ui, "web_actor", return_value=ADMIN)
        )
        self.row = copy.deepcopy(ROW)
        self.stack.enter_context(
            patch.object(ui, "get_access_request", side_effect=lambda _: self.row)
        )
        self.stack.enter_context(
            patch(
                "gateway_mcp.services.access_requests.get_access_request",
                side_effect=lambda _: self.row,
            )
        )
        self.claim = self.stack.enter_context(
            patch(
                "gateway_mcp.services.access_requests.claim_access_request_decision",
                return_value={**ROW, "status": "processing"},
            )
        )
        self.decide = self.stack.enter_context(
            patch(
                "gateway_mcp.services.access_requests.decide_access_request",
                return_value={**ROW, "status": "approved"},
            )
        )
        self.insert = self.stack.enter_context(
            patch(
                "gateway_mcp.services.access_admin.insert_access_bundle",
                return_value={"bundle": {"id": "bundle-1"}},
            )
        )
        self.audit = self.stack.enter_context(patch.object(ui, "audit_event"))
        self.cookies = self.stack.enter_context(
            patch.object(ui.HTMLResponse, "set_cookie", create=True)
        )
        self.stack.enter_context(
            patch.object(ui, "jwt_secret", return_value="unit-test-key")
        )

    def call(self, path, request=None):
        return asyncio.run(self.mcp.routes[path](request or Request()))

    def preview(self, decision="approved"):
        return self.call(
            "/admin/access-requests/{request_id}/preview",
            Request(
                form={
                    "csrf": "csrf-value",
                    "decision": decision,
                    "reason": "Role confirmed",
                }
            ),
        )

    def confirm(self, fields):
        return self.call(
            "/admin/access-requests/{request_id}/confirm",
            Request(form={**fields, "confirmed": "yes"}),
        )

    def test_all_routes_require_admin(self):
        self.actor.return_value = GatewayActor(
            subject="employee", scopes=("access:read",)
        )
        for path in self.mcp.routes:
            with self.subTest(path=path):
                self.assertEqual(self.call(path).status_code, 403)
        self.insert.assert_not_called()

    def test_unauthenticated_redirect(self):
        self.actor.return_value = None
        self.assertEqual(self.call("/admin").status_code, 303)

    def test_detail_escapes_content_and_has_csrf(self):
        self.row["reason"] = '<script>alert("bad")</script>'
        response = self.call("/admin/access-requests/{request_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;script&gt;", body(response))
        self.assertNotIn("<script>alert", body(response))
        self.assertIn("gitlab:write", body(response))
        self.assertIn('name="csrf"', body(response))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_preview_does_not_grant(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Подтвердить выдачу", body(response))
        self.assertIn("90 дней", body(response))
        self.assertIn("gitlab:write", body(response))
        self.insert.assert_not_called()
        self.claim.assert_not_called()

    def test_confirmation_uses_existing_service(self):
        response = self.confirm(hidden(self.preview()))
        self.assertEqual(response.status_code, 303)
        self.insert.assert_called_once()
        self.assertEqual(
            self.insert.call_args.kwargs["subject_key"], ROW["subject_key"]
        )
        self.assertEqual(self.insert.call_args.kwargs["ttl_days"], 90)
        self.decide.assert_called_once()
        self.assertEqual(
            self.audit.call_args.kwargs["event"], "admin_access_request_decided"
        )

    def test_rejection_creates_no_grants(self):
        response = self.confirm(hidden(self.preview("rejected")))
        self.assertEqual(response.status_code, 303)
        self.insert.assert_not_called()
        self.assertEqual(self.decide.call_args.kwargs["decision"], "rejected")

    def test_missing_csrf_blocks_preview(self):
        response = self.call(
            "/admin/access-requests/{request_id}/preview",
            Request(form={"decision": "approved", "reason": "x"}),
        )
        self.assertEqual(response.status_code, 403)
        self.claim.assert_not_called()

    def test_missing_preview_blocks_confirm(self):
        response = self.confirm(
            {"csrf": "csrf-value", "decision": "approved", "reason": "x"}
        )
        self.assertEqual(response.status_code, 409)
        self.claim.assert_not_called()

    def test_preview_bound_to_actor_reason_decision_csrf(self):
        fields = hidden(self.preview())
        for key, value in (
            ("reason", "Other reason"),
            ("decision", "rejected"),
            ("confirmation", "invalid"),
        ):
            with self.subTest(key=key):
                self.assertEqual(self.confirm({**fields, key: value}).status_code, 409)
        self.actor.return_value = GatewayActor(
            subject="admin:2", scopes=("access:admin",)
        )
        self.assertEqual(self.confirm(fields).status_code, 409)
        self.claim.assert_not_called()

    def test_preview_expires(self):
        with patch.object(ui.time, "time", return_value=1000):
            fields = hidden(self.preview())
        with patch.object(ui.time, "time", return_value=1601):
            self.assertEqual(self.confirm(fields).status_code, 409)
        self.claim.assert_not_called()

    def test_modified_request_invalidates_preview(self):
        fields = hidden(self.preview())
        self.row["requested_ttl_days"] = 365
        self.assertEqual(self.confirm(fields).status_code, 409)
        self.claim.assert_not_called()

    def test_already_decided_request_cannot_be_replayed(self):
        fields = hidden(self.preview())
        self.row["status"] = "approved"
        self.assertEqual(self.confirm(fields).status_code, 409)
        self.claim.assert_not_called()

    def test_package_change_requires_new_request(self):
        fields = hidden(self.preview())
        self.row["package_version"] = 1
        response = self.call("/admin/access-requests/{request_id}")
        self.assertIn("Пакет изменился", body(response))
        self.assertEqual(self.confirm(fields).status_code, 409)
        self.claim.assert_not_called()

    def test_self_approval_denied_by_subject_and_email(self):
        for actor in (
            GatewayActor(subject="yandex:42", scopes=("access:admin",)),
            GatewayActor(
                subject="other", email="EMPLOYEE@example.test", scopes=("access:admin",)
            ),
        ):
            self.actor.return_value = actor
            self.assertEqual(self.preview().status_code, 403)
        self.claim.assert_not_called()

    def test_backend_error_never_leaks_details(self):
        with patch.object(
            ui, "list_access_requests", side_effect=RuntimeError("token=private-secret")
        ):
            response = self.call("/admin/access-requests")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-secret", body(response))
        self.assertEqual(self.audit.call_args.kwargs["error"], "RuntimeError")

    def test_request_pagination_and_filters(self):
        with patch.object(ui, "list_access_requests", return_value=[ROW] * 26) as read:
            response = self.call(
                "/admin/access-requests",
                Request(query={"offset": "25", "status": "", "q": "someone"}),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("offset=50", body(response))
        self.assertIn("Страница 2", body(response))
        self.assertEqual(
            body(response).count(f'<a href="/admin/access-requests/{RID}">'), 25
        )
        self.assertEqual(read.call_args.kwargs["offset"], 25)

    def test_user_card_shows_expired_and_revoked_grants(self):
        with (
            patch.object(
                ui,
                "admin_role_state",
                return_value={"is_admin": False, "denied": False, "grants": []},
            ),
            patch.object(
                ui,
                "admin_user_get",
                return_value={"subject": "u", "email": "e", "login": "l"},
            ),
            patch.object(
                ui,
                "admin_user_grants",
                return_value={
                    "packages": [
                        {"title": "Old", "expires_at": "2020-01-01T00:00:00+00:00"}
                    ],
                    "scopes": [
                        {
                            "scope": "gitlab:write",
                            "effect": "allow",
                            "revoked_at": "2026-09-01",
                        }
                    ],
                    "resources": [],
                },
            ),
            patch.object(ui, "list_access_requests", return_value=[]),
        ):
            response = self.call("/admin/users/detail", Request(query={"subject": "u"}))
        self.assertIn("Истекло", body(response))
        self.assertIn("Отозвано", body(response))
        self.assertIn("Прямые назначения", body(response))
        self.assertIn("Назначить администратором", body(response))
        self.assertIn("/admin/users/role/preview", body(response))
        self.cookies.assert_called_once()

    def test_service_denies_unprivileged_and_self_decisions(self):
        for actor in (
            GatewayActor(subject="u"),
            GatewayActor(subject=ROW["requester_subject"], scopes=("access:admin",)),
        ):
            with self.assertRaises(PermissionError):
                ui.admin_decide_access_request(
                    actor=actor,
                    request_id=RID,
                    decision="approved",
                    reason="x",
                    dry_run=False,
                )
        self.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
