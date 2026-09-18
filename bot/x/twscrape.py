import asyncio
from typing import Any

from bot.config import TWITTERAPIS_CT0, TWITTERAPIS_X_AUTH_TOKEN
from bot.x.base import Post, XProvider


class TwscrapeProvider(XProvider):
    """Free X read provider using an authenticated X session via twscrape."""

    def __init__(self) -> None:
        if not TWITTERAPIS_X_AUTH_TOKEN or not TWITTERAPIS_CT0:
            raise ValueError(
                "Twscrape requires the existing TWITTERAPIS_X_AUTH_TOKEN and "
                "TWITTERAPIS_CT0 session cookies"
            )

    @staticmethod
    def _cookies() -> str:
        return (
            f"auth_token={TWITTERAPIS_X_AUTH_TOKEN}; "
            f"ct0={TWITTERAPIS_CT0}"
        )

    @staticmethod
    def _to_post(tweet: Any) -> Post | None:
        tweet_id = str(getattr(tweet, "id_str", "") or getattr(tweet, "id", "")).strip()
        text = str(getattr(tweet, "rawContent", "") or "").strip()
        user = getattr(tweet, "user", None)
        username = str(getattr(user, "username", "") or "").strip()

        if not tweet_id or not text or not username:
            return None

        if getattr(tweet, "retweetedTweet", None) is not None:
            return None

        if getattr(tweet, "inReplyToTweetId", None) is not None:
            return None

        created_at = getattr(tweet, "date", None)
        created_at_text = created_at.isoformat() if created_at is not None else None
        url = str(getattr(tweet, "url", "") or "").strip()
        if not url:
            url = f"https://x.com/{username}/status/{tweet_id}"

        return Post(
            id=tweet_id,
            text=text,
            username=username,
            created_at=created_at_text,
            url=url,
            raw=tweet.__dict__ if hasattr(tweet, "__dict__") else None,
        )

    async def _latest(self, handle: str, limit: int) -> list[Post]:
        from twscrape import API, gather

        api = API()
        await api.pool.add_account_cookies("xbot_session", self._cookies())

        username = handle.lstrip("@").strip()
        user = await api.user_by_login(username)
        if user is None:
            return []

        tweets = await gather(api.user_tweets(user.id, limit=max(limit, 20)))
        posts: list[Post] = []
        for tweet in tweets:
            post = self._to_post(tweet)
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    async def _search(self, query: str, limit: int) -> list[Post]:
        from twscrape import API, gather

        api = API()
        await api.pool.add_account_cookies("xbot_session", self._cookies())

        tweets = await gather(api.search(query, limit=max(limit, 20)))
        posts: list[Post] = []
        for tweet in tweets:
            post = self._to_post(tweet)
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        try:
            return asyncio.run(self._latest(handle, limit))
        except Exception as exc:
            raise RuntimeError(f"Twscrape provider failed: {exc}") from exc

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        try:
            return asyncio.run(self._search(query, limit))
        except Exception as exc:
            raise RuntimeError(f"Twscrape provider failed: {exc}") from exc

    def create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        raise RuntimeError(
            "TwscrapeProvider is read-only; reply publishing remains disabled"
        )
