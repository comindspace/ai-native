from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_platform.io import write_json, write_text, yaml_quote


def platform_metadata(platform_release: str) -> dict[str, str]:
    return {"platformRelease": platform_release} if platform_release else {}


def pack_version(pack: dict[str, Any]) -> str:
    return str(pack.get("version") or "0.1.0")


def pack_plugin_manifest(pack: dict[str, Any], platform_release: str = "") -> dict[str, Any]:
    return {
        "name": pack["name"],
        "version": pack_version(pack),
        "description": pack["description"],
        "author": {
            "name": "coMind",
            "email": "team@comind.space",
            "url": "https://comind.space",
        },
        "keywords": [
            "agents",
            "skills",
            "ai-native",
            pack["category"].lower(),
        ],
        "skills": "./skills/",
        "metadata": platform_metadata(platform_release),
        "interface": {
            "displayName": pack["displayName"],
            "shortDescription": pack["description"],
            "longDescription": pack["description"],
            "developerName": "coMind",
            "category": pack["category"],
            "capabilities": ["Skills"],
            "defaultPrompt": [f"Use {pack['displayName']} for this work."],
        },
    }


def write_claude_manifest(plugin_root: Path, pack: dict[str, Any], platform_release: str = "") -> None:
    write_json(
        plugin_root / ".claude-plugin/plugin.json",
        {
            "name": pack["name"],
            "version": pack_version(pack),
            "description": pack["description"],
            "author": {
                "name": "coMind",
                "email": "team@comind.space",
                "url": "https://comind.space",
            },
            "metadata": platform_metadata(platform_release),
        },
    )


def write_cursor_manifest(plugin_root: Path, pack: dict[str, Any], platform_release: str = "") -> None:
    category = pack["category"].lower()
    write_json(
        plugin_root / ".cursor-plugin/plugin.json",
        {
            "name": pack["name"],
            "displayName": pack["displayName"],
            "version": pack_version(pack),
            "description": pack["description"],
            "author": {"name": "coMind", "email": "team@comind.space"},
            "homepage": "https://comind.space",
            "repository": "https://github.com/comindspace/ai-native",
            "license": "UNLICENSED",
            "keywords": ["agents", "skills", "ai-native", category],
            "category": category,
            "tags": [category, "skills", "agent-skills"],
            "skills": "./skills/",
            "metadata": platform_metadata(platform_release),
        },
    )


def write_zcode_manifest(plugin_root: Path, pack: dict[str, Any], platform_release: str = "") -> None:
    """Write the ZCode plugin manifest.

    ZCode packs plugins as a directory with `.zcode-plugin/plugin.json`; the
    `skills` field names the directory holding the skill trees. ZCode reads
    Claude-style marketplaces, so the companion `.zcode-plugin/marketplace.json`
    at the repository root lists these plugins with relative sources.
    """
    write_json(
        plugin_root / ".zcode-plugin/plugin.json",
        {
            "name": pack["name"],
            "version": pack_version(pack),
            "description": pack["description"],
            "author": {
                "name": "coMind",
                "email": "team@comind.space",
                "url": "https://comind.space",
            },
            "skills": "skills",
            "metadata": platform_metadata(platform_release),
        },
    )


def write_openclaw_manifest(plugin_root: Path, pack: dict[str, Any], platform_release: str = "") -> None:
    write_json(
        plugin_root / "openclaw.plugin.json",
        {
            "schema": 1,
            "name": pack["name"],
            "version": pack_version(pack),
            "description": pack["description"],
            "skills": ["./skills"],
            "metadata": {
                "openclaw": {"category": pack["category"]},
                **platform_metadata(platform_release),
            },
        },
    )


def write_hermes_plugin(plugin_root: Path, pack: dict[str, Any], platform_release: str = "") -> None:
    write_text(
        plugin_root / "plugin.yaml",
        "\n".join(
            [
                f"name: {pack['name']}",
                f'version: "{pack_version(pack)}"',
                f"description: {yaml_quote(pack['description'])}",
                *( [f'platform_release: "{platform_release}"'] if platform_release else [] ),
                "",
            ]
        ),
    )
    lines = [
        '"""Hermes plugin generated from the shared agent skill pack."""',
        "",
        "from pathlib import Path",
        "",
        "",
        "def register(ctx):",
        "    base_dir = Path(__file__).parent",
        "    # Hermes exposes these as namespaced skills, e.g. plugin-name:skill-name.",
    ]
    lines.extend(
        f"    ctx.register_skill({skill!r}, base_dir / 'skills' / {skill!r} / 'SKILL.md')"
        for skill in pack["skills"]
    )
    write_text(plugin_root / "__init__.py", "\n".join(lines) + "\n")


def write_hermes_root_plugin(output: Path, registry: dict[str, Any], platform_release: str = "") -> None:
    """Write a repository-root Hermes plugin wrapper.

    Hermes installs a plugin by cloning a Git repository and checking the clone
    root for plugin.yaml and __init__.py. This repository stores the actual
    pack plugins under plugins/<pack>/, so the root plugin delegates to those
    generated pack directories and makes `hermes plugins install <repo>` work.
    """
    packs = registry["packs"]
    root_description = "Company Agent Skills: shared coMind skill packs for Hermes."
    write_text(
        output / "plugin.yaml",
        "\n".join(
            [
                "name: company-agent-skills",
                f'version: "{platform_release or "0.1.0"}"',
                f"description: {yaml_quote(root_description)}",
                *( [f'platform_release: "{platform_release}"'] if platform_release else [] ),
                "",
            ]
        ),
    )
    lines = [
        '"""Hermes root plugin for the company-agent-skills repository."""',
        "",
        "import shutil",
        "from pathlib import Path",
        "",
        "",
        "PLUGIN_NAME = 'company-agent-skills'",
        "",
        "",
        "PACKS = {",
    ]
    for pack in packs:
        skills = ", ".join(repr(skill) for skill in pack["skills"])
        lines.append(f"    {pack['name']!r}: [{skills}],")
    lines.extend(
        [
            "}",
            "",
            "",
            "def _get_profile_skills_root():",
            "    try:",
            "        from hermes_constants import get_hermes_home",
            "        return get_hermes_home() / 'skills' / PLUGIN_NAME",
            "    except Exception:",
            "        return None",
            "",
            "",
            "def _mirror_skill_for_web_ui(skill, skill_dir):",
            "    skills_root = _get_profile_skills_root()",
            "    if skills_root is None:",
            "        return",
            "    target = skills_root / skill",
            "    try:",
            "        skills_root.mkdir(parents=True, exist_ok=True)",
            "        if target.is_symlink():",
            "            if target.resolve() == skill_dir.resolve():",
            "                return",
            "            target.unlink()",
            "        elif target.exists():",
            "            shutil.rmtree(target)",
            "        try:",
            "            target.symlink_to(skill_dir, target_is_directory=True)",
            "        except OSError:",
            "            shutil.copytree(skill_dir, target, dirs_exist_ok=True)",
            "    except Exception:",
            "        return",
            "",
            "",
            "def register(ctx):",
            "    base_dir = Path(__file__).parent",
            "    seen = set()",
            "    for pack_name, skills in PACKS.items():",
            "        pack_dir = base_dir / 'plugins' / pack_name",
            "        for skill in skills:",
            "            skill_dir = pack_dir / 'skills' / skill",
            "            if skill in seen or not (skill_dir / 'SKILL.md').exists():",
            "                continue",
            "            ctx.register_skill(skill, skill_dir / 'SKILL.md')",
            "            _mirror_skill_for_web_ui(skill, skill_dir)",
            "            seen.add(skill)",
        ]
    )
    write_text(output / "__init__.py", "\n".join(lines) + "\n")
