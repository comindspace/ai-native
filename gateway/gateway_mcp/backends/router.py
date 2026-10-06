from importlib import import_module
from typing import Any

from gateway_mcp.backends.common import BackendRouteError, _apply_argument_aliases


BACKEND_DISPATCH: dict[str, tuple[str, str]] = {
    "bitrix24-rest": ("gateway_mcp.backends.bitrix24", "_call_bitrix24"),
    "caldav": ("gateway_mcp.backends.caldav", "_call_caldav"),
    "gitlab-rest": ("gateway_mcp.backends.gitlab", "_call_gitlab"),
    "google-rest": ("gateway_mcp.backends.google", "_call_google"),
    "infra": ("gateway_mcp.backends.infra", "_call_infra"),
    "metrika-rest": ("gateway_mcp.backends.metrika", "_call_metrika"),
    "notification": ("gateway_mcp.backends.notifications", "_call_notifications"),
    "openrouter-audio": ("gateway_mcp.backends.openrouter", "_call_openrouter_audio"),
    "telegram": ("gateway_mcp.backends.telegram", "_call_telegram"),
    "tracker-rest": ("gateway_mcp.backends.tracker", "_call_tracker"),
    "webmaster-rest": ("gateway_mcp.backends.webmaster", "_call_webmaster"),
    "wordstat-rest": ("gateway_mcp.backends.wordstat", "_call_wordstat"),
    "yandex-disk-rest": ("gateway_mcp.backends.yandex_disk", "_call_yandex_disk"),
    "yandex-mail": ("gateway_mcp.backends.yandex_mail", "_call_yandex_mail"),
    "yonote-rpc": ("gateway_mcp.backends.yonote", "_call_yonote"),
}


def _backend_callable(transport: str):
    module_name, function_name = BACKEND_DISPATCH[transport]
    return getattr(import_module(module_name), function_name)


async def call_backend(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    arguments = _apply_argument_aliases(route, arguments)
    transport = route.get("transport")
    if transport in BACKEND_DISPATCH:
        return await _backend_callable(str(transport))(route, arguments)
    raise BackendRouteError(f"Unsupported backend transport: {transport or '<missing>'}")
