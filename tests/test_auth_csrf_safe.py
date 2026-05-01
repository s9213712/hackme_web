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

    @app.route("/public-form", methods=["POST"])
    @auth.require_csrf
    def public_form():
        return auth.json_resp({"ok": True})

    response = app.test_client().post("/public-form", data={"csrf_token": "form-token"})

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


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
