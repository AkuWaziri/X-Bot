import re

from groq import Groq

from bot.config import GROQ_API_KEY, GROQ_MODEL, MAX_REPLY_CHARS, MIN_REPLY_CHARS

STYLE_EXAMPLES = """
Examples of the account's natural X reply style:
- I love your art man 😂
- Cracks me up anytime it comes up. Never stop doing this
- oh man, hype lives his own life
- hope you haven't lost everything
- Wow interesting 😃
- U should start posting ur predictions 👀
- Bro do you think it finally coming sir
- mf. Learnt bait for the first time
- Congratulations my boss
- I didn't see this earlier
- Happy weekend big cat
- made fun of wale ✅ secured a whitelist ✅ take notes
- that's a win, if profits are involved
- GM castro. do have a productive week
- if it happens, its gonna be a massive in my financial freedom journey
"""

SYSTEM_PROMPT = f"""You reply to posts on X as a real person.

Do not write polished social-media copy. React to the exact post like someone casually replying from their phone.

STYLE EXAMPLES:
{STYLE_EXAMPLES}

Learn the rhythm from the examples without copying them.

Rules:
- React to what was actually posted. Talk to the person, not about the post.
- Short and spontaneous is usually better than clever or detailed.
- Fragments, lowercase, loose grammar and missing punctuation are allowed.
- Match the energy of the post: joke back to jokes, ask natural questions, tease when appropriate, be supportive when appropriate.
- Do not force an insight, explanation, lesson or analysis.
- Do not make every reply clever, enthusiastic, or the same length.
- Casual words like bro, man, boss are allowed only when they fit naturally.
- Never use corporate or polished influencer language.
- Never use generic filler such as Great post, Interesting, Absolutely, Well said, This, Exactly, Love this.
- Do not restate or summarize the post.
- Do not invent facts.
- Avoid hashtags unless directly relevant.
- Emojis are optional and should feel natural.
- Avoid AI-sounding phrases such as the interesting part, this highlights, it's worth noting, great reminder, or this is why.

Generate THREE genuinely different spontaneous reactions. They should feel like three different ways a real person might reply, not three rewrites of one sentence.

Each reply MUST be {MIN_REPLY_CHARS}-{MAX_REPLY_CHARS} characters including spaces and punctuation.

OUTPUT:
R1: reply
R2: reply
R3: reply

Return only those three lines.
"""


def _clean_reply(reply: str) -> str:
    reply = re.sub(r"\s+", " ", reply.strip())
    reply = re.sub(r"^(?:R[123]\s*:\s*|[-*•]\s*|\d+[.)]\s*)", "", reply, flags=re.IGNORECASE)
    return reply.strip('"').strip()


def _valid_reply(reply: str) -> bool:
    return MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS


def _parse_replies(raw: str) -> list[str]:
    if raw.upper().strip() == "NO_REPLY":
        return []

    tagged = re.findall(
        r"R[123]\s*:\s*(.*?)(?=\n\s*R[123]\s*:|$)",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    candidates = tagged if len(tagged) == 3 else [line for line in raw.splitlines() if line.strip()]

    replies: list[str] = []
    for candidate in candidates:
        cleaned = _clean_reply(candidate)
        if cleaned.upper() == "NO_REPLY":
            continue
        if _valid_reply(cleaned) and cleaned not in replies:
            replies.append(cleaned)

    return replies


def generate_replies(post_text: str) -> list[str] | None:
    """Generate three distinct human-style reply suggestions, or None."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    client = Groq(api_key=GROQ_API_KEY)

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=1.0,
            max_completion_tokens=1000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Post:\n{post_text}\n\nReact naturally. Return R1, R2 and R3 only."},
            ],
        )
    except Exception as exc:
        raise RuntimeError(f"Groq request failed: {exc}") from exc

    raw = (completion.choices[0].message.content or "").strip()
    replies = _parse_replies(raw)

    if len(replies) != 3:
        raise RuntimeError(f"Groq returned {len(replies)} valid replies instead of 3")

    return replies


def validate_replies(replies: list[str] | None) -> bool:
    if not replies or len(replies) != 3:
        return False
    return all(_valid_reply(reply) for reply in replies) and len(set(replies)) == 3


def validate_reply(reply: str | None) -> bool:
    if reply is None:
        return False
    return _valid_reply(reply)
