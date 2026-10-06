create table if not exists work_runs (
    work_id text primary key,
    idempotency_key text not null default '',
    actor_subject text not null,
    project_id text not null,
    project_path text not null default '',
    scope_id text not null default '',
    scope_decision text not null default 'unresolved',
    source_type text not null,
    source_ref text not null default '',
    intent_summary text not null,
    work_kind text not null default 'code_change',
    sdd_level text not null check (sdd_level in ('S0', 'S1', 'S2', 'S3')),
    execution_mode text not null check (execution_mode in ('local', 'factory')),
    risk_level text not null default 'normal' check (risk_level in ('low', 'normal', 'high', 'critical')),
    status text not null check (status in ('queued', 'running', 'review', 'completed', 'accepted', 'blocked', 'cancelled')),
    priority integer not null default 0,
    source_refs jsonb not null default '[]'::jsonb,
    acceptance_criteria jsonb not null default '[]'::jsonb,
    quality_gates jsonb not null default '[]'::jsonb,
    contract jsonb not null default '{}'::jsonb,
    result_refs jsonb not null default '[]'::jsonb,
    metrics jsonb not null default '{}'::jsonb,
    claimed_by text not null default '',
    lease_expires_at timestamptz,
    correction_rounds integer not null default 0,
    signal_at timestamptz not null default now(),
    started_at timestamptz,
    first_verified_at timestamptz,
    completed_at timestamptz,
    accepted_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists work_runs_idempotency_idx
on work_runs (actor_subject, idempotency_key)
where idempotency_key <> '';

create index if not exists work_runs_queue_idx
on work_runs (status, execution_mode, priority desc, created_at);

create index if not exists work_runs_project_idx
on work_runs (project_id, created_at desc);

create table if not exists work_events (
    id bigserial primary key,
    work_id text not null references work_runs(work_id) on delete cascade,
    actor_subject text not null,
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    occurred_at timestamptz not null default now()
);

create index if not exists work_events_work_idx
on work_events (work_id, occurred_at);
