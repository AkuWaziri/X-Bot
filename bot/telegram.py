import asyncio
import os

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.db import (
    get_db,
    get_pending_reply,
    mark_reply_posted,
    mark_reply_rejected,
    mark_reply_selected,
    mark_reply_pending,
    record_activity,
)
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
    suggested_replies: list[str] | None = None,
    auto_reply_text: str | None = None,
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

    if auto_reply_text:
        message += f"\n\n🤖 AUTO REPLY SENT\n{auto_reply_text}"

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


def _parse_callback_data(data: str) -> tuple[str, int | None, str] | None:
    parts = data.split(":")
    if len(parts) == 3 and parts[0] == "select" and parts[1] in {"1", "2", "3"}:
        return "select", int(parts[1]), parts[2]
    if len(parts) == 2 and parts[0] == "reject" and parts[1]:
        return "reject", None, parts[1]
    return None


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    if not _authorized(update):
        return

    parsed = _parse_callback_data(str(query.data or ""))
    if parsed is None:
        return

    action, reply_number, post_id = parsed
    db = get_db()

    if action == "reject":
        pending = get_pending_reply(db, post_id)
        if pending is None:
            await query.edit_message_reply_markup(reply_markup=None)
            return
        mark_reply_rejected(db, post_id)
        record_activity(db, "reply_rejected", pending.get("handle", ""), post_id, "Manual reply rejected")
        await query.edit_message_reply_markup(reply_markup=None)
        return

    pending = get_pending_reply(db, post_id)
    if pending is None:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    reply_text = str(pending.get(f"reply_{reply_number}") or "").strip()
    if not reply_text:
        return

    mark_reply_selected(db, post_id, int(reply_number))
    try:
        result = get_x_provider().create_reply(reply_text, post_id)
        reply_id = str(result.get("id") or result.get("reply_id") or "").strip() or None
        reply_url = str(result.get("url") or result.get("reply_url") or "").strip() or None
        mark_reply_posted(db, post_id, reply_id=reply_id, reply_url=reply_url)
        record_activity(db, "reply_posted", pending.get("handle", ""), post_id, f"Manual reply {reply_number} posted")
    except Exception as exc:
        mark_reply_pending(db, post_id)
        record_activity(db, "reply_failed", pending.get("handle", ""), post_id, f"Manual reply failed: {exc}")
        return

    await query.edit_message_reply_markup(reply_markup=None)


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

    port = int(os.getenv("PORT", "10000"))
    base_url = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base_url:
        raise RuntimeError("WEBHOOK_URL or RENDER_EXTERNAL_URL is required for webhook mode")

    webhook_url = f"{base_url}/telegram"
    secret_token = os.getenv("TELEGRAM_WEBHOOK_SECRET")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(button_callback))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram",
        webhook_url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        secret_token=secret_token,
    )


if __name__ == "__main__":
    main()
