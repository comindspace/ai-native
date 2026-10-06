import os

from prometheus_client import CONTENT_TYPE_LATEST
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway_mcp.services.auth import auth_enabled
from gateway_mcp.services.observability import metrics_response
from gateway_mcp.services.storage import health as storage_health


def register_health_routes(mcp):
    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_: Request) -> Response:
        db = storage_health()
        ok = not db.get("enabled") or bool(db.get("ok"))
        return JSONResponse(
            {
                "ok": ok,
                "service": "gateway-mcp",
                "release_sha": os.getenv("GATEWAY_RELEASE_SHA", "dev"),
                "auth_enabled": auth_enabled(),
                "postgres": db,
            },
            status_code=200 if ok else 503,
        )

    @mcp.custom_route("/metrics", methods=["GET"], include_in_schema=False)
    async def metrics(_: Request) -> Response:
        return Response(metrics_response(), media_type=CONTENT_TYPE_LATEST)
