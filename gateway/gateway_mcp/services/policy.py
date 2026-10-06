import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway_mcp.config import resolve_configured_path
from gateway_mcp.services.storage import list_active_scope_grants

DEFAULT_POLICY: dict[str, Any] = {
    "schema": 1,
    "allowed_email_domains": [],
    "default_groups": ["employees"],
    "groups": {
        "employees": {
            "scopes": [
                "access:request",
                "skills:read",
                "tools:read",
                "company:read",
                "factory:read",
                "factory:write",
                "files:read",
                "files:write",
                "llm:proxy",
                "privacy:use",
                "process:read",
                "approvals:read",
                "approvals:write",
                "memory:read",
                "memory:write",
                "notifications:read",
                "notifications:write",
                "telemetry:write",
            ]
        },
        "tool-callers": {
            "scopes": [
                "tools:call",
            ]
        },
        "service-agents": {
            "scopes": [
                "factory:read",
                "factory:write",
                "factory:claim",
            ]
        },
        "notification-writers": {
            "scopes": [
                "notifications:write",
                "notifications:broadcast",
            ]
        },
        "notification-readers": {
            "scopes": [
                "notifications:read",
            ]
        },
        "file-readers": {
            "scopes": [
                "files:read",
            ]
        },
        "file-writers": {
            "scopes": [
                "files:read",
                "files:write",
            ]
        },
        "llm-proxy-users": {
            "scopes": [
                "llm:proxy",
                "privacy:use",
            ]
        },
        "privacy-users": {
            "scopes": [
                "privacy:use",
            ]
        },
        "mail-readers": {
            "scopes": [
                "mail:read",
            ]
        },
        "mail-senders": {
            "scopes": [
                "mail:send",
            ]
        },
        "access-readers": {
            "scopes": [
                "access:read",
            ]
        },
        "process-readers": {
            "scopes": [
                "process:read",
            ]
        },
        "access-admins": {
            "scopes": [
                "access:read",
                "access:admin",
            ]
        },
        "approval-reviewers": {
            "scopes": [
                "approvals:read",
                "approvals:write",
            ]
        },
        "approval-admins": {
            "scopes": [
                "approvals:read",
                "approvals:write",
                "approvals:admin",
            ]
        },
        "telemetry-readers": {
            "scopes": [
                "telemetry:read",
            ]
        },
        "telemetry-writers": {
            "scopes": [
                "telemetry:write",
            ]
        },
        "admins": {"scopes": ["*"]},
    },
    "users": {},
}


@dataclass(frozen=True)
class GatewayActor:
    subject: str
    email: str = ""
    login: str = ""
    yandex_id: str = ""
    groups: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return self.email or self.login or self.subject


def _policy_file() -> Path:
    return resolve_configured_path("GATEWAY_POLICY_FILE", "gateway-policy.json")


def _read_policy() -> dict[str, Any]:
    path = _policy_file()
    if not path.exists():
        return DEFAULT_POLICY

    loaded = json.loads(path.read_text(encoding="utf-8"))
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    policy.update(loaded)
    policy["groups"] = {**DEFAULT_POLICY["groups"], **loaded.get("groups", {})}
    return policy


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _user_keys(user_info: dict[str, Any]) -> list[str]:
    keys = []
    for key in ("default_email", "email", "login", "id", "uid", "psuid"):
        value = user_info.get(key)
        if value:
            keys.append(str(value))
    return keys


def _matches_allowed_domain(email: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].casefold()
    return domain in {item.casefold().lstrip("@") for item in allowed_domains}


def is_user_allowed(user_info: dict[str, Any]) -> bool:
    policy = _read_policy()
    env_domains = _split_csv(os.getenv("GATEWAY_ALLOWED_EMAIL_DOMAINS", ""))
    allowed_domains = env_domains or list(policy.get("allowed_email_domains", []))
    email = str(user_info.get("default_email") or user_info.get("email") or "")
    users = policy.get("users", {})

    if any(key in users for key in _user_keys(user_info)):
        return True

    return _matches_allowed_domain(email, allowed_domains)


def actor_from_user_info(
    user_info: dict[str, Any], *, include_database_grants: bool = True
) -> GatewayActor:
    policy = _read_policy()
    users = policy.get("users", {})
    matched_user: dict[str, Any] = {}
    for key in _user_keys(user_info):
        if key in users:
            matched_user = users[key]
            break

    groups = list(policy.get("default_groups", []))
    groups.extend(matched_user.get("groups", []))

    scopes: set[str] = set(matched_user.get("scopes", []))
    for group in groups:
        scopes.update(policy.get("groups", {}).get(group, {}).get("scopes", []))

    yandex_id = str(user_info.get("id") or user_info.get("uid") or "")
    login = str(user_info.get("login") or "")
    email = str(user_info.get("default_email") or user_info.get("email") or "")
    subject = f"yandex:{yandex_id or login or email}"
    if include_database_grants:
        _apply_database_scope_grants(
            scopes,
            subject=subject,
            email=email,
            login=login,
            yandex_id=yandex_id,
            groups=groups,
        )

    return GatewayActor(
        subject=subject,
        email=email,
        login=login,
        yandex_id=yandex_id,
        groups=tuple(sorted(set(groups))),
        scopes=tuple(sorted(scopes)),
    )


def actor_from_claims(claims: dict[str, Any]) -> GatewayActor:
    policy = _read_policy()
    scopes = claims.get("scope", "")
    if isinstance(scopes, str):
        scope_values = {scope for scope in scopes.split(" ") if scope}
    else:
        scope_values = set(scopes or [])

    groups = claims.get("groups", [])
    for group in groups or []:
        scope_values.update(policy.get("groups", {}).get(group, {}).get("scopes", []))
    subject = str(claims.get("sub", ""))
    email = str(claims.get("email", ""))
    login = str(claims.get("login", ""))
    yandex_id = str(claims.get("yandex_id", ""))
    _apply_database_scope_grants(
        scope_values,
        subject=subject,
        email=email,
        login=login,
        yandex_id=yandex_id,
        groups=list(groups or []),
    )
    return GatewayActor(
        subject=subject,
        email=email,
        login=login,
        yandex_id=yandex_id,
        groups=tuple(groups or []),
        scopes=tuple(sorted(scope_values)),
    )


def has_scope(actor: GatewayActor, required_scope: str) -> bool:
    if not required_scope:
        return True
    scopes = set(actor.scopes)
    if "*" in scopes or required_scope in scopes:
        return True
    if ":" not in required_scope:
        return False
    domain, action = required_scope.split(":", 1)
    return action == "read" and f"{domain}:admin" in scopes


def _apply_database_scope_grants(
    scopes: set[str],
    *,
    subject: str,
    email: str,
    login: str,
    yandex_id: str,
    groups: list[str],
) -> None:
    subjects = {("user", _normalize_key(subject))}
    for value in (email, login, yandex_id):
        if value:
            subjects.add(("user", _normalize_key(value)))
    for group in groups:
        subjects.add(("group", _normalize_key(group)))

    try:
        grants = list_active_scope_grants(sorted(subjects))
    except Exception:  # noqa: BLE001 - policy enrichment degrades to token scopes
        return

    for grant in grants:
        scope = str(grant.get("scope") or "").strip()
        if not scope:
            continue
        if grant.get("effect") == "deny":
            scopes.discard(scope)
        else:
            scopes.add(scope)


def _normalize_key(value: str) -> str:
    return str(value or "").strip().casefold()
