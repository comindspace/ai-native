import unittest
from unittest.mock import AsyncMock, patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.backends.common import BackendRouteError
from gateway_mcp.backends.router import call_backend


class BackendRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_by_transport_and_applies_aliases(self) -> None:
        call = AsyncMock(return_value={"ok": True})
        with patch("gateway_mcp.backends.router._backend_callable", return_value=call) as backend_callable:
            result = await call_backend(
                {"transport": "yonote-rpc", "argument_aliases": {"id": "document_id"}},
                {"id": "doc-1"},
            )

        self.assertEqual(result, {"ok": True})
        backend_callable.assert_called_once_with("yonote-rpc")
        call.assert_awaited_once_with(
            {"transport": "yonote-rpc", "argument_aliases": {"id": "document_id"}},
            {"document_id": "doc-1"},
        )

    def test_router_import_does_not_load_backend_adapters(self) -> None:
        import importlib
        import sys

        for name in list(sys.modules):
            if (
                name.startswith("gateway_mcp.backends.")
                and name
                not in {
                    "gateway_mcp.backends.common",
                    "gateway_mcp.backends.router",
                }
            ):
                sys.modules.pop(name)

        import gateway_mcp.backends.router as router

        importlib.reload(router)

        loaded_adapters = {
            name
            for name in sys.modules
            if name.startswith("gateway_mcp.backends.")
            and name
            not in {
                "gateway_mcp.backends.common",
                "gateway_mcp.backends.router",
            }
        }
        self.assertEqual(loaded_adapters, set())

    async def test_unknown_transport_raises(self) -> None:
        with self.assertRaises(BackendRouteError):
            await call_backend({"transport": "unknown"}, {})
