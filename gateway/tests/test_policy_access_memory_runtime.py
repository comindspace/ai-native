import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.audit import finish_tool
from gateway_mcp.services import access, memory, policy
from gateway_mcp.tools.runtime import ToolRun


class PolicyTests(unittest.TestCase):
    def test_employee_group_can_submit_access_request(self) -> None:
        from gateway_mcp.services import policy

        actor = policy.actor_from_claims(
            {"sub": "yandex:42", "groups": ["employees"], "scope": "company:read"}
        )

        self.assertTrue(policy.has_scope(actor, "access:request"))

    def test_has_scope_accepts_exact_and_wildcard(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("skills:read",))
        admin = policy.GatewayActor(subject="u2", scopes=("*",))

        self.assertTrue(policy.has_scope(actor, "skills:read"))
        self.assertFalse(policy.has_scope(actor, "tools:call"))
        self.assertTrue(policy.has_scope(admin, "anything:anything"))

    def test_has_scope_allows_domain_admin_to_read(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("access:admin",))

        self.assertTrue(policy.has_scope(actor, "access:read"))
        self.assertFalse(policy.has_scope(actor, "access:write"))
        self.assertFalse(policy.has_scope(actor, "tools:read"))

    def test_actor_from_claims_parses_space_separated_scopes(self) -> None:
        actor = policy.actor_from_claims(
            {"sub": "u1", "email": "a@example.com", "scope": "skills:read tools:call", "groups": ["employees"]}
        )

        self.assertEqual(actor.subject, "u1")
        self.assertIn("skills:read", actor.scopes)
        self.assertIn("tools:call", actor.scopes)
        self.assertIn("telemetry:write", actor.scopes)
        self.assertEqual(actor.groups, ("employees",))

    def test_actor_from_claims_applies_database_scope_grants(self) -> None:
        with patch(
            "gateway_mcp.services.policy.list_active_scope_grants",
            return_value=[{"scope": "infra:read", "effect": "allow"}],
        ):
            actor = policy.actor_from_claims(
                {"sub": "service:hermes", "email": "hermes-service@comind.space", "scope": "tools:call", "groups": ["service-agents"]}
            )

        self.assertIn("tools:call", actor.scopes)
        self.assertIn("infra:read", actor.scopes)

    def test_actor_from_claims_expands_current_policy_group_scopes(self) -> None:
        actor = policy.actor_from_claims(
            {"sub": "u1", "scope": "skills:read", "groups": ["employees"]}
        )

        self.assertIn("skills:read", actor.scopes)
        self.assertIn("telemetry:write", actor.scopes)


class AccessTests(unittest.TestCase):
    def test_subjects_for_actor_includes_user_keys_and_groups(self) -> None:
        actor = policy.GatewayActor(
            subject="Yandex:42",
            email="User@Example.com",
            login="Login",
            yandex_id="42",
            groups=("Employees",),
        )

        self.assertEqual(
            access.subjects_for_actor(actor),
            [
                ("group", "employees"),
                ("user", "42"),
                ("user", "login"),
                ("user", "user@example.com"),
                ("user", "yandex:42"),
            ],
        )

    def test_require_resource_access_denies_in_strict_mode_without_grant(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("tools:call",))
        route = {"name": "gitlab.files.get", "scope": "gitlab:read", "backend": "gitlab"}

        with patch.dict(os.environ, {"GATEWAY_RESOURCE_POLICY_MODE": "strict"}, clear=False):
            with patch("gateway_mcp.services.access_policy.list_active_resource_grants", return_value=[]):
                with self.assertRaises(PermissionError):
                    access.require_resource_access(actor=actor, route=route, arguments={"project_id": "p1"})

    def test_require_resource_access_allows_matching_grant(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("tools:call",))
        route = {"name": "gitlab.files.get", "scope": "gitlab:read", "backend": "gitlab"}
        grants = [
            {
                "effect": "allow",
                "actions": ["read"],
                "resource_type": "project",
                "resource_pattern": "p1",
            }
        ]

        with patch.dict(os.environ, {"GATEWAY_RESOURCE_POLICY_MODE": "strict"}, clear=False):
            with patch("gateway_mcp.services.access_policy.list_active_resource_grants", return_value=grants):
                result = access.require_resource_access(actor=actor, route=route, arguments={"project_id": "p1"})

        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["reason"], "matched_allow")

    def test_gitlab_write_grant_does_not_allow_deploy_action(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("gitlab:deploy",))
        route = {
            "name": "gitlab.pipeline_jobs.play",
            "scope": "gitlab:deploy",
            "backend": "gitlab",
        }
        grants = [
            {
                "effect": "allow",
                "actions": ["write"],
                "resource_type": "project",
                "resource_pattern": "241",
            }
        ]

        with patch.dict(
            os.environ, {"GATEWAY_RESOURCE_POLICY_MODE": "strict"}, clear=False
        ), patch(
            "gateway_mcp.services.access_policy.list_active_resource_grants",
            return_value=grants,
        ), self.assertRaises(PermissionError):
            access.require_resource_access(
                actor=actor,
                route=route,
                arguments={"project_id": 241},
            )

    def test_gitlab_deploy_grant_is_limited_to_matching_project(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("gitlab:deploy",))
        route = {
            "name": "gitlab.pipeline_jobs.play",
            "scope": "gitlab:deploy",
            "backend": "gitlab",
        }
        grants = [
            {
                "effect": "allow",
                "actions": ["deploy"],
                "resource_type": "project",
                "resource_pattern": "241",
            }
        ]

        with patch.dict(
            os.environ, {"GATEWAY_RESOURCE_POLICY_MODE": "strict"}, clear=False
        ), patch(
            "gateway_mcp.services.access_policy.list_active_resource_grants",
            return_value=grants,
        ):
            allowed = access.require_resource_access(
                actor=actor,
                route=route,
                arguments={"project_id": 241},
            )
            with self.assertRaises(PermissionError):
                access.require_resource_access(
                    actor=actor,
                    route=route,
                    arguments={"project_id": 227},
                )

        self.assertEqual(allowed["action"], "deploy")
        self.assertEqual(allowed["resource"], "241")


class MemoryTests(unittest.TestCase):
    def test_parse_tiers_normalizes_and_deduplicates(self) -> None:
        self.assertEqual(memory.parse_tiers('["session", "short", "project"]'), ["short", "medium"])

    def test_resolve_subject_blocks_other_user_without_admin_scope(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("memory:write",))

        with self.assertRaises(PermissionError):
            memory.resolve_subject(actor, "user", "u2")

    def test_normalize_ttl_uses_env_defaults_and_caps_max(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GATEWAY_MEMORY_SHORT_TTL_DAYS": "7",
                "GATEWAY_MEMORY_MEDIUM_TTL_DAYS": "90",
                "GATEWAY_MEMORY_MAX_TTL_DAYS": "30",
            },
            clear=False,
        ):
            self.assertEqual(memory.normalize_ttl("short", None), 7)
            self.assertEqual(memory.normalize_ttl("medium", 90), 30)

    def test_search_obsidian_sources_reads_markdown_frontmatter(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("memory:read",))
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "01-methodology").mkdir()
            (vault / "01-methodology" / "discovery.md").write_text(
                "\n".join(
                    [
                        "---",
                        'title: "AI-Native Discovery"',
                        "scope: company",
                        "sensitivity: internal",
                        "owners:",
                        "  - methodology",
                        "tags: [ai-native, discovery]",
                        "source_status: editorial",
                        "---",
                        "# Discovery",
                        "Process for finding first-wave scenarios.",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GATEWAY_OBSIDIAN_ENABLED": "true", "GATEWAY_OBSIDIAN_VAULT_PATH": str(vault)}, clear=False):
                results = memory.search_obsidian_sources("first-wave", 5, actor)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "obsidian")
        self.assertEqual(results[0]["title"], "AI-Native Discovery")
        self.assertEqual(results[0]["metadata"]["path"], "01-methodology/discovery.md")
        self.assertIn("discovery", results[0]["metadata"]["tags"])

    def test_search_obsidian_sources_hides_restricted_notes_without_admin(self) -> None:
        actor = policy.GatewayActor(subject="u1", scopes=("memory:read",))
        admin = policy.GatewayActor(subject="u2", scopes=("memory:read", "memory:admin"))
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "restricted.md").write_text(
                "\n".join(["---", "title: Restricted", "sensitivity: restricted", "---", "Sensitive playbook"]),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GATEWAY_OBSIDIAN_ENABLED": "true", "GATEWAY_OBSIDIAN_VAULT_PATH": str(vault)}, clear=False):
                self.assertEqual(memory.search_obsidian_sources("Sensitive", 5, actor), [])
                self.assertEqual(len(memory.search_obsidian_sources("Sensitive", 5, admin)), 1)


class ToolRuntimeTests(unittest.TestCase):
    def test_finish_delegates_audit_fields(self) -> None:
        run = ToolRun(tool="tool", system="system", scope="scope:read", arguments={"a": 1}, started_at=123.0)

        with patch("gateway_mcp.tools.runtime.finish_tool") as finish:
            run.finish(status="ok")

        finish.assert_called_once_with(
            tool="tool",
            system="system",
            started_at=123.0,
            status="ok",
            decision="allow",
            scope="scope:read",
            arguments={"a": 1},
            error="",
        )

    def test_denied_records_policy_deny_and_audit(self) -> None:
        run = ToolRun(tool="tool", system="system", scope="scope:read", arguments={}, started_at=123.0)
        exc = PermissionError("missing")

        with patch("gateway_mcp.tools.runtime.deny") as deny, patch("gateway_mcp.tools.runtime.finish_tool") as finish:
            run.denied(exc, deny_tool="backend.tool")

        deny.assert_called_once_with("backend.tool", "scope:read", "missing_scope")
        self.assertEqual(finish.call_args.kwargs["status"], "denied")
        self.assertEqual(finish.call_args.kwargs["decision"], "deny")
        self.assertEqual(finish.call_args.kwargs["error"], "missing")

    def test_require_scope_delegates_to_auth(self) -> None:
        expected = policy.GatewayActor(subject="u1")
        run = ToolRun(tool="tool", system="system", scope="scope:read", arguments={}, started_at=123.0)

        with patch("gateway_mcp.tools.runtime.require_scope", Mock(return_value=expected)) as require:
            result = run.require_scope("scope:write", tool="other")

        self.assertIs(result, expected)
        require.assert_called_once_with("scope:write", tool="other")


class AuditTests(unittest.TestCase):
    def test_finish_tool_records_metrics_and_audit_with_current_signatures(self) -> None:
        with patch("gateway_mcp.services.observability.append_audit_event", return_value=True) as append:
            finish_tool(
                tool="gateway_search_tools",
                system="gateway",
                started_at=123.0,
                status="ok",
                decision="allow",
                scope="tools:read",
                arguments={"query": "gitlab"},
            )

        payload = append.call_args.args[0]
        self.assertEqual(payload["event"], "tool_call")
        self.assertEqual(payload["tool"], "gateway_search_tools")
        self.assertEqual(payload["decision"], "allow")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["actor"]["subject"], "dev:local")
