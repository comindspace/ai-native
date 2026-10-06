import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class BackendCommonTests(unittest.TestCase):
    def test_yandex_disk_token_prefers_disk_provider(self) -> None:
        from gateway_mcp.backends.common import _yandex_user_token
        from gateway_mcp.services.policy import GatewayActor

        def fake_token(provider, actor_subject):
            if provider == "yandex-disk":
                return {"access_token": "disk-token"}
            if provider == "yandex":
                return {"access_token": "core-token"}
            return None

        with (
            patch("gateway_mcp.services.auth.current_actor", return_value=GatewayActor(subject="service:agent")),
            patch("gateway_mcp.services.storage.get_user_oauth_token", side_effect=fake_token),
        ):
            self.assertEqual(_yandex_user_token("yandex-disk"), "disk-token")

    def test_yandex_disk_token_falls_back_to_core_provider(self) -> None:
        from gateway_mcp.backends.common import _yandex_user_token
        from gateway_mcp.services.policy import GatewayActor

        def fake_token(provider, actor_subject):
            if provider == "yandex":
                return {"access_token": "core-token"}
            return None

        with (
            patch("gateway_mcp.services.auth.current_actor", return_value=GatewayActor(subject="service:agent")),
            patch("gateway_mcp.services.storage.get_user_oauth_token", side_effect=fake_token),
        ):
            self.assertEqual(_yandex_user_token("yandex-disk"), "core-token")


if __name__ == "__main__":
    unittest.main()
