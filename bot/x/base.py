from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Post:
    id: str
    text: str
    username: str
    created_at: str | None = None
    url: str | None = None
    raw: dict[str, Any] | None = None


def is_reply_payload(raw: dict[str, Any] | None, post_id: str | None = None) -> bool:
    """Identify replies using provider metadata, including nested legacy payloads."""
    if not isinstance(raw, dict):
        return False

    containers = [raw]
    for key in ("legacy", "tweet", "status", "data", "result", "reply_metadata"):
        value = raw.get(key)
        if isinstance(value, dict):
            containers.append(value)

    reply_fields = (
        "in_reply_to_status_id", "in_reply_to_status_id_str",
        "in_reply_to_tweet_id", "inReplyToTweetId", "inReplyToStatusId",
        "replying_to", "reply_to", "reply_to_id", "reply_to_status_id",
        "in_reply_to", "in_reply_to_user_id", "in_reply_to_user_id_str",
        "inReplyToUserId", "reply_to_user_id",
    )
    for payload in containers:
        for field in reply_fields:
            value = payload.get(field)
            if value not in (None, "", 0, False, [], {}):
                return True

        # On X, an original post's conversation ID is its own ID. Replies
        # retain the root post's conversation ID, even when reply_to fields
        # are omitted by a provider.
        conversation_id = payload.get("conversation_id") or payload.get("conversation_id_str")
        if conversation_id not in (None, "") and post_id not in (None, ""):
            if str(conversation_id) != str(post_id):
                return True

        if payload.get("is_reply") is True or payload.get("isReply") is True:
            return True
        if str(payload.get("type") or "").strip().lower() == "reply":
            return True

    return False


class XProvider:
    """Interface for fetching public X posts and performing X actions."""

    def get_latest_posts(self, handle: str, limit: int = 20) -> list[Post]:
        raise NotImplementedError

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        raise NotImplementedError

    def create_reply(self, text: str, reply_to: str) -> dict[str, Any]:
        raise NotImplementedError
