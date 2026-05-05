import sqlite3

from flask import Flask

from services import auth


def test_require_csrf_safe_get_does_not_require_csrf(monkeypatch):
    seen = {}
    app = Flask(__name__)
    app.testing = True

    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: "alice" if token == "session-1" else None)

    def fake_verify(token, username):
        seen["token"] = token
        seen["username"] = username
        return False

    monkeypatch.setattr(auth, "verify_csrf_token", fake_verify)

    @app.route("/safe-preview")
    @auth.require_csrf_safe
    def safe_preview():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    client.set_cookie("session_token", "session-1")
    response = client.get("/safe-preview")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert seen == {}


def test_require_csrf_safe_rejects_query_token_for_unsafe_methods(monkeypatch):
    seen = {}
    app = Flask(__name__)
    app.testing = True

    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: "alice" if token == "session-1" else None)

    def fake_verify(token, username):
        seen["token"] = token
        seen["username"] = username
        return token == "query-token" and username == "alice"

    monkeypatch.setattr(auth, "verify_csrf_token", fake_verify)

    @app.route("/safe-preview", methods=["POST"])
    @auth.require_csrf_safe
    def safe_preview_post():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    client.set_cookie("session_token", "session-1")
    response = client.post("/safe-preview?csrf_token=query-token")

    assert response.status_code == 403
    assert response.get_json() == {
        "ok": False,
        "error": "csrf_invalid",
        "message": "CSRF token expired or invalid",
    }
    assert seen == {"token": "", "username": "alice"}


def test_require_csrf_accepts_reused_session_token(monkeypatch):
    seen = []
    app = Flask(__name__)
    app.testing = True

    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: "alice" if token == "session-1" else None)
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, username: seen.append((token, username)) or token == "stable-token" and username == "alice")
    monkeypatch.setattr(auth, "delete_csrf_token", lambda token: (_ for _ in ()).throw(AssertionError("session CSRF token must not be single-use")))

    @app.route("/mutate", methods=["POST"])
    @auth.require_csrf
    def mutate():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    client.set_cookie("session_token", "session-1")
    for _ in range(2):
        response = client.post("/mutate", headers={"X-CSRF-Token": "stable-token"})
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
    assert seen == [("stable-token", "alice"), ("stable-token", "alice")]


def test_require_csrf_accepts_form_field_for_public_post(monkeypatch):
    app = Flask(__name__)
    app.testing = True

    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: None)
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, username: token == "form-token" and username == "__public__")
    monkeypatch.setattr(auth, "consume_csrf_token", lambda token, username: True)

    @app.route("/public-form", methods=["POST"])
    @auth.require_csrf
    def public_form():
        return auth.json_resp({"ok": True})

    response = app.test_client().post("/public-form", data={"csrf_token": "form-token"})

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_require_csrf_consumes_public_token_but_keeps_session_tokens(tmp_path, monkeypatch):
    db_path = tmp_path / "csrf.sqlite"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS csrf_tokens (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL)"
        )
        return conn

    auth.configure_auth_service(get_db=get_db, get_user_by_username=lambda username: None, fernet=None)
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: None)
    auth.store_csrf_token("public-token", "__public__")
    app = Flask(__name__)
    app.testing = True

    @app.route("/public-form", methods=["POST"])
    @auth.require_csrf
    def public_form():
        return auth.json_resp({"ok": True})

    response = app.test_client().post("/public-form", headers={"X-CSRF-Token": "public-token"})

    assert response.status_code == 200
    assert auth.verify_csrf_token("public-token", "__public__") is False


def test_csrf_failure_ip_uses_configured_client_ip_not_spoofed_xff(monkeypatch):
    seen = {}

    monkeypatch.setattr(auth, "record_security_event", lambda event_type, ip, **kwargs: seen.update({"event_type": event_type, "ip": ip, **kwargs}))
    auth.configure_auth_service(get_db=lambda: None, get_user_by_username=lambda username: None, fernet=None, get_client_ip=lambda: "127.0.0.1")
    app = Flask(__name__)
    app.testing = True

    with app.test_request_context("/mutate", headers={"X-Forwarded-For": "8.8.8.8"}):
        response, status = auth.csrf_invalid_response("test", "alice")

    assert status == 403
    assert response.get_json()["error"] == "csrf_invalid"
    assert seen["event_type"] == "csrf_fail"
    assert seen["ip"] == "127.0.0.1"


def test_delete_csrf_tokens_for_username_invalidates_old_session_token(tmp_path):
    db_path = tmp_path / "csrf.sqlite"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS csrf_tokens (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL)"
        )
        return conn

    auth.configure_auth_service(get_db=get_db, get_user_by_username=lambda username: None, fernet=None)
    auth.store_csrf_token("old-token", "alice")

    assert auth.verify_csrf_token("old-token", "alice") is True
    auth.delete_csrf_tokens_for_username("alice")
    assert auth.verify_csrf_token("old-token", "alice") is False


# ── Server Mode v2 §Mode Behavior Matrix footnote 1 ────────────────────────
# CSRF is on in every mode EXCEPT `superweak` (the deliberate weakest web
# mode for red-team / fuzz / pentest). Tests below lock both halves of that
# invariant: enforced-by-default + bypassed-only-in-superweak.
# See SERVER_MODE_V2_PROFILE_MATRIX.md footnote 1.


def test_require_csrf_is_enforced_when_no_token_present(monkeypatch):
    """csrf default-on: missing CSRF token must be rejected."""
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: None)
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, owner: False)

    app = Flask(__name__)
    app.testing = True

    @app.route("/probe", methods=["POST"])
    @auth.require_csrf
    def probe():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    response = client.post("/probe", json={"username": ""})
    assert response.status_code == 403
    assert response.get_json().get("error") == "csrf_invalid"


def test_require_csrf_safe_rejects_authenticated_request_without_csrf(monkeypatch):
    """csrf default-on: authenticated POST without verified CSRF must 403."""
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: "alice" if token == "session-1" else None)
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, owner: False)

    app = Flask(__name__)
    app.testing = True

    @app.route("/safe-probe", methods=["POST"])
    @auth.require_csrf_safe
    def safe_probe():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    client.set_cookie("session_token", "session-1")
    response = client.post("/safe-probe", json={})
    assert response.status_code == 403
    assert response.get_json().get("error") == "csrf_invalid"


def test_require_csrf_safe_still_requires_login_first(monkeypatch):
    """No session → 401 before CSRF check is even attempted."""
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: None)

    app = Flask(__name__)
    app.testing = True

    @app.route("/safe-probe", methods=["POST"])
    @auth.require_csrf_safe
    def safe_probe():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    response = client.post("/safe-probe", json={})
    assert response.status_code == 401


def test_require_csrf_bypassed_in_superweak(monkeypatch):
    """superweak mode: CSRF check is skipped for require_csrf-decorated POSTs.

    This is the only mode that bypasses CSRF; all 6 other modes
    (test / internal_test / dev_ready / production / maintenance /
    incident_lockdown) keep CSRF on.
    """
    events = []
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: None)
    # If the bypass leaks, this would force a 403 — so we keep verify
    # returning False and assert we never reach it.
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, owner: False)
    monkeypatch.setattr(auth, "record_security_event", lambda event_type, ip, **kwargs: events.append({"event_type": event_type, "ip": ip, **kwargs}))
    auth.configure_auth_service(
        get_db=lambda: None,
        get_user_by_username=lambda username: None,
        fernet=None,
        get_runtime_server_mode=lambda: "superweak",
    )

    app = Flask(__name__)
    app.testing = True

    @app.route("/probe", methods=["POST"])
    @auth.require_csrf
    def probe():
        return auth.json_resp({"ok": True})

    response = app.test_client().post("/probe", json={})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert any(ev["event_type"] == "csrf_skipped_superweak" and "require_csrf" in ev.get("detail", "") for ev in events), events


def test_require_csrf_safe_bypassed_in_superweak(monkeypatch):
    """superweak mode: CSRF check is skipped for require_csrf_safe-decorated POSTs.

    Login is still required (the bypass is only on the CSRF check, not on
    authentication).
    """
    events = []
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: "alice" if token == "session-1" else None)
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, owner: False)
    monkeypatch.setattr(auth, "record_security_event", lambda event_type, ip, **kwargs: events.append({"event_type": event_type, "ip": ip, **kwargs}))
    auth.configure_auth_service(
        get_db=lambda: None,
        get_user_by_username=lambda username: None,
        fernet=None,
        get_runtime_server_mode=lambda: "superweak",
    )

    app = Flask(__name__)
    app.testing = True

    @app.route("/safe-probe", methods=["POST"])
    @auth.require_csrf_safe
    def safe_probe():
        return auth.json_resp({"ok": True})

    client = app.test_client()

    # Without session → 401 (auth still required).
    no_session = client.post("/safe-probe", json={})
    assert no_session.status_code == 401

    # With session but no CSRF → 200 in superweak.
    client.set_cookie("session_token", "session-1")
    response = client.post("/safe-probe", json={})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert any(ev["event_type"] == "csrf_skipped_superweak" and "require_csrf_safe" in ev.get("detail", "") for ev in events), events


def test_csrf_bypass_strict_equality_only(monkeypatch):
    """superweak bypass is strict equality only — no other mode bypasses.

    Modes that contain 'super' or 'weak' as substrings, or modes whose
    name is similar but not exactly 'superweak', must not trigger bypass.
    """
    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: None)
    monkeypatch.setattr(auth, "verify_csrf_token", lambda token, owner: False)
    monkeypatch.setattr(auth, "record_security_event", lambda event_type, ip, **kwargs: None)

    app = Flask(__name__)
    app.testing = True

    @app.route("/probe", methods=["POST"])
    @auth.require_csrf
    def probe():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    for mode in ("production", "internal_test", "test", "dev_ready", "maintenance", "incident_lockdown", "", None, "Superweak", "superweak ", "super_weak"):
        auth.configure_auth_service(
            get_db=lambda: None,
            get_user_by_username=lambda username: None,
            fernet=None,
            get_runtime_server_mode=lambda mode=mode: mode,
        )
        response = client.post("/probe", json={})
        assert response.status_code == 403, f"mode={mode!r} unexpectedly bypassed CSRF"
