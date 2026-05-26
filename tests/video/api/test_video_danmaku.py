import pytest

from services.media.videos import (
    add_video_danmaku,
    delete_video_danmaku,
    list_video_danmaku,
    publish_video,
)
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


class _FakePointsFacade:
    def __init__(self):
        self.calls = []

    def append_product_ledger_locked(self, conn, **kwargs):
        self.calls.append(kwargs)
        return {"ledger_uuid": f"ledger-{len(self.calls)}"}, True


class _FakePointsService:
    def __init__(self):
        self.facade = _FakePointsFacade()

    def ensure_schema(self, conn):
        return None

    def rc1_facade(self):
        return self.facade


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
    assert first["effect"] == "none"
    assert first["paid_points"] == 0
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


def test_special_video_danmaku_charges_official_revenue_once_by_idempotency():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="video-1", owner_user_id=1, mime="video/mp4")
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="video-1", title="Demo")
    points = _FakePointsService()

    item = add_video_danmaku(
        conn,
        actor=actor(2, "viewer"),
        video_id=video["id"],
        time_ms=1200,
        content="paid glow",
        mode="top",
        size="large",
        effect="glow",
        points_service=points,
        idempotency_key="danmaku-paid-1",
    )
    duplicate = add_video_danmaku(
        conn,
        actor=actor(2, "viewer"),
        video_id=video["id"],
        time_ms=1200,
        content="paid glow",
        mode="top",
        size="large",
        effect="glow",
        points_service=points,
        idempotency_key="danmaku-paid-1",
    )

    assert item["id"] == duplicate["id"]
    assert item["mode"] == "top"
    assert item["size"] == "large"
    assert item["effect"] == "glow"
    assert item["paid_points"] == 30
    assert item["ledger_debit_uuid"] == "ledger-1"
    assert item["ledger_credit_uuid"] == "ledger-2"
    assert len(points.facade.calls) == 2
    assert points.facade.calls[0]["action_type"] == "video_danmaku_special_debit"
    assert points.facade.calls[1]["action_type"] == "video_danmaku_special_fee"


def test_special_video_danmaku_requires_points_service():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="video-1", owner_user_id=1, mime="video/mp4")
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="video-1", title="Demo")

    with pytest.raises(RuntimeError, match="PointsChain service"):
        add_video_danmaku(
            conn,
            actor=actor(2, "viewer"),
            video_id=video["id"],
            time_ms=1200,
            content="paid",
            effect="rainbow",
        )
