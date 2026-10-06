import json
import os
import urllib.request
from typing import Any

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError
from gateway_mcp.backends.telegram import _serialize_telegram_message, _telegram_client
from gateway_mcp.services.managed_integrations import integration_value


def _configured_skill_update_chat_id() -> str:
    # GATEWAY_COMIND_* names are legacy deploy names; the generic
    # GATEWAY_SKILL_UPDATE_CHAT_ID is preferred for new deployments.
    managed = integration_value("telegram", "TELEGRAM_NOTIFICATION_CHAT_ID")
    if managed:
        return managed
    for name in (
        "GATEWAY_SKILL_UPDATE_CHAT_ID",
        "GATEWAY_COMIND_CHAT_ID",
        "GATEWAY_COMIND_MR_REVIEW_CHAT_ID",
        "TELEGRAM_COMIND_CHAT_ID",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise BackendConfigError(
        "Missing configured notifications chat. Set GATEWAY_SKILL_UPDATE_CHAT_ID "
        "(legacy GATEWAY_COMIND_CHAT_ID is still honored)."
    )


def _clean_text(value: Any, *, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def _line(label: str, value: str) -> str:
    return f"{label}: {value}"


def _build_skill_update_message(arguments: dict[str, Any]) -> str:
    skill = _clean_text(arguments.get("skill") or arguments.get("skill_name"), max_length=160)
    pack = _clean_text(arguments.get("pack") or arguments.get("plugin_pack"), max_length=80)
    summary = _clean_text(arguments.get("summary") or arguments.get("what_changed"), max_length=700)
    url = _clean_text(arguments.get("url") or arguments.get("mr_url"), max_length=500)
    source_agent = _clean_text(arguments.get("source_agent") or arguments.get("agent"), max_length=80)

    if not skill:
        raise BackendRouteError("notifications.skill_update.send requires skill or skill_name")

    lines = [f"Обновился скилл: {skill}"]
    if pack:
        lines.append(_line("Пак", pack))
    if summary:
        lines.append(_line("Что изменилось", summary))
    if url:
        lines.append(_line("Ссылка", url))
    if source_agent:
        lines.append(_line("Отправитель", source_agent))
    lines.append("")
    lines.append("Обновите плагины у себя, чтобы агенты получили изменения.")
    return "\n".join(lines)


def _bot_api_token() -> str:
    return integration_value("telegram", "TELEGRAM_BOT_TOKEN")


def _send_via_bot_api(chat_id: str, text: str) -> dict[str, Any]:
    """Send through the Telegram Bot API over HTTPS.

    Unlike MTProto (telethon), plain HTTPS goes through the standard
    HTTPS_PROXY/ALL_PROXY environment settings, so this path works on hosts
    where Telegram DC addresses are blocked but the outbound proxy is allowed.
    urllib picks up the proxy environment automatically.
    """
    token = _bot_api_token()
    if not token:
        raise BackendConfigError("TELEGRAM_BOT_TOKEN is not set")
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise BackendRouteError(f"Telegram Bot API request failed: {exc}") from exc
    if not result.get("ok"):
        raise BackendRouteError(f"Telegram Bot API error: {result.get('description', 'unknown')}")
    message = result.get("message", {})
    return {
        "ok": True,
        "backend": "notifications",
        "data": {
            "channel": "skill_update",
            "transport": "bot-api",
            "message": {
                "id": message.get("message_id"),
                "chat_id": str(message.get("chat", {}).get("id", chat_id)),
                "date": message.get("date"),
                "text": message.get("text", text),
            },
        },
    }


async def _call_notifications(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation", ""))
    if operation != "skill_update.send":
        raise BackendRouteError(f"Unsupported notifications operation: {operation or '<missing>'}")

    chat_id = _configured_skill_update_chat_id()
    message_text = _build_skill_update_message(arguments)

    # GATEWAY_NOTIFICATIONS_TRANSPORT: "bot-api" | "telethon". По умолчанию bot-api,
    # если задан TELEGRAM_BOT_TOKEN, иначе telethon (user-сессия).
    # GATEWAY_MR_REVIEW_TRANSPORT is the legacy deploy name and is still honored.
    transport = (
        os.getenv("GATEWAY_NOTIFICATIONS_TRANSPORT", "").strip().lower()
        or os.getenv("GATEWAY_MR_REVIEW_TRANSPORT", "").strip().lower()
    )
    if transport == "telethon" or (not transport and not _bot_api_token()):
        client = await _telegram_client()
        try:
            message = await client.send_message(chat_id, message_text)
            return {
                "ok": True,
                "backend": "notifications",
                "data": {
                    "channel": "skill_update",
                    "transport": "telethon",
                    "message": _serialize_telegram_message(message),
                },
            }
        finally:
            await client.disconnect()

    return _send_via_bot_api(chat_id, message_text)
