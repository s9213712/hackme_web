import pytest

from services.points_chain import DISPLAY_CURRENCY, PointsLedgerService
from services.media.videos import publish_video, tip_video
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


def _points_service(conn):
    service = PointsLedgerService(get_db=lambda: conn, chain_secret="video-test-secret")
    service.ensure_schema(conn)
    service._record_transaction(
        conn,
        user_id=2,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=200,
        action_type="user_initial_grant",
        reference_type="test",
        reference_id="seed",
        idempotency_key="seed:viewer",
        reason="seed viewer",
        actor=actor(1, "owner"),
    )
    return service


def test_video_tip_debits_viewer_credits_uploader_and_is_idempotent():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")
    service = _points_service(conn)

    result = tip_video(
        conn,
        points_service=service,
        actor=actor(2, "viewer"),
        video_id=video["id"],
        amount=100,
        fee_percent=5,
        idempotency_key="tip-once",
    )
    assert result["created"] is True
    assert result["tip"]["amount_points"] == 100
    assert result["tip"]["fee_points"] == 5
    assert result["tip"]["net_points"] == 95
    assert result["tip"]["fee_user_id"] == 9
    assert result["ledger"]["fee_uuid"]

    again = tip_video(
        conn,
        points_service=service,
        actor=actor(2, "viewer"),
        video_id=video["id"],
        amount=100,
        fee_percent=5,
        idempotency_key="tip-once",
    )
    assert again["created"] is False

    wallet_viewer = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=2").fetchone()[0]
    wallet_owner = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=1").fetchone()[0]
    wallet_official = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=9").fetchone()[0]
    assert wallet_viewer == 100
    assert wallet_owner == 95
    assert wallet_official == 5
    assert conn.execute("SELECT COUNT(*) FROM video_tips").fetchone()[0] == 1


def test_video_tip_rejects_idempotency_key_reuse_for_different_tip():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")
    service = _points_service(conn)

    tip_video(
        conn,
        points_service=service,
        actor=actor(2, "viewer"),
        video_id=video["id"],
        amount=25,
        fee_percent=5,
        idempotency_key="shared-key",
    )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        tip_video(
            conn,
            points_service=service,
            actor=actor(2, "viewer"),
            video_id=video["id"],
            amount=30,
            fee_percent=5,
            idempotency_key="shared-key",
        )


def test_video_tip_rejects_insufficient_balance_and_self_tip():
    conn = video_test_db()
    seed_cloud_file(conn)
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="file-video", title="Demo")
    service = _points_service(conn)

    with pytest.raises(ValueError, match="own video"):
        tip_video(conn, points_service=service, actor=actor(1, "owner"), video_id=video["id"], amount=1)

    with pytest.raises(ValueError, match="insufficient balance"):
        tip_video(conn, points_service=service, actor=actor(2, "viewer"), video_id=video["id"], amount=1000)
