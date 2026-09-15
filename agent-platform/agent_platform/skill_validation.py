from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_platform.io import parse_frontmatter
from agent_platform.telemetry import telemetry_contract_errors

ALLOWED_FRONTMATTER = {
    "allowed-tools",
    "description",
    "license",
    "metadata",
    "name",
}
REQUIRED_MANIFEST_KEYS = {
    "schema",
    "name",
    "version",
    "title",
    "description",
    "compatible_agents",
    "requires",
    "resources",
}
SUPPORTED_AGENTS = {"claude", "codex", "cursor", "opencode", "openclaw", "hermes"}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _manifest_top_level(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _manifest_list(text: str, key: str) -> set[str]:
    values: set[str] = set()
    active = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            active = line.rstrip() == f"{key}:"
            continue
        if active:
            stripped = line.strip()
            if stripped.startswith("- "):
                values.add(stripped[2:].strip().strip("\"'"))
            elif not line.startswith(("  ", "\t")):
                break
    return values


def validate_skills(source: Path, registry: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    skill_dirs: set[str] = set()
    frontmatter_names: dict[str, str] = {}
    legacy_manifests = set(
        registry.get("validation", {}).get("legacySkillManifests", [])
    )

    for skill_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        skill_dirs.add(skill_dir.name)
        text = skill_md.read_text(encoding="utf-8")

        readme = skill_dir / "README.md"
        if readme.exists():
            errors.append(
                f"{readme}: remove auxiliary README and keep agent instructions in SKILL.md or references/"
            )

        try:
            frontmatter = parse_frontmatter(text)
        except ValueError as exc:
            errors.append(f"{skill_md}: invalid frontmatter: {exc}")
            continue

        unexpected = sorted(set(frontmatter) - ALLOWED_FRONTMATTER)
        if unexpected:
            errors.append(f"{skill_md}: unexpected frontmatter keys: {', '.join(unexpected)}")

        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")
        if not name or not NAME_PATTERN.fullmatch(name):
            errors.append(f"{skill_md}: name must use lowercase hyphen-case")
        elif name != skill_dir.name:
            errors.append(f"{skill_md}: name '{name}' must match directory '{skill_dir.name}'")
        elif name in frontmatter_names:
            errors.append(f"{skill_md}: duplicate skill name also used by {frontmatter_names[name]}")
        else:
            frontmatter_names[name] = str(skill_md)

        if not description:
            errors.append(f"{skill_md}: description is required")
        if "<" in description or ">" in description:
            errors.append(f"{skill_md}: description cannot contain angle brackets")
        if len(description) > 1024:
            errors.append(f"{skill_md}: description exceeds 1024 characters")

        manifest_path = skill_dir / "skill.yaml"
        if not manifest_path.exists():
            errors.append(f"{manifest_path}: manifest is required")
        else:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest = _manifest_top_level(manifest_text)
            missing = sorted(REQUIRED_MANIFEST_KEYS - set(manifest))
            if missing:
                message = f"{manifest_path}: missing keys: {', '.join(missing)}"
                if skill_dir.name in legacy_manifests:
                    warnings.append(f"{message}; preserved as an explicit legacy exception")
                else:
                    errors.append(message)
            if manifest.get("schema") != "1":
                message = f"{manifest_path}: schema must be 1"
                if skill_dir.name in legacy_manifests:
                    warnings.append(f"{message}; preserved as an explicit legacy exception")
                else:
                    errors.append(message)
            if manifest.get("name") != skill_dir.name:
                errors.append(f"{manifest_path}: name must match directory '{skill_dir.name}'")
            if not VERSION_PATTERN.fullmatch(manifest.get("version", "")):
                errors.append(f"{manifest_path}: version must use semantic versioning")
            agents = _manifest_list(manifest_text, "compatible_agents")
            if agents != SUPPORTED_AGENTS:
                missing_agents = sorted(SUPPORTED_AGENTS - agents)
                extra_agents = sorted(agents - SUPPORTED_AGENTS)
                details = []
                if missing_agents:
                    details.append(f"missing {', '.join(missing_agents)}")
                if extra_agents:
                    details.append(f"unsupported {', '.join(extra_agents)}")
                message = f"{manifest_path}: compatible_agents {'; '.join(details)}"
                if skill_dir.name in legacy_manifests:
                    warnings.append(f"{message}; preserved as an explicit legacy exception")
                else:
                    errors.append(message)

        line_count = len(text.splitlines())
        if line_count > 300:
            warnings.append(
                f"{skill_md}: {line_count} lines; move detailed material to references/"
            )

    packed: dict[str, list[str]] = {}
    for pack in registry["packs"]:
        if not VERSION_PATTERN.fullmatch(str(pack.get("version", ""))):
            errors.append(f"pack {pack['name']}: version must use semantic versioning")
        seen: set[str] = set()
        for skill_name in pack["skills"]:
            if skill_name in seen:
                errors.append(f"pack {pack['name']}: duplicate skill '{skill_name}'")
            seen.add(skill_name)
            packed.setdefault(skill_name, []).append(pack["name"])
            if skill_name not in skill_dirs:
                errors.append(f"pack {pack['name']}: missing source skill '{skill_name}'")

    for skill_name in sorted(skill_dirs - set(packed)):
        errors.append(f"skill {skill_name}: not included in any plugin pack")

    errors.extend(telemetry_contract_errors(source, registry))

    return {
        "ok": not errors,
        "skillCount": len(skill_dirs),
        "packCount": len(registry["packs"]),
        "errors": errors,
        "warnings": warnings,
    }
