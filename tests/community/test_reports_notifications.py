import sqlite3

from flask import Flask, jsonify

from routes.reports_notifications import register_reports_notification_routes
from services.platform import settings as platform_settings
from services.users.member_levels import ensure_member_level_rules_schema


def _role_rank(role):
    return {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0)


def _parse_positive_int(value, default=None, min_value=None, max_value=None):
    try:
        parsed = int(value)
    except Exception:
        return default
    if min_value is not None and parsed < min_value:
        return default
    if max_value is not None and parsed > max_value:
        return default
    return parsed


def _build_app(db_path, actor_box, violations):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def passthrough(fn):
        return fn

    def add_violation(user_id, username, role, **kwargs):
        violations.append({"user_id": user_id, "username": username, "role": role, **kwargs})
        return "warn", "違規已記錄", 1

    register_reports_notification_routes(app, {
        "add_violation": add_violation,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": lambda payload: jsonify(payload),
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_positive_int": _parse_positive_int,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "role_rank": _role_rank,
    })
    return app


def _seed_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            member_level TEXT NOT NULL DEFAULT 'normal'
        );
        CREATE TABLE forum_threads (
            id INTEGER PRIMARY KEY,
            author_user_id INTEGER NOT NULL
        );
        CREATE TABLE forum_posts (
            id INTEGER PRIMARY KEY,
            thread_id INTEGER NOT NULL,
            author_user_id INTEGER NOT NULL,
            content TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO users (id, username, role, member_level) VALUES (?, ?, ?, ?)",
        [
            (1, "root", "super_admin", "normal"),
            (2, "admin", "manager", "normal"),
            (3, "alice", "user", "normal"),
            (4, "bob", "user", "normal"),
        ],
    )
    conn.execute("INSERT INTO forum_threads (id, author_user_id) VALUES (10, 4)")
    conn.execute("INSERT INTO forum_posts (id, thread_id, author_user_id, content) VALUES (20, 10, 4, 'bad post')")
    ensure_member_level_rules_schema(conn)
    conn.commit()
    conn.close()


def test_admin_can_send_active_notification(tmp_path):
    db_path = tmp_path / "reports.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin", "member_level": "normal"}}
    client = _build_app(db_path, actor_box, []).test_client()

    sent = client.post(
        "/api/admin/notifications/send",
        json={"user_id": 3, "title": "系統通知", "body": "請確認帳號狀態"},
    )
    assert sent.status_code == 200
    assert sent.get_json()["sent"] == ["alice"]

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}
    notes = client.get("/api/notifications").get_json()
    assert notes["notifications"][0]["type"] == "admin_notice"
    assert notes["notifications"][0]["title"] == "系統通知"


def test_user_report_claim_resolve_and_notifications(tmp_path):
    db_path = tmp_path / "reports.db"
    _seed_db(db_path)
    violations = []
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box, violations).test_client()

    submitted = client.post("/api/reports", json={"target_type": "forum_post", "target_id": 20, "reason": "違規內容"})
    assert submitted.status_code == 200
    report_id = submitted.get_json()["report_id"]

    notes = client.get("/api/notifications")
    assert notes.status_code == 200
    assert notes.get_json()["unread_count"] == 1
    assert notes.get_json()["notifications"][0]["type"] == "report_submitted"

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager", "member_level": "normal"}
    listed = client.get("/api/admin/reports")
    assert listed.status_code == 200
    assert listed.get_json()["reports"][0]["id"] == report_id
    assert listed.get_json()["reports"][0]["reported_user_id"] == 4

    claimed = client.post(f"/api/admin/reports/{report_id}/claim")
    assert claimed.status_code == 200
    resolved = client.post(f"/api/admin/reports/{report_id}/resolve", json={"action": "approve", "note": "成立"})
    assert resolved.status_code == 200
    assert violations[0]["user_id"] == 4

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}
    reporter_notes = client.get("/api/notifications").get_json()
    assert reporter_notes["unread_count"] == 2
    note_id = reporter_notes["notifications"][0]["id"]
    read = client.post(f"/api/notifications/{note_id}/read")
    assert read.status_code == 200
    read_all = client.post("/api/notifications/read-all")
    assert read_all.status_code == 200
    assert client.get("/api/notifications").get_json()["unread_count"] == 0


def test_report_claim_blocks_other_manager(tmp_path):
    db_path = tmp_path / "reports.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box, []).test_client()

    report_id = client.post("/api/reports", json={"target_type": "forum_post", "target_id": 20, "reason": "違規內容"}).get_json()["report_id"]
    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager", "member_level": "normal"}
    assert client.post(f"/api/admin/reports/{report_id}/claim").status_code == 200

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin", "member_level": "normal"}
    blocked = client.post(f"/api/admin/reports/{report_id}/resolve", json={"action": "reject"})
    assert blocked.status_code == 409
    assert "領取" in blocked.get_json()["msg"]


def test_muted_admin_notice_is_not_created(tmp_path, monkeypatch):
    db_path = tmp_path / "reports.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin", "member_level": "normal"}}
    client = _build_app(db_path, actor_box, []).test_client()

    monkeypatch.setattr(
        platform_settings,
        "get_system_settings",
        lambda: {
            "feature_reports_notifications_enabled": True,
            "notification_muted_types": "admin_notice\nreport_submitted",
        },
    )

    sent = client.post(
        "/api/admin/notifications/send",
        json={"user_id": 3, "title": "系統通知", "body": "請確認帳號狀態"},
    )
    assert sent.status_code == 200
    assert sent.get_json()["sent"] == []

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}
    notes = client.get("/api/notifications").get_json()
    assert notes["unread_count"] == 0
    assert notes["notifications"] == []


def test_muted_report_submitted_notification_is_skipped(tmp_path, monkeypatch):
    db_path = tmp_path / "reports.db"
    _seed_db(db_path)
    violations = []
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box, violations).test_client()

    monkeypatch.setattr(
        platform_settings,
        "get_system_settings",
        lambda: {
            "feature_reports_notifications_enabled": True,
            "notification_muted_types": "report_submitted",
        },
    )

    submitted = client.post("/api/reports", json={"target_type": "forum_post", "target_id": 20, "reason": "違規內容"})
    assert submitted.status_code == 200

    notes = client.get("/api/notifications")
    assert notes.status_code == 200
    assert notes.get_json()["unread_count"] == 0
    assert notes.get_json()["notifications"] == []
