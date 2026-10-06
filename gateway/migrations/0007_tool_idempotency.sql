create table if not exists tool_idempotency_records (
    actor_subject text not null,
    tool_name text not null,
    idempotency_key text not null,
    request_hash text not null,
    status text not null check (status in ('pending', 'completed', 'failed')),
    response jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    expires_at timestamptz not null,
    primary key (actor_subject, tool_name, idempotency_key)
);

create index if not exists idx_tool_idempotency_expires_at
    on tool_idempotency_records (expires_at);
