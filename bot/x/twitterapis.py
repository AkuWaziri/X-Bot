import json
import urllib.error
import urllib.parse
import urllib.request

from bot.x.base import Post, XProvider


BASE_URL = "https://api.twitterapis.com/twitter/user/tweets"


class TwitterAPIsProvider(XProvider):
    """TwitterAPIs implementation for public user timelines."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("TWITTERAPIS_API_KEY is not configured")
        self.api_key = api_key

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        username = handle.lstrip("@").strip()
        params = urllib.parse.urlencode({"username": username})
        request = urllib.request.Request(
            f"{BASE_URL}?{params}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"TwitterAPIs HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"TwitterAPIs connection error: {exc.reason}") from exc

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
