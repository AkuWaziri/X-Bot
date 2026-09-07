import re

from groq import Groq

from bot.config import GROQ_API_KEY, GROQ_MODEL, MAX_REPLY_CHARS, MIN_REPLY_CHARS

SYSTEM_PROMPT = f"""You write replies for a real person on X.

Write one natural response to the exact post you receive.

Rules:
- Reply must be {MIN_REPLY_CHARS}-{MAX_REPLY_CHARS} characters, including spaces and punctuation.
- Sound like a human who actually read the post.
- React to the specific idea, question, joke, observation, or situation in the post.
- Add a thought, reaction, or natural conversational hook when possible.
- Never use generic filler such as: Great post, Interesting, Absolutely, Well said, This, Exactly, Love this.
- Never use phrases like "That's the key bit", "That part matters", or "That's a big signal" unless the post genuinely makes that exact point.
- Do not summarize the post.
- Do not mention AI or the instruction.
- Do not invent facts.
- Avoid hashtags unless directly relevant.
- Use emojis only when they genuinely fit.
- If there is no natural reason to reply, return NO_REPLY.
- Return exactly one reply or NO_REPLY. No quotation marks, labels, or explanations.
"""


def _clean_reply(reply: str) -> str:
    reply = re.sub(r"\s+", " ", reply.strip())
    return reply.strip('"').strip()


def generate_reply(post_text: str) -> str | None:
    """Generate one human-style reply suggestion, or None when no reply fits."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    client = Groq(api_key=GROQ_API_KEY)

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.85,
            max_completion_tokens=100,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Post:\n{post_text}\n\nReply:"},
            ],
        )
    except Exception as exc:
        raise RuntimeError(f"Groq request failed: {exc}") from exc

    reply = _clean_reply(completion.choices[0].message.content or "")

    if reply.upper() == "NO_REPLY":
        return None

    if not (MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS):
        return None

    return reply


def validate_reply(reply: str | None) -> bool:
    if reply is None:
        return False
    return MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS
