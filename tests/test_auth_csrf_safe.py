from flask import Flask

from services import auth


def test_require_csrf_safe_accepts_query_token_for_embedded_media(monkeypatch):
    seen = {}
    app = Flask(__name__)
    app.testing = True

    monkeypatch.setattr(auth, "db_get_user_from_token", lambda token: "alice" if token == "session-1" else None)

    def fake_verify(token, username):
        seen["token"] = token
        seen["username"] = username
        return token == "query-token" and username == "alice"

    monkeypatch.setattr(auth, "verify_csrf_token", fake_verify)

    @app.route("/safe-preview")
    @auth.require_csrf_safe
    def safe_preview():
        return auth.json_resp({"ok": True})

    client = app.test_client()
    client.set_cookie("session_token", "session-1")
    response = client.get("/safe-preview?csrf_token=query-token")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert seen == {"token": "query-token", "username": "alice"}


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
    assert response.get_json()["ok"] is False
    assert seen == {"token": "", "username": "alice"}
