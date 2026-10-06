create table if not exists access_requests (
    id uuid primary key,
    requester_subject text not null,
    requester_email text not null default '',
    subject_key text not null,
    package_key text not null,
    package_version integer not null,
    reason text not null,
    requested_ttl_days integer,
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'approved', 'rejected', 'cancelled')),
    idempotency_key text not null default '',
    decided_by text not null default '',
    decision_reason text not null default '',
    grant_bundle_id uuid references access_grant_bundles(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    decided_at timestamptz
);

create index if not exists access_requests_requester_idx
on access_requests (requester_subject, created_at desc);

create index if not exists access_requests_status_idx
on access_requests (status, created_at asc);

create unique index if not exists access_requests_active_package_idx
on access_requests (requester_subject, package_key)
where status in ('pending', 'processing');

create unique index if not exists access_requests_idempotency_idx
on access_requests (requester_subject, idempotency_key)
where idempotency_key <> '';
