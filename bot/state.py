import json
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).resolve().parent.parent / "config" / "state.json"


def load_state() -> dict[str, Any]:
    """Load local monitor state, creating the default structure when needed."""
    if not STATE_FILE.exists():
        return {"seen_posts": [], "reply_history": []}

    with STATE_FILE.open("r", encoding="utf-8") as file:
        state = json.load(file)

    state.setdefault("seen_posts", [])
    state.setdefault("reply_history", [])
    return state


def save_state(state: dict[str, Any]) -> None:
    """Persist monitor state to the repository workspace."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)
        file.write("\n")


def is_seen(state: dict[str, Any], post_id: str) -> bool:
    return post_id in state.get("seen_posts", [])


def mark_seen(state: dict[str, Any], post_id: str) -> None:
    seen_posts = state.setdefault("seen_posts", [])
    if post_id not in seen_posts:
        seen_posts.append(post_id)


def replied_today(state: dict[str, Any], username: str, today_utc: str) -> bool:
    for item in state.get("reply_history", []):
        if item.get("username", "").lower() == username.lower() and item.get("date_utc") == today_utc:
            return True
    return False


def record_reply(state: dict[str, Any], username: str, post_id: str, date_utc: str) -> None:
    state.setdefault("reply_history", []).append(
        {"username": username, "post_id": post_id, "date_utc": date_utc}
    )
