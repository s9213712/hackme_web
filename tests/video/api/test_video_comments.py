import pytest

from services.media.videos import add_video_comment, create_video_social_share, get_video, list_video_comments, publish_video
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


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


def test_video_social_share_counts_and_interaction_score():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")

    share, msg = create_video_social_share(conn, actor=actor(2, "viewer"), video_id=video["id"])
    hydrated = get_video(conn, video["id"], actor=actor(2, "viewer"))

    assert msg is None
    assert share["url"].startswith("/shared/videos/")
    assert hydrated["share_count"] == 1
    assert hydrated["interaction_score"] >= 5


def test_video_social_share_rejects_private_video():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo", visibility="private")

    share, msg = create_video_social_share(conn, actor=actor(1, "owner"), video_id=video["id"])

    assert share is None
    assert "公開" in msg
