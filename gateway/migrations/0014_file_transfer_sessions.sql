create table if not exists gateway_upload_sessions (
    upload_id uuid primary key,
    actor_subject text not null,
    upload_token_hash text not null unique,
    original_filename text not null,
    content_type text not null,
    expected_size_bytes bigint not null,
    expected_sha256 text not null,
    size_bytes bigint,
    sha256 text not null default '',
    storage_path text not null,
    state text not null default 'pending',
    error_code text not null default '',
    created_at timestamptz not null default now(),
    uploaded_at timestamptz,
    completed_at timestamptz,
    expires_at timestamptz not null,
    constraint gateway_upload_sessions_state check (
        state in ('pending', 'uploading', 'succeeded', 'failed', 'expired')
    ),
    constraint gateway_upload_sessions_expected_size_positive check (
        expected_size_bytes > 0
    ),
    constraint gateway_upload_sessions_size_positive check (
        size_bytes is null or size_bytes >= 0
    ),
    constraint gateway_upload_sessions_expected_sha256 check (
        expected_sha256 ~ '^[0-9a-f]{64}$'
    )
);

create index if not exists gateway_upload_sessions_actor_idx
    on gateway_upload_sessions (actor_subject, created_at desc);

create index if not exists gateway_upload_sessions_expiry_idx
    on gateway_upload_sessions (expires_at)
    where state in ('pending', 'uploading', 'succeeded');

create table if not exists gateway_download_sessions (
    download_id uuid primary key,
    actor_subject text not null,
    download_token_hash text not null unique,
    upload_id uuid not null references gateway_upload_sessions(upload_id) on delete cascade,
    state text not null default 'pending',
    filename text not null default '',
    content_type text not null default 'application/octet-stream',
    size_bytes bigint,
    sha256 text not null default '',
    error_code text not null default '',
    created_at timestamptz not null default now(),
    claimed_at timestamptz,
    completed_at timestamptz,
    expires_at timestamptz not null,
    constraint gateway_download_sessions_state check (
        state in ('pending', 'downloading', 'succeeded', 'failed', 'expired')
    ),
    constraint gateway_download_sessions_size_positive check (
        size_bytes is null or size_bytes >= 0
    ),
    constraint gateway_download_sessions_sha256 check (
        sha256 = '' or sha256 ~ '^[0-9a-f]{64}$'
    )
);

create index if not exists gateway_download_sessions_actor_idx
    on gateway_download_sessions (actor_subject, created_at desc);

create index if not exists gateway_download_sessions_expiry_idx
    on gateway_download_sessions (expires_at)
    where state in ('pending', 'downloading');
