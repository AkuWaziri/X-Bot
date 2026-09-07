import logging

from bot.accounts import load_accounts
from bot.x.provider import get_x_provider

logger = logging.getLogger(__name__)


def run_monitor_cycle() -> None:
    """Fetch the latest public posts for every configured account."""
    accounts = load_accounts()

    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    provider = get_x_provider()

    for handle in accounts:
        try:
            posts = provider.get_latest_posts(handle, limit=20)
        except Exception:
            logger.exception("Failed to fetch posts for %s", handle)
            continue

        logger.info("Fetched %d original posts for %s", len(posts), handle)
        for post in posts:
            logger.info(
                "POST | %s | %s | %s",
                post.username,
                post.id,
                post.text.replace("\n", " "),
            )


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
