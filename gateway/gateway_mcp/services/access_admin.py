from typing import Any

from gateway_mcp.services.access_common import normalize_key, normalize_subject_type, normalize_system, parse_actions, parse_ttl, _normalize_effect
from gateway_mcp.services.policy import GatewayActor
from gateway_mcp.services.access_packages import access_package
from gateway_mcp.services.storage import (
    insert_access_bundle,
    insert_resource_grant,
    insert_scope_grant,
    list_access_bundles,
    list_resource_grants,
    list_scope_grants,
    revoke_resource_grants,
    revoke_access_bundle,
    revoke_scope_grants,
)


def admin_grant_access_package(
    *,
    subject_type: str,
    subject_key: str,
    package_key: str,
    reason: str,
    actor: GatewayActor,
    ttl_days: int | None,
    dry_run: bool = True,
) -> dict[str, Any]:
    package = access_package(package_key)
    payload = {
        "subject_type": normalize_subject_type(subject_type),
        "subject_key": normalize_key(subject_key),
        "package_key": str(package["key"]),
        "package_version": int(package["version"]),
        "title": str(package["title"]),
        "scopes": list(package["scopes"]),
        "resources": list(package["resources"]),
        "reason": str(reason or "").strip(),
        "created_by": actor.subject,
        "ttl_days": parse_ttl(ttl_days),
    }
    if not payload["reason"]:
        raise ValueError("reason is required")
    if dry_run:
        return {"dry_run": True, "package": payload}
    result = insert_access_bundle(**payload)
    return {"dry_run": False, **result}


def admin_list_access_packages(
    *,
    subject_type: str = "",
    subject_key: str = "",
    include_revoked: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "packages": list_access_bundles(
            subject_type=(normalize_subject_type(subject_type) if subject_type else ""),
            subject_key=(normalize_key(subject_key) if subject_key else ""),
            include_revoked=include_revoked,
            limit=limit,
        )
    }


def admin_revoke_access_package(
    *, actor: GatewayActor, bundle_id: str, dry_run: bool = True
) -> dict[str, Any]:
    normalized_id = str(bundle_id or "").strip()
    if not normalized_id:
        raise ValueError("bundle_id is required")
    if dry_run:
        return {"dry_run": True, "bundle_id": normalized_id}
    return {
        "dry_run": False,
        **revoke_access_bundle(
            bundle_id=normalized_id,
            actor_subject=actor.subject,
        ),
    }

def admin_list_access(
    *,
    subject_type: str = "",
    subject_key: str = "",
    system: str = "",
    include_revoked: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    normalized_subject_type = normalize_subject_type(subject_type) if subject_type else ""
    normalized_subject_key = normalize_key(subject_key) if subject_key else ""
    normalized_system = normalize_system(system) if system else ""
    return {
        "scope_grants": list_scope_grants(
            subject_type=normalized_subject_type,
            subject_key=normalized_subject_key,
            include_revoked=include_revoked,
            limit=limit,
        ),
        "resource_grants": list_resource_grants(
            subject_type=normalized_subject_type,
            subject_key=normalized_subject_key,
            system=normalized_system,
            include_revoked=include_revoked,
            limit=limit,
        ),
    }


def admin_grant_scope(
    *,
    subject_type: str,
    subject_key: str,
    scope: str,
    effect: str,
    reason: str,
    actor: GatewayActor,
    ttl_days: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    payload = {
        "subject_type": normalize_subject_type(subject_type),
        "subject_key": normalize_key(subject_key),
        "scope": str(scope or "").strip(),
        "effect": _normalize_effect(effect),
        "reason": reason,
        "created_by": actor.subject,
        "ttl_days": parse_ttl(ttl_days),
    }
    if not payload["scope"]:
        raise ValueError("scope is required")
    if dry_run:
        return {"dry_run": True, "grant": payload}
    return {"dry_run": False, "grant": insert_scope_grant(**payload)}


def admin_revoke_scope(
    *,
    actor: GatewayActor,
    grant_id: int | None = None,
    subject_type: str = "",
    subject_key: str = "",
    scope: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    payload = {
        "grant_id": grant_id,
        "subject_type": normalize_subject_type(subject_type) if subject_type else "",
        "subject_key": normalize_key(subject_key) if subject_key else "",
        "scope": str(scope or "").strip(),
        "actor_subject": actor.subject,
    }
    if grant_id is None and not any((payload["subject_type"], payload["subject_key"], payload["scope"])):
        raise ValueError("grant_id or a revoke filter is required")
    if dry_run:
        return {"dry_run": True, "revoke": payload}
    return {"dry_run": False, "revoked": revoke_scope_grants(**payload)}


def admin_grant_resource(
    *,
    subject_type: str,
    subject_key: str,
    system: str,
    resource_pattern: str,
    actions_json: str,
    resource_type: str,
    effect: str,
    priority: int,
    reason: str,
    actor: GatewayActor,
    ttl_days: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    payload = {
        "subject_type": normalize_subject_type(subject_type),
        "subject_key": normalize_key(subject_key),
        "system": normalize_system(system),
        "resource_type": str(resource_type or "").strip().casefold(),
        "resource_pattern": str(resource_pattern or "").strip(),
        "actions": parse_actions(actions_json),
        "effect": _normalize_effect(effect),
        "priority": int(priority),
        "reason": reason,
        "created_by": actor.subject,
        "ttl_days": parse_ttl(ttl_days),
    }
    if not payload["system"]:
        raise ValueError("system is required")
    if not payload["resource_pattern"]:
        raise ValueError("resource_pattern is required")
    if dry_run:
        return {"dry_run": True, "grant": payload}
    return {"dry_run": False, "grant": insert_resource_grant(**payload)}


def admin_revoke_resource(
    *,
    actor: GatewayActor,
    grant_id: int | None = None,
    subject_type: str = "",
    subject_key: str = "",
    system: str = "",
    resource_pattern: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    payload = {
        "grant_id": grant_id,
        "subject_type": normalize_subject_type(subject_type) if subject_type else "",
        "subject_key": normalize_key(subject_key) if subject_key else "",
        "system": normalize_system(system) if system else "",
        "resource_pattern": str(resource_pattern or "").strip(),
        "actor_subject": actor.subject,
    }
    if grant_id is None and not any((payload["subject_type"], payload["subject_key"], payload["system"], payload["resource_pattern"])):
        raise ValueError("grant_id or a revoke filter is required")
    if dry_run:
        return {"dry_run": True, "revoke": payload}
    return {"dry_run": False, "revoked": revoke_resource_grants(**payload)}
    list_access_bundles,
    revoke_access_bundle,
