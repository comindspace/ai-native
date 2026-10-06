import unittest

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services.storage_idempotency import _validate_key, request_fingerprint


class IdempotencyTests(unittest.TestCase):
    def test_request_fingerprint_is_stable_for_key_order(self) -> None:
        self.assertEqual(
            request_fingerprint(
                {"id": 42, "fields": {"TITLE": "Deal", "STAGE": "NEW"}}
            ),
            request_fingerprint(
                {"fields": {"STAGE": "NEW", "TITLE": "Deal"}, "id": 42}
            ),
        )

    def test_idempotency_key_rejects_control_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "control characters"):
            _validate_key("call-1\ncall-2")

    def test_idempotency_key_has_a_size_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 to 200"):
            _validate_key("x" * 201)


if __name__ == "__main__":
    unittest.main()
