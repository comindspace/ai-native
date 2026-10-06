import asyncio
import base64
import email.utils
import json
import os
import re
import ssl
from email.message import EmailMessage
from typing import Any

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError, _xoauth2_string, _yandex_user_email, _yandex_user_token


_BOUNCE_FROM_MARKERS = ("mailer-daemon", "postmaster@", "mail-daemon", "no-reply@delivery", "auto-reply")
_BOUNCE_SUBJECT_MARKERS = (
    "undelivered mail returned",
    "undelivered mail returned to sender",
    "delivery status notification",
    "delivery failure",
    "returned to sender",
    "mail delivery failed",
    "ошибка достав",
    "не доставлен",
    "сообщение не доставлено",
)


# Base64 attachment content is inlined into the MCP JSON response; keep it bounded.
_MAX_ATTACHMENT_CONTENT_BYTES = 10 * 1024 * 1024


def _is_bounce(sender: str, subject: str) -> bool:
    s = (sender or "").lower()
    subj = (subject or "").lower()
    return any(m in s for m in _BOUNCE_FROM_MARKERS) or any(m in subj for m in _BOUNCE_SUBJECT_MARKERS)


def _imap_utf7_encode(value: str) -> str:
    """Encode to IMAP modified UTF-7 (RFC 3501 section 5.1.3) for mailbox names."""
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        chunk = "".join(pending).encode("utf-16-be")
        out.append("&" + base64.b64encode(chunk).decode("ascii").rstrip("=").replace("/", ",") + "-")
        pending.clear()

    for ch in value:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return "".join(out)


def _imap_utf7_decode(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = value.find("-", i + 1)
        if end < 0:
            out.append(ch)
            break
        b64 = value[i + 1 : end].replace(",", "/")
        if not b64:
            out.append("&")
        else:
            padded = b64 + "=" * (-len(b64) % 4)
            out.append(base64.b64decode(padded).decode("utf-16-be"))
        i = end + 1
    return "".join(out)


def _imap_mailbox_literal(name: str) -> str:
    """Quote a mailbox name for IMAP commands, encoding non-ASCII as modified UTF-7."""
    encoded = name if all(ord(ch) < 0x80 for ch in name) else _imap_utf7_encode(name)
    escaped = encoded.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _imap_select_name(mailbox: str) -> str:
    """SELECT/EXAMINE argument: plain atom when simple ASCII, quoted UTF-7 literal otherwise."""
    if mailbox and all(0x20 < ord(ch) < 0x7F for ch in mailbox) and '"' not in mailbox:
        return mailbox
    return _imap_mailbox_literal(mailbox)


def _parse_imap_list_line(line: str) -> dict[str, Any] | None:
    match = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"(?P<delimiter>[^"]*)"\s+|NIL\s+)(?P<name>.+)$', line.strip())
    if not match:
        return None
    raw_name = match.group("name").strip()
    if len(raw_name) >= 2 and raw_name.startswith('"') and raw_name.endswith('"'):
        raw_name = raw_name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return {
        "name": _imap_utf7_decode(raw_name),
        "raw_name": raw_name,
        "delimiter": match.group("delimiter") or "",
        "flags": (match.group("flags") or "").split(),
    }


def _decode_payload(part: Any) -> str:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="ignore")
        except (LookupError, AttributeError):
            return payload.decode("utf-8", errors="ignore")
    return str(payload or "")


def _mail_search_sync(arguments: dict[str, Any], username: str, token: str) -> dict[str, Any]:
    import imaplib
    from email import message_from_bytes
    from email.header import decode_header, make_header

    host = os.getenv("YANDEX_MAIL_IMAP_HOST", "imap.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_IMAP_PORT", "993"))
    mailbox = str(arguments.get("mailbox") or "INBOX")
    query = str(arguments.get("query") or "").strip().lower()
    limit = max(1, min(50, int(arguments.get("limit") or 10)))
    scan_limit = max(limit, min(100, int(arguments.get("scan_limit") or 50)))
    include_text = bool(arguments.get("include_text", True))
    text_max = max(64, min(8000, int(arguments.get("text_max_chars") or 2000)))
    unseen_only = bool(arguments.get("unseen_only", False))

    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        imap.authenticate("XOAUTH2", lambda _: _xoauth2_string(username, token).encode("utf-8"))
        status, _ = imap.select(_imap_select_name(mailbox), readonly=True)
        if status != "OK":
            raise BackendRouteError(f"Unable to open mailbox: {mailbox}")
        status, data = imap.search(None, "UNSEEN" if unseen_only else "ALL")
        if status != "OK":
            raise BackendRouteError("Unable to search mailbox")
        ids = (data[0] or b"").split()
        messages = []
        for message_id in reversed(ids[-scan_limit:]):
            status, fetched = imap.fetch(
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)] BODY.PEEK[TEXT]<0.{0}>)".format(text_max),
            )
            if status != "OK" or not fetched:
                continue
            raw = b"".join(part[1] for part in fetched if isinstance(part, tuple))
            parsed = message_from_bytes(raw)
            subject = str(make_header(decode_header(parsed.get("Subject", ""))))
            sender = parsed.get("From", "")
            to = parsed.get("To", "")
            cc = parsed.get("Cc", "")
            date = parsed.get("Date", "")
            text_preview = ""
            if include_text:
                payload = parsed.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = parsed.get_content_charset() or "utf-8"
                    try:
                        text_preview = payload.decode(charset, errors="ignore")
                    except (LookupError, AttributeError):
                        text_preview = payload.decode("utf-8", errors="ignore")
                elif payload:
                    text_preview = str(payload)
                text_preview = text_preview.strip()[:text_max]
            haystack = json.dumps([subject, sender, to, cc, date, text_preview], ensure_ascii=False).lower()
            if query and query not in haystack:
                continue
            entry: dict[str, Any] = {
                "id": message_id.decode("ascii", errors="ignore"),
                "subject": subject,
                "from": sender,
                "to": parsed.get("To", ""),
                "date": date,
                "message_id": parsed.get("Message-ID", ""),
                "is_bounce": _is_bounce(sender, subject),
            }
            if include_text:
                entry["text"] = text_preview
            messages.append(entry)
            if len(messages) >= limit:
                break
        return {"ok": True, "backend": "yandex-mail", "data": {"mailbox": mailbox, "count": len(messages), "messages": messages}}
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _mail_get_sync(arguments: dict[str, Any], username: str, token: str) -> dict[str, Any]:
    import imaplib
    from email import message_from_bytes
    from email.header import decode_header, make_header

    host = os.getenv("YANDEX_MAIL_IMAP_HOST", "imap.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_IMAP_PORT", "993"))
    mailbox = str(arguments.get("mailbox") or "INBOX")
    message_id = str(arguments.get("id") or "").strip()
    if not message_id:
        raise BackendRouteError("mail.messages.get requires 'id'")

    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        imap.authenticate("XOAUTH2", lambda _: _xoauth2_string(username, token).encode("utf-8"))
        status, _ = imap.select(_imap_select_name(mailbox), readonly=True)
        if status != "OK":
            raise BackendRouteError(f"Unable to open mailbox: {mailbox}")
        status, fetched = imap.fetch(message_id, "(RFC822)")
        if status != "OK" or not fetched:
            raise BackendRouteError(f"Unable to fetch message id: {message_id}")
        raw = b""
        for part in fetched:
            if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                raw = bytes(part[1])
                break
        if not raw:
            raise BackendRouteError(f"Empty message for id: {message_id}")
        msg = message_from_bytes(raw)
        subject = str(make_header(decode_header(msg.get("Subject", ""))))

        text_body = ""
        html_body = ""
        include_attachment_content = bool(arguments.get("include_attachments_content", False))
        attachments: list[dict[str, Any]] = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disposition = (part.get("Content-Disposition") or "").lower()
                filename = part.get_filename()
                is_attachment = "attachment" in disposition or (bool(filename) and ctype not in ("text/plain", "text/html"))
                if is_attachment:
                    if filename:
                        payload_bytes = part.get_payload(decode=True) or b""
                        entry: dict[str, Any] = {
                            "filename": str(make_header(decode_header(filename))),
                            "content_type": ctype,
                            "size": len(payload_bytes),
                        }
                        if include_attachment_content:
                            if len(payload_bytes) <= _MAX_ATTACHMENT_CONTENT_BYTES:
                                entry["content_base64"] = base64.b64encode(payload_bytes).decode("ascii")
                            else:
                                entry["content_skipped"] = "attachment exceeds content size limit"
                        attachments.append(entry)
                elif ctype == "text/plain" and not text_body:
                    text_body = _decode_payload(part)
                elif ctype == "text/html" and not html_body:
                    html_body = _decode_payload(part)
        else:
            decoded = _decode_payload(msg)
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded

        sender = msg.get("From", "")
        return {
            "ok": True,
            "backend": "yandex-mail",
            "data": {
                "mailbox": mailbox,
                "id": message_id,
                "subject": subject,
                "from": sender,
                "to": msg.get("To", ""),
                "cc": msg.get("Cc", ""),
                "date": msg.get("Date", ""),
                "message_id": msg.get("Message-ID", ""),
                "is_bounce": _is_bounce(sender, subject),
                "text": text_body,
                "html": html_body,
                "attachments": attachments,
            },
        }
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _mail_mark_read_sync(arguments: dict[str, Any], username: str, token: str) -> dict[str, Any]:
    import imaplib

    host = os.getenv("YANDEX_MAIL_IMAP_HOST", "imap.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_IMAP_PORT", "993"))
    mailbox = str(arguments.get("mailbox") or "INBOX")
    message_id = str(arguments.get("id") or "").strip()
    if not message_id:
        raise BackendRouteError("mail.messages.mark_read requires 'id'")

    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        imap.authenticate("XOAUTH2", lambda _: _xoauth2_string(username, token).encode("utf-8"))
        status, _ = imap.select(_imap_select_name(mailbox), readonly=False)
        if status != "OK":
            raise BackendRouteError(f"Unable to open mailbox: {mailbox}")
        unread = bool(arguments.get("unread", False))
        if unread:
            status, _ = imap.store(message_id, "-FLAGS.SILENT", "(\\Seen)")
            flags: list[str] = []
        else:
            status, _ = imap.store(message_id, "+FLAGS.SILENT", "(\\Seen)")
            flags = ["\\Seen"]
        if status != "OK":
            raise BackendRouteError(f"Unable to update \\Seen flag: {message_id}")
        return {
            "ok": True,
            "backend": "yandex-mail",
            "data": {"mailbox": mailbox, "id": message_id, "flags_set": flags, "unread": unread},
        }
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _mail_list_folders_sync(arguments: dict[str, Any], username: str, token: str) -> dict[str, Any]:
    import imaplib

    host = os.getenv("YANDEX_MAIL_IMAP_HOST", "imap.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_IMAP_PORT", "993"))

    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        imap.authenticate("XOAUTH2", lambda _: _xoauth2_string(username, token).encode("utf-8"))
        status, lines = imap.list()
        if status != "OK":
            raise BackendRouteError("Unable to list mail folders")
        folders: list[dict[str, Any]] = []
        for line in lines or []:
            text = line.decode("utf-8", errors="replace") if isinstance(line, (bytes, bytearray)) else str(line)
            entry = _parse_imap_list_line(text)
            if entry:
                folders.append(entry)
        return {"ok": True, "backend": "yandex-mail", "data": {"count": len(folders), "folders": folders}}
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _mail_move_sync(arguments: dict[str, Any], username: str, token: str) -> dict[str, Any]:
    import imaplib

    host = os.getenv("YANDEX_MAIL_IMAP_HOST", "imap.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_IMAP_PORT", "993"))
    mailbox = str(arguments.get("mailbox") or "INBOX")
    message_id = str(arguments.get("id") or "").strip()
    if not message_id:
        raise BackendRouteError("mail.messages.move requires 'id'")
    destination = str(arguments.get("destination") or "").strip()
    if not destination:
        raise BackendRouteError("mail.messages.move requires 'destination' (folder name, see mail.folders.list)")

    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        imap.authenticate("XOAUTH2", lambda _: _xoauth2_string(username, token).encode("utf-8"))
        status, _ = imap.select(_imap_select_name(mailbox), readonly=False)
        if status != "OK":
            raise BackendRouteError(f"Unable to open mailbox: {mailbox}")
        status, _ = imap.copy(message_id, _imap_mailbox_literal(destination))
        if status != "OK":
            raise BackendRouteError(f"Unable to copy message {message_id} to folder: {destination}")
        status, _ = imap.store(message_id, "+FLAGS.SILENT", "(\\Deleted)")
        if status != "OK":
            raise BackendRouteError(f"Unable to flag copied message as deleted: {message_id}")
        expunged = True
        try:
            imap.expunge()
        except imaplib.IMAP4.error:
            # Copy and the \\Deleted flag already succeeded; some servers only
            # expunge on logout, the message is gone from the source view anyway.
            expunged = False
        return {
            "ok": True,
            "backend": "yandex-mail",
            "data": {
                "mailbox": mailbox,
                "id": message_id,
                "destination": destination,
                "moved": True,
                "expunged": expunged,
            },
        }
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _mail_send_sync(arguments: dict[str, Any], username: str, token: str) -> dict[str, Any]:
    import smtplib

    to = [item.strip() for item in str(arguments.get("to") or "").replace(";", ",").split(",") if item.strip()]
    if not to:
        raise BackendRouteError("mail.messages.send requires to")
    subject = str(arguments.get("subject") or "").strip()
    body = str(arguments.get("body") or "").strip()
    if not subject:
        raise BackendRouteError("mail.messages.send requires subject")
    if not body:
        raise BackendRouteError("mail.messages.send requires body")

    message = EmailMessage()
    message["From"] = username
    message["To"] = ", ".join(to)
    if arguments.get("cc"):
        message["Cc"] = str(arguments["cc"])
    message["Subject"] = subject
    message["Date"] = email.utils.formatdate(localtime=True)
    message.set_content(body)

    host = os.getenv("YANDEX_MAIL_SMTP_HOST", "smtp.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_SMTP_PORT", "465"))
    auth = base64.b64encode(_xoauth2_string(username, token).encode("utf-8")).decode("ascii")
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as smtp:
        code, response = smtp.docmd("AUTH", "XOAUTH2 " + auth)
        if code != 235:
            raise BackendConfigError(f"Yandex SMTP OAuth failed: {code} {response!r}")
        smtp.send_message(message)
    return {"ok": True, "backend": "yandex-mail", "data": {"to": to, "subject": subject}}


async def _call_yandex_mail(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation", ""))
    username = _yandex_user_email()
    token = _yandex_user_token()
    if operation == "search_messages":
        return await asyncio.to_thread(_mail_search_sync, arguments, username, token)
    if operation == "get_message":
        return await asyncio.to_thread(_mail_get_sync, arguments, username, token)
    if operation == "mark_read":
        return await asyncio.to_thread(_mail_mark_read_sync, arguments, username, token)
    if operation == "list_folders":
        return await asyncio.to_thread(_mail_list_folders_sync, arguments, username, token)
    if operation == "move_message":
        return await asyncio.to_thread(_mail_move_sync, arguments, username, token)
    if operation == "send_message":
        return await asyncio.to_thread(_mail_send_sync, arguments, username, token)
    raise BackendRouteError(f"Unsupported Yandex Mail operation: {operation or '<missing>'}")
