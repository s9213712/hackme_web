import pytest

from services.media.videos import can_view_video, get_video, list_videos, publish_video
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


def _published(conn, visibility):
    seed_cloud_file(conn, file_id=f"file-{visibility}", owner_user_id=1, mime="video/mp4")
    return publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id=f"file-{visibility}",
        title=f"{visibility} video",
        visibility=visibility,
    )


def test_video_visibility_rules():
    conn = video_test_db()
    public = _published(conn, "public")
    unlisted = _published(conn, "unlisted")
    private = _published(conn, "private")

    assert get_video(conn, public["id"], actor=None)["visibility"] == "public"
    with pytest.raises(PermissionError):
        get_video(conn, unlisted["id"], actor=None)
    assert get_video(conn, unlisted["id"], actor=actor(1, "owner"))["visibility"] == "unlisted"
    assert get_video(conn, unlisted["id"], actor=actor(3, "manager", "manager"))["visibility"] == "unlisted"

    with pytest.raises(PermissionError):
        get_video(conn, private["id"], actor=actor(2, "viewer"))

    assert get_video(conn, private["id"], actor=actor(1, "owner"))["id"] == private["id"]
    assert get_video(conn, private["id"], actor=actor(3, "manager", "manager"))["id"] == private["id"]


def test_unlisted_video_is_link_accessible_but_not_publicly_listed():
    conn = video_test_db()
    public = _published(conn, "public")
    unlisted = _published(conn, "unlisted")

    with pytest.raises(PermissionError):
        get_video(conn, unlisted["id"], actor=None)
    anonymous_ids = {row["id"] for row in list_videos(conn, actor=None)}
    viewer_ids = {row["id"] for row in list_videos(conn, actor=actor(2, "viewer"))}
    owner_ids = {row["id"] for row in list_videos(conn, actor=actor(1, "owner"))}
    manager_ids = {row["id"] for row in list_videos(conn, actor=actor(3, "manager", "manager"))}

    assert public["id"] in anonymous_ids
    assert unlisted["id"] not in anonymous_ids
    assert unlisted["id"] not in viewer_ids
    assert unlisted["id"] in owner_ids
    assert unlisted["id"] in manager_ids


def test_blocked_video_metadata_owner_visible_but_stream_denied():
    conn = video_test_db()
    video = _published(conn, "public")
    conn.execute("UPDATE videos SET status='blocked' WHERE id=?", (video["id"],))
    row = conn.execute("SELECT * FROM videos WHERE id=?", (video["id"],)).fetchone()
    assert can_view_video(actor(1, "owner"), row)
    assert not can_view_video(actor(1, "owner"), row, for_stream=True)
