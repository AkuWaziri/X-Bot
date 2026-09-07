from bot.accounts import normalize_handle


def test_normalize_handle():
    assert normalize_handle("alice") == "@alice"
    assert normalize_handle("@alice") == "@alice"
    assert normalize_handle("  @alice  ") == "@alice"
    assert normalize_handle("") == ""
