from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import httpx

from gateway_mcp.services import storage_factory
from gateway_mcp.services import storage_service_connections as store
from gateway_mcp.services.access_policy import explain_resource_access
from gateway_mcp.services.factory_readiness import clean_url, connection_settings
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.policy import GatewayActor, has_scope

REFERENCE = re.compile(r"gitlab(?::[a-z0-9][a-z0-9_.-]{0,100})?")
PROJECT = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+")


def require_connection_admin(actor: GatewayActor) -> None:
    if not (has_scope(actor, "factory:admin") or has_scope(actor, "access:admin")):
        raise PermissionError("factory:admin or access:admin is required")


def repository_paths(raw: str) -> list[str]:
    paths = sorted(set(raw.replace(",", "\n").split()))
    if (
        not paths
        or len(paths) > 200
        or any(
            not PROJECT.fullmatch(path)
            or len(path) > 500
            or any(
                part in {".", ".."} or part.endswith(".git") for part in path.split("/")
            )
            for path in paths
        )
    ):
        raise ValueError(
            "Укажи точные пути репозиториев: группа/проект, без URL и масок."
        )
    return paths


def allowed_repositories(payload: dict) -> list[str] | None:
    raw = payload.get("FACTORY_ALLOWED_REPOSITORIES")
    if raw is None:
        return None  # Existing CLI connections retain their explicit binding policy.
    paths = json.loads(raw)
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise ValueError("Invalid repository allowlist")
    return repository_paths("\n".join(paths))


def save_connection(
    *,
    actor: GatewayActor,
    reference: str,
    api_url: str,
    username: str,
    token: str,
    repositories: str,
    expires_at: datetime | None,
    expected_version: int,
) -> None:
    require_connection_admin(actor)
    if reference == "gitlab" and not has_scope(actor, "access:admin"):
        raise PermissionError("access:admin is required for the shared GitLab endpoint")
    if not REFERENCE.fullmatch(reference) or expected_version < 0:
        raise ValueError("Некорректный идентификатор или версия подключения.")
    base = clean_url(api_url.strip())
    if not base.endswith("/api/v4"):
        raise ValueError("Адрес API должен оканчиваться на /api/v4.")
    username = username.strip()
    if (
        not username
        or len(username) > 200
        or any(ord(c) < 33 or c == ":" for c in username)
    ):
        raise ValueError("Укажи служебный логин GitLab.")
    paths = repository_paths(repositories)
    if expires_at and (
        expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc)
    ):
        raise ValueError("Срок действия должен быть в будущем, с часовым поясом.")
    existing = store.get_service_connection(reference, include_payload=True)
    if int((existing or {}).get("version", 0)) != expected_version:
        raise ValueError("Подключение изменилось. Обнови страницу.")
    previous = (existing or {}).get("payload") or {}
    token = token.strip()
    if not token:
        if previous.get("GITLAB_API_BASE_URL") != base:
            raise ValueError("Для нового адреса GitLab нужен новый токен.")
        token = str(previous.get("GITLAB_TOKEN") or "")
    if not token or len(token) > 4096 or any(ord(c) < 33 for c in token):
        raise ValueError("Укажи действующий служебный токен GitLab.")
    # Keep unrelated managed fields when editing the legacy shared connection.
    payload = {
        **previous,
        "GITLAB_API_BASE_URL": base,
        "GITLAB_USERNAME": username,
        "GITLAB_TOKEN": token,
        "FACTORY_ALLOWED_REPOSITORIES": json.dumps(paths),
    }
    store.upsert_service_connection(
        system=reference,
        payload=payload,
        updated_by=actor.subject,
        expires_at=expires_at,
        expected_version=expected_version,
    )
    _audit(actor, reference, "save")
    if reference == "gitlab":
        from gateway_mcp.services.managed_integrations import (
            invalidate_integration_cache,
        )

        invalidate_integration_cache("gitlab")


def disable_connection(
    *, actor: GatewayActor, reference: str, expected_version: int
) -> None:
    require_connection_admin(actor)
    if reference == "gitlab" and not has_scope(actor, "access:admin"):
        raise PermissionError("access:admin is required for the shared GitLab endpoint")
    if not REFERENCE.fullmatch(reference):
        raise ValueError("Некорректное подключение.")
    row = store.get_service_connection(reference)
    if not row or row["version"] != expected_version:
        raise ValueError("Подключение изменилось. Обнови страницу.")
    if row["state"] != "disabled" and not store.set_service_connection_state(
        reference,
        state="disabled",
        updated_by=actor.subject,
        expected_version=expected_version,
    ):
        raise ValueError("Подключение изменилось. Обнови страницу.")
    _audit(actor, reference, "disable")


def _audit(actor: GatewayActor, reference: str, action: str) -> None:
    audit_event(
        event="factory_connection_change",
        actor=actor,
        system="factory",
        decision="allow",
        status="ok",
        arguments={
            "action": action,
            "connection_fingerprint": hashlib.sha256(reference.encode()).hexdigest()[
                :16
            ],
        },
    )


def connection_cards(actor: GatewayActor) -> list[dict]:
    require_connection_admin(actor)
    projects = storage_factory.list_projects()
    result = []
    for summary in store.list_service_connections():
        reference = summary["system"]
        if not REFERENCE.fullmatch(reference):
            continue
        try:
            row = store.get_service_connection(reference, include_payload=True) or {}
            payload = row.get("payload") or {}
            paths = allowed_repositories(payload)
            expires = row.get("expires_at")
            expired = expires and datetime.fromisoformat(expires) <= datetime.now(
                timezone.utc
            )
            configured = bool(payload.get("GITLAB_TOKEN"))
            state = "expired" if expired else row.get("state", "missing")
            if state == "active" and not configured:
                state = "missing"
            card = {
                "connection_id": reference,
                "api_url": clean_url(payload.get("GITLAB_API_BASE_URL", "")),
                "username": payload.get("GITLAB_USERNAME", "oauth2"),
                "repositories": paths,
                "state": state,
                "version": row.get("version", 0),
                "expires_at": expires,
                "last_check_ok": row.get("last_check_ok"),
                "last_checked_at": row.get("last_checked_at"),
                "token_configured": configured,
            }
        except (ValueError, RuntimeError):
            card = {
                "connection_id": reference,
                "state": "invalid",
                "version": summary["version"],
            }
        card["projects"] = [
            r["project_id"]
            for r in projects
            if r["config"].get("gitlab_connection_id") == reference
        ]
        result.append(card)
    return result


def discover_connections(
    *, actor: GatewayActor, project_id: str, repository_url: str
) -> list[dict]:
    from gateway_mcp.services.factory_admin import require_project_admin

    require_project_admin(actor, project_id)
    repository_url = clean_url(repository_url)
    result = []
    for row in store.list_service_connections():
        reference = row["system"]
        if not REFERENCE.fullmatch(reference):
            continue
        if not has_scope(actor, "factory:admin"):
            checks = [
                explain_resource_access(
                    actor=actor,
                    system="factory",
                    action="write",
                    resource=value,
                    resource_type=kind,
                )
                for kind, value in (
                    ("connection", reference),
                    ("repository", repository_url),
                )
            ]
            if any(
                c["decision"] != "allow" or c["reason"] != "matched_allow"
                for c in checks
            ):
                continue
        try:
            settings = connection_settings(reference)
            prefix = settings["base_url"] + "/"
            if not repository_url.startswith(prefix):
                continue
            path = repository_url[len(prefix) :]
            if (
                settings.get("repositories") is not None
                and path not in settings["repositories"]
            ):
                continue
            result.append(
                {
                    "connection_id": reference,
                    "gitlab_web_url": settings["base_url"],
                    "state": "configured",
                    "version": settings["version"],
                }
            )
        except (ValueError, RuntimeError):
            continue
    return result


async def check_connection(reference: str) -> dict:
    version = None
    try:
        settings = connection_settings(reference)
        version = settings["version"]
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                settings["api_url"] + "/user",
                headers={"PRIVATE-TOKEN": settings["token"]},
            )
        if response.status_code == 200:
            code, message = "authenticated", "GitLab подтвердил служебную авторизацию."
        elif response.status_code in {401, 403}:
            code, message = (
                "authentication_denied",
                "GitLab отклонил токен или его права.",
            )
        elif 300 <= response.status_code < 400:
            code, message = (
                "redirect_denied",
                "GitLab перенаправляет запрос. Проверь точный адрес API.",
            )
        else:
            code, message = "upstream_error", "GitLab вернул ошибку API."
    except (ValueError, RuntimeError):
        code, message = (
            "connection_unavailable",
            "Служебное подключение не настроено, отключено или истекло.",
        )
    except Exception:  # noqa: BLE001 - diagnostics never expose upstream error bodies
        code, message = (
            "network_error",
            "Не удалось связаться с GitLab. Проверь DNS, сеть и TLS.",
        )
    ok = code == "authenticated"
    if version is not None:
        recorded = store.record_service_connection_check(
            reference, ok=ok, message=message, expected_version=version
        )
        if not recorded:
            return {
                "ok": False,
                "code": "connection_changed",
                "message": "Подключение изменилось во время проверки. Повтори проверку.",
            }
    return {"ok": ok, "code": code, "message": message}
