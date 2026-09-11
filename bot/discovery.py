import random
import re
from dataclasses import dataclass

from bot.x.base import Post, XProvider


@dataclass(frozen=True)
class DiscoveryTopic:
    name: str
    query: str
    keywords: tuple[str, ...]


DISCOVERY_TOPICS = (
    DiscoveryTopic("defi", '(DeFi OR "decentralized finance" OR DEX OR lending OR liquidity) (crypto OR web3)', ("defi", "dex", "lending", "liquidity", "finance")),
    DiscoveryTopic("comics", '("crypto comic" OR "web3 comic" OR "crypto meme" OR "web3 meme")', ("comic", "meme", "crypto", "web3")),
    DiscoveryTopic("ai_agents", '("AI agents" OR "AI agent" OR "agentic AI") (crypto OR web3 OR blockchain)', ("ai", "agent", "crypto", "web3", "builder")),
    DiscoveryTopic("airdrops", '(airdrop OR testnet OR points) (crypto OR web3 OR blockchain)', ("airdrop", "testnet", "points", "crypto", "web3")),
    DiscoveryTopic("rewards", '(rewards OR incentives OR points) (crypto OR web3 OR protocol)', ("rewards", "incentives", "points", "crypto", "protocol")),
    DiscoveryTopic("claim_now", '("claim now" OR "claim your" OR claim) (airdrop OR rewards OR tokens) (crypto OR web3)', ("claim", "airdrop", "rewards", "tokens")),
    DiscoveryTopic("security", '("crypto security" OR "defi hack" OR exploit OR drained OR hacked OR vulnerability) (crypto OR defi OR web3)', ("security", "hack", "exploit", "drained", "hacked")),
    DiscoveryTopic("hot_topics", '(crypto OR bitcoin OR ethereum OR stablecoin OR solana OR web3) (trending OR "hot topic" OR viral OR breaking OR "just in")', ("crypto", "trending", "viral", "breaking", "news")),
)

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
    """Accept X verified/check-mark signals used by different API response shapes."""
    raw = post.raw or {}
    author = raw.get("author") or raw.get("user") or {}
    values = (
        raw.get("verified"), raw.get("is_verified"), raw.get("verified_type"), raw.get("verification_type"), raw.get("blue_verified"), raw.get("is_blue_verified"),
        author.get("verified"), author.get("is_verified"), author.get("verified_type"), author.get("verification_type"), author.get("blue_verified"), author.get("is_blue_verified"),
    )
    for value in values:
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() not in {"", "false", "none", "null", "unverified"}:
            return True
    return False


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


def discover_posts(provider: XProvider, monitored_handles: list[str], max_posts: int = 5) -> list[tuple[Post, str, int]]:
    """Find up to five random, verified posts from non-monitored accounts across the discovery topics."""
    topics = list(DISCOVERY_TOPICS)
    random.shuffle(topics)

    monitored = {handle.lstrip("@").lower() for handle in monitored_handles}
    candidates: dict[str, tuple[Post, str, int]] = {}
    used_topics: set[str] = set()

    for topic in topics:
        if len(candidates) >= max_posts:
            break
        try:
            posts = provider.search_posts(topic.query, limit=20)
        except Exception:
            continue

        topic_candidates: list[tuple[Post, str, int]] = []
        for post in posts:
            username = post.username.lstrip("@").lower()
            if not username or username in monitored or not _is_verified(post) or not post.text.strip():
                continue
            if re.fullmatch(r"https?://\S+", post.text.strip()):
                continue
            score = _score(post, topic)
            if score < 5:
                continue
            topic_candidates.append((post, topic.name, score))

        random.shuffle(topic_candidates)
        for candidate in topic_candidates:
            post, topic_name, score = candidate
            if post.id in candidates:
                continue
            candidates[post.id] = candidate
            used_topics.add(topic_name)
            break

    pool = list(candidates.values())
    random.shuffle(pool)
    return pool[: min(max_posts, len(pool))]
