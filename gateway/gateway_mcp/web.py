from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from gateway_mcp.services.auth import (
    auth_enabled,
    current_actor,
    token_ttl_seconds,
    verify_gateway_token_claims,
)
from gateway_mcp.services.policy import GatewayActor, actor_from_claims
from gateway_mcp.config import public_url


def web_actor(request: Request) -> GatewayActor | None:
    if not auth_enabled():
        return current_actor()

    authorization = request.headers.get("authorization", "")
    token = ""
    if authorization.casefold().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get("gateway_token", "")
    if not token:
        return None
    try:
        return actor_from_claims(verify_gateway_token_claims(token))
    except Exception:
        return None


def with_gateway_cookie(response: Response, token: str) -> Response:
    response.set_cookie(
        "gateway_token",
        token,
        max_age=token_ttl_seconds(),
        httponly=True,
        secure=public_url().startswith("https://"),
        samesite="lax",
        path="/",
    )
    return response


def clear_gateway_cookie(response: Response) -> Response:
    response.delete_cookie(
        "gateway_token",
        path="/",
        secure=public_url().startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    return response


def login_redirect(next_url: str = "/credentials") -> RedirectResponse:
    return RedirectResponse(f"/auth/yandex/login?next={quote(next_url, safe='/?:=&')}", status_code=303)
