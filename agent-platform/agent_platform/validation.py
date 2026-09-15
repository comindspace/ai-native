from __future__ import annotations

import filecmp
import tempfile
from pathlib import Path
from typing import Any

from agent_platform.io import parse_frontmatter
from agent_platform.paths import GENERATED_PATHS, REPO_ROOT
from agent_platform.plugins.builder import build_plugins
from agent_platform.telemetry import telemetry_contract_errors


def compare_dirs(left: Path, right: Path) -> list[str]:
    if not left.exists() and not right.exists():
        return []
    if not left.exists():
        return [f"missing generated path: {left}"]
    if not right.exists():
        return [f"unexpected generated path absent from temp build: {right}"]

    diffs: list[str] = []
    comparison = filecmp.dircmp(left, right)
    for name in comparison.left_only:
        diffs.append(f"only in committed output: {left / name}")
    for name in comparison.right_only:
        diffs.append(f"only in rebuilt output: {right / name}")
    for name in comparison.common_files:
        if not _files_equal(left / name, right / name):
            diffs.append(f"content differs: {left / name}")
    for subdir in comparison.common_dirs:
        diffs.extend(compare_dirs(left / subdir, right / subdir))
    return diffs


def _files_equal(left: Path, right: Path) -> bool:
    left_bytes = left.read_bytes()
    right_bytes = right.read_bytes()
    if left_bytes == right_bytes:
        return True
    try:
        left_text = left_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        right_text = (
            right_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    except UnicodeDecodeError:
        return False
    return left_text == right_text


def skill_markdown_paths(root: Path) -> list[Path]:
    return [
        *sorted(root.glob("skills/*/SKILL.md")),
        *sorted(root.glob("plugins/*/skills/*/SKILL.md")),
    ]


def validate_skill_frontmatter(root: Path) -> list[str]:
    errors: list[str] = []
    for path in skill_markdown_paths(root):
        try:
            parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: invalid YAML front matter: {exc}")
    return errors


def validate_generated(source: Path, registry: dict[str, Any]) -> dict[str, Any]:
    frontmatter_errors = validate_skill_frontmatter(REPO_ROOT)
    telemetry_errors = telemetry_contract_errors(source, registry)
    if frontmatter_errors or telemetry_errors:
        return {
            "ok": False,
            "diffs": [],
            "frontmatterErrors": frontmatter_errors,
            "telemetryErrors": telemetry_errors,
        }

    with tempfile.TemporaryDirectory(prefix="agent-plugin-build-") as tmp:
        tmp_path = Path(tmp)
        build_plugins(source, registry, tmp_path, clean=True)
        frontmatter_errors = validate_skill_frontmatter(tmp_path)
        if frontmatter_errors:
            return {
                "ok": False,
                "diffs": [],
                "frontmatterErrors": frontmatter_errors,
                "telemetryErrors": [],
            }

        diffs: list[str] = []
        for rel_path in GENERATED_PATHS:
            diffs.extend(compare_dirs(REPO_ROOT / rel_path, tmp_path / rel_path))
        if diffs:
            return {
                "ok": False,
                "diffs": diffs,
                "frontmatterErrors": [],
                "telemetryErrors": [],
            }
    return {
        "ok": True,
        "diffs": [],
        "frontmatterErrors": [],
        "telemetryErrors": [],
    }
