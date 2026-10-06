import json
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled


def upsert_assistant_session(
    *,
    session_id: str,
    actor_subject: str,
    agent: str,
    client: str,
    project: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into assistant_sessions (
                    session_id,
                    actor_subject,
                    agent,
                    client,
                    project,
                    metadata
                )
                values (%s, %s, %s, %s, %s, %s::jsonb)
                on conflict (session_id) do update set
                    actor_subject = excluded.actor_subject,
                    agent = excluded.agent,
                    client = excluded.client,
                    project = excluded.project,
                    metadata = assistant_sessions.metadata || excluded.metadata,
                    updated_at = now()
                returning *
                """,
                (
                    session_id,
                    actor_subject,
                    agent,
                    client,
                    project,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row(row)


def insert_assistant_skill_event(
    *,
    event_type: str,
    correlation_id: str,
    session_id: str,
    actor_subject: str,
    agent: str,
    skill_id: str,
    skill_pack: str,
    skill_version: str,
    project: str,
    client: str,
    status: str,
    duration_ms: int | None,
    mcp_routes: list[str],
    missing_scopes: list[str],
    metadata: dict[str, Any],
    error_class: str,
) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into assistant_skill_events (
                    event_type,
                    correlation_id,
                    session_id,
                    actor_subject,
                    agent,
                    skill_id,
                    skill_pack,
                    skill_version,
                    project,
                    client,
                    status,
                    duration_ms,
                    mcp_routes,
                    missing_scopes,
                    metadata,
                    error_class
                )
                values (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s
                )
                on conflict (actor_subject, correlation_id, event_type) do nothing
                returning *, true as inserted
                """,
                (
                    event_type,
                    correlation_id,
                    session_id,
                    actor_subject,
                    agent,
                    skill_id,
                    skill_pack,
                    skill_version,
                    project,
                    client,
                    status,
                    duration_ms,
                    json.dumps(mcp_routes, ensure_ascii=False),
                    json.dumps(missing_scopes, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    error_class,
                ),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    select *, false as inserted
                    from assistant_skill_events
                    where actor_subject = %s
                      and correlation_id = %s
                      and event_type = %s
                    """,
                    (actor_subject, correlation_id, event_type),
                )
                row = cur.fetchone()
        conn.commit()
    return _row(row)


def open_assistant_skill_events(
    *,
    actor_subject: str,
    session_id: str,
    agent: str = "",
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        return []

    ensure_schema()
    where = [
        "started.actor_subject = %s",
        "started.session_id = %s",
        "started.event_type = 'started'",
        """not exists (
            select 1 from assistant_skill_events terminal
            where terminal.actor_subject = started.actor_subject
              and terminal.correlation_id = started.correlation_id
              and terminal.event_type in ('completed', 'failed')
        )""",
    ]
    params: list[Any] = [actor_subject, session_id]
    if agent:
        where.insert(2, "started.agent = %s")
        params.append(agent)

    sql = f"""
        select
            started.*,
            greatest(
                0,
                (extract(epoch from (now() - started.created_at)) * 1000)::bigint
            ) as elapsed_ms
        from assistant_skill_events started
        where {' and '.join(where)}
        order by started.created_at asc
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def assistant_skill_stats(
    *,
    days: int,
    limit: int,
    agent: str = "",
    skill_id: str = "",
    skill_pack: str = "",
    skill_version: str = "",
    project: str = "",
    actor_subject: str = "",
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for assistant telemetry stats")

    ensure_schema()
    where = ["started.created_at >= now() - (%s::text || ' days')::interval"]
    params: list[Any] = [max(1, min(int(days or 30), 365))]
    if agent:
        where.append("started.agent = %s")
        params.append(agent)
    if skill_id:
        where.append("started.skill_id = %s")
        params.append(skill_id)
    if skill_pack:
        where.append("started.skill_pack = %s")
        params.append(skill_pack)
    if skill_version:
        where.append("started.skill_version = %s")
        params.append(skill_version)
    if project:
        where.append("started.project = %s")
        params.append(project)
    if actor_subject:
        where.append("started.actor_subject = %s")
        params.append(actor_subject)

    params.append(max(1, min(int(limit or 25), 250)))
    sql = f"""
        with starts as (
            select distinct on (actor_subject, correlation_id)
                actor_subject,
                correlation_id,
                session_id,
                agent,
                skill_id,
                skill_pack,
                skill_version,
                project,
                client,
                created_at as started_at
            from assistant_skill_events started
            where event_type = 'started'
              and {' and '.join(where)}
            order by actor_subject, correlation_id, created_at desc
        ),
        outcomes as (
            select distinct on (actor_subject, correlation_id)
                actor_subject,
                correlation_id,
                event_type,
                duration_ms,
                created_at as finished_at
            from assistant_skill_events
            where event_type in ('completed', 'failed')
            order by actor_subject, correlation_id, created_at desc
        )
        select
            starts.skill_id,
            starts.skill_pack,
            starts.skill_version,
            starts.agent,
            starts.project,
            count(*) as started_count,
            count(*) filter (where outcomes.event_type = 'completed') as completed_count,
            count(*) filter (where outcomes.event_type = 'failed') as failed_count,
            count(*) filter (
                where outcomes.event_type is null
                  and starts.started_at < now() - interval '30 minutes'
            ) as abandoned_count,
            count(*) filter (
                where outcomes.event_type is null
                  and starts.started_at >= now() - interval '30 minutes'
            ) as running_count,
            count(distinct starts.actor_subject) as active_users,
            case
                when count(*) filter (where outcomes.event_type in ('completed', 'failed')) = 0 then null
                else round(
                    100.0 * count(*) filter (where outcomes.event_type = 'completed')
                    / count(*) filter (where outcomes.event_type in ('completed', 'failed')),
                    1
                )
            end as success_rate,
            percentile_cont(0.5) within group (
                order by coalesce(
                    outcomes.duration_ms,
                    (extract(epoch from (outcomes.finished_at - starts.started_at)) * 1000)::bigint
                )
            ) filter (where outcomes.event_type is not null) as p50_duration_ms,
            percentile_cont(0.95) within group (
                order by coalesce(
                    outcomes.duration_ms,
                    (extract(epoch from (outcomes.finished_at - starts.started_at)) * 1000)::bigint
                )
            ) filter (where outcomes.event_type is not null) as p95_duration_ms,
            max(starts.started_at) as last_seen_at
        from starts
        left join outcomes
          on outcomes.actor_subject = starts.actor_subject
         and outcomes.correlation_id = starts.correlation_id
        group by
            starts.skill_id,
            starts.skill_pack,
            starts.skill_version,
            starts.agent,
            starts.project
        order by count(*) desc, max(starts.started_at) desc
        limit %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def insert_assistant_usage_event(
    *,
    event_name: str,
    source: str,
    source_quality: str,
    actor_subject: str,
    agent: str,
    provider: str,
    model: str,
    session_id: str,
    correlation_id: str,
    skill_id: str,
    skill_pack: str,
    project: str,
    client: str,
    cwd: str,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    cache_creation_input_tokens: int | None,
    cache_read_input_tokens: int | None,
    reasoning_tokens: int | None,
    duration_ms: int | None,
    tool_use_count: int | None,
    usage_class: str,
    estimated_cost_usd: float | None,
    metadata: dict[str, Any],
    raw_event: dict[str, Any],
) -> dict[str, Any] | None:
    if not postgres_enabled():
        return None

    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into assistant_usage_events (
                    event_name,
                    source,
                    source_quality,
                    actor_subject,
                    agent,
                    provider,
                    model,
                    session_id,
                    correlation_id,
                    skill_id,
                    skill_pack,
                    project,
                    client,
                    cwd,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    reasoning_tokens,
                    duration_ms,
                    tool_use_count,
                    usage_class,
                    estimated_cost_usd,
                    metadata,
                    raw_event
                )
                values (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
                )
                returning *
                """,
                (
                    event_name,
                    source,
                    source_quality,
                    actor_subject,
                    agent,
                    provider,
                    model,
                    session_id,
                    correlation_id,
                    skill_id,
                    skill_pack,
                    project,
                    client,
                    cwd,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    reasoning_tokens,
                    duration_ms,
                    tool_use_count,
                    usage_class,
                    estimated_cost_usd,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(raw_event, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row(row)


def assistant_usage_summary(
    *,
    days: int,
    limit: int,
    agent: str = "",
    skill_id: str = "",
    project: str = "",
    source_quality: str = "",
) -> list[dict[str, Any]]:
    if not postgres_enabled():
        raise RuntimeError("GATEWAY_DATABASE_URL is required for assistant usage summary")

    ensure_schema()
    where = ["created_at >= now() - (%s::text || ' days')::interval"]
    params: list[Any] = [max(1, min(int(days or 30), 365))]
    if agent:
        where.append("agent = %s")
        params.append(agent)
    if skill_id:
        where.append("skill_id = %s")
        params.append(skill_id)
    if project:
        where.append("project = %s")
        params.append(project)
    if source_quality:
        where.append("source_quality = %s")
        params.append(source_quality)

    params.append(max(1, min(int(limit or 25), 200)))
    sql = f"""
        select
            agent,
            provider,
            model,
            skill_id,
            skill_pack,
            project,
            source_quality,
            usage_class,
            count(*) as event_count,
            count(distinct actor_subject) as active_users,
            sum(coalesce(input_tokens, 0)) as input_tokens,
            sum(coalesce(output_tokens, 0)) as output_tokens,
            sum(coalesce(total_tokens, 0)) as total_tokens,
            sum(coalesce(cache_creation_input_tokens, 0)) as cache_creation_input_tokens,
            sum(coalesce(cache_read_input_tokens, 0)) as cache_read_input_tokens,
            sum(coalesce(reasoning_tokens, 0)) as reasoning_tokens,
            sum(coalesce(estimated_cost_usd, 0)) as estimated_cost_usd,
            max(created_at) as last_seen_at
        from assistant_usage_events
        where {' and '.join(where)}
        group by agent, provider, model, skill_id, skill_pack, project, source_quality, usage_class
        order by sum(coalesce(total_tokens, 0)) desc, count(*) desc, max(created_at) desc
        limit %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row(row) for row in rows]


def _row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}

    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    for key in ("p50_duration_ms", "p95_duration_ms", "success_rate"):
        if result.get(key) is not None:
            result[key] = float(result[key])
    if result.get("estimated_cost_usd") is not None:
        result["estimated_cost_usd"] = float(result["estimated_cost_usd"])
    return result
