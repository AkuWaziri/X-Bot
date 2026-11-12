from datetime import datetime, timezone

from bot.x.base import Post
from bot.x.mock import MockXProvider


def test_mock_provider_never_needs_twitterapis_credentials():
    provider = MockXProvider(now=datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc))

    posts = provider.get_latest_posts("@alice", limit=20)

    assert len(posts) == 2
    assert posts[0].id == "mock-alice-current"
    assert posts[0].created_at == "2026-09-08T15:28:00+00:00"
    assert all(isinstance(post, Post) for post in posts)


def test_mock_provider_returns_discovery_post_without_network():
    provider = MockXProvider(now=datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc))

    posts = provider.search_posts("airdrop rewards", limit=20)

    assert len(posts) == 2
    assert [post.username for post in posts] == [
        "mock_discovery_airdrop_1",
        "mock_discovery_airdrop_2",
    ]
    assert posts[0].created_at == "2026-09-08T15:27:00+00:00"
    assert posts[1].created_at == "2026-09-08T15:26:00+00:00"


def test_mock_provider_reply_is_non_publishing():
    provider = MockXProvider(now=datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc))

    result = provider.create_reply("test reply", "123")

    assert result == {
        "ok": True,
        "mock": True,
        "text": "test reply",
        "reply_to": "123",
    }


def test_provider_factory_selects_mock_without_twitterapis(monkeypatch):
    monkeypatch.setattr("bot.x.provider.X_PROVIDER_MODE", "mock")
    monkeypatch.setattr("bot.x.provider.TWITTERAPIS_API_KEY", "")

    from bot.x.provider import get_x_provider

    provider = get_x_provider()

    assert isinstance(provider, MockXProvider)



def test_fxtwitter_empty_profile_timeline_404_returns_no_posts(monkeypatch):
    import io
    import urllib.error

    from bot.x.fxtwitter import FxTwitterProvider

    def raise_not_found(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"code":404,"message":"User not found or empty timeline"}'),
        )

    monkeypatch.setattr("bot.x.fxtwitter.urllib.request.urlopen", raise_not_found)

    posts = FxTwitterProvider().get_latest_posts("@binance", limit=20)

    assert posts == []


def test_fxtwitter_empty_search_404_returns_no_posts(monkeypatch):
    import io
    import urllib.error

    from bot.x.fxtwitter import FxTwitterProvider

    def raise_not_found(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"code":404,"message":"No search results"}'),
        )

    monkeypatch.setattr("bot.x.fxtwitter.urllib.request.urlopen", raise_not_found)

    posts = FxTwitterProvider().search_posts("defi crypto", limit=20)

    assert posts == []
