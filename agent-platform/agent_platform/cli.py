from __future__ import annotations

import argparse
import json
import sys

from agent_platform.io import read_json
from agent_platform.paths import REPO_ROOT, repo_path
from agent_platform.cursor_distribution import (
    DEFAULT_CURSOR_DISTRIBUTION_URL,
    build_cursor_distribution,
)
from agent_platform.plugins.builder import (
    build_claude,
    build_cursor_rules,
    build_plugins,
    build_portable,
)
from agent_platform.skills import inventory, write_skill_manifests
from agent_platform.skill_validation import validate_skills
from agent_platform.validation import validate_generated


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and validate shared agent plugins.")
    parser.add_argument(
        "command",
        choices=[
            "inventory",
            "write-manifests",
            "build-plugins",
            "build-claude",
            "build-cursor",
            "build-cursor-distribution",
            "build-opencode",
            "build-openclaw",
            "build-hermes",
            "build-all",
            "validate-generated",
            "validate-skills",
        ],
        nargs="?",
        default="inventory",
    )
    parser.add_argument("--source", default="skills")
    parser.add_argument("--packs-file", default="agent-platform/skill-packs.json")
    parser.add_argument("--output", default=".agent-platform-build")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--base-url", default=DEFAULT_CURSOR_DISTRIBUTION_URL)
    return parser


def run_command(args: argparse.Namespace) -> tuple[object, int]:
    source = repo_path(args.source)
    registry = read_json(repo_path(args.packs_file))

    if args.command == "inventory":
        return inventory(source, registry), 0
    if args.command == "write-manifests":
        return write_skill_manifests(source, args.force), 0
    if args.command == "build-plugins":
        return build_plugins(source, registry, REPO_ROOT, clean=args.clean), 0
    if args.command == "build-claude":
        return build_claude(source, registry, repo_path(args.output), clean=args.clean), 0
    if args.command == "build-cursor":
        return build_cursor_rules(source, repo_path(args.output), clean=args.clean), 0
    if args.command == "build-cursor-distribution":
        return (
            build_cursor_distribution(
                REPO_ROOT / "plugins",
                repo_path(args.output) / "cursor-plugins",
                REPO_ROOT / "agent-platform" / "cursor-distribution",
                str(registry.get("platformRelease") or ""),
                base_url=args.base_url,
                clean=args.clean,
            ),
            0,
        )
    if args.command == "build-opencode":
        return build_portable("opencode", source, repo_path(args.output), clean=args.clean), 0
    if args.command == "build-openclaw":
        return build_portable("openclaw", source, repo_path(args.output), clean=args.clean), 0
    if args.command == "build-hermes":
        return build_portable("hermes", source, repo_path(args.output), clean=args.clean), 0
    if args.command == "build-all":
        output = repo_path(args.output)
        return [
            build_claude(source, registry, output, clean=args.clean),
            build_plugins(source, registry, output, clean=args.clean),
            build_cursor_rules(source, output, clean=args.clean),
            build_portable("opencode", source, output, clean=args.clean),
            build_portable("openclaw", source, output, clean=args.clean),
            build_portable("hermes", source, output, clean=args.clean),
        ], 0
    if args.command == "validate-generated":
        result = validate_generated(source, registry)
        return result, 0 if result["ok"] else 1
    if args.command == "validate-skills":
        result = validate_skills(source, registry)
        return result, 0 if result["ok"] else 1

    raise AssertionError(args.command)


def main() -> int:
    result, exit_code = run_command(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code
