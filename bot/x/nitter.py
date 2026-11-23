import logging
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from bot.x.base import Post, XProvider
from bot.x.websearch import FreeWebSearchProvider

logger = logging.getLogger(__name__)


class _NitterLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.href = href
                self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(" ".join(self.text).split())))
            self.href = None
            self.text = []


class NitterSearchProvider(XProvider):
    """Read-only public Nitter search with X syndication hydration.

    Public mirrors are community-operated and can disappear or rate-limit.
    Each mirror is isolated so an outage falls through to the next one.
    """

    INSTANCES = (
        "https://nitter.mie.foundation",
        "https://nitter.mizuki.st",
    )
    TIMEOUT_SECONDS = 8

    @classmethod
    def _request(cls, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X-Bot; public-post-discovery)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Nitter HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"Nitter request failed: {exc}") from exc

    @classmethod
    def _extract_ids(cls, page: str, base_url: str) -> list[tuple[str, str]]:
        parser = _NitterLinks()
        parser.feed(page)
        found = {}
        for href, title in parser.links:
            absolute = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlparse(absolute)
            match = __import__("re").search(
                r"/([A-Za-z0-9_]{1,15})/status/(\d{5,25})",
                parsed.path,
            )
            if match:
                username, post_id = match.groups()
                found.setdefault(post_id, (username, title))
        return list(found.items())

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        last_error = None
        for instance in self.INSTANCES:
            try:
                url = f"{instance}/search?{urllib.parse.urlencode({'f': 'tweets', 'q': query})}"
                page = self._request(url)
                hits = self._extract_ids(page, instance)[:max(1, limit)]
                posts = []
                for post_id, (_username, _title) in hits:
                    try:
                        post = FreeWebSearchProvider._hydrate(post_id)
                    except Exception as exc:
                        logger.warning(
                            "NITTER HYDRATION FAILED | instance=%s | post_id=%s | error=%s",
                            instance, post_id, str(exc)[:160],
                        )
                        continue
                    if post is not None:
                        posts.append(post)
                    if len(posts) >= limit:
                        break
                logger.info(
                    "NITTER SEARCH RESULT | instance=%s | indexed_hits=%d | hydrated=%d",
                    instance, len(hits), len(posts),
                )
                if posts:
                    return posts
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "NITTER SEARCH FAILED | instance=%s | error=%s",
                    instance, str(exc)[:200],
                )
        if last_error is not None:
            raise RuntimeError(f"All public Nitter mirrors failed: {last_error}")
        return []

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        return self.search_posts(f"from:{handle.lstrip('@')}", limit)

    def create_reply(self, text: str, reply_to: str):
        raise NotImplementedError("Nitter search provider is read-only")
