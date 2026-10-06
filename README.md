# ai-native: agent skill platform + gateway

[![CI](https://github.com/comindspace/ai-native/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A portable skill system for AI coding and operational assistants — bundled with the GatewayMCP server the skills talk to. One repository, one command to deploy, one MCP URL for every agent client.

Two parts:

- **Skills platform.** Skills are executable instructions: how to do a piece of work according to your company's rules. They live in a repository, are versioned, reviewed, and packed into installable plugin packs for different agents — Claude Code, Codex, Cursor, OpenCode, OpenClaw, Hermes, ZCode. This repository contains the AI-Native reference skill set plus the build tool that turns the canonical `skills/` tree into packs.
- **GatewayMCP** (the `gateway/` directory). One MCP boundary between assistants and company systems: OAuth, scopes and resource grants, audit, secret isolation, corporate memory, and backend adapters. Agents connect to the gateway, authenticate once, and call a small, stable set of public MCP tools — backend credentials never reach the agent. This is the canonical home of the server; the earlier standalone mirror [`comindspace/gateway-mcp`](https://github.com/comindspace/gateway-mcp) is archived (readable, releases up to v0.2.0).

> Status: early public release of a system in daily production use. Skills are written for a Russian business environment first; English packaging is catching up. [Читать по-русски](README.ru.md).

## Deploy in one command

On a clean Ubuntu/Debian VM (no git or Docker required upfront):

```bash
curl -fsSL https://raw.githubusercontent.com/comindspace/ai-native/main/bootstrap.sh -o bootstrap.sh
sudo bash bootstrap.sh
```

Download the script to a file first: piping it straight into `bash` breaks, because child processes consume the piped script. The script installs Docker, Docker Compose, Caddy and git, clones this repository to `/opt/ai-native`, generates secrets, seeds the first admin, starts PostgreSQL + Gateway + notification worker behind HTTPS, verifies `/healthz`, and prints the ready MCP URL. The only manual prerequisite is a Yandex OAuth application for login (the script prints the exact redirect URI). Full guide, manual install and troubleshooting: [DEPLOY.md](DEPLOY.md) (Russian).

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

Targets: Claude Code (`.claude-plugin`), Codex (`.codex-plugin` + marketplace), Cursor (`.cursor-plugin`), OpenClaw (`openclaw.plugin.json`), Hermes (`plugin.yaml`), OpenCode and ZCode (portable tree; ZCode also reads the `.zcode-plugin/` marketplace at the repository root).

## Installing for ZCode

ZCode consumes Claude-style plugin marketplaces. Add this repository as a marketplace (it ships `.zcode-plugin/marketplace.json`) and install the `ai-native-core` pack, or copy the skill directories from `skills/` into your `.zcode/skills/`. The GatewayMCP server is not wired by the pack: connect it through ZCode's own MCP settings.

## Repository layout

```text
gateway/           GatewayMCP server: code, compose files, policy, tests
skills/            canonical skill tree (source of truth for packs)
agent-platform/    pack builder and its tests
plugins/           generated plugin packs (do not edit by hand)
.claude-plugin/ .cursor-plugin/ .zcode-plugin/ .agents/   agent marketplaces
bootstrap.sh       one-command VM installer
DEPLOY.md          deployment guide (Russian)
```

The `gateway/` directory is the canonical home of the GatewayMCP server; server-specific docs live there (`gateway/README.md`, `gateway/SECURITY.md`, `gateway/docs/`). Maintainers sync it from the internal source repository.

## Writing your own skills

Start by copying a small skill (`editorial-style` or `sequential-thinking`) and reading its `skill.yaml`. Run `validate-skills` before committing. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
