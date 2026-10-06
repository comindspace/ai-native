import json
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def append_audit_event(payload: dict[str, Any]) -> bool:
    if not postgres_enabled():
        return False

    ensure_schema()
    raw_actor = payload.get("actor")
    actor: dict[str, Any] = raw_actor if isinstance(raw_actor, dict) else {}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into audit_events (
                    ts_ms,
                    event,
                    actor_subject,
                    tool,
                    system,
                    decision,
                    status,
                    scope,
                    payload
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    payload.get("ts_ms", 0),
                    payload.get("event", ""),
                    actor.get("subject", ""),
                    payload.get("tool", ""),
                    payload.get("system", ""),
                    payload.get("decision", ""),
                    payload.get("status", ""),
                    payload.get("scope", ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        conn.commit()
    return True


def list_audit_events(
    *,
    days: int = 7,
    actor_subject: str = "",
    event: str = "",
    tool: str = "",
    system: str = "",
    decision: str = "",
    status: str = "",
    gateway_request_id: str = "",
    limit: int = 100,
    offset: int = 0,
    include_payload: bool = True,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for audit event search")

    ensure_schema()
    where = ["created_at >= now() - (%s::text || ' days')::interval"]
    params: list[Any] = [max(1, min(int(days or 7), 365))]
    filters = {
        "actor_subject": actor_subject,
        "event": event,
        "tool": tool,
        "system": system,
        "decision": decision,
        "status": status,
    }
    for column, value in filters.items():
        clean = str(value or "").strip()
        if clean:
            where.append(f"{column} = %s")
            params.append(clean)

    clean_request_id = str(gateway_request_id or "").strip()
    if clean_request_id:
        where.append("payload #>> '{arguments,gateway_request_id}' = %s")
        params.append(clean_request_id)

    params.append(max(1, min(int(limit or 100), 500)))
    normalized_offset = max(0, min(int(offset or 0), 500_000))
    payload_column = ", payload" if include_payload else ""
    offset_clause = " offset %s" if normalized_offset else ""
    if normalized_offset:
        params.append(normalized_offset)
    sql = f"""
        select
            id,
            created_at,
            ts_ms,
            event,
            actor_subject,
            tool,
            system,
            decision,
            status,
            scope,
            payload #>> '{{arguments,gateway_request_id}}' as gateway_request_id
            {payload_column}
        from audit_events
        where {" and ".join(where)}
        order by created_at desc, id desc
        limit %s{offset_clause}
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_audit_row(row) for row in rows]


def audit_event_summary(
    *,
    days: int = 7,
    actor_subject: str = "",
    system: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for audit event summary")

    ensure_schema()
    where = ["created_at >= now() - (%s::text || ' days')::interval"]
    params: list[Any] = [max(1, min(int(days or 7), 365))]
    if actor_subject:
        where.append("actor_subject = %s")
        params.append(str(actor_subject).strip())
    if system:
        where.append("system = %s")
        params.append(str(system).strip())

    params.append(max(1, min(int(limit or 50), 200)))
    sql = f"""
        select
            event,
            tool,
            system,
            decision,
            status,
            count(*) as count,
            min(created_at) as first_seen_at,
            max(created_at) as last_seen_at
        from audit_events
        where {" and ".join(where)}
        group by event, tool, system, decision, status
        order by count(*) desc, max(created_at) desc
        limit %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_audit_row(row) for row in rows]


def gateway_activity_metrics(*, days: int = 30) -> dict[str, Any]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for gateway activity metrics")

    ensure_schema()
    period = max(1, min(int(days), 365))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    count(*) filter (where event = 'tool_call') as tool_calls,
                    count(*) filter (where event = 'tool_call' and status = 'error') as tool_errors,
                    count(*) filter (where event = 'tool_call' and status = 'denied') as tool_denials,
                    count(distinct actor_subject) filter (
                        where event = 'tool_call' and actor_subject <> ''
                    ) as active_actors,
                    count(*) filter (where event = 'login' and status = 'ok') as logins
                from audit_events
                where created_at >= now() - (%s::text || ' days')::interval
                """,
                (period,),
            )
            totals = cur.fetchone() or {}
            cur.execute(
                """
                select
                    tool,
                    system,
                    count(*) as calls,
                    count(*) filter (where status = 'error') as errors,
                    count(*) filter (where status = 'denied') as denials
                from audit_events
                where event = 'tool_call'
                  and created_at >= now() - (%s::text || ' days')::interval
                group by tool, system
                order by count(*) desc, tool
                limit 20
                """,
                (period,),
            )
            routes = cur.fetchall()
    return {"days": period, "totals": dict(totals), "routes": [dict(row) for row in routes]}


def _audit_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}

    result = dict(row)
    payload = result.get("payload")
    if isinstance(payload, str):
        try:
            result["payload"] = json.loads(payload)
        except json.JSONDecodeError:
            result["payload"] = {}
    for key, value in list(result.items()):
        formatter = getattr(value, "isoformat", None)
        if callable(formatter):
            result[key] = formatter()
    return result
