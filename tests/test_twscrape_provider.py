from datetime import datetime, timezone

import pytest

from bot.x.base import Post
from bot.x.twscrape import TwscrapeProvider


class FakeUser:
    username = "alice"


class FakeTweet:
    id_str = "123"
    id = 123
    rawContent = "hello from X"
    user = FakeUser()
    date = datetime(2026, 9, 10, 12, 34, tzinfo=timezone.utc)
    url = "https://x.com/alice/status/123"
    retweetedTweet = None
    inReplyToTweetId = None


def test_twscrape_conversion():
    post = TwscrapeProvider._to_post(FakeTweet())
    assert isinstance(post, Post)
    assert post.id == "123"
    assert post.text == "hello from X"
    assert post.username == "alice"
    assert post.created_at == "2026-09-10T12:34:00+00:00"
    assert post.url == "https://x.com/alice/status/123"


def test_twscrape_filters_replies():
    tweet = FakeTweet()
    tweet.inReplyToTweetId = 99
    assert TwscrapeProvider._to_post(tweet) is None


def test_twscrape_filters_retweets():
    tweet = FakeTweet()
    tweet.retweetedTweet = object()
    assert TwscrapeProvider._to_post(tweet) is None


def test_twscrape_requires_existing_session(monkeypatch):
    monkeypatch.setattr("bot.x.twscrape.TWITTERAPIS_X_AUTH_TOKEN", "")
    monkeypatch.setattr("bot.x.twscrape.TWITTERAPIS_CT0", "")
    with pytest.raises(ValueError, match="requires the existing"):
        TwscrapeProvider()


class VerifiedUser:
    username = "verified"
    verified = True


class VerifiedTweet(FakeTweet):
    user = VerifiedUser()


def test_discovery_verification_accepts_model_objects():
    from bot.discovery import _is_verified

    post = Post(
        id="456",
        text="verified post",
        username="verified",
        created_at="2026-09-10T12:34:00+00:00",
        url="https://x.com/verified/status/456",
        raw={"author": VerifiedUser()},
    )
    assert _is_verified(post) is True
