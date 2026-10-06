import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError
from gateway_mcp.backends.notifications import _build_skill_update_message, _call_notifications


class FakeTelegramClient:
    def __init__(self) -> None:
        self.chat_id = None
        self.message_text = ""
        self.disconnected = False

    async def send_message(self, chat_id, message_text):
        self.chat_id = chat_id
        self.message_text = message_text
        return SimpleNamespace(
            id=42,
            chat_id=chat_id,
            sender_id=7,
            date=None,
            message=message_text,
        )

    async def disconnect(self) -> None:
        self.disconnected = True


class NotificationsBackendTests(unittest.IsolatedAsyncioTestCase):
    def test_builds_skill_update_message(self) -> None:
        message = _build_skill_update_message(
            {
                "skill": "metrics-autofill",
                "pack": "delivery-core",
                "summary": "Обновлены правила сводных отчетов Медиалогии.",
                "mr_url": "https://gitlab.example/mr/54",
                "source_agent": "Codex",
            }
        )

        self.assertIn("Обновился скилл: metrics-autofill", message)
        self.assertIn("Пак: delivery-core", message)
        self.assertIn("Что изменилось: Обновлены правила сводных отчетов Медиалогии.", message)
        self.assertIn("Ссылка: https://gitlab.example/mr/54", message)
        self.assertIn("Отправитель: Codex", message)
        self.assertIn("Обновите плагины у себя", message)

    def test_minimal_message_requires_only_skill(self) -> None:
        message = _build_skill_update_message({"skill_name": "kp-draft"})

        self.assertIn("Обновился скилл: kp-draft", message)
        self.assertIn("Обновите плагины у себя", message)

    def test_requires_skill(self) -> None:
        with self.assertRaises(BackendRouteError):
            _build_skill_update_message({"summary": "no skill given"})

    async def test_sends_to_configured_skill_update_chat(self) -> None:
        fake_client = FakeTelegramClient()
        route = {"operation": "skill_update.send"}
        arguments = {
            "skill": "metrics-autofill",
            "pack": "delivery-core",
            "mr_url": "https://gitlab.example/mr/54",
        }

        with patch.dict(
            "os.environ",
            {"GATEWAY_COMIND_CHAT_ID": "-100123", "TELEGRAM_BOT_TOKEN": ""},
            clear=False,
        ):
            with patch(
                "gateway_mcp.backends.notifications._telegram_client",
                AsyncMock(return_value=fake_client),
            ):
                result = await _call_notifications(route, arguments)

        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "notifications")
        self.assertEqual(result["data"]["channel"], "skill_update")
        self.assertEqual(fake_client.chat_id, "-100123")
        self.assertIn("Обновился скилл: metrics-autofill", fake_client.message_text)
        self.assertTrue(fake_client.disconnected)

    async def test_honors_legacy_chat_env_name(self) -> None:
        fake_client = FakeTelegramClient()
        route = {"operation": "skill_update.send"}
        arguments = {"skill": "kp-draft"}

        with patch.dict(
            "os.environ",
            {
                "GATEWAY_COMIND_CHAT_ID": "",
                "GATEWAY_COMIND_MR_REVIEW_CHAT_ID": "-100456",
                "TELEGRAM_BOT_TOKEN": "",
            },
            clear=False,
        ):
            with patch(
                "gateway_mcp.backends.notifications._telegram_client",
                AsyncMock(return_value=fake_client),
            ):
                result = await _call_notifications(route, arguments)

        self.assertTrue(result["ok"])
        self.assertEqual(fake_client.chat_id, "-100456")

    async def test_requires_configured_chat(self) -> None:
        route = {"operation": "skill_update.send"}
        arguments = {"skill": "kp-draft"}

        with patch.dict(
            "os.environ",
            {
                "GATEWAY_COMIND_CHAT_ID": "",
                "GATEWAY_COMIND_MR_REVIEW_CHAT_ID": "",
                "TELEGRAM_COMIND_CHAT_ID": "",
            },
            clear=False,
        ):
            with self.assertRaises(BackendConfigError):
                await _call_notifications(route, arguments)

    async def test_rejects_unknown_operation(self) -> None:
        with self.assertRaises(BackendRouteError):
            await _call_notifications({"operation": "mr_review.send"}, {"skill": "kp-draft"})


if __name__ == "__main__":
    unittest.main()
