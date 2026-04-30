import io
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes, restart_launcher_code
from services.snapshots import ServerModeService, SnapshotService, ensure_snapshot_schema
from services.upload_security import ensure_upload_security_schema


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
        VALUES (1, 'root', 'super_admin', 'active', 'normal', 'normal', 'normal');
        INSERT INTO posts (id, title) VALUES (1, 'P1');
        INSERT INTO system_settings (key, value, value_type, updated_at, updated_by)
        VALUES ('maintenance_mode', 'false', 'bool', '2026-01-01T00:00:00', 'test');
        """
    )
    ensure_snapshot_schema(conn)
    conn.commit()
    conn.close()


def _service(tmp_path, audit_log, *, runtime_secret_files=None):
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
        runtime_secret_files=runtime_secret_files,
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
    conn.execute("UPDATE users SET base_level='normal', effective_level='restricted', member_level='restricted' WHERE id=1")
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
    assert user["effective_level"] == "normal"
    assert (uploads / "f1.txt").exists()
    assert not (uploads / "f2.txt").exists()
    assert event["status"] == "completed"
    assert event["pre_restore_snapshot_id"]
    assert (service.snapshots_root / event["pre_restore_snapshot_id"]).exists()
    assert any(call[0][0] == "SNAPSHOT_RESTORE_COMPLETED" for call in audit_log)


def test_portable_snapshot_archive_restores_on_different_instance(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    source_audit = []
    source, source_db, source_uploads = _service(source_root, source_audit)
    (source_uploads / "portable.txt").write_text("portable source", encoding="utf-8")
    snap = source.create_snapshot(snapshot_type="manual", actor={"id": 1, "username": "root"}, notes="portable baseline")
    exported = source.export_snapshot_archive(snapshot_id=snap.snapshot_id, actor={"id": 1, "username": "root"})

    assert exported["ok"] is True
    archive_path = Path(exported["path"])
    assert archive_path.exists()

    target_audit = []
    target, target_db, target_uploads = _service(target_root, target_audit)
    (target_uploads / "dirty.txt").write_text("dirty target", encoding="utf-8")
    conn = _db(target_db)
    conn.execute("INSERT INTO posts (id, title) VALUES (99, 'target dirty')")
    conn.commit()
    conn.close()

    restored = target.restore_snapshot_archive(
        actor={"id": 1, "username": "root"},
        archive_path=archive_path,
        reason="portable restore",
    )

    assert restored["ok"] is True
    assert restored["imported_snapshot_id"] == snap.snapshot_id
    conn = _db(target_db)
    posts = [row["title"] for row in conn.execute("SELECT title FROM posts ORDER BY id").fetchall()]
    snapshot_row = conn.execute("SELECT storage_path, db_dump_path FROM snapshots WHERE id=?", (snap.snapshot_id,)).fetchone()
    conn.close()
    assert posts == ["P1"]
    assert (target_uploads / "portable.txt").read_text(encoding="utf-8") == "portable source"
    assert not (target_uploads / "dirty.txt").exists()
    assert str(target.snapshots_root) in snapshot_row["storage_path"]
    assert Path(snapshot_row["db_dump_path"]).exists()
    assert any(call[0][0] == "SNAPSHOT_IMPORTED" for call in target_audit)


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


def test_production_mode_requires_confirmation_and_hardens_accounts(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    conn = _db(db_path)
    conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE users ADD COLUMN is_default_password INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, is_revoked INTEGER NOT NULL DEFAULT 0, revoked_at TEXT)")
    conn.execute("INSERT INTO users (id, username, role, status, member_level, base_level, effective_level, must_change_password, is_default_password) VALUES (2, 'admin', 'manager', 'active', 'normal', 'normal', 'normal', 0, 0)")
    conn.execute("INSERT INTO users (id, username, role, status, member_level, base_level, effective_level, must_change_password, is_default_password) VALUES (3, 'test', 'user', 'active', 'trusted', 'trusted', 'trusted', 0, 1)")
    conn.execute("INSERT INTO sessions (id, user_id, is_revoked) VALUES (1, 3, 0)")
    ensure_upload_security_schema(conn)
    conn.commit()
    conn.close()
    saved_settings = []
    mode = ServerModeService(
        snapshot_service=service,
        get_db=lambda: _db(db_path),
        audit=lambda *args, **kwargs: audit_log.append((args, kwargs)),
        save_settings=lambda data: saved_settings.append(dict(data)) or dict(data),
    )
    actor = {"id": 1, "username": "root"}

    denied = mode.switch_mode(target_mode="production", actor=actor, confirm="", notes="go live")
    assert denied["ok"] is False
    assert "GO_LIVE" in denied["msg"]

    switched = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE", notes="go live")
    assert switched["ok"] is True
    assert switched["mode"]["current_mode"] == "production"
    assert saved_settings[-1]["audit_chain_enabled"] is True
    assert saved_settings[-1]["feature_account_security_enabled"] is True
    assert saved_settings[-1]["captcha_mode"] == "math"
    assert switched["production"]["accounts"]["default_password_reset_required"] == 3
    assert switched["production"]["accounts"]["test_accounts_disabled"] == 1

    conn = _db(db_path)
    rows = {
        row["username"]: dict(row)
        for row in conn.execute("SELECT username, status, must_change_password, is_default_password FROM users")
    }
    session = conn.execute("SELECT is_revoked FROM sessions WHERE user_id=3").fetchone()
    policy = conn.execute("SELECT scanner_enabled, scanner_backend, fail_closed_on_scanner_error, yara_enabled FROM cloud_drive_security_policies WHERE scope='default'").fetchone()
    conn.close()
    assert rows["root"]["must_change_password"] == 1
    assert rows["admin"]["must_change_password"] == 1
    assert rows["test"]["status"] == "inactive"
    assert rows["test"]["must_change_password"] == 1
    assert session["is_revoked"] == 1
    assert policy["scanner_enabled"] == 1
    assert policy["scanner_backend"] == "clamav"
    assert policy["fail_closed_on_scanner_error"] == 1
    assert policy["yara_enabled"] == 1


def test_internal_test_mode_disables_open_registration_and_revokes_non_root_sessions(tmp_path):
    audit_log = []
    service, db_path, uploads = _service(tmp_path, audit_log)
    conn = _db(db_path)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, is_revoked INTEGER NOT NULL DEFAULT 0, revoked_at TEXT)")
    conn.execute("INSERT INTO users (id, username, role, status, member_level, base_level, effective_level) VALUES (2, 'alice', 'user', 'active', 'normal', 'normal', 'normal')")
    conn.execute("INSERT INTO sessions (id, user_id, is_revoked) VALUES (1, 1, 0)")
    conn.execute("INSERT INTO sessions (id, user_id, is_revoked) VALUES (2, 2, 0)")
    conn.commit()
    conn.close()
    saved_settings = []
    mode = ServerModeService(
        snapshot_service=service,
        get_db=lambda: _db(db_path),
        audit=lambda *args, **kwargs: audit_log.append((args, kwargs)),
        save_settings=lambda data: saved_settings.append(dict(data)) or dict(data),
    )

    switched = mode.switch_mode(
        target_mode="internal_test",
        actor={"id": 1, "username": "root"},
        confirm="",
        notes="invite-only test",
    )

    assert switched["ok"] is True
    assert switched["mode"]["current_mode"] == "internal_test"
    assert saved_settings[-1]["allow_register"] is False
    assert saved_settings[-1]["feature_account_security_enabled"] is True
    assert switched["internal_test"]["sessions_revoked"] == 1
    conn = _db(db_path)
    sessions = {row["user_id"]: row["is_revoked"] for row in conn.execute("SELECT user_id, is_revoked FROM sessions")}
    conn.close()
    assert sessions[1] == 0
    assert sessions[2] == 1


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
    settings = {
        row["key"]: row["value"]
        for row in conn.execute(
            "SELECT key, value FROM system_settings WHERE key LIKE 'feature_%' OR key IN ('allow_register', 'snapshot_daily_auto_enabled', 'storage_maintenance_auto_enabled')"
        ).fetchall()
    }
    conn.close()
    assert post_count == 0
    assert root_count == 1
    assert pre_reset["type"] == "pre_reset"
    assert pre_reset["status"] == "ready"
    assert settings["feature_accounts_enabled"] == "True"
    assert settings["feature_audit_log_enabled"] == "True"
    assert settings["feature_snapshot_restore_enabled"] == "True"
    assert settings["feature_chat_enabled"] == "False"
    assert settings["feature_community_enabled"] == "False"
    assert settings["feature_storage_albums_enabled"] == "False"
    assert settings["feature_comfyui_enabled"] == "False"
    assert settings["feature_economy_enabled"] == "False"
    assert settings["feature_games_enabled"] == "False"
    assert settings["allow_register"] == "False"
    assert any(call[0][0] == "SYSTEM_RUNTIME_RESET" for call in audit_log)


def test_runtime_reset_removes_generated_secret_files_but_keeps_tls_files(tmp_path):
    audit_log = []
    base = tmp_path / "app"
    secret_names = [
        ".chain_seed",
        ".csrfkey",
        ".fkey",
        ".fley",
        ".integrity_key",
        "integrity_manifest.json",
    ]
    service, _db_path, _uploads = _service(
        tmp_path,
        audit_log,
        runtime_secret_files=[base / name for name in secret_names],
    )
    for name in secret_names:
        (base / name).write_text(f"{name}-value", encoding="utf-8")
    (base / "cert.pem").write_text("deployment certificate", encoding="utf-8")
    (base / "key.pem").write_text("deployment private key", encoding="utf-8")

    result = service.reset_runtime_state(
        actor={"id": 1, "username": "root"},
        confirm="RESET_RUNTIME_STATE",
        reason="rotate generated runtime secrets",
    )

    assert result["ok"] is True
    assert result["requires_restart"] is True
    assert sorted(result["runtime_secret_files_removed"]) == sorted(secret_names)
    assert result["runtime_secret_files_skipped"] == []
    for name in secret_names:
        assert not (base / name).exists()
    assert (base / "cert.pem").exists()
    assert (base / "key.pem").exists()
    reset_detail = next(call[1]["detail"] for call in audit_log if call[0][0] == "SYSTEM_RUNTIME_RESET")
    assert "runtime_secret_files_removed=" in reset_detail
    assert ".chain_seed" in reset_detail


def test_runtime_reset_invokes_points_and_audit_chain_resets(tmp_path):
    audit_log = []
    service, _db_path, _uploads = _service(tmp_path, audit_log)
    calls = {"points": [], "audit": []}
    service.reset_points_chain = lambda **kwargs: calls["points"].append(kwargs) or {"ok": True, "reset": True}
    service.reset_audit_chain = lambda *args, **kwargs: calls["audit"].append((args, kwargs)) or {"ok": True, "reset": True}

    result = service.reset_runtime_state(
        actor={"id": 1, "username": "root"},
        confirm="RESET_RUNTIME_STATE",
        reason="cleanup",
    )

    assert result["ok"] is True
    assert result["points_chain_reset"]["reset"] is True
    assert result["audit_chain_reset"]["reset"] is True
    assert result["management_only_settings"]["feature_accounts_enabled"] is True
    assert result["management_only_settings"]["feature_chat_enabled"] is False
    assert calls["points"][0]["pre_reset_snapshot_id"] == result["pre_reset_snapshot_id"]
    assert calls["points"][0]["reason"] == "cleanup"
    assert calls["audit"][0][0][0] == "SYSTEM_RUNTIME_RESET"
    assert "points_chain_reset=True" in calls["audit"][0][1]["detail"]


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


class _FakeSnapshotService:
    def __init__(self):
        self.created = []
        self.download_path = None
        self.upload_restores = []

    def create_snapshot(self, *, snapshot_type, actor, notes=None):
        self.created.append((snapshot_type, actor["username"], notes))
        return type("Result", (), {"ok": True, "snapshot_id": "snap_20260427_153000_abcdef", "status": "ready"})()

    def list_snapshots(self, *, actor):
        return [{"id": "snap_20260427_153000_abcdef", "status": "ready", "type": "manual"}]

    def get_snapshot(self, *, snapshot_id, actor=None):
        return {"id": snapshot_id, "status": "ready"}

    def restore_snapshot(self, *, snapshot_id, actor, reason, dry_run=False):
        return {"ok": True, "snapshot_id": snapshot_id, "dry_run": dry_run}

    def export_snapshot_archive(self, *, snapshot_id, actor=None):
        if not self.download_path:
            return {"ok": False, "msg": "download path not configured"}
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "path": str(self.download_path),
            "filename": Path(self.download_path).name,
            "size_bytes": Path(self.download_path).stat().st_size,
        }

    def restore_snapshot_archive(self, *, actor, file_storage, reason, dry_run=False):
        self.upload_restores.append((actor["username"], getattr(file_storage, "filename", ""), reason, dry_run))
        return {"ok": True, "imported_snapshot_id": "snap_20260427_153000_abcdef", "dry_run": dry_run}

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
    def __init__(self):
        self.saved_profiles = []

    def get_current_mode(self):
        return {"current_mode": "preprod", "previous_mode": None, "active_snapshot_id": None}

    def list_profiles(self):
        return [{"name": "preprod", "label": "preprod（準上線）", "is_builtin": True, "settings": {}, "thresholds": {}}] + self.saved_profiles

    def save_profile(self, **kwargs):
        profile = {
            "name": kwargs["name"],
            "label": kwargs["label"],
            "description": kwargs.get("description") or "",
            "settings": kwargs.get("settings") or {},
            "thresholds": kwargs.get("thresholds") or {},
            "is_builtin": False,
        }
        self.saved_profiles.append(profile)
        return {"ok": True, "profile": profile}

    def switch_mode(self, **kwargs):
        return {"ok": True, "mode": {"current_mode": kwargs["target_mode"]}}

    def exit_superweak(self, **kwargs):
        return {"ok": True, "mode": {"current_mode": "preprod"}}


def _build_admin_app(actor_box, snapshot_service, restart_calls=None):
    app = Flask(__name__)
    app.testing = True
    if restart_calls is None:
        restart_calls = []
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
        "schedule_server_restart": lambda **kwargs: restart_calls.append(kwargs) or {"mode": "test"},
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


def test_snapshot_api_downloads_and_restores_uploaded_portable_archive(tmp_path):
    snapshot_service = _FakeSnapshotService()
    archive = tmp_path / "snap_20260427_153000_abcdef.snapshot.tar.gz"
    archive.write_bytes(b"portable snapshot bytes")
    snapshot_service.download_path = archive
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_admin_app(actor_box, snapshot_service).test_client()

    downloaded = client.get("/api/admin/snapshots/snap_20260427_153000_abcdef/download")
    assert downloaded.status_code == 200
    assert downloaded.data == b"portable snapshot bytes"
    assert "attachment" in downloaded.headers["Content-Disposition"]

    restored = client.post(
        "/api/admin/snapshots/upload-restore",
        data={
            "confirm": "RESTORE",
            "reason": "api portable restore",
            "file": (io.BytesIO(b"portable upload"), "portable.snapshot.tar.gz"),
        },
        content_type="multipart/form-data",
    )
    assert restored.status_code == 200
    assert restored.get_json()["imported_snapshot_id"] == "snap_20260427_153000_abcdef"
    assert snapshot_service.upload_restores == [("root", "portable.snapshot.tar.gz", "api portable restore", False)]

    dry_run = client.post(
        "/api/admin/snapshots/upload-restore",
        data={
            "confirm": "DRY_RUN",
            "dry_run": "true",
            "file": (io.BytesIO(b"portable upload"), "portable.snapshot.tar.gz"),
        },
        content_type="multipart/form-data",
    )
    assert dry_run.status_code == 200
    assert dry_run.get_json()["dry_run"] is True


def test_daily_snapshot_and_reset_api_are_root_only():
    snapshot_service = _FakeSnapshotService()
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    restart_calls = []
    client = _build_admin_app(actor_box, snapshot_service, restart_calls).test_client()

    daily = client.post("/api/admin/snapshots/daily", json={"confirm": "RUN_DAILY_SNAPSHOT", "force": True})
    assert daily.status_code == 200
    assert daily.get_json()["created"] is True

    reset = client.post("/api/admin/system-reset", json={"confirm": "RESET_RUNTIME_STATE", "reason": "test"})
    assert reset.status_code == 200
    reset_data = reset.get_json()
    assert reset_data["pre_reset_snapshot_id"] == "snap_20260427_153000_abcdef"
    assert reset_data["restart_scheduled"] is True
    assert restart_calls == [{"reason": "system-reset", "delay_seconds": 1.25}]

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    denied = client.post("/api/admin/system-reset", json={"confirm": "RESET_RUNTIME_STATE"})
    assert denied.status_code == 403


def test_manual_restart_uses_restart_scheduler():
    snapshot_service = _FakeSnapshotService()
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    restart_calls = []
    client = _build_admin_app(actor_box, snapshot_service, restart_calls).test_client()

    res = client.post("/api/admin/restart")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["restart_scheduled"] is True
    assert restart_calls == [{"reason": "manual-restart", "delay_seconds": 1.25}]


def test_restart_launcher_waits_for_parent_exit_and_port_release():
    code = restart_launcher_code()
    assert "parent_alive()" in code
    assert "port_is_free()" in code
    assert "close_fds=True" in code
    assert "start_new_session=True" in code
    assert "subprocess.Popen([python_exe, script_path]" in code


def test_security_profile_api_validates_and_server_mode_lists_profiles():
    snapshot_service = _FakeSnapshotService()
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_admin_app(actor_box, snapshot_service).test_client()

    mode = client.get("/api/admin/server-mode")
    assert mode.status_code == 200
    assert mode.get_json()["profiles"][0]["name"] == "preprod"

    invalid = client.post("/api/admin/security-center/profiles", json={
        "name": "custom_lock",
        "label": "Custom Lock",
        "settings": {"not_a_setting": True},
        "thresholds": {},
    })
    assert invalid.status_code == 400
    assert "不支援的 settings key" in invalid.get_json()["msg"]

    saved = client.post("/api/admin/security-center/profiles", json={
        "name": "custom_lock",
        "label": "Custom Lock",
        "settings": {"ip_blocking_enabled": True},
        "thresholds": {"security_pending_chat_reports_threshold": 2},
    })
    assert saved.status_code == 200
    assert saved.get_json()["profile"]["settings"]["ip_blocking_enabled"] is True


def test_security_center_and_server_output_are_root_only():
    snapshot_service = _FakeSnapshotService()
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_admin_app(actor_box, snapshot_service).test_client()

    denied_center = client.get("/api/admin/security-center")
    denied_output = client.get("/api/admin/server-output")
    assert denied_center.status_code == 403
    assert denied_output.status_code == 403

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    output = client.get("/api/admin/server-output?limit=10")
    assert output.status_code == 200
    assert output.get_json()["ok"] is True
