create table if not exists approval_requests (
    approval_id text primary key,
    approval_type text not null,
    status text not null default 'pending'
        check (status in ('pending', 'approved', 'rejected', 'need_info', 'cancelled', 'superseded')),
    subject text not null,
    created_by text not null default '',
    required_role text not null default '',
    required_scope text not null default '',
    artifact_hash text not null default '',
    artifact_version text not null default '',
    payload jsonb not null default '{}'::jsonb,
    source_refs jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    four_eyes boolean not null default true,
    decided_by text not null default '',
    decided_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    expires_at timestamptz
);

create index if not exists approval_requests_lookup_idx
on approval_requests (status, approval_type, required_role, created_at desc);

create index if not exists approval_requests_creator_idx
on approval_requests (created_by, created_at desc);

create index if not exists approval_requests_artifact_idx
on approval_requests (artifact_hash);

create table if not exists approval_events (
    id bigserial primary key,
    approval_id text not null references approval_requests(approval_id) on delete cascade,
    event_type text not null
        check (event_type in ('created', 'commented', 'approved', 'rejected', 'need_info', 'cancelled', 'superseded')),
    actor_subject text not null default '',
    actor_groups jsonb not null default '[]'::jsonb,
    comment text not null default '',
    decision_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists approval_events_approval_idx
on approval_events (approval_id, created_at, id);
