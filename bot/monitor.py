import logging
import os
import random
from datetime import datetime, timedelta, timezone

from bot.accounts import load_accounts
from bot.config import AUTO_REPLY
from bot.db import get_db, post_seen, record_activity, save_pending_replies, save_post
from bot.discovery import discover_posts
from bot.reply_engine import generate_replies, validate_replies
from bot.telegram import send_new_post
from bot.x.provider import get_x_provider

logger = logging.getLogger(__name__)

MONITORED_HANDLES_PER_RUN = 15
MAX_DISCOVERY_POSTS_PER_RUN = 5
SCHEDULE_TIMES_UTC = ((11, 0), (14, 0), (19, 0))
SCHEDULE_ACTIVITY_EVENT = "schedule_processed"
SCAN_CHECKPOINT_EVENT = "scan_checkpoint"


def telegram_already_sent(db, post_id: str) -> bool:
    result = db.table("activity_log").select("id").eq("event_type", "telegram_sent").eq("post_id", post_id).limit(1).execute()
    return bool(result.data)


def _schedule_key(schedule_start: datetime) -> str:
    return schedule_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _schedule_already_processed(db, schedule_start: datetime) -> bool:
    key = _schedule_key(schedule_start)
    result = db.table("activity_log").select("id").eq("event_type", SCHEDULE_ACTIVITY_EVENT).eq("message", f"slot={key}").limit(1).execute()
    return bool(result.data)


def _mark_schedule_processed(db, schedule_start: datetime) -> None:
    record_activity(db, SCHEDULE_ACTIVITY_EVENT, "SYSTEM", None, f"slot={_schedule_key(schedule_start)}")


def _last_scan_checkpoint(db) -> datetime | None:
    result = (
        db.table("activity_log")
        .select("message")
        .eq("event_type", SCAN_CHECKPOINT_EVENT)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    message = str(result.data[0].get("message") or "")
    if not message.startswith("scan="):
        return None
    return _parse_created_at(message[5:])


def _mark_scan_checkpoint(db, scan_at: datetime) -> None:
    record_activity(db, SCAN_CHECKPOINT_EVENT, "SYSTEM", None, f"scan={scan_at.astimezone(timezone.utc).isoformat()}")


def _schedule_start(now: datetime) -> datetime:
    """Return the fallback start point used only before a checkpoint exists."""
    if os.getenv("TEST_MODE", "").strip().lower() == "true":
        minutes = int(os.getenv("TEST_WINDOW_MINUTES", "10"))
        return now - timedelta(minutes=minutes)

    configured = os.getenv("SCHEDULE_SLOT", "").strip()
    configured_times = {"11": (11, 0), "14": (14, 0), "19": (19, 0)}
    if configured in configured_times:
        hour, minute = configured_times[configured]
    else:
        current_minutes = now.hour * 60 + now.minute
        eligible = [(hour, minute) for hour, minute in SCHEDULE_TIMES_UTC if hour * 60 + minute <= current_minutes]
        hour, minute = eligible[-1] if eligible else SCHEDULE_TIMES_UTC[-1]

    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            created = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            logger.warning("Unable to parse post timestamp: %r", value)
            return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc)


def _is_recent_for_schedule(post, scan_start: datetime, now: datetime) -> bool:
    created = _parse_created_at(post.created_at)
    return created is not None and scan_start < created <= now


def _select_handles(accounts: list[str]) -> list[str]:
    candidates = list(accounts)
    random.shuffle(candidates)
    logger.info("Randomized monitored handle pool: %d handles", len(candidates))
    return candidates


def _is_missing_account_error(exc: Exception) -> bool:
    """Return True only for a provider 404 that means the monitored account cannot be resolved."""
    return "TwitterAPIs HTTP 404:" in str(exc)


def _process_post(db, post, handle: str, *, source: str) -> str:
    if post_seen(db, post.id) and telegram_already_sent(db, post.id):
        logger.info("SEEN | %s | %s", handle, post.id)
        return "skipped"

    if not post_seen(db, post.id):
        save_post(db, post)
        record_activity(db, "new_post", handle, post.id, post.text.replace("\n", " "))

    try:
        replies = generate_replies(post.text)
    except Exception as exc:
        if "Groq returned" not in str(exc):
            logger.exception("Failed to generate reply suggestions for %s", post.id)
            record_activity(db, "error", handle, post.id, "Failed to generate reply suggestions")
            return "error"

        logger.warning("Groq returned an incomplete reply set for %s; retrying once", post.id)
        try:
            replies = generate_replies(post.text)
        except Exception as retry_exc:
            if "Groq returned" in str(retry_exc):
                logger.warning("SOFT SKIP | %s | Groq still returned an incomplete reply set after retry", post.id)
                record_activity(db, "reply_generation_skipped", handle, post.id, "Groq returned fewer than three valid replies after one retry")
                return "skipped"
            logger.exception("Retry failed while generating reply suggestions for %s", post.id)
            record_activity(db, "error", handle, post.id, "Failed to generate reply suggestions on retry")
            return "error"

    if not replies or not validate_replies(replies):
        logger.warning("Reply validation failed for %s: %r", post.id, replies)
        record_activity(db, "reply_generation_skipped", handle, post.id, "Reply validation failed")
        return "skipped"

    record_activity(db, "replies_suggested", handle, post.id, f"Three reply suggestions generated from {source}")

    if AUTO_REPLY:
        logger.warning("AUTO_REPLY is enabled but manual three-choice mode is required; skipping automatic post for %s", post.id)
    else:
        save_pending_replies(db, post.id, handle, post.text, replies)

    try:
        if telegram_already_sent(db, post.id):
            return "skipped"
        send_new_post(handle, post.text, post.url, suggested_replies=replies, post_id=post.id)
        record_activity(db, "telegram_sent", handle, post.id, f"Post notification sent to Telegram from {source}")
        return "sent"
    except Exception:
        logger.exception("Failed to send Telegram notification for %s", post.id)
        record_activity(db, "error", handle, post.id, f"Failed to send Telegram notification from {source}")
        return "error"


def _process_handle(db, provider, handle: str, scan_start: datetime, now: datetime) -> str:
    try:
        posts = provider.get_latest_posts(handle, limit=20)
    except Exception as exc:
        if _is_missing_account_error(exc):
            logger.warning("SKIP ACCOUNT | %s | TwitterAPIs could not resolve this account", handle)
            record_activity(db, "account_skipped", handle, None, "TwitterAPIs returned HTTP 404; account may be invalid, renamed, or unavailable")
            return "skipped"
        logger.exception("Failed to fetch posts for %s", handle)
        record_activity(db, "error", handle, None, "Failed to fetch recent posts from X provider")
        return "error"

    if not posts:
        logger.info("NO FEED | %s | no posts returned", handle)
        return "skipped"

    newest = None
    newest_created = None
    for post in posts:
        parsed = _parse_created_at(post.created_at)
        logger.info("POST | %s | id=%s | created_at=%r | parsed_utc=%s", handle, post.id, post.created_at, parsed.isoformat() if parsed else "INVALID")
        if not _is_recent_for_schedule(post, scan_start, now):
            continue
        if post_seen(db, post.id) and telegram_already_sent(db, post.id):
            continue
        if newest_created is None or (parsed is not None and parsed > newest_created):
            newest = post
            newest_created = parsed

    if newest is None:
        logger.info("NO FEED | %s | no new qualifying post since last scan", handle)
        return "skipped"

    return _process_post(db, newest, handle, source="monitored account")


def _run_discovery(db, provider, accounts: list[str], scan_start: datetime, now: datetime) -> tuple[int, bool]:
    candidates = discover_posts(provider, accounts, max_posts=MAX_DISCOVERY_POSTS_PER_RUN)
    if not candidates:
        logger.info("Discovery found no qualifying non-monitored posts.")
        return 0, False

    recent = []
    for post, topic, score in candidates:
        if _is_recent_for_schedule(post, scan_start, now):
            recent.append((post, topic, score))
        else:
            logger.info("NO DISCOVERY FEED | %s | outside last-scan range: %s", post.username, post.created_at)

    recent.sort(key=lambda item: _parse_created_at(item[0].created_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    used_authors: set[str] = set()
    sent = 0
    had_error = False
    for post, topic, score in recent:
        author = post.username.lstrip("@").lower()
        if author in used_authors or post_seen(db, post.id):
            continue
        handle = f"@{post.username.lstrip('@')}"
        logger.info("DISCOVERY | %s | score=%d | %s", topic, score, handle)
        result = _process_post(db, post, handle, source=f"discovery:{topic}")
        if result == "error":
            had_error = True
        elif result == "sent":
            record_activity(db, "discovery_processed", handle, post.id, f"Discovered reply opportunity from topic {topic} with score {score}")
            used_authors.add(author)
            sent += 1
            if sent >= MAX_DISCOVERY_POSTS_PER_RUN:
                break
    return sent, had_error


def run_monitor_cycle() -> None:
    accounts = load_accounts()
    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    provider = get_x_provider()
    db = get_db()
    now = datetime.now(timezone.utc)
    previous_scan = _last_scan_checkpoint(db)
    scan_start = previous_scan or _schedule_start(now)
    logger.info("Scan range: %s → %s UTC", scan_start.isoformat(), now.isoformat())

    had_error = False
    monitored_sent = 0

    for handle in _select_handles(accounts):
        if monitored_sent >= MONITORED_HANDLES_PER_RUN:
            break
        result = _process_handle(db, provider, handle, scan_start, now)
        if result == "error":
            had_error = True
        elif result == "sent":
            monitored_sent += 1

    logger.info("MONITORED COMPLETE | feeds=%d/%d", monitored_sent, MONITORED_HANDLES_PER_RUN)

    discovery_sent, discovery_error = _run_discovery(db, provider, accounts, scan_start, now)
    had_error = had_error or discovery_error
    logger.info("DISCOVERY COMPLETE | feeds=%d/%d", discovery_sent, MAX_DISCOVERY_POSTS_PER_RUN)

    if had_error:
        logger.error("SCAN NOT CHECKPOINTED | one or more feed operations failed")
        return

    _mark_scan_checkpoint(db, now)
    logger.info("SCAN COMPLETE | checkpoint=%s | total_feeds=%d", now.isoformat(), monitored_sent + discovery_sent)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
    run_monitor_cycle()
