create table notification_events (
    notification_id text primary key,
    event_type text not null,
    title text not null,
    body text not null default '',
    action_url text not null default '',
    project_id text not null default '',
    priority text not null default 'normal'
        check (priority in ('low', 'normal', 'high', 'urgent')),
    created_by text not null,
    artifact_refs jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    idempotency_key text not null default '',
    expires_at timestamptz,
    created_at timestamptz not null default now()
);

create unique index notification_events_idempotency_idx
    on notification_events (created_by, idempotency_key)
    where idempotency_key <> '';

create index notification_events_created_idx
    on notification_events (created_at desc);

create index notification_events_project_idx
    on notification_events (project_id, created_at desc)
    where project_id <> '';

create table notification_recipients (
    id bigserial primary key,
    notification_id text not null references notification_events(notification_id) on delete cascade,
    recipient_type text not null
        check (recipient_type in ('user', 'group', 'role', 'team', 'project')),
    recipient_key text not null,
    created_at timestamptz not null default now(),
    unique (notification_id, recipient_type, recipient_key)
);

create index notification_recipients_lookup_idx
    on notification_recipients (recipient_type, recipient_key, notification_id);

create table notification_receipts (
    notification_id text not null references notification_events(notification_id) on delete cascade,
    actor_subject text not null,
    seen_at timestamptz,
    read_at timestamptz,
    updated_at timestamptz not null default now(),
    primary key (notification_id, actor_subject)
);

create index notification_receipts_actor_idx
    on notification_receipts (actor_subject, read_at, updated_at desc);

create table notification_topic_subscriptions (
    actor_subject text not null,
    topic_type text not null check (topic_type in ('project')),
    topic_key text not null,
    created_at timestamptz not null default now(),
    primary key (actor_subject, topic_type, topic_key)
);

create table push_subscriptions (
    subscription_id text primary key,
    actor_subject text not null,
    actor_email text not null default '',
    actor_login text not null default '',
    actor_yandex_id text not null default '',
    actor_groups jsonb not null default '[]'::jsonb,
    endpoint text not null unique,
    p256dh text not null,
    auth_secret text not null,
    user_agent text not null default '',
    enabled boolean not null default true,
    failure_count integer not null default 0,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index push_subscriptions_actor_idx
    on push_subscriptions (actor_subject, enabled);

create table notification_deliveries (
    id bigserial primary key,
    notification_id text not null references notification_events(notification_id) on delete cascade,
    subscription_id text not null references push_subscriptions(subscription_id) on delete cascade,
    status text not null default 'pending'
        check (status in ('pending', 'sending', 'sent', 'retry', 'failed')),
    attempts integer not null default 0,
    next_attempt_at timestamptz not null default now(),
    locked_at timestamptz,
    sent_at timestamptz,
    last_error_code text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (notification_id, subscription_id)
);

create index notification_deliveries_pending_idx
    on notification_deliveries (next_attempt_at, id)
    where status in ('pending', 'retry', 'sending');
