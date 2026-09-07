import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.db import get_db, get_pending_reply, mark_reply_rejected, mark_reply_selected, record_activity


def _authorized(update: Update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return bool(TELEGRAM_CHAT_ID) and chat_id == TELEGRAM_CHAT_ID


def send_new_post(
    handle: str,
    text: str,
    url: str | None = None,
    reply_score: int | None = None,
    suggested_reply: str | None = None,
    reply_reason: str | None = None,
    post_id: str | None = None,
    suggested_replies: list[str] | None = None,
) -> None:
    """Send a newly detected X post and up to three reply suggestions to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

    clean_text = text.strip()
    message = f"🟢 NEW POST\n\n{handle}\n\n{clean_text}"

    if url:
        message += f"\n\n🔗 {url}"

    replies = suggested_replies or ([] if not suggested_reply else [suggested_reply])
    reply_markup = None

    if replies:
        message += "\n\n💬 REPLY OPTIONS"
        for index, reply in enumerate(replies[:3], start=1):
            message += f"\n\n{index}️⃣ {reply} ({len(reply)} chars)"

        if post_id and len(replies) == 3:
            reply_markup = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("1️⃣ SELECT REPLY 1", callback_data=f"select:1:{post_id}")],
                    [InlineKeyboardButton("2️⃣ SELECT REPLY 2", callback_data=f"select:2:{post_id}")],
                    [InlineKeyboardButton("3️⃣ SELECT REPLY 3", callback_data=f"select:3:{post_id}")],
                    [InlineKeyboardButton("❌ REJECT ALL", callback_data=f"reject:{post_id}")],
                ]
            )
    elif reply_reason:
        message += f"\n\nNo suggestion: {reply_reason}"

    message = message[:4096]

    async def _send() -> None:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                reply_markup=reply_markup,
            )

    asyncio.run(_send())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text("X-Bot is online.\n\nUse /status to check the bot.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text("🟢 X-Bot online\nManual reply selection: ON")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.run_polling(allowed_updates=Update.ALL_TYPES)
