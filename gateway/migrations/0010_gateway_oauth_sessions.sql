create table if not exists gateway_oauth_refresh_tokens (
    token_hash text primary key,
    actor_payload jsonb not null,
    client_id text not null,
    resource text not null,
    scope text not null default '',
    created_at timestamptz not null default now(),
    last_used_at timestamptz,
    expires_at timestamptz not null,
    revoked_at timestamptz
);

create index if not exists gateway_oauth_refresh_tokens_expires_idx
    on gateway_oauth_refresh_tokens (expires_at)
    where revoked_at is null;

create table if not exists gateway_oauth_revoked_access_tokens (
    jti text primary key,
    expires_at timestamptz not null,
    revoked_at timestamptz not null default now()
);

create index if not exists gateway_oauth_revoked_access_tokens_expires_idx
    on gateway_oauth_revoked_access_tokens (expires_at);
