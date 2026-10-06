import os
import unittest
from unittest.mock import patch

from tests.support import install_dependency_stubs


install_dependency_stubs()


class FakeResponse:
    def __init__(self, data=None, *, text="", status_code=200):
        self._data = data
        self.text = text
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class FakeAsyncClient:
    calls = []
    response = FakeResponse({"ok": True})

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class GitLabBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.calls = []
        FakeAsyncClient.response = FakeResponse({"ok": True})

    async def _call(self, route, arguments):
        from gateway_mcp.backends.gitlab import _call_gitlab

        with patch.dict(os.environ, {"GITLAB_API_BASE_URL": "https://gitlab.example/api/v4"}), patch(
            "gateway_mcp.backends.gitlab._gitlab_token", return_value="token"
        ), patch("gateway_mcp.backends.gitlab.httpx.AsyncClient", FakeAsyncClient):
            return await _call_gitlab(route, arguments)

    async def test_create_merge_request_note_posts_body(self) -> None:
        route = {
            "name": "gitlab.merge_request_notes.create",
            "http_method": "POST",
            "path": "projects/{project_id}/merge_requests/{merge_request_iid}/notes",
            "path_args": ["project_id", "merge_request_iid"],
            "body_arg": "body",
        }

        await self._call(route, {"project_id": "ai-factory/template", "merge_request_iid": 2, "body": {"body": "review"}})

        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://gitlab.example/api/v4/projects/ai-factory%2Ftemplate/merge_requests/2/notes")
        self.assertEqual(kwargs["json"], {"body": "review"})

    async def test_merge_request_merge_uses_put_and_body(self) -> None:
        route = {
            "name": "gitlab.merge_requests.merge",
            "http_method": "PUT",
            "path": "projects/{project_id}/merge_requests/{merge_request_iid}/merge",
            "path_args": ["project_id", "merge_request_iid"],
            "body_arg": "body",
        }

        await self._call(
            route,
            {
                "project_id": 242,
                "merge_request_iid": 2,
                "body": {"should_remove_source_branch": True, "merge_commit_message": "Merge !2"},
            },
        )

        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://gitlab.example/api/v4/projects/242/merge_requests/2/merge")
        self.assertEqual(kwargs["json"]["should_remove_source_branch"], True)

    async def test_pipeline_job_trace_returns_text(self) -> None:
        route = {
            "name": "gitlab.pipeline_jobs.trace",
            "http_method": "GET",
            "path": "projects/{project_id}/jobs/{job_id}/trace",
            "path_args": ["project_id", "job_id"],
        }
        FakeAsyncClient.response = FakeResponse(None, text="failed test log")

        result = await self._call(route, {"project_id": 242, "job_id": 17})

        self.assertEqual(result["data"], "failed test log")
        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://gitlab.example/api/v4/projects/242/jobs/17/trace")
        self.assertIsNone(kwargs["json"])

    async def test_merge_request_diffs_pass_query(self) -> None:
        route = {
            "name": "gitlab.merge_requests.diffs.list",
            "http_method": "GET",
            "path": "projects/{project_id}/merge_requests/{merge_request_iid}/diffs",
            "path_args": ["project_id", "merge_request_iid"],
            "query_args": ["page", "per_page", "unidiff"],
        }

        await self._call(route, {"project_id": 242, "merge_request_iid": 2, "page": 1, "per_page": 20, "unidiff": True})

        _, _, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(kwargs["params"], {"page": 1, "per_page": 20, "unidiff": True})


if __name__ == "__main__":
    unittest.main()
