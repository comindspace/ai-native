import os
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

from gateway_mcp.services.migrations import check_current


_SCHEMA_READY = False

def database_url() -> str:
    return os.getenv("GATEWAY_DATABASE_URL", "")


def postgres_enabled() -> bool:
    return bool(database_url())


def _connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), row_factory=dict_row)


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY or not postgres_enabled():
        return

    status = check_current()
    if not status.get("ok"):
        pending = ", ".join(status.get("pending") or [])
        detail = f" Pending migrations: {pending}." if pending else ""
        raise RuntimeError(f"GatewayMCP database schema is not migrated.{detail} Run `gateway-mcp migrate up`.")
    _SCHEMA_READY = True


def health() -> dict[str, Any]:
    if not postgres_enabled():
        return {"enabled": False}

    started_at = time.perf_counter()
    try:
        ensure_schema()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1 as ok")
                row = cur.fetchone()
        return {
            "enabled": True,
            "ok": bool(row and row["ok"] == 1),
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    except Exception as exc:
        return {
            "enabled": True,
            "ok": False,
            "error": exc.__class__.__name__,
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
