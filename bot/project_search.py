from datetime import datetime, timedelta, timezone
import logging
import re

from bot.x.base import Post
from bot.x.provider import get_x_provider


HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
MAX_PROJECT_RESULTS = 35
SEARCH_WINDOW_MINUTES = 180


def normalize_handle(value: str) -> str:
    handle = value.strip()
    if handle.startswith("https://x.com/") or handle.startswith("https://twitter.com/"):
        handle = handle.rstrip("/").split("/")[-1]
    handle = handle.lstrip("@")
    if not HANDLE_RE.fullmatch(handle):
        raise ValueError("Send one valid X handle, for example: /project primus_labs")
    return handle


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _search_queries(handle: str) -> tuple[str, str, str]:
    # Search authored posts, direct mentions, and posts discussing the project name.
    return (f"from:{handle}", f"@{handle}", f'"{handle}"')


def _is_reply_post(post: Post) -> bool:
    """Return True when provider metadata identifies this status as a reply."""
    raw = post.raw or {}
    reply_fields = (
        "inReplyToTweetId",
        "in_reply_to_tweet_id",
        "in_reply_to_status_id",
        "inReplyToStatusId",
        "reply_to_id",
        "reply_to",
    )
    for field in reply_fields:
        value = raw.get(field)
        if value not in (None, "", 0, False, [], {}):
            return True

    # Some providers nest reply metadata in the legacy tweet result object.
    legacy = raw.get("legacy")
    if isinstance(legacy, dict):
        for field in ("in_reply_to_status_id_str", "in_reply_to_status_id"):
            value = legacy.get(field)
            if value not in (None, "", 0, False):
                return True
    return False


def _has_recent_post(posts: list[Post], cutoff: datetime, now_utc: datetime) -> bool:
    for post in posts:
        created = _parse_created_at(post.created_at)
        if created is not None and cutoff <= created <= now_utc and post.text.strip() and not _is_reply_post(post):
            return True
    return False


def _search_with_provider(provider, handle: str, limit: int) -> tuple[list[Post], bool]:
    collected: list[Post] = []
    had_success = False
    for query in _search_queries(handle):
        try:
            collected.extend(provider.search_posts(query, limit=min(max(limit, 1), 100)))
            had_success = True
        except Exception as exc:
            logging.warning(
                "PROJECT SEARCH PROVIDER ERROR | provider=%s | query=%s | error=%s",
                provider.__class__.__name__,
                query,
                str(exc)[:240],
            )
    return collected, had_success


def search_project_posts(
    project_handle: str,
    *,
    limit: int = MAX_PROJECT_RESULTS,
    window_minutes: int = SEARCH_WINDOW_MINUTES,
    now: datetime | None = None,
    provider=None,
) -> list[Post]:
    """Search recent project-related X posts without touching scheduled-feed state."""
    handle = normalize_handle(project_handle)
    limit = min(max(int(limit), 1), MAX_PROJECT_RESULTS)
    now_utc = (now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(minutes=window_minutes)

    primary = provider or get_x_provider()

    # Search endpoints can return a narrow/overlapping sample. Pull the
    # project's own recent timeline as a separate source, then merge it with
    # keyword/mention search results before de-duplicating and applying cutoff.
    raw_posts: list[Post] = []
    primary_succeeded = False
    get_latest_posts = getattr(primary, "get_latest_posts", None)
    if callable(get_latest_posts):
        try:
            timeline_posts = get_latest_posts(handle, limit=100)
            raw_posts.extend(timeline_posts or [])
            primary_succeeded = True
            logging.info(
                "PROJECT TIMELINE FETCH | handle=%s | fetched=%d",
                handle,
                len(timeline_posts or []),
            )
        except Exception as exc:
            logging.warning(
                "PROJECT TIMELINE FETCH FAILED | handle=%s | error=%s",
                handle,
                str(exc)[:240],
            )

    searched_posts, search_succeeded = _search_with_provider(primary, handle, 100)
    raw_posts.extend(searched_posts)
    primary_succeeded = primary_succeeded or search_succeeded

    # FxTwitter's search route may return an incomplete/empty sample even when
    # recent posts exist. If the combined primary results contain no recent
    # original posts, use the existing authenticated X session as fallback.
    if (
        primary.__class__.__name__ == "FxTwitterProvider"
        and not _has_recent_post(raw_posts, cutoff, now_utc)
    ):
        try:
            from bot.x.twscrape import TwscrapeProvider

            fallback = TwscrapeProvider()
            fallback_posts, fallback_succeeded = _search_with_provider(fallback, handle, limit)
            if not fallback_succeeded:
                raise RuntimeError("Authenticated X session search requests failed")
            raw_posts = fallback_posts
            primary_succeeded = True
        except Exception as exc:
            logging.warning("PROJECT SESSION SEARCH FALLBACK ERROR | error=%s", str(exc)[:240])
            raise RuntimeError(
                "X project search is unavailable: FxTwitter returned no searchable posts and "
                "the authenticated X session search failed. Check TWITTERAPIS_X_AUTH_TOKEN "
                "and TWITTERAPIS_CT0 in Render; X may also be blocking search."
            ) from exc

    if not primary_succeeded and not raw_posts:
        raise RuntimeError(
            "X search is currently unavailable from the configured providers. "
            "Check the X search provider/API credentials and try again."
        )

    unique: dict[str, tuple[datetime, Post]] = {}
    for post in raw_posts:
        created = _parse_created_at(post.created_at)
        if created is None or created < cutoff or created > now_utc:
            continue
        post_id = str(post.id or "").strip()
        if not post_id or not post.text.strip() or _is_reply_post(post):
            continue
        previous = unique.get(post_id)
        if previous is None or created > previous[0]:
            unique[post_id] = (created, post)

    ordered = sorted(unique.values(), key=lambda item: item[0], reverse=True)
    return [post for _, post in ordered[:limit]]
