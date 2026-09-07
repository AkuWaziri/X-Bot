import logging

from bot.accounts import load_accounts
from bot.db import get_db, post_seen, record_activity, save_post
from bot.x.provider import get_x_provider

logger = logging.getLogger(__name__)


def run_monitor_cycle() -> None:
    """Fetch posts and persist new posts/activity in Supabase."""
    accounts = load_accounts()

    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    provider = get_x_provider()
    db = get_db()

    for handle in accounts:
        try:
            posts = provider.get_latest_posts(handle, limit=20)
        except Exception:
            logger.exception("Failed to fetch posts for %s", handle)
            record_activity(db, "error", handle, None, "Failed to fetch posts from X provider")
            continue

        logger.info("Fetched %d original posts for %s", len(posts), handle)

        for post in posts:
            if post_seen(db, post.id):
                logger.info("SEEN | %s | %s", handle, post.id)
                continue

            save_post(db, post)
            record_activity(
                db,
                "new_post",
                handle,
                post.id,
                post.text.replace("\n", " "),
            )
            logger.info("NEW | %s | %s | %s", handle, post.id, post.text.replace("\n", " "))


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
