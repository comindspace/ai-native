import json
import tempfile
import unittest
from pathlib import Path

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.factory_project_registry import (
    find_project_by_id,
    find_project_by_tracker_project,
    load_factory_project_registry,
    queue_fallback_allowed,
    tracker_project_identity,
)


class FactoryProjectRegistryTests(unittest.TestCase):
    def test_load_and_match_tracker_project(self) -> None:
        payload = {
            "schema_version": "1.0",
            "queue_fallback": {"mode": "allowlist", "queues": ["LEGACY"]},
            "projects": [
                {
                    "project_id": "acme-claims",
                    "tracker_project_id": "292",
                    "tracker_project_name": "Acme Claims",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projects.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            registry = load_factory_project_registry(path)

        by_tracker = find_project_by_tracker_project(
            registry,
            {"id": "292", "name": "Acme Claims"},
        )
        self.assertEqual(by_tracker["project_id"], "acme-claims")
        self.assertEqual(find_project_by_id(registry, "ACME-CLAIMS"), by_tracker)
        self.assertTrue(queue_fallback_allowed(registry, "legacy"))
        self.assertFalse(queue_fallback_allowed(registry, "PM"))
        self.assertIsNone(
            find_project_by_tracker_project(
                registry,
                {"id": "999", "name": "Acme Claims"},
            )
        )

    def test_tracker_project_identity_handles_missing_and_primary_values(self) -> None:
        self.assertEqual(
            tracker_project_identity({}),
            {"id": "", "name": ""},
        )
        self.assertEqual(
            tracker_project_identity(
                {"project": {"primary": {"id": "292", "display": "Acme Claims"}}}
            ),
            {"id": "292", "name": "Acme Claims"},
        )
        self.assertEqual(
            tracker_project_identity(
                {"project": {"primary": {"shortId": 292, "name": "Acme"}}}
            ),
            {"id": "292", "name": "Acme"},
        )


if __name__ == "__main__":
    unittest.main()
