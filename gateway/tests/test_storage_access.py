import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql, params=None) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return []


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True


class StorageAccessTests(unittest.TestCase):
    def test_revoke_scope_casts_actor_for_postgres_concat(self) -> None:
        from gateway_mcp.services import storage_access

        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        with (
            patch("gateway_mcp.services.storage_access.postgres_enabled", return_value=True),
            patch("gateway_mcp.services.storage_access.ensure_schema"),
            patch("gateway_mcp.services.storage_access._connect", return_value=connection),
        ):
            storage_access.revoke_scope_grants(grant_id=42, actor_subject="admin@example.com")

        sql, params = cursor.calls[0]
        self.assertIn("%s::text", sql)
        self.assertEqual(params, ["admin@example.com", 42])
        self.assertTrue(connection.committed)

    def test_revoke_resource_casts_actor_for_postgres_concat(self) -> None:
        from gateway_mcp.services import storage_access

        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        with (
            patch("gateway_mcp.services.storage_access.postgres_enabled", return_value=True),
            patch("gateway_mcp.services.storage_access.ensure_schema"),
            patch("gateway_mcp.services.storage_access._connect", return_value=connection),
        ):
            storage_access.revoke_resource_grants(
                system="gitlab",
                resource_pattern="241",
                actor_subject="admin@example.com",
            )

        sql, params = cursor.calls[0]
        self.assertIn("%s::text", sql)
        self.assertEqual(params, ["admin@example.com", "gitlab", "241"])
        self.assertTrue(connection.committed)


if __name__ == "__main__":
    unittest.main()
