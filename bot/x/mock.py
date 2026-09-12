from datetime import datetime, timedelta, timezone

from bot.x.base import Post, XProvider


class MockXProvider(XProvider):
    """Deterministic X provider for tests; it never makes network requests."""

    def __init__(self, now: datetime | None = None) -> None:
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        username = handle.lstrip("@").strip() or "mock_user"
        return [
            Post(
                id=f"mock-{username}-current",
                text=f"Mock current post from @{username}",
                username=username,
                created_at=(self.now - timedelta(minutes=2)).isoformat(),
                url=f"https://x.com/{username}/status/mock-{username}-current",
            ),
            Post(
                id=f"mock-{username}-old",
                text=f"Mock older post from @{username}",
                username=username,
                created_at=(self.now - timedelta(hours=2)).isoformat(),
                url=f"https://x.com/{username}/status/mock-{username}-old",
            ),
        ][:limit]

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        """Return one stable, unique candidate per discovery topic.

        The real provider searches independently for each topic. The mock must do
        the same so integration tests can reliably exercise the five-post
        discovery cap without duplicate mock post IDs collapsing the result set.
        """
        normalized = query.lower()
        topic_markers = (
            ("tokenized_stocks", ("tokenized stocks", "tokenized stock", "tokenized equities", "onchain stocks", "stock tokens")),
            ("ai_agents", ("ai agents", "ai agent", "agentic ai")),
            ("claim_now", ("claim now", "claim your", "claim)")),
            ("airdrops", ("airdrop", "testnet", "points")),
            ("rewards", ("rewards", "incentives")),
            ("security", ("security", "exploit", "hacked", "drained", "vulnerability")),
            ("comics", ("crypto comic", "web3 comic", "crypto meme", "web3 meme")),
            ("hot_topics", ("trending", "hot topic", "viral", "breaking", "just in")),
            ("defi", ("defi", "decentralized finance", "dex", "lending", "liquidity")),
        )

        slug = "crypto"
        for candidate, markers in topic_markers:
            if any(marker in normalized for marker in markers):
                slug = candidate
                break

        username = f"mock_discovery_{slug}"
        return [
            Post(
                id=f"mock-discovery-{slug}",
                text=f"Mock discovery opportunity about {slug}",
                username=username,
                created_at=(self.now - timedelta(minutes=3)).isoformat(),
                url=f"https://x.com/{username}/status/mock-discovery-{slug}",
                raw={
                    "author": {"username": username, "verified": True},
                    "public_metrics": {"like_count": 100, "retweet_count": 25},
                },
            )
        ][:limit]

    def create_reply(self, text: str, reply_to: str) -> dict[str, object]:
        return {"ok": True, "mock": True, "text": text, "reply_to": reply_to}
