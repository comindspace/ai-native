# Contributing to GatewayMCP

Thanks for your interest. This repository is a published export of an actively maintained internal project; development happens in the maintainers' canonical repository and is mirrored here. External contributions are welcome and land through the maintainers.

## Ways to contribute

- Bug reports and reproducible examples (see issue templates).
- New backend adapters or route improvements (see "Adding a backend route" below).
- Tests: every declared transport must be routed, and every public tool must follow the standard `ToolRun` lifecycle.
- Documentation and deployment examples.

## Development setup

Requirements: Python 3.10+ (CI runs 3.12), a Postgres instance for integration surfaces, Docker for the full compose stack.

```bash
git clone <this repository>
cd gateway-mcp
pip install -e .
```

Run the same checks CI runs before opening an issue or PR:

```bash
python -m json.tool gateway-tools.json > /dev/null
python -m json.tool gateway-policy.json > /dev/null
python -m json.tool gateway-company-indexes.json > /dev/null
python -m compileall -q gateway_mcp gateway.py gateway_access.py gateway_auth.py gateway_backends.py gateway_company.py gateway_memory.py gateway_migrations.py gateway_observability.py gateway_policy.py gateway_storage.py
python -m unittest discover -s tests
```

For a full local stack, copy `deploy.env.example`, fill in what you need, and use `docker compose up`.

## Adding a backend route

1. Add the route declaration to `gateway-tools.json`.
2. Reuse an existing `transport` if possible.
3. If a new transport is needed, add an adapter in `gateway_mcp/backends/`.
4. Register dispatch in `gateway_mcp/backends/router.py`.
5. Add or update tests so every declared transport is routed.

Route declarations include scope, backend, operation or path metadata, and argument aliases when useful. Secrets must come from env vars or per-user encrypted credentials, never from the registry.

## Adding a public MCP tool

1. Add the tool to the matching file in `gateway_mcp/tools/`.
2. Use `ToolRun.start(...)`.
3. Call `run.require_scope(...)` for required scopes.
4. Finish through `run.finish(...)`, `run.denied(...)`, and `run.error(...)` in the standard try/except shape.
5. Register the tool file in `gateway_mcp/server.py` if it is a new domain.

Do not call `finish_tool`, `deny`, or `start_timer` directly from tool modules; `tests/test_structure.py` enforces this.

## Pull requests

- Keep PRs focused: one route, one tool, or one fix per PR.
- Include tests for any new behavior.
- Follow the existing code style: stdlib-first, typed where the codebase already types, no new dependencies without discussion.
- UI strings in admin routes are currently Russian; i18n extraction is on the roadmap — do not machine-translate them in passing.

## License

By contributing, you agree that your contributions are licensed under the Apache-2.0 license that covers this project.
