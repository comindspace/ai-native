create table if not exists business_project_links (
    tracker_project_id text primary key,
    crm_deal_id bigint not null unique check (crm_deal_id > 0),
    contract_confirmed boolean not null default false,
    confirmed_amount numeric(18, 2),
    confirmed_currency text,
    updated_by text not null,
    updated_at timestamptz not null default now()
);

create table if not exists business_cost_rates (
    tracker_user_id text primary key,
    hourly_rate_rub numeric(12, 2) not null check (hourly_rate_rub >= 0),
    basis text not null default 'estimate' check (basis in ('estimate', 'approved')),
    updated_by text not null,
    updated_at timestamptz not null default now()
);
