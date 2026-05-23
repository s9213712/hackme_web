import sqlite3

from flask import Flask, jsonify, make_response
import pytest

from routes.videos import register_video_routes
from services.media.videos import (
    boost_owner_video,
    delete_owner_video,
    get_video,
    list_owner_videos,
    list_videos,
    publish_video,
    record_video_view,
    resolve_video_share_token,
    set_video_like,
    tip_video,
    update_owner_video,
)
from services.points_chain import DISPLAY_CURRENCY, PointsLedgerService
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


def _points_service(conn, *, user_id, amount=500):
    service = PointsLedgerService(get_db=lambda: conn, chain_secret="video-management-test")
    service.ensure_schema(conn)
    service._record_transaction(
        conn,
        user_id=user_id,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=amount,
        action_type="user_initial_grant",
        reference_type="test",
        reference_id=f"seed:{user_id}",
        idempotency_key=f"video-management-seed:{user_id}",
        reason="seed test wallet",
        actor=actor(9, "root", "super_admin"),
    )
    return service


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _build_management_app(db_path, actor_box, tmp_path):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_video_routes(app, {
        "STORAGE_DIR": str(tmp_path),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box.get("actor"),
        "get_db": get_db,
        "get_system_settings": lambda: {},
        "get_member_level_rule": lambda conn, level: {
            "can_upload_attachment": True,
            "attachment_quota_mb": 10,
            "max_attachment_size_mb": 10,
            "upload_rate_limit_per_day": 10,
        },
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "points_service": None,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "server_file_fernet": None,
    })
    return app


def _copy_conn_to_path(conn, db_path):
    conn.commit()
    target = sqlite3.connect(db_path)
    conn.backup(target)
    target.close()


def test_owner_video_management_reports_metrics_and_keeps_other_accounts_out():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="owner-video", owner_user_id=1, mime="video/mp4")
    seed_cloud_file(conn, file_id="viewer-video", owner_user_id=2, mime="video/mp4")
    owner_video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="owner-video",
        title="Owner clip",
        visibility="public",
    )
    publish_video(
        conn,
        actor=actor(2, "viewer"),
        cloud_file_id="viewer-video",
        title="Viewer clip",
    )
    service = _points_service(conn, user_id=2, amount=200)

    record_video_view(conn, actor=actor(2, "viewer"), video_id=owner_video["id"], ip="127.0.0.1", watch_seconds=10)
    set_video_like(conn, actor=actor(2, "viewer"), video_id=owner_video["id"], liked=True)
    tip_video(
        conn,
        points_service=service,
        actor=actor(2, "viewer"),
        video_id=owner_video["id"],
        amount=100,
        fee_percent=5,
        idempotency_key="management-tip",
    )

    managed = list_owner_videos(conn, actor=actor(1, "owner"))

    assert [video["id"] for video in managed] == [owner_video["id"]]
    assert managed[0]["view_count"] == 1
    assert managed[0]["like_count"] == 1
    assert managed[0]["gross_points"] == 100
    assert managed[0]["revenue_points"] == 95
    assert managed[0]["platform_fee_points"] == 5

    with pytest.raises(ValueError, match="找不到影音"):
        update_owner_video(conn, actor=actor(2, "viewer"), video_id=owner_video["id"], title="stolen")


def test_video_management_routes_are_owner_scoped(tmp_path):
    source = video_test_db()
    seed_cloud_file(source, file_id="owner-video", owner_user_id=1, mime="video/mp4")
    seed_cloud_file(source, file_id="viewer-video", owner_user_id=2, mime="video/mp4")
    owner_video = publish_video(source, actor=actor(1, "owner"), cloud_file_id="owner-video", title="Owner route")
    publish_video(source, actor=actor(2, "viewer"), cloud_file_id="viewer-video", title="Viewer route")
    db_path = tmp_path / "video-management.db"
    _copy_conn_to_path(source, db_path)
    actor_box = {"actor": actor(1, "owner")}
    client = _build_management_app(db_path, actor_box, tmp_path).test_client()

    response = client.get("/api/videos/manage")
    payload = response.get_json()
    assert response.status_code == 200
    assert [video["id"] for video in payload["videos"]] == [owner_video["id"]]

    actor_box["actor"] = actor(2, "viewer")
    response = client.put(
        f"/api/videos/{owner_video['id']}/manage",
        json={"title": "stolen", "visibility": "public", "description": ""},
    )
    assert response.status_code == 400
    assert response.get_json()["msg"] == "找不到影音"

    actor_box["actor"] = actor(1, "owner")
    response = client.put(
        f"/api/videos/{owner_video['id']}/manage",
        json={"title": "Updated route", "visibility": "private", "description": "edited"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["video"]["title"] == "Updated route"
    assert payload["video"]["visibility"] == "private"

    response = client.delete(f"/api/videos/{owner_video['id']}/manage")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert client.get("/api/videos/manage").get_json()["videos"] == []


def test_owner_delete_hides_video_and_revokes_share_link():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="owner-video", owner_user_id=1, mime="video/mp4")
    video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="owner-video",
        title="Delete me",
        visibility="unlisted",
    )
    token = video["share_url"].rsplit("/", 1)[-1]

    result = delete_owner_video(conn, actor=actor(1, "owner"), video_id=video["id"])

    assert result["ok"] is True
    assert list_owner_videos(conn, actor=actor(1, "owner")) == []
    assert get_video(conn, video["id"], actor=actor(1, "owner")) is None
    assert resolve_video_share_token(conn, token)[1] == "not_found"


def test_video_boost_spends_owner_points_and_promotes_active_video():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="old-video", owner_user_id=1, mime="video/mp4")
    seed_cloud_file(conn, file_id="new-video", owner_user_id=1, mime="video/mp4")
    old_video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="old-video", title="Old clip")
    new_video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="new-video", title="New clip")
    conn.execute("UPDATE videos SET created_at='2026-01-01T00:00:00' WHERE id=?", (old_video["id"],))
    conn.execute("UPDATE videos SET created_at='2026-01-02T00:00:00' WHERE id=?", (new_video["id"],))
    service = _points_service(conn, user_id=1, amount=300)

    assert [video["id"] for video in list_videos(conn, actor=None, sort="new")][:2] == [new_video["id"], old_video["id"]]

    result = boost_owner_video(
        conn,
        points_service=service,
        actor=actor(1, "owner"),
        video_id=old_video["id"],
        amount=120,
        idempotency_key="boost-once",
    )

    assert result["created"] is True
    assert result["video"]["boost_active"] is True
    assert result["video"]["boost_points_total"] == 120
    assert [video["id"] for video in list_videos(conn, actor=None, sort="new")][:2] == [old_video["id"], new_video["id"]]
    wallet = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=1").fetchone()
    assert int(wallet["soft_balance"]) == 180


def test_video_search_matches_metadata_and_respects_visibility():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="lofi-public", owner_user_id=1, mime="video/mp4")
    seed_cloud_file(conn, file_id="cooking-public", owner_user_id=1, mime="video/mp4")
    seed_cloud_file(conn, file_id="lofi-private", owner_user_id=1, mime="video/mp4")
    public = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="lofi-public",
        title="LoFi Study Mix",
        description="piano focus session",
    )
    publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="cooking-public",
        title="Cooking Notes",
        description="kitchen playlist",
    )
    private = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="lofi-private",
        title="Private LoFi Draft",
        visibility="private",
    )

    anonymous_ids = {video["id"] for video in list_videos(conn, actor=None, query="lofi")}
    owner_ids = {video["id"] for video in list_videos(conn, actor=actor(1, "owner"), query="lofi")}
    description_ids = {video["id"] for video in list_videos(conn, actor=None, query="piano")}

    assert public["id"] in anonymous_ids
    assert private["id"] not in anonymous_ids
    assert private["id"] in owner_ids
    assert description_ids == {public["id"]}
