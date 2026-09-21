from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agent_platform.io import parse_frontmatter, write_text, yaml_quote
from agent_platform.models import Skill
from agent_platform.telemetry import (
    TELEMETRY_CONTRACT_VERSION,
    has_telemetry_contract,
)


def get_skills(source: Path) -> list[Skill]:
    if not source.exists():
        raise SystemExit(f"Skill source not found: {source}")

    skills: list[Skill] = []
    for skill_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        frontmatter = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        skills.append(
            Skill(
                name=frontmatter.get("name", skill_dir.name),
                directory=skill_dir.name,
                path=skill_dir,
                description=frontmatter.get("description", ""),
                has_references=(skill_dir / "references").exists(),
                has_reference=(skill_dir / "reference").exists(),
                has_scripts=(skill_dir / "scripts").exists(),
                has_assets=(skill_dir / "assets").exists(),
                has_manifest=(skill_dir / "skill.yaml").exists(),
            )
        )
    return skills


def inventory(source: Path, registry: dict[str, Any]) -> dict[str, Any]:
    skills = get_skills(source)
    skill_dirs = {skill.directory for skill in skills}
    pack_skill_map: dict[str, list[str]] = {}
    missing_from_source: list[dict[str, str]] = []

    for pack in registry["packs"]:
        for skill in pack["skills"]:
            pack_skill_map.setdefault(skill, []).append(pack["name"])
            if skill not in skill_dirs:
                missing_from_source.append({"pack": pack["name"], "skill": skill})

    return {
        "source": str(source),
        "skillCount": len(skills),
        "packCount": len(registry["packs"]),
        "telemetryContractVersion": TELEMETRY_CONTRACT_VERSION,
        "skillsWithoutTelemetryContract": [
            skill.directory
            for skill in skills
            if not has_telemetry_contract(
                (skill.path / "SKILL.md").read_text(encoding="utf-8")
            )
        ],
        "skillsWithoutSkillManifest": [
            skill.directory for skill in skills if not skill.has_manifest
        ],
        "skillsNotInAnyPack": [
            skill.directory for skill in skills if skill.directory not in pack_skill_map
        ],
        "packEntriesMissingFromSource": missing_from_source,
        "skills": [
            {
                "name": skill.name,
                "directory": skill.directory,
                "path": str(skill.path),
                "description": skill.description,
                "hasReferences": skill.has_references,
                "hasReference": skill.has_reference,
                "hasScripts": skill.has_scripts,
                "hasAssets": skill.has_assets,
                "hasSkillManifest": skill.has_manifest,
                "hasTelemetryContract": has_telemetry_contract(
                    (skill.path / "SKILL.md").read_text(encoding="utf-8")
                ),
            }
            for skill in skills
        ],
    }


def write_skill_manifests(source: Path, force: bool) -> dict[str, Any]:
    written: list[str] = []
    skipped: list[str] = []
    for skill in get_skills(source):
        manifest_path = skill.path / "skill.yaml"
        if manifest_path.exists() and not force:
            skipped.append(skill.directory)
            continue
        filesystem = "write" if skill.has_scripts or skill.has_assets else "read"
        manifest = "\n".join(
            [
                "schema: 1",
                f"name: {skill.directory}",
                "version: 0.1.0",
                f"title: {yaml_quote(skill.name)}",
                f"description: {yaml_quote(skill.description)}",
                "compatible_agents:",
                "  - claude",
                "  - codex",
                "  - cursor",
                "  - opencode",
                "  - openclaw",
                "  - hermes",
                "  - zcode",
                "requires:",
                "  mcp: []",
                "  permissions:",
                f"    filesystem: {filesystem}",
                "resources:",
                "  skill: SKILL.md",
                f"  references: {str(skill.has_references or skill.has_reference).lower()}",
                f"  scripts: {str(skill.has_scripts).lower()}",
                f"  assets: {str(skill.has_assets).lower()}",
                "",
            ]
        )
        write_text(manifest_path, manifest)
        written.append(skill.directory)
    return {
        "target": "skill-manifests",
        "written": len(written),
        "skipped": len(skipped),
        "writtenSkills": written,
        "skippedSkills": skipped,
    }


def copy_skill(source: Path, skill_name: str, destination_root: Path) -> None:
    source_skill = source / skill_name
    if not (source_skill / "SKILL.md").exists():
        raise SystemExit(f"Skill '{skill_name}' not found in {source}")
    destination_root.mkdir(parents=True, exist_ok=True)
    destination_skill = destination_root / skill_name
    if destination_skill.exists():
        shutil.rmtree(destination_skill)
    shutil.copytree(source_skill, destination_skill)
