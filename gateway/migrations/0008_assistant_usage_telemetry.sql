create table if not exists assistant_usage_events (
    id bigserial primary key,
    event_name text not null default '',
    source text not null default '',
    source_quality text not null default 'estimated'
        check (source_quality in ('actual', 'agent_local_estimate', 'estimated', 'billing_import')),
    actor_subject text not null default '',
    agent text not null default '',
    provider text not null default '',
    model text not null default '',
    session_id text not null default '',
    correlation_id text not null default '',
    skill_id text not null default '',
    skill_pack text not null default '',
    project text not null default '',
    client text not null default '',
    cwd text not null default '',
    input_tokens integer,
    output_tokens integer,
    total_tokens integer,
    cache_creation_input_tokens integer,
    cache_read_input_tokens integer,
    reasoning_tokens integer,
    duration_ms integer,
    tool_use_count integer,
    usage_class text not null default '',
    estimated_cost_usd numeric(12,6),
    metadata jsonb not null default '{}'::jsonb,
    raw_event jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists assistant_usage_events_lookup_idx
on assistant_usage_events (created_at desc, agent, skill_id, project);

create index if not exists assistant_usage_events_actor_idx
on assistant_usage_events (actor_subject, created_at desc);

create index if not exists assistant_usage_events_session_idx
on assistant_usage_events (session_id, created_at desc);
