from datetime import datetime, timedelta, timezone
import logging
import re

from bot.x.base import Post
from bot.x.provider import get_x_provider


HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
MAX_PROJECT_RESULTS = 35
SEARCH_WINDOW_MINUTES = 180


def normalize_handle(value: str) -> str:
    """Normalize an X handle or preserve a free-text project/topic query."""
    query = " ".join(str(value or "").strip().split())
    if not query:
        raise ValueError("Enter an X handle or search words, e.g. /project primus_labs or /project tokenized stocks")
    if query.startswith(("https://x.com/", "https://twitter.com/")):
        query = "@" + query.rstrip("/").split("/")[-1]
    if query.startswith("@"):
        handle = query[1:]
        if HANDLE_RE.fullmatch(handle):
            return "@" + handle
        raise ValueError("For an X handle, use letters, numbers, and underscores only.")
    if HANDLE_RE.fullmatch(query):
        return query
    if len(query) > 100 or len(query) < 2 or not re.search(r"[A-Za-z0-9]", query):
        raise ValueError("Search words must be 2–100 characters and include letters or numbers.")
    return query


def _is_handle_query(query: str) -> bool:
    """Only an explicitly prefixed @handle (or profile URL) means account search."""
    return query.startswith("@") and bool(HANDLE_RE.fullmatch(query[1:]))


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


def _search_queries(query: str) -> tuple[str, ...]:
    # Search explicit @mentions both literally and without @ because X search
    # backends do not consistently index the @ prefix. The latter is a fallback
    # query only; results are deduplicated after retrieval.
    phrase = query.replace('"', "").strip()
    if _is_handle_query(phrase):
        handle = phrase[1:]
        stem = handle.split("_", 1)[0]
        variants = [phrase, f'"{phrase}"', handle, f'"{handle}"']
        # X search can tokenize handles containing underscores inconsistently.
        # Search the distinctive leading token as a last-resort candidate source;
        # explicit-handle results are checked locally before being returned.
        if len(stem) >= 3:
            variants.extend([stem, f'"{stem}"'])
        return tuple(dict.fromkeys(variants))
    # Quoting a single token (including an underscore handle-like term) adds
    # no useful phrase constraint and doubles provider latency. Keep both
    # variants for actual multi-word phrases.
    if not re.search(r"\s", phrase):
        return (phrase,)
    return (phrase, f'"{phrase}"')


def _matches_explicit_handle(post: Post, query: str) -> bool:
    """Require the searched handle to appear in post text, not just in author metadata."""
    if not _is_handle_query(query):
        return True
    text = (post.text or "").casefold()
    handle = query[1:].casefold()
    return f"@{handle}" in text or handle in text


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
        "replying_to",
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


def _qualifying_post_count(posts: list[Post], cutoff: datetime, now_utc: datetime, query: str | None = None) -> int:
    """Count unique results that can survive the final eligibility filters."""
    ids: set[str] = set()
    for post in posts:
        created = _parse_created_at(post.created_at)
        post_id = str(post.id or "").strip()
        if (
            post_id
            and _matches_explicit_handle(post, query or "")
            and created is not None
            and cutoff <= created <= now_utc
            and post.text.strip()
            and not _is_reply_post(post)
        ):
            ids.add(post_id)
    return len(ids)


def _search_with_provider(
    provider,
    handle: str,
    limit: int,
    *,
    cutoff: datetime | None = None,
    now_utc: datetime | None = None,
) -> tuple[list[Post], bool]:
    collected: list[Post] = []
    had_success = False
    for query in _search_queries(handle):
        try:
            found = provider.search_posts(query, limit=min(max(limit, 1), 100))
            collected.extend(found)
            had_success = True
            logging.info(
                "PROJECT SEARCH QUERY RESULT | provider=%s | query_variant=%s | returned=%s | collected=%s",
                provider.__class__.__name__, query, len(found), len(collected),
            )
            # Stop once enough unique, in-window, non-reply posts are available.
            # This prevents trying every fallback spelling when the first query
            # already filled the user's result quota.
            if cutoff is not None and now_utc is not None:
                if _qualifying_post_count(collected, cutoff, now_utc, handle) >= limit:
                    break
        except Exception as exc:
            logging.warning(
                "PROJECT SEARCH PROVIDER ERROR | provider=%s | query=%s | error=%s",
                provider.__class__.__name__,
                handle,
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
    """Search recent X posts for an account handle or free-text project/topic query."""
    query = normalize_handle(project_handle)
    limit = min(max(int(limit), 1), MAX_PROJECT_RESULTS)
    now_utc = (now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(minutes=window_minutes)

    primary = provider or get_x_provider()

    # Search the post text for the exact user-supplied term. Do not substitute
    # an account timeline or account-author query for explicit @handles.
    raw_posts: list[Post] = []
    primary_succeeded = False
    # Request only the amount the command can display; oversized pagination can stall
    # the Telegram command while walking irrelevant older search pages.
    searched_posts, search_succeeded = _search_with_provider(primary, query, limit, cutoff=cutoff, now_utc=now_utc)
    raw_posts.extend(searched_posts)
    primary_succeeded = primary_succeeded or search_succeeded

    # FxTwitter can return incomplete samples, and some returned posts are
    # discarded by eligibility filters. When it produces fewer than the
    # requested number of displayable results, supplement it with X session
    # search instead of treating a partial sample as complete.
    primary_qualifying = _qualifying_post_count(raw_posts, cutoff, now_utc, query)
    logging.info(
        "PROJECT SEARCH PRIMARY SUMMARY | query=%s | provider=%s | raw_count=%s | qualifying_count=%s",
        query, primary.__class__.__name__, len(raw_posts), primary_qualifying,
    )
    if (
        primary.__class__.__name__ == "FxTwitterProvider"
        and primary_qualifying < limit
    ):
        try:
            from bot.x.twscrape import TwscrapeProvider

            fallback = TwscrapeProvider()
            # One authenticated request is enough to supplement an incomplete
            # public result set. Repeating quoted variants here can double the
            # wait on X's session search without adding useful coverage.
            fallback_posts = fallback.search_posts(query, limit=min(max(limit, 1), 100))
            raw_posts.extend(fallback_posts)
            primary_succeeded = True
        except Exception as exc:
            logging.warning("PROJECT SESSION SEARCH FALLBACK ERROR | error=%s", str(exc)[:240])
            # A successful primary search with zero matching/recent posts is a
            # valid empty result, not a provider outage. Keep its results and let
            # the normal filtering return no matches. Raise only when both the
            # primary search and its authenticated fallback are unavailable.
            if not raw_posts:
                raise RuntimeError(
                    "X project search returned no usable results and the authenticated "
                    "fallback failed. This is a provider/search failure, not a confirmed "
                    "no-match result. Check Render logs and TWITTERAPIS_X_AUTH_TOKEN / "
                    "TWITTERAPIS_CT0; the FxTwitter endpoint may be unavailable to Render."
                ) from exc

    if not primary_succeeded and not raw_posts:
        raise RuntimeError(
            "X search is currently unavailable from the configured providers. "
            "Check the X search provider/API credentials and try again."
        )

    unique: dict[str, tuple[datetime, Post]] = {}
    rejected_missing_date = 0
    rejected_outside_window = 0
    rejected_reply = 0
    rejected_empty = 0
    for post in raw_posts:
        created = _parse_created_at(post.created_at)
        if not _matches_explicit_handle(post, query):
            continue
        if created is None:
            rejected_missing_date += 1
            continue
        if created < cutoff or created > now_utc:
            rejected_outside_window += 1
            continue
        post_id = str(post.id or "").strip()
        if not post_id or not post.text.strip():
            rejected_empty += 1
            continue
        if _is_reply_post(post):
            rejected_reply += 1
            continue
        previous = unique.get(post_id)
        if previous is None or created > previous[0]:
            unique[post_id] = (created, post)

    ordered = sorted(unique.values(), key=lambda item: item[0], reverse=True)
    results = [post for _, post in ordered[:limit]]
    logging.info(
        "PROJECT SEARCH FILTER SUMMARY | query=%s | raw_count=%s | unique_count=%s | "
        "result_count=%s | missing_date=%s | outside_window=%s | replies=%s | empty=%s",
        query, len(raw_posts), len(unique), len(results), rejected_missing_date,
        rejected_outside_window, rejected_reply, rejected_empty,
    )
    return results
