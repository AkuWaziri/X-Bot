import logging
import random
from datetime import datetime, timezone

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


# Discovery is intentionally smaller than the monitored-account pool.
MAX_DISCOVERY_POSTS_PER_RUN = 3


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


def _used_handles_today(db) -> set[str]:
    """Return monitored handles that successfully completed a reply cycle today (UTC)."""
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        db.table("activity_log")
        .select("handle")
        .eq("event_type", "handle_replied")
        .gte("created_at", f"{today}T00:00:00+00:00")
        .lt("created_at", f"{today}T23:59:59.999999+00:00")
        .execute()
    )
    return {row["handle"].lower() for row in (result.data or []) if row.get("handle")}


def _select_handles(db, accounts: list[str]) -> list[str]:
    """Randomly select 5-10 monitored handles that have not been used successfully today."""
    used = _used_handles_today(db)
    eligible = [handle for handle in accounts if handle.lower() not in used]

    if not eligible:
        logger.info("All monitored handles have been used today.")
        return []

    random.shuffle(eligible)
    count = min(len(eligible), random.randint(5, 10))
    selected = eligible[:count]

    logger.info(
        "Selected %d monitored handles for this schedule: %s",
        len(selected),
        ", ".join(selected),
    )
    return selected


def _process_post(db, post, handle: str, *, source: str) -> bool:
    """Generate three replies and deliver the post/options to Telegram."""
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
        record_activity(
            db,
            "error",
            handle,
            post.id,
            "Failed to generate reply suggestions",
        )

    if replies and not validate_replies(replies):
        logger.warning("Reply validation failed for %s: %r", post.id, replies)
        replies = None

    if not replies:
        return False

    record_activity(
        db,
        "replies_suggested",
        handle,
        post.id,
        f"Three reply suggestions generated from {source}",
    )

    if AUTO_REPLY:
        logger.warning(
            "AUTO_REPLY is enabled but manual three-choice mode is required; skipping automatic post for %s",
            post.id,
        )
    else:
        save_pending_replies(db, post.id, handle, post.text, replies)

    try:
        if telegram_already_sent(db, post.id):
            return False

        send_new_post(
            handle,
            post.text,
            post.url,
            suggested_replies=replies,
            post_id=post.id,
        )
        record_activity(
            db,
            "telegram_sent",
            handle,
            post.id,
            f"Post notification sent to Telegram from {source}",
        )
        return True
    except Exception:
        logger.exception("Failed to send Telegram notification for %s", post.id)
        record_activity(
            db,
            "error",
            handle,
            post.id,
            f"Failed to send Telegram notification from {source}",
        )
        return False


def _process_handle(db, provider, handle: str) -> None:
    try:
        posts = provider.get_latest_posts(handle, limit=1)
    except Exception:
        logger.exception("Failed to fetch post for %s", handle)
        record_activity(db, "error", handle, None, "Failed to fetch latest post from X provider")
        return

    logger.info("Fetched %d latest post for %s", len(posts), handle)

    if not posts:
        logger.info("No post returned for %s", handle)
        return

    if _process_post(db, posts[0], handle, source="monitored account"):
        # Only successful monitored cycles count toward the daily rotation.
        record_activity(
            db,
            "handle_replied",
            handle,
            posts[0].id,
            "Monitored handle used for today's randomized reply rotation",
        )


def _run_discovery(db, provider, accounts: list[str]) -> None:
    """Find up to three reply opportunities outside the monitored handle list."""
    candidates = discover_posts(
        provider,
        accounts,
        max_posts=MAX_DISCOVERY_POSTS_PER_RUN,
    )

    if not candidates:
        logger.info("Discovery found no qualifying non-monitored posts.")
        return

    logger.info("Discovery found %d qualifying non-monitored posts.", len(candidates))

    used_authors: set[str] = set()
    sent = 0

    for post, topic, score in candidates:
        author = post.username.lstrip("@").lower()
        if author in used_authors:
            continue
        if post_seen(db, post.id):
            continue

        handle = f"@{post.username.lstrip('@')}"
        logger.info(
            "DISCOVERY | %s | score=%d | %s",
            topic,
            score,
            handle,
        )

        if _process_post(db, post, handle, source=f"discovery:{topic}"):
            record_activity(
                db,
                "discovery_processed",
                handle,
                post.id,
                f"Discovered reply opportunity from topic {topic} with score {score}",
            )
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

    # Core coverage: 5-10 deliberately monitored accounts.
    handles = _select_handles(db, accounts)
    for handle in handles:
        _process_handle(db, provider, handle)

    # Opportunity coverage: up to 3 strong posts from accounts we did not add.
    _run_discovery(db, provider, accounts)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
