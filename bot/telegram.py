import asyncio

from telegram import Bot

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_new_post(
    handle: str,
    text: str,
    url: str | None = None,
    reply_score: int | None = None,
    suggested_reply: str | None = None,
    reply_reason: str | None = None,
    post_id: str | None = None,
) -> None:
    """Send a newly detected X post and optional reply analysis to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

    clean_text = text.strip()
    message = f"🟢 NEW POST\n\n{handle}\n\n{clean_text}"

    if url:
        message += f"\n\n🔗 {url}"

    if reply_score is not None:
        message += f"\n\n💬 Reply opportunity: {reply_score}%"
        if suggested_reply:
            message += f"\nSuggested ({len(suggested_reply)} chars):\n{suggested_reply}"
            if post_id:
                message += f"\n\n/reply {post_id}"
        elif reply_reason:
            message += f"\nNo suggestion: {reply_reason}"

    # Telegram messages are limited to 4096 characters.
    message = message[:4096]

    async def _send() -> None:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

    asyncio.run(_send())
