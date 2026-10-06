import os
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError
from gateway_mcp.backends.metrika import _call_metrika
from gateway_mcp.backends.webmaster import _call_webmaster


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = ""

    def json(self):
        return self.payload


class FakeAsyncClient:
    calls = []
    get_responses = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def request(self, method, url, **kwargs):
        FakeAsyncClient.calls.append((method, url, kwargs))
        return FakeResponse(FakeAsyncClient.get_responses.pop(0) if FakeAsyncClient.get_responses else {})

    async def get(self, url, **kwargs):
        FakeAsyncClient.calls.append(("GET", url, kwargs))
        return FakeResponse(FakeAsyncClient.get_responses.pop(0) if FakeAsyncClient.get_responses else {})


def _env(**overrides):
    values = {
        "YANDEX_METRIKA_OAUTH_ACCESS_TOKEN": "",
        "YANDEX_WEBMASTER_OAUTH_ACCESS_TOKEN": "",
        "YANDEX_OAUTH_ACCESS_TOKEN": "",
        "GATEWAY_ALLOW_SERVER_YANDEX_TOKENS": "false",
    }
    values.update(overrides)
    return values


class MetrikaBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.calls = []
        FakeAsyncClient.get_responses = []

    async def test_missing_token_raises_config_error(self) -> None:
        with patch.dict(os.environ, _env()):
            with self.assertRaises(BackendConfigError):
                await _call_metrika(
                    {"name": "metrika.stats.data", "http_method": "GET", "path": "stat/v1/data", "query_args": ["ids"]},
                    {"ids": "110936689"},
                )

    async def test_request_passes_params_and_oauth_header(self) -> None:
        route = {
            "name": "metrika.stats.data",
            "http_method": "GET",
            "path": "stat/v1/data",
            "query_args": ["ids", "metrics", "date1", "date2"],
        }
        arguments = {"ids": "110936689", "metrics": "ym:s:visits", "date1": "7_days_ago", "date2": "today"}
        with patch.dict(os.environ, _env(YANDEX_METRIKA_OAUTH_ACCESS_TOKEN="tok-metrika")):
            with patch("gateway_mcp.backends.metrika.httpx.AsyncClient", FakeAsyncClient):
                result = await _call_metrika(route, arguments)

        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "metrika")
        self.assertEqual(result["path"], "stat/v1/data")
        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api-metrika.yandex.ru/stat/v1/data")
        self.assertEqual(kwargs["headers"]["Authorization"], "OAuth tok-metrika")
        self.assertEqual(kwargs["params"]["ids"], "110936689")
        self.assertEqual(kwargs["params"]["metrics"], "ym:s:visits")

    async def test_formats_path_arguments(self) -> None:
        route = {
            "name": "metrika.goals.list",
            "http_method": "GET",
            "path": "management/v1/counter/{counter_id}/goals",
            "path_args": ["counter_id"],
        }
        with patch.dict(os.environ, _env(YANDEX_METRIKA_OAUTH_ACCESS_TOKEN="tok")):
            with patch("gateway_mcp.backends.metrika.httpx.AsyncClient", FakeAsyncClient):
                await _call_metrika(route, {"counter_id": 110936932})

        _, url, _ = FakeAsyncClient.calls[0]
        self.assertEqual(url, "https://api-metrika.yandex.ru/management/v1/counter/110936932/goals")


class WebmasterBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.calls = []
        FakeAsyncClient.get_responses = []
        import gateway_mcp.backends.webmaster as webmaster_module

        webmaster_module._WEBMASTER_USER_ID.pop("user_id", None)

    async def test_missing_token_raises_config_error(self) -> None:
        with patch.dict(os.environ, _env()):
            with self.assertRaises(BackendConfigError):
                await _call_webmaster({"name": "webmaster.sites.list", "operation": "list_hosts"}, {})

    async def test_resolves_user_id_and_lists_hosts(self) -> None:
        FakeAsyncClient.get_responses = [
            {"user_id": 12345},
            {"hosts": [{"host_id": "https:example.com:443"}]},
        ]
        with patch.dict(os.environ, _env(YANDEX_METRIKA_OAUTH_ACCESS_TOKEN="tok-metrika")):
            with patch("gateway_mcp.backends.webmaster.httpx.AsyncClient", FakeAsyncClient):
                result = await _call_webmaster({"name": "webmaster.sites.list", "operation": "list_hosts"}, {})

        self.assertTrue(result["ok"])
        self.assertEqual(len(FakeAsyncClient.calls), 2)
        self.assertTrue(FakeAsyncClient.calls[0][1].endswith("/v4/user"))
        self.assertTrue(FakeAsyncClient.calls[1][1].endswith("/v4/user/12345/hosts"))
        self.assertEqual(result["data"]["hosts"][0]["host_id"], "https:example.com:443")

    async def test_uses_cached_user_id_on_second_call(self) -> None:
        FakeAsyncClient.get_responses = [
            {"user_id": 12345},
            {"hosts": []},
        ]
        with patch.dict(os.environ, _env(YANDEX_WEBMASTER_OAUTH_ACCESS_TOKEN="tok-webmaster")):
            with patch("gateway_mcp.backends.webmaster.httpx.AsyncClient", FakeAsyncClient):
                await _call_webmaster({"name": "webmaster.sites.list", "operation": "list_hosts"}, {})
                FakeAsyncClient.calls = []
                FakeAsyncClient.get_responses = [{"hosts": []}]
                await _call_webmaster({"name": "webmaster.sites.list", "operation": "list_hosts"}, {})

        self.assertEqual(len(FakeAsyncClient.calls), 1)
        self.assertTrue(FakeAsyncClient.calls[0][1].endswith("/v4/user/12345/hosts"))
        self.assertEqual(FakeAsyncClient.calls[0][2]["headers"]["Authorization"], "OAuth tok-webmaster")

    async def test_quotes_host_id_and_passes_query_args(self) -> None:
        FakeAsyncClient.get_responses = [
            {"user_id": 12345},
            {"queries": []},
        ]
        route = {
            "name": "webmaster.search-queries.popular",
            "operation": "search_queries_popular",
            "query_args": ["order_by", "limit"],
        }
        arguments = {"host_id": "https:example.com:443", "order_by": "TOTAL_SHOWS", "limit": 50}
        with patch.dict(os.environ, _env(YANDEX_METRIKA_OAUTH_ACCESS_TOKEN="tok")):
            with patch("gateway_mcp.backends.webmaster.httpx.AsyncClient", FakeAsyncClient):
                result = await _call_webmaster(route, arguments)

        self.assertTrue(result["ok"])
        _, url, kwargs = FakeAsyncClient.calls[-1]
        self.assertTrue(url.endswith("/v4/user/12345/hosts/https%3Aexample.com%3A443/search-queries/popular"))
        self.assertEqual(kwargs["params"]["order_by"], "TOTAL_SHOWS")
        self.assertEqual(kwargs["params"]["limit"], 50)

    async def test_host_routes_require_host_id(self) -> None:
        FakeAsyncClient.get_responses = [{"user_id": 12345}]
        with patch.dict(os.environ, _env(YANDEX_METRIKA_OAUTH_ACCESS_TOKEN="tok")):
            with patch("gateway_mcp.backends.webmaster.httpx.AsyncClient", FakeAsyncClient):
                with self.assertRaises(BackendRouteError):
                    await _call_webmaster(
                        {"name": "webmaster.host.summary", "operation": "host_summary"}, {}
                    )

    async def test_unresolved_user_id_raises_route_error(self) -> None:
        FakeAsyncClient.get_responses = [{"error": "unauthorized"}]
        with patch.dict(os.environ, _env(YANDEX_METRIKA_OAUTH_ACCESS_TOKEN="tok")):
            with patch("gateway_mcp.backends.webmaster.httpx.AsyncClient", FakeAsyncClient):
                with self.assertRaises(BackendRouteError):
                    await _call_webmaster({"name": "webmaster.sites.list", "operation": "list_hosts"}, {})


if __name__ == "__main__":
    unittest.main()
