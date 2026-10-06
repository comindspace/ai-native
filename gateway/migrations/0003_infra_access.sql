create table if not exists infra_servers (
    id text primary key,
    hostname text not null default '',
    address text not null default '',
    environment text not null default '',
    role text not null default '',
    owner text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    revoked_at timestamptz
);

create index if not exists infra_servers_environment_idx
on infra_servers (environment, revoked_at);

create table if not exists infra_ssh_credentials (
    handle text primary key,
    server_id text not null references infra_servers(id) on delete cascade,
    username text not null,
    private_key_path_encrypted text not null,
    allowlist jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    revoked_at timestamptz
);

create index if not exists infra_ssh_credentials_server_idx
on infra_ssh_credentials (server_id, revoked_at);
