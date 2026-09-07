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


def save_pending_reply(
    db: Client,
    post_id: str,
    handle: str,
    post_text: str,
    suggested_reply: str,
) -> None:
    db.table("pending_replies").upsert(
        {
            "post_id": post_id,
            "handle": handle,
            "post_text": post_text,
            "suggested_reply": suggested_reply,
            "status": "pending",
        },
        on_conflict="post_id",
    ).execute()


def record_activity(db: Client, event_type: str, handle: str, post_id: str | None, message: str) -> None:
    db.table("activity_log").insert(
        {
            "event_type": event_type,
            "handle": handle,
            "post_id": post_id,
            "message": message,
        }
    ).execute()
