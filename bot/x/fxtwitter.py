import urllib.parse
import urllib.request
from typing import Any

from bot.x.base import Post, XProvider


class FxTwitterProvider(XProvider):
    """Read-only X provider using the public FxTwitter API."""

    BASE_URL = "https://api.fxtwitter.com"
    REQUEST_TIMEOUT_SECONDS = 20

    @staticmethod
    def _request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(params or {})
        url = f"{FxTwitterProvider.BASE_URL}{path}"
        if query:
            url = f"{url}?{query}"

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "X-Bot/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=FxTwitterProvider.REQUEST_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", 200)
                body = response.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"FxTwitter provider request failed: {exc}") from exc

        if status >= 400:
            raise RuntimeError(f"FxTwitter provider HTTP {status}: {body[:500]}")

        try:
            data = __import__("json").loads(body)
        except ValueError as exc:
            raise RuntimeError(f"FxTwitter provider returned invalid JSON: {body[:500]}") from exc

        code = data.get("code")
        if code is not None and int(code) >= 400:
            raise RuntimeError(f"FxTwitter provider API error {code}: {data}")

        return data

    @staticmethod
    def _to_post(item: dict[str, Any]) -> Post | None:
        if item.get("type") != "status":
            return None

        tweet_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        author = item.get("author") or {}
        username = str(author.get("screen_name") or "").strip()

        if not tweet_id or not text or not username:
            return None

        # FxTwitter exposes the original post/reply state in the status object.
        # Keep the raw response so discovery can inspect engagement and verification.
        raw = dict(item)
        raw["author"] = {
            **author,
            "is_verified": bool((author.get("verification") or {}).get("verified")),
            "is_blue_verified": bool((author.get("verification") or {}).get("verified")),
        }

        return Post(
            id=tweet_id,
            text=text,
            username=username,
            created_at=str(item.get("created_at") or "").strip() or None,
            url=str(item.get("url") or f"https://x.com/{username}/status/{tweet_id}"),
            raw=raw,
        )

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        username = handle.lstrip("@").strip()
        if not username:
            return []

        data = self._request(
            f"/2/profile/{urllib.parse.quote(username, safe='')}/statuses",
            {"count": min(max(limit, 1), 100)},
        )

        posts: list[Post] = []
        for item in data.get("results") or []:
            post = self._to_post(item)
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        if not query.strip():
            return []

        data = self._request(
            "/2/search",
            {
                "q": query,
                "feed": "latest",
                "count": min(max(limit, 1), 100),
            },
        )

        posts: list[Post] = []
        for item in data.get("results") or []:
            post = self._to_post(item)
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        # Reading is decoupled from the X web session. Only publishing uses
        # the existing authenticated session.
        from bot.x.twscrape import TwscrapeProvider

        return TwscrapeProvider().create_reply(text, reply_to)
