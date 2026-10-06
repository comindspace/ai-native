import asyncio
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from test_admin_showcase import PERSON, PROFILE, SNAPSHOT, Mcp, Request

from gateway_mcp.routes import admin_access, team_ai_ui
from gateway_mcp.services.policy import GatewayActor


class TeamAIOverviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mcp = Mcp()
        admin_access.register_admin_access_routes(self.mcp)
        self.actor = self.stack.enter_context(
            patch.object(
                admin_access,
                "web_actor",
                return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
            )
        )
        self.authority = self.stack.enter_context(
            patch(
                "gateway_mcp.services.admin_roles.admin_role_state",
                return_value={"is_admin": True},
            )
        )
        self.snapshot = self.stack.enter_context(
            patch.object(
                admin_access.storage_showcase,
                "showcase_snapshot",
                return_value=copy.deepcopy(SNAPSHOT),
            )
        )
        person = {
            **copy.deepcopy(PERSON),
            "favorites": [{"skill_id": "architect", "skill_pack": "ai-native-core"}],
        }
        self.people = self.stack.enter_context(
            patch.object(
                admin_access.storage_showcase,
                "showcase_people",
                return_value={
                    "registered": 2,
                    "active": 1,
                    "unlinked": 0,
                    "people": [person],
                },
            )
        )
        self.agents = self.stack.enter_context(
            patch.object(
                admin_access.storage_showcase,
                "agent_profiles",
                return_value=[copy.deepcopy(PROFILE)],
            )
        )
        self.audit = self.stack.enter_context(patch.object(admin_access, "audit_event"))

    def page(self, query=None):
        response = asyncio.run(self.mcp.routes["/admin"](Request(query=query)))
        self.assertEqual(response.status_code, 200)
        return (
            response.body.decode()
            if isinstance(response.body, bytes)
            else response.body
        )

    def test_people_and_agents_precede_analytics_without_business_data(self):
        page = self.page()
        for label in (
            "Команда и AI",
            "Люди и их AI",
            "Codex",
            "Claude",
            "architect",
            "Ассистент",
            "Навыки в работе",
            "Активность команды",
        ):
            self.assertIn(label, page)
        for retired in (
            "Договорный портфель",
            "Оценка труда",
            "Экономика",
            "Продажи",
            "Проекты",
            "Витрина",
            "Бизнес-пульс",
            "category_id",
        ):
            self.assertNotIn(retired, page)
        self.assertLess(page.index('id="team-title"'), page.index("Навыки в работе"))
        self.assertLess(page.index('id="agents-title"'), page.index("Навыки в работе"))
        self.assertIn("Телеметрия пока не привязана", page)
        self.assertIn('aria-current="page"', page)
        self.assertIn(
            "Cache-Control", asyncio.run(self.mcp.routes["/admin"](Request())).headers
        )

    def test_source_outages_do_not_hide_other_sources_or_expose_details(self):
        for failed in (self.snapshot, self.people, self.agents):
            failed.side_effect = RuntimeError("private-secret")
            page = self.page()
            self.assertIn("Обнови страницу чуть позже", page)
            self.assertNotIn("private-secret", page)
            if failed is not self.people:
                self.assertIn("test-user", page)
            if failed is not self.agents:
                self.assertIn("Ассистент", page)
            failed.side_effect = None

    def test_period_is_validated_and_shared_by_all_sources(self):
        for raw, expected in (
            ("7", 7),
            ("90", 90),
            ("365", 30),
            ("-1", 30),
            ("oops", 30),
        ):
            self.page({"days": raw, "category_id": "19"})
            self.snapshot.assert_called_with(expected)
            self.people.assert_called_with(expected, limit=4)
            self.agents.assert_called_with(expected)

    def test_unavailable_data_is_not_presented_as_zero(self):
        page = team_ai_ui.render(None, None, None, 30)
        self.assertNotIn("<strong>0</strong>", page)
        self.assertEqual(page.count("<strong>—</strong>"), 4)

    def test_empty_sources_offer_real_navigation(self):
        self.people.return_value = {
            "registered": 0,
            "active": 0,
            "unlinked": 0,
            "people": [],
        }
        self.agents.return_value = []
        page = self.page()
        self.assertIn("После входа сотрудников", page)
        self.assertIn("В реестре пока нет", page)
        self.assertIn("/my/skills?days=30", page)

    def test_directory_values_are_escaped(self):
        self.people.return_value["people"][0]["login"] = "<img src=x onerror=alert(1)>"
        self.people.return_value["people"][0]["favorites"][0]["skill_id"] = (
            "<script>bad()</script>"
        )
        page = self.page()
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<script>bad()", page)
        self.assertIn("&lt;script&gt;bad()", page)

    def test_non_admin_never_reads_directory(self):
        self.actor.return_value = GatewayActor(
            subject="employee", scopes=("skills:read",)
        )
        response = asyncio.run(self.mcp.routes["/admin"](Request()))
        self.assertEqual(response.status_code, 403)
        self.snapshot.assert_not_called()
        self.people.assert_not_called()
        self.agents.assert_not_called()

    def test_revoked_admin_token_never_reads_directory(self):
        self.authority.return_value = {"is_admin": False}
        response = asyncio.run(self.mcp.routes["/admin"](Request()))
        self.assertEqual(response.status_code, 403)
        self.authority.assert_called_once()
        self.snapshot.assert_not_called()
        self.people.assert_not_called()
        self.agents.assert_not_called()

    def test_authority_read_failure_never_reads_directory(self):
        self.authority.side_effect = RuntimeError("private-policy-secret")
        response = asyncio.run(self.mcp.routes["/admin"](Request()))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-policy-secret", str(response.body))
        self.snapshot.assert_not_called()
        self.people.assert_not_called()
        self.agents.assert_not_called()
