# Gateway MCP Plugin

This plugin connects agents to the remote company GatewayMCP endpoint.

## Configure

Claude Code:

```text
/plugin install gateway-mcp@company-agent-skills
/mcp
```

Authenticate the MCP server when Claude prompts. The endpoint is `https://gateway.example.com/mcp`.
If Claude was previously connected with an old token or wrong account, open `/mcp`, clear authentication for GatewayMCP, then reconnect.

Smoke tools after login:

```text
/mcp list
gateway_search_tools
gateway_company_get_source_of_truth
```

Codex uses the production endpoint from `codex.mcp.json` and authenticates through MCP OAuth.
Cursor uses the production endpoint from `cursor.mcp.json` and authenticates through MCP OAuth.
OpenClaw and Hermes can use a Gateway bearer token only when their runtime does not support MCP OAuth.

Do not configure direct MCP servers in agent workspaces.

Claude Code uses `.mcp.json` plus MCP OAuth discovery; no bearer token should be stored in the Claude plugin config.
Codex uses `codex.mcp.json` and Cursor uses `cursor.mcp.json`; neither stores a bearer token. OpenClaw uses `mcp.json` with `GATEWAY_MCP_URL` and `GATEWAY_MCP_TOKEN` placeholders.
Hermes uses config-driven MCP servers; add the same remote GatewayMCP URL and token to the Hermes MCP configuration.

Corporate memory is remote too. Use `gateway_memory_write` for short/medium Postgres memory,
`gateway_memory_search` for combined short/medium/source-backed retrieval, and
`gateway_memory_sources_search` for long-term Yonote/templates/ADR/docs knowledge.

GitLab and Yandex Disk are routed through GatewayMCP. Discover exact routes with `gateway_search_tools`
and call them through `gateway_call_tool`; do not place GitLab or Yandex Disk tokens in agent workspaces.
For GitLab, OAuth login lives at the GatewayMCP boundary. If `/mcp list` or `codex mcp list` shows GatewayMCP
authenticated and Gateway tools respond, do not ask for a separate GitLab login. Start discovery with a broad
`gateway_search_tools` query such as `gitlab`; a zero result for a narrow phrase does not prove the routes are missing.
Repository updates should feel like an assistant workflow: the user asks to update code or publish a change,
and the agent handles branches, commits, pushes, and merge requests through GatewayMCP when routes are available.
If a GitLab route is missing or denied, report the GatewayMCP route/scope gap and leave a durable handoff,
such as a local branch, commit, patch, or merge request payload. Do not ask the user to authenticate to GitLab
or learn GitLab mechanics unless the task is explicitly platform administration.
After creating or reviewing a merge request, check its mergeability and conflict status before calling it ready.
Do not send pre-merge MR notifications (MR ready, merge needed) to the coMind chat; reviewer pings are discontinued
and the reviewer works from the MR link returned to the author. After a merge that changes company skills, plugin packs,
or GatewayMCP skill content, send one post-merge skill update notification through the GatewayMCP notification route
`notifications.skill_update.send`. Use a dedicated service-identity bot when available; otherwise use the configured
GatewayMCP notification identity for the coMind chat. The message names the updated skill, briefly describes the change,
and asks users to update their installed plugin packs. Do not require routine users to receive `telegram:read` or
`telegram:write` grants just to receive notifications. Short-lived user Telegram grants are break-glass administration only.
If notification routes are missing, return the message payload as a maintainer handoff and report the missing platform
notification capability instead of asking the user to send it manually.

Company context is remote too and is maintained in Yonote/source systems, not plugin files.
Start company-context-heavy work with `gateway_company_get_source_of_truth`, then `gateway_company_bootstrap_context`,
and use `gateway_company_search` / `gateway_company_get` for specific people, teams, projects, clients, processes, documents, decisions, and systems.

Access administration is remote too. Use the `platform-admin` pack and GatewayMCP `gateway_admin_*` tools;
write tools default to `dry_run=true` and should be verified with `gateway_admin_explain_access`.

Privacy-sensitive data must be sanitized before it enters LLM context. When GatewayMCP sanitized privacy tools are available,
use them instead of fetching raw personal, client, HR, contract, finance, Telegram, CRM, secret, or confidential content.
