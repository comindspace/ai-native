import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

import gateway_mcp.backends.telegram as _telegram_module
from gateway_mcp.backends.common import BackendRouteError
from gateway_mcp.backends.telegram import _call_telegram, _serialize_telegram_media, _serialize_telegram_message


class FakeFile:
    def __init__(self, name="", mime_type="", size=0):
        self.name = name
        self.mime_type = mime_type
        self.size = size


def _make_message(msg_id=1, chat_id=100, text="hello", media=None, file=None, photo=None):
    return SimpleNamespace(
        id=msg_id,
        chat_id=chat_id,
        sender_id=7,
        date=None,
        message=text,
        media=media,
        file=file,
        photo=photo,
    )


class FakeTelegramClient:
    def __init__(self, messages=None, download_data=None):
        self._messages = messages or []
        self._download_data = download_data

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def disconnect(self):
        pass

    async def iter_messages(self, chat_id, **kwargs):
        for msg in self._messages:
            yield msg

    async def get_messages(self, chat_id, ids=None):
        for msg in self._messages:
            if msg.id == ids:
                return msg
        return None

    async def download_media(self, message, file=None):
        if self._download_data is None:
            return None
        return self._download_data

    async def send_message(self, chat_id, text):
        return _make_message(msg_id=99, chat_id=chat_id, text=text)

    async def iter_dialogs(self, limit=50):
        return
        yield


_TELEGRAM_ENV = {
    "TELEGRAM_API_ID": "12345",
    "TELEGRAM_API_HASH": "testhash",
    "TELEGRAM_SESSION_STRING": "test-session",
}


class SerializeTelegramMessageTests(unittest.TestCase):
    def test_message_without_media_has_no_media_key(self):
        msg = _make_message(media=None)
        result = _serialize_telegram_message(msg)
        self.assertNotIn("media", result)
        self.assertEqual(result["text"], "hello")

    def test_message_with_document_media(self):
        msg = _make_message(
            media=SimpleNamespace(),
            file=FakeFile(name="proposal.pdf", mime_type="application/pdf", size=2048),
        )
        result = _serialize_telegram_message(msg)
        self.assertIn("media", result)
        self.assertEqual(result["media"]["type"], "document")
        self.assertEqual(result["media"]["file_name"], "proposal.pdf")
        self.assertEqual(result["media"]["mime_type"], "application/pdf")
        self.assertEqual(result["media"]["size"], 2048)
        self.assertTrue(result["media"]["has_file"])

    def test_message_with_photo_media(self):
        msg = _make_message(
            media=SimpleNamespace(),
            file=FakeFile(name="image.jpg", mime_type="image/jpeg", size=1024),
            photo=SimpleNamespace(),
        )
        result = _serialize_telegram_message(msg)
        self.assertEqual(result["media"]["type"], "photo")

    def test_media_without_file_object(self):
        msg = _make_message(media=SimpleNamespace(), file=None)
        result = _serialize_telegram_media(msg)
        self.assertIsNotNone(result)
        self.assertFalse(result["has_file"])

    def test_no_media_returns_none(self):
        msg = _make_message(media=None)
        self.assertIsNone(_serialize_telegram_media(msg))


class DownloadFileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_env = {key: os.environ.get(key) for key in _TELEGRAM_ENV}
        os.environ.update(_TELEGRAM_ENV)

    def tearDown(self):
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    async def test_download_file_returns_base64_content(self):
        raw = b"%PDF-1.4 test"
        msg = _make_message(
            msg_id=55,
            media=SimpleNamespace(),
            file=FakeFile(name="doc.pdf", mime_type="application/pdf", size=len(raw)),
        )
        client = FakeTelegramClient(messages=[msg], download_data=raw)
        with patch.object(_telegram_module, "_telegram_client", new=AsyncMock(return_value=client)):
            result = await _call_telegram(
                {"operation": "download_file"},
                {"chat_id": 100, "message_id": 55},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["file_name"], "doc.pdf")
        self.assertEqual(result["data"]["mime_type"], "application/pdf")
        self.assertEqual(result["data"]["size"], len(raw))
        self.assertEqual(base64.b64decode(result["data"]["content_base64"]), raw)

    async def test_download_file_missing_chat_id(self):
        client = FakeTelegramClient()
        with patch.object(_telegram_module, "_telegram_client", new=AsyncMock(return_value=client)):
            with self.assertRaises(BackendRouteError) as ctx:
                await _call_telegram({"operation": "download_file"}, {"message_id": 1})
            self.assertIn("chat_id", str(ctx.exception))

    async def test_download_file_missing_message_id(self):
        client = FakeTelegramClient()
        with patch.object(_telegram_module, "_telegram_client", new=AsyncMock(return_value=client)):
            with self.assertRaises(BackendRouteError) as ctx:
                await _call_telegram({"operation": "download_file"}, {"chat_id": 100})
            self.assertIn("message_id", str(ctx.exception))

    async def test_download_file_message_not_found(self):
        client = FakeTelegramClient(messages=[])
        with patch.object(_telegram_module, "_telegram_client", new=AsyncMock(return_value=client)):
            with self.assertRaises(BackendRouteError) as ctx:
                await _call_telegram(
                    {"operation": "download_file"},
                    {"chat_id": 100, "message_id": 999},
                )
            self.assertIn("not found", str(ctx.exception))

    async def test_download_file_no_media(self):
        msg = _make_message(msg_id=55, media=None)
        client = FakeTelegramClient(messages=[msg])
        with patch.object(_telegram_module, "_telegram_client", new=AsyncMock(return_value=client)):
            with self.assertRaises(BackendRouteError) as ctx:
                await _call_telegram(
                    {"operation": "download_file"},
                    {"chat_id": 100, "message_id": 55},
                )
            self.assertIn("no downloadable file", str(ctx.exception))

    async def test_get_messages_includes_media_info(self):
        msg = _make_message(
            msg_id=10,
            text="see attached",
            media=SimpleNamespace(),
            file=FakeFile(name="report.pdf", mime_type="application/pdf", size=5000),
        )
        client = FakeTelegramClient(messages=[msg])
        with patch.object(_telegram_module, "_telegram_client", new=AsyncMock(return_value=client)):
            result = await _call_telegram(
                {"operation": "get_messages"},
                {"chat_id": 100, "limit": 5},
            )
        self.assertTrue(result["ok"])
        messages = result["data"]["messages"]
        self.assertEqual(len(messages), 1)
        self.assertIn("media", messages[0])
        self.assertEqual(messages[0]["media"]["file_name"], "report.pdf")


if __name__ == "__main__":
    unittest.main()
