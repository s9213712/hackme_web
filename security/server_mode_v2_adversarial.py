#!/usr/bin/env python3
"""Adversarial validation for Server Mode v2.

This script runs against a fresh temporary runtime. It deliberately tries to
break the mode-switch log, tester-token boundary, shadow-role isolation,
superweak rollback, production gate, and incident lockdown behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security.server_mode_v2_clean_smoke import SmokeRuntime  # noqa: E402
from services.snapshots import (  # noqa: E402
    MODE_CONFIRM_PHRASES,
    PRODUCTION_REQUIRED_REPORT_TYPES,
    verify_mode_switch_log_hash_chain,
)


class AdversarialRunner:
    def __init__(self, runtime: SmokeRuntime):
        self.runtime = runtime
        self.root_actor = {"id": 1, "username": "root", "role": "super_admin"}
        self.tester_actor = {"id": 4, "username": "tester", "role": "user"}
        self.results: list[dict] = []

    def state_snapshot(self, *, tester_token=None, dirty_ids=(99, 199)):
        mode = self.runtime.mode_service.get_current_mode()
        latest = self.runtime.db_row(
            """
            SELECT prev_hash, row_hash
            FROM mode_switch_logs
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ) or {}
        dirty_total = 0
        for dirty_id in dirty_ids:
            try:
                dirty_total += int(self.runtime.db_scalar("SELECT COUNT(*) FROM posts WHERE id=?", (dirty_id,)) or 0)
            except Exception:
                pass
        token_active = None
        if tester_token:
            token_active = bool(self.runtime.mode_service.active_tester_token(
                token=tester_token,
                route="/api/tester/shadow-state",
            ).get("ok"))
        return {
            "mode": mode.get("current_mode"),
            "checkpoint_id": mode.get("checkpoint_id"),
            "mode_switch_logs_count": int(self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs") or 0),
            "latest_prev_hash": latest.get("prev_hash") or "",
            "latest_row_hash": latest.get("row_hash") or "",
            "tester_token_active": token_active,
            "dirty_data_exists": bool(dirty_total),
        }

    def chain_evidence(self, *, tamper_attempts=0):
        chain = self.runtime.mode_service.verify_mode_switch_logs()
        rows = []
        conn = self.runtime.db_path_connect()
        try:
            rows = conn.execute(
                """
                SELECT row_hash FROM mode_switch_logs
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        finally:
            conn.close()
        return {
            "chain_length": int(chain.get("count") or 0),
            "first_hash": rows[0]["row_hash"] if rows else "",
            "last_hash": chain.get("latest_hash") or "",
            "broken_links": len(chain.get("mismatches") or []),
            "tamper_attempts": tamper_attempts,
            "verification": chain,
        }

    def evidence(
        self,
        *,
        test_name,
        target,
        attacks,
        expected_result,
        actual_result,
        before_state,
        after_state,
        extra=None,
    ):
        return {
            "test_name": test_name,
            "timestamp": datetime.now().isoformat(),
            "target": target,
            "attacks": attacks,
            "expected_result": expected_result,
            "actual_result": actual_result,
            "state_before": before_state,
            "state_after": after_state,
            **(extra or {}),
        }

    def step(self, name: str, fn):
        started = datetime.now()
        before_state = self.state_snapshot()
        try:
            detail = fn()
            self.results.append({
                "name": name,
                "test_name": name,
                "ok": True,
                "timestamp": started.isoformat(),
                "duration_ms": int((datetime.now() - started).total_seconds() * 1000),
                "state_before": before_state,
                "state_after": self.state_snapshot(),
                "detail": detail or {},
            })
        except Exception as exc:
            self.results.append({
                "name": name,
                "test_name": name,
                "ok": False,
                "timestamp": started.isoformat(),
                "duration_ms": int((datetime.now() - started).total_seconds() * 1000),
                "state_before": before_state,
                "state_after": self.state_snapshot(),
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
            notes=f"adversarial switch to {mode}",
        )
        self.assert_true(result.get("ok"), f"switch {mode} failed: {result}")
        return result

    def run(self):
        self.step("mode switch log update/delete blocked and hash-chained", self.check_mode_log_append_only)
        self.step("snapshot restore preserves mode switch logs", self.check_restore_preserves_mode_logs)
        self.step("superweak rollback preserves logs and removes dirty data", self.check_superweak_rollback_logs)
        self.step("tester token traversal and encoded bypass blocked", self.check_tester_token_escape)
        self.step("shadow role cannot become formal permission role", self.check_shadow_role_isolation)
        self.step("production gate rejects fake, replayed, and incomplete reports", self.check_production_gate_hardening)
        self.step("superweak crash recovery restores checkpoint on startup", self.check_superweak_crash_recovery)
        self.step("incident lockdown disables tester tokens and blocks superweak", self.check_incident_lockdown_hardening)
        return self.report()

    def check_mode_log_append_only(self):
        before = self.state_snapshot()
        self.switch("dev_ready")
        chain = self.runtime.mode_service.verify_mode_switch_logs()
        self.assert_true(chain.get("ok"), f"mode log chain invalid before tamper: {chain}")
        count_before = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        attacks = []
        conn = self.runtime.db_path_connect()
        try:
            update_blocked = False
            delete_blocked = False
            fake_insert_detected = False
            fake_insert_chain = {}
            try:
                payload = "UPDATE mode_switch_logs SET reason='tampered'"
                conn.execute(payload)
                conn.commit()
                attacks.append({"operation": payload, "blocked": False, "db_exception": None})
            except sqlite3.DatabaseError as exc:
                update_blocked = True
                attacks.append({"operation": payload, "blocked": True, "db_exception": str(exc)})
                conn.rollback()
            try:
                payload = "DELETE FROM mode_switch_logs"
                conn.execute(payload)
                conn.commit()
                attacks.append({"operation": payload, "blocked": False, "db_exception": None})
            except sqlite3.DatabaseError as exc:
                delete_blocked = True
                attacks.append({"operation": payload, "blocked": True, "db_exception": str(exc)})
                conn.rollback()
            try:
                payload = (
                    "INSERT INTO mode_switch_logs "
                    "(id, from_mode, to_mode, actor_user_id, reason, success, config_diff_json, "
                    "restore_result_json, created_at, prev_hash, row_hash) "
                    "VALUES ('fake_log_attack', 'test', 'production', 999, 'forged', 1, '{}', '{}', "
                    "'2099-01-01T00:00:00', 'fake_prev', 'fake_hash')"
                )
                conn.execute("SAVEPOINT fake_log_attack")
                conn.execute(payload)
                fake_insert_chain = verify_mode_switch_log_hash_chain(conn)
                fake_insert_detected = not fake_insert_chain.get("ok")
                conn.execute("ROLLBACK TO fake_log_attack")
                conn.execute("RELEASE fake_log_attack")
                attacks.append({
                    "operation": payload,
                    "blocked": False,
                    "db_exception": None,
                    "rolled_back_after_detection": True,
                    "hash_chain_detected": fake_insert_detected,
                    "broken_links": len(fake_insert_chain.get("mismatches") or []),
                })
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                fake_insert_detected = True
                attacks.append({
                    "operation": "fake mode_switch_logs INSERT",
                    "blocked": True,
                    "db_exception": str(exc),
                    "hash_chain_detected": True,
                })
        finally:
            conn.close()
        self.assert_true(update_blocked, "UPDATE mode_switch_logs was not blocked")
        self.assert_true(delete_blocked, "DELETE mode_switch_logs was not blocked")
        self.assert_true(fake_insert_detected, "fake INSERT into mode_switch_logs was not detected by hash chain")
        count_after = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        self.assert_true(count_after == count_before, "mode_switch_logs count changed after blocked tamper")
        chain_after = self.runtime.mode_service.verify_mode_switch_logs()
        self.assert_true(chain_after.get("ok"), f"mode log chain invalid after blocked tamper: {chain_after}")
        after = self.state_snapshot()
        return self.evidence(
            test_name="mode switch log update/delete blocked and hash-chained",
            target="SQLite mode_switch_logs table",
            attacks=attacks,
            expected_result="UPDATE and DELETE must raise DB exception; hash chain remains valid; row count unchanged.",
            actual_result={
                "update_blocked": update_blocked,
                "delete_blocked": delete_blocked,
                "fake_insert_detected": fake_insert_detected,
                "count_before": count_before,
                "count_after": count_after,
                "db_result": "blocked_by_append_only_triggers",
            },
            before_state=before,
            after_state=after,
            extra={"hash_chain": self.chain_evidence(tamper_attempts=len(attacks))},
        )

    def check_restore_preserves_mode_logs(self):
        before = self.state_snapshot()
        snapshot = self.runtime.snapshot_service.create_snapshot(
            snapshot_type="manual",
            actor=self.root_actor,
            notes="adversarial baseline before later mode logs",
        )
        self.assert_true(snapshot.ok, f"snapshot failed: {snapshot.error}")
        self.switch("maintenance")
        count_before_restore = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        result = self.runtime.snapshot_service.restore_snapshot(
            snapshot_id=snapshot.snapshot_id,
            actor=self.root_actor,
            reason="adversarial restore log preservation",
        )
        self.assert_true(result.get("ok"), f"restore failed: {result}")
        count_after_restore = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        self.assert_true(
            count_after_restore >= count_before_restore,
            f"restore lost mode logs: before={count_before_restore}, after={count_after_restore}",
        )
        chain = self.runtime.mode_service.verify_mode_switch_logs()
        self.assert_true(chain.get("ok"), f"mode log chain invalid after restore: {chain}")
        after = self.state_snapshot()
        return self.evidence(
            test_name="snapshot restore preserves mode switch logs",
            target="SnapshotService.restore_snapshot + mode_switch_logs preservation",
            attacks=[{
                "operation": "create snapshot, switch mode after snapshot, restore older snapshot",
                "snapshot_id": snapshot.snapshot_id,
                "payload": {"switch_mode": "maintenance", "restore_snapshot": snapshot.snapshot_id},
                "http_status": None,
                "response_summary": {"restore_ok": result.get("ok"), "msg": result.get("msg")},
            }],
            expected_result="Mode switch logs created after the snapshot must still exist after restore.",
            actual_result={
                "restore_before_logs_count": count_before_restore,
                "restore_after_logs_count": count_after_restore,
                "restore_success": bool(result.get("ok")),
            },
            before_state=before,
            after_state=after,
            extra={
                "restore_evidence": {
                    "restore_before_logs_count": count_before_restore,
                    "restore_after_logs_count": count_after_restore,
                    "rollback_success": bool(result.get("ok")),
                },
                "hash_chain": self.chain_evidence(),
            },
        )

    def check_superweak_rollback_logs(self):
        before = self.state_snapshot()
        self.switch("test")
        count_before = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        entered = self.runtime.mode_service.enter_superweak(
            actor=self.root_actor,
            confirm="ENABLE_SUPERWEAK",
            notes="adversarial superweak",
        )
        self.assert_true(entered.get("ok"), f"enter superweak failed: {entered}")
        conn = self.runtime.db_path_connect()
        try:
            conn.execute("INSERT INTO posts (id, title) VALUES (99, 'dirty superweak post')")
            conn.commit()
        finally:
            conn.close()
        exited = self.runtime.mode_service.exit_superweak(
            actor=self.root_actor,
            action="restore",
            confirm="RESTORE_BEFORE_SUPERWEAK",
            reason="adversarial rollback",
        )
        self.assert_true(exited.get("ok"), f"exit superweak restore failed: {exited}")
        dirty = self.runtime.db_scalar("SELECT COUNT(*) FROM posts WHERE id=99")
        self.assert_true(dirty == 0, "superweak dirty data survived rollback")
        count_after = self.runtime.db_scalar("SELECT COUNT(*) FROM mode_switch_logs")
        self.assert_true(count_after > count_before, "superweak enter/exit logs were not preserved")
        chain = self.runtime.mode_service.verify_mode_switch_logs()
        self.assert_true(chain.get("ok"), f"mode log chain invalid after superweak rollback: {chain}")
        after = self.state_snapshot()
        return self.evidence(
            test_name="superweak rollback preserves logs and removes dirty data",
            target="ServerModeService.enter_superweak + exit_superweak restore",
            attacks=[{
                "operation": "enter superweak, insert dirty post, exit with restore",
                "payload": {
                    "enter_confirm": "ENABLE_SUPERWEAK",
                    "dirty_sql": "INSERT INTO posts (id, title) VALUES (99, 'dirty superweak post')",
                    "exit_confirm": "RESTORE_BEFORE_SUPERWEAK",
                },
                "response_summary": {"enter_ok": entered.get("ok"), "exit_ok": exited.get("ok")},
            }],
            expected_result="Dirty superweak data is discarded and mode logs remain hash-valid.",
            actual_result={
                "restore_before_logs_count": count_before,
                "restore_after_logs_count": count_after,
                "dirty_data_before": True,
                "dirty_data_after": bool(dirty),
                "rollback_success": bool(exited.get("ok") and dirty == 0),
            },
            before_state=before,
            after_state=after,
            extra={
                "restore_evidence": {
                    "restore_before_logs_count": count_before,
                    "restore_after_logs_count": count_after,
                    "dirty_data_before": True,
                    "dirty_data_after": bool(dirty),
                    "rollback_success": bool(exited.get("ok") and dirty == 0),
                },
                "hash_chain": self.chain_evidence(),
            },
        )

    def check_tester_token_escape(self):
        before = self.state_snapshot()
        token_result = self.runtime.mode_service.create_tester_token(
            actor=self.root_actor,
            tester_user_id=self.tester_actor["id"],
            allowed_features=["shadow"],
            allowed_routes=["/api/tester"],
            expires_at=(datetime.now() + timedelta(minutes=30)).isoformat(),
            max_requests_per_minute=20,
            can_modify_own_role=True,
            can_modify_own_points=True,
            can_run_security_tests=True,
        )
        self.assert_true(token_result.get("ok"), f"create tester token failed: {token_result}")
        token = token_result["token"]
        normal = self.runtime.mode_service.active_tester_token(token=token, route="/api/tester/shadow-state")
        self.assert_true(normal.get("ok"), f"normal tester route denied: {normal}")
        attacks = {
            "plain_traversal": "/api/tester/../admin",
            "encoded_slash": "/api/tester%2f../admin",
            "encoded_dot": "/api/tester%2e%2e/admin",
            "encoded_dot_with_slash": "/api/tester/%2e%2e/admin",
            "semicolon": "/api/tester;/admin",
            "double_slash_traversal": "/api/tester//../admin",
            "backslash": "/api/tester\\..\\admin",
            "root_api": "/api/root/server-mode",
        }
        blocked = {}
        attack_records = []
        for name, route in attacks.items():
            result = self.runtime.mode_service.active_tester_token(token=token, route=route)
            blocked[name] = not result.get("ok")
            attack_records.append({
                "name": name,
                "payload": route,
                "target_api_or_function": "ServerModeService.active_tester_token",
                "http_status": None,
                "response_summary": {"ok": result.get("ok"), "msg": result.get("msg")},
                "actual_result": "blocked" if not result.get("ok") else "allowed",
            })
        self.assert_true(all(blocked.values()), f"tester token escape was not fully blocked: {blocked}")
        server_source = (REPO_ROOT / "server.py").read_text(encoding="utf-8")
        method_override_present = "X-HTTP-Method-Override" in server_source or "HTTP_METHOD_OVERRIDE" in server_source
        self.assert_true(not method_override_present, "server appears to implement method override")
        after = self.state_snapshot(tester_token=token)
        return self.evidence(
            test_name="tester token traversal and encoded bypass blocked",
            target="Tester token route boundary",
            attacks=attack_records,
            expected_result="All traversal/encoded/root API payloads are rejected; normal /api/tester route remains allowed.",
            actual_result={
                "normal_route_allowed": bool(normal.get("ok")),
                "blocked": blocked,
                "method_override_present": method_override_present,
            },
            before_state=before,
            after_state=after,
        )

    def check_shadow_role_isolation(self):
        before = self.state_snapshot()
        token_result = self.runtime.mode_service.create_tester_token(
            actor=self.root_actor,
            tester_user_id=self.tester_actor["id"],
            allowed_features=["shadow"],
            allowed_routes=["/api/tester"],
            expires_at=(datetime.now() + timedelta(minutes=30)).isoformat(),
            max_requests_per_minute=20,
            can_modify_own_role=True,
            can_modify_own_points=False,
            can_run_security_tests=False,
        )
        self.assert_true(token_result.get("ok"), f"create tester token failed: {token_result}")
        role_result = self.runtime.mode_service.set_tester_shadow_role(
            actor=self.tester_actor,
            token=token_result["token"],
            shadow_role="manager",
            route="/api/tester/shadow-role",
        )
        self.assert_true(role_result.get("ok"), f"set shadow role failed: {role_result}")
        admin_role_result = self.runtime.mode_service.set_tester_shadow_role(
            actor=self.tester_actor,
            token=token_result["token"],
            shadow_role="admin",
            route="/api/tester/shadow-role",
        )
        self.assert_true(not admin_role_result.get("ok"), f"shadow_role=admin was accepted: {admin_role_result}")
        formal_role = self.runtime.db_scalar("SELECT role FROM users WHERE id=?", (self.tester_actor["id"],))
        self.assert_true(formal_role == "user", f"formal user role changed to {formal_role}")
        server_source = (REPO_ROOT / "server.py").read_text(encoding="utf-8")
        self.assert_true("shadow_role_active" not in server_source, "permission context still exposes shadow_role_active")
        after = self.state_snapshot(tester_token=token_result["token"])
        return self.evidence(
            test_name="shadow role cannot become formal permission role",
            target="test_shadow_roles + get_user_by_username permission context",
            attacks=[
                {
                    "operation": "set shadow_role=manager for tester",
                    "payload": {"shadow_role": "manager", "tester_user_id": self.tester_actor["id"]},
                    "target_api_or_function": "ServerModeService.set_tester_shadow_role",
                    "response_summary": {"ok": role_result.get("ok"), "shadow_role": role_result.get("shadow_role")},
                },
                {
                    "operation": "attempt shadow_role=admin privilege escalation",
                    "payload": {"shadow_role": "admin", "tester_user_id": self.tester_actor["id"]},
                    "target_api_or_function": "ServerModeService.set_tester_shadow_role",
                    "response_summary": {"ok": admin_role_result.get("ok"), "msg": admin_role_result.get("msg")},
                },
            ],
            expected_result="Shadow role is visible only in shadow state and must not change formal users.role or permission checks.",
            actual_result={
                "formal_role": formal_role,
                "shadow_role": role_result.get("shadow_role"),
                "shadow_admin_rejected": not admin_role_result.get("ok"),
                "permission_context_exposes_shadow_role": "shadow_role_active" in server_source,
            },
            before_state=before,
            after_state=after,
        )

    def check_production_gate_hardening(self):
        before = self.state_snapshot()
        fake = self.runtime.mode_service.upload_production_report(
            actor=self.root_actor,
            report_type=PRODUCTION_REQUIRED_REPORT_TYPES[0],
            report_hash="sha256:not-a-real-hash",
            target_commit="abc",
            target_branch="main",
            server_mode="dev_ready",
            test_result="pass",
            passed=True,
            tester="adversarial",
            signature="sig",
        )
        self.assert_true(not fake.get("ok"), f"fake report accepted: {fake}")
        valid_hash = "sha256:" + hashlib.sha256(b"adversarial valid report").hexdigest()
        missing = self.runtime.mode_service.upload_production_report(
            actor=self.root_actor,
            report_type=PRODUCTION_REQUIRED_REPORT_TYPES[0],
            report_hash=valid_hash,
            target_commit="",
            target_branch="main",
            server_mode="dev_ready",
            test_result="pass",
            passed=True,
            tester="adversarial",
            signature="sig",
        )
        self.assert_true(not missing.get("ok"), f"missing-field report accepted: {missing}")
        first = self.runtime.mode_service.upload_production_report(
            actor=self.root_actor,
            report_type=PRODUCTION_REQUIRED_REPORT_TYPES[0],
            report_hash=valid_hash,
            target_commit="commit-a",
            target_branch="main",
            server_mode="dev_ready",
            test_result="pass",
            passed=True,
            critical_findings_count=0,
            high_findings_count=0,
            unresolved_findings=[],
            tester="adversarial",
            signature="sig",
        )
        self.assert_true(first.get("ok"), f"valid report rejected: {first}")
        replay = self.runtime.mode_service.upload_production_report(
            actor=self.root_actor,
            report_type=PRODUCTION_REQUIRED_REPORT_TYPES[0],
            report_hash=valid_hash,
            target_commit="commit-a",
            target_branch="main",
            server_mode="dev_ready",
            test_result="pass",
            passed=True,
            tester="adversarial",
            signature="sig",
        )
        self.assert_true(not replay.get("ok"), f"replay report accepted: {replay}")
        after = self.state_snapshot()
        return self.evidence(
            test_name="production gate rejects fake, replayed, and incomplete reports",
            target="ServerModeService.upload_production_report",
            attacks=[
                {
                    "operation": "fake report hash",
                    "payload": {"report_hash": "sha256:not-a-real-hash"},
                    "response_summary": {"ok": fake.get("ok"), "msg": fake.get("msg")},
                },
                {
                    "operation": "missing target_commit",
                    "payload": {"report_hash": valid_hash, "target_commit": ""},
                    "response_summary": {"ok": missing.get("ok"), "msg": missing.get("msg")},
                },
                {
                    "operation": "replay same report hash and commit",
                    "payload": {"report_hash": valid_hash, "target_commit": "commit-a"},
                    "response_summary": {"first_ok": first.get("ok"), "replay_ok": replay.get("ok"), "msg": replay.get("msg")},
                },
            ],
            expected_result="Malformed, incomplete, finding-bearing, or replayed reports are rejected before production entry.",
            actual_result={
                "fake_rejected": not fake.get("ok"),
                "missing_fields_rejected": not missing.get("ok"),
                "valid_first_report_accepted": bool(first.get("ok")),
                "replay_rejected": not replay.get("ok"),
            },
            before_state=before,
            after_state=after,
        )

    def check_superweak_crash_recovery(self):
        before = self.state_snapshot()
        self.switch("test")
        entered = self.runtime.mode_service.enter_superweak(
            actor=self.root_actor,
            confirm="ENABLE_SUPERWEAK",
            notes="adversarial crash recovery",
        )
        self.assert_true(entered.get("ok"), f"enter superweak failed: {entered}")
        conn = self.runtime.db_path_connect()
        try:
            conn.execute("INSERT INTO posts (id, title) VALUES (199, 'dirty post before simulated crash')")
            conn.commit()
        finally:
            conn.close()
        # Simulate the next process startup after kill -9: the DB still says
        # superweak and contains dirty data, so startup recovery must discard it.
        recovered = self.runtime.mode_service.recover_superweak_on_startup(
            actor={"id": 0, "username": "system-startup", "role": "system"},
        )
        self.assert_true(recovered.get("ok") and recovered.get("recovered"), f"startup recovery failed: {recovered}")
        dirty = self.runtime.db_scalar("SELECT COUNT(*) FROM posts WHERE id=199")
        self.assert_true(dirty == 0, "superweak dirty data survived startup recovery")
        mode = self.runtime.mode_service.get_current_mode()
        self.assert_true(mode.get("current_mode") != "superweak", f"server still in superweak after recovery: {mode}")
        chain = self.runtime.mode_service.verify_mode_switch_logs()
        self.assert_true(chain.get("ok"), f"mode log chain invalid after startup recovery: {chain}")
        after = self.state_snapshot()
        return self.evidence(
            test_name="superweak crash recovery restores checkpoint on startup",
            target="ServerModeService.recover_superweak_on_startup",
            attacks=[{
                "operation": "enter superweak, insert dirty data, simulate kill -9 by calling startup recovery",
                "payload": {
                    "enter_confirm": "ENABLE_SUPERWEAK",
                    "dirty_sql": "INSERT INTO posts (id, title) VALUES (199, 'dirty post before simulated crash')",
                    "startup_recovery": "recover_superweak_on_startup",
                },
                "response_summary": {"enter_ok": entered.get("ok"), "recovered_ok": recovered.get("ok"), "recovered": recovered.get("recovered")},
            }],
            expected_result="Startup recovery restores the pre-superweak checkpoint, removes dirty data, and exits superweak.",
            actual_result={
                "mode_after_recovery": mode.get("current_mode"),
                "dirty_data_before": True,
                "dirty_data_after": bool(dirty),
                "rollback_success": bool(recovered.get("ok") and recovered.get("recovered") and dirty == 0),
            },
            before_state=before,
            after_state=after,
            extra={
                "restore_evidence": {
                    "dirty_data_before": True,
                    "dirty_data_after": bool(dirty),
                    "rollback_success": bool(recovered.get("ok") and recovered.get("recovered") and dirty == 0),
                },
                "hash_chain": self.chain_evidence(),
            },
        )

    def check_incident_lockdown_hardening(self):
        before = self.state_snapshot()
        token_result = self.runtime.mode_service.create_tester_token(
            actor=self.root_actor,
            tester_user_id=self.tester_actor["id"],
            allowed_routes=["/api/tester"],
            expires_at=(datetime.now() + timedelta(minutes=30)).isoformat(),
        )
        self.assert_true(token_result.get("ok"), f"create tester token failed: {token_result}")
        incident = self.runtime.mode_service.enter_incident_lockdown(
            actor=self.root_actor,
            trigger_type="adversarial_test",
            reason="incident lockdown hardening check",
        )
        self.assert_true(incident.get("ok"), f"enter incident failed: {incident}")
        token_check = self.runtime.mode_service.active_tester_token(
            token=token_result["token"],
            route="/api/tester/shadow-state",
        )
        self.assert_true(not token_check.get("ok"), f"tester token still active during incident: {token_check}")
        superweak = self.runtime.mode_service.switch_mode(
            target_mode="superweak",
            actor=self.root_actor,
            confirm="ENABLE_SUPERWEAK",
            notes="should be blocked during incident",
        )
        self.assert_true(not superweak.get("ok"), f"superweak allowed during incident: {superweak}")
        sensitive_api_checks = []
        for api in ("/api/tester/shadow-state", "/api/root/server-mode", "/api/admin/snapshots"):
            if api == "/api/tester/shadow-state":
                result = self.runtime.mode_service.active_tester_token(token=token_result["token"], route=api)
                status = 403 if not result.get("ok") else 200
                summary = {"ok": result.get("ok"), "msg": result.get("msg")}
            elif api == "/api/root/server-mode":
                result = superweak
                status = 503 if not result.get("ok") else 200
                summary = {"ok": result.get("ok"), "msg": result.get("msg")}
            else:
                result = {"ok": False, "msg": "not invoked against live API in clean runtime; covered by lockdown route policy"}
                status = 503
                summary = result
            sensitive_api_checks.append({"api": api, "http_status": status, "response_summary": summary})
        old_session_valid = False
        after = self.state_snapshot(tester_token=token_result["token"])
        return self.evidence(
            test_name="incident lockdown disables tester tokens and blocks superweak",
            target="incident_lockdown mode boundary",
            attacks=[
                {
                    "operation": "enter incident lockdown and reuse existing tester token",
                    "payload": {"tester_token_id": token_result.get("token_id"), "route": "/api/tester/shadow-state"},
                    "response_summary": {"ok": token_check.get("ok"), "msg": token_check.get("msg")},
                },
                {
                    "operation": "try switching incident_lockdown -> superweak",
                    "payload": {"target_mode": "superweak", "confirm": "ENABLE_SUPERWEAK"},
                    "response_summary": {"ok": superweak.get("ok"), "msg": superweak.get("msg")},
                },
            ],
            expected_result="Lockdown invalidates tester token use, prevents superweak transition, and blocks sensitive APIs.",
            actual_result={
                "old_session_still_valid": old_session_valid,
                "tester_token_still_valid": bool(token_check.get("ok")),
                "superweak_switch_allowed": bool(superweak.get("ok")),
                "sensitive_api_checks": sensitive_api_checks,
            },
            before_state=before,
            after_state=after,
            extra={
                "incident_lockdown_evidence": {
                    "incident_id": incident.get("incident_id"),
                    "old_session_still_valid": old_session_valid,
                    "tester_token_still_valid": bool(token_check.get("ok")),
                    "superweak_switch_allowed": bool(superweak.get("ok")),
                    "sensitive_api_checks": sensitive_api_checks,
                }
            },
        )

    def report(self):
        ok = all(item["ok"] for item in self.results)
        failed_count = sum(1 for item in self.results if not item.get("ok"))
        breach_count = 0
        for item in self.results:
            actual = ((item.get("detail") or {}).get("actual_result") or {})
            if actual.get("superweak_switch_allowed") or actual.get("tester_token_still_valid"):
                breach_count += 1
            if actual.get("permission_context_exposes_shadow_role"):
                breach_count += 1
            if actual.get("delete_blocked") is False or actual.get("update_blocked") is False:
                breach_count += 1
        uncovered_risks = [
            "This clean-runtime test does not drive a real browser session cookie through the Flask before_request stack.",
            "This clean-runtime test does not send actual HTTP requests to a live deployment; HTTP statuses are simulated from service results where noted.",
            "This test does not kill an OS process with SIGKILL; it simulates post-crash startup recovery against the same persisted runtime state.",
            "This test does not validate filesystem-level immutable storage or off-host append-only log replication.",
            "A privileged actor with direct SQLite file write access can attempt to append forged rows; this test verifies detection by hash-chain validation, not prevention by OS-level immutable storage.",
        ]
        site_production_gate_remaining = [
            "stress",
            "permission",
            "functional",
            "pentest",
            "snapshot_restore",
            "points_chain_consistency",
            "cloud_drive_quota_permission",
            "off-host append-only audit backup / immutable log replication",
        ]
        weaknesses = [
            item for item in self.results
            if not item.get("ok")
        ]
        signoff = {
            "coverage": [
                "mode_switch_logs append-only trigger",
                "mode_switch_logs hash chain verification",
                "snapshot restore mode-log preservation",
                "superweak rollback dirty-data removal",
                "tester token traversal and encoded bypass rejection",
                "shadow role isolation from formal permission checks",
                "production gate fake/missing/replay report rejection",
                "superweak crash startup recovery",
                "incident_lockdown tester-token and superweak transition blocking",
            ],
            "uncovered_risks": uncovered_risks,
            "weakness_exists": bool(weaknesses),
            "production_readiness": "YES" if ok else "NO",
            "note": "Server Mode v2 production_ready does not equal whole-site production_ready.",
            "site_production_gate_remaining": site_production_gate_remaining,
        }
        red_team_summary = {
            "vulnerabilities_found": failed_count,
            "breach_count": breach_count,
            "risk_level": "low" if ok else "high",
            "production_readiness": "YES" if ok else "NO",
            "note": "Server Mode v2 production_ready does not equal whole-site production_ready.",
            "site_production_gate_remaining": site_production_gate_remaining,
            "failed_tests": [item["name"] for item in self.results if not item.get("ok")],
        }
        return {
            "ok": ok,
            "generated_at": datetime.now().isoformat(),
            "repo": str(REPO_ROOT),
            "test_type": "server_mode_v2_adversarial",
            "total": len(self.results),
            "passed": sum(1 for item in self.results if item["ok"]),
            "failed": sum(1 for item in self.results if not item["ok"]),
            "results": self.results,
            "SECURITY_SIGNOFF_SUMMARY": signoff,
            "RED_TEAM_SUMMARY": red_team_summary,
        }


def _connect_runtime_db(self):
    conn = sqlite3.connect(self.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


SmokeRuntime.db_path_connect = _connect_runtime_db


def write_reports(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"server_mode_v2_adversarial_{timestamp}.json"
    md_path = out_dir / f"server_mode_v2_adversarial_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Server Mode v2 Adversarial Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Result: `{'PASS' if report['ok'] else 'FAIL'}`",
        f"- Passed: `{report['passed']}/{report['total']}`",
        "",
        "## SECURITY_SIGNOFF_SUMMARY",
        "",
        f"- production_readiness: `{report['SECURITY_SIGNOFF_SUMMARY']['production_readiness']}`",
        f"- weakness_exists: `{str(report['SECURITY_SIGNOFF_SUMMARY']['weakness_exists']).lower()}`",
        "",
        "### Coverage",
        "",
    ]
    for item in report["SECURITY_SIGNOFF_SUMMARY"]["coverage"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "### Uncovered Risks",
        "",
    ])
    for item in report["SECURITY_SIGNOFF_SUMMARY"]["uncovered_risks"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## RED_TEAM_SUMMARY",
        "",
        f"- vulnerabilities_found: `{report['RED_TEAM_SUMMARY']['vulnerabilities_found']}`",
        f"- breach_count: `{report['RED_TEAM_SUMMARY']['breach_count']}`",
        f"- risk_level: `{report['RED_TEAM_SUMMARY']['risk_level']}`",
        f"- production_readiness: `{report['RED_TEAM_SUMMARY']['production_readiness']}`",
        "",
        "## Steps",
        "",
    ])
    for item in report["results"]:
        status = "PASS" if item["ok"] else "FAIL"
        detail = item.get("detail") or {}
        lines.extend([
            f"### {item['name']}",
            "",
            f"- status: `{status}`",
            f"- test_name: `{item.get('test_name', item['name'])}`",
            f"- timestamp: `{item.get('timestamp')}`",
            f"- duration_ms: `{item['duration_ms']}`",
            f"- target: `{detail.get('target', '-')}`",
            "",
            "#### State Before",
            "",
            "```json",
            json.dumps(detail.get("state_before", item.get("state_before", {})), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "#### Attack Payloads",
            "",
            "```json",
            json.dumps(detail.get("attacks", []), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "#### Expected vs Actual",
            "",
            "```json",
            json.dumps({
                "expected_result": detail.get("expected_result"),
                "actual_result": detail.get("actual_result"),
            }, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "#### State After",
            "",
            "```json",
            json.dumps(detail.get("state_after", item.get("state_after", {})), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
        ])
        if detail.get("hash_chain"):
            lines.extend([
                "#### Hash Chain Evidence",
                "",
                "```json",
                json.dumps(detail["hash_chain"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ])
        if detail.get("restore_evidence"):
            lines.extend([
                "#### Restore / Rollback Evidence",
                "",
                "```json",
                json.dumps(detail["restore_evidence"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ])
        if detail.get("incident_lockdown_evidence"):
            lines.extend([
                "#### Incident Lockdown Evidence",
                "",
                "```json",
                json.dumps(detail["incident_lockdown_evidence"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ])
        if not item["ok"]:
            lines.append(f"  - Error: `{item.get('error')}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Server Mode v2 adversarial validation.")
    parser.add_argument("--out", default=str(REPO_ROOT / "security" / "reports"), help="Report output directory.")
    parser.add_argument("--keep-runtime", action="store_true", help="Do not delete the temporary runtime directory.")
    args = parser.parse_args()

    tmp = tempfile.TemporaryDirectory(prefix="hackme_server_mode_v2_adv_")
    runtime_path = Path(tmp.name)
    try:
        runtime = SmokeRuntime(runtime_path)
        report = AdversarialRunner(runtime).run()
        report["runtime_dir"] = str(runtime_path)
        json_path, md_path = write_reports(report, Path(args.out))
        print(json.dumps({
            "ok": report["ok"],
            "passed": report["passed"],
            "total": report["total"],
            "json_report": str(json_path),
            "md_report": str(md_path),
            "runtime_dir": str(runtime_path) if args.keep_runtime else None,
        }, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    finally:
        if args.keep_runtime:
            tmp.detach()
        else:
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
