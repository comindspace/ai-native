import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from gateway_mcp.config import root


def database_url() -> str:
    return os.getenv("GATEWAY_DATABASE_URL", "")


def migrations_dir() -> Path:
    raw = os.getenv("GATEWAY_MIGRATIONS_DIR", "migrations")
    path = Path(raw)
    if path.is_absolute():
        return path
    module_relative = (root() / path).resolve()
    if module_relative.exists():
        return module_relative
    return (Path(sys.prefix) / path).resolve()


def migration_files() -> list[Path]:
    root = migrations_dir()
    if not root.exists():
        raise RuntimeError(f"GatewayMCP migrations directory not found: {root}")
    return sorted(path for path in root.glob("*.sql") if path.is_file())


def latest_migration_id() -> str:
    files = migration_files()
    return files[-1].stem if files else ""


def connect() -> psycopg.Connection:
    if not database_url():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for GatewayMCP migrations")
    return psycopg.connect(database_url(), row_factory=dict_row)


def ensure_migration_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
                version text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
    conn.commit()


def applied_versions(conn: psycopg.Connection, *, create_table: bool = False) -> set[str]:
    if create_table:
        ensure_migration_table(conn)
    with conn.cursor() as cur:
        try:
            cur.execute("select version from schema_migrations")
            rows = cur.fetchall()
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            return set()
    return {str(row["version"]) for row in rows}


def migration_status() -> dict[str, Any]:
    files = migration_files()
    if not database_url():
        return {
            "database_enabled": False,
            "latest": files[-1].stem if files else "",
            "applied": [],
            "pending": [path.stem for path in files],
        }
    with connect() as conn:
        applied = applied_versions(conn)
    pending = [path.stem for path in files if path.stem not in applied]
    return {
        "database_enabled": True,
        "latest": files[-1].stem if files else "",
        "applied": sorted(applied),
        "pending": pending,
    }


def migrate_up() -> dict[str, Any]:
    files = migration_files()
    applied_now: list[str] = []
    with connect() as conn:
        applied = applied_versions(conn, create_table=True)
        for path in files:
            version = path.stem
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute("insert into schema_migrations (version) values (%s)", (version,))
            applied_now.append(version)
    return {
        "ok": True,
        "applied": applied_now,
        "status": migration_status(),
    }


def check_current() -> dict[str, Any]:
    status = migration_status()
    pending = status.get("pending", [])
    return {
        **status,
        "ok": bool(status.get("database_enabled")) and not pending,
    }
