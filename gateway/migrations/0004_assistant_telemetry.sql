create table if not exists assistant_sessions (
    session_id text primary key,
    actor_subject text not null default '',
    agent text not null default '',
    client text not null default '',
    project text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    started_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    ended_at timestamptz
);

create index if not exists assistant_sessions_actor_idx
on assistant_sessions (actor_subject, updated_at desc);

create table if not exists assistant_skill_events (
    id bigserial primary key,
    event_type text not null check (event_type in ('started', 'completed', 'failed')),
    correlation_id text not null,
    session_id text not null default '',
    actor_subject text not null default '',
    agent text not null default '',
    skill_id text not null default '',
    skill_pack text not null default '',
    skill_version text not null default '',
    project text not null default '',
    client text not null default '',
    status text not null default '',
    duration_ms integer,
    mcp_routes jsonb not null default '[]'::jsonb,
    missing_scopes jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    error_class text not null default '',
    created_at timestamptz not null default now()
);

create index if not exists assistant_skill_events_lookup_idx
on assistant_skill_events (skill_id, agent, event_type, created_at desc);

create index if not exists assistant_skill_events_actor_idx
on assistant_skill_events (actor_subject, created_at desc);

create or replace view assistant_adoption_daily as
select
    date_trunc('day', created_at)::date as day,
    agent,
    skill_pack,
    skill_id,
    count(*) filter (where event_type = 'started') as started_count,
    count(*) filter (where event_type = 'completed') as completed_count,
    count(*) filter (where event_type = 'failed') as failed_count,
    count(distinct actor_subject) as active_users,
    percentile_cont(0.5) within group (order by duration_ms)
        filter (where duration_ms is not null) as p50_duration_ms,
    percentile_cont(0.95) within group (order by duration_ms)
        filter (where duration_ms is not null) as p95_duration_ms
from assistant_skill_events
group by 1, 2, 3, 4;
