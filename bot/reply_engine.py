import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplyAnalysis:
    score: int
    suggested_reply: str | None
    reason: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def analyze_post(text: str) -> ReplyAnalysis:
    """Score a post and produce a short reply suggestion when appropriate.

    This V1 is deliberately deterministic and dependency-free. It is a safe
    foundation that can later be replaced by an LLM without changing the
    monitoring pipeline.
    """
    clean = _clean(text)
    lower = clean.lower()

    if not clean:
        return ReplyAnalysis(0, None, "Empty post")

    # Low-signal posts should still reach Telegram, but should not receive
    # forced reply suggestions.
    if re.search(r"^(gm|gn|good morning|good night)[!,.\s]*$", lower):
        return ReplyAnalysis(10, None, "Greeting only")

    if len(clean) < 25:
        return ReplyAnalysis(25, None, "Too little context")

    keyword_replies = [
        (("agent", "agents"), "Agents need rails."),
        (("payment", "payments"), "Payments need this."),
        (("wallet", "wallets"), "Wallets change this."),
        (("airdrop", "airdrop"), "That's the key bit."),
        (("launch", "launched", "launching"), "That's a big signal."),
        (("funding", "funded", "raise", "raised"), "That's a big signal."),
        (("data", "analytics", "onchain"), "The signal is clear."),
        (("price", "market", "token"), "Market missed that."),
    ]

    for keywords, reply in keyword_replies:
        if any(keyword in lower for keyword in keywords):
            return ReplyAnalysis(85, reply, "Strong topical signal")

    if "?" in clean:
        return ReplyAnalysis(75, "That's the key bit.", "Direct question")

    if any(word in lower for word in ("because", "however", "but", "yet", "instead", "why")):
        return ReplyAnalysis(80, "That part matters.", "Contains an opinion or contrast")

    if len(clean) >= 60:
        return ReplyAnalysis(65, "That's the key bit.", "Enough context for a focused reply")

    return ReplyAnalysis(40, None, "Low reply signal")


def validate_reply(reply: str | None, min_chars: int = 15, max_chars: int = 20) -> bool:
    if reply is None:
        return False
    return min_chars <= len(reply) <= max_chars
