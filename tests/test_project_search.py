import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from bot.project_search import normalize_handle, search_project_posts
from bot.x.base import Post


class FakeProvider:
    def __init__(self, posts=None, error=False):
        self.posts = posts or []
        self.error = error
        self.queries = []

    def search_posts(self, query, limit=20):
        self.queries.append((query, limit))
        if self.error:
            raise RuntimeError("provider unavailable")
        return self.posts[:limit]


def post(post_id, minutes_ago, now, username="alice"):
    return Post(
        id=post_id,
        text=f"post {post_id} mentioning primus_labs",
        username=username,
        created_at=(now - timedelta(minutes=minutes_ago)).isoformat(),
        url=f"https://x.com/{username}/status/{post_id}",
    )


def test_normalize_handle_accepts_at_sign_and_profile_url():
    assert normalize_handle("@primus_labs") == "primus_labs"
    assert normalize_handle("https://x.com/primus_labs/") == "primus_labs"


@pytest.mark.parametrize("value", ["", "@", "two handles", "handle!", "https://x.com/"])
def test_normalize_handle_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_handle(value)


def test_search_returns_only_unique_posts_from_last_hour_sorted_newest_first():
    now = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    provider = FakeProvider(
        [
            post("old", 61, now),
            post("newer", 4, now),
            post("older", 28, now),
            post("future", -2, now),
            post("newer", 4, now, username="different_author"),
        ]
    )

    results = search_project_posts("primus_labs", now=now, provider=provider)

    assert [item.id for item in results] == ["newer", "older"]
    assert len(provider.queries) == 2
    assert provider.queries[0][0] == "from:primus_labs OR @primus_labs"


def test_search_caps_results_at_35():
    now = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    provider = FakeProvider([post(str(i), i, now) for i in range(40)])

    results = search_project_posts("some_project", limit=99, now=now, provider=provider)

    assert len(results) == 35


def test_search_raises_when_all_provider_queries_fail():
    now = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    provider = FakeProvider(error=True)

    with pytest.raises(RuntimeError, match="X search is currently unavailable"):
        search_project_posts("primus_labs", now=now, provider=provider)
