import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from bot.x.base import Post, XProvider

logger = logging.getLogger(__name__)


class _ResultLinks(HTMLParser):
    """Collect links from DuckDuckGo's public HTML search results."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            values = dict(attrs)
            href = values.get("href", "")
            if href:
                self._href = href
                self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None
            self._text = []


def _syndication_token(tweet_id: str) -> str:
    """Generate X's public embed token using the same base-36 formula as react-tweet."""
    value = (int(tweet_id) / 1e15) * 3.141592653589793
    if value == 0:
        return "0"
    whole = int(value)
    fraction = value - whole
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    digits = ""
    while whole:
        whole, remainder = divmod(whole, 36)
        digits = alphabet[remainder] + digits
    if not digits:
        digits = "0"
    fractional = []
    for _ in range(16):
        fraction *= 36
        digit = int(fraction)
        fractional.append(alphabet[digit])
        fraction -= digit
        if fraction < 1e-12:
            break
    return (digits + ("." + "".join(fractional) if fractional else "")).replace("0", "").replace(".", "") or "0"


class FreeWebSearchProvider(XProvider):
    """No-key discovery: DuckDuckGo indexes X status URLs; X syndication hydrates posts.

    This is indexed web search, not X's live search. Very recent posts may not
    appear until search engines index them. No paid API or X login is required.
    """

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"
    TIMEOUT_SECONDS = 15
    MAX_HYDRATE_PER_QUERY = 12

    @staticmethod
    def _request(url: str, *, data: bytes | None = None) -> str:
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/json,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=FreeWebSearchProvider.TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"free web search HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"free web search request failed: {exc}") from exc

    @classmethod
    def _search_ids(cls, query: str, limit: int) -> list[tuple[str, str]]:
        search_query = f"site:x.com {query}"
        body = urllib.parse.urlencode({"q": search_query, "kl": "us-en"}).encode()
        page = cls._request(cls.SEARCH_URL, data=body)
        parser = _ResultLinks()
        parser.feed(page)
        found = {}
        for href, title in parser.links:
            href = html.unescape(href)
            parsed = urllib.parse.urlparse(href)
            if parsed.netloc.endswith("duckduckgo.com"):
                target = urllib.parse.parse_qs(parsed.query).get("uddg")
                if target:
                    href = urllib.parse.unquote(target[0])
            match = re.search(
                r"(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/status/(\d{5,25})",
                href,
                re.IGNORECASE,
            )
            if match:
                username, tweet_id = match.groups()
                found.setdefault(tweet_id, (username, title))
            if len(found) >= max(limit, cls.MAX_HYDRATE_PER_QUERY):
                break
        if not found and any(term in page.lower() for term in ("captcha", "unusual traffic", "verify you are human")):
            raise RuntimeError("DuckDuckGo search returned a bot challenge")
        return list(found.items())

    @classmethod
    def _hydrate(cls, tweet_id: str) -> Post | None:
        token = _syndication_token(tweet_id)
        url = f"{cls.SYNDICATION_URL}?{urllib.parse.urlencode({'id': tweet_id, 'lang': 'en', 'token': token})}"
        body = cls._request(url)
        try:
            raw = json.loads(body)
        except ValueError as exc:
            raise RuntimeError(f"X syndication returned invalid JSON for {tweet_id}") from exc
        if not isinstance(raw, dict) or raw.get("__typename") != "Tweet":
            return None
        user = raw.get("user") or {}
        username = str(user.get("screen_name") or "").strip()
        text = html.unescape(str(raw.get("text") or "")).strip()
        if not username or not text:
            return None
        raw["author"] = {
            **user,
            "is_blue_verified": user.get("is_blue_verified") is True,
            "verified_type": user.get("verified_type") or user.get("verification_type"),
        }
        return Post(
            id=str(raw.get("id_str") or tweet_id),
            text=text,
            username=username,
            created_at=str(raw.get("created_at") or "") or None,
            url=f"https://x.com/{username}/status/{tweet_id}",
            raw=raw,
        )

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        hits = self._search_ids(query, min(limit, self.MAX_HYDRATE_PER_QUERY))
        posts = []
        for tweet_id, (username, _title) in hits:
            try:
                post = self._hydrate(tweet_id)
            except Exception as exc:
                logger.warning("FREE WEB SEARCH HYDRATION FAILED | post_id=%s | error=%s", tweet_id, str(exc)[:180])
                continue
            if post is not None:
                posts.append(post)
            if len(posts) >= limit:
                break
        logger.info("FREE WEB SEARCH RESULT | query=%s | indexed_hits=%d | hydrated=%d", query[:80], len(hits), len(posts))
        return posts

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        return self.search_posts(f"from:{handle.lstrip('@')}", limit=limit)

    def create_reply(self, text: str, reply_to: str):
        raise NotImplementedError("Free web search provider is read-only")
