import unittest

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.common import BackendRouteError
from gateway_mcp.backends.yonote import _build_yonote_body


class YonoteBackendTests(unittest.TestCase):
    def test_update_title_builds_database_transaction(self) -> None:
        body = _build_yonote_body(
            {"name": "yonote.database.rows.update_title"},
            {"database_id": "db-1", "row_id": "row-1", "title": "Alice"},
        )

        self.assertEqual(
            body,
            {
                "db-1": [
                    {
                        "path": "rows.row-1.title",
                        "op": "update",
                        "val": "Alice",
                    }
                ]
            },
        )

    def test_update_values_builds_database_transaction(self) -> None:
        values = {"field-1": {"v": 2, "from": "1990/06/27", "to": ""}}
        body = _build_yonote_body(
            {"name": "yonote.database.rows.update_values"},
            {"databaseId": "db-1", "rowId": "row-1", "values": values},
        )

        self.assertEqual(
            body,
            {
                "db-1": [
                    {
                        "path": "rows.row-1.values",
                        "op": "update",
                        "val": values,
                    }
                ]
            },
        )

    def test_update_values_accepts_single_field_value(self) -> None:
        body = _build_yonote_body(
            {"name": "yonote.database.rows.update_values"},
            {"parentDocumentId": "db-1", "id": "row-1", "field_id": "field-1", "value": "done"},
        )

        self.assertEqual(
            body,
            {
                "db-1": [
                    {
                        "path": "rows.row-1.values",
                        "op": "update",
                        "val": {"field-1": "done"},
                    }
                ]
            },
        )

    def test_raw_transaction_accepts_transactions_body(self) -> None:
        transactions = {"db-1": [{"path": "rows.row-1", "op": "remove", "val": None}]}

        body = _build_yonote_body(
            {"name": "yonote.database.transaction"},
            {"transactions": transactions},
        )

        self.assertEqual(body, transactions)

    def test_create_requires_row_object(self) -> None:
        with self.assertRaisesRegex(BackendRouteError, "row object"):
            _build_yonote_body(
                {"name": "yonote.database.rows.create"},
                {"database_id": "db-1", "row": "not-an-object"},
            )

    def test_delete_builds_database_transaction(self) -> None:
        body = _build_yonote_body(
            {"name": "yonote.database.rows.delete"},
            {"database_id": "db-1", "row_id": "row-1"},
        )

        self.assertEqual(
            body,
            {
                "db-1": [
                    {
                        "path": "rows.row-1",
                        "op": "remove",
                        "val": None,
                    }
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
