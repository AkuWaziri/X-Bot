-- Move the former emergency allocation to the new owned-post comments feature.
-- This is safe whether migration 002 was applied before or after the allocation rename.
alter table public.groq_token_usage
    drop constraint if exists groq_token_usage_usage_class_check;

insert into public.groq_token_usage (
    usage_date, usage_class, used_tokens, reserved_tokens, updated_at
)
select
    usage_date, 'comments', used_tokens, reserved_tokens, updated_at
from public.groq_token_usage
where usage_class = 'emergency'
on conflict (usage_date, usage_class) do update
set used_tokens = public.groq_token_usage.used_tokens + excluded.used_tokens,
    reserved_tokens = public.groq_token_usage.reserved_tokens + excluded.reserved_tokens,
    updated_at = now();

delete from public.groq_token_usage where usage_class = 'emergency';

alter table public.groq_token_usage
    add constraint groq_token_usage_usage_class_check
    check (usage_class in ('project', 'scheduled', 'comments'));

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

-- Persist the owner's recent original posts and deduplicate comment notifications.
create table if not exists public.owned_posts (
    post_id text primary key,
    post_url text not null,
    post_text text not null,
    posted_at timestamptz,
    first_seen_at timestamptz not null default now()
);

create table if not exists public.notified_comments (
    comment_id text primary key,
    root_post_id text not null,
    author_handle text not null,
    comment_text text not null,
    comment_url text not null,
    notified_at timestamptz not null default now()
);

alter table public.owned_posts enable row level security;
alter table public.notified_comments enable row level security;
revoke all on public.owned_posts from anon, authenticated;
revoke all on public.notified_comments from anon, authenticated;
grant all on public.owned_posts to service_role;
grant all on public.notified_comments to service_role;

create index if not exists owned_posts_posted_at_idx
    on public.owned_posts (posted_at desc);
create index if not exists notified_comments_root_post_id_idx
    on public.notified_comments (root_post_id);
