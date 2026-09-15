# ai-native: agent skill platform

[![CI](https://github.com/comindspace/ai-native/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A portable skill system for AI coding and operational assistants. Skills are executable instructions: how to do a piece of work according to your company's rules. They live in a repository, are versioned, reviewed, and packed into installable plugin packs for different agents — Claude Code, Codex, Cursor, OpenCode, OpenClaw, Hermes.

This repository contains the AI-Native reference set: methodology skills for running company operations with assistants, plus the build tool that turns a canonical `skills/` tree into installable packs.

> Status: early public release of a system in daily production use. Skills are written for a Russian business environment first; English packaging is catching up. [Читать по-русски](README.ru.md).

## The skill contract

```text
skill-name/
  skill.yaml      # portable manifest: name, version, compatible agents, requirements
  SKILL.md        # canonical instructions the agent reads
  references/     # optional, loaded on demand
  scripts/        # optional deterministic helpers
  assets/         # optional output assets
  evals/          # optional smoke/evaluation prompts
```

`SKILL.md` is the procedural context; `skill.yaml` is for the registry, installer, policy, and pack composition. Every packed skill also carries the portable `gateway-skill-telemetry:v1` contract: on execution the agent records `started`, keeps the returned `correlation_id`, and closes the lifecycle with `completed` or `failed`. Telemetry is metadata-only — no prompts, documents, message bodies, or secrets.

## Published skills

- `ai-native-core-starter-kit` — the operating model for launching AI-Native roles: intake, operating model, source of truth, role cards, pilot brief, release gates, baseline, reviews.
- `ai-native-proposal` — shaping client proposals for AI-Native programs.
- `architect` — GenAI architecture: RAG, agents, tool use, MCP, ADRs, security.
- `editorial-style` — a shared final wording layer for clear business Russian.
- `comind-docx` — DOCX formatting helpers.
- `smd-drawio`, `func-arch-drawio`, `eepc-drawio` — diagramming methods (draw.io): system-thinking schemes, functional architecture, event-driven process chains.
- `sequential-thinking` — structured step-by-step reasoning.
- `document-templates` — process and document templates as a portable skill.

The public pack registry lives in `agent-platform/skill-packs.json`.

## Build tool

`agent-platform/` builds plugin packs from the canonical `skills/` tree:

```bash
pip install -e agent-platform/
python agent-platform/build_agent_plugins.py inventory
python agent-platform/build_agent_plugins.py validate-skills
python agent-platform/build_agent_plugins.py build-plugins --clean
python agent-platform/build_agent_plugins.py validate-generated
```

Targets: Claude Code (`.claude-plugin`), Codex (`.codex-plugin` + marketplace), Cursor (`.cursor-plugin`), OpenClaw (`openclaw.plugin.json`), Hermes (`plugin.yaml`), OpenCode (portable tree).

## Where GatewayMCP fits

Agents reach company systems (wiki, tracker, code hosting, CRM, mail, calendar, drives) through one MCP gateway — not through scattered credentials. The gateway is the companion repository [`comindspace/gateway-mcp`](https://github.com/comindspace/gateway-mcp): OAuth, scopes, per-resource grants, audit, secret isolation, skill telemetry ingestion.

## Writing your own skills

Start by copying a small skill (`editorial-style` or `sequential-thinking`) and reading its `skill.yaml`. Run `validate-skills` before committing. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
