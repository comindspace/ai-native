import os
import urllib.parse
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.bitrix24 import _call_bitrix24


class FakeResponse:
    status_code = 200
    is_success = True
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeAsyncClient:
    calls = []
    responses = {}

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        method = url.rsplit("/", 1)[-1]
        return FakeResponse(self.responses.get(method, {"result": [], "total": 0}))

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        method = url.rsplit("/", 1)[-1]
        if method == "crm.activity.list":
            parsed = urllib.parse.parse_qs(kwargs.get("content", b"").decode("utf-8"))
            owner_id = parsed.get("filter[OWNER_ID]", [""])[0]
            activities = self.responses.get("crm.activity.list", {}).get(owner_id, [])
            return FakeResponse({"result": activities, "total": len(activities)})
        return FakeResponse(self.responses.get(method, {"result": [], "total": 0}))


class Bitrix24BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.calls = []
        FakeAsyncClient.responses = {}

    async def test_empty_arguments_use_get(self) -> None:
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24({"bitrix_method": "crm.lead.list"}, {})

        self.assertTrue(result["ok"])
        self.assertEqual(FakeAsyncClient.calls[0][0], "GET")
        self.assertEqual(FakeAsyncClient.calls[0][1], "https://example.bitrix24.ru/rest/1/token/crm.lead.list")

    async def test_flat_arguments_use_async_safe_urlencoded_content(self) -> None:
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"bitrix_method": "crm.deal.list"},
                {"select": ["ID", "TITLE"], "start": 0},
            )

        self.assertTrue(result["ok"])
        method, _, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertNotIn("data", kwargs)
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(kwargs["content"], b"select%5B0%5D=ID&select%5B1%5D=TITLE&start=0")

    async def test_params_envelope_is_encoded(self) -> None:
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"bitrix_method": "crm.duplicate.findbycomm"},
                {"params": {"entity_type": "CONTACT", "type": "EMAIL", "values": ["a@example.com"]}},
            )

        self.assertTrue(result["ok"])
        _, _, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(
            kwargs["content"],
            b"entity_type=CONTACT&type=EMAIL&values%5B0%5D=a%40example.com",
        )

    async def test_sales_pipeline_filter_select_and_custom_fields_are_encoded(self) -> None:
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"bitrix_method": "crm.deal.list"},
                {
                    "params": {
                        "filter": {
                            "CATEGORY_ID": 1,
                            "STAGE_ID": "C1:NEW",
                            "ASSIGNED_BY_ID": 7,
                            ">=DATE_MODIFY": "2026-06-01T00:00:00+03:00",
                        },
                        "select": [
                            "ID",
                            "TITLE",
                            "ASSIGNED_BY_ID",
                            "UF_CRM_NEXT_STEP",
                            "UF_CRM_NEXT_TOUCH_DATE",
                        ],
                        "start": 50,
                    }
                },
            )

        self.assertTrue(result["ok"])
        _, _, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(
            kwargs["content"],
            (
                b"filter%5BCATEGORY_ID%5D=1&filter%5BSTAGE_ID%5D=C1%3ANEW"
                b"&filter%5BASSIGNED_BY_ID%5D=7&filter%5B%3E%3DDATE_MODIFY%5D=2026-06-01T00%3A00%3A00%2B03%3A00"
                b"&select%5B0%5D=ID&select%5B1%5D=TITLE&select%5B2%5D=ASSIGNED_BY_ID"
                b"&select%5B3%5D=UF_CRM_NEXT_STEP&select%5B4%5D=UF_CRM_NEXT_TOUCH_DATE&start=50"
            ),
        )

    async def test_timeline_comment_add_with_files_normalizes_agent_payload(self) -> None:
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"name": "bitrix24.timeline.comment.add_with_files"},
                {
                    "params": {
                        "entity_type": "deal",
                        "entity_id": 1709,
                        "comment": "КП во вложении",
                        "files": [
                            {"name": "proposal.pdf", "content_base64": "JVBERi0x"},
                            ["invoice.txt", "SGVsbG8="],
                        ],
                    }
                },
            )

        self.assertTrue(result["ok"])
        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://example.bitrix24.ru/rest/1/token/crm.timeline.comment.add")
        parsed = urllib.parse.parse_qs(kwargs["content"].decode("utf-8"))
        self.assertEqual(parsed["fields[ENTITY_TYPE]"], ["deal"])
        self.assertEqual(parsed["fields[ENTITY_ID]"], ["1709"])
        self.assertEqual(parsed["fields[COMMENT]"], ["КП во вложении"])
        self.assertEqual(parsed["fields[FILES][0][0]"], ["proposal.pdf"])
        self.assertEqual(parsed["fields[FILES][0][1]"], ["JVBERi0x"])
        self.assertEqual(parsed["fields[FILES][1][0]"], ["invoice.txt"])
        self.assertEqual(parsed["fields[FILES][1][1]"], ["SGVsbG8="])

    async def test_deal_attach_file_normalizes_deal_payload(self) -> None:
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"name": "bitrix24.deals.attach_file"},
                {
                    "params": {
                        "deal_id": 1753,
                        "comment": "КП во вложении",
                        "files": [{"name": "proposal.pdf", "content_base64": "JVBERi0x"}],
                    }
                },
            )

        self.assertTrue(result["ok"])
        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://example.bitrix24.ru/rest/1/token/crm.timeline.comment.add")
        parsed = urllib.parse.parse_qs(kwargs["content"].decode("utf-8"))
        self.assertEqual(parsed["fields[ENTITY_TYPE]"], ["deal"])
        self.assertEqual(parsed["fields[ENTITY_ID]"], ["1753"])
        self.assertEqual(parsed["fields[COMMENT]"], ["КП во вложении"])
        self.assertEqual(parsed["fields[FILES][0][0]"], ["proposal.pdf"])
        self.assertEqual(parsed["fields[FILES][0][1]"], ["JVBERi0x"])

    async def test_company_upsert_updates_existing_and_links_deal(self) -> None:
        FakeAsyncClient.responses = {
            "crm.company.list": {
                "result": [{"ID": "42", "TITLE": "Acme Development", "WEB": []}],
                "total": 1,
            },
            "crm.company.update": {"result": True},
            "crm.deal.update": {"result": True},
        }
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"name": "bitrix24.companies.upsert"},
                {
                    "params": {
                        "title": "Acme Development",
                        "website": "https://acme.example",
                        "deal_id": 1753,
                    }
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["company_id"], "42")
        self.assertEqual(result["data"]["deal_id"], "1753")
        self.assertEqual([call[1].rsplit("/", 1)[-1] for call in FakeAsyncClient.calls], [
            "crm.company.list",
            "crm.company.update",
            "crm.deal.update",
        ])

        company_update = urllib.parse.parse_qs(FakeAsyncClient.calls[1][2]["content"].decode("utf-8"))
        self.assertEqual(company_update["id"], ["42"])
        self.assertEqual(company_update["fields[TITLE]"], ["Acme Development"])
        self.assertEqual(company_update["fields[WEB][0][VALUE]"], ["https://acme.example"])
        self.assertEqual(company_update["fields[WEB][0][VALUE_TYPE]"], ["WORK"])

        deal_update = urllib.parse.parse_qs(FakeAsyncClient.calls[2][2]["content"].decode("utf-8"))
        self.assertEqual(deal_update["id"], ["1753"])
        self.assertEqual(deal_update["fields[COMPANY_ID]"], ["42"])

    async def test_company_upsert_creates_missing_company(self) -> None:
        FakeAsyncClient.responses = {
            "crm.company.list": {"result": [], "total": 0},
            "crm.company.add": {"result": 77},
        }
        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_bitrix24(
                {"name": "bitrix24.companies.upsert"},
                {"params": {"title": "New Company", "website": "https://new.example"}},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["company_id"], "77")
        self.assertEqual([call[1].rsplit("/", 1)[-1] for call in FakeAsyncClient.calls], [
            "crm.company.list",
            "crm.company.list",
            "crm.company.list",
            "crm.company.add",
        ])

    async def test_sales_funnel_health_aggregates_deal_hygiene(self) -> None:
        FakeAsyncClient.responses = {
            "crm.status.list": {
                "result": [
                    {"STATUS_ID": "NEW", "NAME": "Новая", "SORT": 10},
                    {"STATUS_ID": "PROPOSAL", "NAME": "КП", "SORT": 40},
                ]
            },
            "crm.deal.list": {
                "result": [
                    {
                        "ID": "101",
                        "TITLE": "Зависшая сделка",
                        "STAGE_ID": "PROPOSAL",
                        "CATEGORY_ID": "0",
                        "CLOSED": "N",
                        "OPPORTUNITY": "0",
                        "CURRENCY_ID": "USD",
                        "ASSIGNED_BY_ID": "7",
                        "DATE_MODIFY": "2026-06-01T09:00:00+03:00",
                        "UF_CRM_NEXT_STEP": "",
                        "UF_CRM_PROPOSAL_LINK": "",
                    },
                    {
                        "ID": "102",
                        "TITLE": "Живая сделка",
                        "STAGE_ID": "NEW",
                        "CATEGORY_ID": "0",
                        "CLOSED": "N",
                        "OPPORTUNITY": "150000",
                        "CURRENCY_ID": "RUB",
                        "ASSIGNED_BY_ID": "8",
                        "DATE_MODIFY": "2026-06-15T09:00:00+03:00",
                        "UF_CRM_NEXT_STEP": "Созвониться",
                        "UF_CRM_PROPOSAL_LINK": "https://disk.example/proposal",
                    },
                ],
                "total": 2,
            },
            "user.get": {
                "result": [
                    {"ID": "7", "NAME": "Егор", "LAST_NAME": "Иванов", "EMAIL": "egor@example.com", "ACTIVE": True},
                    {"ID": "8", "NAME": "Саша", "LAST_NAME": "Петров", "EMAIL": "sasha@example.com", "ACTIVE": True},
                ]
            },
            "crm.activity.list": {
                "102": [
                    {
                        "ID": "900",
                        "OWNER_ID": "102",
                        "CREATED": "2026-06-15T10:00:00+03:00",
                        "LAST_UPDATED": "2026-06-15T10:05:00+03:00",
                        "DEADLINE": "2026-06-20T12:00:00+03:00",
                        "COMPLETED": "N",
                    }
                ]
            },
        }

        with (
            patch.dict(os.environ, {"BITRIX24_WEBHOOK_URL": "https://example.bitrix24.ru/rest/1/token"}),
            patch("gateway_mcp.backends.bitrix24.httpx.AsyncClient", FakeAsyncClient),
            patch("gateway_mcp.backends.bitrix24.datetime") as fake_datetime,
        ):
            from datetime import datetime, timezone

            fake_datetime.now.return_value = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)
            fake_datetime.fromisoformat.side_effect = datetime.fromisoformat
            result = await _call_bitrix24(
                {"name": "bitrix24.sales_funnel.health"},
                {"category_id": 0, "stale_days": 7, "require_next_step": True},
            )

        self.assertTrue(result["ok"])
        deals = result["data"]["deals"]
        self.assertEqual(result["data"]["summary"]["total_active"], 2)
        stuck = deals[0]
        self.assertEqual(stuck["id"], "101")
        self.assertEqual(stuck["responsible"]["name"], "Егор Иванов")
        self.assertIn("no_amount", stuck["hygiene_flags"])
        self.assertIn("no_next_step", stuck["hygiene_flags"])
        self.assertIn("stale", stuck["hygiene_flags"])
        self.assertIn("no_activity", stuck["hygiene_flags"])
        self.assertIn("late_stage_zero_amount", stuck["hygiene_flags"])
        self.assertIn("missing_proposal_link", stuck["hygiene_flags"])
        self.assertIn("wrong_currency", stuck["hygiene_flags"])
        self.assertTrue(stuck["suggested_nudge_text"].startswith("Проверьте сделку"))
        alive = deals[1]
        self.assertEqual(alive["hygiene_flags"], [])
        self.assertEqual(alive["next_step"], "Созвониться")
        self.assertEqual(alive["next_activity_date"], "2026-06-20T09:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
