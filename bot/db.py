import logging

from supabase import Client, create_client

from bot.config import SUPABASE_SECRET_KEY, SUPABASE_URL


def get_db() -> Client:
    """Create a Supabase client using the server-side secret key."""
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL is not configured")
    if not SUPABASE_SECRET_KEY:
        raise RuntimeError("SUPABASE_SECRET_KEY is not configured")
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)



def diagnose_supabase_connection() -> None:
    """Run a read-only startup diagnostic without exposing credentials."""
    logger = logging.getLogger(__name__)
    key = SUPABASE_SECRET_KEY or ""
    key_kind = "sb_secret" if key.startswith("sb_secret_") else (
        "legacy_jwt" if key.startswith("eyJ") else ("other" if key else "missing")
    )
    logger.warning(
        "SUPABASE DIAGNOSTIC | url_configured=%s | secret_key_configured=%s | key_kind=%s | key_length=%d",
        bool(SUPABASE_URL), bool(key), key_kind, len(key),
    )
    try:
        db = get_db()
        session = getattr(getattr(db, "postgrest", None), "session", None)
        headers = getattr(session, "headers", {}) or {}
        api_key_header = str(headers.get("apikey", ""))
        auth_header = str(headers.get("Authorization", ""))
        auth_value = auth_header.removeprefix("Bearer ").strip()
        def key_type(value: str) -> str:
            if value.startswith("sb_secret_"):
                return "sb_secret"
            if value.startswith("eyJ"):
                return "legacy_jwt"
            return "other" if value else "missing"
        logger.warning(
            "SUPABASE DIAGNOSTIC HEADERS | apikey_present=%s | apikey_kind=%s | authorization_present=%s | authorization_kind=%s",
            bool(api_key_header), key_type(api_key_header), bool(auth_header), key_type(auth_value),
        )
        result = db.table("owned_posts").select("post_id").limit(1).execute()
        logger.warning("SUPABASE DIAGNOSTIC READ | table=owned_posts | success=true | rows=%d", len(result.data or []))
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        code = getattr(exc, "code", None)
        message = str(getattr(exc, "message", "") or exc)[:300]
        logger.error(
            "SUPABASE DIAGNOSTIC READ | table=owned_posts | success=false | status=%s | code=%s | error=%s",
            status, code, message,
        )

def post_seen(db: Client, post_id: str) -> bool:
    result = db.table("posts_seen").select("post_id").eq("post_id", post_id).limit(1).execute()
    return bool(result.data)


def save_post(db: Client, post) -> None:
    db.table("posts_seen").insert(
        {
            "post_id": post.id,
            "handle": f"@{post.username.lstrip('@')}",
            "post_text": post.text,
            "post_url": post.url,
            "posted_at": post.created_at,
        }
    ).execute()


def save_pending_replies(
    db: Client,
    post_id: str,
    handle: str,
    post_text: str,
    replies: list[str],
) -> None:
    if len(replies) != 3:
        raise ValueError("Exactly three replies are required")

    db.table("pending_replies").upsert(
        {
            "post_id": post_id,
            "handle": handle,
            "post_text": post_text,
            # Keep the legacy required column populated while the new
            # three-option columns are used by the bot.
            "suggested_reply": replies[0],
            "reply_1": replies[0],
            "reply_2": replies[1],
            "reply_3": replies[2],
            "selected_reply": None,
            "status": "pending",
        },
        on_conflict="post_id",
    ).execute()


def get_pending_reply(db: Client, post_id: str) -> dict | None:
    result = (
        db.table("pending_replies")
        .select("*")
        .eq("post_id", post_id)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_reply_selected(db: Client, post_id: str, reply_number: int) -> bool:
    """Atomically claim a pending reply option for manual posting."""
    if reply_number not in (1, 2, 3):
        raise ValueError("Reply number must be 1, 2, or 3")
    result = (
        db.table("pending_replies")
        .update({"selected_reply": reply_number, "status": "selected"})
        .eq("post_id", post_id)
        .eq("status", "pending")
        .select("post_id")
        .execute()
    )
    return bool(result.data)


def mark_reply_posted(db: Client, post_id: str, reply_id: str | None = None, reply_url: str | None = None) -> None:
    updates = {"status": "posted"}
    if reply_id:
        updates["reply_id"] = reply_id
    if reply_url:
        updates["reply_url"] = reply_url
    db.table("pending_replies").update(updates).eq("post_id", post_id).eq("status", "selected").execute()


def mark_reply_rejected(db: Client, post_id: str) -> None:
    db.table("pending_replies").update({"status": "rejected"}).eq("post_id", post_id).eq("status", "pending").execute()


def mark_reply_pending(db: Client, post_id: str) -> None:
    db.table("pending_replies").update({"selected_reply": None, "status": "pending"}).eq("post_id", post_id).eq("status", "selected").execute()


def record_activity(db: Client, event_type: str, handle: str, post_id: str | None, message: str) -> None:
    db.table("activity_log").insert(
        {
            "event_type": event_type,
            "handle": handle,
            "post_id": post_id,
            "message": message,
        }
    ).execute()


def project_post_sent(db: Client, post_id: str) -> bool:
    """Return True when this X post has already been delivered by any /project query."""
    result = (
        db.table("activity_log")
        .select("id")
        .eq("event_type", "project_post_sent")
        .eq("post_id", str(post_id))
        .limit(1)
        .execute()
    )
    return bool(result.data)


def mark_project_post_sent(db: Client, post_id: str, handle: str, query: str) -> None:
    """Persist global /project delivery history, independent of the search query."""
    record_activity(db, "project_post_sent", handle, str(post_id), f"Delivered by /project query: {query}")
