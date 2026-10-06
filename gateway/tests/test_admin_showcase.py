import asyncio
import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import urlencode

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.routes import admin_showcase as routes
from gateway_mcp.routes import showcase_ui as ui
from gateway_mcp.services import storage_showcase as storage
from gateway_mcp.services.policy import GatewayActor

ACTOR = GatewayActor(
    subject="yandex:1", email="one@example.test", scopes=("access:admin",)
)
TOTALS = {
    "starts": 8,
    "completed": 5,
    "failed": 1,
    "pending": 2,
    "timed": 4,
    "median_ms": 120000,
    "last_activity": "2026-09-29T08:00:00+00:00",
    "actors": 2,
    "skills": 3,
}
SNAPSHOT = {
    "days": 30,
    "today": "2026-09-29",
    "totals": TOTALS,
    "clients": [{"agent": "codex", "starts": 8}],
    "skills": [{"skill_id": "tech-lead", "skill_pack": "delivery-core", "starts": 8}],
    "daily": [{"day": "2026-09-28", "starts": 8}],
}
PERSON = {
    "subject": "yandex:1",
    "login": "test-user",
    "email": "one@example.test",
    "starts": 8,
    "completed": 5,
    "failed": 1,
    "pending": 2,
    "last_activity": "2026-09-29T08:00:00+00:00",
    "clients": ["codex", "claude-code"],
    "skills": SNAPSHOT["skills"],
    "favorites": [],
}
PROFILE = {
    "agent_key": "assistant",
    "display_name": "Ассистент",
    "description": "Корпоративный агент",
    "actor_subject": "",
    "agent": "",
    "revision": 1,
    "starts": None,
    "completed": None,
    "failed": None,
    "pending": None,
    "timed": None,
    "median_ms": None,
    "last_activity": None,
}


class Mcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, **kwargs):
        def register(fn):
            self.routes[path] = fn
            return fn

        return register


class Request:
    def __init__(self, query=None, form=None, csrf="csrf", raw=None):
        self.query_params = query or {}
        self.cookies = {routes.CSRF_COOKIE: csrf}
        self.form, self.raw = form or {}, raw

    async def body(self):
        return self.raw if self.raw is not None else urlencode(self.form).encode()


def body(response):
    return response.body.decode() if isinstance(response.body, bytes) else response.body


class ShowcaseRoutesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mcp = Mcp()
        routes.register_admin_showcase_routes(self.mcp)
        self.actor = self.stack.enter_context(
            patch.object(routes, "web_actor", return_value=ACTOR)
        )
        self.authority = self.stack.enter_context(
            patch.object(routes, "require_current_admin")
        )
        self.audit = self.stack.enter_context(
            patch.object(routes, "audit_event", autospec=True)
        )
        self.cookie = self.stack.enter_context(
            patch.object(routes.HTMLResponse, "set_cookie", create=True)
        )
        self.reads = {}
        values = {
            "showcase_snapshot": copy.deepcopy(SNAPSHOT),
            "showcase_people": {
                "registered": 2,
                "active": 1,
                "matched": 2,
                "unlinked": 0,
                "people": [PERSON],
            },
            "agent_profiles": [copy.deepcopy(PROFILE)],
            "agent_binding_options": [],
            "showcase_usage": [],
            "skill_favorites": [],
            "set_skill_favorite": None,
            "save_agent_profile": None,
        }
        for key, value in values.items():
            self.reads[key] = self.stack.enter_context(
                patch.object(storage, key, return_value=value)
            )
        self.user = self.stack.enter_context(
            patch.object(routes, "admin_user_get", return_value=PERSON)
        )

    def call(self, path, request=None):
        return asyncio.run(self.mcp.routes[path](request or Request()))

    def test_every_admin_route_checks_current_authority(self):
        self.authority.side_effect = PermissionError("revoked")
        for path in self.mcp.routes:
            if path.startswith("/admin/"):
                with self.subTest(path=path):
                    self.assertEqual(self.call(path).status_code, 403)
        for read in self.reads.values():
            read.assert_not_called()

    def test_unauthenticated_personal_page_redirects(self):
        self.actor.return_value = None
        self.assertIn(self.call("/my/skills").status_code, (302, 303, 307))
        self.reads["showcase_snapshot"].assert_not_called()

    def test_period_and_pagination_are_bounded(self):
        response = self.call(
            "/admin/people",
            Request(query={"days": "999", "page": "-1", "q": "<script>"}),
        )
        self.assertEqual(response.status_code, 200)
        self.reads["showcase_people"].assert_called_once_with(30, "<script>", 0)
        self.assertNotIn("<script>", body(response))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_personal_metrics_are_self_scoped_without_admin_authority(self):
        self.actor.return_value = GatewayActor(subject="employee", scopes=())
        response = self.call(
            "/my/skills", Request(query={"subject": "victim", "days": "7"})
        )
        self.assertEqual(response.status_code, 200)
        self.authority.assert_not_called()
        self.reads["showcase_snapshot"].assert_called_once_with(
            7, subject="employee", people_only=True
        )
        self.reads["showcase_usage"].assert_called_once_with(7, "employee")
        self.assertNotIn('href="/admin/people', body(response))

    def test_favorite_never_accepts_another_subject(self):
        form = {
            "csrf": "csrf",
            "skill_pack": "delivery-core",
            "skill_id": "tech-lead",
            "selected": "1",
            "days": "7",
            "subject": "victim",
        }
        self.assertEqual(
            self.call("/my/skills/favorite", Request(form=form)).status_code, 409
        )
        self.reads["set_skill_favorite"].assert_not_called()
        del form["subject"]
        response = self.call("/my/skills/favorite", Request(form=form))
        self.assertEqual(response.status_code, 303)
        self.reads["set_skill_favorite"].assert_called_once_with(
            ACTOR.subject, "delivery-core", "tech-lead", True
        )
        self.assertIn("days=7", response.headers["location"])

    def test_csrf_invalid_forms_and_duplicate_fields_do_not_write(self):
        cases = [
            Request(form={"csrf": "wrong"}),
            Request(raw=b"csrf=csrf&csrf=csrf"),
            Request(raw=b"x" * 8001),
            Request(raw=b"\xff"),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertIn(
                    self.call("/my/skills/favorite", case).status_code, (403, 409)
                )
                self.assertIn(
                    self.call("/admin/agents/save", case).status_code, (403, 409)
                )
        self.reads["set_skill_favorite"].assert_not_called()
        self.reads["save_agent_profile"].assert_not_called()

    def test_unknown_profile_is_404_and_unbound_has_no_fake_metrics(self):
        self.assertEqual(
            self.call(
                "/admin/agents/detail", Request(query={"key": "missing"})
            ).status_code,
            404,
        )
        response = self.call("/admin/agents/detail", Request(query={"key": "assistant"}))
        self.assertIn("Статус работы и результаты пока неизвестны", body(response))
        self.reads["showcase_snapshot"].assert_not_called()
        self.reads["showcase_usage"].assert_not_called()

    def test_bound_autonomous_profile_reads_exact_pair(self):
        self.reads["agent_profiles"].return_value = [
            {**PROFILE, "actor_subject": "service:assistant", "agent": "hermes"}
        ]
        response = self.call("/admin/agents/detail", Request(query={"key": "assistant"}))
        self.assertEqual(response.status_code, 200)
        self.reads["showcase_snapshot"].assert_called_once_with(
            30, subject="service:assistant", agent="hermes"
        )
        self.reads["showcase_usage"].assert_called_once_with(
            30, "service:assistant", "hermes", False
        )

    def test_registry_save_uses_revision_and_current_identity(self):
        form = {
            "csrf": "csrf",
            "key": "assistant",
            "name": "Ассистент",
            "description": "Updates",
            "binding": json.dumps(["service:assistant", "hermes"]),
            "revision": "1",
        }
        self.assertEqual(
            self.call("/admin/agents/save", Request(form=form)).status_code, 303
        )
        self.reads["save_agent_profile"].assert_called_once_with(
            key="assistant",
            name="Ассистент",
            description="Updates",
            subject="service:assistant",
            agent="hermes",
            revision=1,
            updated_by=ACTOR.subject,
        )
        for pair in ("hermes", {}, ["x"], [1, 2], ["", "hermes"]):
            with self.subTest(pair=pair):
                self.assertEqual(
                    self.call(
                        "/admin/agents/save",
                        Request(form={**form, "binding": json.dumps(pair)}),
                    ).status_code,
                    409,
                )

    def test_database_failure_does_not_leak_secrets_or_show_zero(self):
        self.reads["showcase_snapshot"].side_effect = RuntimeError("postgres://SECRET")
        response = self.call("/admin/showcase")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SECRET", body(response))
        self.assertIn("Не удалось загрузить", body(response))


class ShowcaseProjectionTests(unittest.TestCase):
    def test_queries_scope_before_aggregation_and_parameterize_values(self):
        # Not just a UI filter: cross-user data must never be fetched for personal pages.
        with patch.object(storage, "_rows", return_value=[{}]) as read:
            storage.showcase_snapshot(
                7, subject="' OR true", agent="hermes", people_only=True
            )
        sql, params = read.call_args.args
        self.assertEqual(params, (7, "' OR true", "hermes"))
        self.assertNotIn("' OR true", sql)
        self.assertIn("e.actor_subject = s.actor_subject", sql)
        self.assertIn("e.correlation_id = s.correlation_id", sql)
        self.assertIn("e.created_at >= s.created_at", sql)
        self.assertIn("not exists", sql)
        for private in ("raw_event", "payload", "metadata", "access_token", "cwd"):
            self.assertNotIn(private, sql)

    def test_explicit_favorites_are_not_lost_when_outside_top_skills(self):
        markup = ui.favorite_list(
            [],
            [{"skill_pack": "pack", "skill_id": "rare", "starts": 3}],
            True,
            "csrf",
            30,
        )
        self.assertIn("3 запусков", markup)
        self.assertIn('aria-pressed="true"', markup)
        self.assertIn('value="0"', markup)

    def test_unknown_and_measured_zero_are_distinct(self):
        unbound = ui.agent_card(PROFILE, 30)
        bound = ui.agent_card({**PROFILE, "actor_subject": "service:x"}, 30)
        self.assertIn("<strong>—</strong>", unbound)
        self.assertIn("<strong>0</strong>", bound)
        self.assertNotIn("онлайн", bound.lower())
        self.assertIn("Нет сигнала", bound)

    def test_untrusted_names_and_saved_preferences_are_escaped(self):
        markup = ui.person_card(
            {
                **PERSON,
                "login": '<img src=x onerror="x">',
                "favorites": [{"skill_id": "<script>"}],
            },
            30,
        )
        self.assertNotIn("<img", markup)
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)

    def test_partial_usage_costs_have_coverage_and_no_combined_total(self):
        markup = ui.usage_panel(
            [
                {
                    "source_quality": "actual",
                    "source": "proxy",
                    "usage_class": "inference",
                    "records": 5,
                    "token_records": 4,
                    "tokens": 100,
                    "cost_records": 0,
                    "cost_usd": None,
                }
            ]
        )
        self.assertIn("4 из 5", markup)
        self.assertIn("0 из 5", markup)
        self.assertNotIn("$0.00", markup)
        self.assertIn("без общего итога", markup)


if __name__ == "__main__":
    unittest.main()
