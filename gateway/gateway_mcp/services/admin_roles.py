"""Admin-role UI delegates all grants to the existing access service."""

from typing import Any

from gateway_mcp.services.access_admin import admin_grant_scope
from gateway_mcp.services.access_policy import subjects_for_actor
from gateway_mcp.services.policy import actor_from_user_info, has_scope
from gateway_mcp.services.storage import list_active_scope_grants
from gateway_mcp.services.storage_admin_console import admin_user_get
from gateway_mcp.services.storage_admin_roles import admin_role_assignment_lock


def admin_role_state(user: dict[str, Any]) -> dict[str, Any]:
    """Resolve the same identity aliases and bootstrap policy as a fresh login."""
    subject = str(user["subject"])
    yandex_id = str(user.get("yandex_id") or "")
    if not yandex_id and subject.startswith("yandex:"):
        yandex_id = subject.removeprefix("yandex:")
    actor = actor_from_user_info(
        {
            "id": yandex_id,
            "login": user.get("login", ""),
            "default_email": user.get("email", ""),
        },
        include_database_grants=False,
    )
    subjects = sorted(set(subjects_for_actor(actor)) | {("user", subject.casefold())})
    # Unlike policy enrichment, this explicit read fails closed on a DB error.
    grants = list_active_scope_grants(subjects)
    relevant = [
        {key: row.get(key) for key in ("id", "scope", "effect", "expires_at")}
        for row in grants
        if row.get("scope") in {"*", "access:admin"}
    ]
    denied = any(row.get("effect") == "deny" for row in relevant)
    return {
        "is_admin": not denied
        and (
            has_scope(actor, "access:admin")
            or any(row.get("effect") == "allow" for row in relevant)
        ),
        "denied": denied,
        "grants": sorted(relevant, key=lambda row: str(row["id"])),
    }


def require_current_admin(actor):
    """Signed token claims identify the caller; live policy alone authorizes writes."""
    state = admin_role_state(
        {
            "subject": actor.subject,
            "yandex_id": actor.yandex_id,
            "email": actor.email,
            "login": actor.login,
        }
    )
    if not state["is_admin"]:
        raise PermissionError("current administrator authority required")


def assign_admin_role(actor, preview):
    """Recheck and grant under one recipient lock, including different confirmations."""
    subject = preview["user"]["subject"]
    with admin_role_assignment_lock(subject):
        require_current_admin(actor)
        user = admin_user_get(subject)
        if user != preview["user"]:
            raise ValueError("recipient changed")
        state = admin_role_state(user)
        if state != preview["state"] or state["is_admin"] or state["denied"]:
            raise ValueError("recipient role changed")
        grant = preview["grant"]
        return admin_grant_scope(
            actor=actor,
            subject_type="user",
            subject_key=subject,
            scope="access:admin",
            effect="allow",
            reason=grant["reason"],
            ttl_days=grant["ttl_days"],
            dry_run=False,
        )
