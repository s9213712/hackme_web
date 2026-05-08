import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.system_admin import _retry_sqlite_locked, register_system_admin_routes
from services.platform.bootstrap import CURRENT_SCHEMA_VERSION
from services.system.integrity_guard import IntegrityGuard, ensure_integrity_schema


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


class _SnapshotStub:
    def list_snapshots(self, actor=None):
        return [{"id": "snap_test"}]


def _make_app(tmp_path, actor=None, audit_result=(True, None, "integrity OK"), include_forum_tables=True, activation_log=None, integrity_guard=None):
    db_path = tmp_path / "health.db"
    chat_dir = tmp_path / "chats"
    log_dir = tmp_path / "logs"
    anchor_dir = tmp_path / "anchors"
    storage_dir = tmp_path / "storage"
    for path in (chat_dir, log_dir, anchor_dir, storage_dir):
        path.mkdir()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    schema = """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, status TEXT);
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, expires_at TEXT, is_revoked INTEGER DEFAULT 0);
        CREATE TABLE chat_messages (id INTEGER PRIMARY KEY);
        CREATE TABLE chat_message_reports (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE violation_appeals (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE moderation_proposals (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE secure_violations (id INTEGER PRIMARY KEY);
        CREATE TABLE secure_audit (id INTEGER PRIMARY KEY);
        CREATE TABLE uploaded_files (id TEXT PRIMARY KEY, scan_status TEXT, risk_level TEXT, deleted_at TEXT);
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);
        """
    if include_forum_tables:
        schema += """
        CREATE TABLE forum_boards (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE forum_threads (id INTEGER PRIMARY KEY, status TEXT);
        """
    conn.executescript(schema)
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, 'current', '2026-01-01T00:00:00')",
        (CURRENT_SCHEMA_VERSION,),
    )
    conn.execute("INSERT INTO users (id, username, status) VALUES (1, 'root', 'active')")
    conn.execute("INSERT INTO chat_message_reports (id, status) VALUES (1, 'pending')")
    conn.execute("INSERT INTO uploaded_files (id, scan_status, risk_level, deleted_at) VALUES ('f1', 'quarantined', 'blocked', NULL)")
    conn.commit()
    conn.close()

    def get_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    app = Flask(__name__)
    app.testing = True
    register_system_admin_routes(app, {
        "ANCHOR_DIR": str(anchor_dir),
        "BASE_DIR": str(tmp_path),
        "CHAT_DIR": str(chat_dir),
        "DB_PATH": str(db_path),
        "LOG_DIR": str(log_dir),
        "SERVER_LOG_PATH": str(log_dir / "server.log"),
        "STORAGE_DIR": str(storage_dir),
        "activate_emergency_lockdown": lambda reason: (activation_log.append(reason) if activation_log is not None else None),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor or {"id": 1, "username": "root", "role": "super_admin"},
        "get_db": get_db,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: {"maintenance_mode": False},
        "get_ua": lambda: "pytest",
        "integrity_guard": integrity_guard,
        "is_audit_chain_enabled": lambda: True,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": lambda data: data,
        "server_mode_service": None,
        "snapshot_service": _SnapshotStub(),
        "verify_audit_integrity": lambda: audit_result,
    })
    return app


def _write_integrity_project(base: Path):
    (base / "services").mkdir(parents=True)
    (base / "routes").mkdir(parents=True)
    (base / "public" / "js").mkdir(parents=True)
    (base / "server.py").write_text("print('server')\n", encoding="utf-8")
    (base / "services" / "auth.py").write_text("AUTH = True\n", encoding="utf-8")
    (base / "routes" / "system_admin.py").write_text("ROOT = True\n", encoding="utf-8")
    (base / "public" / "js" / "50-admin.js").write_text("const admin = true;\n", encoding="utf-8")
    (base / "bootstrap.schema.sql").write_text("CREATE TABLE x(id);\n", encoding="utf-8")
    (base / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (base / "README.md").write_text("# test project\n", encoding="utf-8")


def test_health_readiness_and_db_integrity_endpoints(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    readiness = client.get("/api/admin/health/readiness")
    assert readiness.status_code == 200
    body = readiness.get_json()
    assert body["readiness"]["status"] == "ok"
    assert body["readiness"]["database"]["schema_version"] == CURRENT_SCHEMA_VERSION

    db = client.get("/api/admin/health/db-integrity")
    assert db.status_code == 200
    assert db.get_json()["database"]["quick_check"] == ["ok"]
    assert db.get_json()["database"]["ok"] is True


def test_retry_sqlite_locked_retries_until_success(monkeypatch):
    attempts = {"count": 0}
    sleeps = []

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return {"ok": True}

    monkeypatch.setattr("routes.system_admin.time.sleep", lambda seconds: sleeps.append(seconds))

    result = _retry_sqlite_locked(flaky, attempts=3, delay_seconds=0.05)

    assert result == {"ok": True}
    assert attempts["count"] == 3
    assert sleeps == [0.05, 0.05]


def test_admin_health_summary_includes_grouped_dashboard_data(tmp_path):
    app = _make_app(tmp_path)
    res = app.test_client().get("/api/admin/health")
    data = res.get_json()

    assert res.status_code == 200
    assert data["ok"] is True
    assert data["status"] in {"ok", "degraded", "critical"}
    assert data["counts"]["pending_chat_reports"] == 1
    assert data["counts"]["pending_reports"] == 1
    assert "pending_moderation_proposals" in data["counts"]
    assert {"log_files", "anchor_files", "storage_files"} <= set(data["storage"])
    assert data["readiness"]["database"]["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "signals" in data["anomaly"]


def test_health_anomaly_reports_quarantined_files(tmp_path):
    app = _make_app(tmp_path)
    res = app.test_client().get("/api/admin/health/anomaly")
    data = res.get_json()
    assert res.status_code == 200
    assert data["anomaly"]["status"] == "warning"
    assert any(signal["name"] == "quarantined_files" for signal in data["anomaly"]["signals"])


def test_health_anomaly_treats_missing_optional_forum_tables_as_zero(tmp_path):
    app = _make_app(tmp_path, include_forum_tables=False)
    res = app.test_client().get("/api/admin/health/anomaly")
    data = res.get_json()

    assert res.status_code == 200
    assert data["anomaly"]["counts"]["pending_board_reviews"] == 0
    assert data["anomaly"]["counts"]["pending_thread_reviews"] == 0
    assert "pending_board_reviews" not in data["anomaly"]["errors"]
    assert "pending_thread_reviews" not in data["anomaly"]["errors"]
    assert not any(signal["name"] == "count_errors" for signal in data["anomaly"]["signals"])


def test_health_audit_chain_reports_broken_chain(tmp_path):
    activation_log = []
    app = _make_app(tmp_path, audit_result=(False, 7, "hash mismatch"), activation_log=activation_log)
    res = app.test_client().get("/api/admin/health/audit-chain")
    data = res.get_json()
    assert res.status_code == 200
    assert data["audit_integrity"]["ok"] is False
    assert data["audit_integrity"]["broken_at"] == 7
    assert data["audit_integrity"]["operator_action_required"] is True
    assert data["audit_integrity"]["auto_lockdown_applied"] is False
    assert activation_log == []


def test_admin_health_broken_audit_chain_marks_critical_without_auto_lockdown(tmp_path):
    activation_log = []
    app = _make_app(tmp_path, audit_result=(False, 7, "hash mismatch"), activation_log=activation_log)
    res = app.test_client().get("/api/admin/health")
    data = res.get_json()

    assert res.status_code == 200
    assert data["status"] == "critical"
    assert data["audit_integrity"]["ok"] is False
    assert data["audit_integrity"]["operator_action_required"] is True
    assert data["audit_integrity"]["auto_lockdown_applied"] is False
    assert activation_log == []


def test_health_integrity_guard_clean_deploy_drift_is_degraded_not_critical(tmp_path):
    integrity_db = tmp_path / "integrity.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_integrity_project(repo)

    def get_integrity_db():
        conn = sqlite3.connect(integrity_db)
        conn.row_factory = sqlite3.Row
        ensure_integrity_schema(conn)
        return conn

    guard = IntegrityGuard(
        base_dir=repo,
        signing_key=b"test-signing-key",
        get_db=get_integrity_db,
        audit=lambda *args, **kwargs: None,
    )
    guard.scan(actor="system")
    (repo / "services" / "auth.py").write_text("AUTH = 'changed'\n", encoding="utf-8")
    guard._is_clean_git_checkout = lambda: True
    guard.scan(actor="system-startup", create_initial_manifest=False)

    app = _make_app(tmp_path, integrity_guard=guard)
    res = app.test_client().get("/api/admin/health/readiness")
    data = res.get_json()["readiness"]

    assert res.status_code == 200
    assert data["status"] == "degraded"
    integrity = next(item for item in data["checks"] if item["name"] == "integrity_guard")
    assert integrity["ok"] is False
    assert integrity["severity"] == "degraded"
    assert "尚未 rebaseline" in integrity["detail"]


def test_health_center_requires_super_admin(tmp_path):
    app = _make_app(tmp_path, actor={"id": 2, "username": "admin", "role": "manager"})
    res = app.test_client().get("/api/admin/health/readiness")
    assert res.status_code == 403


def test_unknown_path_options_does_not_advertise_unsafe_methods(tmp_path):
    app = _make_app(tmp_path)
    res = app.test_client().open("/not-real-pentest-path", method="OPTIONS")

    assert res.status_code == 404
    allow = res.headers["Allow"]
    assert "PUT" not in allow
    assert "DELETE" not in allow
    assert "PATCH" not in allow
    assert allow == "GET, POST, HEAD, OPTIONS"
