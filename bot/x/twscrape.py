import asyncio
import threading
from typing import Any

from bot.config import TWITTERAPIS_CT0, TWITTERAPIS_X_AUTH_TOKEN
from bot.x.base import Post, XProvider



# twscrape persists its authenticated account in a shared SQLite pool. Avoid
# concurrent search calls racing while adding/reusing the same session.
_SEARCH_LOCK = threading.Lock()
_SEARCH_LOCK_WAIT_SECONDS = 35


class TwscrapeBlockedError(RuntimeError):
    """Raised when X blocks the twscrape session and the cycle must stop immediately."""

class XReplyTargetUnavailableError(RuntimeError):
    """Raised when X permanently disallows replying to a specific target post."""


class TwscrapeProvider(XProvider):
    """Free X read provider using an authenticated X session via twscrape."""

    REQUEST_TIMEOUT_SECONDS = 20

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

    async def _preflight(self, handle: str) -> None:
        """Check X directly before twscrape can lock the only account and wait."""
        from curl_cffi import requests as curl_requests

        username = handle.lstrip("@").strip()
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": self._cookies(),
        }
        with curl_requests.Session(impersonate="chrome") as client:
            response = client.get(
                f"https://x.com/{username}",
                headers=headers,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
        if response.status_code in {401, 403, 429}:
            raise TwscrapeBlockedError(
                f"X preflight blocked the twscrape session: HTTP {response.status_code}"
            )

    @staticmethod
    def _to_post(tweet: Any, *, include_replies: bool = False) -> Post | None:
        tweet_id = str(getattr(tweet, "id_str", "") or getattr(tweet, "id", "")).strip()
        text = str(getattr(tweet, "rawContent", "") or "").strip()
        user = getattr(tweet, "user", None)
        username = str(getattr(user, "username", "") or "").strip()

        if not tweet_id or not text or not username:
            return None

        if getattr(tweet, "retweetedTweet", None) is not None:
            return None

        if not include_replies and getattr(tweet, "inReplyToTweetId", None) is not None:
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

        await self._preflight(handle)

        api = API()
        await api.pool.add_account_cookies("xbot_session", self._cookies())

        username = handle.lstrip("@").strip()
        user = await asyncio.wait_for(
            api.user_by_login(username), timeout=self.REQUEST_TIMEOUT_SECONDS
        )
        if user is None:
            return []

        tweets = await asyncio.wait_for(
            gather(api.user_tweets(user.id, limit=max(limit, 20))),
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
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
        # Account-pool setup can also stall on SQLite contention, so bound it
        # separately rather than timing only the network search.
        await asyncio.wait_for(
            api.pool.add_account_cookies("xbot_session", self._cookies()),
            timeout=10,
        )

        tweets = await asyncio.wait_for(
            gather(api.search(query, limit=max(limit, 20))),
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        posts: list[Post] = []
        for tweet in tweets:
            post = self._to_post(tweet)
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    @staticmethod
    def _is_blocked_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "403" in message or "forbidden" in message or "cloudflare" in message

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        try:
            return asyncio.run(self._latest(handle, limit))
        except Exception as exc:
            if self._is_blocked_error(exc):
                raise TwscrapeBlockedError(
                    f"X blocked the twscrape session (403/Cloudflare): {exc}"
                ) from exc
            raise RuntimeError(f"Twscrape provider failed: {exc}") from exc

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        acquired = _SEARCH_LOCK.acquire(timeout=_SEARCH_LOCK_WAIT_SECONDS)
        if not acquired:
            raise RuntimeError(
                "Another authenticated X search is still using the session; retry shortly"
            )
        try:
            return asyncio.run(self._search(query, limit))
        except Exception as exc:
            raise RuntimeError(f"Twscrape provider failed: {exc}") from exc
        finally:
            _SEARCH_LOCK.release()

    async def _create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        from curl_cffi import requests as curl_requests
        from twscrape.account import TOKEN
        from twscrape.api import GQL_FEATURES
        from twscrape.xclid import XClIdGen

        query_id = "H-t2v_HvFR07ZBP9aOeKoA"
        payload = {
            "variables": {
                "tweet_text": text,
                "dark_request": False,
                "reply": {
                    "in_reply_to_tweet_id": str(reply_to),
                    "exclude_reply_user_ids": [],
                },
                "media": {
                    "media_entities": [],
                    "possibly_sensitive": False,
                },
                "semantic_annotation_ids": [],
                "disallowed_reply_options": None,
                "semantic_annotation_options": {"source": "Unknown"},
            },
            "features": GQL_FEATURES,
            "queryId": query_id,
        }
        transaction_id = await XClIdGen.create(cookies={
            "auth_token": TWITTERAPIS_X_AUTH_TOKEN,
            "ct0": TWITTERAPIS_CT0,
        })
        headers = {
            "Authorization": TOKEN,
            "x-client-transaction-id": transaction_id.calc(
                "POST",
                f"/i/api/graphql/{query_id}/CreateTweet",
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "X-CSRF-Token": TWITTERAPIS_CT0,
            "X-Twitter-Auth-Type": "OAuth2Session",
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Client-Language": "en",
            "Origin": "https://x.com",
            "Referer": "https://x.com/home",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Cookie": self._cookies(),
        }

        with curl_requests.Session(impersonate="chrome") as client:
            response = client.post(
                f"https://x.com/i/api/graphql/{query_id}/CreateTweet",
                headers=headers,
                json=payload,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )

        if response.status_code in {401, 403, 429}:
            raise TwscrapeBlockedError(
                f"X reply publishing blocked: HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"X reply publishing failed: HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )
        reply_id = str(result.get("rest_id") or "").strip()
        if not reply_id:
            errors = data.get("errors") or []
            for error in errors:
                code = str(error.get("code") or "")
                message = str(error.get("message") or "")
                if code == "461" or "outdated tweet" in message.lower():
                    raise XReplyTargetUnavailableError(
                        "X does not permit replies to this outdated post (461). "
                        "This target cannot be replied to; choose a newer post."
                    )
            raise RuntimeError(
                "X reply publishing returned no tweet id: "
                f"{data}; errors={errors}"
            )

        return {"id": reply_id, "tweet_id": reply_id}

    def create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        return asyncio.run(self._create_reply(text, reply_to))
