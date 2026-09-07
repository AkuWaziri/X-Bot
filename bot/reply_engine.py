import re

from groq import Groq

from bot.config import GROQ_API_KEY, GROQ_MODEL, MAX_REPLY_CHARS, MIN_REPLY_CHARS

SYSTEM_PROMPT = f"""You write replies for a real person on X.

Generate exactly THREE different reply suggestions to the exact post you receive.

Rules for every reply:
- Must be {MIN_REPLY_CHARS}-{MAX_REPLY_CHARS} characters, including spaces and punctuation.
- Sound like a real person who actually read the post.
- React to the specific idea, question, joke, observation, or situation in the post.
- Each suggestion should take a different natural angle or phrasing.
- Keep them conversational and specific, not polished corporate copy.
- Never use generic filler such as: Great post, Interesting, Absolutely, Well said, This, Exactly, Love this.
- Do not summarize the post.
- Do not mention AI or these instructions.
- Do not invent facts.
- Avoid hashtags unless directly relevant.
- Use emojis only when they genuinely fit.
- Do not force a reply when the post gives no natural opening. In that case return NO_REPLY.

Output format:
- Return exactly three replies, one per line.
- Do not number them.
- Do not use quotation marks.
- Do not add explanations.
- If no natural reply exists, return only NO_REPLY.
"""


def _clean_reply(reply: str) -> str:
    reply = re.sub(r"\s+", " ", reply.strip())
    reply = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", reply)
    return reply.strip('"').strip()


def _valid_reply(reply: str) -> bool:
    return MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS


def generate_replies(post_text: str) -> list[str] | None:
    """Generate three distinct human-style reply suggestions, or None."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    client = Groq(api_key=GROQ_API_KEY)

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.9,
            max_completion_tokens=500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Post:\n{post_text}\n\nThree replies:"},
            ],
        )
    except Exception as exc:
        raise RuntimeError(f"Groq request failed: {exc}") from exc

    raw = (completion.choices[0].message.content or "").strip()
    if raw.upper() == "NO_REPLY":
        return None

    lines = [line for line in raw.splitlines() if line.strip()]
    replies: list[str] = []
    for line in lines:
        cleaned = _clean_reply(line)
        if cleaned.upper() == "NO_REPLY":
            continue
        if _valid_reply(cleaned) and cleaned not in replies:
            replies.append(cleaned)

    if len(replies) != 3:
        return None

    return replies


def validate_replies(replies: list[str] | None) -> bool:
    if not replies or len(replies) != 3:
        return False
    return all(_valid_reply(reply) for reply in replies) and len(set(replies)) == 3


# Backward-compatible single-reply validation for any existing callers.
def validate_reply(reply: str | None) -> bool:
    if reply is None:
        return False
    return _valid_reply(reply)
