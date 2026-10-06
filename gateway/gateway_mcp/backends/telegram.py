import base64
import os
from typing import Any

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError, _env

def _proxy_from_env() -> tuple | None:
    """Parse TELEGRAM_PROXY (e.g. socks5://outbound-proxy:7890) for MTProto.

    Telethon opens raw sockets to Telegram DC addresses and ignores the
    standard proxy environment variables, so MTProto routes need the proxy
    passed explicitly (requires python-socks, which telethon uses when
    present). Returns a telethon proxy tuple or None.
    """
    raw = os.getenv("TELEGRAM_PROXY", "").strip()
    if not raw:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "socks5").lower()
    types = {"socks5": 2, "socks4": 1, "http": 3}
    if scheme not in types or not parsed.hostname:
        raise BackendConfigError(f"Unsupported TELEGRAM_PROXY value: {raw!r}")
    return (types[scheme], parsed.hostname, parsed.port or 1080, True, None, None)


async def _telegram_client() -> Any:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError as exc:
        raise BackendConfigError("Install telethon dependency to use Telegram routes") from exc

    api_id = int(_env("TELEGRAM_API_ID"))
    api_hash = _env("TELEGRAM_API_HASH")
    proxy = _proxy_from_env()
    session_string = os.getenv("TELEGRAM_SESSION_STRING", "").strip()
    if session_string:
        client = TelegramClient(StringSession(session_string), api_id, api_hash, proxy=proxy)
    else:
        client = TelegramClient(
            os.getenv("TELEGRAM_SESSION_NAME", "gateway-mcp-telegram"), api_id, api_hash, proxy=proxy
        )

    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise BackendConfigError("Telegram session is not authorized. Set TELEGRAM_SESSION_STRING or pre-login the session file.")
    return client


def _serialize_telegram_media(message: Any) -> dict[str, Any] | None:
    media = getattr(message, "media", None)
    if media is None:
        return None
    file_obj = getattr(message, "file", None)
    if file_obj is None:
        return {"type": "unknown", "has_file": False}
    media_type = "photo" if getattr(message, "photo", None) is not None else "document"
    return {
        "type": media_type,
        "file_name": getattr(file_obj, "name", None) or "",
        "mime_type": getattr(file_obj, "mime_type", None) or "",
        "size": getattr(file_obj, "size", None),
        "has_file": True,
    }


def _serialize_telegram_message(message: Any) -> dict[str, Any]:
    date = getattr(message, "date", None)
    result: dict[str, Any] = {
        "id": getattr(message, "id", None),
        "chat_id": getattr(message, "chat_id", None),
        "sender_id": getattr(message, "sender_id", None),
        "date": date.isoformat() if hasattr(date, "isoformat") else None,
        "text": getattr(message, "message", "") or "",
    }
    media = _serialize_telegram_media(message)
    if media is not None:
        result["media"] = media
    return result


async def _call_telegram(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation", ""))
    client = await _telegram_client()
    try:
        if operation == "list_chats":
            limit = max(1, int(arguments.get("limit") or arguments.get("page_size") or 50))
            chats = []
            async for dialog in client.iter_dialogs(limit=limit):
                entity = dialog.entity
                chats.append(
                    {
                        "id": getattr(entity, "id", None),
                        "title": getattr(dialog, "name", "") or getattr(entity, "title", "") or "",
                        "is_user": bool(getattr(dialog, "is_user", False)),
                        "is_group": bool(getattr(dialog, "is_group", False)),
                        "is_channel": bool(getattr(dialog, "is_channel", False)),
                    }
                )
            return {"ok": True, "backend": "telegram", "data": {"chats": chats}}

        if operation in {"get_messages", "search_messages"}:
            chat_id = arguments.get("chat_id")
            if chat_id is None or chat_id == "":
                raise BackendRouteError("Telegram messages route requires chat_id")
            limit = max(1, int(arguments.get("limit") or arguments.get("page_size") or 50))
            query = str(arguments.get("query") or "").strip()
            kwargs = {"limit": limit}
            if query:
                kwargs["search"] = query
            messages = [
                _serialize_telegram_message(message)
                async for message in client.iter_messages(chat_id, **kwargs)
            ]
            return {"ok": True, "backend": "telegram", "data": {"messages": messages}}

        if operation == "send_message":
            chat_id = arguments.get("chat_id")
            message_text = str(arguments.get("message") or "").strip()
            if chat_id is None or chat_id == "":
                raise BackendRouteError("telegram.messages.send requires chat_id")
            if not message_text:
                raise BackendRouteError("telegram.messages.send requires message")
            message = await client.send_message(chat_id, message_text)
            return {
                "ok": True,
                "backend": "telegram",
                "data": {"message": _serialize_telegram_message(message)},
            }

        if operation == "download_file":
            chat_id = arguments.get("chat_id")
            message_id = arguments.get("message_id")
            if not chat_id:
                raise BackendRouteError("telegram.files.download requires chat_id")
            if not message_id:
                raise BackendRouteError("telegram.files.download requires message_id")
            message = await client.get_messages(chat_id, ids=int(message_id))
            if message is None:
                raise BackendRouteError(f"Telegram message {message_id} not found in chat {chat_id}")
            media = _serialize_telegram_media(message)
            if media is None or not media.get("has_file"):
                raise BackendRouteError(f"Telegram message {message_id} has no downloadable file")
            data = await client.download_media(message, file=bytes)
            if not data:
                raise BackendRouteError(f"Failed to download media from Telegram message {message_id}")
            return {
                "ok": True,
                "backend": "telegram",
                "data": {
                    "file_name": media.get("file_name") or f"telegram_{message_id}",
                    "mime_type": media.get("mime_type") or "application/octet-stream",
                    "size": len(data),
                    "content_base64": base64.b64encode(data).decode("ascii"),
                },
            }

        raise BackendRouteError(f"Unsupported Telegram operation: {operation or '<missing>'}")
    finally:
        await client.disconnect()
