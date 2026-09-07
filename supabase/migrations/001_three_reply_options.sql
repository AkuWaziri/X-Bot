-- Run this migration in the Supabase SQL editor before the next monitor run.
-- Keep the existing suggested_reply column for backward compatibility.

alter table pending_replies
    add column if not exists reply_1 text,
    add column if not exists reply_2 text,
    add column if not exists reply_3 text,
    add column if not exists selected_reply integer,
    add column if not exists reply_id text,
    add column if not exists reply_url text;

-- Existing rows are intentionally left untouched. New rows created by X-Bot
-- will use reply_1/reply_2/reply_3 and status='pending'.
