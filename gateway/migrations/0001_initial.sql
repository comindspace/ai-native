create table if not exists oauth_states (
    state text primary key,
    payload jsonb not null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index if not exists oauth_states_expires_at_idx
on oauth_states (expires_at);

create table if not exists audit_events (
    id bigserial primary key,
    ts_ms bigint not null,
    event text not null,
    actor_subject text not null default '',
    tool text not null default '',
    system text not null default '',
    decision text not null default '',
    status text not null default '',
    scope text not null default '',
    payload jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists audit_events_created_at_idx
on audit_events (created_at);

create index if not exists audit_events_tool_status_idx
on audit_events (tool, status);

create table if not exists memory_entries (
    id bigserial primary key,
    tier text not null check (tier in ('short', 'medium')),
    scope text not null check (scope in ('user', 'team', 'project', 'company')),
    subject text not null,
    kind text not null default 'fact',
    content text not null,
    source_type text not null default 'manual',
    source_uri text not null default '',
    source_title text not null default '',
    sensitivity text not null default 'internal',
    confidence numeric(3,2) not null default 1.0,
    tags jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_by text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    expires_at timestamptz
);

create index if not exists memory_entries_lookup_idx
on memory_entries (tier, scope, subject, expires_at);

create index if not exists memory_entries_created_at_idx
on memory_entries (created_at desc);

create table if not exists access_scope_grants (
    id bigserial primary key,
    subject_type text not null check (subject_type in ('user', 'group')),
    subject_key text not null,
    scope text not null,
    effect text not null default 'allow' check (effect in ('allow', 'deny')),
    reason text not null default '',
    created_by text not null default '',
    created_at timestamptz not null default now(),
    expires_at timestamptz,
    revoked_at timestamptz
);

create index if not exists access_scope_grants_lookup_idx
on access_scope_grants (subject_type, subject_key, scope, effect, expires_at, revoked_at);

create table if not exists access_resource_grants (
    id bigserial primary key,
    subject_type text not null check (subject_type in ('user', 'group')),
    subject_key text not null,
    system text not null,
    resource_type text not null default '',
    resource_pattern text not null,
    actions jsonb not null default '[]'::jsonb,
    effect text not null default 'allow' check (effect in ('allow', 'deny')),
    priority integer not null default 100,
    reason text not null default '',
    created_by text not null default '',
    created_at timestamptz not null default now(),
    expires_at timestamptz,
    revoked_at timestamptz
);

create index if not exists access_resource_grants_lookup_idx
on access_resource_grants (system, subject_type, subject_key, effect, expires_at, revoked_at);
