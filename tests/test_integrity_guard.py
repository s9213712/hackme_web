import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes
from services.integrity_guard import CONFIRM_APPROVE, IntegrityGuard, ensure_integrity_schema
from services.snapshots import ServerModeService, ensure_snapshot_schema


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_integrity_schema(conn)
    conn.commit()
    return conn


def _write_project(base):
    (base / "services").mkdir()
    (base / "routes").mkdir()
    (base / "public" / "js").mkdir(parents=True)
    (base / "database").mkdir()
    (base / "server.py").write_text("print('server')\n", encoding="utf-8")
    (base / "services" / "auth.py").write_text("AUTH = True\n", encoding="utf-8")
    (base / "routes" / "system_admin.py").write_text("ROOT = True\n", encoding="utf-8")
    (base / "public" / "js" / "50-admin.js").write_text("const admin = true;\n", encoding="utf-8")
    (base / "database" / "bootstrap.schema.sql").write_text("CREATE TABLE x(id);\n", encoding="utf-8")
    (base / "requirements.txt").write_text("flask\n", encoding="utf-8")


def _guard(tmp_path, audit_log=None):
    base = tmp_path / "app"
    base.mkdir()
    _write_project(base)
    db_path = tmp_path / "integrity.db"
    audit_log = audit_log if audit_log is not None else []
    guard = IntegrityGuard(
        base_dir=base,
        signing_key=b"test-signing-key",
        get_db=lambda: _db(db_path),
        audit=lambda *args, **kwargs: audit_log.append((args, kwargs)),
    )
    return guard, base, audit_log


def test_integrity_scan_creates_initial_manifest_without_findings(tmp_path):
    guard, base, _ = _guard(tmp_path)
    status = guard.scan(actor="system")
    assert status["ok"] is True
    assert status["summary"]["pending"] == 0
    assert (base / "integrity_manifest.json").exists()


def test_modified_deleted_and_added_files_create_findings(tmp_path):
    guard, base, _ = _guard(tmp_path)
    guard.scan(actor="system")
    (base / "server.py").write_text("print('changed')\n", encoding="utf-8")
    os.remove(base / "requirements.txt")
    (base / "services" / "new_service.py").write_text("NEW = True\n", encoding="utf-8")

    status = guard.scan(actor="system")
    findings = guard.list_findings(status="pending")
    by_type = {item["change_type"] for item in findings}
    assert {"modified", "deleted", "added"} <= by_type
    assert status["summary"]["pending"] >= 3


def test_auth_admin_security_file_changes_are_high_risk(tmp_path):
    guard, base, _ = _guard(tmp_path)
    guard.scan(actor="system")
    (base / "services" / "auth.py").write_text("AUTH = 'changed'\n", encoding="utf-8")
    guard.scan(actor="system")
    finding = next(item for item in guard.list_findings(status="pending") if item["file_path"] == "services/auth.py")
    assert finding["risk_level"] == "high"


def test_manifest_signature_tampering_creates_high_risk_finding(tmp_path):
    guard, base, _ = _guard(tmp_path)
    guard.scan(actor="system")
    manifest = base / "integrity_manifest.json"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("manifest_signature", "manifest_signature_tampered"), encoding="utf-8")
    guard.scan(actor="system")
    finding = next(item for item in guard.list_findings(status="pending") if item["file_path"] == "integrity_manifest.json")
    assert finding["risk_level"] == "high"


def test_approve_updates_manifest_and_reject_does_not(tmp_path):
    guard, base, audit_log = _guard(tmp_path)
    guard.scan(actor="system")
    old_manifest = (base / "integrity_manifest.json").read_text(encoding="utf-8")
    (base / "server.py").write_text("print('approved')\n", encoding="utf-8")
    guard.scan(actor="system")
    finding = next(item for item in guard.list_findings(status="pending") if item["file_path"] == "server.py")

    rejected = guard.review_finding(finding["id"], action="reject", actor={"username": "root"}, note="bad")
    assert rejected["ok"] is True
    assert (base / "integrity_manifest.json").read_text(encoding="utf-8") == old_manifest

    guard.scan(actor="system")
    finding = next(item for item in guard.list_findings(status="pending") if item["file_path"] == "server.py")
    approved = guard.review_finding(
        finding["id"],
        action="approve",
        actor={"username": "root"},
        note="trusted deploy",
        confirm=CONFIRM_APPROVE,
    )
    assert approved["ok"] is True
    assert (base / "integrity_manifest.json").read_text(encoding="utf-8") != old_manifest
    assert any("INTEGRITY_FINDING_APPROVED" in args for args, _ in audit_log)


def test_preprod_mode_is_blocked_by_pending_high_risk_integrity_finding(tmp_path):
    guard, base, _ = _guard(tmp_path)
    guard.scan(actor="system")
    (base / "server.py").write_text("print('danger')\n", encoding="utf-8")
    guard.scan(actor="system")
    db_path = tmp_path / "mode.db"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        ensure_snapshot_schema(conn)
        conn.commit()
        return conn

    mode = ServerModeService(snapshot_service=None, get_db=get_db, audit=lambda *args, **kwargs: None, integrity_guard=guard)
    result = mode.switch_mode(target_mode="preprod", actor={"id": 1, "username": "root"}, confirm="", notes="")
    assert result["ok"] is False
    assert result["high_risk_count"] >= 1


def _admin_app(tmp_path, actor_box, guard, audit_log):
    app = Flask(__name__)
    app.testing = True
    register_system_admin_routes(app, {
        "ANCHOR_DIR": str(tmp_path),
        "BASE_DIR": str(tmp_path),
        "CHAT_DIR": str(tmp_path),
        "DB_PATH": str(tmp_path / "app.db"),
        "LOG_DIR": str(tmp_path),
        "SERVER_LOG_PATH": str(tmp_path / "server.log"),
        "STORAGE_DIR": str(tmp_path / "storage"),
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: audit_log.append((args, kwargs)),
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": guard.get_db,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: {},
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": lambda data: data,
        "snapshot_service": None,
        "server_mode_service": None,
        "integrity_guard": guard,
        "verify_audit_integrity": lambda: (True, None, "ok"),
    })
    return app


def test_integrity_api_is_root_only_and_reviews_are_audited(tmp_path):
    guard, base, audit_log = _guard(tmp_path)
    guard.scan(actor="system")
    (base / "server.py").write_text("print('api')\n", encoding="utf-8")
    guard.scan(actor="system")
    finding = next(item for item in guard.list_findings(status="pending") if item["file_path"] == "server.py")
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _admin_app(tmp_path, actor_box, guard, audit_log).test_client()

    status = client.get("/api/root/integrity/status")
    assert status.status_code == 200
    bad_confirm = client.post(f"/api/root/integrity/findings/{finding['id']}/approve", json={"confirm": "YES"})
    assert bad_confirm.status_code == 400
    rejected = client.post(f"/api/root/integrity/findings/{finding['id']}/reject", json={"note": "not expected"})
    assert rejected.status_code == 200
    assert any("INTEGRITY_FINDING_REJECTED" in args for args, _ in audit_log)

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    denied = client.get("/api/root/integrity/status")
    assert denied.status_code == 403


def test_report_does_not_expose_signing_key(tmp_path):
    guard, _, _ = _guard(tmp_path)
    guard.scan(actor="system")
    report = guard.export_report()
    assert "test-signing-key" not in str(report)
