create table if not exists user_oauth_tokens (
    id bigserial primary key,
    provider text not null,
    actor_subject text not null,
    yandex_id text not null default '',
    login text not null default '',
    email text not null default '',
    access_token_encrypted text not null,
    token_type text not null default 'OAuth',
    scopes jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    expires_at timestamptz,
    revoked_at timestamptz,
    unique (provider, actor_subject)
);

create index if not exists user_oauth_tokens_lookup_idx
on user_oauth_tokens (provider, actor_subject, revoked_at, expires_at);
