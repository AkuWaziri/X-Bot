import json
import urllib.parse
import urllib.request

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.db import (
    get_db,
    get_pending_reply,
    mark_reply_posted,
    mark_reply_rejected,
    record_activity,
)
from bot.x.provider import get_x_provider


TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def telegram_call(method: str, params: dict | None = None) -> dict:
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{TELEGRAM_API}/{method}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram API error"))
    return payload


def send_message(text: str) -> None:
    telegram_call(
        "sendMessage",
        {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]},
    )


def process_reply(db, post_id: str) -> None:
    pending = get_pending_reply(db, post_id)
    if not pending:
        send_message("No pending reply found for that post.")
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

        message = f"✅ Reply posted\n\n{suggested_reply}"
        if reply_url:
            message += f"\n\n🔗 {reply_url}"
        send_message(message)
    except Exception:
        record_activity(db, "error", handle, post_id, "Failed to post approved reply")
        send_message("❌ Failed to post reply. Check the GitHub Actions log.")


def process_skip(db, post_id: str) -> None:
    pending = get_pending_reply(db, post_id)
    if not pending:
        send_message("No pending reply found for that post.")
        return

    mark_reply_rejected(db, post_id)
    handle = str(pending.get("handle", ""))
    record_activity(db, "reply_rejected", handle, post_id, "Manual reply rejected")
    send_message("⏭️ Reply rejected.")


def process_updates() -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    response = telegram_call(
        "getUpdates",
        {"limit": 100, "allowed_updates": json.dumps(["message"])},
    )
    updates = response.get("result", [])
    if not updates:
        return

    db = get_db()
    highest_update_id = None

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            highest_update_id = int(update_id)

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))

        if chat_id != str(TELEGRAM_CHAT_ID):
            continue

        text = str(message.get("text", "")).strip()
        parts = text.split()
        if not parts:
            continue

        command = parts[0].split("@", 1)[0].lower()
        post_id = parts[1] if len(parts) > 1 else ""

        if command == "/reply":
            if post_id:
                process_reply(db, post_id)
            else:
                send_message("Usage: /reply POST_ID")
        elif command == "/skip":
            if post_id:
                process_skip(db, post_id)
            else:
                send_message("Usage: /skip POST_ID")
        elif command == "/status":
            send_message("🟢 X-Bot online\nManual approval mode: ON")

    # Confirm all updates only after this batch has been processed.
    if highest_update_id is not None:
        telegram_call(
            "getUpdates",
            {
                "offset": highest_update_id + 1,
                "limit": 1,
                "allowed_updates": json.dumps(["message"]),
            },
        )


if __name__ == "__main__":
    process_updates()
