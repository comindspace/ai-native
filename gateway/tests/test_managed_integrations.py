import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class ManagedIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from gateway_mcp.services.managed_integrations import (
            invalidate_integration_cache,
        )

        invalidate_integration_cache()

    def tearDown(self) -> None:
        from gateway_mcp.services.managed_integrations import (
            invalidate_integration_cache,
        )

        invalidate_integration_cache()

    def test_environment_is_used_when_no_managed_row_exists(self) -> None:
        from gateway_mcp.services import managed_integrations

        with (
            patch.object(
                managed_integrations, "get_service_connection", return_value=None
            ),
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-key"}, clear=False),
        ):
            value = managed_integrations.integration_value(
                "openrouter", "OPENROUTER_API_KEY"
            )
        self.assertEqual(value, "env-key")

    def test_active_managed_row_overrides_environment(self) -> None:
        from gateway_mcp.services import managed_integrations

        row = {
            "system": "openrouter",
            "state": "active",
            "expires_at": None,
            "payload": {"OPENROUTER_API_KEY": "managed-key"},
        }
        with (
            patch.object(
                managed_integrations, "get_service_connection", return_value=row
            ),
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-key"}, clear=False),
        ):
            value = managed_integrations.integration_value(
                "openrouter", "OPENROUTER_API_KEY"
            )
        self.assertEqual(value, "managed-key")

    def test_disabled_or_expired_row_blocks_environment_fallback(self) -> None:
        from gateway_mcp.services import managed_integrations

        rows = (
            {
                "state": "disabled",
                "expires_at": None,
                "payload": {"OPENROUTER_API_KEY": "managed"},
            },
            {
                "state": "active",
                "expires_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=1)
                ).isoformat(),
                "payload": {"OPENROUTER_API_KEY": "managed"},
            },
        )
        for row in rows:
            managed_integrations.invalidate_integration_cache()
            with (
                self.subTest(row=row),
                patch.object(
                    managed_integrations, "get_service_connection", return_value=row
                ),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-key"}, clear=False),
            ):
                value = managed_integrations.integration_value(
                    "openrouter", "OPENROUTER_API_KEY"
                )
                self.assertEqual(value, "")

    def test_save_preserves_blank_secret_and_rotates_supplied_value(self) -> None:
        from gateway_mcp.services import managed_integrations

        existing = {
            "payload": {
                "OPENROUTER_API_KEY": "old-key",
                "OPENROUTER_BASE_URL": "https://old.example/v1",
            }
        }
        with (
            patch.object(
                managed_integrations, "get_service_connection", return_value=existing
            ),
            patch.object(
                managed_integrations,
                "upsert_service_connection",
                return_value={"system": "openrouter", "version": 2},
            ) as save,
        ):
            managed_integrations.save_integration(
                "openrouter",
                values={"OPENROUTER_API_KEY": "new-key", "OPENROUTER_BASE_URL": ""},
                clear_fields=set(),
                updated_by="admin",
                expires_at=None,
            )
        self.assertEqual(
            save.call_args.kwargs["payload"],
            {
                "OPENROUTER_API_KEY": "new-key",
                "OPENROUTER_BASE_URL": "https://old.example/v1",
            },
        )

    def test_secret_display_never_returns_raw_value(self) -> None:
        from gateway_mcp.services import managed_integrations

        row = {
            "payload": {
                "BITRIX24_WEBHOOK_URL": "https://crm.example/rest/350/top-secret"
            }
        }
        field = managed_integrations.INTEGRATIONS["bitrix24"].fields[0]
        with patch.object(
            managed_integrations, "get_service_connection", return_value=row
        ):
            value = managed_integrations.safe_field_value("bitrix24", field)
        self.assertEqual(value, "https://crm.example/rest/350/***")
        self.assertNotIn("top-secret", value)


if __name__ == "__main__":
    unittest.main()
