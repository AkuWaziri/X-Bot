import re
from dataclasses import dataclass

from bot.x.base import Post


@dataclass(frozen=True)
class PostAnalysis:
    post: Post
    score: int
    qualifies: bool
    reason: str


LOW_SIGNAL_PATTERNS = (
    r"^gm[!,. ]*$",
    r"^gn[!,. ]*$",
    r"^good morning",
    r"^goodnight",
    r"^good night",
    r"^happy new week",
    r"^happy monday",
    r"^happy friday",
)

PROMO_PATTERNS = (
    r"follow me",
    r"giveaway",
    r"airdrop now",
    r"claim now",
    r"use my code",
    r"referral",
)

QUESTION_PATTERN = re.compile(r"\?|\b(why|how|what|when|which|should|can|does|is|are)\b", re.I)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def analyze_post(post: Post) -> PostAnalysis:
    """Score a post for whether it presents a meaningful reply opportunity."""
    text = " ".join(post.text.split())
    lowered = text.lower()
    words = _word_count(text)

    for pattern in LOW_SIGNAL_PATTERNS:
        if re.search(pattern, lowered):
            return PostAnalysis(post, 0, False, "low-signal social post")

    score = 0
    reasons: list[str] = []

    if QUESTION_PATTERN.search(text):
        score += 35
        reasons.append("conversation cue")

    if words >= 12:
        score += 15
        reasons.append("substantive")
    elif words < 5:
        score -= 20

    if any(token in lowered for token in ("build", "launch", "launched", "shipping", "shipped", "update", "released")):
        score += 15
        reasons.append("useful update")

    if any(token in lowered for token in ("because", "but", "however", "instead", "means", "lesson", "learned", "think", "believe")):
        score += 15
        reasons.append("opinion or insight")

    if any(re.search(pattern, lowered) for pattern in PROMO_PATTERNS):
        score -= 35
        reasons.append("promotional")

    if lowered.startswith(("rt ", "retweeted ")):
        score -= 30
        reasons.append("retweet-like")

    qualifies = score >= 30
    reason = ", ".join(reasons) if reasons else "no strong reply signal"

    return PostAnalysis(post, score, qualifies, reason)


def select_best_post(posts: list[Post]) -> PostAnalysis | None:
    """Return the single strongest qualifying post for one monitoring round."""
    analyses = [analyze_post(post) for post in posts]
    qualifying = [analysis for analysis in analyses if analysis.qualifies]

    if not qualifying:
        return None

    return max(
        qualifying,
        key=lambda analysis: (analysis.score, analysis.post.created_at or "", analysis.post.id),
    )
