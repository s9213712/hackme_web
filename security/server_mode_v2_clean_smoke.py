#!/usr/bin/env python3
"""Clean-environment smoke test for Server Mode v2.

This test intentionally avoids the developer's live database. It creates a
fresh temporary runtime with a new DB/storage tree, then exercises all canonical
Server Mode v2 transitions and the core isolation guarantees.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.snapshots import (  # noqa: E402
    MODE_CONFIRM_PHRASES,
    PRODUCTION_REQUIRED_REPORT_TYPES,
    ServerModeService,
    SnapshotService,
    ensure_snapshot_schema,
)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_clean_db(db_path: Path) -> None:
    conn = connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            member_level TEXT NOT NULL DEFAULT 'normal',
            base_level TEXT NOT NULL DEFAULT 'normal',
            effective_level TEXT NOT NULL DEFAULT 'normal',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            is_default_password INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
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
        CREATE TABLE storage_files (
            id INTEGER PRIMARY KEY,
            owner_user_id INTEGER,
            filename TEXT,
            folder_id INTEGER,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        );
        INSERT INTO users (id, username, role, status, member_level, base_level, effective_level)
        VALUES
          (1, 'root', 'super_admin', 'active', 'normal', 'normal', 'normal'),
          (2, 'admin', 'manager', 'active', 'normal', 'normal', 'normal'),
          (3, 'test', 'user', 'active', 'normal', 'normal', 'normal'),
          (4, 'tester', 'user', 'active', 'normal', 'normal', 'normal');
        INSERT INTO posts (id, title) VALUES (1, 'baseline');
        INSERT INTO system_settings (key, value, value_type, updated_at, updated_by)
        VALUES
          ('maintenance_mode', 'false', 'bool', '2026-01-01T00:00:00', 'clean-smoke'),
          ('audit_chain_enabled', 'true', 'bool', '2026-01-01T00:00:00', 'clean-smoke'),
          ('integrity_guard_enabled', 'true', 'bool', '2026-01-01T00:00:00', 'clean-smoke'),
          ('feature_server_modes_enabled', 'true', 'bool', '2026-01-01T00:00:00', 'clean-smoke');
        """
    )
    ensure_snapshot_schema(conn)
    conn.commit()
    conn.close()


def setting_value_type(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    return "str"


def serialize_setting(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class SmokeRuntime:
    def __init__(self, root: Path):
        os.environ.setdefault("SERVER_MODE_LOG_HMAC_KEY", "clean-smoke-server-mode-log-hmac-key")
        os.environ.setdefault("SERVER_MODE_TOKEN_HMAC_KEY", "clean-smoke-server-mode-token-hmac-key")
        os.environ.setdefault("SERVER_MODE_LOG_HMAC_KEY_VERSION", "clean-smoke-v1")
        os.environ.setdefault("SERVER_MODE_TOKEN_HMAC_KEY_VERSION", "clean-smoke-v1")
        self.root = root
        self.db_path = root / "database.db"
        self.storage = root / "storage"
        self.uploads = root / "uploads"
        self.config = root / "config.json"
        self.integrity_manifest = root / "integrity_manifest.json"
        self.audit_events: list[dict] = []
        self.storage.mkdir()
        self.uploads.mkdir()
        self.config.write_text(json.dumps({"clean": True}, sort_keys=True), encoding="utf-8")
        self.integrity_manifest.write_text(json.dumps({"files": []}, sort_keys=True), encoding="utf-8")
        init_clean_db(self.db_path)

        def get_db():
            return connect(self.db_path)

        def audit(event, ip="-", **kwargs):
            self.audit_events.append({"event": event, "ip": ip, **kwargs})

        def save_settings(settings: dict):
            conn = connect(self.db_path)
            try:
                now = datetime.now().isoformat()
                for key, value in settings.items():
                    conn.execute(
                        """
                        INSERT INTO system_settings (key, value, value_type, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, 'server-mode-clean-smoke')
                        ON CONFLICT(key) DO UPDATE SET
                          value=excluded.value,
                          value_type=excluded.value_type,
                          updated_at=excluded.updated_at,
                          updated_by=excluded.updated_by
                        """,
                        (key, serialize_setting(value), setting_value_type(value), now),
                    )
                conn.commit()
                return dict(settings)
            finally:
                conn.close()

        class IntegrityGuard:
            manifest_path = str(self.integrity_manifest)

            @staticmethod
            def can_enter_preprod():
                return True, 0

        self.snapshot_service = SnapshotService(
            get_db=get_db,
            db_path=self.db_path,
            base_dir=root,
            storage_root=self.storage,
            audit=audit,
            # Do not snapshot the snapshot storage root itself; Cloud Drive
            # metadata is verified through DB hashes in this smoke.
            file_roots=[self.uploads],
            config_files=[self.config, self.integrity_manifest],
        )
        self.mode_service = ServerModeService(
            snapshot_service=self.snapshot_service,
            get_db=get_db,
            audit=audit,
            save_settings=save_settings,
            integrity_guard=IntegrityGuard(),
        )

    def db_scalar(self, sql: str, params=()):
        conn = connect(self.db_path)
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def db_row(self, sql: str, params=()):
        conn = connect(self.db_path)
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


class SmokeRunner:
    def __init__(self, runtime: SmokeRuntime):
        self.runtime = runtime
        self.root_actor = {"id": 1, "username": "root", "role": "super_admin"}
        self.tester_actor = {"id": 4, "username": "tester", "role": "user"}
        self.results: list[dict] = []

    def step(self, name: str, fn):
        started = datetime.now()
        try:
            detail = fn()
            self.results.append({
                "name": name,
                "ok": True,
                "duration_ms": int((datetime.now() - started).total_seconds() * 1000),
                "detail": detail or {},
            })
        except Exception as exc:  # keep collecting a useful report
            self.results.append({
                "name": name,
                "ok": False,
                "duration_ms": int((datetime.now() - started).total_seconds() * 1000),
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })

    def assert_true(self, condition: bool, message: str):
        if not condition:
            raise AssertionError(message)

    def switch(self, mode: str):
        result = self.runtime.mode_service.switch_mode(
            target_mode=mode,
            actor=self.root_actor,
            confirm=MODE_CONFIRM_PHRASES[mode],
            notes=f"clean smoke switch to {mode}",
        )
        self.assert_true(result.get("ok"), f"switch {mode} failed: {result}")
        current = result.get("mode") or {}
        self.assert_true(current.get("current_mode") == mode, f"expected {mode}, got {current}")
        self.assert_true(bool(current.get("checkpoint_id")), f"{mode} did not record checkpoint_id")
        log = self.runtime.db_row("SELECT * FROM mode_switch_logs ORDER BY created_at DESC LIMIT 1")
        self.assert_true(log and log["to_mode"] == mode and int(log["success"]) == 1, f"{mode} did not write successful mode log")
        return {"mode": current, "checkpoint": result.get("checkpoint")}

    def run(self):
        self.step("initial mode is clean test", self.check_initial_mode)
        self.step("production gate rejects missing reports", self.check_production_gate_missing)
        for mode in ("dev_ready", "maintenance", "test", "internal_test"):
            self.step(f"switch to {mode}", lambda mode=mode: self.switch(mode))
        self.step("tester token shadow layer isolation", self.check_tester_shadow)
        self.step("manual incident lockdown and superweak rejection", self.check_incident_lockdown)
        self.step("leave incident by switching to dev_ready", lambda: self.switch("dev_ready"))
        self.step("superweak is disposable and restores checkpoint", self.check_superweak_restore)
        self.step("production gate accepts complete passing reports", self.check_production_gate_pass)
        self.step("switch to production", lambda: self.switch("production"))
        self.step("mode switch logs are query-only by API design", self.check_no_delete_api_marker)
        return self.report()

    def check_initial_mode(self):
        mode = self.runtime.mode_service.get_current_mode()
        self.assert_true(mode["current_mode"] == "test", f"unexpected initial mode {mode}")
        return {"mode": mode}

    def check_production_gate_missing(self):
        result = self.runtime.mode_service.switch_mode(
            target_mode="production",
            actor=self.root_actor,
            confirm=MODE_CONFIRM_PHRASES["production"],
            notes="should fail missing reports",
        )
        self.assert_true(not result.get("ok"), f"production unexpectedly passed: {result}")
        self.assert_true("requirements" in result, f"missing requirements detail: {result}")
        return {"missing": result["requirements"].get("missing")}

    def check_tester_shadow(self):
        token = self.runtime.mode_service.create_tester_token(
            actor=self.root_actor,
            tester_user_id=4,
            allowed_routes=["/api/tester"],
            expires_at="2099-01-01T00:00:00",
            max_requests_per_minute=60,
            can_modify_own_role=True,
            can_modify_own_points=True,
        )
        self.assert_true(token.get("ok"), f"create tester token failed: {token}")
        denied = self.runtime.mode_service.active_tester_token(
            token=token["token"],
            route="/api/root/server-mode",
        )
        self.assert_true(not denied.get("ok"), "tester token was allowed to access root API")
        role = self.runtime.mode_service.set_tester_shadow_role(
            actor=self.tester_actor,
            token=token["token"],
            shadow_role="manager",
            route="/api/tester/shadow-role",
        )
        wallet = self.runtime.mode_service.adjust_tester_shadow_wallet(
            actor=self.tester_actor,
            token=token["token"],
            delta_points=250,
            reason="clean smoke",
            route="/api/tester/shadow-wallet",
        )
        state = self.runtime.mode_service.tester_shadow_state(
            actor=self.tester_actor,
            token=token["token"],
            route="/api/tester/shadow-state",
        )
        formal_role = self.runtime.db_scalar("SELECT role FROM users WHERE id=4")
        self.assert_true(role.get("ok"), f"shadow role failed: {role}")
        self.assert_true(wallet.get("ok"), f"shadow wallet failed: {wallet}")
        self.assert_true(state.get("shadow_wallet", {}).get("balance_points") == 250, f"bad shadow state: {state}")
        self.assert_true(formal_role == "user", f"formal users.role mutated to {formal_role}")
        return {"token_id": token["token_id"], "shadow_balance": state["shadow_wallet"]["balance_points"], "formal_role": formal_role}

    def check_incident_lockdown(self):
        incident = self.runtime.mode_service.enter_incident_lockdown(
            actor=self.root_actor,
            trigger_type="clean_smoke_manual",
            reason="clean smoke incident",
            verification={"ok": True},
        )
        self.assert_true(incident.get("ok"), f"manual incident failed: {incident}")
        rejected = self.runtime.mode_service.switch_mode(
            target_mode="superweak",
            actor=self.root_actor,
            confirm=MODE_CONFIRM_PHRASES["superweak"],
            notes="should be blocked from incident",
        )
        self.assert_true(not rejected.get("ok"), f"incident allowed superweak: {rejected}")
        return {"incident_id": incident.get("incident_id"), "superweak_rejected": rejected.get("msg")}

    def check_superweak_restore(self):
        entered = self.runtime.mode_service.enter_superweak(
            actor=self.root_actor,
            confirm=MODE_CONFIRM_PHRASES["superweak"],
            notes="clean smoke superweak",
        )
        self.assert_true(entered.get("ok"), f"enter superweak failed: {entered}")
        conn = connect(self.runtime.db_path)
        try:
            conn.execute("INSERT INTO posts (id, title) VALUES (99, 'dirty superweak row')")
            conn.execute("INSERT INTO storage_files (id, owner_user_id, filename, size_bytes, created_at) VALUES (99, 1, 'dirty.txt', 1, ?)", (datetime.now().isoformat(),))
            conn.commit()
        finally:
            conn.close()
        exited = self.runtime.mode_service.exit_superweak(
            actor=self.root_actor,
            action="restore",
            confirm="RESTORE_BEFORE_SUPERWEAK",
            reason="clean smoke done",
        )
        self.assert_true(exited.get("ok"), f"exit superweak restore failed: {exited}")
        dirty_post = self.runtime.db_scalar("SELECT COUNT(*) FROM posts WHERE id=99")
        dirty_file = self.runtime.db_scalar("SELECT COUNT(*) FROM storage_files WHERE id=99")
        self.assert_true(dirty_post == 0, "dirty post survived superweak restore")
        self.assert_true(dirty_file == 0, "dirty storage metadata survived superweak restore")
        return {"mode": exited.get("mode"), "validation": exited.get("validation")}

    def check_production_gate_pass(self):
        for report_type in PRODUCTION_REQUIRED_REPORT_TYPES:
            report_hash = "sha256:" + hashlib.sha256(f"{report_type}:clean-smoke".encode("utf-8")).hexdigest()
            result = self.runtime.mode_service.upload_production_report(
                actor=self.root_actor,
                report_type=report_type,
                report_hash=report_hash,
                target_commit="clean-smoke",
                target_branch="clean-env",
                server_mode="dev_ready",
                test_result="pass",
                passed=True,
                critical_findings_count=0,
                high_findings_count=0,
                unresolved_findings=[],
                tester="server_mode_v2_clean_smoke",
                signature=f"smoke-signature:{report_type}",
            )
            self.assert_true(result.get("ok"), f"upload production report failed: {report_type} {result}")
        requirements = self.runtime.mode_service.production_requirements()
        self.assert_true(requirements.get("ok"), f"production requirements not satisfied: {requirements}")
        return {"required": requirements.get("required")}

    def check_no_delete_api_marker(self):
        # This script validates the backend contract: logs are readable through
        # service/API but no delete method is exposed on ServerModeService.
        self.assert_true(not hasattr(self.runtime.mode_service, "delete_mode_switch_log"), "delete mode switch log API exists")
        count = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        self.assert_true(count and count > 0, "mode switch logs were not written")
        return {"mode_switch_log_count": count}

    def report(self):
        ok = all(item["ok"] for item in self.results)
        return {
            "ok": ok,
            "generated_at": datetime.now().isoformat(),
            "repo": str(REPO_ROOT),
            "test_type": "server_mode_v2_clean_environment_smoke",
            "total": len(self.results),
            "passed": sum(1 for item in self.results if item["ok"]),
            "failed": sum(1 for item in self.results if not item["ok"]),
            "results": self.results,
        }


def write_reports(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"server_mode_v2_clean_smoke_{timestamp}.json"
    md_path = out_dir / f"server_mode_v2_clean_smoke_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Server Mode v2 Clean Smoke Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Result: `{'PASS' if report['ok'] else 'FAIL'}`",
        f"- Passed: `{report['passed']}/{report['total']}`",
        "",
        "## Steps",
        "",
    ]
    for item in report["results"]:
        status = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- `{status}` {item['name']} ({item['duration_ms']} ms)")
        if not item["ok"]:
            lines.append(f"  - Error: `{item.get('error')}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Server Mode v2 clean-environment smoke test.")
    parser.add_argument("--out", default=str(REPO_ROOT / "security" / "reports"), help="Report output directory.")
    parser.add_argument("--keep-runtime", action="store_true", help="Do not delete the temporary runtime directory.")
    args = parser.parse_args()

    if args.keep_runtime:
        root = Path(tempfile.mkdtemp(prefix="hackme_server_mode_v2_"))
        runtime = SmokeRuntime(root)
        report = SmokeRunner(runtime).run()
        report["runtime_dir"] = str(root)
    else:
        with tempfile.TemporaryDirectory(prefix="hackme_server_mode_v2_") as tmp:
            runtime = SmokeRuntime(Path(tmp))
            report = SmokeRunner(runtime).run()
            report["runtime_dir"] = "<temporary directory removed>"

    json_path, md_path = write_reports(report, Path(args.out))
    print(json.dumps({
        "ok": report["ok"],
        "passed": report["passed"],
        "failed": report["failed"],
        "json_report": str(json_path),
        "md_report": str(md_path),
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
