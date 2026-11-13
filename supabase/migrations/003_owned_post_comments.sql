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
