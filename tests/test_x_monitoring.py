import os
from datetime import datetime, timezone

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from bot.discovery import DISCOVERY_TOPICS
from bot.monitor import (
    MONITORED_HANDLES_PER_RUN,
    _is_recent_for_schedule,
    _last_scan_checkpoint,
    _parse_created_at,
    _schedule_already_processed,
    _schedule_start,
    _process_handle,
    _process_post,
    _select_handles,
    run_monitor_cycle,
)
from bot.x.base import Post
from bot.x.fxtwitter import FxTwitterProvider
from bot.x.mock import MockXProvider
from bot.x.twscrape import TwscrapeBlockedError
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

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        return self

    def insert(self, row):
        self.db.activities.append(row)
        return self

    def execute(self):
        if self.name == "activity_log" and self.filters.get("event_type") == "schedule_processed":
            slot = self.filters.get("message")
            rows = [item for item in self.db.activities if item["event_type"] == "schedule_processed" and item["message"] == slot]
            return type("Result", (), {"data": rows})()
        if self.name == "activity_log" and self.filters.get("event_type") == "scan_checkpoint":
            rows = [item for item in self.db.activities if item["event_type"] == "scan_checkpoint"]
            return type("Result", (), {"data": rows[-1:]})()
        if self.name == "activity_log" and self.filters.get("event_type") == "handle_rotation":
            rows = [item for item in self.db.activities if item["event_type"] == "handle_rotation"]
            return type("Result", (), {"data": rows[-1:]})()
        return type("Result", (), {"data": []})()


def test_fxtwitter_status_mapping():
    item = {
        "type": "status",
        "id": "123",
        "url": "https://x.com/alice/status/123",
        "text": "hello",
        "created_at": "2026-09-18T17:00:00.000Z",
        "likes": 12,
        "reposts": 3,
        "replies": 2,
        "author": {
            "id": "1",
            "name": "Alice",
            "screen_name": "alice",
            "verification": {"verified": True, "type": "individual"},
        },
    }

    post = FxTwitterProvider._to_post(item)

    assert post is not None
    assert post.id == "123"
    assert post.username == "alice"
    assert post.text == "hello"
    assert post.raw["author"]["is_verified"] is True


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

    posts = provider.get_latest_posts("alice", limit=1)
    assert len(posts) == 1
    assert posts[0].id == "original"


def test_monitored_pool_randomizes_full_account_list():
    accounts = [f"@user{i}" for i in range(20)]
    selected = _select_handles(accounts)

    assert len(selected) == 20
    assert set(selected) == set(accounts)
    assert MONITORED_HANDLES_PER_RUN == 20


def test_monitored_handles_randomly_change_between_schedules():
    from bot.monitor import _select_rotating_handles

    accounts = [f"@user{i:02d}" for i in range(60)]
    db = IntegrationDB()

    first = _select_rotating_handles(db, accounts)
    second = _select_rotating_handles(db, accounts)
    third = _select_rotating_handles(db, accounts)

    assert len(first) == 20
    assert len(second) == 20
    assert len(third) == 20
    assert set(first).isdisjoint(second)
    assert set(second).isdisjoint(third)
    assert len(set(first + second + third)) >= 40


def test_monitored_handle_selection_uses_random_sample(monkeypatch):
    from bot.monitor import _select_rotating_handles

    accounts = [f"@user{i:02d}" for i in range(20)]
    db = IntegrationDB()
    calls = []

    def fake_sample(pool, count):
        calls.append((list(pool), count))
        return list(pool)[:count]

    monkeypatch.setattr("bot.monitor.random.sample", fake_sample)

    selected = _select_rotating_handles(db, accounts)

    assert len(selected) == 20
    assert calls
    assert calls[0][1] == 20


def test_monitored_handle_selects_newest_qualifying_post_since_scan():
    older_post = Post(
        id="older",
        text="older post",
        username="alice",
        created_at="Tue Sep 08 15:10:00 +0000 2026",
    )
    newest_post = Post(
        id="newest",
        text="newest post",
        username="alice",
        created_at="Tue Sep 08 15:20:00 +0000 2026",
    )

    processed = []
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr(
        "bot.monitor._process_post",
        lambda db, post, handle, source: processed.append(post.id) or "sent",
    )

    provider = FakeRecentProvider([older_post, newest_post])
    start = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)

    result = _process_handle(object(), provider, "@alice", start, now)
    monkeypatch.undo()

    assert result == "sent"
    assert processed == ["newest"]


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


def test_twscrape_block_stops_cycle_without_checkpoint(monkeypatch):
    accounts = ["@alice", "@bob", "@carol"]
    db = IntegrationDB()
    activity = []

    class BlockedProvider:
        def get_latest_posts(self, handle, limit=20):
            raise TwscrapeBlockedError("X blocked the twscrape session (403/Cloudflare)")

    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setattr("bot.monitor.load_accounts", lambda: accounts)
    monkeypatch.setattr("bot.monitor.get_x_provider", lambda: BlockedProvider())
    monkeypatch.setattr("bot.monitor.get_db", lambda: db)
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: activity.append(args))

    run_monitor_cycle()

    assert any(item[1] == "x_provider_blocked" for item in activity)
    assert not any(item[1] == "scan_checkpoint" for item in activity)


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
        return ["this rollout actually looks useful", "wait the wallet flow works already?", "lol that timing is wild honestly"]

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
        "tokenized_stocks",
        "payments_stablecoins",
    } <= names


def test_last_scan_checkpoint_is_read_from_activity_log():
    db = IntegrationDB()
    db.activities.append(
        {
            "event_type": "scan_checkpoint",
            "handle": "SYSTEM",
            "post_id": None,
            "message": "scan=2026-09-08T15:00:00+00:00",
        }
    )

    assert _last_scan_checkpoint(db) == datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def test_schedule_marker_prevents_duplicate_cycle(monkeypatch):
    from bot.monitor import _mark_schedule_processed

    db = IntegrationDB()
    now = datetime(2026, 9, 8, 14, 5, tzinfo=timezone.utc)
    slot = _schedule_start(now)

    assert not _schedule_already_processed(db, slot)
    _mark_schedule_processed(db, slot)
    assert _schedule_already_processed(db, slot)


def test_schedule_marker_is_written_only_after_successful_cycle(monkeypatch):
    accounts = ["@alice"]
    db = IntegrationDB()

    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setenv("TEST_WINDOW_MINUTES", "10")
    monkeypatch.setattr("bot.monitor.load_accounts", lambda: accounts)
    monkeypatch.setattr("bot.monitor.get_x_provider", lambda: object())
    monkeypatch.setattr("bot.monitor.get_db", lambda: db)
    monkeypatch.setattr("bot.monitor._process_handle", lambda *args: "error")
    monkeypatch.setattr("bot.monitor._run_discovery", lambda *args: (0, False))
    monkeypatch.setattr(
        "bot.monitor.record_activity",
        lambda db, event_type, handle, post_id, message: db.activities.append(
            {"event_type": event_type, "handle": handle, "post_id": post_id, "message": message}
        ),
    )

    run_monitor_cycle()

    assert not any(item["event_type"] == "schedule_processed" for item in db.activities)
    assert not any(item["event_type"] == "scan_checkpoint" for item in db.activities)


def test_discovery_uses_five_post_target(monkeypatch):
    accounts = [f"@integration{i}" for i in range(20)]
    db = IntegrationDB()
    captured = []

    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setattr("bot.monitor.load_accounts", lambda: accounts)
    monkeypatch.setattr("bot.monitor.get_x_provider", lambda: object())
    monkeypatch.setattr("bot.monitor.get_db", lambda: db)
    monkeypatch.setattr("bot.monitor._process_handle", lambda *args: "skipped")
    monkeypatch.setattr(
        "bot.monitor._run_discovery",
        lambda db, provider, accounts, scan_start, now, max_posts: captured.append(max_posts) or (max_posts, False),
    )
    monkeypatch.setattr("bot.monitor.record_activity", lambda db, event_type, handle, post_id, message: db.activities.append(
        {"event_type": event_type, "handle": handle, "post_id": post_id, "message": message}
    ))

    run_monitor_cycle()

    assert captured == [5]


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
    monitored_posts = [item for item in telegram_posts if str(item[1]).startswith("mock-integration")]
    discovery_posts = [item for item in telegram_posts if str(item[1]).startswith("mock-discovery-")]

    assert len(monitored_posts) == MONITORED_HANDLES_PER_RUN
    assert len(discovery_posts) == 5
    assert len(telegram_posts) == MONITORED_HANDLES_PER_RUN + 5
    assert len(saved_replies) == len(telegram_posts)
    assert any(item["event_type"] == "scan_checkpoint" for item in db.activities)
    assert not any(item["event_type"] == "error" for item in db.activities)


def test_manual_reply_selection_claim_is_single_use(monkeypatch):
    from bot import telegram_commands as commands

    calls = []

    class FakePendingDB:
        pass

    monkeypatch.setattr(
        commands,
        "get_pending_reply",
        lambda db, post_id: {
            "reply_1": "a useful reply with enough characters",
            "handle": "@alice",
        },
    )
    monkeypatch.setattr(
        commands,
        "mark_reply_selected",
        lambda db, post_id, reply_number: calls.append("claim") or len(calls) == 1,
    )
    monkeypatch.setattr(commands, "record_activity", lambda *args: None)
    monkeypatch.setattr(commands, "send_message", lambda message: calls.append(message))

    commands.process_select(FakePendingDB(), "post-1", 1)
    commands.process_select(FakePendingDB(), "post-1", 1)

    assert calls.count("claim") == 2
    assert sum(1 for item in calls if isinstance(item, str) and item.startswith("✅ REPLY")) == 1
    assert "That reply has already been processed." in calls


def test_auto_reply_uncertain_attempt_is_not_retried(monkeypatch):
    post = Post(
        id="auto-uncertain",
        text="test post",
        username="alice",
        created_at="Tue Sep 08 15:20:00 +0000 2026",
        url="https://x.com/alice/status/auto-uncertain",
    )
    activity = []
    create_calls = []

    class Provider:
        def create_reply(self, text, post_id):
            create_calls.append((text, post_id))
            return {"tweet_id": "new-reply"}

    monkeypatch.setattr("bot.monitor.AUTO_REPLY", True)
    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.save_post", lambda db, value: None)
    monkeypatch.setattr("bot.monitor.generate_replies", lambda text: ["good reply one", "good reply two", "good reply three"])
    monkeypatch.setattr("bot.monitor.validate_replies", lambda replies: True)
    monkeypatch.setattr("bot.monitor._latest_auto_reply_state", lambda db, post_id: ("auto_reply_started", None))
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: activity.append(args))
    monkeypatch.setattr("bot.monitor.send_new_post", lambda *args, **kwargs: None)

    result = _process_post(FakeDB(), post, "@alice", source="test", provider=Provider())

    assert result == "skipped"
    assert create_calls == []
    assert any(item[1] == "auto_reply_recovery_blocked" for item in activity)


def test_auto_reply_posted_state_is_reused_without_duplicate_post(monkeypatch):
    post = Post(
        id="auto-posted",
        text="test post",
        username="alice",
        created_at="Tue Sep 08 15:20:00 +0000 2026",
        url="https://x.com/alice/status/auto-posted",
    )
    sent = []
    create_calls = []

    class Provider:
        def create_reply(self, text, post_id):
            create_calls.append((text, post_id))
            return {"tweet_id": "duplicate"}

    monkeypatch.setattr("bot.monitor.AUTO_REPLY", True)
    monkeypatch.setattr("bot.monitor.post_seen", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.telegram_already_sent", lambda db, post_id: False)
    monkeypatch.setattr("bot.monitor.save_post", lambda db, value: None)
    monkeypatch.setattr("bot.monitor.generate_replies", lambda text: ["good reply one", "good reply two", "good reply three"])
    monkeypatch.setattr("bot.monitor.validate_replies", lambda replies: True)
    monkeypatch.setattr("bot.monitor._latest_auto_reply_state", lambda db, post_id: ("auto_reply_posted", "already posted reply"))
    monkeypatch.setattr("bot.monitor.record_activity", lambda *args: None)
    monkeypatch.setattr("bot.monitor.send_new_post", lambda *args, **kwargs: sent.append(kwargs))

    result = _process_post(FakeDB(), post, "@alice", source="test", provider=Provider())

    assert result == "sent"
    assert create_calls == []
    assert sent[0]["auto_reply_text"] == "already posted reply"
    assert sent[0]["suggested_replies"] is None
