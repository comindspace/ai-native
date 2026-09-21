# Contributing to ai-native

Thanks for your interest. This repository is a published export of an actively maintained internal project; development happens in the maintainers' canonical repository and is mirrored here. External contributions are welcome and land through the maintainers.

## The skill contract

Every skill is a directory under `skills/`:

```text
skill-name/
  skill.yaml      # portable manifest
  SKILL.md        # canonical instructions
  references/     # optional, loaded on demand
  scripts/        # optional deterministic helpers
  assets/         # optional output assets
  evals/          # optional smoke/evaluation prompts
```

Minimum `skill.yaml` shape:

```yaml
schema: 1
name: my-skill
version: 0.1.0
title: My Skill
description: One line about what it does.
compatible_agents:
  - claude
  - codex
  - cursor
  - opencode
  - openclaw
  - hermes
  - zcode
requires:
  mcp: []
  permissions:
    filesystem: read
```

## Writing a skill

- `SKILL.md` is what the agent reads. Keep it procedural: when the skill applies, what steps to follow, what quality bar to hit, what never to do.
- Long reference material goes to `references/`, not into `SKILL.md` (context budget matters).
- Deterministic helpers go to `scripts/` and must not contain credentials or personal data.
- If the skill is packed, it must carry the `gateway-skill-telemetry:v1` lifecycle contract in `SKILL.md`.
- Write for the reader the skill targets; default language of this set is Russian, English contributions are welcome.

## Before submitting

Run the same checks CI runs:

```bash
pip install -e agent-platform/
python agent-platform/build_agent_plugins.py validate-skills
python agent-platform/build_agent_plugins.py inventory
python agent-platform/build_agent_plugins.py build-plugins --clean
python agent-platform/build_agent_plugins.py validate-generated
```

Never commit secrets, tokens, customer names, or personal data. Test fixtures use fictional companies.

## Pull requests

- One skill or one fix per PR.
- Keep `skills/` as the single source; generated pack output under `plugins/` is produced by the build tool, not edited by hand.
- By contributing, you agree your contributions are licensed under Apache-2.0.
