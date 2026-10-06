import asyncio
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from support import install_dependency_stubs

install_dependency_stubs()


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods, include_in_schema=False):
        def decorator(func):
            self.routes[path] = func
            return func

        return decorator


class FakeRequest:
    def __init__(self, query_params=None) -> None:
        self.headers = {}
        self.cookies = {}
        self.query_params = query_params or {}


class FakePostRequest(FakeRequest):
    def __init__(self, body: str, csrf: str = "") -> None:
        super().__init__()
        self._body = body.encode()
        self.cookies = {"gateway_business_csrf": csrf} if csrf else {}

    async def body(self) -> bytes:
        return self._body


def response_text(response) -> str:
    return (
        response.body.decode("utf-8")
        if isinstance(response.body, bytes)
        else response.body
    )


class AdminMetricsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        from gateway_mcp.routes.admin_metrics import register_admin_metrics_routes

        self.mcp = FakeMcp()
        register_admin_metrics_routes(self.mcp)

    def test_requires_administrator(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        with patch(
            "gateway_mcp.routes.admin_metrics.web_actor",
            return_value=GatewayActor(subject="user", scopes=("factory:read",)),
        ):
            response = asyncio.run(self.mcp.routes["/admin/metrics"](FakeRequest()))
        self.assertEqual(response.status_code, 403)

    def test_old_business_sections_show_gateway_without_reading_crm(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        for section in (None, "business", "sales", "projects", "agents", "unknown"):
            with (
                patch(
                    "gateway_mcp.routes.admin_metrics.web_actor",
                    return_value=GatewayActor(
                        subject="admin", scopes=("access:admin",)
                    ),
                ),
                patch(
                    "gateway_mcp.routes.admin_metrics._gateway",
                    new_callable=AsyncMock,
                    return_value="Gateway data",
                ) as gateway,
                patch(
                    "gateway_mcp.routes.admin_metrics._business", new_callable=AsyncMock
                ) as business,
                patch(
                    "gateway_mcp.routes.admin_metrics._sales", new_callable=AsyncMock
                ) as sales,
                patch(
                    "gateway_mcp.routes.admin_metrics._projects", new_callable=AsyncMock
                ) as projects,
                patch(
                    "gateway_mcp.routes.admin_metrics._agents", new_callable=AsyncMock
                ) as agents,
            ):
                response = asyncio.run(
                    self.mcp.routes["/admin/metrics"](FakeRequest({"section": section}))
                )
            self.assertEqual(response.status_code, 200)
            self.assertIn("Состояние шлюза", response_text(response))
            for retired in (
                "Экономика",
                "Продажи",
                "Исполнение",
                "Договорный портфель",
            ):
                self.assertNotIn(retired, response_text(response))
            gateway.assert_awaited_once_with(30)
            for source in (business, sales, projects, agents):
                source.assert_not_awaited()

    def test_business_write_requires_csrf(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        with patch(
            "gateway_mcp.routes.admin_metrics.web_actor",
            return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
        ):
            response = asyncio.run(
                self.mcp.routes["/admin/metrics/business"](
                    FakePostRequest(
                        "action=rate&tracker_project_id=101&tracker_user_id=u1&hourly_rate_rub=1800"
                    )
                )
            )
        self.assertEqual(response.status_code, 403)

    def test_contract_link_validates_sources_and_records_confirmed_amount(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        with (
            patch(
                "gateway_mcp.routes.admin_metrics.web_actor",
                return_value=GatewayActor(
                    subject="admin",
                    scopes=("access:admin", "tracker:read", "bitrix24:read"),
                ),
            ),
            patch(
                "gateway_mcp.routes.admin_metrics.tracker_projects_snapshot",
                new_callable=AsyncMock,
                return_value={"projects": [{"short_id": "101"}]},
            ),
            patch(
                "gateway_mcp.routes.admin_metrics.crm_deal_amount",
                new_callable=AsyncMock,
                return_value={"ID": "42", "OPPORTUNITY": "10000", "CURRENCY_ID": "RUB"},
            ),
            patch("gateway_mcp.routes.admin_metrics.save_project_link") as save,
            patch("gateway_mcp.routes.admin_metrics.audit_event"),
        ):
            response = asyncio.run(
                self.mcp.routes["/admin/metrics/business"](
                    FakePostRequest(
                        "csrf=good&action=link&tracker_project_id=101&crm_deal_id=42&contract_confirmed=1",
                        csrf="good",
                    )
                )
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(save.call_args.kwargs["amount"], Decimal(10000))
        self.assertTrue(save.call_args.kwargs["confirmed"])

    def test_business_rate_does_not_accept_non_finite_values(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        with (
            patch(
                "gateway_mcp.routes.admin_metrics.web_actor",
                return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
            ),
            patch("gateway_mcp.routes.admin_metrics.save_cost_rate") as save,
        ):
            response = asyncio.run(
                self.mcp.routes["/admin/metrics/business"](
                    FakePostRequest(
                        "csrf=good&action=rate&tracker_project_id=101&tracker_user_id=u1&hourly_rate_rub=NaN",
                        csrf="good",
                    )
                )
            )
        self.assertEqual(response.status_code, 400)
        save.assert_not_called()

    def test_unconfirmed_link_allows_empty_crm_amount(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        with (
            patch(
                "gateway_mcp.routes.admin_metrics.web_actor",
                return_value=GatewayActor(
                    subject="admin",
                    scopes=("access:admin", "tracker:read", "bitrix24:read"),
                ),
            ),
            patch(
                "gateway_mcp.routes.admin_metrics.tracker_projects_snapshot",
                new_callable=AsyncMock,
                return_value={"projects": [{"short_id": "101"}]},
            ),
            patch(
                "gateway_mcp.routes.admin_metrics.crm_deal_amount",
                new_callable=AsyncMock,
                return_value={"ID": "42", "OPPORTUNITY": "", "CURRENCY_ID": "RUB"},
            ),
            patch("gateway_mcp.routes.admin_metrics.save_project_link") as save,
            patch("gateway_mcp.routes.admin_metrics.audit_event"),
        ):
            response = asyncio.run(
                self.mcp.routes["/admin/metrics/business"](
                    FakePostRequest(
                        "csrf=good&action=link&tracker_project_id=101&crm_deal_id=42",
                        csrf="good",
                    )
                )
            )
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(save.call_args.kwargs["amount"])
        self.assertFalse(save.call_args.kwargs["confirmed"])

    def test_business_link_and_rate_can_be_removed(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        with (
            patch(
                "gateway_mcp.routes.admin_metrics.web_actor",
                return_value=GatewayActor(subject="admin", scopes=("access:admin",)),
            ),
            patch("gateway_mcp.routes.admin_metrics.delete_project_link") as unlink,
            patch("gateway_mcp.routes.admin_metrics.delete_cost_rate") as remove_rate,
            patch("gateway_mcp.routes.admin_metrics.audit_event"),
        ):
            unlink_response = asyncio.run(
                self.mcp.routes["/admin/metrics/business"](
                    FakePostRequest(
                        "csrf=good&action=unlink&tracker_project_id=101",
                        csrf="good",
                    )
                )
            )
            rate_response = asyncio.run(
                self.mcp.routes["/admin/metrics/business"](
                    FakePostRequest(
                        "csrf=good&action=rate_delete&tracker_project_id=101&tracker_user_id=u1",
                        csrf="good",
                    )
                )
            )
        self.assertEqual(unlink_response.status_code, 303)
        self.assertEqual(rate_response.status_code, 303)
        unlink.assert_called_once_with(project_id="101")
        remove_rate.assert_called_once_with(user_id="u1")

    def test_project_selector_uses_registered_projects(self) -> None:
        from gateway_mcp.routes.admin_metrics import _project_control

        with patch(
            "gateway_mcp.routes.admin_metrics.load_factory_project_registry",
            return_value={
                "projects": [{"project_id": "acme", "name": "Acme"}]
            },
        ):
            control = _project_control("acme")
        self.assertIn('<select name="project_id">', control)
        self.assertIn('value="acme" selected', control)
        self.assertIn("Acme", control)

    def test_tracker_selector_uses_tracker_projects(self) -> None:
        from gateway_mcp.routes.admin_metrics import _tracker_project_control

        control = _tracker_project_control(
            "101", {"projects": [{"short_id": "101", "name": "Acme"}]}
        )
        self.assertIn('<select name="tracker_project_id">', control)
        self.assertIn('value="101" selected', control)
        self.assertIn("Acme", control)

    def test_tracker_project_registry_snapshot_uses_oauth_and_pagination(self) -> None:
        from gateway_mcp.services.admin_metrics import tracker_projects_snapshot

        responses = [
            {
                "ok": True,
                "data": {
                    "hits": 2,
                    "pages": 2,
                    "values": [
                        {
                            "id": "entity-1",
                            "shortId": 101,
                            "fields": {
                                "summary": "Acme",
                                "entityStatus": "at_risk",
                                "end": "2026-09-30",
                                "lead": {"display": "PM"},
                            },
                        }
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "hits": 2,
                    "pages": 2,
                    "values": [
                        {"id": "entity-2", "shortId": 80, "fields": {"summary": "Contoso"}}
                    ],
                },
            },
        ]
        with patch(
            "gateway_mcp.services.admin_metrics._call_tracker",
            new_callable=AsyncMock,
            side_effect=responses,
        ) as call:
            snapshot = asyncio.run(tracker_projects_snapshot(actor_subject="admin:1"))
        self.assertEqual(snapshot["total"], 2)
        self.assertEqual(snapshot["sampled"], 2)
        self.assertFalse(snapshot["limited"])
        self.assertEqual(snapshot["projects"][0]["short_id"], "101")
        self.assertEqual(snapshot["projects"][0]["lead"], "PM")
        self.assertEqual(call.await_count, 2)
        self.assertEqual(call.await_args_list[0].kwargs["actor_subject"], "admin:1")

    def test_backend_error_does_not_render_secret(self) -> None:
        from gateway_mcp.services.policy import GatewayActor

        for error in (
            RuntimeError("token=must-not-render"),
            ValueError("token=must-not-render"),
        ):
            with (
                patch(
                    "gateway_mcp.routes.admin_metrics.web_actor",
                    return_value=GatewayActor(
                        subject="admin", scopes=("access:admin", "bitrix24:read")
                    ),
                ),
                patch(
                    "gateway_mcp.routes.admin_metrics.gateway_snapshot",
                    side_effect=error,
                ),
            ):
                response = asyncio.run(
                    self.mcp.routes["/admin/metrics"](
                        FakeRequest({"section": "gateway"})
                    )
                )
            self.assertNotIn("must-not-render", response_text(response))

    def test_tracker_web_request_uses_administrator_oauth(self) -> None:
        from gateway_mcp.backends.tracker import _tracker_headers

        with (
            patch(
                "gateway_mcp.services.storage.get_user_oauth_token",
                return_value={"access_token": "private-token"},
            ) as credential,
            patch(
                "gateway_mcp.backends.tracker.integration_value",
                side_effect=lambda _, key: "123" if key == "TRACKER_ORG_ID" else "",
            ),
        ):
            headers = _tracker_headers("yandex:admin")
        credential.assert_called_once_with("yandex", "yandex:admin")
        self.assertEqual(headers["Authorization"], "OAuth private-token")
        self.assertEqual(headers["X-Org-ID"], "123")


class AdminMetricsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracker_counts_deadlines_across_pages(self) -> None:
        from gateway_mcp.services.admin_metrics import tracker_snapshot

        now = datetime.now(ZoneInfo("Europe/Moscow"))
        old = (now - timedelta(days=2)).date().isoformat()
        soon = (now + timedelta(days=3)).date().isoformat()
        page_one = [
            {"key": f"PM-{index}", "statusType": {"key": "resolved"}}
            for index in range(100)
        ]
        page_two = [
            {"key": "PM-101", "deadline": old, "statusType": {"key": "open"}},
            {"key": "PM-102", "deadline": soon, "statusType": {"key": "paused"}},
        ]
        calls = []

        async def fake_tracker(route, arguments, *, actor_subject):
            calls.append((arguments, actor_subject))
            return {
                "ok": True,
                "data": page_one if arguments["page"] == 1 else page_two,
                "total_count": "102",
            }

        with (
            patch(
                "gateway_mcp.services.admin_metrics._route",
                return_value={"name": "tracker.issues.search"},
            ),
            patch(
                "gateway_mcp.services.admin_metrics._call_tracker",
                side_effect=fake_tracker,
            ),
        ):
            result = await tracker_snapshot(
                actor_subject="admin", tracker_project_id="101"
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0]["body"], {"filter": {"project": "101"}})
        self.assertEqual(result["total"], 102)
        self.assertEqual(result["open"], 2)
        self.assertEqual(result["overdue"], 1)
        self.assertEqual(result["due_soon"], 1)
        self.assertEqual(result["paused"], 1)
        self.assertFalse(result["limited"])

    async def test_sales_paginates_and_keeps_currency_separate(self) -> None:
        from gateway_mcp.services.admin_metrics import sales_snapshot

        active = [
            {
                "ID": str(index),
                "STAGE_ID": "NEW",
                "OPPORTUNITY": "100",
                "CURRENCY_ID": "RUB",
                "UF_CRM_NEXT_STEP": "Позвонить",
            }
            for index in range(50)
        ]
        last = [
            {
                "ID": "50",
                "STAGE_ID": "NEW",
                "OPPORTUNITY": "20",
                "CURRENCY_ID": "USD",
                "UF_CRM_NEXT_STEP": "",
                "DATE_MODIFY": "2020-01-01T00:00:00+00:00",
            }
        ]
        starts = []

        async def fake_bitrix(name, arguments):
            if name == "bitrix24.deals.fields":
                return {"result": {"UF_CRM_NEXT_STEP": {"title": "Next step"}}}
            if name == "bitrix24.statuses.list":
                return {"result": [{"STATUS_ID": "NEW", "NAME": "Новая"}]}
            params = arguments["params"]
            if ">=DATE_CREATE" in params["filter"]:
                return {"result": [], "total": 8}
            starts.append(params["start"])
            return {
                "result": active if params["start"] == 0 else last,
                "total": 51,
                "next": 50 if params["start"] == 0 else None,
            }

        with patch(
            "gateway_mcp.services.admin_metrics._bitrix", side_effect=fake_bitrix
        ):
            result = await sales_snapshot(category_id="0", days=30, stale_days=7)
        self.assertEqual(starts, [0, 50])
        self.assertEqual(result["total_active"], 51)
        self.assertEqual(result["sampled"], 51)
        self.assertEqual(result["new_deals"], 8)
        self.assertEqual(result["stale"], 1)
        self.assertEqual(result["no_next_step"], 1)
        self.assertEqual(result["currency_amounts"]["RUB"], Decimal(5000))
        self.assertEqual(result["currency_amounts"]["USD"], Decimal(20))
        self.assertEqual(result["stale_amounts"], {"USD": Decimal(20)})
        self.assertEqual(result["attention"][0]["id"], "50")
        self.assertEqual(
            result["attention"][0]["reasons"],
            ["Нет обновлений 7 дней", "Не указан следующий шаг"],
        )


if __name__ == "__main__":
    unittest.main()
