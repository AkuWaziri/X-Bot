import logging

from bot.accounts import load_accounts

logger = logging.getLogger(__name__)


def run_monitor_cycle() -> None:
    """Run one monitoring cycle using the configured account list."""
    accounts = load_accounts()

    if not accounts:
        logger.info("No monitored X accounts configured.")
        return

    for handle in accounts:
        logger.info("Monitoring %s", handle)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    run_monitor_cycle()
