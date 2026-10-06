import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.storage_work import (
    append_work_event_locked,
    claim_work_run,
    work_metrics,
)


class StorageWorkTests(unittest.TestCase):
    def test_claim_and_admission_share_one_commit_and_failure_rolls_back(self):
        for fail_insert, empty in [(False, False), (True, False), (False, True)]:
            with self.subTest(fail_insert=fail_insert, empty=empty):
                cursor = MagicMock()
                cursor.__enter__.return_value = cursor
                expiry = datetime(2026, 9, 17, 15, tzinfo=timezone.utc)
                cursor.fetchone.return_value = (
                    None
                    if empty
                    else {
                        "work_id": "work-1",
                        "lease_expires_at": expiry,
                    }
                )
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.__exit__.return_value = False
                connection.cursor.return_value = cursor

                def execute(sql, params, connection=connection, fail_insert=fail_insert):
                    connection.commit.assert_not_called()
                    if "insert into work_events" in sql and fail_insert:
                        raise RuntimeError("synthetic event insert failure")

                cursor.execute.side_effect = execute
                with (
                    patch("gateway_mcp.services.storage_work._require_postgres"),
                    patch("gateway_mcp.services.storage_work.ensure_schema"),
                    patch(
                        "gateway_mcp.services.storage_work._connect",
                        return_value=connection,
                    ) as connect,
                ):
                    if fail_insert:
                        with self.assertRaises(RuntimeError):
                            claim_work_run(claimed_by="same-worker", lease_seconds=900)
                        connection.commit.assert_not_called()
                        self.assertIs(
                            connection.__exit__.call_args.args[0], RuntimeError
                        )
                    else:
                        result = claim_work_run(
                            claimed_by="same-worker", lease_seconds=900
                        )
                        connection.commit.assert_called_once_with()
                        self.assertEqual(result is None, empty)
                connect.assert_called_once_with()
                self.assertEqual(cursor.execute.call_count, 1 if empty else 2)
                if not empty:
                    sql, params = cursor.execute.call_args.args
                    self.assertIn("'claimed'", sql)
                    self.assertEqual(params[:2], ("work-1", "same-worker"))
                    self.assertEqual(
                        json.loads(params[2]),
                        {
                            "lease_seconds": 900,
                            "lease_expires_at": str(expiry),
                        },
                    )

    def test_artifact_append_locks_work_before_reading_latest_event(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [
            {"work_id": "work-1", "project_id": "demo"},
            {"payload": {"sequence": 1, "digest": "a" * 64}},
            {"id": 2, "work_id": "work-1", "event_type": "artifact_manifest"},
        ]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor

        with (
            patch("gateway_mcp.services.storage_work._require_postgres"),
            patch("gateway_mcp.services.storage_work.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_work._connect", return_value=connection
            ),
        ):
            work, event = append_work_event_locked(
                work_id="work-1",
                actor_subject="service:factory",
                event_type="artifact_manifest",
                payload_factory=lambda latest: {"sequence": latest["sequence"] + 1},
            )

        statements = [
            str(call.args[0]).casefold() for call in cursor.execute.call_args_list
        ]
        self.assertIn("for update", statements[0])
        self.assertIn("order by id desc", statements[1])
        self.assertEqual(work["work_id"], "work-1")
        self.assertEqual(event["id"], 2)
        connection.commit.assert_called_once_with()

    def test_work_metrics_returns_blocked_rate_and_median_corrections(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = [
            {
                "execution_mode": "factory",
                "runs": 4,
                "accepted_runs": 2,
                "blocked_runs": 1,
                "blocked_rate": 0.25,
                "avg_correction_rounds": 1.5,
                "p50_correction_rounds": 1.0,
            }
        ]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor

        with (
            patch("gateway_mcp.services.storage_work._require_postgres"),
            patch("gateway_mcp.services.storage_work.ensure_schema"),
            patch(
                "gateway_mcp.services.storage_work._connect", return_value=connection
            ),
        ):
            rows = work_metrics(project_id="demo", days=30)

        statement, params = cursor.execute.call_args.args
        normalized_statement = " ".join(statement.split()).casefold()
        self.assertIn("as blocked_rate", normalized_statement)
        self.assertIn("order by correction_rounds", normalized_statement)
        self.assertIn("as p50_correction_rounds", normalized_statement)
        self.assertIn("avg(correction_rounds)", normalized_statement)
        self.assertEqual(params, [30, "demo", "demo", "demo", "demo"])
        self.assertEqual(rows[0]["blocked_rate"], 0.25)
        self.assertEqual(rows[0]["avg_correction_rounds"], 1.5)
        self.assertEqual(rows[0]["p50_correction_rounds"], 1.0)


if __name__ == "__main__":
    unittest.main()
