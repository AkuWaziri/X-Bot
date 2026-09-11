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
        topic = query.strip().split()[0] if query.strip() else "crypto"
        slug = "".join(character.lower() if character.isalnum() else "-" for character in topic).strip("-") or "crypto"
        return [
            Post(
                id=f"mock-discovery-{slug}",
                text=f"Mock discovery opportunity about {topic}",
                username="mock_discovery",
                created_at=(self.now - timedelta(minutes=3)).isoformat(),
                url=f"https://x.com/mock_discovery/status/mock-discovery-{slug}",
                raw={
                    "author": {"username": "mock_discovery", "verified": True},
                    "public_metrics": {"like_count": 100, "retweet_count": 25},
                },
            )
        ][:limit]

    def create_reply(self, text: str, reply_to: str) -> dict[str, object]:
        return {"ok": True, "mock": True, "text": text, "reply_to": reply_to}
