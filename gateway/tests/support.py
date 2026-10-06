import sys
import types


def install_dependency_stubs() -> None:
    if "cryptography.fernet" not in sys.modules:
        cryptography = types.ModuleType("cryptography")
        fernet_module = types.ModuleType("cryptography.fernet")

        class Fernet:
            def __init__(self, key: bytes | str) -> None:
                self.key = key

            def encrypt(self, value: bytes) -> bytes:
                return value

            def decrypt(self, value: bytes) -> bytes:
                return value

        fernet_module.Fernet = Fernet
        sys.modules.setdefault("cryptography", cryptography)
        sys.modules["cryptography.fernet"] = fernet_module

    if "psycopg" not in sys.modules:
        psycopg = types.ModuleType("psycopg")

        class UndefinedTable(Exception):
            pass

        psycopg.errors = types.SimpleNamespace(UndefinedTable=UndefinedTable)
        psycopg.Connection = object
        psycopg.connect = lambda *args, **kwargs: None
        rows = types.ModuleType("psycopg.rows")
        rows.dict_row = object()
        sys.modules["psycopg"] = psycopg
        sys.modules["psycopg.rows"] = rows

    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")

        class Response:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {}

        class AsyncClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                return None

        httpx.Response = Response
        httpx.AsyncClient = AsyncClient
        sys.modules["httpx"] = httpx

    if "jwt" not in sys.modules:
        jwt = types.ModuleType("jwt")
        jwt.encode = lambda payload, key, algorithm="HS256": "test.jwt.token"
        jwt.decode = lambda token, key, algorithms=None, options=None: {}
        sys.modules["jwt"] = jwt

    if "pydantic" not in sys.modules:
        pydantic = types.ModuleType("pydantic")
        pydantic.Field = lambda *args, **kwargs: kwargs
        sys.modules["pydantic"] = pydantic

    if "mcp.server.auth.settings" not in sys.modules:
        mcp = types.ModuleType("mcp")
        server = types.ModuleType("mcp.server")
        auth = types.ModuleType("mcp.server.auth")
        middleware = types.ModuleType("mcp.server.auth.middleware")
        auth_context = types.ModuleType("mcp.server.auth.middleware.auth_context")
        provider = types.ModuleType("mcp.server.auth.provider")
        settings = types.ModuleType("mcp.server.auth.settings")
        fastmcp = types.ModuleType("mcp.server.fastmcp")
        mcp_types = types.ModuleType("mcp.types")

        auth_context.get_access_token = lambda: None

        class AccessToken:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        class AuthSettings:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        class FastMCP:
            pass

        class ToolAnnotations:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        provider.AccessToken = AccessToken
        settings.AuthSettings = AuthSettings
        fastmcp.FastMCP = FastMCP
        mcp_types.ToolAnnotations = ToolAnnotations
        sys.modules.setdefault("mcp", mcp)
        sys.modules.setdefault("mcp.server", server)
        sys.modules.setdefault("mcp.server.auth", auth)
        sys.modules.setdefault("mcp.server.auth.middleware", middleware)
        sys.modules["mcp.server.auth.middleware.auth_context"] = auth_context
        sys.modules["mcp.server.auth.provider"] = provider
        sys.modules["mcp.server.auth.settings"] = settings
        sys.modules["mcp.server.fastmcp"] = fastmcp
        sys.modules["mcp.types"] = mcp_types

    if "prometheus_client" not in sys.modules:
        prometheus = types.ModuleType("prometheus_client")

        class Metric:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def labels(self, **kwargs):
                return self

            def inc(self, *args, **kwargs) -> None:
                return None

            def observe(self, *args, **kwargs) -> None:
                return None

            def set(self, *args, **kwargs) -> None:
                return None

        prometheus.Counter = Metric
        prometheus.Gauge = Metric
        prometheus.Histogram = Metric
        prometheus.generate_latest = lambda: b""
        prometheus.CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
        sys.modules["prometheus_client"] = prometheus

    if "starlette.responses" not in sys.modules:
        starlette = types.ModuleType("starlette")
        requests = types.ModuleType("starlette.requests")
        responses = types.ModuleType("starlette.responses")

        class Request:
            pass

        class Response:
            def __init__(
                self,
                content=None,
                media_type: str | None = None,
                status_code: int = 200,
                headers=None,
            ) -> None:
                self.body = content
                self.media_type = media_type
                self.status_code = status_code
                self.headers = headers or {}
                self.deleted_cookies = []

            def delete_cookie(self, key: str, path: str = "/", **kwargs) -> None:
                self.deleted_cookies.append({"key": key, "path": path, **kwargs})

        class JSONResponse(Response):
            pass

        class PlainTextResponse(Response):
            pass

        class RedirectResponse(Response):
            def __init__(self, url: str, status_code: int = 307, headers=None) -> None:
                super().__init__(
                    None,
                    status_code=status_code,
                    headers={"location": url, **(headers or {})},
                )
                self.url = url

        class HTMLResponse(Response):
            pass

        class StreamingResponse(Response):
            def __init__(
                self, content=None, media_type=None, status_code=200, headers=None
            ) -> None:
                super().__init__(
                    content,
                    media_type=media_type,
                    status_code=status_code,
                    headers=headers,
                )

        requests.Request = Request
        responses.Response = Response
        responses.JSONResponse = JSONResponse
        responses.PlainTextResponse = PlainTextResponse
        responses.RedirectResponse = RedirectResponse
        responses.HTMLResponse = HTMLResponse
        responses.StreamingResponse = StreamingResponse
        sys.modules.setdefault("starlette", starlette)
        sys.modules["starlette.requests"] = requests
        sys.modules["starlette.responses"] = responses

    if "telethon" not in sys.modules:
        telethon = types.ModuleType("telethon")

        class TelegramClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

        telethon.TelegramClient = TelegramClient
        sys.modules["telethon"] = telethon

        sessions = types.ModuleType("telethon.sessions")

        class StringSession:
            def __init__(self, *args, **kwargs) -> None:
                pass

        sessions.StringSession = StringSession
        sys.modules["telethon.sessions"] = sessions
