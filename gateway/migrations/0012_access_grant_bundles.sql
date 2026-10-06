create table if not exists access_grant_bundles (
    id uuid primary key,
    subject_type text not null check (subject_type in ('user', 'group')),
    subject_key text not null,
    package_key text not null,
    package_version integer not null default 1,
    title text not null,
    resources jsonb not null default '[]'::jsonb,
    reason text not null default '',
    created_by text not null default '',
    created_at timestamptz not null default now(),
    expires_at timestamptz,
    revoked_at timestamptz
);

create index if not exists access_grant_bundles_subject_idx
on access_grant_bundles (subject_type, subject_key, revoked_at, expires_at);

alter table access_scope_grants
add column if not exists bundle_id uuid references access_grant_bundles(id);

alter table access_resource_grants
add column if not exists bundle_id uuid references access_grant_bundles(id);

create index if not exists access_scope_grants_bundle_idx
on access_scope_grants (bundle_id);

create index if not exists access_resource_grants_bundle_idx
on access_resource_grants (bundle_id);
