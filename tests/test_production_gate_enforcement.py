"""Locks the production-gate enforcement contract.

Existing tests/test_snapshots.py covers the happy path
(13 reports passing -> switch succeeds) and the empty-DB blocked
path. This file adds the granular regression cases the launch-check
UI promises to surface:

1. Wrong confirm phrase -> blocked
2. 0 / 13 reports -> blocked
3. 12 / 13 reports (one missing) -> blocked, response lists the
   missing report
4. 13 / 13 inserted but ONE has critical_findings_count > 0 -> blocked
5. 13 / 13 inserted but ONE has high_findings_count > 0 -> blocked
6. 13 / 13 inserted but ONE has empty report_hash -> blocked
7. 13 / 13 inserted but ONE has pass=False -> blocked
8. 13 / 13 perfect -> mode actually switches to production

If any of these regress, an operator could push to production with
unverified or actively-failing reports — exactly the contamination
the gate exists to prevent.
"""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from services.snapshots import (
    PRODUCTION_REQUIRED_REPORT_TYPES,
    ServerModeService,
    SnapshotService,
    ensure_snapshot_schema,
)


def _build_runtime(tmp_path):
    """Build a ServerModeService backed by a snapshot service, mirroring
    the existing tests/test_snapshots.py helpers — so we drive the real
    gate-and-switch path, not a stripped-down stub.
    """
    base = tmp_path / "app"
    base.mkdir()
    db_path = base / "database.db"
    uploads = base / "uploads"
    storage = base / "storage"
    uploads.mkdir()
    storage.mkdir()

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # Minimum supporting tables ServerModeService.switch_mode reaches into.
    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "member_level TEXT, base_level TEXT, effective_level TEXT, must_change_password INTEGER DEFAULT 0, "
        "is_default_password INTEGER DEFAULT 0)"
    )
    conn.execute(
        "INSERT INTO users (id, username, role, status, member_level, base_level, effective_level) "
        "VALUES (1,'root','super_admin','active','normal','normal','normal')"
    )
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, is_revoked INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE user_passwords (id INTEGER PRIMARY KEY, user_id INTEGER, password_hash TEXT, created_at TEXT)")
    ensure_snapshot_schema(conn)
    conn.commit()
    conn.close()

    snapshot = SnapshotService(
        get_db=get_db,
        db_path=db_path,
        base_dir=base,
        storage_root=storage,
        audit=lambda *a, **kw: None,
        file_roots=[uploads],
        config_files=[],
    )
    saved = []
    mode = ServerModeService(
        snapshot_service=snapshot,
        get_db=get_db,
        audit=lambda *a, **kw: None,
        save_settings=lambda data: saved.append(dict(data)) or dict(data),
    )
    return mode, get_db, db_path


def _insert_report(db_path, report_type, *, _pass=True, critical=0, high=0, report_hash=None, target_commit="test-commit"):
    """Insert a single production_entry_reports row with controllable
    failure dimensions, so each test can inject exactly the kind of
    failure it wants to see blocked.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    now = datetime.now().isoformat()
    rh = report_hash if report_hash is not None else f"hash_{report_type}"
    conn.execute(
        """
        INSERT INTO production_entry_reports
        (id, report_type, report_hash, target_commit, target_branch, server_mode,
         test_result, pass, critical_findings_count, high_findings_count,
         unresolved_findings_json, tester, signature, created_at)
        VALUES (?, ?, ?, ?, 'test-branch', 'test', ?, ?, ?, ?, '[]', 'pytest', '', ?)
        """,
        (
            f"rep_{report_type}",
            report_type,
            rh,
            target_commit,
            "pass" if _pass else "fail",
            1 if _pass else 0,
            int(critical),
            int(high),
            now,
        ),
    )
    conn.commit()
    conn.close()


def _insert_all_passing(db_path):
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES:
        _insert_report(db_path, rt)


# ── #1 Wrong confirm phrase ───────────────────────────────────────────


def test_gate_blocks_with_wrong_confirm_phrase(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    _insert_all_passing(db_path)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="LETS_GO")
    assert res["ok"] is False
    assert "GO_LIVE" in res["msg"]


# ── #2 Empty DB ───────────────────────────────────────────────────────


def test_gate_blocks_when_no_reports(tmp_path):
    mode, _, _ = _build_runtime(tmp_path)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is False
    assert "production gate" in res["msg"]
    requirements = res.get("requirements") or {}
    assert set(requirements.get("missing", [])) == set(PRODUCTION_REQUIRED_REPORT_TYPES)


# ── #3 12 / 13 (one missing) ─────────────────────────────────────────


def test_gate_blocks_when_one_report_missing(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    # Insert 12 of the 13 — drop the first one.
    skipped = PRODUCTION_REQUIRED_REPORT_TYPES[0]
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES[1:]:
        _insert_report(db_path, rt)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is False
    requirements = res.get("requirements") or {}
    # The one we skipped must show up as missing — and only that one.
    assert requirements.get("missing") == [skipped]
    assert not requirements.get("failed")


# ── #4 critical_findings_count > 0 ─────────────────────────────────────


def test_gate_blocks_when_one_report_has_critical_finding(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    # All passing except one with critical=2.
    bad_one = PRODUCTION_REQUIRED_REPORT_TYPES[3]
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES:
        if rt == bad_one:
            _insert_report(db_path, rt, critical=2)
        else:
            _insert_report(db_path, rt)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is False
    requirements = res.get("requirements") or {}
    assert bad_one in requirements.get("failed", []), requirements


# ── #5 high_findings_count > 0 ─────────────────────────────────────────


def test_gate_blocks_when_one_report_has_high_finding(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    bad_one = PRODUCTION_REQUIRED_REPORT_TYPES[5]
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES:
        if rt == bad_one:
            _insert_report(db_path, rt, high=1)
        else:
            _insert_report(db_path, rt)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is False
    requirements = res.get("requirements") or {}
    assert bad_one in requirements.get("failed", []), requirements


# ── #6 empty report_hash ──────────────────────────────────────────────


def test_gate_blocks_when_one_report_has_empty_hash(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    bad_one = PRODUCTION_REQUIRED_REPORT_TYPES[7]
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES:
        if rt == bad_one:
            _insert_report(db_path, rt, report_hash="")
        else:
            _insert_report(db_path, rt)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is False
    requirements = res.get("requirements") or {}
    assert bad_one in requirements.get("failed", []), requirements


# ── #7 pass=False ─────────────────────────────────────────────────────


def test_gate_blocks_when_one_report_has_pass_false(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    bad_one = PRODUCTION_REQUIRED_REPORT_TYPES[10]
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES:
        if rt == bad_one:
            _insert_report(db_path, rt, _pass=False)
        else:
            _insert_report(db_path, rt)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is False
    requirements = res.get("requirements") or {}
    assert bad_one in requirements.get("failed", []), requirements


# ── #8 13 / 13 perfect -> switch succeeds ─────────────────────────────


def test_gate_allows_switch_when_all_13_pass(tmp_path):
    mode, _, db_path = _build_runtime(tmp_path)
    _insert_all_passing(db_path)
    actor = {"id": 1, "username": "root"}
    res = mode.switch_mode(target_mode="production", actor=actor, confirm="GO_LIVE")
    assert res["ok"] is True, res
    assert res.get("mode", {}).get("current_mode") == "production"


# ── #9 production_requirements rollup matches what the UI reads ────────


def test_production_requirements_payload_shape_for_launch_check_ui(tmp_path):
    """The launch-check tab reads .required / .missing / .failed /
    .reports / .ok. Verify all five fields exist and are well-formed
    so the UI doesn't have to defensive-code around shape drift.
    """
    mode, _, db_path = _build_runtime(tmp_path)
    # Insert 11 passing + 1 failed + leave 1 missing.
    skipped = PRODUCTION_REQUIRED_REPORT_TYPES[0]
    bad_one = PRODUCTION_REQUIRED_REPORT_TYPES[1]
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES[1:]:
        if rt == bad_one:
            _insert_report(db_path, rt, critical=1)
        else:
            _insert_report(db_path, rt)
    requirements = mode.production_requirements()
    assert isinstance(requirements.get("required"), list)
    assert set(requirements["required"]) == set(PRODUCTION_REQUIRED_REPORT_TYPES)
    assert requirements.get("missing") == [skipped]
    assert bad_one in requirements.get("failed", [])
    assert isinstance(requirements.get("reports"), dict)
    assert requirements.get("ok") is False
    # Shape contracts the UI relies on.
    for rt in PRODUCTION_REQUIRED_REPORT_TYPES:
        assert rt in requirements["reports"]
