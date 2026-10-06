import os
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError
from gateway_mcp.backends.wordstat import _call_wordstat


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
    post_responses = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url, **kwargs):
        FakeAsyncClient.calls.append(("POST", url, kwargs))
        return FakeResponse(
            FakeAsyncClient.post_responses.pop(0) if FakeAsyncClient.post_responses else {}
        )


def _env(**overrides):
    values = {
        "GATEWAY_WORDSTAT_API_KEY": "test-api-key",
        "GATEWAY_WORDSTAT_FOLDER_ID": "",
        "GATEWAY_WORDSTAT_API_BASE_URL": "https://searchapi.test",
        "GATEWAY_UPSTREAM_TIMEOUT_SECONDS": "60",
    }
    values.update(overrides)
    return values


class WordstatBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.calls = []
        FakeAsyncClient.post_responses = []

    async def test_missing_api_key(self) -> None:
        with patch.dict(os.environ, _env(GATEWAY_WORDSTAT_API_KEY=""), clear=False):
            with self.assertRaises(BackendConfigError):
                await _call_wordstat(
                    {"name": "wordstat.top_requests", "operation": "top_requests"},
                    {"phrase": "comind"},
                )

    async def test_top_requests_builds_body(self) -> None:
        FakeAsyncClient.post_responses = [{"totalCount": "91"}]
        route = {"name": "wordstat.top_requests", "operation": "top_requests"}
        with patch.dict(os.environ, _env(), clear=False), patch(
            "gateway_mcp.backends.wordstat.httpx.AsyncClient", FakeAsyncClient
        ):
            result = await _call_wordstat(
                route,
                {"phrase": "comind", "num_phrases": "10", "regions": "213, 1", "devices": "desktop"},
            )
        self.assertTrue(result["ok"])
        method, url, kwargs = FakeAsyncClient.calls[-1]
        self.assertEqual(url, "https://searchapi.test/v2/wordstat/topRequests")
        self.assertEqual(kwargs["headers"]["Authorization"], "Api-Key test-api-key")
        self.assertEqual(kwargs["json"]["phrase"], "comind")
        self.assertEqual(kwargs["json"]["numPhrases"], 10)
        self.assertEqual(kwargs["json"]["regions"], ["213", "1"])
        self.assertEqual(kwargs["json"]["devices"], ["DEVICE_DESKTOP"])
        self.assertEqual(result["data"], {"totalCount": "91"})

    async def test_top_requests_requires_phrase(self) -> None:
        with patch.dict(os.environ, _env(), clear=False):
            with self.assertRaises(BackendRouteError):
                await _call_wordstat({"name": "wordstat.top_requests", "operation": "top_requests"}, {})

    async def test_dynamics_normalizes_period(self) -> None:
        FakeAsyncClient.post_responses = [{}]
        route = {"name": "wordstat.dynamics", "operation": "dynamics"}
        with patch.dict(os.environ, _env(), clear=False), patch(
            "gateway_mcp.backends.wordstat.httpx.AsyncClient", FakeAsyncClient
        ):
            await _call_wordstat(
                route, {"phrase": "ai native", "period": "monthly", "from_date": "2026-07-31"}
            )
        _, _, kwargs = FakeAsyncClient.calls[-1]
        self.assertEqual(kwargs["json"]["period"], "PERIOD_MONTHLY")
        self.assertEqual(kwargs["json"]["fromDate"], "2026-07-31")

    async def test_dynamics_rejects_bad_period(self) -> None:
        with patch.dict(os.environ, _env(), clear=False):
            with self.assertRaises(BackendRouteError):
                await _call_wordstat(
                    {"name": "wordstat.dynamics", "operation": "dynamics"},
                    {"phrase": "ai native", "period": "yearly", "from_date": "2026-07-31"},
                )

    async def test_dynamics_requires_from_date(self) -> None:
        with patch.dict(os.environ, _env(), clear=False):
            with self.assertRaises(BackendRouteError):
                await _call_wordstat(
                    {"name": "wordstat.dynamics", "operation": "dynamics"},
                    {"phrase": "ai native", "period": "monthly"},
                )

    async def test_folder_id_from_env_and_args(self) -> None:
        FakeAsyncClient.post_responses = [{}]
        route = {"name": "wordstat.regions_tree", "operation": "regions_tree"}
        with patch.dict(os.environ, _env(GATEWAY_WORDSTAT_FOLDER_ID="folder-env"), clear=False), patch(
            "gateway_mcp.backends.wordstat.httpx.AsyncClient", FakeAsyncClient
        ):
            await _call_wordstat(route, {})
        _, _, kwargs = FakeAsyncClient.calls[-1]
        self.assertEqual(kwargs["json"]["folderId"], "folder-env")

        FakeAsyncClient.post_responses = [{}]
        with patch.dict(os.environ, _env(), clear=False), patch(
            "gateway_mcp.backends.wordstat.httpx.AsyncClient", FakeAsyncClient
        ):
            await _call_wordstat(route, {"folder_id": "folder-args"})
        _, _, kwargs = FakeAsyncClient.calls[-1]
        self.assertEqual(kwargs["json"]["folderId"], "folder-args")

    async def test_unsupported_operation(self) -> None:
        with patch.dict(os.environ, _env(), clear=False):
            with self.assertRaises(BackendRouteError):
                await _call_wordstat({"name": "wordstat.other", "operation": "other"}, {})


if __name__ == "__main__":
    unittest.main()
