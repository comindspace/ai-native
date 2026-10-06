"""Serialize administrator assignment by recipient across Gateway workers."""

from contextlib import contextmanager

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


@contextmanager
def admin_role_assignment_lock(subject: str):
    if not postgres_enabled():
        raise RuntimeError("administrator assignment requires GatewayMCP Postgres")
    ensure_schema()
    # Keep this transaction open around the existing grant service. Its writes
    # commit before this lock is released, so the next caller sees the live role.
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("gateway-admin-role:" + subject.strip().casefold(),),
            )
        yield
