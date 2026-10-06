import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GatewayStructureTests(unittest.TestCase):
    def test_root_service_modules_are_compatibility_wrappers(self) -> None:
        wrappers = {
            "gateway_access.py": "access",
            "gateway_auth.py": "auth",
            "gateway_company.py": "company",
            "gateway_memory.py": "memory",
            "gateway_migrations.py": "migrations",
            "gateway_observability.py": "observability",
            "gateway_policy.py": "policy",
            "gateway_storage.py": "storage",
        }
        for file_name, service_name in wrappers.items():
            with self.subTest(file_name=file_name):
                text = (ROOT / file_name).read_text(encoding="utf-8").strip()
                self.assertEqual(
                    text,
                    f"from gateway_mcp.services.{service_name} import *  # noqa: F401,F403",
                )

    def test_package_does_not_import_root_service_modules(self) -> None:
        forbidden = re.compile(
            r"from gateway_(access|auth|company|memory|migrations|observability|policy|storage) import"
        )
        offenders = []
        for path in (ROOT / "gateway_mcp").rglob("*.py"):
            if forbidden.search(path.read_text(encoding="utf-8")):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_declared_backend_transports_are_routed(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        transports = {
            str(item.get("transport"))
            for item in registry.get("tools", [])
            if item.get("transport")
        }
        router_source = (ROOT / "gateway_mcp" / "backends" / "router.py").read_text(encoding="utf-8")
        missing = sorted(transport for transport in transports if f'"{transport}"' not in router_source)
        self.assertEqual(missing, [])

    def test_tracker_worklog_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "tracker.worklogs.list": "tracker:read",
            "tracker.worklogs.search": "tracker:read",
            "tracker.worklogs.create": "tracker:write",
            "tracker.worklogs.update": "tracker:write",
            "tracker.worklogs.delete": "tracker:write",
        }
        for route_name, scope in expected.items():
            with self.subTest(route_name=route_name):
                self.assertIn(route_name, routes)
                self.assertEqual(routes[route_name]["transport"], "tracker-rest")
                self.assertEqual(routes[route_name]["scope"], scope)

    def test_tracker_transition_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "tracker.transitions.list": "tracker:read",
            "tracker.transitions.execute": "tracker:write",
        }
        for route_name, scope in expected.items():
            with self.subTest(route_name=route_name):
                self.assertIn(route_name, routes)
                self.assertEqual(routes[route_name]["transport"], "tracker-rest")
                self.assertEqual(routes[route_name]["scope"], scope)

        self.assertEqual(routes["tracker.transitions.list"]["path"], "v3/issues/{issue_id}/transitions")
        self.assertEqual(
            routes["tracker.transitions.execute"]["path"],
            "v3/issues/{issue_id}/transitions/{transition_id}/_execute",
        )

    def test_bitrix24_sales_pipeline_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "bitrix24.users.list": ("user.get", "bitrix24:read"),
            "bitrix24.users.get": ("user.get", "bitrix24:read"),
            "bitrix24.deals.fields": ("crm.deal.fields", "bitrix24:read"),
            "bitrix24.companies.get": ("crm.company.get", "bitrix24:read"),
            "bitrix24.companies.fields": ("crm.company.fields", "bitrix24:read"),
            "bitrix24.companies.create": ("crm.company.add", "bitrix24:write"),
            "bitrix24.companies.update": ("crm.company.update", "bitrix24:write"),
            "bitrix24.companies.upsert": ("", "bitrix24:write"),
            "bitrix24.sales_funnel.health": ("", "bitrix24:read"),
            "bitrix24.timeline.comments.list": ("crm.timeline.comment.list", "bitrix24:read"),
            "bitrix24.timeline.comment.add": ("crm.timeline.comment.add", "bitrix24:write"),
            "bitrix24.timeline.comment.add_with_files": ("", "bitrix24:write"),
            "bitrix24.deals.attach_file": ("", "bitrix24:write"),
            "bitrix24.disk.folder.uploadfile": ("disk.folder.uploadfile", "bitrix24:write"),
            "bitrix24.disk.storage.uploadfile": ("disk.storage.uploadfile", "bitrix24:write"),
            "bitrix24.activities.list": ("crm.activity.list", "bitrix24:read"),
            "bitrix24.activities.add": ("crm.activity.add", "bitrix24:write"),
            "bitrix24.activities.update": ("crm.activity.update", "bitrix24:write"),
            "bitrix24.leads.update": ("crm.lead.update", "bitrix24:write"),
            "bitrix24.tasks.list": ("tasks.task.list", "bitrix24:read"),
            "bitrix24.tasks.add": ("tasks.task.add", "bitrix24:write"),
            "bitrix24.tasks.update": ("tasks.task.update", "bitrix24:write"),
        }

        for route_name, (method, scope) in expected.items():
            with self.subTest(route_name=route_name):
                route = routes[route_name]
                self.assertEqual(route["backend"], "bitrix24")
                self.assertEqual(route["transport"], "bitrix24-rest")
                if method:
                    self.assertEqual(route["bitrix_method"], method)
                else:
                    self.assertNotIn("bitrix_method", route)
                self.assertEqual(route["scope"], scope)

    def test_google_drive_and_sheets_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "google_sheets.spreadsheets.get": ("sheets", "google_sheets:read"),
            "google_sheets.values.get": ("sheets", "google_sheets:read"),
            "google_sheets.values.batch_get": ("sheets", "google_sheets:read"),
            "google_sheets.values.update": ("sheets", "google_sheets:write"),
            "google_sheets.values.batch_update": ("sheets", "google_sheets:write"),
            "google_sheets.values.append": ("sheets", "google_sheets:write"),
            "google_sheets.spreadsheets.batch_update": ("sheets", "google_sheets:write"),
            "google_drive.files.list": ("drive", "google_drive:read"),
            "google_drive.files.get": ("drive", "google_drive:read"),
            "google_drive.files.download": ("drive", "google_drive:read"),
            "google_drive.files.export": ("drive", "google_drive:read"),
            "google_drive.files.create": ("drive", "google_drive:write"),
            "google_drive.files.copy": ("drive", "google_drive:write"),
            "google_drive.files.update": ("drive", "google_drive:write"),
            "google_drive.files.delete": ("drive", "google_drive:write"),
            "google_drive.permissions.create": ("drive", "google_drive:write"),
            "google_drive.permissions.delete": ("drive", "google_drive:write"),
            "google_docs.documents.get": ("docs", "google_docs:read"),
            "google_docs.documents.create": ("docs", "google_docs:write"),
            "google_docs.documents.batch_update": ("docs", "google_docs:write"),
        }

        for route_name, (api, scope) in expected.items():
            with self.subTest(route_name=route_name):
                route = routes[route_name]
                self.assertEqual(route["transport"], "google-rest")
                self.assertEqual(route["google_api"], api)
                self.assertEqual(route["scope"], scope)

        self.assertTrue(routes["google_drive.files.download"]["binary_response"])
        self.assertEqual(routes["google_drive.files.download"]["fixed_query"], {"alt": "media"})
        self.assertEqual(routes["google_drive.files.create"]["body_arg"], "body")
        self.assertEqual(routes["google_docs.documents.batch_update"]["body_arg"], "body")

    def test_gitlab_review_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "gitlab.merge_requests.changes": ("GET", "gitlab:read"),
            "gitlab.merge_requests.diffs.list": ("GET", "gitlab:read"),
            "gitlab.merge_request_notes.list": ("GET", "gitlab:read"),
            "gitlab.merge_request_notes.create": ("POST", "gitlab:write"),
            "gitlab.merge_requests.merge": ("PUT", "gitlab:write"),
            "gitlab.merge_request_approvals.get": ("GET", "gitlab:read"),
            "gitlab.merge_request_approvals.approve": ("POST", "gitlab:write"),
            "gitlab.pipeline_jobs.list": ("GET", "gitlab:read"),
            "gitlab.pipeline_jobs.get": ("GET", "gitlab:read"),
            "gitlab.pipeline_jobs.trace": ("GET", "gitlab:read"),
            "gitlab.pipeline_jobs.play": ("POST", "gitlab:deploy"),
        }

        for route_name, (method, scope) in expected.items():
            with self.subTest(route_name=route_name):
                route = routes[route_name]
                self.assertEqual(route["backend"], "gitlab")
                self.assertEqual(route["transport"], "gitlab-rest")
                self.assertEqual(route["http_method"], method)
                self.assertEqual(route["scope"], scope)

        self.assertEqual(routes["gitlab.merge_request_notes.create"]["body_arg"], "body")
        self.assertEqual(routes["gitlab.merge_requests.merge"]["body_arg"], "body")
        self.assertEqual(routes["gitlab.pipeline_jobs.trace"]["path"], "projects/{project_id}/jobs/{job_id}/trace")
        self.assertTrue(routes["gitlab.pipeline_jobs.play"]["requires_approval_ref"])
        self.assertTrue(routes["gitlab.pipeline_jobs.play"]["requires_idempotency_key"])

    def test_protected_routes_bind_approval_type_and_idempotency(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        protected_routes = [
            item
            for item in registry.get("tools", [])
            if item.get("requires_approval_ref")
        ]

        self.assertTrue(protected_routes)
        for route in protected_routes:
            with self.subTest(route_name=route.get("name")):
                self.assertTrue(str(route.get("approval_type") or "").strip())
                self.assertTrue(route.get("requires_idempotency_key"))

    def test_yonote_database_row_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}

        route = routes["yonote.database.rows.list"]
        self.assertEqual(route["backend"], "yonote")
        self.assertEqual(route["transport"], "yonote-rpc")
        self.assertEqual(route["rpc_method"], "database.rows.list")
        self.assertEqual(route["scope"], "yonote:read")
        self.assertEqual(
            route["argument_aliases"],
            {
                "database_id": "parentDocumentId",
                "parent_document_id": "parentDocumentId",
            },
        )

        expected_write_routes = [
            "yonote.database.transaction",
            "yonote.database.rows.update_title",
            "yonote.database.rows.update_values",
            "yonote.database.rows.create",
            "yonote.database.rows.delete",
        ]
        for route_name in expected_write_routes:
            with self.subTest(route_name=route_name):
                route = routes[route_name]
                self.assertEqual(route["backend"], "yonote")
                self.assertEqual(route["transport"], "yonote-rpc")
                self.assertEqual(route["rpc_method"], "v2/database/transaction")
                self.assertEqual(route["scope"], "yonote:write")

    def test_yandex_mail_folder_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "mail.folders.list": ("list_folders", "mail:read"),
            "mail.messages.move": ("move_message", "mail:write"),
        }
        for route_name, (operation, scope) in expected.items():
            with self.subTest(route_name=route_name):
                route = routes[route_name]
                self.assertEqual(route["backend"], "yandex-mail")
                self.assertEqual(route["transport"], "yandex-mail")
                self.assertEqual(route["operation"], operation)
                self.assertEqual(route["scope"], scope)

    def test_tool_audit_runtime_is_centralized(self) -> None:
        offenders = []
        for path in (ROOT / "gateway_mcp" / "tools").glob("*.py"):
            if path.name == "runtime.py":
                continue
            source = path.read_text(encoding="utf-8")
            if "finish_tool(" in source or "deny(" in source or "start_timer(" in source:
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_telegram_routes_are_declared(self) -> None:
        registry = json.loads((ROOT / "gateway-tools.json").read_text(encoding="utf-8"))
        routes = {str(item.get("name")): item for item in registry.get("tools", [])}
        expected = {
            "telegram.chats.list": ("list_chats", "telegram:read"),
            "telegram.messages.get": ("get_messages", "telegram:read"),
            "telegram.messages.search": ("search_messages", "telegram:read"),
            "telegram.messages.send": ("send_message", "telegram:write"),
            "telegram.files.download": ("download_file", "telegram:read"),
        }
        for route_name, (operation, scope) in expected.items():
            with self.subTest(route_name=route_name):
                route = routes[route_name]
                self.assertEqual(route["backend"], "telegram")
                self.assertEqual(route["transport"], "telegram")
                self.assertEqual(route["operation"], operation)
                self.assertEqual(route["scope"], scope)

    def test_health_route_imports_auth_enabled(self) -> None:
        source = (ROOT / "gateway_mcp" / "routes" / "health.py").read_text(encoding="utf-8")
        self.assertIn("auth_enabled()", source)
        self.assertIn("from gateway_mcp.services.auth import auth_enabled", source)

    def test_generic_router_exposes_backend_route_as_mcp_header(self) -> None:
        source = (ROOT / "gateway_mcp" / "tools" / "router.py").read_text(encoding="utf-8")
        self.assertIn('json_schema_extra={"x-mcp-header": "Route"}', source)
        self.assertIn('json_schema_extra={"x-mcp-header": "Idempotency-Key"}', source)

    def test_idempotency_uses_a_database_migration(self) -> None:
        migration = (ROOT / "migrations" / "0007_tool_idempotency.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists tool_idempotency_records", migration)
        self.assertIn("primary key (actor_subject, tool_name, idempotency_key)", migration)


if __name__ == "__main__":
    unittest.main()
