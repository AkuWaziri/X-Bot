from bot.config import TWITTERAPIS_API_KEY
from bot.x.base import XProvider
from bot.x.twitterapis import TwitterAPIsProvider


def get_x_provider() -> XProvider:
    """Return the configured X data provider."""
    return TwitterAPIsProvider(TWITTERAPIS_API_KEY)
