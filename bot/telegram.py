import asyncio

from telegram import Bot

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_new_post(handle: str, text: str, url: str | None = None) -> None:
    """Send a newly detected X post to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

    clean_text = text.strip()
    message = f"🟢 NEW POST\n\n{handle}\n\n{clean_text}"
    if url:
        message += f"\n\n🔗 {url}"
    message += "\n\n🔎 Reply opportunity analysis coming next."

    # Telegram messages are limited to 4096 characters.
    message = message[:4096]

    async def _send() -> None:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

    asyncio.run(_send())
