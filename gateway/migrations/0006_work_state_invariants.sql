create or replace function enforce_work_run_state_transition()
returns trigger
language plpgsql
as $$
declare
    allowed boolean := false;
begin
    if new.status = old.status then
        allowed := true;
    elsif old.status = 'queued' then
        allowed := new.status in ('running', 'cancelled');
    elsif old.status = 'running' then
        allowed := new.status in ('review', 'completed', 'blocked', 'cancelled');
    elsif old.status = 'review' then
        allowed := new.status in ('running', 'completed', 'blocked', 'cancelled');
    elsif old.status = 'blocked' then
        allowed := new.status in ('running', 'queued', 'cancelled');
    elsif old.status = 'completed' then
        allowed := new.status in ('running', 'accepted');
    end if;

    if not allowed then
        raise exception 'invalid work status transition: % -> %', old.status, new.status;
    end if;
    if new.status = 'completed' and old.status <> 'completed' and new.completed_at is null then
        raise exception 'completed work requires completed_at';
    end if;
    if new.status = 'accepted'
       and old.status <> 'accepted'
       and (new.completed_at is null or new.first_verified_at is null or new.accepted_at is null) then
        raise exception 'accepted work requires completed and verified timestamps';
    end if;
    return new;
end;
$$;

drop trigger if exists work_runs_state_transition_guard on work_runs;
create trigger work_runs_state_transition_guard
before update on work_runs
for each row
execute function enforce_work_run_state_transition();
