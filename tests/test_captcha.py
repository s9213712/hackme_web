import sqlite3
from datetime import datetime, timedelta

from services.captcha import (
    create_captcha_challenge,
    ensure_captcha_schema,
    normalize_captcha_mode,
    verify_captcha_response,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_captcha_schema(conn)
    return conn


def _answer_for(conn, challenge):
    row = conn.execute(
        "SELECT id, answer_hash FROM captcha_challenges WHERE id=?",
        (challenge["captcha_id"],),
    ).fetchone()
    for value in range(0, 40):
        import hashlib

        hashed = hashlib.sha256(f"{row['id']}:{value}".encode("utf-8")).hexdigest()
        if hashed == row["answer_hash"]:
            return str(value)
    raise AssertionError("challenge answer not found")


def test_captcha_none_does_not_require_challenge():
    conn = _conn()
    assert normalize_captcha_mode("bad") == "none"
    ok, msg = verify_captcha_response(conn, {"captcha_mode": "none"}, {}, ip="127.0.0.1")
    assert ok is True
    assert msg == ""


def test_math_challenge_accepts_once_and_rejects_reuse():
    conn = _conn()
    challenge = create_captcha_challenge(conn, mode="math", ttl_seconds=300, ip="127.0.0.1")
    answer = _answer_for(conn, challenge)

    ok, msg = verify_captcha_response(
        conn,
        {"captcha_mode": "math"},
        {"captcha_id": challenge["captcha_id"], "captcha_answer": answer},
        ip="127.0.0.1",
    )
    assert ok is True
    assert msg == ""

    ok, msg = verify_captcha_response(
        conn,
        {"captcha_mode": "math"},
        {"captcha_id": challenge["captcha_id"], "captcha_answer": answer},
        ip="127.0.0.1",
    )
    assert ok is False
    assert "已使用" in msg


def test_expired_challenge_is_rejected():
    conn = _conn()
    challenge = create_captcha_challenge(conn, mode="math", ttl_seconds=300, ip="127.0.0.1")
    answer = _answer_for(conn, challenge)
    conn.execute(
        "UPDATE captcha_challenges SET expires_at=? WHERE id=?",
        ((datetime.now() - timedelta(seconds=1)).isoformat(), challenge["captcha_id"]),
    )

    ok, msg = verify_captcha_response(
        conn,
        {"captcha_mode": "math"},
        {"captcha_id": challenge["captcha_id"], "captcha_answer": answer},
        ip="127.0.0.1",
    )
    assert ok is False
    assert "過期" in msg


def test_image_challenge_returns_svg_data_uri():
    conn = _conn()
    challenge = create_captcha_challenge(conn, mode="image", ttl_seconds=300, ip="127.0.0.1")
    answer = _answer_for(conn, challenge)

    assert challenge["image_data_uri"].startswith("data:image/svg+xml;base64,")
    ok, _ = verify_captcha_response(
        conn,
        {"captcha_mode": "image"},
        {"captcha_id": challenge["captcha_id"], "captcha_answer": answer},
        ip="127.0.0.1",
    )
    assert ok is True


def test_turnstile_without_server_key_fails_with_actionable_message(monkeypatch):
    conn = _conn()
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    ok, msg = verify_captcha_response(
        conn,
        {"captcha_mode": "turnstile"},
        {"captcha_turnstile_token": "dummy-token"},
        ip="127.0.0.1",
    )
    assert ok is False
    assert "TURNSTILE_SECRET_KEY" in msg
