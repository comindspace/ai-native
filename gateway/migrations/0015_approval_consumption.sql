alter table approval_requests
    add column if not exists consumed_at timestamptz,
    add column if not exists consumed_by text not null default '',
    add column if not exists consumed_action text not null default '',
    add column if not exists consumption_key text not null default '';

create unique index if not exists approval_requests_consumption_key_idx
    on approval_requests (consumption_key)
    where consumption_key <> '';
