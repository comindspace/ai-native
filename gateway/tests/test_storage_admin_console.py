import unittest
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import storage_access_requests
from gateway_mcp.services import storage_admin_console as storage


class AdminConsoleStorageTests(unittest.TestCase):
    def test_user_queries_are_paginated_and_do_not_select_credentials(self):
        with patch.object(storage, "_rows", return_value=[]) as read:
            storage.admin_users_page(query="a' OR true", offset=25, limit=26)
        sql, params = read.call_args.args
        self.assertNotIn("a' OR true", sql)
        self.assertEqual(params, ("a' OR true", 26, 25))
        self.assertIn("limit %s offset %s", sql)
        self.assertNotIn("access_token", sql)
        self.assertNotIn("metadata", sql)
        self.assertNotIn("select *", sql)

    def test_grants_use_all_known_aliases_and_retain_expired_history(self):
        with patch.object(storage, "_rows", return_value=[]) as read:
            storage.admin_user_grants(
                {
                    "subject": "yandex:42",
                    "email": "E@X",
                    "login": "e",
                    "yandex_id": "42",
                },
                offset=25,
            )
        self.assertEqual(read.call_count, 3)
        for call in read.call_args_list:
            sql, params = call.args
            self.assertEqual(params, (["42", "e", "e@x", "yandex:42"], 26, 25))
            self.assertNotIn("revoked_at is null", sql)
            self.assertIn("subject_type = 'user'", sql)
            self.assertIn("expires_at", sql)

    def test_overview_counts_are_not_limited_samples(self):
        with patch.object(storage, "_rows", return_value=[{"users": 2000}]) as read:
            self.assertEqual(storage.admin_overview_counts()["users"], 2000)
        sql = read.call_args.args[0]
        self.assertNotIn("limit", sql)
        self.assertIn("interval '24 hours'", sql)

    def test_requests_offset_and_search_are_parameterized(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with (
            patch.object(
                storage_access_requests, "postgres_enabled", return_value=True
            ),
            patch.object(storage_access_requests, "ensure_schema"),
            patch.object(storage_access_requests, "_connect", return_value=connection),
        ):
            storage_access_requests.list_access_requests(
                status="pending", query="'unsafe", offset=25, limit=26
            )
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params, ["pending", "'unsafe", 26, 25])
        self.assertNotIn("'unsafe", sql)
        self.assertIn("order by created_at desc, id desc", sql)

    def test_missing_database_is_not_an_empty_directory(self):
        with (
            patch.object(storage, "postgres_enabled", return_value=False),
            self.assertRaises(RuntimeError),
        ):
            storage.admin_users_page()


if __name__ == "__main__":
    unittest.main()
