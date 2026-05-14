import sqlite3

import pytest
from flask import Flask, jsonify, make_response

from routes.public import register_public_routes


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _build_app(db_path):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_public_routes(app, {
        "CSRF_TOKEN_TTL": 3600,
        "PUBLIC_DIR": ".",
        "ROLE_LABEL": {},
        "SERVER_APP_NAME": "hackme_web",
        "SERVER_RELEASE_ID": "test",
        "SERVER_STARTED_AT": "2026-01-01T00:00:00",
        "SERVER_VERSION": "test",
        "SESSION_COOKIE_SAMESITE": "Strict",
        "SESSION_COOKIE_SECURE": False,
        "SESSION_TTL": 3600,
        "audit": lambda *args, **kwargs: None,
        "db_delete_session": lambda *args, **kwargs: None,
        "db_get_user_from_token": lambda *args, **kwargs: None,
        "db_save_session": lambda *args, **kwargs: None,
        "decrypt_field": lambda value: value or "",
        "encrypt_field": lambda value: value,
        "ensure_user_official_room_membership": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: None,
        "get_db": get_db,
        "get_feature_settings": lambda: {},
        "get_member_level_rule": lambda conn, level: {},
        "get_system_settings": lambda: {
            "allow_register": True,
            "captcha_mode": "none",
            "max_login_failures": 5,
            "block_duration_minutes": 10,
        },
        "get_ua": lambda: "test-agent",
        "hash_password": lambda value: value,
        "is_feature_enabled": lambda name: False,
        "is_ip_blocked": lambda ip: False,
        "is_rate_limited": lambda *args, **kwargs: (False, {"limit": 10}),
        "json_resp": _json_resp,
        "make_csrf_token": lambda: "csrf",
        "make_token": lambda username: "session-token",
        "normalize_text": lambda value: str(value or "").strip(),
        "parse_birthdate": lambda value: value if value else "",
        "record_login_failure": lambda *args, **kwargs: None,
        "record_security_event": lambda *args, **kwargs: None,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "score_password_strength": lambda value: {"score": 4},
        "store_csrf_token": lambda *args, **kwargs: None,
        "timing_delay": lambda: None,
        "validate_id_number": lambda value: True,
        "validate_password": lambda value: (len(value) >= 8, "密碼太短"),
        "enforce_password_strength": lambda value, min_score=3: (True, "", {"score": 4}),
        "validate_phone": lambda value: True,
        "verify_csrf_double_submit": lambda token: True,
        "verify_password": lambda stored, provided: stored == provided,
    })
    return app


def test_register_validation_returns_field_for_username(tmp_path):
    client = _build_app(tmp_path / "register.db").test_client()

    response = client.post(
        "/api/register",
        json={"username": "ab", "password": "GoodPass1!", "password_confirm": "GoodPass1!", "nickname": "Nick"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["field"] == "username"


def test_register_validation_returns_field_for_password_confirmation(tmp_path):
    client = _build_app(tmp_path / "register.db").test_client()

    response = client.post(
        "/api/register",
        json={"username": "alice123", "password": "GoodPass1!", "password_confirm": "Mismatch1!", "nickname": "Nick"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["field"] == "password_confirm"


@pytest.mark.parametrize("username", ["ROOT", "Root", "ADMIN", "Admin", "TEST", "Test", "r0ot", "te5t"])
def test_register_blocks_reserved_username_case_and_simple_confusables(tmp_path, username):
    client = _build_app(tmp_path / "register.db").test_client()

    response = client.post(
        "/api/register",
        json={"username": username, "password": "GoodPass1!", "password_confirm": "GoodPass1!", "nickname": "Nick"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["field"] == "username"
    assert "保留" in payload["msg"]
