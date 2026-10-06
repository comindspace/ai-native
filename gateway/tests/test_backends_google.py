import base64
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.google import _call_google


class FakeResponse:
    status_code = 200
    is_success = True
    text = ""

    def __init__(self, payload=None, *, content: bytes = b"", headers=None) -> None:
        self.payload = payload if payload is not None else {}
        self.content = content
        self.headers = headers or {}
        self.text = "" if payload is not None else content.decode("utf-8", errors="replace")

    def json(self):
        return self.payload


class FakeAsyncClient:
    calls = []
    response = FakeResponse({"ok": True})

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class GoogleBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.calls = []
        FakeAsyncClient.response = FakeResponse({"ok": True})

    async def test_sheets_range_path_is_url_encoded(self) -> None:
        route = {
            "backend": "google-sheets",
            "transport": "google-rest",
            "google_api": "sheets",
            "http_method": "GET",
            "path": "{spreadsheet_id}/values/{range}",
            "path_args": ["spreadsheet_id", "range"],
            "query_args": ["valueRenderOption"],
        }

        with (
            patch("gateway_mcp.backends.google._google_access_token", return_value="access-token"),
            patch("gateway_mcp.backends.google.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_google(
                route,
                {
                    "spreadsheet_id": "sheet-1",
                    "range": "Rates Sheet!A1:B2",
                    "valueRenderOption": "UNFORMATTED_VALUE",
                },
            )

        self.assertTrue(result["ok"])
        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(
            url,
            "https://sheets.googleapis.com/v4/spreadsheets/sheet-1/values/Rates%20Sheet%21A1%3AB2",
        )
        self.assertEqual(kwargs["params"], {"valueRenderOption": "UNFORMATTED_VALUE"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer access-token")

    async def test_sheets_update_sends_body(self) -> None:
        route = {
            "backend": "google-sheets",
            "transport": "google-rest",
            "google_api": "sheets",
            "http_method": "PUT",
            "path": "{spreadsheet_id}/values/{range}",
            "path_args": ["spreadsheet_id", "range"],
            "query_args": ["valueInputOption"],
            "body_arg": "body",
        }
        body = {"range": "Sheet1!A1", "values": [["value"]]}

        with (
            patch("gateway_mcp.backends.google._google_access_token", return_value="access-token"),
            patch("gateway_mcp.backends.google.httpx.AsyncClient", FakeAsyncClient),
        ):
            await _call_google(
                route,
                {
                    "spreadsheet_id": "sheet-1",
                    "range": "Sheet1!A1",
                    "valueInputOption": "USER_ENTERED",
                    "body": body,
                },
            )

        _, _, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(kwargs["json"], body)
        self.assertEqual(kwargs["params"], {"valueInputOption": "USER_ENTERED"})

    async def test_drive_download_returns_base64_content(self) -> None:
        route = {
            "backend": "google-drive",
            "transport": "google-rest",
            "google_api": "drive",
            "http_method": "GET",
            "path": "files/{file_id}",
            "path_args": ["file_id"],
            "fixed_query": {"alt": "media"},
            "binary_response": True,
        }
        FakeAsyncClient.response = FakeResponse(None, content=b"hello", headers={"content-type": "text/plain"})

        with (
            patch("gateway_mcp.backends.google._google_access_token", return_value="access-token"),
            patch("gateway_mcp.backends.google.httpx.AsyncClient", FakeAsyncClient),
        ):
            result = await _call_google(route, {"file_id": "file-1"})

        self.assertTrue(result["ok"])
        self.assertEqual(FakeAsyncClient.calls[0][2]["params"], {"alt": "media"})
        self.assertEqual(result["data"]["content_base64"], base64.b64encode(b"hello").decode("ascii"))
        self.assertEqual(result["data"]["content_type"], "text/plain")
        self.assertEqual(result["data"]["size"], 5)

    async def test_drive_create_sends_metadata_body(self) -> None:
        route = {
            "backend": "google-drive",
            "transport": "google-rest",
            "google_api": "drive",
            "http_method": "POST",
            "path": "files",
            "query_args": ["fields"],
            "body_arg": "body",
        }
        body = {"name": "Project docs", "mimeType": "application/vnd.google-apps.folder"}

        with (
            patch("gateway_mcp.backends.google._google_access_token", return_value="access-token"),
            patch("gateway_mcp.backends.google.httpx.AsyncClient", FakeAsyncClient),
        ):
            await _call_google(route, {"fields": "id,name", "body": body})

        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://www.googleapis.com/drive/v3/files")
        self.assertEqual(kwargs["params"], {"fields": "id,name"})
        self.assertEqual(kwargs["json"], body)

    async def test_docs_batch_update_uses_docs_base_url(self) -> None:
        route = {
            "backend": "google-docs",
            "transport": "google-rest",
            "google_api": "docs",
            "http_method": "POST",
            "path": "documents/{document_id}:batchUpdate",
            "path_args": ["document_id"],
            "body_arg": "body",
        }
        body = {"requests": [{"insertText": {"location": {"index": 1}, "text": "Hello"}}]}

        with (
            patch("gateway_mcp.backends.google._google_access_token", return_value="access-token"),
            patch("gateway_mcp.backends.google.httpx.AsyncClient", FakeAsyncClient),
        ):
            await _call_google(route, {"document_id": "doc-1", "body": body})

        method, url, kwargs = FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://docs.googleapis.com/v1/documents/doc-1:batchUpdate")
        self.assertEqual(kwargs["json"], body)


if __name__ == "__main__":
    unittest.main()
