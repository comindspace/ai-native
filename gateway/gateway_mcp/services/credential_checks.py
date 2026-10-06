import asyncio
import imaplib
import os
import ssl
from typing import Any

import httpx

from gateway_mcp.backends.common import _xoauth2_string
from gateway_mcp.services.auth import (
    fetch_google_user_info,
    fetch_yandex_user_info,
    refresh_google_access_token,
)
from gateway_mcp.services.managed_integrations import integration_value
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.storage import get_user_oauth_token


def check_result(ok: bool, message: str) -> dict[str, Any]:
    return {"ok": ok, "message": message}


async def check_credential(provider: str, actor: GatewayActor) -> dict[str, Any]:
    if provider == "yandex":
        return await check_yandex_credential(actor)
    if provider == "tracker":
        return await check_tracker_credential(actor)
    if provider == "yandex-disk":
        return await check_yandex_disk_credential(actor)
    if provider == "mail":
        return await check_yandex_mail_credential(actor)
    if provider == "gitlab":
        return await check_gitlab_credential(actor)
    if provider == "google":
        return await check_google_credential(actor)
    if provider == "calendar":
        return await check_calendar_credential(actor)
    return check_result(False, "Неизвестный тип подключения.")


async def check_yandex_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = _stored_yandex_credential(actor)
    if not credential:
        return _yandex_token_missing_result()
    try:
        user_info = await fetch_yandex_user_info(str(credential["access_token"]))
    except Exception as exc:
        return check_result(False, f"Yandex OAuth не прошел проверку: {exc.__class__.__name__}.")
    email = str(user_info.get("default_email") or user_info.get("email") or actor.display)
    return check_result(True, f"Yandex OAuth работает. Пользователь: {email}.")


async def check_tracker_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = _stored_yandex_credential(actor)
    if not credential:
        return _yandex_token_missing_result()
    org_id = integration_value("tracker", "TRACKER_ORG_ID")
    cloud_org_id = integration_value("tracker", "TRACKER_CLOUD_ORG_ID")
    if org_id and cloud_org_id:
        return check_result(False, "Настройте только один из TRACKER_ORG_ID или TRACKER_CLOUD_ORG_ID.")
    if not org_id and not cloud_org_id:
        return check_result(False, "На сервере не настроен TRACKER_ORG_ID или TRACKER_CLOUD_ORG_ID.")

    headers = {"Authorization": f"OAuth {credential['access_token']}", "Accept": "application/json"}
    headers["X-Org-ID" if org_id else "X-Cloud-Org-ID"] = org_id or cloud_org_id
    base_url = integration_value("tracker", "TRACKER_API_BASE_URL", "https://api.tracker.yandex.net").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{base_url}/v3/queues", headers=headers, params={"perPage": 1})
    except Exception as exc:
        return check_result(False, f"Tracker не прошел проверку: {exc.__class__.__name__}.")
    if not response.is_success:
        return check_result(False, f"Tracker вернул HTTP {response.status_code}: {_short_upstream_text(response)}")
    return check_result(True, "Tracker OAuth работает: список очередей доступен.")


async def check_yandex_disk_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = _stored_yandex_credential(actor, provider="yandex-disk") or _stored_yandex_credential(actor)
    if not credential:
        return _yandex_token_missing_result()
    base_url = os.getenv("YANDEX_DISK_API_BASE_URL", "https://cloud-api.yandex.net/v1/disk").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{base_url}/resources",
                headers={"Authorization": f"OAuth {credential['access_token']}"},
                params={"path": "/", "limit": 1},
            )
    except Exception as exc:
        return check_result(False, f"Yandex Disk не прошел проверку: {exc.__class__.__name__}.")
    if not response.is_success:
        return check_result(False, f"Yandex Disk вернул HTTP {response.status_code}: {_short_upstream_text(response)}")
    return check_result(True, "Yandex Disk OAuth работает: корневая папка доступна.")


async def check_yandex_mail_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = _stored_yandex_credential(actor)
    if not credential:
        return _yandex_token_missing_result()
    username = actor.email or actor.login or str(credential.get("email") or "")
    if not username:
        return check_result(False, "Не найден email/login пользователя для проверки почты.")
    try:
        await asyncio.to_thread(_mail_check_sync, username, str(credential["access_token"]))
    except Exception as exc:
        return check_result(
            False,
            f"Yandex Mail не прошел проверку: {exc.__class__.__name__}. Проверьте OAuth scopes и IMAP в почтовом ящике.",
        )
    return check_result(True, "Yandex Mail OAuth работает: IMAP авторизация прошла.")


async def check_gitlab_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = get_user_oauth_token("gitlab", actor.subject)
    if not credential or not credential.get("access_token"):
        return check_result(False, "GitLab токен не найден. Сохраните personal access token.")
    base_url = integration_value("gitlab", "GITLAB_API_BASE_URL", "https://gitlab.example.com/api/v4").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{base_url}/user", headers={"PRIVATE-TOKEN": str(credential["access_token"])})
        if not response.is_success:
            return check_result(False, f"GitLab вернул HTTP {response.status_code}. Проверьте token и scopes.")
        data = response.json()
    except Exception as exc:
        return check_result(False, f"GitLab не прошел проверку: {exc.__class__.__name__}.")
    username = str(data.get("username") or data.get("name") or "пользователь найден")
    return check_result(True, f"GitLab токен работает. Пользователь: {username}.")


async def check_google_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = get_user_oauth_token("google", actor.subject)
    if not credential or not credential.get("access_token"):
        return check_result(False, "Google OAuth токен не найден. Подключите Google на этой странице.")
    try:
        token_payload = await refresh_google_access_token(str(credential["access_token"]))
        access_token = str(token_payload["access_token"])
        user_info = await fetch_google_user_info(access_token)
    except Exception as exc:
        return check_result(False, f"Google OAuth не прошел проверку: {exc.__class__.__name__}.")
    email = str(user_info.get("email") or credential.get("email") or actor.display)
    return check_result(True, f"Google OAuth работает. Пользователь: {email}.")


async def check_calendar_credential(actor: GatewayActor) -> dict[str, Any]:
    credential = get_user_oauth_token("yandex-caldav", actor.subject)
    if not credential or not credential.get("access_token"):
        return check_result(False, "Пароль приложения Yandex Calendar не найден. Добавьте его на этой странице.")
    username = str(credential.get("email") or actor.email or actor.login or "")
    if not username:
        return check_result(False, "Не найден email/login пользователя для проверки CalDAV.")
    try:
        count = await asyncio.to_thread(_calendar_check_sync, username, str(credential["access_token"]))
    except ImportError:
        return check_result(False, "На сервере не установлена зависимость caldav.")
    except Exception as exc:
        return check_result(False, f"Yandex Calendar не прошел проверку: {exc.__class__.__name__}.")
    return check_result(True, f"Yandex Calendar работает. Доступно календарей: {count}.")


def _stored_yandex_credential(actor: GatewayActor, *, provider: str = "yandex") -> dict[str, Any] | None:
    credential = get_user_oauth_token(provider, actor.subject)
    if not credential or not credential.get("access_token"):
        return None
    return credential


def _yandex_token_missing_result() -> dict[str, Any]:
    return check_result(False, "Yandex OAuth токен не найден. Войдите через Yandex OAuth заново.")


def _short_upstream_text(response: httpx.Response, limit: int = 180) -> str:
    text = " ".join(str(response.text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _mail_check_sync(username: str, token: str) -> None:
    host = os.getenv("YANDEX_MAIL_IMAP_HOST", "imap.yandex.com")
    port = int(os.getenv("YANDEX_MAIL_IMAP_PORT", "993"))
    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    try:
        imap.authenticate("XOAUTH2", lambda _: _xoauth2_string(username, token).encode("utf-8"))
        imap.select("INBOX", readonly=True)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _calendar_check_sync(username: str, password: str) -> int:
    import caldav

    client = caldav.DAVClient(
        url=os.getenv("CALDAV_URL", "https://caldav.yandex.ru"),
        username=username,
        password=password,
    )
    return len(client.principal().calendars())
