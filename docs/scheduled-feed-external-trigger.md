# Reliable scheduled-feed triggering

Use the existing X-Bot Supabase project as the primary scheduler. Supabase Cron runs inside Postgres on UTC schedules and can make HTTP requests. This avoids relying on GitHub's best-effort scheduled events and avoids placing a GitHub token in a third-party cron service.

GitHub's scheduled workflow remains a backup, offset from the top of the hour.

## Daily feed slots

Nigeria uses WAT (UTC+1). Create three Supabase Cron jobs:

| WAT | UTC | GitHub `schedule_slot` |
| --- | --- | --- |
| 12:00 | 11:00 | `11:00` |
| 17:00 | 16:00 | `16:00` |
| 21:00 | 20:00 | `20:00` |

Supabase Cron schedules below are UTC. The GitHub dispatch includes the slot time, and the monitor skips it if it arrives more than 20 minutes late.

## 1. Create a fine-grained GitHub token

Create a fine-grained personal access token restricted to the `AkuWaziri/X-Bot` repository. Grant only:

- Repository permissions → Actions → Read and write

Do not grant Contents, Administration, or other permissions. Keep the token private.

## 2. Store the token in Supabase Vault

In the Supabase Dashboard for the database already used by X-Bot:

1. Open Database → Vault.
2. Add a secret with the name `xbot_github_actions_token`.
3. Paste the GitHub token as the secret value and save it.
4. Do not paste the token into this document, SQL snippets, GitHub files, or chat.

Vault encrypts secrets at rest. Note that Supabase's `pg_net` temporarily queues decrypted request headers until it sends the HTTP request; database login roles with access to the queue can read queued headers. Restrict database access accordingly.

## 3. Enable required extensions

In Database → Extensions, ensure these extensions are enabled:

- `pg_cron`
- `pg_net`
- Supabase Vault (usually already enabled)

Do not drop or recreate extensions that are already installed.

## 4. Create the three scheduled jobs

Run this SQL in the Supabase SQL Editor. It does not contain the GitHub token; each run reads it from Vault.

```sql
-- 12:00 WAT / 11:00 UTC
select cron.schedule(
  'xbot-feed-1200-wat',
  '0 11 * * *',
  $job$
  select net.http_post(
    url := 'https://api.github.com/repos/AkuWaziri/X-Bot/actions/workflows/scheduled-feed.yml/dispatches',
    headers := jsonb_build_object(
      'Accept', 'application/vnd.github+json',
      'Authorization', 'Bearer ' || (
        select decrypted_secret
        from vault.decrypted_secrets
        where name = 'xbot_github_actions_token'
      ),
      'X-GitHub-Api-Version', '2022-11-28',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object(
      'ref', 'main',
      'inputs', jsonb_build_object(
        'run_mode', 'production',
        'schedule_slot', '11:00'
      )
    ),
    timeout_milliseconds := 10000
  ) as request_id;
  $job$
);

-- 17:00 WAT / 16:00 UTC
select cron.schedule(
  'xbot-feed-1700-wat',
  '0 16 * * *',
  $job$
  select net.http_post(
    url := 'https://api.github.com/repos/AkuWaziri/X-Bot/actions/workflows/scheduled-feed.yml/dispatches',
    headers := jsonb_build_object(
      'Accept', 'application/vnd.github+json',
      'Authorization', 'Bearer ' || (
        select decrypted_secret
        from vault.decrypted_secrets
        where name = 'xbot_github_actions_token'
      ),
      'X-GitHub-Api-Version', '2022-11-28',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object(
      'ref', 'main',
      'inputs', jsonb_build_object(
        'run_mode', 'production',
        'schedule_slot', '16:00'
      )
    ),
    timeout_milliseconds := 10000
  ) as request_id;
  $job$
);

-- 21:00 WAT / 20:00 UTC
select cron.schedule(
  'xbot-feed-2100-wat',
  '0 20 * * *',
  $job$
  select net.http_post(
    url := 'https://api.github.com/repos/AkuWaziri/X-Bot/actions/workflows/scheduled-feed.yml/dispatches',
    headers := jsonb_build_object(
      'Accept', 'application/vnd.github+json',
      'Authorization', 'Bearer ' || (
        select decrypted_secret
        from vault.decrypted_secrets
        where name = 'xbot_github_actions_token'
      ),
      'X-GitHub-Api-Version', '2022-11-28',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object(
      'ref', 'main',
      'inputs', jsonb_build_object(
        'run_mode', 'production',
        'schedule_slot', '20:00'
      )
    ),
    timeout_milliseconds := 10000
  ) as request_id;
  $job$
);
```

The job names are stable. Running the same `cron.schedule` statements again updates the existing jobs with those names instead of creating duplicate named jobs.

## 5. Verify the schedules

Check that all three jobs are active:

```sql
select jobid, jobname, schedule, active
from cron.job
where jobname in (
  'xbot-feed-1200-wat',
  'xbot-feed-1700-wat',
  'xbot-feed-2100-wat'
)
order by jobname;
```

After a scheduled time, inspect recent runs:

```sql
select j.jobname, r.status, r.start_time, r.end_time, r.return_message
from cron.job_run_details r
join cron.job j on j.jobid = r.jobid
where j.jobname like 'xbot-feed-%'
order by r.start_time desc
limit 12;
```

A successful `pg_net` enqueue is not itself proof that GitHub accepted the dispatch. Confirm each corresponding run in GitHub Actions and inspect the monitor logs. GitHub's workflow dispatch API normally returns HTTP 204 when accepted.

## Operational behavior

- The existing manual GitHub **Run workflow** action remains a short smoke test by default.
- Only explicit `run_mode=production` dispatches run a production feed cycle.
- The three production dispatches pass their matching UTC slot.
- GitHub cron remains a backup.
- Existing Supabase schedule markers prevent duplicate delivery when both triggers fire.
- Runs outside the 20-minute slot grace are skipped and logged as `STALE SCHEDULE SKIPPED`; stale feeds will not be sent overnight.
- The monitored-handle allocation, discovery allocation, feed selection, Groq budget, Telegram formatting, and `/project` workflow are unchanged.
