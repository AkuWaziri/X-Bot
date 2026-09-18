from bot.telegram import _parse_callback_data


def test_parse_select_callback():
    assert _parse_callback_data("select:1:12345") == ("select", 1, "12345")
    assert _parse_callback_data("select:2:abc") == ("select", 2, "abc")
    assert _parse_callback_data("select:3:post-9") == ("select", 3, "post-9")


def test_parse_reject_callback():
    assert _parse_callback_data("reject:12345") == ("reject", None, "12345")


def test_parse_invalid_callback():
    assert _parse_callback_data("") is None
    assert _parse_callback_data("select:4:12345") is None
    assert _parse_callback_data("select:1") is None
    assert _parse_callback_data("reject:") is None
