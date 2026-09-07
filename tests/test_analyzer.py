from bot.analyzer import analyze_post, select_best_post
from bot.x.base import Post


def make_post(post_id: str, text: str) -> Post:
    return Post(id=post_id, text=text, username="test")


def test_low_signal_post_does_not_qualify():
    analysis = analyze_post(make_post("1", "Good morning everyone"))
    assert not analysis.qualifies


def test_question_can_qualify():
    analysis = analyze_post(
        make_post("2", "Why are stablecoins becoming the default rail for global payments?")
    )
    assert analysis.qualifies


def test_select_best_post_returns_only_one():
    posts = [
        make_post("1", "What do you think about the future of onchain payments?"),
        make_post("2", "We just launched a new protocol update. What changed for users?")
    ]
    winner = select_best_post(posts)
    assert winner is not None
    assert winner.post.id in {"1", "2"}
