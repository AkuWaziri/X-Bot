import os
from datetime import datetime, timezone

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from bot.project_search import normalize_handle, search_project_posts
from bot.x.base import Post


class UnicodeQueryProvider:
    def __init__(self):
        self.queries = []

    def search_posts(self, query, limit=20):
        self.queries.append(query)
        return [
            Post(
                id="unicode-result",
                text="A recent post in the matching search results",
                username="multilingual_author",
                created_at=datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc).isoformat(),
                url="https://x.com/multilingual_author/status/unicode-result",
                raw={},
            )
        ]


def test_project_accepts_hausa_special_letters():
    assert normalize_handle("ƙwallo") == "ƙwallo"
    assert normalize_handle("ɗan kasuwa") == "ɗan kasuwa"
    assert normalize_handle("ɓangare") == "ɓangare"


def test_project_accepts_korean_chinese_japanese_arabic_and_cyrillic():
    queries = [
        "비트코인",
        "比特币",
        "區塊鏈",
        "ブロックチェーン",
        "بيتكوين",
        "криптовалюта",
    ]
    for query in queries:
        assert normalize_handle(query) == query


def test_project_accepts_single_character_cjk_search():
    assert normalize_handle("中") == "中"


def test_project_normalizes_canonically_equivalent_unicode():
    decomposed_hausa = "ƙ"  # NFC form remains stable.
    assert normalize_handle(decomposed_hausa) == decomposed_hausa


def test_unicode_query_is_passed_to_x_provider_without_translation():
    now = datetime(2026, 11, 21, 10, 30, tzinfo=timezone.utc)
    provider = UnicodeQueryProvider()
    query = "比特币"

    results = search_project_posts(query, now=now, provider=provider)

    assert provider.queries == [query]
    assert [post.id for post in results] == ["unicode-result"]


def test_punctuation_only_query_remains_invalid():
    import pytest

    with pytest.raises(ValueError):
        normalize_handle("!!!")
