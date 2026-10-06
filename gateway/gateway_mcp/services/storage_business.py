from __future__ import annotations

from decimal import Decimal
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def project_link(project_id: str) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select tracker_project_id, crm_deal_id, contract_confirmed, confirmed_amount, confirmed_currency, updated_at "
            "from business_project_links where tracker_project_id = %s",
            (project_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_project_links() -> list[dict[str, Any]]:
    if not postgres_enabled():
        return []
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select tracker_project_id, crm_deal_id, contract_confirmed, confirmed_amount, confirmed_currency, updated_at "
            "from business_project_links order by tracker_project_id"
        )
        return [dict(row) for row in cur.fetchall()]


def save_project_link(
    *,
    project_id: str,
    deal_id: int,
    confirmed: bool,
    amount: Decimal | None,
    currency: str,
    actor_subject: str,
) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into business_project_links
               (tracker_project_id, crm_deal_id, contract_confirmed, confirmed_amount, confirmed_currency, updated_by)
               values (%s, %s, %s, %s, %s, %s)
               on conflict (tracker_project_id) do update set
                 crm_deal_id = excluded.crm_deal_id,
                 contract_confirmed = excluded.contract_confirmed,
                 confirmed_amount = excluded.confirmed_amount,
                 confirmed_currency = excluded.confirmed_currency,
                 updated_by = excluded.updated_by,
                 updated_at = now()""",
            (
                project_id,
                deal_id,
                confirmed,
                amount if confirmed else None,
                currency if confirmed else None,
                actor_subject,
            ),
        )


def delete_project_link(*, project_id: str) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from business_project_links where tracker_project_id = %s",
            (project_id,),
        )


def cost_rates() -> dict[str, dict[str, Any]]:
    if not postgres_enabled():
        return {}
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select tracker_user_id, hourly_rate_rub, basis from business_cost_rates"
        )
        return {str(row["tracker_user_id"]): dict(row) for row in cur.fetchall()}


def save_cost_rate(
    *, user_id: str, rate: Decimal, basis: str, actor_subject: str
) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into business_cost_rates
               (tracker_user_id, hourly_rate_rub, basis, updated_by)
               values (%s, %s, %s, %s)
               on conflict (tracker_user_id) do update set
                 hourly_rate_rub = excluded.hourly_rate_rub,
                 basis = excluded.basis,
                 updated_by = excluded.updated_by,
                 updated_at = now()""",
            (user_id, rate, basis, actor_subject),
        )


def delete_cost_rate(*, user_id: str) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from business_cost_rates where tracker_user_id = %s",
            (user_id,),
        )
