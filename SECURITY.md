# Security Policy

## Supported versions

Only the latest release on `main` is supported.

## Reporting a vulnerability

Please do **not** open public issues for security problems.

Use [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-reviewing/privately-reporting-a-security-vulnerability) for this repository (Security tab → "Report a vulnerability"). Reports sent this way reach the maintainers directly and are triaged within a few business days.

Include what you can: affected component (`gateway_mcp/tools/`, `gateway_mcp/routes/`, `gateway_mcp/backends/`, `gateway_mcp/services/`), a minimal reproduction, and the impact you see. If you already have a patch, attach it to the private report.

## Scope notes

GatewayMCP is designed to keep upstream service tokens, per-user credentials, and access rules inside the gateway runtime and its Postgres instance. Agent-facing surfaces only ever see Gateway-issued tokens. Reports that concern deliberate parts of this boundary design (for example, a deployment that chooses `permissive` resource policy) may be closed as configuration choices rather than vulnerabilities.

Preferred languages for reports: English or Russian.
