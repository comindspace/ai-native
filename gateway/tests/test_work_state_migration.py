import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkStateMigrationTests(unittest.TestCase):
    def test_database_enforces_terminal_order(self) -> None:
        migration = (ROOT / "migrations/0006_work_state_invariants.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("invalid work status transition", migration)
        self.assertIn("new.status = 'accepted'", migration)
        self.assertIn("new.completed_at is null", migration)
        self.assertIn("new.first_verified_at is null", migration)

    def test_metrics_accept_canonical_id_or_repository_path(self) -> None:
        source = (
            ROOT / "gateway_mcp/services/storage_work.py"
        ).read_text(encoding="utf-8")
        self.assertIn("project_id = %s or project_path = %s", source)
        self.assertIn("right(project_path, char_length(%s) + 1)", source)


if __name__ == "__main__":
    unittest.main()
