from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_platform.io import write_json, write_text, yaml_quote
from agent_platform.paths import GATEWAY_MCP_PUBLIC_URL
from agent_platform.plugins.gateway_content import (
    GATEWAY_PLUGIN_VERSION,
    gateway_codex_manifest,
    gateway_description,
    gateway_hermes_init,
    gateway_readme,
)


def gateway_mcp_config() -> dict[str, Any]:
    return gateway_mcp_config_for("${GATEWAY_MCP_URL}", "${GATEWAY_MCP_TOKEN}")


def codex_gateway_mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "gateway": {
                "type": "http",
                "url": GATEWAY_MCP_PUBLIC_URL,
                "timeout": 60000,
            }
        }
    }


def cursor_gateway_mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "gateway": {
                "url": GATEWAY_MCP_PUBLIC_URL,
            }
        }
    }


def claude_gateway_mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "gateway": {
                "type": "http",
                "url": "${user_config.gateway_mcp_url}",
                "timeout": 60000,
            }
        }
    }


def gateway_mcp_config_for(url: str, token: str) -> dict[str, Any]:
    return {
        "mcpServers": {
            "gateway": {
                "type": "http",
                "url": url,
                "headers": {
                    "Authorization": f"Bearer {token}"
                },
                "timeout": 60000,
            }
        }
    }


def write_gateway_plugin(plugin_root: Path, platform_release: str = "") -> None:
    plugin_root.mkdir(parents=True, exist_ok=True)
    codex_manifest = gateway_codex_manifest(platform_release)
    write_json(plugin_root / ".codex-plugin/plugin.json", codex_manifest)
    write_json(
        plugin_root / ".claude-plugin/plugin.json",
        {
            "name": "gateway-mcp",
            "version": GATEWAY_PLUGIN_VERSION,
            "description": codex_manifest["description"],
            "author": codex_manifest["author"],
            "metadata": codex_manifest["metadata"],
            "mcpServers": "./.mcp.json",
            "userConfig": {
                "gateway_mcp_url": {
                    "type": "string",
                    "title": "GatewayMCP URL",
                    "description": f"Remote GatewayMCP HTTP endpoint. Production: {GATEWAY_MCP_PUBLIC_URL}",
                    "default": GATEWAY_MCP_PUBLIC_URL,
                    "required": True,
                },
            },
        },
    )
    write_json(
        plugin_root / ".cursor-plugin/plugin.json",
        {
            "name": "gateway-mcp",
            "displayName": "Gateway MCP",
            "version": GATEWAY_PLUGIN_VERSION,
            "description": codex_manifest["description"],
            "author": {"name": "coMind", "email": "team@comind.space"},
            "homepage": "https://comind.space",
            "repository": "https://github.com/comindspace/gateway-mcp",
            "license": "UNLICENSED",
            "keywords": ["cursor", "mcp", "gateway", "agents", "skills"],
            "category": "productivity",
            "tags": ["mcp", "gateway", "agent-skills"],
            "mcpServers": "./cursor.mcp.json",
            "metadata": codex_manifest["metadata"],
        },
    )
    write_json(
        plugin_root / "openclaw.plugin.json",
        {
            "schema": 1,
            "name": "gateway-mcp",
            "version": GATEWAY_PLUGIN_VERSION,
            "description": codex_manifest["description"],
            "mcpServers": "./mcp.json",
            "configuration": codex_manifest["configuration"],
            "metadata": {
                "openclaw": {"category": "Productivity"},
                **codex_manifest["metadata"],
            },
        },
    )
    write_json(plugin_root / "codex.mcp.json", codex_gateway_mcp_config())
    write_json(plugin_root / "cursor.mcp.json", cursor_gateway_mcp_config())
    write_json(plugin_root / "mcp.json", gateway_mcp_config())
    write_json(plugin_root / ".mcp.json", claude_gateway_mcp_config())
    write_text(plugin_root / "README.md", gateway_readme())
    write_text(
        plugin_root / "plugin.yaml",
        "\n".join(
            [
                "name: gateway-mcp",
                f'version: "{GATEWAY_PLUGIN_VERSION}"',
                f"description: {yaml_quote(codex_manifest['description'])}",
                *( [f'platform_release: "{platform_release}"'] if platform_release else [] ),
                "requires_env:",
                "  - GATEWAY_MCP_URL",
                "  - GATEWAY_MCP_TOKEN",
                "",
            ]
        ),
    )
    write_text(plugin_root / "__init__.py", gateway_hermes_init())
