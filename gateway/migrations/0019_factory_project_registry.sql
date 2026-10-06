create table if not exists factory_projects (
    project_id text primary key,
    config jsonb not null,
    revision bigint not null default 1,
    readiness jsonb not null default '{}'::jsonb,
    updated_by text not null,
    updated_at timestamptz not null default now()
);

create unique index if not exists factory_projects_tracker_project_id
    on factory_projects ((nullif(config->>'tracker_project_id', '')));

-- Receipts are also the durable audit of configuration changes. No credentials.
create table if not exists factory_project_operations (
    actor_subject text not null,
    operation text not null,
    idempotency_key text not null,
    project_id text not null,
    fingerprint text not null,
    result jsonb not null,
    status text not null default 'running' check (status in ('running', 'complete', 'failed')),
    created_at timestamptz not null default now(),
    primary key (actor_subject, operation, idempotency_key)
);

create table if not exists factory_git_probes (
    ref text primary key,
    project_id text not null,
    remote_url text not null,
    head text not null,
    state text not null check (state in ('pending', 'removed', 'cleanup_required')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists factory_project_one_validation
    on factory_project_operations (project_id) where status = 'running';

create table if not exists factory_work_retries (
    work_id text not null references work_runs(work_id),
    idempotency_key text not null,
    actor_subject text not null,
    project_revision bigint not null,
    created_at timestamptz not null default now(),
    primary key (work_id, actor_subject, idempotency_key)
);
