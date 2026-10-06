import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.privacy import (
    protect_llm_response,
    sanitize_llm_request,
    sanitize_text,
)


class PrivacyTests(unittest.TestCase):
    def test_standard_policy_masks_personal_data_and_redacts_secrets(self) -> None:
        source = (
            "Email roman@example.com, телефон +7 (999) 123-45-67, "
            "паспорт 45 10 123456, password=top-secret-value"
        )
        result = sanitize_text(source, actor_subject="yandex:1")

        self.assertNotIn("roman@example.com", result.value)
        self.assertNotIn("999) 123", result.value)
        self.assertNotIn("45 10 123456", result.value)
        self.assertNotIn("top-secret-value", result.value)
        self.assertIn("password=[GW_CREDENTIAL_REDACTED]", result.value)
        self.assertEqual(result.summary.pseudonymized, 3)
        self.assertEqual(result.summary.redacted, 1)

    def test_pseudonyms_are_stable_per_actor_and_distinct_between_actors(self) -> None:
        first = sanitize_text("roman@example.com", actor_subject="yandex:1")
        repeated = sanitize_text("roman@example.com", actor_subject="yandex:1")
        other = sanitize_text("roman@example.com", actor_subject="yandex:2")

        self.assertEqual(first.value, repeated.value)
        self.assertNotEqual(first.value, other.value)

    def test_strict_policy_generalizes_financial_values(self) -> None:
        standard = sanitize_text("Бюджет 5 800 000 RUB", actor_subject="yandex:1")
        strict = sanitize_text(
            "Бюджет 5 800 000 RUB", actor_subject="yandex:1", policy="strict"
        )

        self.assertEqual(standard.value, "Бюджет 5 800 000 RUB")
        self.assertEqual(strict.value, "Бюджет [GW_FINANCIAL_VALUE]")

    def test_custom_company_terms_are_pseudonymized(self) -> None:
        with TemporaryDirectory() as tmp:
            terms = Path(tmp) / "terms.json"
            terms.write_text(
                json.dumps({"client": ["Grand Capital"]}), encoding="utf-8"
            )
            with patch.dict(
                os.environ, {"GATEWAY_PRIVACY_TERMS_FILE": str(terms)}, clear=False
            ):
                result = sanitize_text(
                    "Встреча с Grand Capital", actor_subject="yandex:1"
                )

        self.assertNotIn("Grand Capital", result.value)
        self.assertIn("GW_CLIENT", result.value)

    def test_binary_payload_is_omitted_from_sanitized_backend_data(self) -> None:
        encoded = "QUJD" * 1024
        result = sanitize_text(encoded, actor_subject="yandex:1")

        self.assertEqual(result.value, "[GW_BINARY_OMITTED]")
        self.assertEqual(result.summary.by_type["binary_payload"]["redact"], 1)

    def test_llm_round_trip_restores_pseudonyms_but_not_secrets(self) -> None:
        request = {
            "model": "test",
            "messages": [
                {
                    "role": "user",
                    "content": "Почта roman@example.com, password=top-secret-value",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Schema owner schema@example.com",
                    },
                }
            ],
        }
        protected = sanitize_llm_request(request, actor_subject="yandex:1")
        upstream_text = protected.value["messages"][0]["content"]

        self.assertNotIn("roman@example.com", upstream_text)
        self.assertNotIn("top-secret-value", upstream_text)
        self.assertNotIn(
            "schema@example.com",
            protected.value["tools"][0]["function"]["description"],
        )

        response = protect_llm_response(
            {"answer": f"Подтверждаю: {upstream_text}"},
            actor_subject="yandex:1",
            restoration=protected.restoration,
        )
        self.assertIn("roman@example.com", response.value["answer"])
        self.assertNotIn("top-secret-value", response.value["answer"])

    def test_llm_request_rejects_binary_and_provider_side_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "input_file"):
            sanitize_llm_request(
                {
                    "model": "test",
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "input_file", "file_id": "file-1"}],
                        }
                    ],
                },
                actor_subject="yandex:1",
            )
        with self.assertRaisesRegex(ValueError, "conversation state"):
            sanitize_llm_request(
                {"model": "test", "previous_response_id": "resp-1", "input": "go"},
                actor_subject="yandex:1",
            )
        with self.assertRaisesRegex(ValueError, "provider-hosted tool"):
            sanitize_llm_request(
                {
                    "model": "test",
                    "input": "Find it",
                    "tools": [{"type": "web_search"}],
                },
                actor_subject="yandex:1",
            )


if __name__ == "__main__":
    unittest.main()
