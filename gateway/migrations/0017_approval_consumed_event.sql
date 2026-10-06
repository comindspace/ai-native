alter table approval_events
    drop constraint if exists approval_events_event_type_check;

alter table approval_events
    add constraint approval_events_event_type_check
    check (
        event_type in (
            'created',
            'commented',
            'approved',
            'rejected',
            'need_info',
            'cancelled',
            'superseded',
            'consumed'
        )
    );
