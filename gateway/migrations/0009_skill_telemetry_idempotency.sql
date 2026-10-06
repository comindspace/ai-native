-- Keep the latest copy of historical retries before enforcing idempotency.
delete from assistant_skill_events older
using assistant_skill_events newer
where older.id < newer.id
  and older.actor_subject = newer.actor_subject
  and older.correlation_id = newer.correlation_id
  and older.event_type = newer.event_type;

create unique index if not exists assistant_skill_events_invocation_event_uidx
on assistant_skill_events (actor_subject, correlation_id, event_type);

create index if not exists assistant_skill_events_session_open_idx
on assistant_skill_events (actor_subject, session_id, agent, created_at desc)
where event_type = 'started';
