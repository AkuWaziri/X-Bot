import logging

from bot.accounts import load_accounts
from bot.db import (
    get_db,
    post_seen,
    record_activity,
    save_pending_reply,
    save_post,
)
from bot.reply_engine import analyze_post, validate_reply
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


def run_monitor_cycle() -> None:
    accounts = load_accounts()
    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    provider = get_x_provider()
    db = get_db()

    for handle in accounts:
        try:
            posts = provider.get_latest_posts(handle, limit=1)
        except Exception:
            logger.exception("Failed to fetch post for %s", handle)
            record_activity(db, "error", handle, None, "Failed to fetch latest post from X provider")
            continue

        logger.info("Fetched %d latest post for %s", len(posts), handle)

        if not posts:
            logger.info("No post returned for %s", handle)
            continue

        post = posts[0]

        if post_seen(db, post.id):
            logger.info("SEEN | %s | %s", handle, post.id)
            continue

        save_post(db, post)
        record_activity(db, "new_post", handle, post.id, post.text.replace("\n", " "))

        analysis = analyze_post(post.text)
        suggested_reply = analysis.suggested_reply

        if suggested_reply and not validate_reply(suggested_reply):
            logger.warning(
                "Reply length validation failed for %s: %r (%d chars)",
                post.id,
                suggested_reply,
                len(suggested_reply),
            )
            suggested_reply = None
            analysis = analysis.__class__(analysis.score, None, "Reply failed length validation")

        if suggested_reply:
            save_pending_reply(
                db,
                post.id,
                handle,
                post.text,
                suggested_reply,
            )
            record_activity(
                db,
                "reply_suggested",
                handle,
                post.id,
                f"Reply suggestion generated: {suggested_reply}",
            )

        try:
            if telegram_already_sent(db, post.id):
                continue

            send_new_post(
                handle,
                post.text,
                post.url,
                reply_score=analysis.score,
                suggested_reply=suggested_reply,
                reply_reason=analysis.reason,
                post_id=post.id,
            )
            record_activity(
                db,
                "telegram_sent",
                handle,
                post.id,
                "Latest post notification sent to Telegram",
            )
        except Exception:
            logger.exception("Failed to send Telegram notification for %s", post.id)
            record_activity(
                db,
                "error",
                handle,
                post.id,
                "Failed to send latest post notification to Telegram",
            )


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
