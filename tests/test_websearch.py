import json
from urllib.parse import parse_qs, urlparse

from bot.x.websearch import FreeWebSearchProvider, _syndication_token


def test_search_ids_extracts_and_deduplicates_x_status_links(monkeypatch):
    page = """
    <a class="result__a" href="https://x.com/alice/status/1234567890123456789">first result</a>
    <a class="result__a" href="https://twitter.com/alice/status/1234567890123456789">duplicate</a>
    <a class="result__a" href="https://x.com/bob/status/2234567890123456789">second result</a>
    <a class="result__a" href="https://example.com/not-x">not an X post</a>
    """
    monkeypatch.setattr(FreeWebSearchProvider, "_request", lambda *args, **kwargs: page)

    hits = FreeWebSearchProvider._search_ids("privacy", 2)

    assert hits == [
        ("1234567890123456789", ("alice", "first result")),
        ("2234567890123456789", ("bob", "second result")),
    ]


def test_search_ids_extracts_redirected_duckduckgo_links(monkeypatch):
    target = "https://x.com/alice/status/1234567890123456789"
    redirect = "https://duckduckgo.com/l/?uddg=" + __import__("urllib.parse").parse.quote(target, safe="")
    monkeypatch.setattr(
        FreeWebSearchProvider,
        "_request",
        lambda *args, **kwargs: f'<a href="{redirect}">indexed post</a>',
    )

    assert FreeWebSearchProvider._search_ids("privacy", 1)[0][0] == "1234567890123456789"


def test_search_ids_raises_on_duckduckgo_bot_challenge(monkeypatch):
    monkeypatch.setattr(
        FreeWebSearchProvider,
        "_request",
        lambda *args, **kwargs: "<html>unusual traffic - verify you are human</html>",
    )

    try:
        FreeWebSearchProvider._search_ids("privacy", 5)
    except RuntimeError as exc:
        assert "bot challenge" in str(exc)
    else:
        raise AssertionError("a search challenge must be reported as a provider failure")


def test_hydrate_maps_syndication_tweet_to_post_and_blue_badge(monkeypatch):
    payload = {
        "__typename": "Tweet",
        "id_str": "1234567890123456789",
        "text": "Privacy-preserving infrastructure update",
        "created_at": "2026-11-22T10:00:00.000Z",
        "user": {
            "screen_name": "alice",
            "is_blue_verified": True,
            "verified_type": "blue",
        },
    }
    captured = {}

    def fake_request(url, **kwargs):
        captured["url"] = url
        return json.dumps(payload)

    monkeypatch.setattr(FreeWebSearchProvider, "_request", fake_request)
    post = FreeWebSearchProvider._hydrate(payload["id_str"])

    assert post is not None
    assert post.id == payload["id_str"]
    assert post.username == "alice"
    assert post.text == payload["text"]
    assert post.url == f"https://x.com/alice/status/{payload['id_str']}"
    assert post.raw["author"]["is_blue_verified"] is True
    params = parse_qs(urlparse(captured["url"]).query)
    assert params["id"] == [payload["id_str"]]
    assert params["token"] == [_syndication_token(payload["id_str"])]


def test_hydrate_rejects_non_tweet_and_missing_author(monkeypatch):
    monkeypatch.setattr(
        FreeWebSearchProvider,
        "_request",
        lambda *args, **kwargs: json.dumps({"__typename": "User"}),
    )
    assert FreeWebSearchProvider._hydrate("1234567890123456789") is None

    monkeypatch.setattr(
        FreeWebSearchProvider,
        "_request",
        lambda *args, **kwargs: json.dumps({
            "__typename": "Tweet",
            "id_str": "1234567890123456789",
            "text": "A post without author metadata",
            "user": {},
        }),
    )
    assert FreeWebSearchProvider._hydrate("1234567890123456789") is None


def test_hydrate_reports_invalid_json(monkeypatch):
    monkeypatch.setattr(FreeWebSearchProvider, "_request", lambda *args, **kwargs: "not-json")

    try:
        FreeWebSearchProvider._hydrate("1234567890123456789")
    except RuntimeError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("invalid syndication JSON must be reported")


def test_search_posts_skips_failed_hydration_and_returns_valid_posts(monkeypatch):
    monkeypatch.setattr(
        FreeWebSearchProvider,
        "_search_ids",
        lambda self, query, limit: [
            ("1234567890123456789", ("alice", "first")),
            ("2234567890123456789", ("bob", "second")),
        ],
    )
    calls = []

    def hydrate(tweet_id):
        calls.append(tweet_id)
        if tweet_id.startswith("1"):
            raise RuntimeError("temporary syndication error")
        from bot.x.base import Post
        return Post(
            id=tweet_id,
            text="Security infrastructure update with useful details",
            username="bob",
            raw={"author": {"is_blue_verified": True}},
        )

    monkeypatch.setattr(FreeWebSearchProvider, "_hydrate", hydrate)
    posts = FreeWebSearchProvider().search_posts("security", limit=5)

    assert calls == ["1234567890123456789", "2234567890123456789"]
    assert len(posts) == 1
    assert posts[0].username == "bob"


def test_syndication_token_is_deterministic_and_nonempty():
    token = _syndication_token("1234567890123456789")
    assert token
    assert token == _syndication_token("1234567890123456789")
    assert "." not in token
