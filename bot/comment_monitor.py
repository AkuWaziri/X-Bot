"""Poll replies to the owner's X posts and deliver Groq reply options to Telegram."""
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import TELEGRAM_CHAT_ID
from bot.db import get_db, save_pending_replies
from bot.reply_engine import generate_replies, validate_replies
from bot.x.provider import get_x_provider

logger = logging.getLogger(__name__)

OWNER_HANDLE = "akuwazir"
COMMENT_SEARCH_QUERY = "to:akuwazir"
OWN_POST_SCAN_LIMIT = 100
COMMENT_SEARCH_LIMIT = 100


def _root_post_id(post) -> str | None:
    raw = post.raw if isinstance(post.raw, dict) else {}
    for key in ("conversation_id", "conversation_id_str"):
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    for key in ("in_reply_to_status_id", "in_reply_to_status_id_str", "in_reply_to_tweet_id"):
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _already_notified(db, comment_id: str) -> bool:
    result = (
        db.table("notified_comments")
        .select("comment_id")
        .eq("comment_id", str(comment_id))
        .limit(1)
        .execute()
    )
    return bool(result.data)


def _owned_post_ids(db) -> set[str]:
    result = (
        db.table("owned_posts")
        .select("post_id")
        .order("posted_at", desc=True)
        .limit(5000)
        .execute()
    )
    return {str(row.get("post_id")) for row in (result.data or []) if row.get("post_id")}


def _remember_owned_posts(db, posts) -> set[str]:
    rows = []
    for post in posts:
        if post.username.lstrip("@").lower() != OWNER_HANDLE:
            continue
        rows.append({
            "post_id": str(post.id),
            "post_url": post.url or f"https://x.com/{OWNER_HANDLE}/status/{post.id}",
            "post_text": post.text,
            "posted_at": post.created_at,
        })
    if rows:
        db.table("owned_posts").upsert(rows, on_conflict="post_id").execute()
    return {row["post_id"] for row in rows}


def _notify_comment(db, bot, comment, root_post_id: str) -> bool:
    if _already_notified(db, comment.id):
        return False

    author = f"@{comment.username.lstrip('@')}"
    replies = generate_replies(
        comment.text,
        request_timeout=15.0,
        max_retries=0,
        usage_class="comments",
    )
    if not replies or not validate_replies(replies):
        raise RuntimeError("Groq did not return three valid comment reply suggestions")

    # The existing manual-reply callback posts to the pending row's post_id.
    # For this feature that ID is the comment ID, so the selected reply targets
    # the exact comment rather than the root post.
    save_pending_replies(db, str(comment.id), author, comment.text, replies)

    root_url = f"https://x.com/{OWNER_HANDLE}/status/{root_post_id}"
    comment_url = comment.url or f"https://x.com/{comment.username}/status/{comment.id}"
    message = (
        "💬 NEW COMMENT ON YOUR POST\n\n"
        f"{author}\n\n"
        f"{comment.text.strip()[:1600]}\n\n"
        f"📝 YOUR POST: {root_url}\n"
        f"🔗 COMMENT: {comment_url}\n\n"
        "REPLY SUGGESTIONS"
    )
    for index, reply in enumerate(replies, start=1):
        message += f"\n\n{index}. {reply} ({len(reply)} chars)"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ POST REPLY 1", callback_data=f"select:1:{comment.id}")],
        [InlineKeyboardButton("2️⃣ POST REPLY 2", callback_data=f"select:2:{comment.id}")],
        [InlineKeyboardButton("3️⃣ POST REPLY 3", callback_data=f"select:3:{comment.id}")],
        [InlineKeyboardButton("❌ REJECT ALL", callback_data=f"reject:{comment.id}")],
    ])
    bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message[:4096],
        reply_markup=keyboard,
    )
    db.table("notified_comments").insert({
        "comment_id": str(comment.id),
        "root_post_id": str(root_post_id),
        "author_handle": author,
        "comment_text": comment.text,
        "comment_url": comment_url,
        "notified_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    logger.info(
        "OWN POST COMMENT DELIVERED | owner=@%s | root_post=%s | comment=%s | author=%s",
        OWNER_HANDLE, root_post_id, comment.id, author,
    )
    return True


def scan_owned_post_comments(bot) -> dict[str, int]:
    """Scan replies addressed to @akuwazir and keep only threads rooted at our posts."""
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

    provider = get_x_provider()
    if not hasattr(provider, "search_replies"):
        raise RuntimeError(
            "The configured X provider does not support reply-inclusive search; "
            "set X_PROVIDER_MODE=fxtwitter on Render."
        )

    db = get_db()
    own_posts = provider.get_latest_posts(f"@{OWNER_HANDLE}", limit=OWN_POST_SCAN_LIMIT)
    newly_seen = _remember_owned_posts(db, own_posts)
    owned_ids = _owned_post_ids(db)
    logger.info(
        "OWN POST COMMENT SCAN | owner=@%s | timeline_posts=%d | known_owned_posts=%d | newly_seen=%d",
        OWNER_HANDLE, len(own_posts), len(owned_ids), len(newly_seen),
    )

    comments = provider.search_replies(COMMENT_SEARCH_QUERY, limit=COMMENT_SEARCH_LIMIT)
    delivered = 0
    skipped = 0
    deferred = 0
    seen_this_scan: set[str] = set()

    for comment in comments:
        comment_id = str(comment.id)
        if not comment_id or comment_id in seen_this_scan:
            continue
        seen_this_scan.add(comment_id)

        if comment.username.lstrip("@").lower() == OWNER_HANDLE:
            skipped += 1
            continue

        root_id = _root_post_id(comment)
        if not root_id or root_id not in owned_ids:
            skipped += 1
            continue

        if _already_notified(db, comment_id):
            skipped += 1
            continue

        try:
            if _notify_comment(db, bot, comment, root_id):
                delivered += 1
        except Exception as exc:
            deferred += 1
            logger.warning(
                "OWN POST COMMENT DEFERRED | comment=%s | root_post=%s | error=%s",
                comment_id, root_id, str(exc)[:350],
            )

    logger.info(
        "OWN POST COMMENT SCAN COMPLETE | found=%d | delivered=%d | skipped=%d | deferred=%d",
        len(comments), delivered, skipped, deferred,
    )
    return {
        "found": len(comments),
        "delivered": delivered,
        "skipped": skipped,
        "deferred": deferred,
    }


async def comment_monitor_loop(application) -> None:
    """Run independently of the scheduled feed and /project handlers."""
    import asyncio

    interval = max(60, int(__import__("os").getenv("OWN_POST_COMMENT_SCAN_SECONDS", "120")))
    logger.info(
        "OWN POST COMMENT MONITOR STARTED | owner=@%s | interval_seconds=%d",
        OWNER_HANDLE, interval,
    )
    while True:
        try:
            await asyncio.to_thread(scan_owned_post_comments, application.bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("OWN POST COMMENT SCAN FAILED")
        await asyncio.sleep(interval)
