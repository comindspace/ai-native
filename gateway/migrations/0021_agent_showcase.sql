-- Preferences are explicit; telemetry frequency never writes this table.
create table assistant_skill_favorites (
    actor_subject text not null,
    skill_pack text not null,
    skill_id text not null,
    created_at timestamptz not null default now(),
    primary key (actor_subject, skill_pack, skill_id)
);

-- A runtime name does not establish autonomy. Bind an exact telemetry identity.
create table assistant_agent_profiles (
    agent_key text primary key,
    display_name text not null,
    description text not null default '',
    actor_subject text not null default '',
    agent text not null default '',
    revision integer not null default 1,
    updated_by text not null,
    updated_at timestamptz not null default now(),
    check ((actor_subject = '' and agent = '') or (actor_subject <> '' and agent <> ''))
);
create unique index assistant_agent_profiles_binding_idx
on assistant_agent_profiles (actor_subject, agent) where actor_subject <> '';

insert into assistant_agent_profiles (agent_key, display_name, description, updated_by)
values ('assistant', 'Ассистент', 'Корпоративный агент. Привяжи отдельный источник телеметрии, чтобы видеть его работу.', 'migration:0021');
