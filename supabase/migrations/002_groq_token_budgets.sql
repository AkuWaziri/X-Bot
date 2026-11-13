-- Shared Groq daily token budgets across Render and GitHub Actions.
create table if not exists public.groq_token_usage (
    usage_date date not null,
    usage_class text not null check (usage_class in ('project', 'scheduled', 'comments')),
    used_tokens bigint not null default 0,
    reserved_tokens bigint not null default 0,
    updated_at timestamptz not null default now(),
    primary key (usage_date, usage_class)
);

alter table public.groq_token_usage enable row level security;
revoke all on public.groq_token_usage from anon, authenticated;
grant all on public.groq_token_usage to service_role;

create or replace function public.reserve_groq_tokens(
    p_usage_class text,
    p_estimate bigint,
    p_daily_limit bigint,
    p_request_id uuid
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_date date := (now() at time zone 'utc')::date;
    v_used bigint;
    v_reserved bigint;
begin
    if p_usage_class not in ('project', 'scheduled', 'comments')
       or p_estimate <= 0 or p_daily_limit <= 0 then
        raise exception 'Invalid Groq budget reservation';
    end if;

    insert into groq_token_usage (usage_date, usage_class)
    values (v_date, p_usage_class)
    on conflict (usage_date, usage_class) do nothing;

    select used_tokens, reserved_tokens into v_used, v_reserved
    from groq_token_usage
    where usage_date = v_date and usage_class = p_usage_class
    for update;

    if v_used + v_reserved + p_estimate > p_daily_limit then
        return false;
    end if;

    update groq_token_usage
    set reserved_tokens = reserved_tokens + p_estimate, updated_at = now()
    where usage_date = v_date and usage_class = p_usage_class;

    insert into groq_token_reservations (request_id, usage_date, usage_class, reserved_tokens)
    values (p_request_id, v_date, p_usage_class, p_estimate)
    on conflict (request_id) do nothing;

    return true;
end;
$$;

create table if not exists public.groq_token_reservations (
    request_id uuid primary key,
    usage_date date not null,
    usage_class text not null,
    reserved_tokens bigint not null,
    settled boolean not null default false,
    created_at timestamptz not null default now()
);

alter table public.groq_token_reservations enable row level security;
revoke all on public.groq_token_reservations from anon, authenticated;
grant all on public.groq_token_reservations to service_role;

create or replace function public.settle_groq_tokens(
    p_request_id uuid,
    p_actual_tokens bigint
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
    r groq_token_reservations%rowtype;
begin
    select * into r from groq_token_reservations
    where request_id = p_request_id and not settled
    for update;

    if not found then return; end if;

    update groq_token_usage
    set reserved_tokens = greatest(0, reserved_tokens - r.reserved_tokens),
        used_tokens = used_tokens + greatest(0, p_actual_tokens),
        updated_at = now()
    where usage_date = r.usage_date and usage_class = r.usage_class;

    update groq_token_reservations set settled = true where request_id = p_request_id;
end;
$$;

revoke all on function public.reserve_groq_tokens(text, bigint, bigint, uuid) from public, anon, authenticated;
revoke all on function public.settle_groq_tokens(uuid, bigint) from public, anon, authenticated;
grant execute on function public.reserve_groq_tokens(text, bigint, bigint, uuid) to service_role;
grant execute on function public.settle_groq_tokens(uuid, bigint) to service_role;
