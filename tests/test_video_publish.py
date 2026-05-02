import pytest

from services.videos import publish_video
from tests.video_test_helpers import actor, seed_cloud_file, video_test_db


def test_publish_video_requires_owner_and_video_mime():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="video-1", owner_user_id=1, mime="video/mp4")
    video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="video-1",
        title="Demo video",
        description="Cloud Drive backed",
        visibility="public",
    )
    assert video["id"] == 1
    assert video["cloud_file_id"] == "video-1"
    assert video["visibility"] == "public"

    with pytest.raises(PermissionError):
        publish_video(conn, actor=actor(2, "viewer"), cloud_file_id="video-1", title="steal")

    seed_cloud_file(conn, file_id="text-1", owner_user_id=1, mime="text/plain")
    with pytest.raises(ValueError, match="video"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="text-1", title="not video")


def test_publish_rejects_e2ee_video_for_server_streaming():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="e2ee-video", owner_user_id=1, mime="video/mp4", privacy_mode="e2ee")
    with pytest.raises(ValueError, match="E2EE"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="e2ee-video", title="secret")
