import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.caldav import _call_caldav
from gateway_mcp.backends.common import BackendConfigError


class CaldavBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_calendar_credential_returns_structured_error(self) -> None:
        with patch(
            "gateway_mcp.backends.caldav._caldav_user_credentials",
            side_effect=BackendConfigError("No per-user Yandex Calendar app password is configured."),
        ):
            result = await _call_caldav({"operation": "list_calendars"}, {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "credential_missing")
        self.assertEqual(result["credential_provider"], "yandex-caldav")
        self.assertEqual(result["credentials_url"], "/credentials")

    async def test_calls_caldav_sync_with_user_credentials(self) -> None:
        with (
            patch("gateway_mcp.backends.caldav._caldav_user_credentials", return_value=("user@example.com", "secret")),
            patch("gateway_mcp.backends.caldav._caldav_sync", return_value={"ok": True, "backend": "caldav"}) as sync,
        ):
            result = await _call_caldav({"operation": "list_calendars"}, {"limit": 1})

        self.assertEqual(result, {"ok": True, "backend": "caldav"})
        sync.assert_called_once_with("list_calendars", {"limit": 1}, "user@example.com", "secret")


if __name__ == "__main__":
    unittest.main()
