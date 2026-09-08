import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from datetime import datetime, timezone

from bot.monitor import _is_recent_for_schedule, _parse_created_at
from bot.x.base import Post
from bot.x.twitterapis import TwitterAPIsProvider


class FakeTwitterAPIsProvider(TwitterAPIsProvider):
    def __init__(self, tweets):
        self.tweets = tweets

    def _request(self, method, path, *, params=None, body=None):
        return {"tweets": self.tweets}


def test_twitter_timestamp_format_is_supported():
    parsed = _parse_created_at("Tue Sep 08 15:23:11 +0000 2026")
    assert parsed == datetime(2026, 9, 8, 15, 23, 11, tzinfo=timezone.utc)


def test_iso_timestamp_is_supported():
    parsed = _parse_created_at("2026-09-08T15:23:11Z")
    assert parsed == datetime(2026, 9, 8, 15, 23, 11, tzinfo=timezone.utc)


def test_recent_window_accepts_twitter_timestamp():
    post = Post(
        id="1",
        text="hello",
        username="alice",
        created_at="Tue Sep 08 15:23:11 +0000 2026",
    )
    start = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)
    assert _is_recent_for_schedule(post, start, now)


def test_provider_finds_original_after_filtered_tweet():
    provider = FakeTwitterAPIsProvider(
        [
            {
                "id": "reply",
                "text": "a reply",
                "author": {"username": "alice"},
                "created_at": "Tue Sep 08 15:25:00 +0000 2026",
                "is_reply": True,
                "is_retweet": False,
            },
            {
                "id": "original",
                "text": "the real post",
                "author": {"username": "alice"},
                "created_at": "Tue Sep 08 15:24:00 +0000 2026",
                "is_reply": False,
                "is_retweet": False,
            },
        ]
    )

    posts = provider.get_latest_posts("@alice", limit=1)
    assert len(posts) == 1
    assert posts[0].id == "original"
