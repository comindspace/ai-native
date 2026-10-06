import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import admin_roles as service
from gateway_mcp.services import policy
from gateway_mcp.services import storage_admin_roles as storage

USER = {
    "subject": "yandex:42",
    "yandex_id": "42",
    "login": "staff",
    "email": "staff@example.test",
}
ACTOR = policy.GatewayActor(
    subject="yandex:1", yandex_id="1", scopes=("access:admin",), groups=("admins",)
)
EMPTY_POLICY = {"users": {}, "groups": {}, "default_groups": []}


class AdminAuthorityTests(unittest.TestCase):
    def test_token_scopes_and_groups_do_not_keep_revoked_authority(self):
        with (
            patch.object(policy, "_read_policy", return_value=EMPTY_POLICY),
            patch.object(service, "list_active_scope_grants", return_value=[]),
            self.assertRaises(PermissionError),
        ):
            service.require_current_admin(ACTOR)

    def test_live_grant_and_current_bootstrap_policy_allow_authority(self):
        for bootstrap, grants in (
            (EMPTY_POLICY, [{"id": 1, "scope": "access:admin", "effect": "allow"}]),
            (
                {
                    "users": {"1": {"scopes": ["access:admin"]}},
                    "groups": {},
                    "default_groups": [],
                },
                [],
            ),
        ):
            with (
                patch.object(policy, "_read_policy", return_value=bootstrap),
                patch.object(
                    service, "list_active_scope_grants", return_value=grants
                ) as read,
            ):
                service.require_current_admin(ACTOR)
                self.assertIn(("user", "yandex:1"), read.call_args.args[0])

    def test_deny_and_failed_database_read_are_closed(self):
        with patch.object(
            policy,
            "_read_policy",
            return_value={
                "users": {"1": {"scopes": ["*"]}},
                "groups": {},
                "default_groups": [],
            },
        ):
            with (
                patch.object(
                    service,
                    "list_active_scope_grants",
                    return_value=[{"id": 1, "scope": "access:admin", "effect": "deny"}],
                ),
                self.assertRaises(PermissionError),
            ):
                service.require_current_admin(ACTOR)
            with (
                patch.object(
                    service, "list_active_scope_grants", side_effect=RuntimeError("db")
                ),
                self.assertRaises(RuntimeError),
            ):
                service.require_current_admin(ACTOR)

    def test_different_concurrent_assignments_have_one_winner(self):
        lock = threading.Lock()
        start = threading.Barrier(2)
        active = []

        @contextmanager
        def recipient_lock(subject):
            self.assertEqual(subject, USER["subject"])
            with lock:
                yield

        def state(user):
            return {"is_admin": bool(active), "denied": False, "grants": list(active)}

        def grant(**kwargs):
            active.append({"id": 1})
            return {"grant": {"id": 1}}

        def run(days):
            preview = {
                "user": USER,
                "state": {"is_admin": False, "denied": False, "grants": []},
                "grant": {"reason": "Admin duties", "ttl_days": days},
            }
            start.wait(timeout=3)
            try:
                service.assign_admin_role(ACTOR, preview)
                return "granted"
            except ValueError:
                return "conflict"

        with (
            patch.object(
                service, "admin_role_assignment_lock", side_effect=recipient_lock
            ),
            patch.object(service, "require_current_admin"),
            patch.object(service, "admin_user_get", return_value=USER),
            patch.object(service, "admin_role_state", side_effect=state),
            patch.object(service, "admin_grant_scope", side_effect=grant) as insert,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            outcomes = list(pool.map(run, [7, 365]))
        self.assertEqual(sorted(outcomes), ["conflict", "granted"])
        insert.assert_called_once()

    def test_storage_lock_is_held_until_critical_section_finishes(self):
        events = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, sql, params):
                self_sql = sql
                if "pg_advisory_xact_lock" not in self_sql:
                    raise AssertionError(sql)
                events.append(("lock", params))

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                events.append("release")

            def cursor(self):
                return Cursor()

        with (
            patch.object(storage, "postgres_enabled", return_value=True),
            patch.object(storage, "ensure_schema"),
            patch.object(storage, "_connect", return_value=Connection()),
            storage.admin_role_assignment_lock("YANDEX:42"),
        ):
            events.append("grant-committed")
        self.assertEqual(
            events,
            [("lock", ("gateway-admin-role:yandex:42",)), "grant-committed", "release"],
        )
