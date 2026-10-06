import unittest
from unittest.mock import AsyncMock, Mock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.infra import _call_infra, _command_allowed
from gateway_mcp.backends.router import call_backend


class InfraBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_dispatches_infra_transport(self) -> None:
        with patch("gateway_mcp.backends.infra.list_infra_servers", return_value=[]):
            result = await call_backend(
                {"transport": "infra", "operation": "servers.search"},
                {"query": "prod"},
            )

        self.assertEqual(result["ok"], True)
        self.assertEqual(result["backend"], "infra")

    async def test_server_get_does_not_return_credentials(self) -> None:
        with patch(
            "gateway_mcp.backends.infra.get_infra_server",
            return_value={"id": "app-prod-01", "address": "203.0.113.10"},
        ):
            result = await _call_infra(
                {"operation": "servers.get"},
                {"server_id": "app-prod-01"},
            )

        self.assertEqual(result["ok"], True)
        self.assertNotIn("private_key", str(result))
        self.assertEqual(result["data"]["server"]["id"], "app-prod-01")

    async def test_ssh_exec_blocks_command_outside_allowlist(self) -> None:
        with patch(
            "gateway_mcp.backends.infra.get_ssh_credential",
            return_value={
                "server_id": "app-prod-01",
                "username": "ops-agent",
                "address": "127.0.0.1",
                "private_key_path": "/tmp/key",
                "allowlist": ["sudo -n /usr/bin/docker ps"],
            },
        ):
            with self.assertRaises(PermissionError):
                await _call_infra(
                    {"operation": "ssh.exec"},
                    {
                        "server_id": "app-prod-01",
                        "credential_handle": "ssh_key_ai_native_prod_01_ops_agent",
                        "command": "sudo -n systemctl restart nginx",
                    },
                )

    async def test_ssh_exec_runs_allowlisted_command(self) -> None:
        proc = Mock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok\n", b""))

        with patch(
            "gateway_mcp.backends.infra.get_ssh_credential",
            return_value={
                "server_id": "app-prod-01",
                "username": "ops-agent",
                "address": "127.0.0.1",
                "private_key_path": "/tmp/key",
                "allowlist": ["hostname"],
                "metadata": {"ssh_port": 41535},
            },
        ), patch("gateway_mcp.backends.infra.os.path.exists", return_value=True), patch(
            "gateway_mcp.backends.infra.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ) as create:
            result = await _call_infra(
                {"operation": "ssh.exec"},
                {
                    "server_id": "app-prod-01",
                    "credential_handle": "ssh_key_ai_native_prod_01_ops_agent",
                    "command": "hostname",
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stdout"], "ok\n")
        self.assertNotIn("/tmp/key", str(result))
        create.assert_awaited()
        self.assertIn("41535", create.await_args.args)

    def test_command_allowlist_normalizes_spacing(self) -> None:
        self.assertTrue(_command_allowed("sudo   -n /usr/bin/docker ps --format x", ["sudo -n /usr/bin/docker ps"]))
        self.assertFalse(_command_allowed("sudo -n /usr/bin/docker rm container", ["sudo -n /usr/bin/docker ps"]))
