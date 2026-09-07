from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Post:
    id: str
    text: str
    username: str
    created_at: str | None = None
    url: str | None = None
    raw: dict[str, Any] | None = None


class XProvider:
    """Interface for fetching public X posts."""

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        raise NotImplementedError
