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
    DiscoveryTopic(
        "ai_jobs",
        '("AI jobs" OR "AI agents" OR "agentic AI") (crypto OR web3 OR blockchain)',
        ("ai", "agent", "job", "hiring", "builder"),
    ),
    DiscoveryTopic(
        "comics",
        '("crypto comic" OR "web3 comic" OR "crypto meme" OR "web3 meme")',
        ("comic", "meme", "crypto", "web3"),
    ),
    DiscoveryTopic(
        "hacks",
        '("crypto hack" OR "defi hack" OR exploit OR drained OR hacked) (crypto OR defi OR web3)',
        ("hack", "exploit", "drained", "hacked", "security"),
    ),
    DiscoveryTopic(
        "breaking",
        '(crypto OR bitcoin OR ethereum OR stablecoin) (breaking OR "just in" OR announced OR launches OR launched)',
        ("breaking", "announced", "launch", "launched", "news"),
    ),
    DiscoveryTopic(
        "airdrops",
        '(airdrop OR testnet OR points OR claim) (crypto OR web3 OR blockchain)',
        ("airdrop", "testnet", "points", "claim", "rewards"),
    ),
)

SPAMMY_TERMS = (
    "referral",
    "ref link",
    "dm me for",
    "free followers",
    "casino",
)


def _engagement(post: Post) -> int:
    raw = post.raw or {}
    metrics = raw.get("public_metrics") or raw.get("metrics") or {}
    values = (
        metrics.get("like_count"),
        metrics.get("retweet_count"),
        metrics.get("reply_count"),
        raw.get("like_count"),
        raw.get("retweets"),
        raw.get("replies"),
    )
    total = 0
    for value in values:
        try:
            if value is not None:
                total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def _score(post: Post, topic: DiscoveryTopic) -> int:
    text = post.text.lower()
    score = 0

    matched = sum(1 for keyword in topic.keywords if keyword in text)
    score += min(matched, 3) * 3

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
    if any(term in text for term in ("breaking", "just in", "announced", "hacked", "exploit")):
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
    max_posts: int = 3,
) -> list[tuple[Post, str, int]]:
    """Find a small number of high-quality posts from non-monitored accounts."""
    topics = list(DISCOVERY_TOPICS)
    random.shuffle(topics)
    selected_topics = topics[:2]

    monitored = {handle.lstrip("@").lower() for handle in monitored_handles}
    candidates: dict[str, tuple[Post, str, int]] = {}

    for topic in selected_topics:
        try:
            posts = provider.search_posts(topic.query, limit=20)
        except Exception:
            continue

        for post in posts:
            username = post.username.lstrip("@").lower()
            if not username or username in monitored:
                continue
            if not post.text.strip():
                continue
            if re.fullmatch(r"https?://\S+", post.text.strip()):
                continue

            score = _score(post, topic)
            if score < 5:
                continue

            current = candidates.get(post.id)
            candidate = (post, topic.name, score)
            if current is None or score > current[2]:
                candidates[post.id] = candidate

    ranked = sorted(candidates.values(), key=lambda item: item[2], reverse=True)

    # Keep discovery varied instead of always taking the exact same top posts.
    shortlist = ranked[: min(len(ranked), max_posts * 3)]
    random.shuffle(shortlist)
    shortlist.sort(key=lambda item: item[2], reverse=True)
    return shortlist[:max_posts]
