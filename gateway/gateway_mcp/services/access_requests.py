from typing import Any

from gateway_mcp.services.access_admin import (
    admin_grant_access_package,
    admin_list_access_packages,
)
from gateway_mcp.services.access_common import normalize_key, parse_ttl
from gateway_mcp.services.access_packages import access_package, access_package_catalog
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage import (
    cancel_access_request,
    claim_access_request_decision,
    decide_access_request,
    get_access_request,
    insert_access_request,
    list_access_requests,
    release_access_request_decision,
)

VALID_REQUEST_STATUSES = {
    "pending",
    "processing",
    "approved",
    "rejected",
    "cancelled",
}


def access_profile(actor: GatewayActor) -> dict[str, Any]:
    keys = _actor_keys(actor)
    packages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        result = admin_list_access_packages(
            subject_type="user", subject_key=key, include_revoked=False, limit=100
        )
        for package in result["packages"]:
            package_id = str(package.get("id") or "")
            if package_id and package_id not in seen:
                seen.add(package_id)
                packages.append(package)
    return {
        "actor": {
            "subject": actor.subject,
            "email": actor.email,
            "login": actor.login,
            "groups": list(actor.groups),
            "scopes": list(actor.scopes),
        },
        "access_packages": packages,
        "requests": list_access_requests(requester_subject=actor.subject, limit=25),
    }


def request_access_package(
    *,
    actor: GatewayActor,
    package_key: str,
    reason: str,
    ttl_days: int | None,
    idempotency_key: str,
) -> dict[str, Any]:
    if not actor.subject or actor.subject == "anonymous":
        raise PermissionError("authenticated user is required")
    package = access_package(package_key)
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("reason is required")
    normalized_ttl = parse_ttl(ttl_days)
    if normalized_ttl is not None and normalized_ttl > 365:
        raise ValueError("ttl_days must not exceed 365")
    request = insert_access_request(
        requester_subject=actor.subject,
        requester_email=actor.email,
        subject_key=_preferred_subject_key(actor),
        package_key=str(package["key"]),
        package_version=int(package["version"]),
        reason=normalized_reason,
        requested_ttl_days=normalized_ttl,
        idempotency_key=str(idempotency_key or "").strip(),
    )
    return {"request": request, "package": package}


def list_my_access_requests(
    *, actor: GatewayActor, status: str = "", limit: int = 50
) -> dict[str, Any]:
    return {
        "requests": list_access_requests(
            requester_subject=actor.subject,
            status=_normalize_status(status),
            limit=limit,
        )
    }


def cancel_my_access_request(
    *, actor: GatewayActor, request_id: str, reason: str = ""
) -> dict[str, Any]:
    request = cancel_access_request(
        request_id=_required(request_id, "request_id"),
        requester_subject=actor.subject,
        reason=str(reason or "Cancelled by requester").strip(),
    )
    if request is None:
        raise ValueError("pending access request was not found for current user")
    return {"request": request}


def admin_list_access_requests(
    *,
    requester_subject: str = "",
    status: str = "",
    package_key: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    requests = list_access_requests(
        requester_subject=str(requester_subject or "").strip(),
        status=_normalize_status(status),
        package_key=str(package_key or "").strip().casefold(),
        limit=limit,
    )
    return {"requests": requests}


def admin_decide_access_request(
    *,
    actor: GatewayActor,
    request_id: str,
    decision: str,
    reason: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    if not has_scope(actor, "access:admin"):
        raise PermissionError("access:admin is required")
    normalized_id = _required(request_id, "request_id")
    normalized_decision = str(decision or "").strip().casefold()
    if normalized_decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    normalized_reason = _required(reason, "reason")
    request = get_access_request(normalized_id)
    if request is None:
        raise ValueError(f"access request not found: {normalized_id}")
    actor_keys = set(_actor_keys(actor))
    if any(normalize_key(request.get(key) or "") in actor_keys
           for key in ("requester_subject", "requester_email", "subject_key")):
        raise PermissionError("another administrator must decide this request")
    if request.get("status") != "pending":
        raise ValueError(f"access request is already {request.get('status')}")

    package = access_package(str(request["package_key"]))
    if int(request["package_version"]) != int(package["version"]):
        raise ValueError("access package changed; requester must submit a new request")

    preview: dict[str, Any] = {"request": request, "decision": normalized_decision}
    if normalized_decision == "approved":
        preview["grant"] = admin_grant_access_package(
            subject_type="user",
            subject_key=str(request["subject_key"]),
            package_key=str(request["package_key"]),
            reason=f"Approved access request {normalized_id}: {normalized_reason}",
            actor=actor,
            ttl_days=request.get("requested_ttl_days"),
            dry_run=True,
        )
    if dry_run:
        return {"dry_run": True, **preview}

    claimed = claim_access_request_decision(
        request_id=normalized_id, decided_by=actor.subject
    )
    if claimed is None:
        raise RuntimeError(
            "access request changed while the decision was being applied"
        )

    grant_bundle_id: str | None = None
    grant: dict[str, Any] | None = None
    try:
        if normalized_decision == "approved":
            grant = admin_grant_access_package(
                subject_type="user",
                subject_key=str(request["subject_key"]),
                package_key=str(request["package_key"]),
                reason=f"Approved access request {normalized_id}: {normalized_reason}",
                actor=actor,
                ttl_days=request.get("requested_ttl_days"),
                dry_run=False,
            )
            grant_bundle_id = str(grant.get("bundle", {}).get("id") or "") or None

        decided = decide_access_request(
            request_id=normalized_id,
            decision=normalized_decision,
            decided_by=actor.subject,
            decision_reason=normalized_reason,
            grant_bundle_id=grant_bundle_id,
        )
    except Exception:
        release_access_request_decision(
            request_id=normalized_id, decided_by=actor.subject
        )
        raise
    if decided is None:
        raise RuntimeError(
            "access request changed while the decision was being applied"
        )
    return {"dry_run": False, "request": decided, "grant": grant}


def public_access_package_catalog() -> list[dict[str, Any]]:
    return access_package_catalog()


def _actor_keys(actor: GatewayActor) -> list[str]:
    keys = []
    for value in (actor.email, actor.login, actor.yandex_id, actor.subject):
        normalized = normalize_key(value)
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _preferred_subject_key(actor: GatewayActor) -> str:
    return normalize_key(actor.email or actor.login or actor.yandex_id or actor.subject)


def _normalize_status(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized and normalized not in VALID_REQUEST_STATUSES:
        raise ValueError(f"unknown access request status: {normalized}")
    return normalized


def _required(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized
