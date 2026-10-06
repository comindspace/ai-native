import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import knowledge
from gateway_mcp.services.policy import GatewayActor


class KnowledgeTests(unittest.TestCase):
    def test_personal_document_roundtrip_and_search(self) -> None:
        actor = GatewayActor(
            subject="yandex:1",
            email="user@example.com",
            scopes=("memory:read", "memory:write"),
        )
        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_KNOWLEDGE_VAULT_PATH": tmp}, clear=False),
        ):
            stored = knowledge.put_document(
                actor=actor,
                space="",
                title="Personal Note",
                content="Remember the onboarding context.",
                tags_json=json.dumps(["onboarding"]),
                document_id="personal-note",
            )
            fetched = knowledge.get_document(
                actor=actor, space="", document="personal-note"
            )
            results = knowledge.search_documents(
                actor=actor, query="onboarding", limit=5
            )

        self.assertEqual(stored["id"], "personal-note")
        self.assertIn("Remember the onboarding context", fetched["content"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Personal Note")

    def test_group_space_enforces_membership_roles(self) -> None:
        owner = GatewayActor(
            subject="yandex:1",
            email="owner@example.com",
            scopes=("memory:read", "memory:write"),
        )
        reader = GatewayActor(
            subject="yandex:2",
            email="reader@example.com",
            scopes=("memory:read", "memory:write"),
        )
        outsider = GatewayActor(
            subject="yandex:3",
            email="outsider@example.com",
            scopes=("memory:read", "memory:write"),
        )

        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_KNOWLEDGE_VAULT_PATH": tmp}, clear=False),
        ):
            knowledge.create_space(
                actor=owner,
                slug="team-alpha",
                title="Team Alpha",
                members_json=json.dumps(
                    [{"subject": "reader@example.com", "role": "reader"}]
                ),
            )
            knowledge.put_document(
                actor=owner,
                space="team-alpha",
                title="Team Fact",
                content="Shared delivery context.",
                document_id="team-fact",
            )
            read_result = knowledge.get_document(
                actor=reader, space="team-alpha", document="team-fact"
            )
            with self.assertRaises(PermissionError):
                knowledge.put_document(
                    actor=reader,
                    space="team-alpha",
                    title="Nope",
                    content="Cannot write",
                )
            with self.assertRaises(PermissionError):
                knowledge.search_documents(
                    actor=outsider, query="delivery", space="team-alpha"
                )

        self.assertEqual(read_result["title"], "Team Fact")

    def test_reindex_writes_indexes(self) -> None:
        actor = GatewayActor(
            subject="yandex:1",
            email="user@example.com",
            scopes=("memory:read", "memory:write"),
        )
        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_KNOWLEDGE_VAULT_PATH": tmp}, clear=False),
        ):
            knowledge.create_space(actor=actor, slug="ops", title="Operations")
            knowledge.put_document(
                actor=actor,
                space="ops",
                title="Runbook",
                content="Daily operating notes.",
                tags_json='["ops"]',
            )
            result = knowledge.reindex(actor=actor, space="ops")
            spaces_index = Path(tmp) / "indexes" / "spaces.json"
            tags_index = Path(tmp) / "indexes" / "tags.json"

            self.assertTrue(spaces_index.exists())
            self.assertTrue(tags_index.exists())
            self.assertEqual(result["spaces"][0]["documents"], 1)
            self.assertIn("ops", tags_index.read_text(encoding="utf-8"))

    def test_ingest_file_requires_allowed_directory(self) -> None:
        actor = GatewayActor(
            subject="yandex:1",
            email="user@example.com",
            scopes=("memory:read", "memory:write"),
        )
        with TemporaryDirectory() as tmp, TemporaryDirectory() as inbox:
            source = Path(inbox) / "brief.md"
            source.write_text("# Brief\n\nImportant client context.", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GATEWAY_KNOWLEDGE_VAULT_PATH": tmp,
                    "GATEWAY_KNOWLEDGE_INGEST_DIRS": inbox,
                },
                clear=False,
            ):
                result = knowledge.ingest_file(
                    actor=actor, source_path="brief.md", title="Client Brief"
                )

        self.assertEqual(result["title"], "Client Brief")
        self.assertEqual(result["kind"], "source")

    def test_update_keeps_version_and_can_restore_it(self) -> None:
        actor = GatewayActor(
            subject="yandex:1",
            email="user@example.com",
            scopes=("memory:read", "memory:write"),
        )
        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_KNOWLEDGE_VAULT_PATH": tmp}, clear=False),
        ):
            knowledge.put_document(
                actor=actor,
                space="",
                title="Operating Rule",
                content="First approved wording.",
                document_id="operating-rule",
            )
            knowledge.put_document(
                actor=actor,
                space="",
                title="Operating Rule",
                content="Second approved wording.",
                document_id="operating-rule",
            )
            versions = knowledge.list_document_versions(
                actor=actor,
                space="",
                document="operating-rule",
            )
            restored = knowledge.restore_document_version(
                actor=actor,
                space="",
                document="operating-rule",
                version_id=versions[0]["version_id"],
            )
            fetched = knowledge.get_document(
                actor=actor, space="", document="operating-rule"
            )

        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["reason"], "update")
        self.assertEqual(restored["restored_version"], versions[0]["version_id"])
        self.assertIn("First approved wording", fetched["content"])

    def test_delete_moves_document_to_trash_and_restore_recovers_it(self) -> None:
        actor = GatewayActor(
            subject="yandex:1",
            email="user@example.com",
            scopes=("memory:read", "memory:write"),
        )
        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_KNOWLEDGE_VAULT_PATH": tmp}, clear=False),
        ):
            knowledge.put_document(
                actor=actor,
                space="",
                title="Temporary Note",
                content="Content must survive deletion.",
                document_id="temporary-note",
            )
            deleted = knowledge.delete_document(
                actor=actor, space="", document="temporary-note"
            )
            trash = knowledge.list_trash(actor=actor, space="")
            search = knowledge.search_documents(actor=actor, query="survive deletion")
            with self.assertRaises(FileNotFoundError):
                knowledge.get_document(actor=actor, space="", document="temporary-note")
            restored = knowledge.restore_trash(
                actor=actor, space="", trash_id=deleted["trash_id"]
            )
            fetched = knowledge.get_document(
                actor=actor, space="", document="temporary-note"
            )

        self.assertTrue(deleted["soft_deleted"])
        self.assertEqual(trash[0]["trash_id"], deleted["trash_id"])
        self.assertEqual(search, [])
        self.assertEqual(restored["restored_from_trash"], deleted["trash_id"])
        self.assertIn("Content must survive deletion", fetched["content"])

    def test_trash_restore_rejects_path_traversal(self) -> None:
        actor = GatewayActor(
            subject="yandex:1",
            email="user@example.com",
            scopes=("memory:read", "memory:write"),
        )
        with (
            TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GATEWAY_KNOWLEDGE_VAULT_PATH": tmp}, clear=False),
            self.assertRaises(ValueError),
        ):
            knowledge.restore_trash(actor=actor, space="", trash_id="../outside")


if __name__ == "__main__":
    unittest.main()
