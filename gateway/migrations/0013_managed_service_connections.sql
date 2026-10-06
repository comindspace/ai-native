create table if not exists managed_service_connections (
    system text primary key,
    payload_encrypted text not null,
    configured_fields jsonb not null default '[]'::jsonb,
    state text not null default 'active',
    version integer not null default 1,
    created_by text not null default '',
    updated_by text not null default '',
    expires_at timestamptz,
    last_checked_at timestamptz,
    last_check_ok boolean,
    last_check_message text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint managed_service_connections_state
        check (state in ('active', 'disabled')),
    constraint managed_service_connections_version_positive
        check (version > 0)
);

create index if not exists managed_service_connections_state_idx
    on managed_service_connections (state, updated_at desc);
