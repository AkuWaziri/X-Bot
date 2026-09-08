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
from bot.reply_engine import generate_replies, validate_replies
from bot.telegram import send_new_post
from bot.x.provider import get_x_provider

logger = logging.getLogger(__name__)


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
    """Return handles that successfully completed a reply cycle today (UTC)."""
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        db.table("activity_log")
        .select("handle")
        .eq("event_type", "handle_replied")
        .gte("created_at", f"{today}T00:00:00+00:00")
        .lt("created_at", f"{today}T00:00:00+00:00".replace("T00:00:00+00:00", "T23:59:59.999999+00:00"))
        .execute()
    )
    return {row["handle"].lower() for row in (result.data or []) if row.get("handle")}


def _select_handle(db, accounts: list[str]) -> str | None:
    """Randomly select one handle not yet used successfully today."""
    used = _used_handles_today(db)
    eligible = [handle for handle in accounts if handle.lower() not in used]
    if not eligible:
        logger.info("All monitored handles have been used today.")
        return None
    random.shuffle(eligible)
    return eligible[0]


def run_monitor_cycle() -> None:
    accounts = load_accounts()
    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    provider = get_x_provider()
    db = get_db()

    handle = _select_handle(db, accounts)
    if not handle:
        return

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

    post = posts[0]

    if post_seen(db, post.id) and telegram_already_sent(db, post.id):
        logger.info("SEEN | %s | %s", handle, post.id)
        return

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
        return

    record_activity(
        db,
        "replies_suggested",
        handle,
        post.id,
        "Three reply suggestions generated",
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
            return

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
            "Latest post notification sent to Telegram",
        )

        # Only mark the handle as used after the full reply cycle succeeds.
        record_activity(
            db,
            "handle_replied",
            handle,
            post.id,
            "Handle used for today's randomized reply rotation",
        )
    except Exception:
        logger.exception("Failed to send Telegram notification for %s", post.id)
        record_activity(
            db,
            "error",
            handle,
            post.id,
            "Failed to send latest post notification for randomized rotation",
        )


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
