import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.config import (
    factory_projects_file,
    resolve_configured_path,
    tools_file,
)
from gateway_mcp.services.company_indexes import _company_indexes_file
from gateway_mcp.services.policy import _policy_file


class ConfigPathTests(unittest.TestCase):
    def test_default_relative_config_prefers_working_directory(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "gateway-tools.json").write_text(
                '{"tools": []}', encoding="utf-8"
            )
            os.chdir(tmp_path)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(tools_file(), tmp_path / "gateway-tools.json")
            finally:
                os.chdir(original_cwd)

    def test_company_indexes_uses_shared_path_resolution(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "gateway-company-indexes.json").write_text(
                '{"indexes": []}', encoding="utf-8"
            )
            (tmp_path / "gateway-policy.json").write_text(
                '{"schema": 1}', encoding="utf-8"
            )
            os.chdir(tmp_path)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(
                        _company_indexes_file(),
                        tmp_path / "gateway-company-indexes.json",
                    )
                    self.assertEqual(_policy_file(), tmp_path / "gateway-policy.json")
            finally:
                os.chdir(original_cwd)

    def test_explicit_absolute_config_path_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.json"
            with patch.dict(os.environ, {"GATEWAY_TOOLS_FILE": str(path)}, clear=True):
                self.assertEqual(
                    resolve_configured_path("GATEWAY_TOOLS_FILE", "gateway-tools.json"),
                    path,
                )

    def test_factory_project_registry_uses_shared_path_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "projects.json"
            with patch.dict(
                os.environ, {"GATEWAY_FACTORY_PROJECTS_FILE": str(path)}, clear=True
            ):
                self.assertEqual(factory_projects_file(), path)


if __name__ == "__main__":
    unittest.main()
