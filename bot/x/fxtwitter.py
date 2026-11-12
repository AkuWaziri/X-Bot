import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            # FxTwitter documents HTTP/API 404 for a valid search with no matches.
            # Treat that as an empty result set instead of invoking the authenticated
            # twscrape fallback, which can fail independently with X 403s.
            if path == "/2/search" and exc.code == 404:
                logging.info(
                    "FXTWITTER SEARCH EMPTY | status=404 | query=%s | response=%s",
                    (params or {}).get("q", ""),
                    body[:240].replace("\\n", " "),
                )
                return {"code": 200, "results": [], "cursor": {}}
            if path.startswith("/2/profile/") and path.endswith("/statuses") and exc.code == 404:
                # FxTwitter documents 404 for both missing accounts and empty /
                # unavailable timelines. Neither should fail the whole feed cycle.
                logging.info(
                    "FXTWITTER TIMELINE EMPTY_OR_UNAVAILABLE | status=404 | path=%s | response=%s",
                    path,
                    body[:240].replace("\\n", " "),
                )
                return {"code": 200, "results": [], "cursor": {}}
            raise RuntimeError(f"FxTwitter provider request failed: HTTP {exc.code}: {body[:500]}") from exc
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
        verification = author.get("verification") or {}
        if not isinstance(verification, dict):
            verification = {}
        verification_type = str(
            verification.get("type")
            or author.get("verification_type")
            or author.get("verified_type")
            or ""
        ).strip().lower()

        # FxTwitter responses have used more than one verification shape over
        # time: nested verification.verified, author.verified, and explicit
        # blue-check/type fields. Normalize those forms before strict filtering.
        verified_values = (
            verification.get("verified"),
            author.get("verified"),
            author.get("is_verified"),
            author.get("blue_verified"),
            author.get("is_blue_verified"),
        )
        verified = any(value is True for value in verified_values)
        blue_types = {"blue", "individual", "blue_verified", "blue verified"}
        non_blue_types = {
            "business", "government", "gold", "gray", "grey",
            "organization", "unverified", "none",
        }
        if verification_type in non_blue_types:
            blue_verified = False
        elif verification_type in blue_types:
            blue_verified = True
        else:
            # Legacy generic verified signals are accepted only when the API
            # does not identify a different badge category.
            blue_verified = verified
        raw["author"] = {
            **author,
            "is_verified": verified or verification_type in blue_types,
            "is_blue_verified": blue_verified,
            "verification_type": verification_type,
        }

        return Post(
            id=tweet_id,
            text=text,
            username=username,
            created_at=(
                str(item.get("created_at") or "").strip()
                or (
                    datetime.fromtimestamp(float(item["created_timestamp"]), tz=timezone.utc).isoformat()
                    if item.get("created_timestamp") is not None
                    else None
                )
            ),
            url=str(item.get("url") or f"https://x.com/{username}/status/{tweet_id}"),
            raw=raw,
        )

    def _get_paginated_posts(
        self,
        path: str,
        params: dict[str, Any],
        limit: int,
    ) -> list[Post]:
        """Read multiple FxTwitter pages because count is a page size, not a total."""
        target = min(max(int(limit), 1), 100)
        posts: list[Post] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while len(posts) < target:
            request_params = {
                **params,
                "count": min(target - len(posts), 100),
            }
            if cursor:
                request_params["cursor"] = cursor

            data = self._request(path, request_params)
            items = data.get("results") or []
            for item in items:
                post = self._to_post(item)
                if post is not None:
                    posts.append(post)
                    if len(posts) >= target:
                        break

            next_cursor = str((data.get("cursor") or {}).get("bottom") or "").strip()
            if not items or not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return posts[:target]

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        username = handle.lstrip("@").strip()
        if not username:
            return []
        return self._get_paginated_posts(
            f"/2/profile/{urllib.parse.quote(username, safe='')}/statuses",
            {},
            limit,
        )

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        if not query.strip():
            return []
        return self._get_paginated_posts(
            "/2/search",
            {"q": query, "feed": "latest"},
            limit,
        )

    def create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        # Reading is decoupled from the X web session. Only publishing uses
        # the existing authenticated session.
        from bot.x.twscrape import TwscrapeProvider

        return TwscrapeProvider().create_reply(text, reply_to)
