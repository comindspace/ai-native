import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import factory_connections as service
from gateway_mcp.services import factory_readiness
from gateway_mcp.services.policy import GatewayActor

ADMIN = GatewayActor(subject="admin", scopes=("factory:admin",))
EDITOR = GatewayActor(subject="editor", scopes=("factory:projects:write",))
SECRET = "never-return-this-upstream-secret"


def connection():
    return {
        "system": "gitlab:test",
        "version": 2,
        "state": "active",
        "expires_at": None,
        "payload": {
            "GITLAB_API_BASE_URL": "https://git.example/api/v4",
            "GITLAB_USERNAME": "oauth2",
            "GITLAB_TOKEN": SECRET,
            "FACTORY_ALLOWED_REPOSITORIES": '["team/repo"]',
        },
    }


class ConnectionTests(unittest.TestCase):
    def test_factory_admin_cannot_change_shared_gitlab_endpoint(self):
        with patch.object(service.store, "upsert_service_connection") as save:
            with self.assertRaises(PermissionError):
                service.save_connection(
                    actor=ADMIN,
                    reference="gitlab",
                    api_url="https://different.example/api/v4",
                    username="oauth2",
                    token=SECRET,
                    repositories="team/repo",
                    expires_at=None,
                    expected_version=0,
                )
            with self.assertRaises(PermissionError):
                service.disable_connection(
                    actor=ADMIN, reference="gitlab", expected_version=0
                )
            save.assert_not_called()

    def test_shared_url_form_passes_read_version_to_storage(self):
        from gateway_mcp.services import managed_integrations

        row = {
            "version": 3,
            "payload": {"GITLAB_API_BASE_URL": "https://git.example/api/v4"},
        }
        with (
            patch.object(
                managed_integrations, "get_service_connection", return_value=row
            ),
            patch.object(
                managed_integrations,
                "upsert_service_connection",
                side_effect=ValueError("concurrent service token save"),
            ) as save,
        ):
            with self.assertRaises(ValueError):
                managed_integrations.save_integration(
                    "gitlab",
                    values={"GITLAB_API_BASE_URL": "https://git.example/api/v4"},
                    clear_fields=set(),
                    updated_by="admin",
                    expires_at=None,
                )
            self.assertEqual(save.call_args.kwargs["expected_version"], 3)

    def test_bind_preserves_browser_revision_through_validation(self):
        from gateway_mcp.services import factory_admin

        config = {
            "project_id": "p",
            "project_path": "team/repo",
            "gitlab_web_url": "https://git.example/team/repo",
            "gitlab_clone_url": "https://git.example/team/repo.git",
            "default_base_branch": "main",
            "mr_target_branch": "main",
            "gitlab_connection_id": "gitlab:test",
        }
        with (
            patch.object(
                factory_admin.storage_factory, "begin_operation", return_value=None
            ),
            patch.object(
                factory_admin.storage_factory,
                "get_project",
                return_value={"revision": 4},
            ),
            patch.object(factory_admin.storage_factory, "fail_operation"),
            patch.object(
                factory_admin, "validate_repository", new=AsyncMock()
            ) as validate,
            patch.object(factory_admin.storage_factory, "save_project") as save,
        ):
            with self.assertRaises(ValueError):
                asyncio.run(
                    factory_admin.upsert_project(
                        actor=ADMIN,
                        config=config,
                        idempotency_key="bind-test",
                        expected_revision=3,
                    )
                )
            validate.assert_not_called()
            save.assert_not_called()

    def test_save_preserves_secret_and_cas(self):
        with (
            patch.object(
                service.store, "get_service_connection", return_value=connection()
            ),
            patch.object(service.store, "upsert_service_connection") as save,
            patch.object(service, "audit_event") as audit,
        ):
            service.save_connection(
                actor=ADMIN,
                reference="gitlab:test",
                api_url="https://git.example/api/v4",
                username="oauth2",
                token="",
                repositories="team/repo",
                expires_at=None,
                expected_version=2,
            )
            self.assertEqual(save.call_args.kwargs["payload"]["GITLAB_TOKEN"], SECRET)
            self.assertEqual(save.call_args.kwargs["expected_version"], 2)
            self.assertNotIn(SECRET, str(audit.call_args))
            self.assertNotIn("gitlab:test", str(audit.call_args))

    def test_reject_new_host_without_new_token(self):
        with (
            patch.object(
                service.store, "get_service_connection", return_value=connection()
            ),
            patch.object(service.store, "upsert_service_connection") as save,
        ):
            with self.assertRaises(ValueError):
                service.save_connection(
                    actor=ADMIN,
                    reference="gitlab:test",
                    api_url="https://different.example/api/v4",
                    username="oauth2",
                    token="",
                    repositories="team/repo",
                    expires_at=None,
                    expected_version=2,
                )
            save.assert_not_called()

    def test_save_requires_admin(self):
        with self.assertRaises(PermissionError):
            service.save_connection(
                actor=EDITOR,
                reference="gitlab:test",
                api_url="https://git.example/api/v4",
                username="oauth2",
                token=SECRET,
                repositories="team/repo",
                expires_at=None,
                expected_version=0,
            )

    def test_reject_stale_version(self):
        with (
            patch.object(
                service.store, "get_service_connection", return_value=connection()
            ),
            self.assertRaises(ValueError),
        ):
            service.save_connection(
                actor=ADMIN,
                reference="gitlab:test",
                api_url="https://git.example/api/v4",
                username="oauth2",
                token=SECRET,
                repositories="team/repo",
                expires_at=None,
                expected_version=1,
            )

    def test_validate_repositories(self):
        for raw in [
            "",
            "*",
            "team/*",
            "https://git.example/team/repo",
            "team/../repo",
            "team/repo.git",
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                service.repository_paths(raw)
        self.assertEqual(service.repository_paths("a/b\na/c a/b"), ["a/b", "a/c"])

    def test_readiness_respects_repository_restrictions(self):
        with patch.object(
            factory_readiness, "get_service_connection", return_value=connection()
        ):
            settings = factory_readiness.connection_settings("gitlab:test")
        config = {
            "project_path": "other/repo",
            "gitlab_web_url": "https://git.example/other/repo",
            "gitlab_clone_url": "https://git.example/other/repo.git",
        }
        with self.assertRaises(ValueError):
            factory_readiness.check_destination(config, settings)

    def test_legacy_connection_compatibility(self):
        row = connection()
        del row["payload"]["FACTORY_ALLOWED_REPOSITORIES"]
        with patch.object(
            factory_readiness, "get_service_connection", return_value=row
        ):
            self.assertIsNone(
                factory_readiness.connection_settings("gitlab:test")["repositories"]
            )

    def test_cards_hide_secrets(self):
        with (
            patch.object(
                service.store, "list_service_connections", return_value=[connection()]
            ),
            patch.object(
                service.store, "get_service_connection", return_value=connection()
            ),
            patch.object(service.storage_factory, "list_projects", return_value=[]),
        ):
            result = service.connection_cards(ADMIN)
        self.assertEqual(result[0]["state"], "active")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn("payload", result[0])

    def test_discovery_requires_explicit_both_grants(self):
        settings = {
            "base_url": "https://git.example",
            "repositories": ["team/repo"],
            "version": 2,
        }
        with (
            patch("gateway_mcp.services.factory_admin.require_project_admin"),
            patch.object(
                service.store, "list_service_connections", return_value=[connection()]
            ),
            patch.object(service, "connection_settings", return_value=settings),
            patch.object(
                service,
                "explain_resource_access",
                return_value={"decision": "allow", "reason": "permissive_mode"},
            ),
        ):
            self.assertEqual(
                service.discover_connections(
                    actor=EDITOR,
                    project_id="project",
                    repository_url="https://git.example/team/repo",
                ),
                [],
            )

    def test_discovery_filters_host_and_repository(self):
        settings = {
            "base_url": "https://git.example",
            "repositories": ["team/repo"],
            "version": 2,
        }
        with (
            patch.object(
                service.store, "list_service_connections", return_value=[connection()]
            ),
            patch.object(service, "connection_settings", return_value=settings),
        ):
            for url in [
                "https://other.example/team/repo",
                "https://git.example/other/repo",
            ]:
                self.assertEqual(
                    service.discover_connections(
                        actor=ADMIN, project_id="p", repository_url=url
                    ),
                    [],
                )
            self.assertEqual(
                len(
                    service.discover_connections(
                        actor=ADMIN,
                        project_id="p",
                        repository_url="https://git.example/team/repo",
                    )
                ),
                1,
            )

    def test_check_authenticates_and_redacts_errors(self):
        for status, code in [
            (200, "authenticated"),
            (401, "authentication_denied"),
            (403, "authentication_denied"),
            (302, "redirect_denied"),
            (500, "upstream_error"),
        ]:
            client = MagicMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(
                return_value=MagicMock(status_code=status, text=SECRET)
            )
            with (
                self.subTest(status=status),
                patch.object(
                    service,
                    "connection_settings",
                    return_value={
                        "api_url": "https://git.example/api/v4",
                        "token": SECRET,
                        "version": 2,
                    },
                ),
                patch.object(service.httpx, "AsyncClient", return_value=client),
                patch.object(
                    service.store, "record_service_connection_check", return_value=True
                ) as record,
            ):
                result = asyncio.run(service.check_connection("gitlab:test"))
                self.assertEqual(result["code"], code)
                self.assertNotIn(SECRET, str(result))
                self.assertEqual(
                    client.get.call_args.kwargs["headers"]["PRIVATE-TOKEN"], SECRET
                )
                self.assertEqual(record.call_args.kwargs["expected_version"], 2)

    def test_check_missing_connection_does_not_call_gitlab(self):
        with (
            patch.object(
                service, "connection_settings", side_effect=ValueError(SECRET)
            ),
            patch.object(service.httpx, "AsyncClient") as client,
        ):
            result = asyncio.run(service.check_connection("gitlab:test"))
            self.assertEqual(result["code"], "connection_unavailable")
            self.assertNotIn(SECRET, str(result))
            client.assert_not_called()

    def test_expired_connection_fails_closed(self):
        row = connection()
        row["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with (
            patch.object(factory_readiness, "get_service_connection", return_value=row),
            self.assertRaises(ValueError),
        ):
            factory_readiness.connection_settings("gitlab:test")

    def test_shared_gitlab_save_cannot_drop_factory_secret(self):
        from gateway_mcp.services import managed_integrations

        with (
            patch.object(
                managed_integrations,
                "get_service_connection",
                return_value=connection(),
            ),
            self.assertRaises(ValueError),
        ):
            managed_integrations.save_integration(
                "gitlab",
                values={"GITLAB_API_BASE_URL": "https://git.example/api/v4"},
                clear_fields=set(),
                updated_by="admin",
                expires_at=None,
            )

    def test_shared_gitlab_check_has_no_anonymous_probe(self):
        from gateway_mcp.services import managed_integrations

        with patch.object(
            service,
            "check_connection",
            new=AsyncMock(
                return_value={
                    "ok": False,
                    "code": "connection_unavailable",
                    "message": "missing",
                }
            ),
        ) as check:
            result = asyncio.run(managed_integrations.check_integration("gitlab"))
            self.assertEqual(result["code"], "connection_unavailable")
            check.assert_awaited_once_with("gitlab")
