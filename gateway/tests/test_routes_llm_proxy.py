import asyncio
import json
import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()


class FakeMcp:
    def __init__(self) -> None:
        self.routes = {}

    def custom_route(self, path, methods, include_in_schema=False):
        def decorator(func):
            self.routes[path] = {"func": func, "methods": methods}
            return func

        return decorator


class FakeRequest:
    def __init__(self, payload, headers=None) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = {"content-length": str(len(self._body)), **(headers or {})}

    async def body(self) -> bytes:
        return self._body


class FakeUpstream:
    status_code = 200

    def __init__(self, payload) -> None:
        self._payload = payload

    def json(self):
        return self._payload


async def _consume(stream) -> bytes:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


class LlmProxyRouteTests(unittest.TestCase):
    def test_proxy_masks_upstream_and_restores_safe_response(self) -> None:
        from gateway_mcp.routes import llm_proxy

        fake = FakeMcp()
        llm_proxy.register_llm_proxy_routes(fake)
        captured = {}

        async def upstream(_path, payload):
            captured["payload"] = payload
            return FakeUpstream(
                {
                    "id": "chat-1",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": payload["messages"][0]["content"],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )

        request = FakeRequest(
            {
                "model": "test-model",
                "messages": [
                    {
                        "role": "user",
                        "content": "roman@example.com password=top-secret-value",
                    }
                ],
            }
        )
        with (
            patch.object(llm_proxy, "auth_enabled", return_value=False),
            patch.object(llm_proxy, "_upstream_post", side_effect=upstream),
            patch.object(llm_proxy, "integration_value", return_value=""),
            patch.object(llm_proxy, "audit_event"),
        ):
            response = asyncio.run(
                fake.routes["/privacy/v1/chat/completions"]["func"](request)
            )

        upstream_text = captured["payload"]["messages"][0]["content"]
        returned_text = response.body["choices"][0]["message"]["content"]
        self.assertNotIn("roman@example.com", upstream_text)
        self.assertNotIn("top-secret-value", upstream_text)
        self.assertIn("roman@example.com", returned_text)
        self.assertNotIn("top-secret-value", returned_text)

    def test_streaming_client_receives_sanitized_buffered_events(self) -> None:
        from gateway_mcp.routes import llm_proxy

        fake = FakeMcp()
        llm_proxy.register_llm_proxy_routes(fake)

        async def upstream(_path, payload):
            return FakeUpstream(
                {
                    "id": "chat-1",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": payload["messages"][0]["content"],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )

        request = FakeRequest(
            {
                "model": "test-model",
                "stream": True,
                "messages": [{"role": "user", "content": "roman@example.com"}],
            }
        )
        with (
            patch.object(llm_proxy, "auth_enabled", return_value=False),
            patch.object(llm_proxy, "_upstream_post", side_effect=upstream),
            patch.object(llm_proxy, "integration_value", return_value=""),
            patch.object(llm_proxy, "audit_event"),
        ):
            response = asyncio.run(
                fake.routes["/privacy/v1/chat/completions"]["func"](request)
            )
            body = asyncio.run(_consume(response.body)).decode("utf-8")

        self.assertIn("roman@example.com", body)
        self.assertIn("data: [DONE]", body)

    def test_proxy_requires_gateway_auth_when_enabled(self) -> None:
        from gateway_mcp.routes import llm_proxy

        fake = FakeMcp()
        llm_proxy.register_llm_proxy_routes(fake)
        request = FakeRequest({"model": "test", "messages": []})
        with patch.object(llm_proxy, "auth_enabled", return_value=True):
            response = asyncio.run(
                fake.routes["/privacy/v1/chat/completions"]["func"](request)
            )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
