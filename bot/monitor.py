import logging
import os
import random
from datetime import datetime, timedelta, timezone

from bot.accounts import load_accounts
from bot.config import AUTO_REPLY
from bot.db import (
    get_db,
    post_seen,
    record_activity,
    save_pending_replies,
    save_post,
)
from bot.discovery import discover_posts
from bot.reply_engine import generate_replies, validate_replies
from bot.telegram import send_new_post
from bot.x.provider import get_x_provider

logger = logging.getLogger(__name__)

MONITORED_HANDLES_PER_RUN = 8
MAX_DISCOVERY_POSTS_PER_RUN = 2
SCHEDULE_HOURS_UTC = (10, 15, 20)


def telegram_already_sent(db, post_id: str) -> bool:
    result = (
        db.table("activity_log")
        .select("id")
        .eq("event_type", "telegram_sent")
        .eq("post_id", post_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def _schedule_start(now: datetime) -> datetime:
    """Return the start of the active monitoring window in UTC."""
    test_mode = os.getenv("TEST_MODE", "").strip().lower() == "true"
    if test_mode:
        minutes = int(os.getenv("TEST_WINDOW_MINUTES", "10"))
        return now - timedelta(minutes=minutes)

    configured = os.getenv("SCHEDULE_SLOT", "").strip()
    if configured in {"10", "15", "20"}:
        hour = int(configured)
    else:
        hour = max((h for h in SCHEDULE_HOURS_UTC if h <= now.hour), default=10)
        if now.hour < 10:
            hour = 10
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def _is_recent_for_schedule(post, schedule_start: datetime, now: datetime) -> bool:
    if not post.created_at:
        return False

    raw = str(post.created_at).strip()
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unable to parse post timestamp: %r", post.created_at)
        return False

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created = created.astimezone(timezone.utc)

    return schedule_start <= created <= now and created.date() == now.date()


def _select_handles(accounts: list[str]) -> list[str]:
    candidates = list(accounts)
    random.shuffle(candidates)
    selected = candidates[: min(MONITORED_HANDLES_PER_RUN, len(candidates))]
    logger.info("Selected %d monitored handles for this schedule: %s", len(selected), ", ".join(selected))
    return selected


def _process_post(db, post, handle: str, *, source: str) -> bool:
    if post_seen(db, post.id) and telegram_already_sent(db, post.id):
        logger.info("SEEN | %s | %s", handle, post.id)
        return False

    if not post_seen(db, post.id):
        save_post(db, post)
        record_activity(db, "new_post", handle, post.id, post.text.replace("\n", " "))

    replies = None
    try:
        replies = generate_replies(post.text)
    except Exception:
        logger.exception("Failed to generate reply suggestions for %s", post.id)
        record_activity(db, "error", handle, post.id, "Failed to generate reply suggestions")

    if replies and not validate_replies(replies):
        logger.warning("Reply validation failed for %s: %r", post.id, replies)
        replies = None

    if not replies:
        return False

    record_activity(db, "replies_suggested", handle, post.id, f"Three reply suggestions generated from {source}")

    if AUTO_REPLY:
        logger.warning("AUTO_REPLY is enabled but manual three-choice mode is required; skipping automatic post for %s", post.id)
    else:
        save_pending_replies(db, post.id, handle, post.text, replies)

    try:
        if telegram_already_sent(db, post.id):
            return False
        send_new_post(handle, post.text, post.url, suggested_replies=replies, post_id=post.id)
        record_activity(db, "telegram_sent", handle, post.id, f"Post notification sent to Telegram from {source}")
        return True
    except Exception:
        logger.exception("Failed to send Telegram notification for %s", post.id)
        record_activity(db, "error", handle, post.id, f"Failed to send Telegram notification from {source}")
        return False


def _process_handle(db, provider, handle: str, schedule_start: datetime, now: datetime) -> None:
    try:
        posts = provider.get_latest_posts(handle, limit=1)
    except Exception:
        logger.exception("Failed to fetch post for %s", handle)
        record_activity(db, "error", handle, None, "Failed to fetch latest post from X provider")
        return

    logger.info("Fetched %d latest post for %s", len(posts), handle)
    if not posts:
        logger.info("NO FEED | %s | no post returned", handle)
        return

    post = posts[0]
    if not _is_recent_for_schedule(post, schedule_start, now):
        logger.info("NO FEED | %s | latest post is outside schedule window: %s", handle, post.created_at)
        return

    _process_post(db, post, handle, source="monitored account")


def _run_discovery(db, provider, accounts: list[str], schedule_start: datetime, now: datetime) -> None:
    candidates = discover_posts(provider, accounts, max_posts=MAX_DISCOVERY_POSTS_PER_RUN)
    if not candidates:
        logger.info("Discovery found no qualifying non-monitored posts.")
        return

    used_authors: set[str] = set()
    sent = 0
    for post, topic, score in candidates:
        if not _is_recent_for_schedule(post, schedule_start, now):
            logger.info("NO DISCOVERY FEED | %s | outside schedule window: %s", post.username, post.created_at)
            continue

        author = post.username.lstrip("@").lower()
        if author in used_authors or post_seen(db, post.id):
            continue

        handle = f"@{post.username.lstrip('@')}"
        logger.info("DISCOVERY | %s | score=%d | %s", topic, score, handle)
        if _process_post(db, post, handle, source=f"discovery:{topic}"):
            record_activity(db, "discovery_processed", handle, post.id, f"Discovered reply opportunity from topic {topic} with score {score}")
            used_authors.add(author)
            sent += 1
            if sent >= MAX_DISCOVERY_POSTS_PER_RUN:
                break


def run_monitor_cycle() -> None:
    accounts = load_accounts()
    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    provider = get_x_provider()
    db = get_db()
    now = datetime.now(timezone.utc)
    schedule_start = _schedule_start(now)

    logger.info("Schedule window: %s → %s UTC", schedule_start.isoformat(), now.isoformat())
    _select_handles(accounts)
    handles = _select_handles(accounts)
    for handle in handles:
        _process_handle(db, provider, handle, schedule_start, now)

    _run_discovery(db, provider, accounts, schedule_start, now)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
    run_monitor_cycle()
