import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_platform.cursor_distribution import build_cursor_distribution
from agent_platform.plugins.gateway import write_gateway_plugin


class CursorDistributionTests(unittest.TestCase):
    def _create_source(self, root: Path) -> tuple[Path, Path]:
        plugins = root / "plugins"
        plugin = plugins / "company-core"
        manifest = plugin / ".cursor-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "company-core", "version": "1.2.3"}),
            encoding="utf-8",
        )
        skill = plugin / "skills" / "onboarding" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# Onboarding\n", encoding="utf-8")

        installers = root / "installers"
        installers.mkdir()
        (installers / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (installers / "install.ps1").write_text("Write-Host ok\n", encoding="utf-8")
        return plugins, installers

    def test_builds_deterministic_cursor_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins, installers = self._create_source(root)
            first = root / "first"
            second = root / "second"

            build_cursor_distribution(
                plugins, first, installers, "2026.09.10", clean=True
            )
            build_cursor_distribution(
                plugins, second, installers, "2026.09.10", clean=True
            )

            first_archive = first / "company-core-1.2.3.zip"
            second_archive = second / "company-core-1.2.3.zip"
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            self.assertEqual(
                hashlib.sha256(first_archive.read_bytes()).hexdigest(),
                hashlib.sha256((first / "company-core.zip").read_bytes()).hexdigest(),
            )
            with zipfile.ZipFile(first_archive) as bundle:
                self.assertIn(".cursor-plugin/plugin.json", bundle.namelist())
                self.assertIn("skills/onboarding/SKILL.md", bundle.namelist())

            latest = json.loads((first / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["platformRelease"], "2026.09.10")
            self.assertEqual(latest["plugins"][0]["name"], "company-core")
            self.assertEqual(latest["plugins"][0]["version"], "1.2.3")
            self.assertEqual(
                latest["plugins"][0]["installPath"],
                "~/.cursor/plugins/local/company-core",
            )

    def test_rejects_manifest_name_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins, installers = self._create_source(root)
            manifest = plugins / "company-core" / ".cursor-plugin" / "plugin.json"
            manifest.write_text(
                json.dumps({"name": "wrong-name", "version": "1.2.3"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                build_cursor_distribution(
                    plugins, root / "output", installers, "2026.09.10"
                )

    def test_gateway_cursor_config_uses_oauth_without_bearer_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "gateway-mcp"
            write_gateway_plugin(plugin_root, "2026.09.10")

            cursor_manifest = json.loads(
                (plugin_root / ".cursor-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            cursor_mcp = json.loads(
                (plugin_root / "cursor.mcp.json").read_text(encoding="utf-8")
            )
            self.assertEqual(cursor_manifest["mcpServers"], "./cursor.mcp.json")
            self.assertNotIn("configuration", cursor_manifest)
            self.assertEqual(
                cursor_mcp["mcpServers"]["gateway"]["url"],
                "https://gateway.example.com/mcp",
            )
            self.assertNotIn("headers", cursor_mcp["mcpServers"]["gateway"])


if __name__ == "__main__":
    unittest.main()
