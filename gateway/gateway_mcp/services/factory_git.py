from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from gateway_mcp.config import public_url
from gateway_mcp.services import storage_factory
from gateway_mcp.services.factory_preflight import lease_readiness_valid
from gateway_mcp.services.factory_readiness import (
    check_destination,
    connection_settings,
)
from gateway_mcp.services.policy import has_scope
from gateway_mcp.services.work import _require_project_access, get_work

WORK_ID = re.compile(r"work-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def enabled() -> bool:
    return os.getenv("GATEWAY_FACTORY_GIT_ENABLED", "false").casefold() in {
        "true",
        "1",
        "yes",
    }


def authorize_git(actor, work_id: str):
    if not enabled():
        raise PermissionError("Factory Git transport is disabled")
    if (
        not WORK_ID.fullmatch(work_id)
        or not has_scope(actor, "factory:git")
        or not has_scope(actor, "factory:claim")
    ):
        raise PermissionError("Factory Git access is required")
    work = get_work(actor, work_id, include_events=False)
    _require_project_access(actor, "write", work["project_id"])
    expiry = work.get("lease_expires_at")
    if (
        work.get("execution_mode") != "factory"
        or work.get("status") != "running"
        or work.get("scope_decision") not in {"within_scope", "clarification"}
        or work.get("claimed_by") != actor.subject
        or not expiry
        or datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        <= datetime.now(timezone.utc)
    ):
        raise PermissionError("An active owned Factory lease is required")
    row = storage_factory.get_project(work["project_id"])
    if not row:
        raise PermissionError("Factory project is not registered")
    config = row["config"]
    connection = connection_settings(config["gitlab_connection_id"])
    check_destination(config, connection)
    metadata = (work.get("contract") or {}).get("metadata") or {}
    if (
        work.get("project_path") != config["project_path"]
        or str(metadata.get("gitlab_backend") or "").rstrip("/")
        != connection["base_url"]
    ):
        raise PermissionError(
            "Work repository identity does not match the registration"
        )
    readiness = row.get("readiness") or {}
    if not lease_readiness_valid(work, row):
        raise PermissionError("A verified preflight admission is required")
    if (
        not readiness.get("ready")
        or readiness.get("connection_version") != connection["version"]
        or storage_factory.list_probes(work["project_id"])
    ):
        raise PermissionError(
            "Validate the current project connection before execution"
        )
    branch = "codex/" + work_id
    if branch in {config["default_base_branch"], config["mr_target_branch"]}:
        raise PermissionError("Work branch must not be a base or target branch")
    return work, config, connection, branch


def transport_config(actor, work_id: str) -> dict:
    work, config, _, branch = authorize_git(actor, work_id)
    base = public_url().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("Factory Git requires a public HTTPS Gateway URL")
    return {
        "clone_url": f"{base}/factory/git/{work_id}/repo.git",
        "branch": branch,
        "default_base_branch": config["default_base_branch"],
        "mr_target_branch": config["mr_target_branch"],
        "authentication": "gateway_bearer",
        "lease_expires_at": str(work["lease_expires_at"]),
        "upstream_credentials_exposed": False,
    }


def validate_push(body: bytes, branch: str) -> None:
    """Parse receive-pack commands before forwarding any pack bytes upstream.

    Allow exactly one non-delete ref update. Reject signed pushes and push-options
    (which can request server-side MR merging or CI variables).
    """
    offset, commands, shallow_count = 0, 0, 0
    while True:
        if offset + 4 > len(body) or not re.fullmatch(
            rb"[0-9a-fA-F]{4}", body[offset : offset + 4]
        ):
            raise ValueError("Malformed Git command framing")
        length = int(body[offset : offset + 4], 16)
        if length == 0:
            offset += 4
            break
        if length < 4 or length > 65520 or offset + length > len(body):
            raise ValueError("Malformed Git command length")
        packet = body[offset + 4 : offset + length]
        offset += length
        if packet.startswith(b"shallow "):
            shallow_count += 1
            if (
                commands
                or shallow_count > 1024
                or not re.fullmatch(rb"shallow [0-9a-f]{40}\n?", packet)
            ):
                raise ValueError("Malformed Git shallow boundary")
            continue
        if b"\x00" in packet:
            packet, capabilities = packet.split(b"\x00", 1)
            allowed = {
                b"report-status",
                b"report-status-v2",
                b"side-band-64k",
                b"quiet",
                b"atomic",
                b"ofs-delta",
                b"object-format=sha1",
            }
            if commands or any(
                c not in allowed and not re.fullmatch(rb"agent=[\x21-\x7e]{1,200}", c)
                for c in capabilities.strip(b"\n ").split(b" ")
            ):
                raise ValueError("Unsupported Git push capabilities")
        parts = packet.rstrip(b"\n").split(b" ")
        if len(parts) != 3 or any(
            not re.fullmatch(rb"[0-9a-f]{40}", sha) for sha in parts[:2]
        ):
            raise ValueError("Unsupported Git ref update")
        if parts[2] != ("refs/heads/" + branch).encode() or parts[1] == b"0" * 40:
            raise PermissionError(
                "Only non-delete updates to the assigned work branch are allowed"
            )
        commands += 1
        if commands > 1:
            raise PermissionError("Only one work branch may be pushed")
    if commands != 1 or (body[offset:] and not body[offset:].startswith(b"PACK")):
        raise ValueError("Unsupported Git push payload")
