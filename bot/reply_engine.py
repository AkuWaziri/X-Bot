import json
import urllib.error
import urllib.request

from bot.config import GROQ_API_KEY, GROQ_MODEL, MAX_REPLY_CHARS, MIN_REPLY_CHARS

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = f"""You write replies for a real person on X.

Your job is to respond naturally to the exact post you receive.

Rules:
- Reply must be {MIN_REPLY_CHARS}-{MAX_REPLY_CHARS} characters, including spaces and punctuation.
- Sound like a human who actually read the post.
- Be specific to the post. React to its idea, question, joke, observation, or situation.
- Never use generic filler such as: Great post, Interesting, Absolutely, Well said, This, Exactly, Love this.
- Do not summarize the post.
- Do not mention that you are an AI.
- Do not explain your reasoning.
- Do not use hashtags unless the post clearly calls for one.
- Avoid emojis unless one genuinely fits the conversation.
- Do not invent facts.
- If the post is only a greeting, engagement bait, giveaway, obvious spam, or something with no natural conversational opening, return NO_REPLY.
- Return exactly one reply or NO_REPLY. No quotation marks, labels, or extra text.
"""


def generate_reply(post_text: str) -> str | None:
    """Generate one human-style reply suggestion, or None when no reply fits."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.85,
        "max_tokens": 80,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Post:\n{post_text}\n\nWrite the reply now.",
            },
        ],
    }

    request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Groq HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Groq connection error: {exc.reason}") from exc

    choices = result.get("choices", [])
    if not choices:
        return None

    reply = str(choices[0].get("message", {}).get("content", "")).strip()
    reply = reply.strip('"').strip()

    if reply.upper() == "NO_REPLY":
        return None

    if not (MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS):
        return None

    return reply
