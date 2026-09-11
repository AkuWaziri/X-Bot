from bot.config import TWITTERAPIS_API_KEY, X_PROVIDER_MODE
from bot.x.base import XProvider
from bot.x.mock import MockXProvider
from bot.x.twitterapis import TwitterAPIsProvider


def get_x_provider() -> XProvider:
    """Return the configured X data provider."""
    if X_PROVIDER_MODE == "mock":
        return MockXProvider()
    if X_PROVIDER_MODE != "twitterapis":
        raise ValueError(f"Unsupported X_PROVIDER_MODE: {X_PROVIDER_MODE}")
    return TwitterAPIsProvider(TWITTERAPIS_API_KEY)
