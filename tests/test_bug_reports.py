import json
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.bug_reports import register_bug_report_routes


def _build_app(reports_dir, actor_box, db_path=None):
    app = Flask(__name__)
    app.testing = True

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    deps = {
        "REPORTS_DIR": str(reports_dir),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_ua": lambda: "pytest",
        "json_resp": json_resp,
        "require_csrf": lambda fn: fn,
        "require_csrf_safe": lambda fn: fn,
    }
    if db_path:
        def get_db():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
        deps["get_db"] = get_db
    register_bug_report_routes(app, deps)
    return app


def test_logged_in_user_can_create_bug_report_file(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    client = _build_app(reports_dir, actor_box).test_client()

    res = client.post("/api/bug-reports", json={
        "severity": "high",
        "title": "root cannot delete post",
        "description": "Delete failed from UI",
        "steps": "login root, delete post",
        "expected": "post deleted",
        "actual": "error",
        "page": "/#community",
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    report_path = reports_dir / "bugs" / f"{body['report_id']}.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["severity"] == "high"
    assert payload["reward_points"] == 5
    assert payload["title"] == "root cannot delete post"
    assert payload["reporter"]["username"] == "alice"


def test_root_can_list_bug_reports_but_manager_cannot(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(reports_dir, actor_box).test_client()
    created = client.post("/api/bug-reports", json={"title": "bug", "description": "details"})
    assert created.status_code == 200

    listed = client.get("/api/admin/bug-reports")
    assert listed.status_code == 200
    assert listed.get_json()["reports"][0]["title"] == "bug"

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    denied = client.get("/api/admin/bug-reports")
    assert denied.status_code == 403


def test_bug_report_requires_title_and_description(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(reports_dir, actor_box).test_client()

    res = client.post("/api/bug-reports", json={"title": ""})

    assert res.status_code == 400
    assert not list((reports_dir / "bugs").glob("*.json")) if (reports_dir / "bugs").exists() else True


def test_bug_report_rewards_points_by_severity(tmp_path):
    reports_dir = tmp_path / "reports"
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, points INTEGER NOT NULL DEFAULT 0, updated_at TEXT)")
    conn.execute(
        "CREATE TABLE reputation_events (id INTEGER PRIMARY KEY, user_id INTEGER, delta INTEGER, reason TEXT, source_user_id INTEGER, source_post_id INTEGER, created_at TEXT)"
    )
    conn.execute("INSERT INTO users (id, username, points) VALUES (3, 'alice', 0)")
    conn.commit()
    conn.close()
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    client = _build_app(reports_dir, actor_box, db_path=db_path).test_client()

    res = client.post("/api/bug-reports", json={"severity": "critical", "title": "critical bug", "description": "details"})

    assert res.status_code == 200
    assert res.get_json()["reward_points"] == 10
    conn = sqlite3.connect(db_path)
    points = conn.execute("SELECT points FROM users WHERE id=3").fetchone()[0]
    event = conn.execute("SELECT delta, reason FROM reputation_events WHERE user_id=3").fetchone()
    conn.close()
    assert points == 10
    assert event == (10, "bug_report:critical")
