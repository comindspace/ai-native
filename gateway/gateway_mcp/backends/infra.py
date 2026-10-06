import asyncio
import os
import shlex
from typing import Any

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError
from gateway_mcp.services.storage import get_infra_server, get_ssh_credential, list_infra_servers


DEFAULT_READONLY_ALLOWLIST = [
    "whoami",
    "hostname",
    "uptime",
    "sudo -n /usr/bin/docker ps",
    "sudo -n /usr/bin/docker logs",
    "sudo -n /usr/bin/docker inspect",
    "sudo -n /usr/bin/docker compose ps",
    "sudo -n /usr/bin/docker compose logs",
    "sudo -n /usr/bin/systemctl status",
    "sudo -n /usr/bin/journalctl",
    "sudo -n /usr/bin/df",
    "sudo -n /usr/bin/free",
    "sudo -n /usr/bin/ss",
    "sudo -n /usr/sbin/nginx -t",
    "sudo -n /usr/bin/certbot certificates",
    "sudo -n /usr/bin/du",
]


async def _call_infra(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation") or "")
    if operation == "servers.search":
        return await _servers_search(arguments)
    if operation == "servers.get":
        return await _servers_get(arguments)
    if operation == "ssh.exec":
        return await _ssh_exec(arguments)
    raise BackendRouteError(f"Unsupported infra operation: {operation or '<missing>'}")


async def _servers_search(arguments: dict[str, Any]) -> dict[str, Any]:
    servers = list_infra_servers(
        query=str(arguments.get("query") or ""),
        environment=str(arguments.get("environment") or ""),
        limit=int(arguments.get("limit") or 50),
    )
    return {"ok": True, "status": 200, "backend": "infra", "data": {"servers": servers, "count": len(servers)}}


async def _servers_get(arguments: dict[str, Any]) -> dict[str, Any]:
    server_id = str(arguments.get("server_id") or arguments.get("id") or "").strip()
    if not server_id:
        raise BackendRouteError("server_id is required")
    server = get_infra_server(server_id)
    if not server:
        return {"ok": False, "status": 404, "backend": "infra", "data": {"error": "server_not_found"}}
    return {"ok": True, "status": 200, "backend": "infra", "data": {"server": server}}


async def _ssh_exec(arguments: dict[str, Any]) -> dict[str, Any]:
    server_id = str(arguments.get("server_id") or "").strip()
    command = str(arguments.get("command") or "").strip()
    credential_handle = str(arguments.get("credential_handle") or "").strip()
    timeout = max(1, min(int(arguments.get("timeout_seconds") or 30), 120))

    if not server_id:
        raise BackendRouteError("server_id is required")
    if not command:
        raise BackendRouteError("command is required")
    if not credential_handle:
        raise BackendRouteError("credential_handle is required")

    credential = get_ssh_credential(credential_handle)
    if not credential:
        raise BackendConfigError("SSH credential handle is not configured")
    if credential.get("server_id") != server_id:
        raise PermissionError("SSH credential handle does not belong to requested server")

    allowlist = credential.get("allowlist") if isinstance(credential.get("allowlist"), list) else []
    if not _command_allowed(command, allowlist):
        raise PermissionError("SSH command is not in the read-only allowlist")

    host = str(credential.get("address") or credential.get("hostname") or "").strip()
    username = str(credential.get("username") or "").strip()
    private_key_path = str(credential.get("private_key_path") or "").strip()
    metadata = credential.get("metadata") if isinstance(credential.get("metadata"), dict) else {}
    ssh_port = int(arguments.get("port") or metadata.get("ssh_port") or metadata.get("port") or 22)
    if not host or not username or not private_key_path:
        raise BackendConfigError("SSH credential is incomplete")
    if not os.path.exists(private_key_path):
        raise BackendConfigError("SSH private key path does not exist on the GatewayMCP host")

    ssh_command = [
        "ssh",
        "-i",
        private_key_path,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(ssh_port),
        f"{username}@{host}",
        command,
    ]
    proc = await asyncio.create_subprocess_exec(
        *ssh_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "ok": False,
            "status": 124,
            "backend": "infra",
            "data": {"server_id": server_id, "command": command, "error": "timeout"},
        }

    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")
    return {
        "ok": proc.returncode == 0,
        "status": proc.returncode or 0,
        "backend": "infra",
        "data": {
            "server_id": server_id,
            "credential_handle": credential_handle,
            "command": command,
            "returncode": proc.returncode,
            "stdout": stdout[-20000:],
            "stderr": stderr[-20000:],
        },
    }


def _command_allowed(command: str, allowlist: list[str]) -> bool:
    normalized = " ".join(shlex.split(command))
    prefixes = [" ".join(shlex.split(item)) for item in (allowlist or DEFAULT_READONLY_ALLOWLIST) if str(item).strip()]
    return any(normalized == prefix or normalized.startswith(f"{prefix} ") for prefix in prefixes)
