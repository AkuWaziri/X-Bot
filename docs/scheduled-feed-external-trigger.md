# Reliable scheduled-feed triggering

The scheduled-feed workflow keeps GitHub's cron triggers as a backup, but GitHub-hosted cron is best-effort and is not a punctual scheduler. Configure an external HTTP scheduler as the primary trigger.

## Daily UTC schedule

Nigeria uses WAT (UTC+1). Create three recurring HTTP POST jobs:

| WAT | UTC | `schedule_slot` |
| --- | --- | --- |
| 12:00 | 11:00 | `11:00` |
| 17:00 | 16:00 | `16:00` |
| 21:00 | 20:00 | `20:00` |

Use the UTC timezone in the external scheduler. Trigger each job at the listed UTC time. A trigger arriving more than 20 minutes after its slot is intentionally skipped; it will not send an old feed in the middle of the night.

## GitHub API request

Configure each external job to send an HTTP POST to:

`https://api.github.com/repos/AkuWaziri/X-Bot/actions/workflows/scheduled-feed.yml/dispatches`

Headers:

- `Accept: application/vnd.github+json`
- `Authorization: Bearer <fine-grained-token>`
- `X-GitHub-Api-Version: 2022-11-28`
- `Content-Type: application/json`

Request body for the 12:00 WAT job:

```json
{
  "ref": "main",
  "inputs": {
    "run_mode": "production",
    "schedule_slot": "11:00"
  }
}
```

For the 17:00 WAT job, use `"schedule_slot": "16:00"`; for the 21:00 WAT job, use `"schedule_slot": "20:00"`.

Create a fine-grained GitHub personal access token restricted to this repository, with **Actions: Read and write** permission. Store it only in the external scheduler's secret/header store. Do not put the token in this repository, workflow YAML, or chat.

## Operational behavior

- The existing manual **Run workflow** action remains a short smoke test by default.
- Only an explicit `run_mode=production` dispatch runs the production feed cycle.
- Production dispatches must include the matching UTC slot.
- GitHub cron remains a backup, offset from the top of the hour.
- Duplicate triggers are protected by the existing Supabase schedule marker.
- The workflow queues concurrent invocations rather than replacing a pending run.
- Runs outside the 20-minute slot grace are skipped and logged as `STALE SCHEDULE SKIPPED`.
- The monitored-handle allocation, discovery allocation, feed selection, Groq budget, Telegram formatting, and `/project` workflow are unchanged.
