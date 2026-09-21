from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agent_platform.io import write_json, write_text, yaml_quote
from agent_platform.plugins.gateway import (
    GATEWAY_PLUGIN_VERSION,
    gateway_description,
    write_gateway_plugin,
)
from agent_platform.plugins.manifests import (
    pack_plugin_manifest,
    pack_version,
    write_claude_manifest,
    write_cursor_manifest,
    write_hermes_plugin,
    write_hermes_root_plugin,
    write_openclaw_manifest,
    write_zcode_manifest,
)
from agent_platform.skills import copy_skill, get_skills


def marketplace_entry(name: str, category: str) -> dict[str, Any]:
    return {
        "name": name,
        "source": {"source": "local", "path": f"./plugins/{name}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": category,
    }


def build_plugins(source: Path, registry: dict[str, Any], output: Path, clean: bool) -> dict[str, Any]:
    plugins_root = output / "plugins"
    if clean and plugins_root.exists():
        shutil.rmtree(plugins_root)

    platform_release = str(registry.get("platformRelease") or "")
    marketplace_plugins: list[dict[str, Any]] = []
    claude_plugins: list[dict[str, Any]] = []
    cursor_plugins: list[dict[str, Any]] = []
    zcode_plugins: list[dict[str, Any]] = []

    for pack in registry["packs"]:
        plugin_root = plugins_root / pack["name"]
        if clean and plugin_root.exists():
            shutil.rmtree(plugin_root)
        for skill in pack["skills"]:
            copy_skill(source, skill, plugin_root / "skills")

        write_json(plugin_root / ".codex-plugin/plugin.json", pack_plugin_manifest(pack, platform_release))
        write_claude_manifest(plugin_root, pack, platform_release)
        write_cursor_manifest(plugin_root, pack, platform_release)
        write_openclaw_manifest(plugin_root, pack, platform_release)
        write_hermes_plugin(plugin_root, pack, platform_release)
        write_zcode_manifest(plugin_root, pack, platform_release)

        marketplace_plugins.append(marketplace_entry(pack["name"], pack["category"]))
        claude_plugins.append(
            {
                "name": pack["name"],
                "source": f"./plugins/{pack['name']}",
                "description": pack["description"],
                "version": pack_version(pack),
                "platformRelease": platform_release,
            }
        )
        cursor_plugins.append(claude_plugins[-1].copy())
        # ZCode marketplace carries skill packs only: the gateway plugin's MCP
        # wiring is agent-specific and ZCode users connect it via settings.
        zcode_plugins.append(
            {
                "name": pack["name"],
                "source": f"./plugins/{pack['name']}",
                "description": pack["description"],
                "version": pack_version(pack),
                "category": pack["category"],
                "platformRelease": platform_release,
            }
        )

    gateway_root = plugins_root / "gateway-mcp"
    if clean and gateway_root.exists():
        shutil.rmtree(gateway_root)
    write_gateway_plugin(gateway_root, platform_release)
    marketplace_plugins.append(marketplace_entry("gateway-mcp", "Productivity"))
    claude_plugins.append(
        {
            "name": "gateway-mcp",
            "source": "./plugins/gateway-mcp",
            "description": gateway_description(),
            "version": GATEWAY_PLUGIN_VERSION,
            "platformRelease": platform_release,
        }
    )
    cursor_plugins.append(claude_plugins[-1].copy())

    write_hermes_root_plugin(output, registry, platform_release)

    write_json(
        output / ".agents/plugins/marketplace.json",
        {
            "name": "company-agent-skills",
            "platformRelease": platform_release,
            "interface": {"displayName": "Company Agent Skills"},
            "plugins": marketplace_plugins,
        },
    )
    write_json(
        output / ".claude-plugin/marketplace.json",
        {
            "name": "company-agent-skills",
            "owner": {"name": "coMind"},
            "platformRelease": platform_release,
            "plugins": claude_plugins,
        },
    )
    write_json(
        output / ".cursor-plugin/marketplace.json",
        {
            "name": "company-agent-skills",
            "owner": {"name": "coMind", "email": "team@comind.space"},
            "platformRelease": platform_release,
            "metadata": {
                "description": "coMind agent skill packs and GatewayMCP plugin for Cursor"
            },
            "plugins": cursor_plugins,
        },
    )
    write_json(
        output / ".zcode-plugin/marketplace.json",
        {
            "name": "company-agent-skills",
            "owner": {"name": "coMind", "email": "team@comind.space"},
            "platformRelease": platform_release,
            "description": "coMind agent skill packs for ZCode",
            "plugins": zcode_plugins,
        },
    )
    return {
        "target": "plugins",
        "pluginsRoot": str(plugins_root),
        "marketplaces": [
            str(output / ".agents/plugins/marketplace.json"),
            str(output / ".claude-plugin/marketplace.json"),
            str(output / ".cursor-plugin/marketplace.json"),
            str(output / ".zcode-plugin/marketplace.json"),
        ],
        "plugins": len(marketplace_plugins),
    }


def build_claude(source: Path, registry: dict[str, Any], output: Path, clean: bool) -> dict[str, Any]:
    target = output / "claude/.claude/skills"
    if clean and target.exists():
        shutil.rmtree(target)
    for pack in registry["packs"]:
        for skill in pack["skills"]:
            copy_skill(source, skill, target)
    return {"target": "claude", "path": str(target), "skills": len(list(target.iterdir()))}


def build_cursor_rules(source: Path, output: Path, clean: bool) -> dict[str, Any]:
    target = output / "cursor/.cursor/rules"
    if clean and target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    skills = get_skills(source)
    for skill in skills:
        text = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        content = "\n".join(
            [
                "---",
                f"description: {yaml_quote(skill.description)}",
                "alwaysApply: false",
                "---",
                "",
                text,
            ]
        )
        write_text(target / f"skill-{skill.directory}.mdc", content)
    return {"target": "cursor", "path": str(target), "rules": len(skills)}


def build_portable(target_name: str, source: Path, output: Path, clean: bool) -> dict[str, Any]:
    target = output / target_name / "skills"
    if clean and target.exists():
        shutil.rmtree(target)
    skills = get_skills(source)
    for skill in skills:
        copy_skill(source, skill.directory, target)
    write_json(
        output / target_name / "skills.json",
        {
            "schema": 1,
            "target": target_name,
            "format": "portable-skills-v1",
            "skills": [
                {
                    "name": skill.directory,
                    "title": skill.name,
                    "description": skill.description,
                    "path": f"./skills/{skill.directory}",
                    "manifest": f"./skills/{skill.directory}/skill.yaml",
                    "instructions": f"./skills/{skill.directory}/SKILL.md",
                }
                for skill in skills
            ],
        },
    )
    return {"target": target_name, "path": str(target), "skills": len(skills)}
