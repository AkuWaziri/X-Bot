import os
from datetime import datetime, timezone

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from bot.discovery import DISCOVERY_TOPICS
from bot.monitor import (
    MONITORED_HANDLES_PER_RUN,
    _is_recent_for_schedule,
    _parse_created_at,
    _process_handle,
    _process_post,
    _select_handles,
    run_monitor_cycle,
)
from bot.x.base import Post
from bot.x.mock import MockXProvider
from bot.x.twitterapis import TwitterAPIsProvider


class FakeTwitterAPIsProvider(TwitterAPIsProvider):
    def __init__(self, tweets):
        self.tweets = tweets

    def _request(self, method, path, *, params=None, body=None):
        return {"tweets": self.tweets}


class FakeRecentProvider:
    def __init__(self, posts):
        self.posts = posts

    def get_latest_posts(self, handle, limit=20):
        assert limit == 20
        return self.posts


class FakeErrorProvider:
    def __init__(self, message):
        self.message = message

    def get_latest_posts(self, handle, limit=20):
        raise RuntimeError(self.message)


class FakeDB:
    pass


class IntegrationDB:
    def __init__(self):
        self.activities = []

    def table(self, name):
        return IntegrationTable(self, name)


class IntegrationTable:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self.filters = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, value):
        return self

    def execute(self):
        if self.name == "activity_log" and self.filters.get("event_type") == "schedule_processed":
            slot = self.filters.get("message")
            rows = [item for item in self.db.activities if item["event_type"] == "schedule_processed" and item["message"] == slot]
            return type("Result", (), {"data": rows})()
        return type("Result", (), {"data": []})()


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


def test_monitored_pool_randomizes_full_account_list():
    accounts = [f"@user{i}" for i in range(20)]
    selected = _select_handles(accounts)

    assert len(selected) == 20
    assert set(selected) == set(accounts)
    assert MONITORED_HANDLES_PER_RUN == 15


def test_monitored_handle_scans_recent_posts_until_qualifying(monkeypatch):
    old_post = Post(
        id="old",
        text="old post",
        username="alice",
        created_at="Tue Sep 08 13:00:00 +0000 2026",
    )
    qualifying_post = Post(
        id="new",
        text="new post",
        username="alice",
        created_at="Tue Sep 08 15:20:00 +0000 2026",
    )

    processed = []
    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr(
        "bot.monitor._process_post",
        lambda db, post, handle, source: processed.append(post.id) or "sent",
    )

    provider = FakeRecentProvider([old_post, qualifying_post])
    start = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)

    result = _process_handle(object(), provider, "@alice", start, now)

    assert result == "sent"
    assert processed == ["new"]


def test_unresolved_monitored_account_is_soft_skipped(monkeypatch):
    activity = []
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: activity.append(args))

    provider = FakeErrorProvider("TwitterAPIs HTTP 404: Could not resolve @missing_account")
    result = _process_handle(
        FakeDB(),
        provider,
        "@missing_account",
        datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc),
    )

    assert result == "skipped"
    assert activity
    assert activity[0][1] == "account_skipped"


def test_non_404_provider_failure_remains_hard_error(monkeypatch):
    activity = []
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: activity.append(args))

    provider = FakeErrorProvider("TwitterAPIs HTTP 429: rate limited")
    result = _process_handle(
        FakeDB(),
        provider,
        "@alice",
        datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc),
    )

    assert result == "error"
    assert activity
    assert activity[0][1] == "error"


def test_groq_incomplete_reply_set_retries_and_recovers(monkeypatch):
    post = Post(
        id="groq-retry",
        text="test post",
        username="alice",
        created_at="Tue Sep 08 15:20:00 +0000 2026",
        url="https://x.com/alice/status/groq-retry",
    )
    calls = []

    def fake_generate_replies(text):
        calls.append(text)
        if len(calls) == 1:
            raise RuntimeError("Groq returned 2 valid replies instead of 3")
        return ["this is good", "wait really?", "lol that is wild"]

    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.save_post", lambda db, value: None)
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: None)
    monkeypatch.setattr("bot.monitor.send_new_post", lambda *args, **kwargs: None)
    monkeypatch.setattr("bot.monitor.generate_replies", fake_generate_replies)
    monkeypatch.setattr("bot.monitor.save_pending_replies", lambda *args: None)

    result = _process_post(FakeDB(), post, "@alice", source="test")

    assert result == "sent"
    assert len(calls) == 2


def test_groq_incomplete_reply_set_is_soft_skipped_after_retry(monkeypatch):
    post = Post(
        id="groq-skip",
        text="test post",
        username="alice",
        created_at="Tue Sep 08 15:20:00 +0000 2026",
        url="https://x.com/alice/status/groq-skip",
    )
    calls = []

    def fake_generate_replies(text):
        calls.append(text)
        raise RuntimeError("Groq returned 2 valid replies instead of 3")

    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.save_post", lambda db, value: None)
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: None)
    monkeypatch.setattr("bot.monitor.generate_replies", fake_generate_replies)

    result = _process_post(FakeDB(), post, "@alice", source="test")

    assert result == "skipped"
    assert len(calls) == 2


def test_discovery_topic_pool_covers_requested_categories():
    names = {topic.name for topic in DISCOVERY_TOPICS}
    assert {
        "defi",
        "comics",
        "ai_agents",
        "airdrops",
        "rewards",
        "claim_now",
        "security",
        "hot_topics",
    } <= names


def test_full_monitor_cycle_runs_with_mock_provider_without_twitterapis(monkeypatch):
    accounts = [f"@integration{i}" for i in range(20)]
    db = IntegrationDB()
    sent_posts = []
    saved_replies = []

    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setenv("TEST_WINDOW_MINUTES", "10")
    monkeypatch.setattr("bot.monitor.load_accounts", lambda: accounts)
    monkeypatch.setattr("bot.monitor.get_x_provider", lambda: MockXProvider())
    monkeypatch.setattr("bot.monitor.get_db", lambda: db)
    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.save_post", lambda db, post: sent_posts.append(("saved", post.id)))
    monkeypatch.setattr("bot.monitor.save_pending_replies", lambda *args: saved_replies.append(args))
    monkeypatch.setattr("bot.monitor.generate_replies", lambda text: ["good point", "interesting", "tell me more"])
    monkeypatch.setattr("bot.monitor.validate_replies", lambda replies: True)
    monkeypatch.setattr("bot.monitor.send_new_post", lambda *args, **kwargs: sent_posts.append(("telegram", kwargs.get("post_id"))))
    monkeypatch.setattr(
        "bot.monitor.record_activity",
        lambda db, event_type, handle, post_id, message: db.activities.append(
            {"event_type": event_type, "handle": handle, "post_id": post_id, "message": message}
        ),
    )

    run_monitor_cycle()

    telegram_posts = [item for item in sent_posts if item[0] == "telegram"]
    monitored_posts = [item for item in telegram_posts if str(item[1]).startswith("mock-@integration")]
    discovery_posts = [item for item in telegram_posts if str(item[1]).startswith("mock-discovery-")]

    assert len(monitored_posts) == MONITORED_HANDLES_PER_RUN
    assert len(discovery_posts) == 5
    assert len(telegram_posts) == 20
    assert len(saved_replies) == 20
    assert any(item["event_type"] == "schedule_processed" for item in db.activities)
    assert not any(item["event_type"] == "error" for item in db.activities)
