from __future__ import annotations

from pathlib import Path
from typing import Any

TELEMETRY_CONTRACT_VERSION = 1
TELEMETRY_MARKER = f"<!-- gateway-skill-telemetry:v{TELEMETRY_CONTRACT_VERSION} -->"
TELEMETRY_TOOLS = (
    "gateway_telemetry_skill_started",
    "gateway_telemetry_skill_completed",
    "gateway_telemetry_skill_failed",
)


def packed_skill_names(registry: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(skill).strip()
            for pack in registry.get("packs", [])
            for skill in pack.get("skills", [])
            if str(skill).strip()
        }
    )


def has_telemetry_contract(text: str) -> bool:
    return TELEMETRY_MARKER in text and all(tool in text for tool in TELEMETRY_TOOLS)


def telemetry_contract_errors(source: Path, registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for skill_name in packed_skill_names(registry):
        path = source / skill_name / "SKILL.md"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path}: cannot read telemetry contract: {exc}")
            continue
        if not has_telemetry_contract(text):
            errors.append(
                f"{path}: missing GatewayMCP skill telemetry contract v{TELEMETRY_CONTRACT_VERSION}"
            )
    return errors
