import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.cursor_obj


class StorageCredentialTests(unittest.TestCase):
    def test_service_actor_listing_uses_parameterized_like_pattern(self) -> None:
        from gateway_mcp.services import storage_credentials

        cursor = FakeCursor([{"subject": "service:hermes-salesbro"}])
        with (
            patch("gateway_mcp.services.storage_credentials.postgres_enabled", return_value=True),
            patch("gateway_mcp.services.storage_credentials.ensure_schema"),
            patch("gateway_mcp.services.storage_credentials._connect", return_value=FakeConnection(cursor)),
        ):
            subjects = storage_credentials.list_service_credential_actors()

        self.assertEqual(subjects, ["service:hermes-salesbro"])
        self.assertIn("actor_subject like %s", cursor.calls[0][0])
        self.assertNotIn("like 'service:%'", cursor.calls[0][0])
        self.assertEqual(cursor.calls[0][1], ("service:%", "service:%"))

    def test_service_token_listing_uses_parameterized_like_pattern(self) -> None:
        from gateway_mcp.services import storage_credentials

        cursor = FakeCursor([{"provider": "yandex", "actor_subject": "service:hermes-salesbro"}])
        with (
            patch("gateway_mcp.services.storage_credentials.postgres_enabled", return_value=True),
            patch("gateway_mcp.services.storage_credentials.ensure_schema"),
            patch("gateway_mcp.services.storage_credentials._connect", return_value=FakeConnection(cursor)),
        ):
            rows = storage_credentials.list_service_oauth_tokens("yandex")

        self.assertEqual(rows[0]["actor_subject"], "service:hermes-salesbro")
        self.assertIn("actor_subject like %s", cursor.calls[0][0])
        self.assertNotIn("like 'service:%'", cursor.calls[0][0])
        self.assertEqual(cursor.calls[0][1], ["service:%", "yandex"])


if __name__ == "__main__":
    unittest.main()
