import logging

from bot.accounts import load_accounts
from bot.analyzer import select_best_post
from bot.db import get_db, post_seen, record_activity, save_post
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
            posts = provider.get_latest_posts(handle, limit=2)
        except Exception:
            logger.exception("Failed to fetch posts for %s", handle)
            record_activity(db, "error", handle, None, "Failed to fetch posts from X provider")
            continue

        logger.info("Fetched %d latest original posts for %s", len(posts), handle)
        unseen_posts = []

        for post in posts:
            if post_seen(db, post.id):
                logger.info("SEEN | %s | %s", handle, post.id)
                continue
            save_post(db, post)
            record_activity(db, "new_post", handle, post.id, post.text.replace("\n", " "))
            unseen_posts.append(post)

        if not unseen_posts:
            continue

        analysis = select_best_post(unseen_posts)
        if analysis is None:
            record_activity(
                db,
                "skipped",
                handle,
                None,
                "No qualifying reply opportunity among the two latest posts",
            )
            continue

        selected = analysis.post

        try:
            if telegram_already_sent(db, selected.id):
                continue
            send_new_post(handle, selected.text, selected.url)
            record_activity(
                db,
                "telegram_sent",
                handle,
                selected.id,
                "Qualifying post notification sent to Telegram",
            )
        except Exception:
            logger.exception("Failed to send Telegram notification for %s", selected.id)
            record_activity(
                db,
                "error",
                handle,
                selected.id,
                "Failed to send qualifying post notification to Telegram",
            )


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
