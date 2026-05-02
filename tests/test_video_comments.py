import pytest

from services.videos import add_video_comment, list_video_comments, publish_video
from tests.video_test_helpers import actor, seed_cloud_file, video_test_db


def test_video_comments_support_replies_and_reject_script_markup():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")

    root = add_video_comment(conn, actor=actor(2, "viewer"), video_id=video["id"], content="first")
    reply = add_video_comment(conn, actor=actor(1, "owner"), video_id=video["id"], content="reply", parent_id=root["id"])
    comments = list_video_comments(conn, actor=actor(2, "viewer"), video_id=video["id"])

    assert [item["content"] for item in comments] == ["first", "reply"]
    assert reply["parent_id"] == root["id"]
    assert conn.execute("SELECT comment_count FROM videos WHERE id=?", (video["id"],)).fetchone()[0] == 2

    with pytest.raises(ValueError, match="unsafe"):
        add_video_comment(conn, actor=actor(2, "viewer"), video_id=video["id"], content="<script>alert(1)</script>")
