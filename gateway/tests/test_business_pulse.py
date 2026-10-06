import asyncio
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.routes.business_pulse_ui import (
    render_overview,
    render_portfolio,
    render_sales,
)
from gateway_mcp.services import business_pulse as service
from gateway_mcp.services.policy import GatewayActor

ACTOR = GatewayActor(
    subject="user:1", scopes=("access:admin", "tracker:read", "bitrix24:read")
)
PROJECTS = {
    "projects": [
        {"id": "uuid-1", "short_id": "1", "name": "Contract A"},
        {"id": "uuid-2", "short_id": "2", "name": "Contract B"},
    ],
    "limited": False,
}


def link(project="1", deal=10, amount="2000", currency="RUB"):
    return {
        "tracker_project_id": project,
        "crm_deal_id": deal,
        "contract_confirmed": True,
        "confirmed_amount": Decimal(amount),
        "confirmed_currency": currency,
    }


class BusinessPulseTests(unittest.TestCase):
    def snapshot(self, links, deals=None, logs=None, **kwargs):
        async def deal(deal_id):
            return (deals or {}).get(
                deal_id,
                {"ID": str(deal_id), "OPPORTUNITY": "2000", "CURRENCY_ID": "RUB"},
            )

        with (
            patch.object(service, "cost_rates", return_value={}),
            patch.object(service, "crm_deal_amount", side_effect=deal) as crm,
            patch.object(
                service,
                "project_worklogs",
                new_callable=AsyncMock,
                return_value=logs
                or {
                    "logs": [{"duration": "PT1H", "createdBy": {"id": "person"}}],
                    "limited": False,
                },
            ) as work,
        ):
            value = asyncio.run(
                service.portfolio_snapshot(
                    ACTOR, projects=PROJECTS, links=links, **kwargs
                )
            )
        return value, crm, work

    def test_currency_totals_and_labor_use_the_same_comparable_cohort(self):
        data, _, _ = self.snapshot(
            [link(), link("2", 20, "1000", "USD")],
            deals={20: {"ID": "20", "OPPORTUNITY": "1000", "CURRENCY_ID": "USD"}},
        )
        self.assertEqual(data["totals"], {"RUB": Decimal(2000), "USD": Decimal(1000)})
        self.assertEqual(data["comparable_amount"], Decimal(2000))
        self.assertEqual(data["labor_cost"], Decimal(1800))
        self.assertEqual(data["consumed_percent"], Decimal(90))
        self.assertEqual(data["calculated_count"], 1)
        self.assertEqual(data["attention_count"], 1)
        self.assertEqual(data["rows"][0]["status"], "check_remaining")

    def test_hidden_projects_are_never_fetched_or_exposed(self):
        data, crm, _ = self.snapshot([link(), link("hidden", 99, "9999999")])
        crm.assert_awaited_once_with(10)
        self.assertEqual(data["linked_count"], 1)
        self.assertNotIn("hidden", str(data))
        self.assertNotIn("9999999", str(data))

    def test_project_aliases_do_not_double_count_contracts(self):
        data, crm, work = self.snapshot([link(), link("uuid-1", 20)])
        crm.assert_not_awaited()
        work.assert_not_awaited()
        self.assertEqual(data["totals"], {})
        self.assertEqual(data["rows"][0]["status"], "duplicate_links")

    def test_changed_or_nonfinite_contract_is_excluded(self):
        data, _, work = self.snapshot(
            [link()],
            deals={10: {"ID": "10", "OPPORTUNITY": "NaN", "CURRENCY_ID": "RUB"}},
        )
        work.assert_not_awaited()
        self.assertEqual(data["totals"], {})
        self.assertEqual(data["rows"][0]["status"], "confirm_contract")

    def test_same_deal_on_multiple_projects_is_not_double_counted(self):
        data, crm, work = self.snapshot([link(), link("2")])
        crm.assert_not_awaited()
        work.assert_not_awaited()
        self.assertEqual(data["totals"], {})
        self.assertEqual([r["status"] for r in data["rows"]], ["duplicate_deal"] * 2)

    def test_hidden_project_link_still_excludes_ambiguous_deal_without_disclosure(self):
        data, crm, work = self.snapshot([link(), link("confidential-project")])
        crm.assert_not_awaited()
        work.assert_not_awaited()
        self.assertEqual(data["totals"], {})
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["status"], "duplicate_deal")
        self.assertNotIn("confidential-project", str(data))

    def test_missing_next_step_source_is_visible_in_overview_and_sales(self):
        sales = {
            "category_id": "4",
            "days": 30,
            "sampled": 1,
            "total_active": 1,
            "limited": False,
            "stages": [],
            "no_next_step": None,
            "no_amount": 0,
            "stale": 0,
            "stale_days": 7,
        }
        page = render_sales(sales)
        self.assertIn("Следующий шаг сделок не проверен", page)
        self.assertIn("В доступных показателях", page)
        page = render_overview(
            {
                "portfolio": {"available": False},
                "sales": sales,
                "category_id": "4",
                "days": 30,
            }
        )
        self.assertIn("Следующий шаг сделок не проверен", page)
        self.assertIn("category_id=4", page)

    def test_incomplete_logs_hide_money_but_preserve_contract(self):
        data, _, _ = self.snapshot(
            [link()],
            logs={
                "logs": [{"duration": "PT1H", "createdBy": {"id": "p"}}],
                "limited": True,
            },
        )
        self.assertEqual(data["totals"], {"RUB": Decimal(2000)})
        self.assertIsNone(data["labor_cost"])
        self.assertIsNone(data["consumed_percent"])
        self.assertEqual(data["rows"][0]["status"], "incomplete_worklogs")

    def test_no_logs_are_not_zero_cost(self):
        data, _, _ = self.snapshot([link()], logs={"logs": [], "limited": False})
        self.assertEqual(data["rows"][0]["status"], "no_worklogs")
        self.assertIsNone(data["labor_cost"])

    def test_worklog_timeout_keeps_confirmed_crm_amount(self):
        with (
            patch.object(service, "cost_rates", return_value={}),
            patch.object(
                service,
                "crm_deal_amount",
                new_callable=AsyncMock,
                return_value={"ID": "10", "OPPORTUNITY": "2000", "CURRENCY_ID": "RUB"},
            ),
            patch.object(
                service,
                "project_worklogs",
                new_callable=AsyncMock,
                side_effect=TimeoutError,
            ),
        ):
            data = asyncio.run(
                service.portfolio_snapshot(ACTOR, projects=PROJECTS, links=[link()])
            )
        self.assertEqual(data["totals"], {"RUB": Decimal(2000)})
        self.assertEqual(data["rows"][0]["status"], "worklogs_unavailable")

    def test_read_limit_is_explicit(self):
        with patch.object(service, "MAX_CONTRACTS", 1):
            data, _, _ = self.snapshot([link(), link("2", 20)])
        self.assertTrue(data["limited"])
        self.assertEqual(data["linked_count"], 2)
        self.assertEqual(len(data["rows"]), 1)

    def test_missing_scopes_do_not_read_finance(self):
        with (
            patch.object(service, "list_project_links") as read,
            patch.object(
                service, "tracker_projects_snapshot", new_callable=AsyncMock
            ) as projects,
        ):
            result = asyncio.run(
                service.portfolio_snapshot(
                    GatewayActor(subject="x", scopes=("access:admin",))
                )
            )
        self.assertFalse(result["available"])
        read.assert_not_called()
        projects.assert_not_awaited()

    def test_business_render_is_actionable_escaped_and_not_progress(self):
        data, _, _ = self.snapshot([link()])
        data["rows"][0]["name"] = "<script>secret</script>"
        page = render_overview(
            {"portfolio": data, "sales": None, "category_id": "0", "days": 30}
        )
        self.assertIn("Метрики", page)
        self.assertIn("Оценить затраты до завершения", page)
        self.assertIn("tracker_project_id=1", page)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        full = render_portfolio(data)
        self.assertIn("это не готовность работ", full)
        self.assertIn('id="unlinked"', full)

    def test_sales_survives_portfolio_failure(self):
        with (
            patch.object(
                service,
                "portfolio_snapshot",
                new_callable=AsyncMock,
                return_value={"available": False},
            ),
            patch.object(
                service,
                "sales_snapshot",
                new_callable=AsyncMock,
                return_value={"total_active": 3},
            ),
        ):
            data = asyncio.run(service.business_pulse(ACTOR))
        self.assertEqual(data["sales"]["total_active"], 3)
