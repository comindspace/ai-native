import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()


class BusinessEconomicsTests(unittest.IsolatedAsyncioTestCase):
    def test_crm_deep_link_never_contains_webhook_credentials(self):
        from gateway_mcp.services.business_economics import crm_deal_url

        with patch(
            "gateway_mcp.services.business_economics.integration_value",
            return_value="https://service:password@crm.example.test/rest/1/private-webhook/",
        ):
            self.assertEqual(
                crm_deal_url(42), "https://crm.example.test/crm/deal/details/42/"
            )
            self.assertEqual(crm_deal_url("../private"), "")

    def test_tracker_duration_uses_eight_hour_day(self) -> None:
        from gateway_mcp.services.business_economics import worklog_hours

        self.assertEqual(worklog_hours("P1W2DT30M"), Decimal("56.5"))
        self.assertEqual(worklog_hours("PT1H15M"), Decimal("1.25"))
        self.assertIsNone(worklog_hours("P1M"))
        self.assertIsNone(worklog_hours("invalid"))

    def test_cost_is_estimate_and_margin_requires_complete_rub_contract(self) -> None:
        from gateway_mcp.services.business_economics import calculate_economics

        logs = [
            {"createdBy": {"id": "u1", "display": "Engineer"}, "duration": "PT2H"},
            {"createdBy": {"id": "u2", "display": "PM"}, "duration": "PT1H"},
        ]
        data = calculate_economics(
            deal={"OPPORTUNITY": "10000", "CURRENCY_ID": "RUB"},
            confirmed=True,
            logs=logs,
            rates={"u1": {"hourly_rate_rub": Decimal(1000), "basis": "estimate"}},
            complete=True,
        )
        self.assertEqual(data["hours"], Decimal(3))
        self.assertEqual(data["labor_cost"], Decimal("3800.00"))
        self.assertEqual(data["balance_after_logged_labor"], Decimal("6200.00"))
        self.assertEqual(data["reviewed_rates"], 1)
        for incomplete, confirmed, currency in (
            (True, True, "RUB"),
            (False, False, "RUB"),
            (False, True, "USD"),
        ):
            result = calculate_economics(
                deal={"OPPORTUNITY": "10000", "CURRENCY_ID": currency},
                confirmed=confirmed,
                logs=logs,
                rates={},
                complete=not incomplete,
            )
            self.assertIsNone(result["balance_after_logged_labor"])

    def test_unknown_author_and_invalid_duration_hide_financial_result(self) -> None:
        from gateway_mcp.services.business_economics import calculate_economics

        data = calculate_economics(
            deal={"OPPORTUNITY": "10000", "CURRENCY_ID": "RUB"},
            confirmed=True,
            logs=[
                {"duration": "PT2H"},
                {"createdBy": {"id": "u1"}, "duration": "P1M"},
            ],
            rates={},
            complete=True,
        )
        self.assertEqual(data["unknown_authors"], 1)
        self.assertEqual(data["invalid_durations"], 1)
        self.assertIsNone(data["labor_cost"])
        self.assertIsNone(data["balance_after_logged_labor"])

    def test_no_worklogs_do_not_show_full_contract_as_balance(self) -> None:
        from gateway_mcp.services.business_economics import calculate_economics

        data = calculate_economics(
            deal={"OPPORTUNITY": "10000", "CURRENCY_ID": "RUB"},
            confirmed=True,
            logs=[],
            rates={},
            complete=True,
        )
        self.assertIsNone(data["labor_cost"])
        self.assertIsNone(data["balance_after_logged_labor"])

    async def test_worklogs_follow_pages_and_deduplicate(self) -> None:
        from gateway_mcp.services.business_economics import project_worklogs

        issue = [{"key": "DEMO-1"}]
        page = [{"id": str(index), "duration": "PT1H"} for index in range(100)]
        calls = []

        async def fake_tracker(route, args, *, actor_subject):
            calls.append((route["name"], args, actor_subject))
            if route["name"] == "tracker.issues.search":
                return {"ok": True, "data": issue, "total_count": "1"}
            return {
                "ok": True,
                "data": page
                if "id" not in args
                else [page[-1], {"id": "100", "duration": "PT2H"}],
            }

        with (
            patch(
                "gateway_mcp.services.business_economics._route",
                side_effect=lambda name: {"name": name},
            ),
            patch(
                "gateway_mcp.services.business_economics._call_tracker",
                side_effect=fake_tracker,
            ),
        ):
            result = await project_worklogs(
                actor_subject="admin", tracker_project_id="42"
            )
        self.assertEqual(result["issue_count"], 1)
        self.assertEqual(len(result["logs"]), 101)
        self.assertFalse(result["limited"])
        self.assertEqual(calls[-1][1]["id"], "99")

    async def test_crm_deal_returns_only_needed_fields(self) -> None:
        from gateway_mcp.services.business_economics import crm_deal_amount

        with patch(
            "gateway_mcp.services.business_economics._bitrix",
            new_callable=AsyncMock,
            return_value={
                "result": {
                    "ID": "42",
                    "OPPORTUNITY": "100",
                    "CURRENCY_ID": "RUB",
                    "COMMENTS": "private",
                }
            },
        ):
            result = await crm_deal_amount(42)
        self.assertEqual(result["OPPORTUNITY"], "100")
        self.assertNotIn("COMMENTS", result)


if __name__ == "__main__":
    unittest.main()
