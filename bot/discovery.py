import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone

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
    DiscoveryTopic("tokenized_stocks", '(("tokenized stocks" OR "tokenized stock" OR "tokenized equities" OR "onchain stocks" OR "on-chain stocks" OR "stock tokens") AND (crypto OR blockchain OR web3 OR RWA OR "real world assets"))', ("stock", "stocks", "equities", "tokenized", "onchain", "rwa", "crypto", "blockchain")),
    DiscoveryTopic("payments_stablecoins", '((payments OR stablecoin OR USDC OR USDT OR "stable coins") AND (crypto OR web3 OR blockchain))', ("payments", "stablecoin", "usdc", "usdt", "crypto", "web3", "blockchain")),
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
    """Accept X verified/check-mark signals from dicts and twscrape model objects."""
    raw = post.raw or {}
    author = raw.get("author") or raw.get("user") or {}

    def _get(obj, key):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    values = (
        _get(raw, "verified"),
        _get(raw, "is_verified"),
        _get(raw, "verified_type"),
        _get(raw, "verification_type"),
        _get(raw, "blue_verified"),
        _get(raw, "is_blue_verified"),
        _get(author, "verified"),
        _get(author, "is_verified"),
        _get(author, "verified_type"),
        _get(author, "verification_type"),
        _get(author, "blue_verified"),
        _get(author, "is_blue_verified"),
    )
    for value in values:
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() not in {"", "false", "none", "null", "unverified"}:
            return True
    return False


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


def discover_posts(provider: XProvider, monitored_handles: list[str], max_posts: int = 10) -> list[tuple[Post, str, int]]:
    """Find up to max_posts recent qualifying posts from topic searches."""
    topics = list(DISCOVERY_TOPICS)
    random.shuffle(topics)

    monitored = {handle.lstrip("@").lower() for handle in monitored_handles}
    candidates: list[tuple[Post, str, int]] = []

    for topic in topics:
        try:
            posts = provider.search_posts(topic.query, limit=20)
        except Exception:
            continue

        for post in posts:
            username = post.username.lstrip("@").lower()
            if not username or username in monitored or not _is_verified(post) or not post.text.strip():
                continue
            if re.fullmatch(r"https?://\S+", post.text.strip()):
                continue
            score = _score(post, topic)
            if score < 5:
                continue
            candidates.append((post, topic.name, score))

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
