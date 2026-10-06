import unittest
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.factory_projects import (
    discover_factory_projects,
    get_factory_runtime_config,
    resolve_factory_project_by_issue,
)
from gateway_mcp.services.policy import GatewayActor

TOOLS_REGISTRY = {
    "tools": [
        {
            "name": "tracker.issues.get",
            "backend": "yandex-tracker",
            "scope": "tracker:read",
        },
        {
            "name": "tracker.queues.list",
            "backend": "yandex-tracker",
            "scope": "tracker:read",
        },
        {"name": "gitlab.project.get", "backend": "gitlab", "scope": "gitlab:read"},
        {"name": "gitlab.projects.search", "backend": "gitlab", "scope": "gitlab:read"},
    ]
}

TRACKER_PROJECT_REGISTRY = {
    "projects": [
        {
            "project_id": "factory-demo",
            "name": "Factory Demo",
            "tracker_project_id": "80",
            "tracker_project_name": "Factory Demo",
            "tracker_queue": "TEST",
            "gitlab_project": "ai-factory/agent-dev-factory",
        }
    ],
    "queue_fallback": {"mode": "allowlist", "queues": ["TEST"]},
}


class FactoryProjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_config_resolves_execution_context_from_work_contract(
        self,
    ) -> None:
        work = {
            "work_id": "work-demo",
            "project_id": "factory-demo",
            "project_path": "ai-factory/agent-dev-factory",
            "scope_id": "scope-1",
            "source_type": "chat",
            "source_ref": "slack://dev-factory/1",
            "source_refs": [
                {
                    "type": "project_context",
                    "uri": "https://wiki.example.com/doc/factory-demo",
                    "title": "Factory Demo",
                }
            ],
            "contract": {
                "project_path": "ai-factory/agent-dev-factory",
                "scope_id": "scope-1",
                "metadata": {"reviewer": "Jane Roe"},
            },
        }

        async def fake_backend(route, arguments):
            self.assertEqual(route["name"], "gitlab.project.get")
            self.assertEqual(arguments["project_id"], "ai-factory/agent-dev-factory")
            return {
                "ok": True,
                "data": {
                    "id": 242,
                    "name": "agent-dev-factory",
                    "path_with_namespace": "ai-factory/agent-dev-factory",
                    "http_url_to_repo": "https://gitlab.example.com/ai-factory/agent-dev-factory.git",
                    "web_url": "https://gitlab.example.com/ai-factory/agent-dev-factory",
                    "default_branch": "main",
                },
            }

        with (
            patch("gateway_mcp.services.factory_projects.get_work", return_value=work),
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
        ):
            result = await get_factory_runtime_config(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                work_id="work-demo",
            )

        project = result["project"]
        self.assertEqual(project["source"], "work_contract")
        self.assertEqual(project["gitlab_project"], "242")
        self.assertEqual(
            project["gitlab_clone_url"],
            "https://gitlab.example.com/ai-factory/agent-dev-factory.git",
        )
        self.assertEqual(project["reviewer"], "Jane Roe")
        self.assertEqual(project["yonote_project_name"], "Factory Demo")
        self.assertEqual(project["scope_id"], "scope-1")
        self.assertEqual(project["tracker_queue"], "")
        self.assertEqual(project["readiness_gaps"], [])

    async def test_resolve_issue_builds_runtime_config_from_tracker_and_gitlab(
        self,
    ) -> None:
        async def fake_backend(route, arguments):
            if route["name"] == "tracker.issues.get":
                return {
                    "ok": True,
                    "data": {
                        "key": "TEST-80",
                        "summary": "Factory demo",
                        "description": (
                            "Target repo: https://gitlab.example.com/ai-factory/agent-dev-factory\n"
                            "ADR: https://wiki.example.com/doc/adr-demo"
                        ),
                        "queue": {"key": "TEST", "display": "Testing"},
                        "project": {
                            "primary": {"id": "80", "display": "Factory Demo"},
                            "secondary": [],
                        },
                        "assignee": {"display": "Jane Roe"},
                        "status": {"display": "Open"},
                    },
                }
            if route["name"] == "gitlab.project.get":
                self.assertEqual(
                    arguments["project_id"], "ai-factory/agent-dev-factory"
                )
                return {
                    "ok": True,
                    "data": {
                        "id": 242,
                        "name": "agent-dev-factory",
                        "path_with_namespace": "ai-factory/agent-dev-factory",
                        "http_url_to_repo": "https://gitlab.example.com/ai-factory/agent-dev-factory.git",
                        "web_url": "https://gitlab.example.com/ai-factory/agent-dev-factory",
                        "default_branch": "main",
                    },
                }
            raise AssertionError(route["name"])

        with (
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
            patch(
                "gateway_mcp.services.factory_projects.load_factory_project_registry",
                return_value=TRACKER_PROJECT_REGISTRY,
            ),
        ):
            result = await resolve_factory_project_by_issue(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                issue_id="TEST-80",
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "factory-demo")
        self.assertEqual(project["tracker_queue"], "TEST")
        self.assertEqual(project["tracker_project"]["id"], "80")
        self.assertEqual(project["tracker_project"]["status"], "mapped")
        self.assertEqual(project["project_resolution"]["source"], "tracker_project")
        self.assertEqual(project["gitlab_project"], "242")
        self.assertEqual(project["gitlab_project_path"], "ai-factory/agent-dev-factory")
        self.assertEqual(
            project["gitlab_clone_url"],
            "https://gitlab.example.com/ai-factory/agent-dev-factory.git",
        )
        self.assertEqual(project["reviewer"], "Jane Roe")
        self.assertEqual(
            project["yonote_links"], ["https://wiki.example.com/doc/adr-demo"]
        )
        self.assertFalse(project["allowed_actions"]["can_merge"])
        self.assertFalse(project["allowed_actions"]["can_deploy"])
        self.assertEqual(project["readiness_gaps"], [])

    async def test_resolve_issue_rejects_missing_tracker_project_by_default(
        self,
    ) -> None:
        async def fake_backend(route, arguments):
            if route["name"] == "tracker.issues.get":
                return {
                    "ok": True,
                    "data": {
                        "key": "TEST-81",
                        "summary": "Legacy issue",
                        "description": (
                            "Target repo: https://gitlab.example.com/should/not-bind"
                        ),
                        "queue": {"key": "TEST", "display": "Testing"},
                        "assignee": {"display": "Jane Roe"},
                    },
                }
            if route["name"] == "gitlab.projects.search":
                return {"ok": True, "data": []}
            raise AssertionError(route["name"])

        with (
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
            patch(
                "gateway_mcp.services.factory_projects.load_factory_project_registry",
                return_value=TRACKER_PROJECT_REGISTRY,
            ),
        ):
            result = await resolve_factory_project_by_issue(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                issue_id="TEST-81",
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "unresolved-tracker-project")
        self.assertEqual(project["project_resolution"]["source"], "unresolved")
        self.assertEqual(project["tracker_project"]["status"], "missing")
        self.assertIn("tracker_project", project["readiness_gaps"])

    async def test_resolve_issue_uses_queue_fallback_only_when_explicit(self) -> None:
        async def fake_backend(route, arguments):
            if route["name"] == "tracker.issues.get":
                return {
                    "ok": True,
                    "data": {
                        "key": "TEST-81",
                        "summary": "Legacy issue",
                        "description": "",
                        "queue": {"key": "TEST", "display": "Testing"},
                    },
                }
            if route["name"] == "gitlab.projects.search":
                return {"ok": True, "data": []}
            raise AssertionError(route["name"])

        with (
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
            patch(
                "gateway_mcp.services.factory_projects.load_factory_project_registry",
                return_value=TRACKER_PROJECT_REGISTRY,
            ),
        ):
            result = await resolve_factory_project_by_issue(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                issue_id="TEST-81",
                allow_queue_fallback=True,
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "test")
        self.assertEqual(project["project_resolution"]["source"], "queue_fallback")
        self.assertEqual(project["tracker_project"]["status"], "missing")
        self.assertIn("tracker_project", project["readiness_gaps"])

    async def test_resolve_issue_rejects_unknown_tracker_project_before_queue_fallback(
        self,
    ) -> None:
        async def fake_backend(route, arguments):
            if route["name"] == "tracker.issues.get":
                return {
                    "ok": True,
                    "data": {
                        "key": "TEST-82",
                        "summary": "Unknown project",
                        "description": "",
                        "queue": {"key": "TEST", "display": "Testing"},
                        "project": {
                            "primary": {"id": "999", "display": "Unknown"},
                            "secondary": [],
                        },
                        "assignee": {"display": "Jane Roe"},
                    },
                }
            raise AssertionError(route["name"])

        with (
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
            patch(
                "gateway_mcp.services.factory_projects.load_factory_project_registry",
                return_value=TRACKER_PROJECT_REGISTRY,
            ),
        ):
            result = await resolve_factory_project_by_issue(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                issue_id="TEST-82",
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "tracker-project-999")
        self.assertEqual(project["project_resolution"]["source"], "unresolved")
        self.assertEqual(project["tracker_project"]["status"], "unknown")
        self.assertIn("tracker_project", project["readiness_gaps"])

    async def test_registered_logical_project_is_not_used_as_gitlab_project(
        self,
    ) -> None:
        work = {
            "work_id": "work-acme",
            "project_id": "acme-claims",
            "contract": {"metadata": {}},
            "source_refs": [],
        }
        registry = {
            "schema_version": "1.0",
            "projects": [
                {
                    "project_id": "acme-claims",
                    "name": "Acme Claims Processing",
                    "tracker_project_id": "292",
                    "tracker_project_name": "Acme Claims Processing",
                    "tracker_queue": "PM",
                    "yonote_project_name": "Acme Claims Processing",
                    "yonote_links": [],
                }
            ],
            "queue_fallback": {"mode": "allowlist", "queues": []},
        }

        with (
            patch("gateway_mcp.services.factory_projects.get_work", return_value=work),
            patch(
                "gateway_mcp.services.factory_projects.load_factory_project_registry",
                return_value=registry,
            ),
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=AssertionError("GitLab must not be queried")),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
        ):
            result = await get_factory_runtime_config(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                work_id="work-acme",
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "acme-claims")
        self.assertEqual(project["gitlab_project"], "")
        self.assertEqual(project["tracker_project"]["id"], "292")
        self.assertIn("gitlab_project", project["readiness_gaps"])

    async def test_unregistered_logical_project_is_not_used_as_gitlab_project(
        self,
    ) -> None:
        with (
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=AssertionError("GitLab must not be queried")),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
        ):
            result = await get_factory_runtime_config(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                project_id="logical-project",
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "logical-project")
        self.assertEqual(project["gitlab_project"], "")
        self.assertIn("gitlab_project", project["readiness_gaps"])

    async def test_registered_tracker_project_resolves_runtime_context(self) -> None:
        async def fake_backend(route, arguments):
            if route["name"] == "tracker.issues.get":
                return {
                    "ok": True,
                    "data": {
                        "key": "PM-83",
                        "summary": "Acme claims pilot",
                        "description": (
                            "Target repo: https://gitlab.example.com/should/not-bind"
                        ),
                        "queue": {"key": "PM", "display": "Projects"},
                        "project": {
                            "primary": {
                                "id": "292",
                                "display": "Acme Claims Processing",
                            },
                            "secondary": [],
                        },
                        "assignee": {"display": "Jane Roe"},
                    },
                }
            raise AssertionError(route["name"])

        registry = {
            "schema_version": "1.0",
            "projects": [
                {
                    "project_id": "acme-claims",
                    "name": "Acme Claims Processing",
                    "tracker_project_id": "292",
                    "tracker_project_name": "Acme Claims Processing",
                    "tracker_queue": "PM",
                    "yonote_project_name": "Acme Claims Processing",
                    "yonote_links": [],
                }
            ],
            "queue_fallback": {"mode": "allowlist", "queues": []},
        }

        with (
            patch(
                "gateway_mcp.services.factory_projects.load_factory_project_registry",
                return_value=registry,
            ),
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
        ):
            result = await resolve_factory_project_by_issue(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                issue_id="PM-83",
            )

        project = result["project"]
        self.assertEqual(project["project_id"], "acme-claims")
        self.assertEqual(project["tracker_queue"], "PM")
        self.assertEqual(project["tracker_project"]["status"], "mapped")
        self.assertNotIn("tracker_project", project["readiness_gaps"])
        self.assertEqual(project["gitlab_project"], "")
        self.assertIn("gitlab_project", project["readiness_gaps"])

    async def test_discover_projects_returns_tracker_and_gitlab_candidates(
        self,
    ) -> None:
        async def fake_backend(route, arguments):
            if route["name"] == "tracker.queues.list":
                return {"ok": True, "data": [{"key": "ABC", "display": "Client ABC"}]}
            if route["name"] == "gitlab.projects.search":
                return {
                    "ok": True,
                    "data": [
                        {
                            "id": 17,
                            "name": "abc-service",
                            "path_with_namespace": "clients/abc-service",
                            "http_url_to_repo": "https://gitlab.example.com/clients/abc-service.git",
                            "web_url": "https://gitlab.example.com/clients/abc-service",
                            "default_branch": "main",
                        }
                    ],
                }
            raise AssertionError(route["name"])

        with (
            patch(
                "gateway_mcp.services.factory_projects.call_backend",
                AsyncMock(side_effect=fake_backend),
            ),
            patch("gateway_mcp.services.factory_projects.require_scope"),
            patch("gateway_mcp.services.factory_projects.require_resource_access"),
        ):
            result = await discover_factory_projects(
                actor=GatewayActor(subject="u1", email="u1@example.com"),
                tools_registry=TOOLS_REGISTRY,
                query="",
                limit=10,
            )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["projects"][0]["tracker_queue"], "ABC")
        self.assertIn("gitlab_clone_url", result["projects"][0]["readiness_gaps"])
        self.assertEqual(
            result["projects"][1]["gitlab_project_path"], "clients/abc-service"
        )
        self.assertEqual(
            result["projects"][1]["gitlab_clone_url"],
            "https://gitlab.example.com/clients/abc-service.git",
        )


if __name__ == "__main__":
    unittest.main()
