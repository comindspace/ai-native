import fnmatch
from typing import Any

from gateway_mcp.services.access_common import (
    READ_ACTIONS,
    WRITE_ACTIONS,
    normalize_action,
    normalize_key,
    normalize_system,
    resource_policy_mode,
)
from gateway_mcp.services.access_inference import infer_route_access
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage import list_active_resource_grants


def subjects_for_actor(actor: GatewayActor) -> list[tuple[str, str]]:
    subjects = {("user", normalize_key(actor.subject))}
    for value in (actor.email, actor.login, actor.yandex_id):
        if value:
            subjects.add(("user", normalize_key(value)))
    for group in actor.groups:
        subjects.add(("group", normalize_key(group)))
    return sorted(subjects)


def explain_resource_access(
    *,
    actor: GatewayActor,
    system: str,
    action: str,
    resource: str,
    resource_type: str = "",
) -> dict[str, Any]:
    normalized_system = normalize_system(system)
    normalized_action = normalize_action(action)
    normalized_resource = str(resource or "*").strip() or "*"
    subjects = subjects_for_actor(actor)
    grants = list_active_resource_grants(subjects=subjects, system=normalized_system)
    matches = [
        grant
        for grant in grants
        if _grant_matches(
            grant=grant,
            action=normalized_action,
            resource=normalized_resource,
            resource_type=resource_type,
        )
    ]

    deny = next((grant for grant in matches if grant.get("effect") == "deny"), None)
    allow = next((grant for grant in matches if grant.get("effect") == "allow"), None)
    strict = resource_policy_mode() == "strict"
    decision = "deny" if deny else "allow" if allow or not strict else "deny"
    reason = (
        "matched_deny"
        if deny
        else "matched_allow"
        if allow
        else "no_policy_permissive"
        if not strict
        else "no_policy_strict"
    )
    return {
        "decision": decision,
        "reason": reason,
        "mode": resource_policy_mode(),
        "system": normalized_system,
        "action": normalized_action,
        "resource_type": resource_type,
        "resource": normalized_resource,
        "subjects": [{"type": item[0], "key": item[1]} for item in subjects],
        "matched": matches,
    }


def require_resource_access(
    *,
    actor: GatewayActor,
    route: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    inferred = infer_route_access(route, arguments)
    system = inferred["system"]
    action = inferred["action"]
    if has_scope(actor, "*") or not system:
        return {"decision": "allow", "reason": "scope_admin", **inferred}

    explanation = explain_resource_access(
        actor=actor,
        system=system,
        action=action,
        resource=inferred["resource"],
        resource_type=inferred["resource_type"],
    )
    if explanation["decision"] != "allow":
        raise PermissionError(
            f"resource access denied: {system}:{action} {inferred['resource_type']} {inferred['resource']}"
        )
    return explanation


def _grant_matches(
    *, grant: dict[str, Any], action: str, resource: str, resource_type: str
) -> bool:
    grant_resource_type = str(grant.get("resource_type") or "").casefold()
    if (
        grant_resource_type
        and resource_type
        and grant_resource_type != resource_type.casefold()
    ):
        return False
    actions = grant.get("actions") if isinstance(grant.get("actions"), list) else []
    normalized_actions = {normalize_action(item) for item in actions}
    if "*" not in normalized_actions and action not in normalized_actions:
        covered_by_read = action in READ_ACTIONS and "read" in normalized_actions
        covered_by_write = action in WRITE_ACTIONS and "write" in normalized_actions
        if not covered_by_read and not covered_by_write:
            return False
    pattern = str(grant.get("resource_pattern") or "*")
    return pattern == "*" or fnmatch.fnmatchcase(
        resource.casefold(), pattern.casefold()
    )
