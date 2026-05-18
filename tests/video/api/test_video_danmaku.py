import pytest

from services.media.videos import (
    add_video_danmaku,
    delete_video_danmaku,
    list_video_danmaku,
    publish_video,
)
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


def test_video_danmaku_is_time_bound_sanitized_and_windowed():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="video-1", owner_user_id=1, mime="video/mp4")
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="video-1", title="Demo")

    first = add_video_danmaku(
        conn,
        actor=actor(2, "viewer"),
        video_id=video["id"],
        time_ms=1200,
        content="  hello   world  ",
        mode="scroll",
        color="#FFAA00",
    )
    add_video_danmaku(conn, actor=actor(2, "viewer"), video_id=video["id"], time_ms=90000, content="later")

    assert first["content"] == "hello world"
    assert first["color"] == "#ffaa00"
    assert first["mode"] == "scroll"
    assert first["can_delete"] is True

    rows = list_video_danmaku(conn, actor=actor(2, "viewer"), video_id=video["id"], from_ms=0, to_ms=60000)
    assert [row["content"] for row in rows] == ["hello world"]

    with pytest.raises(ValueError, match="unsafe"):
        add_video_danmaku(conn, actor=actor(2, "viewer"), video_id=video["id"], time_ms=1, content="<script>alert(1)</script>")


def test_video_danmaku_delete_is_limited_to_author_owner_or_moderator():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="video-1", owner_user_id=1, mime="video/mp4")
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="video-1", title="Demo")
    item = add_video_danmaku(conn, actor=actor(2, "viewer"), video_id=video["id"], time_ms=500, content="hi")

    with pytest.raises(PermissionError):
        delete_video_danmaku(conn, actor=actor(4, "stranger"), video_id=video["id"], danmaku_id=item["id"])

    delete_video_danmaku(conn, actor=actor(1, "owner"), video_id=video["id"], danmaku_id=item["id"])
    assert list_video_danmaku(conn, actor=actor(2, "viewer"), video_id=video["id"], from_ms=0, to_ms=1000) == []


def test_audio_media_does_not_accept_danmaku():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="audio-1", owner_user_id=1, mime="audio/mpeg", filename="song.mp3")
    audio = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="audio-1", title="Song")

    with pytest.raises(ValueError, match="only available for video"):
        add_video_danmaku(conn, actor=actor(2, "viewer"), video_id=audio["id"], time_ms=1000, content="beat")
