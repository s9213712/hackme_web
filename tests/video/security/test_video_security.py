import pytest

from services.media.videos import publish_video, record_video_view, set_video_like
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


def test_video_view_deduplicates_counted_views_by_user_or_ip():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")

    first = record_video_view(conn, actor=actor(2, "viewer"), video_id=video["id"], ip="127.0.0.1", watch_seconds=10)
    second = record_video_view(conn, actor=actor(2, "viewer"), video_id=video["id"], ip="127.0.0.1", watch_seconds=10)
    short = record_video_view(conn, actor=actor(3, "manager", "manager"), video_id=video["id"], ip="127.0.0.2", watch_seconds=1)

    assert first["counted"] is True
    assert second["counted"] is False
    assert short["counted"] is False
    assert conn.execute("SELECT view_count FROM videos WHERE id=?", (video["id"],)).fetchone()[0] == 1


def test_video_like_is_unique_per_user():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")

    set_video_like(conn, actor=actor(2, "viewer"), video_id=video["id"], liked=True)
    set_video_like(conn, actor=actor(2, "viewer"), video_id=video["id"], liked=True)
    assert conn.execute("SELECT like_count FROM videos WHERE id=?", (video["id"],)).fetchone()[0] == 1
    set_video_like(conn, actor=actor(2, "viewer"), video_id=video["id"], liked=False)
    assert conn.execute("SELECT like_count FROM videos WHERE id=?", (video["id"],)).fetchone()[0] == 0


def test_publish_rejects_deleted_or_blocked_cloud_files():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="deleted", owner_user_id=1, mime="video/mp4")
    conn.execute("UPDATE uploaded_files SET deleted_at='2026-01-01T00:00:00' WHERE id='deleted'")
    with pytest.raises(ValueError, match="not found"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="deleted", title="deleted")

    seed_cloud_file(conn, file_id="blocked", owner_user_id=1, mime="video/mp4")
    conn.execute("UPDATE uploaded_files SET risk_level='blocked' WHERE id='blocked'")
    with pytest.raises(ValueError, match="blocked"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="blocked", title="blocked")
