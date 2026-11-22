import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.x.base import Post, XProvider, is_reply_payload


@dataclass(frozen=True)
class DiscoveryTopic:
    name: str
    query: str
    keywords: tuple[str, ...]


DISCOVERY_TOPICS = (
    DiscoveryTopic("privacy", '(privacy OR "privacy-preserving" OR "zero knowledge" OR "zero-knowledge" OR ZK) (crypto OR web3 OR blockchain)', ("privacy", "zero knowledge", "zero-knowledge", "zk", "crypto", "web3")),
    DiscoveryTopic("ai_agents", '("AI agents" OR "AI agent" OR "agentic AI") (crypto OR web3 OR blockchain)', ("ai", "agent", "agentic", "crypto", "web3")),
    DiscoveryTopic("security", '("crypto security" OR "web3 security" OR exploit OR hacked OR vulnerability OR "smart contract security")', ("security", "exploit", "hacked", "vulnerability", "smart contract")),
    DiscoveryTopic("comics_memes", '("crypto comic" OR "web3 comic" OR "crypto meme" OR "web3 meme" OR "blockchain meme")', ("comic", "comics", "meme", "memes", "crypto", "web3")),
    DiscoveryTopic("creators", '("crypto creator" OR "web3 creator" OR "content creator" OR "creator economy") (crypto OR web3 OR blockchain)', ("creator", "creators", "content", "building", "web3")),
    DiscoveryTopic("motivation", '(motivation OR mindset OR discipline OR consistency OR "keep building") (crypto OR web3 OR founder OR builder)', ("motivation", "mindset", "discipline", "consistency", "building")),
    DiscoveryTopic("crypto_tools", '("crypto tools" OR "web3 tools" OR "onchain tools" OR "developer tools" OR "blockchain tools")', ("tools", "tool", "onchain", "developer", "crypto", "web3")),
    DiscoveryTopic("encryption", '(encryption OR encrypted OR cryptography OR "end-to-end encryption") (crypto OR web3 OR blockchain)', ("encryption", "encrypted", "cryptography", "end-to-end", "crypto")),
    DiscoveryTopic("automation", '(automation OR automated OR workflow OR "AI automation") (crypto OR web3 OR blockchain)', ("automation", "automated", "workflow", "ai", "crypto", "web3")),
    DiscoveryTopic("hot_crypto_topics", '(crypto OR bitcoin OR ethereum OR stablecoin OR solana OR web3) (trending OR "hot topic" OR viral OR breaking OR "just in")', ("crypto", "bitcoin", "ethereum", "stablecoin", "solana", "trending", "viral", "breaking")),
)

class DiscoveryProviderUnavailable(RuntimeError):
    """Raised when every topic search failed at the provider layer."""


SPAMMY_TERMS = ("referral", "ref link", "dm me for", "free followers", "casino")


def _engagement(post: Post) -> int:
    raw = post.raw or {}
    metrics = raw.get("public_metrics") or raw.get("metrics") or {}
    values = (metrics.get("like_count"), metrics.get("retweet_count"), metrics.get("reply_count"), raw.get("like_count"), raw.get("retweets"), raw.get("replies"))
    total = 0
    for value in values:
        try:
            if value is not None:
                total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def _is_verified(post: Post) -> bool:
    """Fail closed unless provider metadata identifies an X blue check."""
    raw = post.raw or {}
    author = raw.get("author") or raw.get("user") or {}

    def _get(obj, key):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    verification = (
        author.get("verification")
        if isinstance(author, dict)
        else getattr(author, "verification", None)
    ) or {}
    type_fields = (
        _get(raw, "verified_type"),
        _get(raw, "verification_type"),
        _get(author, "verified_type"),
        _get(author, "verification_type"),
        _get(verification, "type"),
    )
    normalized_types = {
        value.strip().lower()
        for value in type_fields
        if isinstance(value, str) and value.strip()
    }
    # An explicit non-blue badge always overrides legacy generic verified flags.
    if normalized_types & {"business", "government", "gold", "gray", "grey", "organization", "unverified", "none"}:
        return False
    if normalized_types & {"blue", "blue_verified", "blue verified", "individual"}:
        return True

    # Legacy X/twscrape `verified=True` is the old blue-check field.
    # Newer providers expose explicit blue-check flags.
    boolean_fields = (
        _get(raw, "is_blue_verified"),
        _get(raw, "blue_verified"),
        _get(author, "is_blue_verified"),
        _get(author, "blue_verified"),
        _get(raw, "verified"),
        _get(author, "verified"),
    )
    return any(isinstance(value, bool) and value for value in boolean_fields)

def _created_at(post: Post) -> datetime:
    raw = str(post.created_at or "").strip()
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            value = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _score(post: Post, topic: DiscoveryTopic) -> int:
    text = post.text.lower()
    score = min(sum(1 for keyword in topic.keywords if keyword in text), 3) * 3
    engagement = _engagement(post)
    if engagement >= 1000:
        score += 5
    elif engagement >= 250:
        score += 4
    elif engagement >= 50:
        score += 2
    elif engagement >= 10:
        score += 1
    if "?" in post.text:
        score += 2
    if any(term in text for term in ("breaking", "just in", "announced", "hacked", "exploit", "trending", "viral")):
        score += 2
    if any(term in text for term in SPAMMY_TERMS):
        score -= 5
    if len(post.text) < 20:
        score -= 2
    if len(post.text) > 1000:
        score -= 1
    return score


def discover_posts(
    provider: XProvider,
    monitored_handles: list[str],
    max_posts: int = 10,
    topic_names: list[str] | None = None,
) -> list[tuple[Post, str, int]]:
    """Find recent qualifying posts across the requested topic batch."""
    if topic_names is None:
        topics = list(DISCOVERY_TOPICS)
        random.shuffle(topics)
    else:
        topics_by_name = {topic.name: topic for topic in DISCOVERY_TOPICS}
        topics = [topics_by_name[name] for name in topic_names if name in topics_by_name]
        if not topics:
            topics = list(DISCOVERY_TOPICS)
            random.shuffle(topics)

    monitored = {handle.lstrip("@").lower() for handle in monitored_handles}
    candidates: list[tuple[Post, str, int]] = []
    search_provider = provider
    fallback_attempted = False
    successful_searches = 0
    failed_searches = 0

    for topic in topics:
        try:
            posts = search_provider.search_posts(topic.query, limit=20)
            successful_searches += 1
        except Exception as exc:
            failed_searches += 1
            # FxTwitter's public search endpoint often returns 404 because its
            # guest search session is blocked. It is not an empty search result.
            # Try the configured paid provider only when its key is present,
            # then retain twscrape as the final no-cost fallback.
            if not fallback_attempted and search_provider is provider and "FxTwitter" in str(exc):
                fallback_attempted = True
                fallback_providers = []
                from bot.config import TWITTERAPIS_API_KEY
                if TWITTERAPIS_API_KEY:
                    from bot.x.twitterapis import TwitterAPIsProvider
                    fallback_providers.append(("twitterapis", lambda: TwitterAPIsProvider(TWITTERAPIS_API_KEY)))
                fallback_providers.append(("twscrape", None))

                posts = None
                for provider_name, provider_factory in fallback_providers:
                    try:
                        if provider_factory is not None:
                            search_provider = provider_factory()
                        else:
                            from bot.x.twscrape import TwscrapeProvider
                            search_provider = TwscrapeProvider()
                        logging.getLogger(__name__).warning(
                            "DISCOVERY PROVIDER FALLBACK | from=fxtwitter | to=%s",
                            provider_name,
                        )
                        posts = search_provider.search_posts(topic.query, limit=20)
                        successful_searches += 1
                        break
                    except Exception as fallback_exc:
                        failed_searches += 1
                        from bot.x.twscrape import TwscrapeBlockedError
                        logging.getLogger(__name__).error(
                            "DISCOVERY PROVIDER FAILED | provider=%s | error=%s",
                            provider_name,
                            str(fallback_exc)[:250],
                        )
                        if isinstance(fallback_exc, TwscrapeBlockedError):
                            break
                if posts is None:
                    # No fallback provider could complete even one search.
                    break
            else:
                logging.getLogger(__name__).warning(
                    "DISCOVERY SEARCH FAILED | topic=%s | provider=%s | error=%s",
                    topic.name,
                    type(search_provider).__name__,
                    str(exc)[:250],
                )
                continue

        accepted_for_topic = 0
        for post in posts:
            if is_reply_payload(post.raw, post.id):
                logging.getLogger(__name__).info(
                    "DISCOVERY REPLY/COMMENT SKIPPED | topic=%s | post_id=%s | author=%s",
                    topic.name,
                    post.id,
                    post.username,
                )
                continue
            username = post.username.lstrip("@").lower()
            if not username or username in monitored or not _is_verified(post) or not post.text.strip():
                continue
            if re.fullmatch(r"https?://\S+", post.text.strip()):
                continue
            score = _score(post, topic)
            if score < 5:
                continue
            candidates.append((post, topic.name, score))
            accepted_for_topic += 1

        logging.getLogger(__name__).info(
            "DISCOVERY SEARCH RESULT | topic=%s | returned=%d | qualifying=%d",
            topic.name,
            len(posts),
            accepted_for_topic,
        )

    if successful_searches == 0 and failed_searches:
        raise DiscoveryProviderUnavailable(
            f"All topic searches failed: {failed_searches} provider attempts failed; no search completed"
        )

    candidates.sort(key=lambda item: (_created_at(item[0]), item[2]), reverse=True)

    selected: list[tuple[Post, str, int]] = []
    used_authors: set[str] = set()
    used_posts: set[str] = set()

    for item in candidates:
        post = item[0]
        author = post.username.lstrip("@").lower()
        if not author or author in used_authors or post.id in used_posts:
            continue
        selected.append(item)
        used_authors.add(author)
        used_posts.add(post.id)
        if len(selected) >= max_posts:
            break

    return selected
