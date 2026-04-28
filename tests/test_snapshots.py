import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes
from services.snapshots import ServerModeService, SnapshotService, ensure_snapshot_schema


def _db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(path):
    conn = _db(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            member_level TEXT NOT NULL DEFAULT 'normal',
            base_level TEXT NOT NULL DEFAULT 'normal',
            effective_level TEXT NOT NULL DEFAULT 'normal'
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL
        );
        CREATE TABLE system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            value_type TEXT,
            updated_at TEXT,
            updated_by TEXT
        );
        INSERT INTO users (id, username, role, status, member_level, base_level, effective_level)
        VALUES (1, 'root', 'super_admin', 'active', 'vip', 'vip', 'vip');
        INSERT INTO posts (id, title) VALUES (1, 'P1');
        INSERT INTO system_settings (key, value, value_type, updated_at, updated_by)
        VALUES ('maintenance_mode', 'false', 'bool', '2026-01-01T00:00:00', 'test');
        """
    )
    ensure_snapshot_schema(conn)
    conn.commit()
    conn.close()


def _service(tmp_path, audit_log):
    base = tmp_path / "app"
    base.mkdir()
    db_path = base / "database.db"
    uploads = base / "uploads"
    storage = base / "storage"
    uploads.mkdir()
    storage.mkdir()
    _init_db(db_path)

    def get_db():
        return _db(db_path)

    service = SnapshotService(
        get_db=get_db,
        db_path=db_path,
        base_dir=base,
        storage_root=storage,
        audit=lambda *args, **kwargs: audit_log.append((args, kwargs)),
        file_roots=[uploads],
        config_files=[],
    )
    return service, db_path, uploads


def test_root_service_creates_manual_snapshot_with_metadata(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    (uploads / "avatar.txt").write_text("v1", encoding="utf-8")

    result = service.create_snapshot(snapshot_type="manual", actor={"id": 1, "username": "root"}, notes="before risky test")

    assert result.ok is True
    snapshot = service.get_snapshot(snapshot_id=result.snapshot_id, actor={"id": 1, "username": "root"})
    snapshot_dir = Path(snapshot["storage_path"])
    assert snapshot["status"] == "ready"
    assert snapshot["metadata"]["secrets_excluded"] is True
    assert (snapshot_dir / "metadata.json").exists()
    assert (snapshot_dir / "db.sqlite3.backup").exists()
    assert (snapshot_dir / "uploads.tar.gz").exists()
    assert (snapshot_dir / "config.tar.gz").exists()
    assert (snapshot_dir / "checksums.sha256").exists()
    assert any(call[0][0] == "SNAPSHOT_CREATE_READY" for call in audit_log)


def test_restore_reverts_db_and_uploaded_files_and_creates_pre_restore(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    (uploads / "f1.txt").write_text("one", encoding="utf-8")
    snap = service.create_snapshot(snapshot_type="manual", actor={"id": 1, "username": "root"}, notes="baseline")

    conn = _db(db_path)
    conn.execute("INSERT INTO posts (id, title) VALUES (2, 'P2')")
    conn.execute("UPDATE users SET base_level='vip', effective_level='restricted', member_level='restricted' WHERE id=1")
    conn.commit()
    conn.close()
    (uploads / "f2.txt").write_text("two", encoding="utf-8")

    restored = service.restore_snapshot(snapshot_id=snap.snapshot_id, actor={"id": 1, "username": "root"}, reason="rollback")

    assert restored["ok"] is True
    conn = _db(db_path)
    posts = [row["title"] for row in conn.execute("SELECT title FROM posts ORDER BY id").fetchall()]
    user = conn.execute("SELECT base_level, effective_level FROM users WHERE id=1").fetchone()
    event = conn.execute("SELECT status, pre_restore_snapshot_id FROM snapshot_restore_events ORDER BY started_at DESC LIMIT 1").fetchone()
    conn.close()
    assert posts == ["P1"]
    assert user["effective_level"] == "vip"
    assert (uploads / "f1.txt").exists()
    assert not (uploads / "f2.txt").exists()
    assert event["status"] == "completed"
    assert event["pre_restore_snapshot_id"]
    assert (service.snapshots_root / event["pre_restore_snapshot_id"]).exists()
    assert any(call[0][0] == "SNAPSHOT_RESTORE_COMPLETED" for call in audit_log)


def test_snapshot_path_traversal_is_rejected(tmp_path):
    audit_log = []
    service, _, _ = _service(tmp_path, audit_log)
    try:
        service.verify_snapshot(snapshot_id="../bad")
    except ValueError as exc:
        assert "snapshot_id" in str(exc)
    else:
        raise AssertionError("path traversal snapshot id was not rejected")


def test_checksum_mismatch_blocks_restore(tmp_path):
    audit_log = []
    service, _, uploads = _service(tmp_path, audit_log)
    snap = service.create_snapshot(snapshot_type="manual", actor={"id": 1, "username": "root"}, notes="baseline")
    snapshot = service.get_snapshot(snapshot_id=snap.snapshot_id, actor={"id": 1, "username": "root"})
    Path(snapshot["db_dump_path"]).write_bytes(b"corrupt")

    restored = service.restore_snapshot(snapshot_id=snap.snapshot_id, actor={"id": 1, "username": "root"}, reason="bad")

    assert restored["ok"] is False
    assert "checksum" in restored["msg"]


def test_superweak_enter_and_exit_restore_rolls_back_dirty_state(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    mode = ServerModeService(snapshot_service=service, get_db=lambda: _db(db_path), audit=lambda *args, **kwargs: audit_log.append((args, kwargs)))
    actor = {"id": 1, "username": "root"}

    entered = mode.enter_superweak(actor=actor, confirm="ENABLE_SUPERWEAK", notes="weak test")
    assert entered["ok"] is True
    assert entered["mode"]["current_mode"] == "superweak"

    conn = _db(db_path)
    conn.execute("INSERT INTO posts (id, title) VALUES (2, 'superweak dirty')")
    conn.commit()
    conn.close()

    exited = mode.exit_superweak(actor=actor, action="restore", confirm="RESTORE_BEFORE_SUPERWEAK", reason="done")

    assert exited["ok"] is True
    assert exited["mode"]["current_mode"] == "preprod"
    conn = _db(db_path)
    count = conn.execute("SELECT COUNT(*) AS c FROM posts WHERE id=2").fetchone()["c"]
    conn.close()
    assert count == 0
    assert any(call[0][0] == "SUPERWEAK_EXIT_RESTORE" for call in audit_log)


def test_superweak_keep_dirty_state_requires_root_confirmation(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    mode = ServerModeService(snapshot_service=service, get_db=lambda: _db(db_path), audit=lambda *args, **kwargs: audit_log.append((args, kwargs)))
    actor = {"id": 1, "username": "root"}
    assert mode.enter_superweak(actor=actor, confirm="ENABLE_SUPERWEAK", notes="weak test")["ok"] is True

    kept = mode.exit_superweak(
        actor=actor,
        action="keep_dirty_state",
        confirm="KEEP_DIRTY_SUPERWEAK_STATE",
        reason="intentional",
    )

    assert kept["ok"] is True
    assert "warning" in kept
    assert any(call[0][0] == "SUPERWEAK_EXIT_KEEP_DIRTY_STATE" for call in audit_log)


def test_custom_security_profile_can_be_saved_and_applied(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    saved_settings = []
    mode = ServerModeService(
        snapshot_service=service,
        get_db=lambda: _db(db_path),
        audit=lambda *args, **kwargs: audit_log.append((args, kwargs)),
        save_settings=lambda data: saved_settings.append(dict(data)) or dict(data),
    )
    actor = {"id": 1, "username": "root"}

    saved = mode.save_profile(
        name="staging_lockdown",
        label="Staging Lockdown",
        description="custom staging thresholds",
        settings={"ip_blocking_enabled": True, "integrity_guard_strict_mode": True},
        thresholds={"security_pending_chat_reports_threshold": 3},
        actor=actor,
    )
    assert saved["ok"] is True
    assert saved["profile"]["is_builtin"] is False

    switched = mode.switch_mode(target_mode="staging_lockdown", actor=actor, confirm="", notes="test custom")

    assert switched["ok"] is True
    assert switched["mode"]["current_mode"] == "staging_lockdown"
    assert saved_settings[-1]["ip_blocking_enabled"] is True
    assert saved_settings[-1]["security_pending_chat_reports_threshold"] == 3
    assert any(call[0][0] == "SERVER_MODE_CHANGE" for call in audit_log)


def test_daily_snapshot_runs_once_after_configured_time(tmp_path):
    audit_log = []
    service, _, _ = _service(tmp_path, audit_log)
    saved = []
    settings = {
        "snapshot_daily_auto_enabled": True,
        "snapshot_daily_time": "03:00",
        "snapshot_daily_last_date": "",
    }

    early = service.create_daily_snapshot_if_due(
        actor={"id": 0, "username": "system"},
        settings=settings,
        save_settings=saved.append,
        now=datetime(2026, 4, 27, 2, 59, 0),
    )
    assert early["created"] is False
    assert early["status"]["reason"] == "before_scheduled_time"

    due = service.create_daily_snapshot_if_due(
        actor={"id": 0, "username": "system"},
        settings=settings,
        save_settings=saved.append,
        now=datetime(2026, 4, 27, 3, 0, 0),
    )

    assert due["ok"] is True
    assert due["created"] is True
    assert saved[-1] == {"snapshot_daily_last_date": "2026-04-27"}
    snapshot = service.get_snapshot(snapshot_id=due["snapshot_id"], actor={"id": 1, "username": "root"})
    assert snapshot["type"] == "scheduled"


def test_runtime_reset_creates_pre_reset_snapshot_and_clears_runtime_tables_and_files(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    (uploads / "dirty.txt").write_text("dirty", encoding="utf-8")
    conn = _db(db_path)
    conn.execute("INSERT INTO posts (id, title) VALUES (2, 'dirty')")
    conn.commit()
    conn.close()

    result = service.reset_runtime_state(
        actor={"id": 1, "username": "root"},
        confirm="RESET_RUNTIME_STATE",
        reason="cleanup",
    )

    assert result["ok"] is True
    assert result["pre_reset_snapshot_id"].startswith("snap_")
    assert "posts" in result["cleared_tables"]
    assert not (uploads / "dirty.txt").exists()
    conn = _db(db_path)
    post_count = conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"]
    root_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE username='root'").fetchone()["c"]
    pre_reset = conn.execute("SELECT type, status FROM snapshots WHERE id=?", (result["pre_reset_snapshot_id"],)).fetchone()
    conn.close()
    assert post_count == 0
    assert root_count == 1
    assert pre_reset["type"] == "pre_reset"
    assert pre_reset["status"] == "ready"
    assert any(call[0][0] == "SYSTEM_RUNTIME_RESET" for call in audit_log)


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


class _FakeSnapshotService:
    def __init__(self):
        self.created = []

    def create_snapshot(self, *, snapshot_type, actor, notes=None):
        self.created.append((snapshot_type, actor["username"], notes))
        return type("Result", (), {"ok": True, "snapshot_id": "snap_20260427_153000_abcdef", "status": "ready"})()

    def list_snapshots(self, *, actor):
        return [{"id": "snap_20260427_153000_abcdef", "status": "ready", "type": "manual"}]

    def get_snapshot(self, *, snapshot_id, actor=None):
        return {"id": snapshot_id, "status": "ready"}

    def restore_snapshot(self, *, snapshot_id, actor, reason, dry_run=False):
        return {"ok": True, "snapshot_id": snapshot_id, "dry_run": dry_run}

    def delete_snapshot(self, *, snapshot_id, actor, reason):
        return {"ok": True}

    def daily_snapshot_status(self, *, settings):
        return {"enabled": True, "due": True, "reason": "due"}

    def create_daily_snapshot_if_due(self, *, actor, settings, save_settings=None, force=False, notes=None):
        if save_settings:
            save_settings({"snapshot_daily_last_date": "2026-04-27"})
        return {"ok": True, "created": True, "snapshot_id": "snap_20260427_153000_abcdef", "force": force}

    def reset_runtime_state(self, *, actor, confirm, reason):
        if confirm != "RESET_RUNTIME_STATE":
            return {"ok": False, "msg": "confirm 必須等於 RESET_RUNTIME_STATE"}
        return {"ok": True, "pre_reset_snapshot_id": "snap_20260427_153000_abcdef", "cleared_tables": ["posts"]}


class _FakeServerModeService:
    def get_current_mode(self):
        return {"current_mode": "preprod", "previous_mode": None, "active_snapshot_id": None}

    def list_profiles(self):
        return [{"name": "preprod", "label": "preprod（準上線）", "is_builtin": True}]

    def switch_mode(self, **kwargs):
        return {"ok": True, "mode": {"current_mode": kwargs["target_mode"]}}

    def exit_superweak(self, **kwargs):
        return {"ok": True, "mode": {"current_mode": "preprod"}}


def _build_admin_app(actor_box, snapshot_service):
    app = Flask(__name__)
    app.testing = True
    register_system_admin_routes(app, {
        "ANCHOR_DIR": ".",
        "BASE_DIR": ".",
        "CHAT_DIR": ".",
        "DB_PATH": "missing.db",
        "LOG_DIR": ".",
        "SERVER_LOG_PATH": "server.log",
        "STORAGE_DIR": ".",
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": lambda: None,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: {},
        "get_ua": lambda: "test-agent",
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 3, "super_admin": 4}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": lambda data: data,
        "server_mode_service": _FakeServerModeService(),
        "snapshot_service": snapshot_service,
        "verify_audit_integrity": lambda: (True, None, "ok"),
    })
    return app


def test_snapshot_api_is_root_only_and_supports_dry_run_restore():
    snapshot_service = _FakeSnapshotService()
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_admin_app(actor_box, snapshot_service).test_client()

    created = client.post("/api/admin/snapshots", json={"type": "manual", "notes": "api"})
    assert created.status_code == 200
    assert created.get_json()["snapshot_id"] == "snap_20260427_153000_abcdef"

    dry_run = client.post(
        "/api/admin/snapshots/snap_20260427_153000_abcdef/restore",
        json={"confirm": "DRY_RUN", "dry_run": True, "reason": "validate"},
    )
    assert dry_run.status_code == 200
    assert dry_run.get_json()["dry_run"] is True

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    denied = client.post("/api/admin/snapshots", json={"type": "manual"})
    assert denied.status_code == 403


def test_daily_snapshot_and_reset_api_are_root_only():
    snapshot_service = _FakeSnapshotService()
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_admin_app(actor_box, snapshot_service).test_client()

    daily = client.post("/api/admin/snapshots/daily", json={"confirm": "RUN_DAILY_SNAPSHOT", "force": True})
    assert daily.status_code == 200
    assert daily.get_json()["created"] is True

    reset = client.post("/api/admin/system-reset", json={"confirm": "RESET_RUNTIME_STATE", "reason": "test"})
    assert reset.status_code == 200
    assert reset.get_json()["pre_reset_snapshot_id"] == "snap_20260427_153000_abcdef"

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    denied = client.post("/api/admin/system-reset", json={"confirm": "RESET_RUNTIME_STATE"})
    assert denied.status_code == 403
