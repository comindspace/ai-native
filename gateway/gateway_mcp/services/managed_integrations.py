from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from gateway_mcp.services.storage_service_connections import (
    delete_service_connection,
    get_service_connection,
    list_service_connections,
    record_service_connection_check,
    set_service_connection_state,
    upsert_service_connection,
)


@dataclass(frozen=True)
class IntegrationField:
    key: str
    label: str
    secret: bool = False
    placeholder: str = ""
    default: str = ""


@dataclass(frozen=True)
class IntegrationDefinition:
    key: str
    label: str
    description: str
    fields: tuple[IntegrationField, ...]


INTEGRATIONS: dict[str, IntegrationDefinition] = {
    "bitrix24": IntegrationDefinition(
        key="bitrix24",
        label="Bitrix24",
        description="Служебный входящий вебхук для операций CRM.",
        fields=(IntegrationField("BITRIX24_WEBHOOK_URL", "URL вебхука", secret=True),),
    ),
    "yonote": IntegrationDefinition(
        key="yonote",
        label="Yonote",
        description="Корпоративные страницы, базы, процессы и архитектурные решения.",
        fields=(
            IntegrationField("YONOTE_API_KEY", "API-ключ", secret=True),
            IntegrationField(
                "YONOTE_BASE_URL",
                "Адрес Yonote",
                default="https://wiki.example.com",
            ),
        ),
    ),
    "openrouter": IntegrationDefinition(
        key="openrouter",
        label="OpenRouter",
        description="Модели и распознавание аудио через внешний API.",
        fields=(
            IntegrationField("OPENROUTER_API_KEY", "API-ключ", secret=True),
            IntegrationField(
                "OPENROUTER_BASE_URL",
                "Адрес API",
                default="https://openrouter.ai/api/v1",
            ),
            IntegrationField("OPENROUTER_TRANSCRIBE_MODEL", "Модель распознавания"),
        ),
    ),
    "llm-proxy": IntegrationDefinition(
        key="llm-proxy",
        label="Внешняя LLM через защитный прокси",
        description="Провайдер моделей, к которому шлюз отправляет только обезличенные запросы.",
        fields=(
            IntegrationField(
                "GATEWAY_LLM_UPSTREAM_URL",
                "Адрес OpenAI-совместимого API",
                default="https://openrouter.ai/api/v1",
            ),
            IntegrationField(
                "GATEWAY_LLM_UPSTREAM_API_KEY",
                "API-ключ провайдера",
                secret=True,
            ),
            IntegrationField("GATEWAY_LLM_DEFAULT_MODEL", "Модель по умолчанию"),
            IntegrationField(
                "GATEWAY_LLM_ALLOWED_MODELS",
                "Разрешённые модели через запятую",
            ),
        ),
    ),
    "tracker": IntegrationDefinition(
        key="tracker",
        label="Yandex Tracker",
        description="Организация и адрес API. Пользовательский OAuth хранится отдельно.",
        fields=(
            IntegrationField("TRACKER_ORG_ID", "Organization ID"),
            IntegrationField("TRACKER_CLOUD_ORG_ID", "Cloud Organization ID"),
            IntegrationField(
                "TRACKER_API_BASE_URL",
                "Адрес API",
                default="https://api.tracker.yandex.net",
            ),
        ),
    ),
    "gitlab": IntegrationDefinition(
        key="gitlab",
        label="GitLab",
        description="Адрес корпоративного GitLab. Пользовательские токены хранятся отдельно.",
        fields=(
            IntegrationField(
                "GITLAB_API_BASE_URL",
                "Адрес API",
                default="https://gitlab.example.com/api/v4",
            ),
        ),
    ),
    "telegram": IntegrationDefinition(
        key="telegram",
        label="Telegram",
        description="Служебный бот для уведомлений GatewayMCP.",
        fields=(
            IntegrationField("TELEGRAM_BOT_TOKEN", "Токен бота", secret=True),
            IntegrationField("TELEGRAM_NOTIFICATION_CHAT_ID", "Чат уведомлений"),
        ),
    ),
}

_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_CACHE_LOCK = Lock()


def integration_definition(system: str) -> IntegrationDefinition:
    try:
        return INTEGRATIONS[str(system).strip().casefold()]
    except KeyError as exc:
        raise ValueError("Unknown managed integration") from exc


def integration_value(system: str, key: str, default: str = "") -> str:
    row = _runtime_connection(system)
    if row is not None:
        if not _connection_usable(row):
            return default
        payload = row.get("payload")
        values = payload if isinstance(payload, dict) else {}
        return str(values.get(key) or default).strip()
    return os.getenv(key, default).strip()


def integration_statuses() -> list[dict[str, Any]]:
    stored = {str(row.get("system")): row for row in list_service_connections()}
    return [
        _safe_status(definition, stored.get(definition.key))
        for definition in INTEGRATIONS.values()
    ]


def integration_status(system: str) -> dict[str, Any]:
    definition = integration_definition(system)
    return _safe_status(
        definition, get_service_connection(definition.key, include_payload=False)
    )


def save_integration(
    system: str,
    *,
    values: dict[str, str],
    clear_fields: set[str],
    updated_by: str,
    expires_at: datetime | None,
) -> dict[str, Any]:
    definition = integration_definition(system)
    allowed = {field.key for field in definition.fields}
    unknown = (set(values) | set(clear_fields)) - allowed
    if unknown:
        raise ValueError(f"Unknown integration fields: {', '.join(sorted(unknown))}")
    existing = get_service_connection(definition.key, include_payload=True)
    if system == "gitlab" and ((existing or {}).get("payload") or {}).get(
        "GITLAB_TOKEN"
    ):
        raise ValueError(
            "Служебное подключение GitLab изменяется в разделе «GitLab для фабрики»."
        )
    current = {
        key: str(value)
        for key, value in dict((existing or {}).get("payload") or {}).items()
        if key in allowed
    }
    for key in clear_fields:
        current.pop(key, None)
    for key, value in values.items():
        normalized = str(value or "").strip()
        if normalized:
            current[key] = normalized
    _validate_payload(definition.key, current)
    result = upsert_service_connection(
        system=definition.key,
        payload=current,
        updated_by=updated_by,
        expires_at=expires_at,
        expected_version=int((existing or {}).get("version", 0))
        if system == "gitlab"
        else None,
    )
    invalidate_integration_cache(definition.key)
    return result


def disable_integration(system: str, *, updated_by: str) -> bool:
    definition = integration_definition(system)
    changed = set_service_connection_state(
        definition.key, state="disabled", updated_by=updated_by
    )
    invalidate_integration_cache(definition.key)
    return changed


def delete_integration(system: str) -> bool:
    definition = integration_definition(system)
    changed = delete_service_connection(definition.key)
    invalidate_integration_cache(definition.key)
    return changed


async def check_integration(system: str) -> dict[str, Any]:
    definition = integration_definition(system)
    if system == "gitlab":
        from gateway_mcp.services.factory_connections import check_connection

        return await check_connection("gitlab")
    try:
        result = await _run_check(definition.key)
    except Exception as exc:  # noqa: BLE001 - health checks must not break the admin page
        result = {
            "ok": False,
            "message": f"Проверка не выполнена: {exc.__class__.__name__}.",
        }
    record_service_connection_check(
        definition.key,
        ok=bool(result["ok"]),
        message=str(result["message"]),
    )
    invalidate_integration_cache(definition.key)
    return result


def invalidate_integration_cache(system: str = "") -> None:
    with _CACHE_LOCK:
        if system:
            _CACHE.pop(str(system).strip().casefold(), None)
        else:
            _CACHE.clear()


def _runtime_connection(system: str) -> dict[str, Any] | None:
    key = integration_definition(system).key
    now = time.monotonic()
    ttl = max(0.0, float(os.getenv("GATEWAY_MANAGED_CONNECTION_CACHE_SECONDS", "5")))
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] <= ttl:
            return cached[1]
    row = get_service_connection(key, include_payload=True)
    with _CACHE_LOCK:
        _CACHE[key] = (now, row)
    return row


def _connection_usable(row: dict[str, Any]) -> bool:
    if str(row.get("state") or "") != "active":
        return False
    expires_at = _parse_datetime(row.get("expires_at"))
    return expires_at is None or expires_at > datetime.now(timezone.utc)


def _safe_status(
    definition: IntegrationDefinition, row: dict[str, Any] | None
) -> dict[str, Any]:
    if row is not None:
        expired = not _connection_usable({**row, "state": "active"})
        return {
            **row,
            "system": definition.key,
            "label": definition.label,
            "description": definition.description,
            "state": "expired" if expired else str(row.get("state") or "disabled"),
            "source": "admin",
            "configured": str(row.get("state") or "") == "active" and not expired,
        }
    env_values = {
        field.key: os.getenv(field.key, "").strip()
        for field in definition.fields
        if os.getenv(field.key, "").strip()
    }
    configured = _payload_valid(definition.key, env_values, allow_defaults=True)
    return {
        "system": definition.key,
        "label": definition.label,
        "description": definition.description,
        "state": "active" if configured else "missing",
        "source": "environment" if configured else "missing",
        "configured": configured,
        "configured_fields": sorted(env_values),
        "version": 0,
    }


def safe_field_value(system: str, field: IntegrationField) -> str:
    row = get_service_connection(
        integration_definition(system).key, include_payload=True
    )
    value = str(dict((row or {}).get("payload") or {}).get(field.key) or "").strip()
    if not value:
        value = os.getenv(field.key, "").strip() or field.default
    if not value:
        return ""
    if not field.secret:
        return value
    if field.key == "BITRIX24_WEBHOOK_URL":
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            netloc = (
                parsed.hostname
                if not parsed.port
                else f"{parsed.hostname}:{parsed.port}"
            )
            parts = [part for part in parsed.path.split("/") if part]
            visible = parts[:2] if parts and parts[0].casefold() == "rest" else []
            return urlunsplit(
                (parsed.scheme, netloc, "/" + "/".join((*visible, "***")), "", "")
            )
    return "Значение скрыто"


def _validate_payload(system: str, values: dict[str, str]) -> None:
    if not _payload_valid(system, values, allow_defaults=True):
        raise ValueError("Не заполнены обязательные параметры подключения")
    effective = {
        field.key: str(values.get(field.key) or field.default).strip()
        for field in integration_definition(system).fields
    }
    for key, value in effective.items():
        if key.endswith("_URL") and value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{key} должен содержать полный HTTP(S)-адрес")
    if (
        system == "tracker"
        and effective["TRACKER_ORG_ID"]
        and effective["TRACKER_CLOUD_ORG_ID"]
    ):
        raise ValueError("Укажите только один идентификатор организации Tracker")


def _payload_valid(
    system: str, values: dict[str, str], *, allow_defaults: bool = False
) -> bool:
    definition = integration_definition(system)

    def present(key: str) -> bool:
        value = str(values.get(key) or "").strip()
        if not value and allow_defaults:
            value = next(
                (field.default for field in definition.fields if field.key == key), ""
            )
        return bool(value)

    required = {
        "bitrix24": ("BITRIX24_WEBHOOK_URL",),
        "yonote": ("YONOTE_API_KEY", "YONOTE_BASE_URL"),
        "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"),
        "llm-proxy": (
            "GATEWAY_LLM_UPSTREAM_URL",
            "GATEWAY_LLM_UPSTREAM_API_KEY",
        ),
        "gitlab": ("GITLAB_API_BASE_URL",),
        "telegram": ("TELEGRAM_BOT_TOKEN",),
    }
    if system == "tracker":
        return present("TRACKER_ORG_ID") != present("TRACKER_CLOUD_ORG_ID")
    return all(present(key) for key in required[system])


async def _run_check(system: str) -> dict[str, Any]:
    if system == "gitlab":
        from gateway_mcp.services.factory_connections import check_connection

        return await check_connection("gitlab")
    if system == "tracker":
        return {
            "ok": True,
            "message": "Организация Tracker настроена; OAuth проверяется у пользователя.",
        }
    timeout = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "60"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        if system == "bitrix24":
            base = integration_value(system, "BITRIX24_WEBHOOK_URL").rstrip("/")
            response = await client.get(f"{base}/profile.json")
        elif system == "yonote":
            base = integration_value(
                system, "YONOTE_BASE_URL", "https://wiki.example.com"
            ).rstrip("/")
            response = await client.post(
                f"{base}/api/documents.search",
                headers={
                    "Authorization": f"Bearer {integration_value(system, 'YONOTE_API_KEY')}"
                },
                json={"query": "GatewayMCP", "limit": 1},
            )
        elif system == "openrouter":
            base = integration_value(
                system, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ).rstrip("/")
            response = await client.get(
                f"{base}/models",
                headers={
                    "Authorization": f"Bearer {integration_value(system, 'OPENROUTER_API_KEY')}"
                },
            )
        elif system == "llm-proxy":
            base = integration_value(
                system,
                "GATEWAY_LLM_UPSTREAM_URL",
                "https://openrouter.ai/api/v1",
            ).rstrip("/")
            response = await client.get(
                f"{base}/models",
                headers={
                    "Authorization": f"Bearer {integration_value(system, 'GATEWAY_LLM_UPSTREAM_API_KEY')}"
                },
            )
        elif system == "telegram":
            token = integration_value(system, "TELEGRAM_BOT_TOKEN")
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        else:
            raise ValueError("Unknown managed integration")
    if response.is_success:
        return {
            "ok": True,
            "message": f"Подключение отвечает: HTTP {response.status_code}.",
        }
    return {
        "ok": False,
        "message": f"Внешняя система вернула HTTP {response.status_code}.",
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
