from supabase import Client, create_client

from bot.config import SUPABASE_SECRET_KEY, SUPABASE_URL


def get_db() -> Client:
    """Create a Supabase client using the server-side secret key."""
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL is not configured")
    if not SUPABASE_SECRET_KEY:
        raise RuntimeError("SUPABASE_SECRET_KEY is not configured")
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


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


def mark_reply_selected(db: Client, post_id: str, reply_number: int) -> None:
    if reply_number not in (1, 2, 3):
        raise ValueError("Reply number must be 1, 2, or 3")
    db.table("pending_replies").update(
        {"selected_reply": reply_number, "status": "selected"}
    ).eq("post_id", post_id).eq("status", "pending").execute()


def mark_reply_posted(db: Client, post_id: str, reply_id: str | None = None, reply_url: str | None = None) -> None:
    updates = {"status": "posted"}
    if reply_id:
        updates["reply_id"] = reply_id
    if reply_url:
        updates["reply_url"] = reply_url
    db.table("pending_replies").update(updates).eq("post_id", post_id).eq("status", "selected").execute()


def mark_reply_rejected(db: Client, post_id: str) -> None:
    db.table("pending_replies").update({"status": "rejected"}).eq("post_id", post_id).eq("status", "pending").execute()


def record_activity(db: Client, event_type: str, handle: str, post_id: str | None, message: str) -> None:
    db.table("activity_log").insert(
        {
            "event_type": event_type,
            "handle": handle,
            "post_id": post_id,
            "message": message,
        }
    ).execute()
