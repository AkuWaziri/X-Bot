import asyncio
import logging
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
    save_pending_replies,
)
from bot.x.provider import get_x_provider
from bot.project_search import search_project_posts, normalize_handle
from bot.reply_engine import generate_replies


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

    await query.answer("Posting selected reply...")

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
        await query.answer("This reply is no longer pending.", show_alert=True)
        return

    reply_text = str(pending.get(f"reply_{reply_number}") or "").strip()
    if not reply_text:
        await query.answer("Selected reply is empty.", show_alert=True)
        return

    mark_reply_selected(db, post_id, int(reply_number))
    try:
        result = await asyncio.to_thread(
            get_x_provider().create_reply,
            reply_text,
            post_id,
        )
        reply_id = str(result.get("id") or result.get("reply_id") or "").strip() or None
        reply_url = str(result.get("url") or result.get("reply_url") or "").strip() or None
        mark_reply_posted(db, post_id, reply_id=reply_id, reply_url=reply_url)
        record_activity(db, "reply_posted", pending.get("handle", ""), post_id, f"Manual reply {reply_number} posted")
    except Exception as exc:
        mark_reply_pending(db, post_id)
        error_text = str(exc).strip() or exc.__class__.__name__
        record_activity(db, "reply_failed", pending.get("handle", ""), post_id, f"Manual reply failed: {error_text}")
        try:
            await query.message.reply_text(
                "❌ REPLY FAILED\n\n"
                f"{pending.get('handle', '')}\n\n"
                f"{error_text[:1000]}\n\n"
                "The reply remains pending. You can try another option."
            )
        except Exception:
            pass
        return

    await query.edit_message_reply_markup(reply_markup=None)
    confirmation = f"✅ Reply {reply_number} posted to {pending.get('handle', '')}"
    if reply_url:
        confirmation += f"\n{reply_url}"
    await query.message.reply_text(confirmation)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "X-Bot is online.\n\nUse /status to check the bot.\n"
        "Use /project <handle> to search recent posts about any project."
    )


def _project_post_entry(index: int, post, replies: list[str] | None) -> str:
    from datetime import datetime, timezone

    created_at = post.created_at or "time unavailable"
    try:
        parsed = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        created_at = parsed.astimezone(timezone.utc).strftime("%H:%M UTC")
    except (TypeError, ValueError):
        pass

    post_text = post.text.strip()
    if len(post_text) > 850:
        post_text = post_text[:847].rstrip() + "..."
    entry = (
        f"{index}. @{post.username} · {created_at}\n"
        f"{post_text}\n"
        f"🔗 {post.url or f'https://x.com/{post.username}/status/{post.id}'}"
    )
    if replies and len(replies) == 3:
        entry += "\n\n💬 REPLY OPTIONS"
        for number, reply in enumerate(replies, start=1):
            entry += f"\n{number}. {reply} ({len(reply)} chars)"
    else:
        entry += "\n\n⚠️ Reply options could not be generated for this post."
    return entry


async def _run_project_search(update: Update, context: ContextTypes.DEFAULT_TYPE, handle: str) -> None:
    chat_id = update.effective_chat.id
    try:
        posts = await asyncio.to_thread(search_project_posts, handle, limit=35, window_minutes=180)
    except Exception as exc:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Project search failed.\n\n{str(exc)[:900]}",
        )
        return

    if not posts:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔎 No posts mentioning or discussing @{handle} were found in the last 3 hours.",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🔎 PROJECT SEARCH: @{handle}\n"
            f"Last 3 hours · {len(posts)} post(s)\n"
            "Tap a reply button below any post to publish it as a reply to that X post."
        ),
    )

    db = None
    try:
        db = await asyncio.to_thread(get_db)
    except Exception as exc:
        logging.warning("PROJECT SEARCH DB INIT FAILED | error=%s", str(exc)[:200])

    for index, post in enumerate(posts, start=1):
        replies = None
        allow_buttons = False
        reply_note = None
        existing = None
        storage_available = db is not None

        if db is not None:
            try:
                existing_result = await asyncio.to_thread(
                    lambda post_id=str(post.id): db.table("pending_replies")
                    .select("*")
                    .eq("post_id", post_id)
                    .limit(1)
                    .execute()
                )
                existing = existing_result.data[0] if existing_result.data else None
            except Exception as exc:
                storage_available = False
                reply_note = "Pending-reply storage could not be read; suggestions will be shown without posting buttons."
                logging.warning(
                    "PROJECT PENDING LOOKUP FAILED | post_id=%s | error=%s",
                    post.id,
                    str(exc)[:200],
                )

        if existing and existing.get("status") == "pending":
            stored = [
                str(existing.get("reply_1") or "").strip(),
                str(existing.get("reply_2") or "").strip(),
                str(existing.get("reply_3") or "").strip(),
            ]
            if all(stored):
                replies = stored
                allow_buttons = True
            else:
                reply_note = "Saved pending replies were incomplete; generating fresh suggestions."
        elif existing:
            # Show useful suggestions for previously seen posts, but never
            # expose posting buttons for a post already selected, posted, or rejected.
            reply_note = f"This post is already marked {existing.get('status', 'handled')}; suggestions are view-only to prevent duplicate replies."

        if replies is None:
            try:
                replies = await asyncio.to_thread(generate_replies, post.text)
                if replies and len(replies) == 3:
                    if existing is None and storage_available:
                        try:
                            await asyncio.to_thread(
                                save_pending_replies,
                                db,
                                str(post.id),
                                f"@{post.username.lstrip('@')}",
                                post.text,
                                replies,
                            )
                            allow_buttons = True
                        except Exception as exc:
                            reply_note = "Suggestions were generated, but pending-reply storage failed; buttons are disabled."
                            logging.warning(
                                "PROJECT PENDING SAVE FAILED | post_id=%s | error=%s",
                                post.id,
                                str(exc)[:200],
                            )
                    elif existing is None and not storage_available:
                        reply_note = "Suggestions are view-only because pending-reply storage is unavailable."
            except Exception as exc:
                replies = None
                reply_note = f"Reply generation failed: {str(exc)[:220]}"
                logging.warning(
                    "PROJECT REPLY PREPARATION FAILED | post_id=%s | error=%s",
                    post.id,
                    str(exc)[:200],
                )

        entry = _project_post_entry(index, post, replies)
        reply_markup = None
        if replies and len(replies) == 3 and storage_available and allow_buttons:
            reply_markup = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("1️⃣ POST REPLY 1", callback_data=f"select:1:{post.id}")],
                    [InlineKeyboardButton("2️⃣ POST REPLY 2", callback_data=f"select:2:{post.id}")],
                    [InlineKeyboardButton("3️⃣ POST REPLY 3", callback_data=f"select:3:{post.id}")],
                    [InlineKeyboardButton("❌ REJECT ALL", callback_data=f"reject:{post.id}")],
                ]
            )
        elif replies and len(replies) == 3 and not reply_note:
            reply_note = "Suggestions are view-only; this post is not eligible for another reply."

        if reply_note:
            entry += f"\n\nℹ️ {reply_note}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=entry[:4096],
            reply_markup=reply_markup,
        )
        # Keep Telegram's per-chat message rate comfortably below its limit.
        if index < len(posts):
            await asyncio.sleep(1.1)


async def project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update) or update.effective_message is None:
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /project <x_handle>\nExample: /project primus_labs"
        )
        return
    try:
        handle = normalize_handle(context.args[0])
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await update.effective_message.reply_text(
        f"🔎 Searching for posts about @{handle} from the last 3 hours. "
        "I’ll send up to 35 results with 3 reply options each."
    )
    context.application.create_task(_run_project_search(update, context, handle), update=update)


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
    application.add_handler(CommandHandler("project", project))
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
