import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWITTERAPIS_API_KEY
from bot.db import get_db, get_pending_reply, mark_reply_posted, mark_reply_rejected, record_activity
from bot.x.provider import get_x_provider


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
) -> None:
    """Send a newly detected X post and optional reply suggestion to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

    clean_text = text.strip()
    message = f"🟢 NEW POST\n\n{handle}\n\n{clean_text}"

    if url:
        message += f"\n\n🔗 {url}"

    reply_markup = None
    if suggested_reply:
        message += f"\n\n💬 Suggested reply ({len(suggested_reply)} chars):\n{suggested_reply}"
        if post_id:
            reply_markup = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve:{post_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject:{post_id}"),
                ]]
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
    await update.message.reply_text(
        "X-Bot is online.\n\nUse /status to check the bot."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text("🟢 X-Bot online\nManual approval mode: ON")


async def approve_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: /reply POST_ID")
        return

    post_id = context.args[0].strip()
    db = get_db()
    pending = get_pending_reply(db, post_id)

    if not pending:
        await update.message.reply_text("No pending reply found for that post.")
        return

    suggested_reply = str(pending["suggested_reply"]).strip()
    handle = str(pending.get("handle", ""))

    try:
        provider = get_x_provider()
        result = provider.create_reply(suggested_reply, post_id)
        reply_id = str(result.get("tweet_id", "")) or None
        reply_url = result.get("url") or None
        mark_reply_posted(db, post_id, reply_id, reply_url)
        record_activity(
            db,
            "reply_approved",
            handle,
            post_id,
            f"Manual reply posted: {suggested_reply} | reply_id={reply_id or ''} | url={reply_url or ''}",
        )

        confirmation = f"✅ Reply posted\n\n{suggested_reply}"
        if reply_url:
            confirmation += f"\n\n🔗 {reply_url}"
        await update.message.reply_text(confirmation)
    except Exception as exc:
        record_activity(db, "error", handle, post_id, "Failed to post approved reply")
        await update.message.reply_text(f"❌ Failed to post reply: {exc}")


async def reject_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: /skip POST_ID")
        return

    post_id = context.args[0].strip()
    db = get_db()
    pending = get_pending_reply(db, post_id)

    if not pending:
        await update.message.reply_text("No pending reply found for that post.")
        return

    mark_reply_rejected(db, post_id)
    handle = str(pending.get("handle", ""))
    record_activity(db, "reply_rejected", handle, post_id, "Manual reply rejected")
    await update.message.reply_text("⏭️ Reply rejected.")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("reply", approve_reply))
    application.add_handler(CommandHandler("skip", reject_reply))
    application.run_polling(allowed_updates=Update.ALL_TYPES)
