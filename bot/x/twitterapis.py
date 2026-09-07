import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from bot.config import TWITTERAPIS_CT0, TWITTERAPIS_X_AUTH_TOKEN
from bot.x.base import Post, XProvider


BASE_URL = "https://api.twitterapis.com/twitter"


class TwitterAPIsProvider(XProvider):
    """TwitterAPIs implementation for public reads and X write actions."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("TWITTERAPIS_API_KEY is not configured")
        self.api_key = api_key

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if TWITTERAPIS_X_AUTH_TOKEN:
            headers["x-auth-token"] = TWITTERAPIS_X_AUTH_TOKEN
        if TWITTERAPIS_CT0:
            headers["x-ct0"] = TWITTERAPIS_CT0

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"TwitterAPIs HTTP {exc.code}: {response_body[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"TwitterAPIs connection error: {exc.reason}"
            ) from exc

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        username = handle.lstrip("@").strip()
        payload = self._request("GET", "user/tweets", params={"username": username})

        tweets = payload.get("tweets", [])
        posts: list[Post] = []

        for tweet in tweets[:limit]:
            if tweet.get("is_retweet") or tweet.get("is_reply"):
                continue

            tweet_id = str(tweet.get("id", ""))
            text = str(tweet.get("text", "")).strip()
            if not tweet_id or not text:
                continue

            post_url = tweet.get("url")
            if not post_url:
                post_url = f"https://x.com/{username}/status/{tweet_id}"

            posts.append(
                Post(
                    id=tweet_id,
                    text=text,
                    username=username,
                    created_at=tweet.get("created_at"),
                    url=post_url,
                    raw=tweet,
                )
            )

        return posts

    def create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        """Publish a reply using inline credentials when supplied, otherwise the registered session."""
        result = self._request(
            "POST",
            "tweet/create",
            body={"text": text, "reply_to": str(reply_to)},
        )

        if not result.get("ok"):
            raise RuntimeError(
                f"TwitterAPIs reply failed: {result.get('error', 'unknown_error')} - "
                f"{result.get('message', 'unknown error')}"
            )

        return result
