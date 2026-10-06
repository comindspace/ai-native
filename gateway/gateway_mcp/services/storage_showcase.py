"""Aggregate projections only: no prompts, event payloads, credentials or HR data."""

from gateway_mcp.services.storage_admin_console import _USERS, _rows
from gateway_mcp.services.storage_core import _connect, ensure_schema


def _runs(days, subject=None, agent=None, people_only=False):
    where = [
        "s.event_type = 'started'",
        "s.created_at >= now() - (%s * interval '1 day')",
        "s.created_at <= now()",
    ]
    params = [days]
    if subject is not None:
        where.append("s.actor_subject = %s")
        params.append(subject)
    if agent is not None:
        where.append("s.agent = %s")
        params.append(agent)
    if people_only:
        where.append(
            "not exists (select 1 from assistant_agent_profiles p where p.actor_subject <> '' and p.actor_subject = s.actor_subject and p.agent = s.agent)"
        )
    return (
        """with runs as (
        select s.actor_subject, s.agent, s.skill_pack, s.skill_id,
            s.created_at, o.event_type as outcome, o.duration_ms
        from assistant_skill_events s
        left join lateral (
            select event_type, duration_ms from assistant_skill_events e
            where e.actor_subject = s.actor_subject and e.correlation_id = s.correlation_id
                and e.event_type in ('completed', 'failed')
                and e.created_at >= s.created_at and e.created_at <= now()
            order by e.created_at desc, e.id desc limit 1
        ) o on true where """
        + " and ".join(where)
        + ")",
        tuple(params),
    )


_COUNTS = """
    count(*) as starts,
    count(*) filter (where outcome = 'completed') as completed,
    count(*) filter (where outcome = 'failed') as failed,
    count(*) filter (where outcome is null) as pending,
    count(duration_ms) filter (where outcome is not null and duration_ms >= 0) as timed,
    percentile_cont(0.5) within group (order by duration_ms)
        filter (where outcome is not null and duration_ms >= 0) as median_ms,
    max(created_at) as last_activity
"""


def showcase_snapshot(days=30, *, subject=None, agent=None, people_only=False):
    cte, params = _runs(days, subject, agent, people_only)
    return _rows(
        cte
        + f""",
        totals as (select {_COUNTS}, count(distinct actor_subject) as actors,
            count(distinct (skill_pack, skill_id)) as skills from runs),
        clients as (select agent, {_COUNTS} from runs group by agent),
        skills as (select skill_pack, skill_id, {_COUNTS} from runs
            group by skill_pack, skill_id order by starts desc, skill_pack, skill_id limit 12),
        daily as (select (created_at at time zone 'Europe/Moscow')::date as day,
            count(*) as starts, count(*) filter (where outcome = 'failed') as failed
            from runs group by 1 order by 1)
        select (select row_to_json(t) from totals t) as totals,
            coalesce((select jsonb_agg(c order by starts desc, agent) from clients c), '[]') as clients,
            coalesce((select jsonb_agg(s order by starts desc, skill_pack, skill_id) from skills s), '[]') as skills,
            coalesce((select jsonb_agg(d order by day) from daily d), '[]') as daily,
            (now() at time zone 'Europe/Moscow')::date as today
    """,
        params,
    )[0]


def showcase_people(days=30, query="", offset=0, limit=12):
    cte, params = _runs(days, people_only=True)
    # The registry of known people, not the telemetry top-N, defines the directory.
    sql = (
        cte
        + ", "
        + _USERS.strip().removeprefix("with ")
        + f""",
        totals as (select actor_subject, {_COUNTS} from runs group by actor_subject),
        clients as (select actor_subject, array_agg(distinct agent order by agent) as clients
            from runs group by actor_subject),
        ranked as (select actor_subject, skill_pack, skill_id, count(*) as starts,
            row_number() over (partition by actor_subject order by count(*) desc, skill_pack, skill_id) as rank
            from runs group by actor_subject, skill_pack, skill_id),
        favorites as (select actor_subject, jsonb_agg(jsonb_build_object('skill_pack', skill_pack, 'skill_id', skill_id)
            order by created_at, skill_pack, skill_id) as favorites
            from assistant_skill_favorites group by actor_subject),
        people as (select u.subject, u.login, u.email,
            coalesce(t.starts, 0) as starts, coalesce(t.completed, 0) as completed,
            coalesce(t.failed, 0) as failed, coalesce(t.pending, 0) as pending,
            t.last_activity, coalesce(c.clients, '{{}}') as clients,
            coalesce(f.favorites, '[]') as favorites,
            coalesce((select jsonb_agg(jsonb_build_object('skill_pack', skill_pack, 'skill_id', skill_id, 'starts', starts)
                order by starts desc, skill_pack, skill_id) from ranked r
                where r.actor_subject = u.subject and rank <= 3), '[]') as skills
            from known_users u left join totals t on t.actor_subject = u.subject
            left join clients c on c.actor_subject = u.subject
            left join favorites f on f.actor_subject = u.subject),
        matched as (select * from people
            where strpos(lower(login || ' ' || email || ' ' || subject), lower(%s)) > 0)
        select (select count(*) from people) as registered,
            (select count(*) from people where starts > 0) as active,
            (select count(*) from matched) as matched,
            (select count(distinct actor_subject) from runs where actor_subject not in (select subject from known_users)) as unlinked,
            coalesce((select jsonb_agg(p) from (select * from matched order by starts desc, lower(login), subject limit %s offset %s) p), '[]') as people
    """
    )
    return _rows(sql, params + (query, limit, offset))[0]


def showcase_usage(days, subject, agent=None, people_only=True):
    where = [
        "u.actor_subject = %s",
        "u.created_at >= now() - (%s * interval '1 day')",
        "u.created_at <= now()",
    ]
    params = [subject, days]
    if agent is not None:
        where.append("u.agent = %s")
        params.append(agent)
    if people_only:
        where.append(
            "not exists (select 1 from assistant_agent_profiles p where p.actor_subject <> '' and p.actor_subject = u.actor_subject and p.agent = u.agent)"
        )
    return _rows(
        """select source_quality, source, usage_class, count(*) as records,
        count(total_tokens) as token_records, sum(total_tokens) as tokens,
        count(estimated_cost_usd) as cost_records, sum(estimated_cost_usd) as cost_usd
        from assistant_usage_events u where """
        + " and ".join(where)
        + " group by source_quality, source, usage_class order by source_quality, source, usage_class",
        tuple(params),
    )


def skill_favorites(subject, days=30):
    cte, params = _runs(days, subject=subject, people_only=True)
    return _rows(
        cte
        + """ select f.skill_pack, f.skill_id,
        (select count(*) from runs r where r.skill_pack = f.skill_pack and r.skill_id = f.skill_id) as starts
        from assistant_skill_favorites f where actor_subject = %s
        order by f.created_at, f.skill_pack, f.skill_id""",
        params + (subject,),
    )


def set_skill_favorite(subject, pack, skill, selected):
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        if selected:
            cur.execute(
                """insert into assistant_skill_favorites (actor_subject, skill_pack, skill_id)
                select %s, %s, %s where exists (select 1 from assistant_skill_events
                where actor_subject = %s and skill_pack = %s and skill_id = %s and event_type = 'started')
                on conflict do nothing""",
                (subject, pack, skill, subject, pack, skill),
            )
        else:
            cur.execute(
                """delete from assistant_skill_favorites
                where actor_subject = %s and skill_pack = %s and skill_id = %s""",
                (subject, pack, skill),
            )


def agent_profiles(days=30):
    cte, params = _runs(days)
    return _rows(
        cte
        + f""", activity as (
        select actor_subject, agent, {_COUNTS} from runs group by actor_subject, agent)
        select p.agent_key, p.display_name, p.description, p.actor_subject, p.agent, p.revision,
            a.starts, a.completed, a.failed, a.pending, a.timed, a.median_ms, a.last_activity
        from assistant_agent_profiles p left join activity a
            on p.actor_subject = a.actor_subject and p.agent = a.agent and p.actor_subject <> ''
        order by p.display_name, p.agent_key""",
        params,
    )


def agent_binding_options():
    return _rows("""select actor_subject, agent, max(created_at) as last_activity
        from assistant_skill_events where event_type = 'started' and actor_subject <> '' and agent <> ''
        group by actor_subject, agent order by last_activity desc, actor_subject, agent limit 100""")


def save_agent_profile(*, key, name, description, subject, agent, revision, updated_by):
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        if subject:
            cur.execute(
                """select 1 from assistant_skill_events
                where actor_subject = %s and agent = %s and event_type = 'started' limit 1""",
                (subject, agent),
            )
            if cur.fetchone() is None:
                raise ValueError("unknown telemetry binding")
        # Unique binding and optimistic revision prevent ambiguous/lost assignments.
        cur.execute(
            """insert into assistant_agent_profiles
            (agent_key, display_name, description, actor_subject, agent, updated_by)
            select %s, %s, %s, %s, %s, %s where %s = 0
            on conflict do nothing returning agent_key""",
            (key, name, description, subject, agent, updated_by, revision),
        )
        if cur.fetchone() is not None:
            return
        cur.execute(
            """update assistant_agent_profiles set display_name = %s, description = %s,
            actor_subject = %s, agent = %s, revision = revision + 1, updated_by = %s, updated_at = now()
            where agent_key = %s and revision = %s returning agent_key""",
            (name, description, subject, agent, updated_by, key, revision),
        )
        if cur.fetchone() is None:
            raise ValueError("profile changed")
