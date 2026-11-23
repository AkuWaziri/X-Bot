from bot.x.nitter import NitterSearchProvider


def test_extract_ids_accepts_relative_nitter_status_links():
    page = """
    <a href="/alice/status/1234567890123456789">alice post</a>
    <a href="https://nitter.mie.foundation/bob/status/2234567890123456789">bob post</a>
    <a href="/alice/status/1234567890123456789">duplicate</a>
    <a href="/alice/status/short">not a post</a>
    """
    hits = NitterSearchProvider._extract_ids(page, "https://nitter.mie.foundation")
    assert hits == [
        ("1234567890123456789", "alice post"),
        ("2234567890123456789", "bob post"),
    ]


def test_search_posts_falls_through_to_second_mirror_and_hydrates(monkeypatch):
    calls = []

    def fake_request(cls, url):
        calls.append(url)
        if "mie.foundation" in url:
            raise RuntimeError("mirror unavailable")
        return '<a href="/alice/status/1234567890123456789">post</a>'

    from bot.x.base import Post
    monkeypatch.setattr(NitterSearchProvider, "_request", classmethod(fake_request))
    monkeypatch.setattr(
        "bot.x.nitter.FreeWebSearchProvider._hydrate",
        lambda post_id: Post(
            id=post_id,
            text="privacy infrastructure update",
            username="alice",
            created_at="2026-11-23T10:00:00+00:00",
            raw={"author": {"is_blue_verified": True}},
        ),
    )

    posts = NitterSearchProvider().search_posts("privacy", limit=5)
    assert len(calls) == 2
    assert len(posts) == 1
    assert posts[0].username == "alice"
