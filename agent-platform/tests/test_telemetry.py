from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_platform.telemetry import (
    TELEMETRY_MARKER,
    has_telemetry_contract,
    packed_skill_names,
    telemetry_contract_errors,
)


class TelemetryContractTests(unittest.TestCase):
    def test_contract_requires_marker_and_all_lifecycle_tools(self) -> None:
        complete = (
            f"{TELEMETRY_MARKER}\n"
            "gateway_telemetry_skill_started\n"
            "gateway_telemetry_skill_completed\n"
            "gateway_telemetry_skill_failed"
        )

        self.assertTrue(has_telemetry_contract(complete))
        self.assertFalse(has_telemetry_contract(complete.replace("_failed", "")))

    def test_packed_skill_names_are_unique_and_sorted(self) -> None:
        registry = {
            "packs": [
                {"skills": ["beta", "alpha"]},
                {"skills": ["alpha"]},
            ]
        }

        self.assertEqual(packed_skill_names(registry), ["alpha", "beta"])

    def test_validation_reports_only_existing_skills_without_contract(self) -> None:
        registry = {"packs": [{"skills": ["missing", "ready", "invalid"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            for skill in ("ready", "invalid"):
                (source / skill).mkdir()
            (source / "ready" / "SKILL.md").write_text(
                f"{TELEMETRY_MARKER}\n"
                "gateway_telemetry_skill_started\n"
                "gateway_telemetry_skill_completed\n"
                "gateway_telemetry_skill_failed",
                encoding="utf-8",
            )
            (source / "invalid" / "SKILL.md").write_text(
                "# No telemetry",
                encoding="utf-8",
            )

            errors = telemetry_contract_errors(source, registry)

        self.assertEqual(len(errors), 1)
        self.assertIn("invalid", errors[0])


if __name__ == "__main__":
    unittest.main()
