import asyncio
import unittest
from contextlib import ExitStack, nullcontext
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from test_admin_access import ADMIN, FakeMcp, Request, body, hidden

from gateway_mcp.routes import admin_access as ui
from gateway_mcp.routes import admin_user_roles as roles
from gateway_mcp.services import admin_roles as service
from gateway_mcp.services.policy import GatewayActor

USER = {
    "subject": "yandex:42",
    "email": "staff@example.test",
    "login": "staff",
    "yandex_id": "42",
    "updated_at": "2026-09-29T10:00:00",
}


class AdminRoleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mcp = FakeMcp()
        roles.register_admin_user_role_routes(self.mcp)
        self.actor = self.stack.enter_context(
            patch.object(ui, "web_actor", return_value=ADMIN)
        )
        self.user = self.stack.enter_context(
            patch.object(roles, "admin_user_get", return_value=dict(USER))
        )
        self.state = self.stack.enter_context(
            patch.object(
                roles,
                "admin_role_state",
                return_value={"is_admin": False, "denied": False, "grants": []},
            )
        )
        self.insert = self.stack.enter_context(
            patch(
                "gateway_mcp.services.access_admin.insert_scope_grant",
                return_value={"id": 999},
            )
        )
        self.stack.enter_context(
            patch.object(roles, "jwt_secret", return_value="test-key")
        )
        self.audit = self.stack.enter_context(patch.object(roles, "audit_event"))
        self.current = self.stack.enter_context(
            patch.object(roles, "require_current_admin")
        )
        self.stack.enter_context(patch.object(service, "require_current_admin"))
        self.stack.enter_context(
            patch.object(
                service, "admin_user_get", side_effect=lambda key: self.user(key)
            )
        )
        self.stack.enter_context(
            patch.object(
                service, "admin_role_state", side_effect=lambda user: self.state(user)
            )
        )
        self.stack.enter_context(
            patch.object(
                service,
                "admin_role_assignment_lock",
                side_effect=lambda key: nullcontext(),
            )
        )
        self.claim = self.stack.enter_context(
            patch.object(roles, "claim_idempotency", return_value={"claimed": True})
        )
        self.complete = self.stack.enter_context(
            patch.object(roles, "complete_idempotency")
        )
        self.stack.enter_context(patch.object(ui, "audit_event"))

    def call(self, route, form=None, **kwargs):
        return asyncio.run(
            self.mcp.routes["/admin/users/role/" + route](
                Request(form=form or self.form(), **kwargs)
            )
        )

    def form(self):
        return {
            "subject": USER["subject"],
            "csrf": "csrf-value",
            "ttl_days": "30",
            "reason": "Platform administration",
        }

    def confirmation(self):
        response = self.call("preview")
        self.assertEqual(response.status_code, 200)
        return {**hidden(response), "confirmed": "yes"}

    def test_preview_does_not_grant_and_confirmation_uses_exact_scope(self):
        form = self.confirmation()
        self.insert.assert_not_called()
        response = self.call("confirm", form)
        self.assertEqual(response.status_code, 303)
        self.insert.assert_called_once()
        args = self.insert.call_args.kwargs
        self.assertEqual(args["subject_key"], USER["subject"])
        self.assertEqual(args["scope"], "access:admin")
        self.assertEqual(args["ttl_days"], 30)
        self.assertEqual(self.audit.call_args.kwargs["event"], "admin_role_granted")

    def test_permanent_is_an_explicit_term(self):
        response = self.call("preview", {**self.form(), "ttl_days": "0"})
        self.assertIn("Бессрочно", body(response))
        response = self.call("confirm", {**hidden(response), "confirmed": "yes"})
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(self.insert.call_args.kwargs["ttl_days"])

    def test_confirmation_claim_prevents_concurrent_replay(self):
        form = self.confirmation()
        self.claim.side_effect = [
            {"claimed": True},
            {"claimed": False, "replayed": True},
        ]
        self.assertEqual(self.call("confirm", form).status_code, 303)
        self.assertEqual(self.call("confirm", form).status_code, 409)
        self.insert.assert_called_once()
        self.complete.assert_called_once()

    def test_idempotency_storage_failure_never_grants(self):
        form = self.confirmation()
        self.claim.side_effect = RuntimeError("storage-secret")
        response = self.call("confirm", form)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("storage-secret", body(response))
        self.insert.assert_not_called()

    def test_tampering_target_reason_or_term_never_grants(self):
        form = self.confirmation()
        for key, value in (
            ("reason", "Changed"),
            ("ttl_days", "365"),
            ("subject", "other"),
        ):
            with self.subTest(key=key):
                if key == "subject":
                    self.user.return_value = {**USER, "subject": "other"}
                response = self.call("confirm", {**form, key: value})
                self.assertEqual(response.status_code, 409)
                self.user.return_value = dict(USER)
        self.insert.assert_not_called()

    def test_actor_permission_is_rechecked_after_preview(self):
        form = self.confirmation()
        self.actor.return_value = GatewayActor(
            subject=ADMIN.subject, scopes=("access:read",)
        )
        self.assertEqual(self.call("confirm", form).status_code, 403)
        self.insert.assert_not_called()

    def test_old_token_scopes_cannot_bypass_live_authority_check(self):
        form = self.confirmation()
        self.current.side_effect = PermissionError("authority revoked")
        self.assertEqual(self.call("preview").status_code, 403)
        self.assertEqual(self.call("confirm", form).status_code, 403)
        self.insert.assert_not_called()

    def test_live_authority_storage_failure_is_closed(self):
        self.current.side_effect = RuntimeError("database-secret")
        response = self.call("preview")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("database-secret", body(response))
        self.insert.assert_not_called()

    def test_csrf_and_confirm_checkbox_are_required(self):
        form = self.confirmation()
        self.assertEqual(
            self.call("confirm", {**form, "csrf": "wrong"}).status_code, 403
        )
        self.assertEqual(
            self.call("confirm", {**form, "confirmed": ""}).status_code, 409
        )
        self.insert.assert_not_called()

    def test_unknown_self_and_denied_users_cannot_be_promoted(self):
        self.user.return_value = None
        self.assertEqual(self.call("preview").status_code, 409)
        self.user.return_value = {**USER, "email": ADMIN.email}
        self.assertEqual(self.call("preview").status_code, 403)
        self.user.return_value = dict(USER)
        self.state.return_value = {"is_admin": False, "denied": True, "grants": []}
        self.assertEqual(self.call("preview").status_code, 409)
        self.insert.assert_not_called()

    def test_replay_after_assignment_does_not_create_another_grant(self):
        form = self.confirmation()
        self.assertEqual(self.call("confirm", form).status_code, 303)
        self.state.return_value = {
            "is_admin": True,
            "denied": False,
            "grants": [{"id": 999}],
        }
        self.assertEqual(self.call("confirm", form).status_code, 409)
        self.insert.assert_called_once()

    def test_expired_and_cross_actor_confirmations_are_rejected(self):
        form = self.confirmation()
        expires = int(form["confirmation"].split(".")[0])
        with patch.object(roles.time, "time", return_value=expires + 1):
            self.assertEqual(self.call("confirm", form).status_code, 409)
        self.actor.return_value = GatewayActor(
            subject="other-admin", scopes=("access:admin",)
        )
        self.assertEqual(self.call("confirm", form).status_code, 409)
        self.insert.assert_not_called()

    def test_unknown_fields_and_invalid_terms_are_rejected(self):
        for extra in (
            {"scope": "*"},
            {"ttl_days": "-1"},
            {"reason": ""},
            {"ttl_days": "10000"},
        ):
            self.assertEqual(
                self.call("preview", {**self.form(), **extra}).status_code, 409
            )
        self.insert.assert_not_called()

    def test_role_panel_names_role_and_hides_redundant_action(self):
        page = roles.role_panel(USER, {"is_admin": True, "denied": False}, "x")
        self.assertIn("Роль в шлюзе: Администратор", page)
        self.assertNotIn("<form", page)
        page = roles.role_panel(USER, {"is_admin": False, "denied": False}, "x")
        self.assertIn("Назначить администратором", page)
        self.assertIn('action="/admin/users/role/preview"', page)
