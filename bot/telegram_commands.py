import json
import urllib.parse
import urllib.request

from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.db import (
    get_db,
    get_pending_reply,
    mark_reply_rejected,
    mark_reply_selected,
    record_activity,
)


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
    telegram_call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]})


def answer_callback(callback_query_id: str, text: str = "") -> None:
    telegram_call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text[:200]})


def remove_buttons(chat_id: str, message_id: int) -> None:
    telegram_call(
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": json.dumps({"inline_keyboard": []}),
        },
    )


def process_select(db, post_id: str, reply_number: int) -> None:
    pending = get_pending_reply(db, post_id)
    if not pending:
        send_message("No pending reply found for that post.")
        return

    key = f"reply_{reply_number}"
    suggested_reply = str(pending.get(key, "")).strip()
    handle = str(pending.get("handle", ""))

    if not suggested_reply:
        send_message("That reply option is unavailable.")
        return

    mark_reply_selected(db, post_id, reply_number)
    record_activity(
        db,
        "reply_selected",
        handle,
        post_id,
        f"Manual reply option {reply_number} selected: {suggested_reply}",
    )

    send_message(
        f"✅ REPLY {reply_number} SELECTED\n\n"
        f"{suggested_reply}\n\n"
        "Copy it and post it manually under the original X post."
    )


def process_skip(db, post_id: str) -> None:
    pending = get_pending_reply(db, post_id)
    if not pending:
        send_message("No pending reply found for that post.")
        return

    mark_reply_rejected(db, post_id)
    handle = str(pending.get("handle", ""))
    record_activity(db, "reply_rejected", handle, post_id, "All reply suggestions rejected")
    send_message("⏭️ All reply suggestions rejected.")


def process_updates() -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    response = telegram_call(
        "getUpdates",
        {
            "limit": 100,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        },
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

        callback = update.get("callback_query")
        if callback:
            callback_message = callback.get("message") or {}
            callback_chat = callback_message.get("chat") or {}
            callback_chat_id = str(callback_chat.get("id", ""))
            if callback_chat_id != str(TELEGRAM_CHAT_ID):
                continue

            callback_data = str(callback.get("data", ""))
            parts = callback_data.split(":", 2)

            if parts[0] == "select" and len(parts) == 3:
                try:
                    reply_number = int(parts[1])
                except ValueError:
                    reply_number = 0
                if reply_number in (1, 2, 3):
                    answer_callback(str(callback.get("id", "")), f"Reply {reply_number} selected")
                    process_select(db, parts[2], reply_number)
                else:
                    answer_callback(str(callback.get("id", "")), "Invalid reply option")
            elif parts[0] == "reject" and len(parts) == 2:
                answer_callback(str(callback.get("id", "")), "All replies rejected")
                process_skip(db, parts[1])
            else:
                answer_callback(str(callback.get("id", "")), "Invalid action")

            message_id = callback_message.get("message_id")
            if message_id:
                try:
                    remove_buttons(callback_chat_id, int(message_id))
                except Exception:
                    pass
            continue

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
        if command == "/status":
            send_message("🟢 X-Bot online\nManual reply selection: ON")

    if highest_update_id is not None:
        telegram_call(
            "getUpdates",
            {
                "offset": highest_update_id + 1,
                "limit": 1,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            },
        )


if __name__ == "__main__":
    process_updates()
