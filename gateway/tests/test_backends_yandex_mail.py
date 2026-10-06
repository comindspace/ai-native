import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.common import BackendRouteError
from gateway_mcp.backends.yandex_mail import (
    _imap_mailbox_literal,
    _imap_select_name,
    _imap_utf7_decode,
    _imap_utf7_encode,
    _parse_imap_list_line,
)
import gateway_mcp.backends.yandex_mail as yandex_mail_module


class ImapUtf7CodecTests(unittest.TestCase):
    def test_ascii_passthrough(self) -> None:
        self.assertEqual(_imap_utf7_encode("INBOX"), "INBOX")
        self.assertEqual(_imap_utf7_decode("INBOX"), "INBOX")

    def test_cyrillic_roundtrip(self) -> None:
        name = "Хрень"
        encoded = _imap_utf7_encode(name)
        self.assertTrue(encoded.startswith("&") and encoded.endswith("-"))
        self.assertNotIn("Х", encoded)
        self.assertEqual(_imap_utf7_decode(encoded), name)

    def test_ampersand_escaping(self) -> None:
        self.assertEqual(_imap_utf7_encode("A&B"), "A&-B")
        self.assertEqual(_imap_utf7_decode("A&-B"), "A&B")

    def test_nested_cyrillic_roundtrip(self) -> None:
        name = "Мои папки/Хрень"
        self.assertEqual(_imap_utf7_decode(_imap_utf7_encode(name)), name)

    def test_slash_stays_outside_base64_chunks(self) -> None:
        name = "a/Хрень"
        encoded = _imap_utf7_encode(name)
        self.assertTrue(encoded.startswith("a/"))
        self.assertNotIn("/", encoded[2:])
        self.assertEqual(_imap_utf7_decode(encoded), name)


class ImapMailboxLiteralTests(unittest.TestCase):
    def test_quotes_ascii_name(self) -> None:
        self.assertEqual(_imap_mailbox_literal("Archive"), '"Archive"')

    def test_encodes_and_quotes_cyrillic_name(self) -> None:
        literal = _imap_mailbox_literal("Хрень")
        self.assertTrue(literal.startswith('"&'))
        self.assertTrue(literal.endswith('"'))
        inner = literal[1:-1]
        self.assertEqual(_imap_utf7_decode(inner), "Хрень")


class ParseImapListLineTests(unittest.TestCase):
    def test_parses_quoted_utf7_folder(self) -> None:
        encoded = _imap_utf7_encode("Хрень")
        entry = _parse_imap_list_line(f'(\\HasNoChildren) "/" "{encoded}"')
        self.assertEqual(entry["name"], "Хрень")
        self.assertEqual(entry["raw_name"], encoded)
        self.assertEqual(entry["delimiter"], "/")
        self.assertEqual(entry["flags"], ["\\HasNoChildren"])

    def test_parses_inbox_with_nil_delimiter(self) -> None:
        entry = _parse_imap_list_line('(\\HasNoChildren) NIL "INBOX"')
        self.assertEqual(entry["name"], "INBOX")
        self.assertEqual(entry["delimiter"], "")

    def test_returns_none_for_garbage(self) -> None:
        self.assertIsNone(_parse_imap_list_line("garbage line"))


class ImapSelectNameTests(unittest.TestCase):
    def test_ascii_atom_stays_plain(self) -> None:
        self.assertEqual(_imap_select_name("INBOX"), "INBOX")
        self.assertEqual(_imap_select_name("Archive"), "Archive")

    def test_cyrillic_becomes_quoted_utf7(self) -> None:
        name = _imap_select_name("Хрень")
        self.assertTrue(name.startswith('"&'))
        self.assertEqual(_imap_utf7_decode(name[1:-1]), "Хрень")

    def test_ascii_with_space_is_quoted(self) -> None:
        self.assertEqual(_imap_select_name("Sent Items"), '"Sent Items"')


class YandexMailDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_mark_read_defaults_to_seen(self) -> None:
        captured: dict = {}

        class FakeImap:
            def authenticate(self, mechanism, authobject):
                return ("OK", [b""])

            def select(self, mailbox, readonly):
                captured["mailbox"] = mailbox
                return ("OK", [b""])

            def store(self, message_id, command, flags):
                captured["store"] = (message_id, command, flags)
                return ("OK", [b""])

            def logout(self):
                pass

        import imaplib as imaplib_module
        from unittest.mock import patch as patch_fn

        with (
            patch_fn.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch_fn.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
            patch_fn.object(imaplib_module, "IMAP4_SSL", lambda *a, **kw: FakeImap()),
        ):
            result = yandex_mail_module._mail_mark_read_sync({"id": "5"}, "u", "t")

        self.assertTrue(result["data"]["flags_set"] == ["\\Seen"])
        self.assertEqual(captured["store"], ("5", "+FLAGS.SILENT", "(\\Seen)"))

    async def test_mark_unread_removes_seen(self) -> None:
        captured: dict = {}

        class FakeImap:
            def authenticate(self, mechanism, authobject):
                return ("OK", [b""])

            def select(self, mailbox, readonly):
                return ("OK", [b""])

            def store(self, message_id, command, flags):
                captured["store"] = (message_id, command, flags)
                return ("OK", [b""])

            def logout(self):
                pass

        import imaplib as imaplib_module
        from unittest.mock import patch as patch_fn

        with (
            patch_fn.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch_fn.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
            patch_fn.object(imaplib_module, "IMAP4_SSL", lambda *a, **kw: FakeImap()),
        ):
            result = yandex_mail_module._mail_mark_read_sync({"id": "5", "unread": True}, "u", "t")

        self.assertTrue(result["data"]["unread"])
        self.assertEqual(captured["store"], ("5", "-FLAGS.SILENT", "(\\Seen)"))

    async def test_dispatches_list_folders_with_credentials(self) -> None:
        with (
            patch.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
            patch.object(
                yandex_mail_module,
                "_mail_list_folders_sync",
                return_value={"ok": True, "backend": "yandex-mail"},
            ) as sync,
        ):
            result = await yandex_mail_module._call_yandex_mail({"operation": "list_folders"}, {})

        self.assertEqual(result, {"ok": True, "backend": "yandex-mail"})
        sync.assert_called_once_with({}, "user@example.com", "token")

    async def test_dispatches_move_message_with_arguments(self) -> None:
        arguments = {"mailbox": "INBOX", "id": "42", "destination": "Хрень"}
        with (
            patch.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
            patch.object(
                yandex_mail_module,
                "_mail_move_sync",
                return_value={"ok": True, "backend": "yandex-mail", "data": {"moved": True}},
            ) as sync,
        ):
            result = await yandex_mail_module._call_yandex_mail({"operation": "move_message"}, arguments)

        self.assertTrue(result["data"]["moved"])
        sync.assert_called_once_with(arguments, "user@example.com", "token")

    async def test_move_requires_id(self) -> None:
        with (
            patch.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
        ):
            with self.assertRaises(BackendRouteError):
                await yandex_mail_module._call_yandex_mail({"operation": "move_message"}, {"destination": "Хрень"})

    async def test_move_requires_destination(self) -> None:
        with (
            patch.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
        ):
            with self.assertRaises(BackendRouteError):
                await yandex_mail_module._call_yandex_mail({"operation": "move_message"}, {"id": "42"})

    async def test_unknown_operation_is_rejected(self) -> None:
        with (
            patch.object(yandex_mail_module, "_yandex_user_email", return_value="user@example.com"),
            patch.object(yandex_mail_module, "_yandex_user_token", return_value="token"),
        ):
            with self.assertRaises(BackendRouteError):
                await yandex_mail_module._call_yandex_mail({"operation": "nope"}, {})


if __name__ == "__main__":
    unittest.main()
