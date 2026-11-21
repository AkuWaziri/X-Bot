from bot.comment_monitor import _root_post_id
from bot.x.base import Post
from bot.x.fxtwitter import FxTwitterProvider


def test_fxtwitter_reply_is_only_included_for_reply_search():
    item = {
        "type": "status",
        "id": "comment-1",
        "text": "reply under the post",
        "created_at": "2026-11-13T18:00:00Z",
        "conversation_id": "root-post-1",
        "in_reply_to_status_id": "root-post-1",
        "author": {"screen_name": "commenter"},
    }

    assert FxTwitterProvider._to_post(item) is None

    reply = FxTwitterProvider._to_post(item, include_replies=True)
    assert reply is not None
    assert reply.id == "comment-1"
    assert _root_post_id(reply) == "root-post-1"


def test_root_post_id_prefers_conversation_id_for_threaded_comments():
    comment = Post(
        id="nested-comment",
        text="nested reply",
        username="someone",
        raw={
            "conversation_id": "my-original-post",
            "in_reply_to_status_id": "another-comment",
        },
    )

    assert _root_post_id(comment) == "my-original-post"


def test_comment_search_is_bound_to_the_owner_handle():
    from bot.comment_monitor import COMMENT_SEARCH_QUERY, OWNER_HANDLE

    assert OWNER_HANDLE == "akuwazir"
    assert COMMENT_SEARCH_QUERY == "to:akuwazir"


def test_remember_owned_posts_deduplicates_conflict_keys_before_upsert():
    from bot.comment_monitor import _remember_owned_posts

    class FakeTable:
        def __init__(self):
            self.rows = None
            self.conflict = None

        def upsert(self, rows, on_conflict):
            self.rows = rows
            self.conflict = on_conflict
            return self

        def execute(self):
            return type("Result", (), {"data": self.rows})()

    class FakeDB:
        def __init__(self):
            self.table_instance = FakeTable()

        def table(self, name):
            assert name == "owned_posts"
            return self.table_instance

    db = FakeDB()
    posts = [
        Post(id="post-1", text="newest copy", username="akuwazir",
             created_at="2026-11-21T12:00:00Z"),
        Post(id="post-1", text="duplicate copy", username="@AkuWaziri",
             created_at="2026-11-21T11:59:00Z"),
        Post(id="post-2", text="another post", username="akuwazir"),
        Post(id="other-1", text="not ours", username="someone"),
    ]

    remembered = _remember_owned_posts(db, posts)

    assert remembered == {"post-1", "post-2"}
    assert db.table_instance.conflict == "post_id"
    assert [row["post_id"] for row in db.table_instance.rows] == ["post-1", "post-2"]
    assert db.table_instance.rows[0]["post_text"] == "newest copy"
