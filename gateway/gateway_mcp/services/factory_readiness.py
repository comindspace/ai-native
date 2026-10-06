from __future__ import annotations

import asyncio
import base64
import os
import re
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

from gateway_mcp.services import storage_factory
from gateway_mcp.services.storage_service_connections import get_service_connection

UTC = timezone.utc
CHECKS = (
    "dns",
    "network",
    "authentication",
    "repository",
    "branch",
    "clone",
    "push_permissions",
    "cleanup",
)


def provision_connection(
    connection_id: str, api_url: str, username: str, token: str
) -> None:
    """Local platform-operator entry point; secrets never become CLI arguments."""
    from gateway_mcp.services.storage_service_connections import (
        upsert_service_connection,
    )

    if not re.fullmatch(r"gitlab(?::[a-z0-9][a-z0-9_.-]{0,100})?", connection_id):
        raise ValueError("invalid GitLab connection reference")
    base = clean_url(api_url)
    if not base.endswith("/api/v4") or not token.strip() or not username.strip():
        raise ValueError("API URL, username and token are required")
    upsert_service_connection(
        system=connection_id,
        payload={
            "GITLAB_API_BASE_URL": base,
            "GITLAB_USERNAME": username,
            "GITLAB_TOKEN": token,
        },
        updated_by="local:factory-connection",
        expires_at=None,
    )


def clean_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 33 for char in value)
        or "\\" in value
        or "%" in value
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise ValueError(
            "GitLab URLs must be credential-free HTTPS URLs without query or fragment"
        )
    return value.rstrip("/")


def connection_settings(connection_id: str) -> dict:
    from gateway_mcp.services.factory_connections import allowed_repositories

    if not re.fullmatch(r"gitlab(?::[a-z0-9][a-z0-9_.-]{0,100})?", connection_id):
        raise ValueError("invalid GitLab connection reference")
    row = get_service_connection(connection_id, include_payload=True)
    if not row or row.get("state") != "active":
        raise ValueError("GitLab connection is missing or disabled")
    expires = row.get("expires_at")
    if expires and datetime.fromisoformat(
        str(expires).replace("Z", "+00:00")
    ) <= datetime.now(UTC):
        raise ValueError("GitLab connection has expired")
    payload = row.get("payload") or {}
    base = clean_url(str(payload.get("GITLAB_API_BASE_URL") or ""))
    if not base.endswith("/api/v4") or not payload.get("GITLAB_TOKEN"):
        raise ValueError("GitLab connection requires an API base URL and token")
    return {
        "api_url": base,
        "base_url": base[:-7],
        "token": payload["GITLAB_TOKEN"],
        "username": payload.get("GITLAB_USERNAME") or "oauth2",
        "version": row["version"],
        "repositories": allowed_repositories(payload),
    }


def check_destination(config: dict, connection: dict) -> None:
    # The pre-provisioned connection is the destination allowlist. Never follow
    # caller URLs or server redirects to another host with a service credential.
    expected = connection["base_url"] + "/" + config["project_path"]
    if (
        connection.get("repositories") is not None
        and config["project_path"] not in connection["repositories"]
    ):
        raise ValueError("repository is not allowed by the service connection")
    if (
        config["gitlab_web_url"] != expected
        or config["gitlab_clone_url"] != expected + ".git"
    ):
        raise ValueError(
            "repository URLs do not match the registered GitLab connection and project_path"
        )


async def _resolve(host: str, port: int) -> None:
    await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 10
    )


async def _get(client, url: str):
    response = await client.get(url)
    if response.status_code in {401, 403}:
        raise ProbeFailure("authentication", "upstream_authentication_denied")
    if 300 <= response.status_code < 400:
        raise ProbeFailure("network", "redirect_not_allowed")
    return response


class ProbeFailure(Exception):
    def __init__(self, check: str, code: str):
        self.check, self.code = check, code
        super().__init__(code)


async def validate_repository(config: dict) -> dict:
    checks = {
        key: {"status": "not_checked", "code": "dependency_not_ready"} for key in CHECKS
    }
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "checked_from": "gateway",
        "worker_environment_verified": False,
        "checks": checks,
        "connection_version": 0,
    }
    stage = "authentication"
    try:
        connection = connection_settings(config["gitlab_connection_id"])
        report["connection_version"] = connection["version"]
        check_destination(config, connection)
        parsed = urlsplit(connection["base_url"])
        stage = "dns"
        await _resolve(parsed.hostname, parsed.port or 443)
        checks[stage] = {"status": "pass", "code": "resolved"}
        stage = "network"
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            headers={"PRIVATE-TOKEN": connection["token"]},
        ) as client:
            user = await _get(client, connection["api_url"] + "/user")
            checks["network"] = {"status": "pass", "code": "reachable"}
            if user.status_code != 200:
                raise ProbeFailure("authentication", "identity_check_failed")
            checks["authentication"] = {"status": "pass", "code": "authenticated"}
            stage = "repository"
            project_url = (
                connection["api_url"]
                + "/projects/"
                + quote(config["project_path"], safe="")
            )
            response = await _get(client, project_url)
            if response.status_code != 200:
                raise ProbeFailure(stage, "repository_missing_or_inaccessible")
            project = response.json()
            if project.get("path_with_namespace") != config[
                "project_path"
            ] or project.get("archived"):
                raise ProbeFailure(stage, "repository_mismatch_or_archived")
            checks[stage] = {"status": "pass", "code": "repository_found"}
            report["gitlab_project_id"] = str(project["id"])
            stage = "branch"
            for branch in {config["default_base_branch"], config["mr_target_branch"]}:
                response = await _get(
                    client,
                    project_url + "/repository/branches/" + quote(branch, safe=""),
                )
                if response.status_code != 200:
                    raise ProbeFailure(stage, "required_branch_missing_or_inaccessible")
                if response.json().get("name") != branch:
                    raise ProbeFailure(stage, "branch_mismatch")
            checks[stage] = {"status": "pass", "code": "base_and_target_exist"}
        stage = "clone"
        await _probe_git(config, connection, checks)
    except ProbeFailure as exc:
        if exc.check == "authentication" and checks["dns"]["status"] == "pass":
            checks["network"] = {"status": "pass", "code": "reachable"}
        checks[exc.check] = {"status": "fail", "code": exc.code}
    except (socket.gaierror, asyncio.TimeoutError):
        checks[stage] = {
            "status": "fail",
            "code": "dns_failed" if stage == "dns" else "timeout",
        }
    except Exception:  # noqa: BLE001 - redact secret-bearing upstream failures
        # Upstream errors may contain request URLs, credentials or response bodies.
        checks[stage] = {
            "status": "fail",
            "code": "connection_unavailable"
            if stage == "authentication"
            else "probe_failed",
        }
    report["readiness_gaps"] = [
        key for key, check in checks.items() if check["status"] != "pass"
    ]
    report["ready"] = not report["readiness_gaps"]
    return report


def _git_env(connection: dict) -> dict[str, str]:
    allowed = {
        "path",
        "systemroot",
        "windir",
        "temp",
        "tmp",
        "home",
        "userprofile",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "ssl_cert_file",
        "ssl_cert_dir",
    }
    env = {key: value for key, value in os.environ.items() if key.casefold() in allowed}
    basic = base64.b64encode(
        f"{connection['username']}:{connection['token']}".encode()
    ).decode()
    settings = {
        "credential.helper": "",
        "http.followRedirects": "false",
        f"http.{connection['base_url']}/.extraHeader": "Authorization: Basic " + basic,
        "core.hooksPath": os.devnull,
        "protocol.file.allow": "never",
    }
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_COUNT=str(len(settings)),
        GCM_INTERACTIVE="Never",
    )
    for index, (key, value) in enumerate(settings.items()):
        env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = key, value
    return env


async def _git_status(*args: str, cwd: str, env: dict) -> int:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), 60)
        return process.returncode
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise


async def _git(*args: str, cwd: str, env: dict) -> bool:
    return await _git_status(*args, cwd=cwd, env=env) == 0


async def _cleanup_probe(ref: str, head: str, repo: str, env: dict) -> bool:
    cleaned = False
    try:
        cleaned = await _git(
            "push",
            "--porcelain",
            "-o",
            "ci.skip",
            f"--force-with-lease={ref}:{head}",
            "origin",
            f":{ref}",
            cwd=repo,
            env=env,
        )
        if not cleaned:
            cleaned = (
                await _git_status(
                    "ls-remote",
                    "--exit-code",
                    "--heads",
                    "origin",
                    ref,
                    cwd=repo,
                    env=env,
                )
                == 2
            )
        return cleaned
    finally:
        storage_factory.finish_probe(ref, cleaned)


async def _protected_cleanup(ref: str, head: str, repo: str, env: dict) -> bool:
    task = asyncio.create_task(
        asyncio.wait_for(_cleanup_probe(ref, head, repo, env), timeout=130)
    )
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        # Cleanup has finished (or left a durable recovery record) before the
        # temporary repository and its process-local auth environment disappear.
        raise asyncio.CancelledError
    return task.result()


async def _probe_git(config: dict, connection: dict, checks: dict) -> None:
    env = _git_env(connection)
    ref = "refs/heads/codex/readiness-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="factory-readiness-") as directory:
        repo = str(Path(directory) / "repo.git")
        cloned = await _git(
            "clone",
            "--bare",
            "--depth=1",
            "--filter=blob:none",
            "--single-branch",
            "--branch",
            config["default_base_branch"],
            "--no-tags",
            "--",
            config["gitlab_clone_url"],
            repo,
            cwd=directory,
            env=env,
        )
        if not cloned:
            raise ProbeFailure("clone", "git_clone_failed")
        checks["clone"] = {"status": "pass", "code": "shallow_clone_succeeded"}
        for pending in storage_factory.list_probes(config["project_id"]):
            if (
                pending["remote_url"] != config["gitlab_clone_url"]
                or not re.fullmatch(
                    r"refs/heads/codex/readiness-[0-9a-f]{32}", pending["ref"]
                )
                or not re.fullmatch(r"[0-9a-f]{40,64}", pending["head"])
            ):
                raise ProbeFailure(
                    "cleanup", "previous_probe_requires_operator_cleanup"
                )
            if not await _protected_cleanup(pending["ref"], pending["head"], repo, env):
                raise ProbeFailure("cleanup", "previous_probe_cleanup_failed")
        # Read the cloned HEAD locally; never run repository hooks or code.
        process = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "HEAD",
            cwd=repo,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 10)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        head = output.decode("ascii", errors="replace").strip()
        if not re.fullmatch(r"[a-f0-9]{40,64}", head):
            raise ProbeFailure("clone", "unexpected_shallow_head")
        storage_factory.reserve_probe(
            config["project_id"], config["gitlab_clone_url"], ref, head
        )
        attempted = False
        try:
            attempted = True
            pushed = await _git(
                "push",
                "--porcelain",
                "-o",
                "ci.skip",
                f"--force-with-lease={ref}:",
                "origin",
                f"{head}:{ref}",
                cwd=repo,
                env=env,
            )
            if not pushed:
                raise ProbeFailure("push_permissions", "temporary_branch_push_failed")
            checks["push_permissions"] = {
                "status": "pass",
                "code": "temporary_branch_pushed",
            }
        finally:
            # A timeout may occur after the server accepted the push. CAS deletion
            # is safe even then, and will never remove a branch changed by others.
            if attempted:
                try:
                    cleaned = await _protected_cleanup(ref, head, repo, env)
                except Exception:  # noqa: BLE001 - preserve durable cleanup failure
                    cleaned = False
                checks["cleanup"] = {
                    "status": "pass" if cleaned else "fail",
                    "code": "probe_removed" if cleaned else "probe_cleanup_unconfirmed",
                }
                if not cleaned:
                    checks["cleanup"]["probe_branch"] = ref.removeprefix("refs/heads/")
