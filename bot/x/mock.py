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
                raw={"author": {"username": username, "is_blue_verified": True}},
            ),
            Post(
                id=f"mock-{username}-old",
                text=f"Mock older post from @{username}",
                username=username,
                created_at=(self.now - timedelta(hours=2)).isoformat(),
                url=f"https://x.com/{username}/status/mock-{username}-old",
                raw={"author": {"username": username, "is_blue_verified": True}},
            ),
        ][:limit]

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        """Return one stable, unique candidate per discovery topic.

        The real provider searches independently for each topic. The mock must do
        the same so integration tests can reliably exercise the discovery pool
        and 10-post final cap without duplicate mock post IDs collapsing the result set.
        """
        normalized = query.lower()
        topic_markers = (
            ("tokenized_stocks", ("tokenized stocks", "tokenized stock", "tokenized equities", "onchain stocks", "stock tokens")),
            ("ai_agents", ("ai agents", "ai agent", "agentic ai")),
            ("claim_now", ("claim now", "claim your", "claim)", "claim")),
            ("airdrop", ("airdrop", "testnet")),
            ("rewards", ("rewards", "incentives", "points")),
            ("security", ("security", "exploit", "hacked", "drained", "vulnerability")),
            ("comics", ("crypto comic", "web3 comic", "crypto meme", "web3 meme")),
            ("hot_topics", ("trending", "hot topic", "viral", "breaking", "just in")),
            ("defi", ("defi", "decentralized finance", "dex", "lending", "liquidity")),
            ("payments_stablecoins", ("payments", "stablecoin", "usdc", "usdt", "stable coins")),
        )

        slug = "crypto"
        for candidate, markers in topic_markers:
            if any(marker in normalized for marker in markers):
                slug = candidate
                break

        posts = []
        for index in range(2):
            username = f"mock_discovery_{slug}_{index + 1}"
            post_id = f"mock-discovery-{slug}-{index + 1}"
            posts.append(
                Post(
                    id=post_id,
                    text=f"Mock discovery opportunity {index + 1} about {slug} crypto web3",
                    username=username,
                    created_at=(self.now - timedelta(minutes=3 + index)).isoformat(),
                    url=f"https://x.com/{username}/status/{post_id}",
                    raw={
                        "author": {"username": username, "verified": True},
                        "public_metrics": {"like_count": 100, "retweet_count": 25},
                    },
                )
            )
        return posts[:limit]

    def create_reply(self, text: str, reply_to: str) -> dict[str, object]:
        return {"ok": True, "mock": True, "text": text, "reply_to": reply_to}
