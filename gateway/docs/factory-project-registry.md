# Factory project registration and readiness

Status: implementation proposal; deploy and live acceptance are separate operations.

Work Contract: `work-af621bde-607e-4b89-8af1-617470768df9`.

## API

- `gateway_factory_project_upsert`: register or replace the project configuration and validate it.
- `gateway_factory_project_validate`: rerun validation of a stored configuration.
- `gateway_factory_projects_discover`: includes registered projects before best-effort upstream discovery.
- `gateway_factory_project_get_runtime_config`: returns the registered repository and explicit base and MR target branches.
- `gateway_work_retry`: rerun readiness checks and explicitly requeue eligible blocked Factory work.
- `gateway_factory_connections_list`: list permitted connection aliases for an exact repository and logical project.
- `gateway_factory_git_config`: return the Gateway Git URL and assigned branch for an active, owned Factory lease.

Administrative operations require `factory:admin` or `factory:projects:write`.
The latter checks the actor's Factory project resource access and requires explicit
`factory` write grants for resource types `connection` (the handle) and `repository`
(the exact canonical web URL). Permissive policy fallback does not authorize these
bindings. A project writer cannot reuse another project's credentials. Ordinary
`factory:write` does not authorize registration or retry. Read operations continue
to require `factory:read`, and stored project results are resource-filtered.

Upsert is full replacement of the listed configuration, not a partial patch.
Use a stable `idempotency_key` for transport retries. Reusing that key with a
different configuration fails. Use a new key to request a fresh check or update.
A successful API operation may return `ready: false`: configuration is saved so
an administrator can diagnose and repair gaps. It does not trigger execution.

```json
{
  "project_id": "tracker-project-279",
  "project_path": "prompter/sale_service",
  "gitlab_clone_url": "https://gitlab.example.org/prompter/sale_service.git",
  "gitlab_web_url": "https://gitlab.example.org/prompter/sale_service",
  "default_base_branch": "dev",
  "mr_target_branch": "dev",
  "gitlab_connection_id": "gitlab:customer",
  "idempotency_key": "onboard-sale-service-1",
  "metadata_json": "{\"tracker_project_id\":\"279\",\"reviewer\":\"project-architect\",\"yonote_project_name\":\"Project context\"}"
}
```

The host above is an example. Use the actual host provisioned by a platform
administrator. Optional metadata: `name`, `tracker_project_id`,
`tracker_project_name`, `tracker_queue`, `reviewer`, `yonote_project_name`.
Tracker mapping is explicit; a logical identifier does not replace the Tracker ID.
Registration validation reports repository readiness. Runtime/discovery also
require a reviewer and project context, supplied in project metadata or, for a
specific work item, its Work Contract. Consolidated `ready`, `readiness_gaps` and
`validation.ready` agree; a technically reachable repository alone is insufficient.

## GitLab connections

Reuse the encrypted `managed_service_connections` store. A connection has an
opaque server-side key such as `gitlab:customer` and the payload
`GITLAB_API_BASE_URL`, `GITLAB_TOKEN`, `GITLAB_USERNAME`.
The existing managed `gitlab` connection can also be referenced. A missing
connection never falls back to another token, user OAuth token, or environment
credential. The token must support the GitLab REST API and repository read/write;
a read-only deploy token cannot meet these requirements.

### Admin workflow

Open `/admin/factory/connections` (also linked from **Integrations**). A platform
administrator with `access:admin` or `factory:admin` can create, rotate, check
and disable a named service connection. Enter its alias (`gitlab:company`), exact
HTTPS API URL, service login, service token, expiry in UTC and exact repository
paths, one per line. Wildcard repositories are not accepted. Several projects
can use the same connection when each repository is allowed.
Changing or disabling the shared alias `gitlab` additionally requires
`access:admin`, because that endpoint also receives personal GitLab credentials.
Factory-only administrators may manage named aliases, not redirect the shared endpoint.

Saved tokens never appear in HTML or MCP output. An empty token field preserves
the current token only when the API URL is unchanged. Saving includes an expected
version: a stale browser tab cannot overwrite a newer configuration. Repeated
identical saves do not change the connection version. Disabling or rotating the
connection immediately invalidates Factory readiness. Errors never echo submitted
secrets. The shared GitLab URL-only form cannot overwrite an existing service token.

**Check** calls `/user` with service authentication; it reports missing/disabled/
expired configuration, rejected authorization, redirects and network failures
separately. It does not prove clone or push access. **Bind and check** for a
registered project uses the existing project upsert and complete readiness probe,
including a temporary branch and cleanup. A saved but unready project remains
blocked. No work is automatically retried.

An agent calls `gateway_factory_connections_list(project_id=..., repository_url=...)`
and passes the chosen alias to `gateway_factory_project_upsert`. A delegated
project administrator sees only connections allowed by explicit connection and
repository grants. An empty list leads to the admin page, not another personal
OAuth login. Connection aliases are intentionally returned only in this authorized
selector; ordinary runtime, project discovery, Work and audit contain no handles.

### Operator fallback

Existing installations can still provision a connection locally:

```bash
docker compose exec gateway gateway-mcp factory-connection \
  --id gitlab:customer \
  --api-url https://gitlab.example.org/api/v4 \
  --username oauth2
```

The command prompts for the token without echo. Never add a token argument, put a
token into a repository URL, or paste it into a Work Contract. The existing
Gateway encryption key and database must be configured. The connection store
records the updating operator identity as `local:factory-connection`.
Run the command again to rotate the connection. Rotation invalidates readiness.

Project-write scope does not allow provisioning connections. CLI provisioning is
an OS-level administrative operation; restrict access to the container and its
environment. Existing CLI connections without repository lists retain the explicit
project-binding policy. Editing them through the UI requires setting a repository list.
Connections are bound to one canonical HTTPS base URL. Repository
URLs must match that base and the registered project path. HTTP redirects,
URL credentials, query strings and fragments are rejected.

## Readiness checks

Checks report `pass`, `fail` or `not_checked` with safe diagnostic codes:

| Check | Evidence |
|---|---|
| `dns` | GitLab hostname resolves from the Gateway process |
| `network` | HTTPS API reachable with certificate verification and no redirects |
| `authentication` | Configured service identity authenticated through `/user` |
| `repository` | Exact project exists, is accessible and is not archived |
| `branch` | Both base and MR target branches exist |
| `clone` | Real bare, shallow, single-branch clone without checkout or repository hooks |
| `push_permissions` | Real push of the cloned commit to a unique `codex/readiness-*` branch |
| `cleanup` | The probe branch was removed with an expected-commit lease |

Validation is a write operation. It creates no application commit or MR, uses
`ci.skip`, and never modifies `dev`, `main`, permissions or secrets. GitLab
webhooks may still receive branch events. On an uncertain cleanup result, the
report includes only the probe branch name and remains not ready. A durable
recovery record stores the remote URL, ref and expected SHA before any push.
Cancellation waits for bounded, shielded cleanup; a killed process leaves a
pending record. The next validation first recovers pending probes with a lease,
or reports `cleanup` for operator intervention if recovery is unsafe or denied.
A repeated operation key returns its receipt without repeating the probe.
Postgres reserves each operation before network access and permits only one
active validation per project, including requests with different keys. Concurrent
requests receive an in-progress error. Abandoned reservations expire after ten
minutes (longer than the bounded probe and cleanup); retry with a new key.

Stored diagnostic readiness expires after five minutes and after credential
rotation, revocation or expiry. Discovery and unclaimed Work runtime responses
then report a gap. A successfully admitted, unchanged live lease can outlive the
diagnostic TTL as described below. `gateway_work_retry` always probes again with
current credentials.

## Claim preflight

`gateway_work_claim` first atomically reserves a queued Work and its lease. For
a registered project it then verifies project write access, the exact repository
mapping and current readiness. A fresh successful check is reused; an expired or
failed check triggers the same bounded server-side validation used by project
administration. This avoids blocking work simply because the poll interval is
longer than the five-minute diagnostic cache. The worker needs `factory:claim`
and project write access, not administration or credential-binding grants.
Validation uses only the trusted registered destination, never a URL or token
provided by the worker. It may create and remove the documented probe branch.

Concurrent claims wait for the existing project validation and reuse its result.
Within a transaction, admission locks the Work and project, rechecks the exact
lease, project revision, fresh readiness, pending probes and active credential
version, then records the server-only `factory_preflight` event. Its payload
contains the revision, credential version, check time and exact lease expiry,
but no token or connection handle. Generic Work events cannot forge this proof.

Runtime config remains read-only. A valid admission suppresses only
`validation_stale` until this lease expires. Other gaps still block execution.
A changed project revision, rotated or disabled credential, unfinished probe,
changed owner, stopped Work or changed lease invalidates admission. Optional
Gateway Git transport requires the same proof on each operation; a `claimed`
event alone does not authorize Git while preflight is running.

Failed preflight conditionally blocks only the originally reserved lease, records
safe readiness codes and returns `claimed: false`. The worker must not execute
that Work. Cancellation or the five-minute total preflight timeout also attempts
this guarded block; a changed lease is never overwritten. An abrupt process kill
may leave a running lease for operator recovery. Probe recovery remains durable.
Existing JSON-only projects keep their previous claim behavior until registered.

### Upgrade with active work

Existing registered-project leases have no `factory_preflight` proof and are
intentionally not grandfathered into runtime or Git access. Before deployment,
pause new poller claims and let active registered-project work finish on the old
version. Do not interrupt a worker while it is writing a branch. If work cannot
finish, stop that worker in a controlled manner and record its blocked state and
evidence before upgrading. Deploy when no such lease is active, resume polling,
then explicitly retry eligible blocked Work using its existing Work ID.

If deployment already happened with an active legacy lease, runtime reports
`lease_preflight_required`. Stop that worker, inspect and preserve its evidence,
record a guarded blocked transition, and use `gateway_work_retry` followed by a
new claim. Never reset the database row or fabricate an admission event. This
release adds no automatic retry and no migration; existing evidence is preserved.

**Location matters:** this release reports `checked_from: gateway` and
`worker_environment_verified: false`. It proves Gateway-side API and Git access,
not DNS, VPN, disk, Codex auth or credential delivery inside a Hermes worker.
The worker must perform its own preflight. Tokens and handles are deliberately
absent from runtime responses. Use the optional Gateway Git transport below or
retain the existing worker-managed access during migration. Deployment alone
does not configure Hermes or prove end-to-end worker readiness.

## Gateway Git transport (opt-in)

Set `GATEWAY_FACTORY_GIT_ENABLED=true` on Gateway only after reviewing this mode.
Grant `factory:git` explicitly to the worker service identity through access
administration; `factory:claim` and project write access are also required. This
release does not grant that scope to employees or existing service accounts.

The worker claims an in-scope Factory Work and calls `gateway_factory_git_config`.
The Work must identify the exact `project_path` and `contract.metadata.gitlab_backend`
(the HTTPS GitLab base URL). The lease must be current and owned by that worker.
The server checks the registered repository, readiness and current credential
version for every Git request. Completing, blocking or losing the lease stops access.
Readiness must have been fresh (within 300 seconds) at the server-issued
`factory_preflight` admission for the current project revision and credential
version. The admission is recorded under a lock on the owned lease and contains
its exact expiry. A valid long lease can continue past the diagnostic cache TTL;
every Git operation still authenticates upstream and checks current connection
state/version. A new lease requires fresh preflight admission. Older `claimed`
events alone cannot authorize Git; follow the active-work upgrade procedure above.

The returned URL is `/factory/git/<work_id>/repo.git`. Authenticate with the
worker's Gateway bearer, or HTTP Basic username `factory` and the same Gateway
token as password. Never put either token in a URL. Gateway sends the GitLab
credential upstream only; neither the worker nor MCP receives it.

The distribution includes a worker wrapper (requires Git and the Gateway Python
package in the worker environment). Inject `GATEWAY_MCP_TOKEN` through the existing
worker secret environment, never through command arguments:

```bash
python -m gateway_mcp.factory_git_client --gateway https://gateway.example \
  --work-id work-11111111-1111-1111-1111-111111111111 \
  --directory /workspace/task --base-branch dev clone

# Create a worktree/local branch and implement/test normally, then:
python -m gateway_mcp.factory_git_client --gateway https://gateway.example \
  --work-id work-11111111-1111-1111-1111-111111111111 \
  --directory /workspace/task push
```

Use the actual Work ID. The wrapper pushes HEAD only to `codex/<work_id>` and
passes Gateway authorization in the Git subprocess environment. It writes no
credential to `.git/config`. GitLab web URL, project path and MR target remain
canonical; MR creation/review continues through Gateway GitLab routes. This
transport does not implement multi-instance MR routing or change Hermes prompts
automatically. Enable it in the worker launch flow deliberately and run preflight.

Only smart HTTP upload-pack and receive-pack are supported. Before any push bytes
reach GitLab, Gateway checks packet framing and permits exactly one non-delete
update to the assigned work branch. Base/target branches, tags, extra refs,
push-options (including server-side merge/CI-variable options) and signed-push
extensions are denied. HTTP redirects and browser-cookie auth are denied.
Git v0 and SHA-1 repositories are supported; LFS, recursive submodules and
repositories exceeding the bounded transfer size require a separate design.

Limits: 64 MiB request, 128 MiB response, two concurrent transfers per Gateway
process and 90 seconds total including queueing. Configure the reverse proxy's
body and timeout limits accordingly. GitLab branch protection and CI deployment
permissions must remain enforced: a normal branch push may trigger project CI.
The transport itself never runs repository code, creates MRs, merges or deploys.

Rollback this mode by setting `GATEWAY_FACTORY_GIT_ENABLED=false`; saved service
connections and project registrations remain intact. Preserve the encryption key.

## Work retry

```json
{"work_id":"work-example","idempotency_key":"retry-after-connection-fix-1"}
```

Only in-scope, blocked, Factory-mode work can be retried. Reviewer, project
context and repository mapping must also be present. A transaction locks the
work, rechecks the project revision and credential version/state, records the
retry receipt and event, and changes `blocked` to `queued`. It clears the claim,
lease and failed completion timestamp. It preserves Work ID, source, criteria,
evidence, correction count and original start time. A duplicate key never queues
a later failed attempt again. Use a new key for a new deliberate retry.
The queue transition also checks current stored readiness, freshness, pending
validation operations and unfinished probes under the same project lock used
for probe admission. An old successful validation receipt cannot bypass a new
readiness failure. Project lookup and Work matching use canonical lowercase IDs.

Updating a project never automatically queues work. The generic `resumed` event
is rejected for registered projects, so it cannot bypass readiness. Legacy
JSON-only projects keep their existing resume behavior until explicitly onboarded.
The operation does not merge, deploy, grant permissions or close Tracker issues.

## Storage and rollout

1. Apply migration `0019_factory_project_registry` using the normal migration command.
2. Build the Gateway image, which now includes Git; deploy through the existing pipeline.
3. Configure the required encrypted service connections in the admin page.
4. Upsert project configuration, inspect every check, and verify discovery and runtime.
5. Check the same repository from the actual Factory worker before retrying production work.

PostgreSQL stores project configuration and readiness, operation receipts,
probe recovery records and retry receipts. Configuration changes survive container replacement. The old
JSON registry remains a read-only baseline; a stored project with the same
logical ID takes precedence. No secrets or connection handles appear in public
runtime config, project discovery results, Work metadata or new audit events.
Connection aliases are visible only in the admin interface and authorized
connection selector; upstream credentials are never returned there.

Rollback: disable new administration tools by rolling back the application.
Do not drop the new tables or revert migrations destructively. Keep new projects
paused until the restored version can resolve them. Preserve the database and
Gateway encryption key in backups.

## Verification

Unit tests cover scope denial, duplicate requests, revision races, runtime
selection, both branch names, credential redaction, invalid URLs, redirects,
DNS/auth/repository failures, real-probe orchestration and atomic retry behavior.
Live acceptance additionally requires a disposable repository, the actual
Gateway database, GitLab service credentials and the worker environment.

Preflight regressions additionally cover a fifteen-minute queue delay, concurrent
claims, cancellation, timeout, repository/host mismatch, mixed-case logical IDs,
config/credential changes and forged or missing lease proof. Storage admission
tests simulate transaction responses; they do not replace concurrent testing
against a real PostgreSQL instance. Verify claim and runtime through the real
worker after deployment before declaring an end-to-end Factory run successful.

References: [GitLab branches API](https://docs.gitlab.com/api/branches/),
[Git push leases](https://git-scm.com/docs/git-push),
[Git HTTP protocol](https://git-scm.com/docs/http-protocol),
[Git pack protocol](https://git-scm.com/docs/pack-protocol).

Local integration test with real Git and synthetic credentials:
`uv run python tests/factory_git_roundtrip.py`. It checks clone, commit and push
through the actual HTTP route, denial of main before forwarding, lease invalidation
and absence of persisted tokens. It is separate from dependency-stub unit tests.
