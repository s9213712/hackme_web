import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from flask import request, send_file

from services.access_controls import (
    access_control_settings_payload,
    generate_internal_test_token,
    generate_maintenance_bypass_token,
    hash_internal_test_token,
    hash_maintenance_bypass_token,
    maintenance_bypass_expires_at,
)
from services.bootstrap import CURRENT_SCHEMA_VERSION, get_schema_version
from services.integrity_guard import CONFIRM_APPROVE
from services.member_levels import (
    DEFAULT_MEMBER_LEVEL_RULES,
    ensure_member_level_rules_schema,
    serialize_member_level_rule,
    update_member_level_rule,
)
from services.server_bind import (
    server_bind_settings_payload,
    server_ssl_settings_payload,
    validate_listen_host,
    validate_listen_port,
)
from services.captcha import normalize_captcha_mode
from services.storage_paths import validate_storage_root
from services.storage_capacity_audit import audit_storage_capacity
from services.upload_security import (
    ensure_upload_security_schema,
    get_cloud_drive_security_policy,
    update_cloud_drive_security_policy,
)
from services.web_terminal_qemu import (
    QemuWebTerminalManager,
    bridge_ssh_to_websocket,
    public_config,
)


SECURITY_TEST_JOBS = {}
SECURITY_TEST_JOBS_LOCK = threading.Lock()


COMFYUI_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def validate_comfyui_api_host(value):
    host = str(value or "").strip().strip("[]")
    if not host:
        return None
    if len(host) > 253:
        return None
    forbidden = ("://", "/", "\\", "@", "?", "#", "%", " ")
    if any(part in host for part in forbidden):
        return None
    if not COMFYUI_HOST_RE.match(host):
        return None
    return host


def restart_launcher_code():
    return r"""
import os
import socket
import subprocess
import sys
import time

python_exe, script_path, base_dir, parent_pid, host, port = sys.argv[1:7]
parent_pid = int(parent_pid)
port = int(port)

def parent_alive():
    try:
        os.kill(parent_pid, 0)
        return True
    except OSError:
        return False

def port_is_free():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex((host, port)) != 0
    except Exception:
        return True

deadline = time.time() + 30
while time.time() < deadline and (parent_alive() or not port_is_free()):
    time.sleep(0.25)

os.chdir(base_dir)
subprocess.Popen([python_exe, script_path], cwd=base_dir, close_fds=True, start_new_session=True)
"""


def register_system_admin_routes(app, deps):
    ANCHOR_DIR = deps["ANCHOR_DIR"]
    BASE_DIR = deps["BASE_DIR"]
    CHAT_DIR = deps["CHAT_DIR"]
    DB_PATH = deps["DB_PATH"]
    LOG_DIR = deps["LOG_DIR"]
    SERVER_LOG_PATH = deps["SERVER_LOG_PATH"]
    STORAGE_DIR = deps.get("STORAGE_DIR")
    CURRENT_SERVER_BIND_STATE = deps.get("CURRENT_SERVER_BIND_STATE") or {}
    CERT_FILE = deps.get("CERT_FILE") or os.path.join(BASE_DIR, "cert.pem")
    KEY_FILE = deps.get("KEY_FILE") or os.path.join(BASE_DIR, "key.pem")
    activate_emergency_lockdown = deps["activate_emergency_lockdown"]
    audit = deps["audit"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_ua = deps.get("get_ua", lambda: "-")
    get_feature_settings = deps["get_feature_settings"]
    get_server_output = deps.get("get_server_output", lambda limit=200: {"lines": [], "max_lines": 0})
    get_system_settings = deps["get_system_settings"]
    is_audit_chain_enabled = deps["is_audit_chain_enabled"]
    json_resp = deps["json_resp"]
    repair_audit_chain = deps["repair_audit_chain"]
    repair_violation_chains = deps["repair_violation_chains"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps["role_rank"]
    points_service = deps.get("points_service")
    save_feature_settings = deps["save_feature_settings"]
    save_settings = deps["save_settings"]
    server_mode_service = deps.get("server_mode_service")
    snapshot_service = deps.get("snapshot_service")
    integrity_guard = deps.get("integrity_guard")
    verify_audit_integrity = deps["verify_audit_integrity"]
    web_terminal_manager = deps.get("web_terminal_manager") or QemuWebTerminalManager(
        base_dir=BASE_DIR,
        storage_dir=STORAGE_DIR,
        get_settings=get_system_settings,
        audit=audit,
    )

    try:
        from flask_sock import Sock
        sock = Sock(app)
    except Exception:
        sock = None

    def default_schedule_server_restart(*, reason, delay_seconds=1.25):
        if app.testing:
            return {"mode": "testing", "pid": os.getpid(), "reason": reason}

        script_path = os.path.join(BASE_DIR, "server.py")
        python_exe = sys.executable or "python3"
        host = CURRENT_SERVER_BIND_STATE.get("host") or "127.0.0.1"
        if host in {"0.0.0.0", "::", ""}:
            host = "127.0.0.1"
        port = int(CURRENT_SERVER_BIND_STATE.get("port") or 5000)

        def restart_delayed():
            time.sleep(delay_seconds)
            subprocess.Popen(
                [python_exe, "-c", restart_launcher_code(), python_exe, script_path, BASE_DIR, str(os.getpid()), host, str(port)],
                cwd=BASE_DIR,
                close_fds=True,
                start_new_session=True,
            )
            os._exit(0)

        threading.Thread(target=restart_delayed, name="server-restart", daemon=True).start()
        return {
            "mode": "detached-restart",
            "pid": os.getpid(),
            "delay_seconds": delay_seconds,
            "host": host,
            "port": port,
            "reason": reason,
        }

    schedule_server_restart = deps.get("schedule_server_restart") or default_schedule_server_restart

    def require_root_actor():
        actor = get_current_user_ctx()
        if not actor:
            return None, (json_resp({"ok":False,"msg":"未登入"}), 401)
        if actor["username"] != "root":
            return None, (json_resp({"ok":False,"msg":"只有 root 可執行此操作"}), 403)
        return actor, None

    def require_super_admin_actor():
        actor = get_current_user_ctx()
        if not actor:
            return None, (json_resp({"ok":False,"msg":"未登入"}), 401)
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return None, (json_resp({"ok":False,"msg":"只有最高管理者可查看健康中心"}), 403)
        return actor, None

    def _is_sensitive_setting_key(key):
        lowered = str(key or "").lower()
        return any(marker in lowered for marker in ("password", "secret", "token", "hash", "key"))

    def _audit_setting_value(key, value):
        if _is_sensitive_setting_key(key):
            return "<redacted>" if str(value or "") else ""
        return value

    def _audit_settings_changed(event_type, actor, before, saved, *, scope="", extra=None):
        before = dict(before or {})
        saved = dict(saved or {})
        changes = []
        for key in sorted(saved):
            old_value = before.get(key)
            new_value = saved.get(key)
            changes.append({
                "key": key,
                "old": _audit_setting_value(key, old_value),
                "new": _audit_setting_value(key, new_value),
                "changed": old_value != new_value,
            })
        detail = {
            "scope": scope or event_type,
            "changed_keys": [row["key"] for row in changes if row["changed"]],
            "keys": [row["key"] for row in changes],
            "changes": changes,
        }
        if extra:
            detail["extra"] = extra
        audit(
            event_type,
            get_client_ip(),
            user=actor["username"] if actor else "-",
            success=True,
            ua=get_ua(),
            detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
        )

    def _force_points_block(reason, actor):
        if not points_service:
            return None
        result = points_service.force_seal_block(actor=actor, reason=reason)
        if result.get("sealed"):
            block = result.get("block") or {}
            audit(
                "POINTS_FORCE_BLOCK_SEALED",
                get_client_ip(),
                user=actor["username"] if actor else "-",
                success=True,
                ua=get_ua(),
                detail=f"reason={reason},block_number={block.get('block_number')},ledger_count={block.get('ledger_count')}",
            )
        elif result.get("ok") is False:
            audit(
                "POINTS_FORCE_BLOCK_FAILED",
                get_client_ip(),
                user=actor["username"] if actor else "-",
                success=False,
                ua=get_ua(),
                detail=f"reason={reason},msg={result.get('msg')}",
            )
        return result

    def cloud_drive_storage_payload(settings):
        configured = str(settings.get("cloud_drive_storage_root") or "").strip()
        current = os.path.abspath(STORAGE_DIR) if STORAGE_DIR else ""
        effective = configured or current
        restart_required = False
        if configured and current:
            try:
                restart_required = os.path.realpath(configured) != os.path.realpath(current)
            except Exception:
                restart_required = configured != current
        return {
            "configured_root": configured,
            "current_root": current,
            "effective_next_root": effective,
            "restart_required": restart_required,
        }

    def ssl_cert_exists():
        return os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)

    def server_ssl_payload(settings):
        return server_ssl_settings_payload(
            settings,
            current_ssl_enabled=CURRENT_SERVER_BIND_STATE.get("ssl_enabled"),
            cert_exists=ssl_cert_exists(),
        )

    def _security_test_report_root():
        path = os.path.join(BASE_DIR, "security", "reports", "root-triggered")
        os.makedirs(path, exist_ok=True)
        return path

    def _safe_security_test_int(value, default, minimum, maximum):
        try:
            number = int(value if value not in (None, "") else default)
        except Exception:
            return None
        if minimum <= number <= maximum:
            return number
        return None

    def _security_test_job_payload(job):
        payload = {key: job.get(key) for key in (
            "job_id",
            "kind",
            "status",
            "started_at",
            "finished_at",
            "returncode",
            "command_label",
            "report_root",
            "report_dir",
            "log_path",
            "error",
        )}
        return payload

    def _find_latest_report_dir(report_root, prefix, started_at_ts):
        try:
            candidates = []
            for name in os.listdir(report_root):
                full = os.path.join(report_root, name)
                if not os.path.isdir(full):
                    continue
                if prefix and not name.startswith(prefix):
                    continue
                try:
                    mtime = os.path.getmtime(full)
                except Exception:
                    mtime = 0
                if mtime + 2 >= started_at_ts:
                    candidates.append((mtime, full))
            if not candidates:
                return ""
            candidates.sort(reverse=True)
            return os.path.relpath(candidates[0][1], BASE_DIR)
        except Exception:
            return ""

    def _start_security_test_job(kind, command, *, command_label, report_root, report_prefix, actor, env=None):
        job_id = f"{kind}_{uuid.uuid4().hex[:12]}"
        started_ts = time.time()
        actor_username = actor.get("username") if actor else "root"
        client_ip = get_client_ip()
        log_dir = os.path.join(report_root, "_jobs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{job_id}.log")
        job = {
            "job_id": job_id,
            "kind": kind,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "finished_at": "",
            "returncode": None,
            "command_label": command_label,
            "report_root": os.path.relpath(report_root, BASE_DIR),
            "report_dir": "",
            "log_path": os.path.relpath(log_path, BASE_DIR),
            "error": "",
            "actor": actor_username,
        }
        with SECURITY_TEST_JOBS_LOCK:
            SECURITY_TEST_JOBS[job_id] = job

        def runner():
            proc_env = os.environ.copy()
            if env:
                proc_env.update(env)
            try:
                with open(log_path, "w", encoding="utf-8") as log_file:
                    log_file.write(f"$ {' '.join(command_label)}\n\n")
                    log_file.flush()
                    proc = subprocess.Popen(
                        command,
                        cwd=BASE_DIR,
                        env=proc_env,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    code = proc.wait()
                status = "passed" if code == 0 else "failed"
                report_dir = _find_latest_report_dir(report_root, report_prefix, started_ts)
                with SECURITY_TEST_JOBS_LOCK:
                    job.update({
                        "status": status,
                        "finished_at": datetime.now().isoformat(),
                        "returncode": code,
                        "report_dir": report_dir,
                    })
                audit("SECURITY_TEST_FINISHED", client_ip, user=actor_username, success=(code == 0), detail=f"job_id={job_id},kind={kind},returncode={code},report_dir={report_dir}")
            except Exception as exc:
                with SECURITY_TEST_JOBS_LOCK:
                    job.update({
                        "status": "failed",
                        "finished_at": datetime.now().isoformat(),
                        "returncode": None,
                        "error": str(exc),
                    })
                audit("SECURITY_TEST_FAILED", client_ip, user=actor_username, success=False, detail=f"job_id={job_id},kind={kind},error={exc}")

        threading.Thread(target=runner, name=f"security-test-{job_id}", daemon=True).start()
        audit("SECURITY_TEST_STARTED", client_ip, user=actor_username, success=True, detail=f"job_id={job_id},kind={kind},command={command_label}")
        return job

    def safe_count(conn, table, where="", params=()):
        try:
            sql = f"SELECT COUNT(*) AS c FROM {table}"
            if where:
                sql += f" WHERE {where}"
            row = conn.execute(sql, params).fetchone()
            return int(row["c"] or 0), None
        except Exception as exc:
            return 0, str(exc)

    def dir_stats(path, suffix=None):
        if not path or not os.path.isdir(path):
            return {"exists": False, "files": 0, "bytes": 0, "path": path}
        files = []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if not os.path.isfile(full):
                continue
            if suffix and not name.endswith(suffix):
                continue
            files.append(full)
        return {
            "exists": True,
            "files": len(files),
            "bytes": sum(os.path.getsize(path) for path in files),
            "path": path,
        }

    def audit_integrity_summary():
        audit_enabled = is_audit_chain_enabled()
        if not audit_enabled:
            return {"enabled": False, "ok": None, "broken_at": None, "details": "audit chain disabled"}
        audit_ok, audit_broken, audit_details = verify_audit_integrity()
        return {"enabled": True, "ok": audit_ok, "broken_at": audit_broken, "details": audit_details}

    def db_integrity_summary():
        conn = get_db()
        try:
            quick_rows = conn.execute("PRAGMA quick_check").fetchall()
            quick_check = [row[0] for row in quick_rows]
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            foreign_key_violations = [dict(row) for row in fk_rows]
            schema_version = get_schema_version(conn)
            return {
                "ok": quick_check == ["ok"] and not foreign_key_violations and schema_version == CURRENT_SCHEMA_VERSION,
                "quick_check": quick_check,
                "foreign_key_violations": foreign_key_violations,
                "schema_version": schema_version,
                "expected_schema_version": CURRENT_SCHEMA_VERSION,
            }
        finally:
            conn.close()

    def health_counts():
        conn = get_db()
        errors = {}
        try:
            now = datetime.now().isoformat()
            counts = {}
            for key, table, where, params in (
                ("users_total", "users", "", ()),
                ("active_users", "users", "status='active'", ()),
                ("active_sessions", "sessions", "expires_at>? AND COALESCE(is_revoked, 0)=0", (now,)),
                ("chat_messages", "chat_messages", "", ()),
                ("pending_chat_reports", "chat_message_reports", "status='pending'", ()),
                ("pending_appeals", "violation_appeals", "status='pending'", ()),
                ("pending_moderation_proposals", "moderation_proposals", "status='pending'", ()),
                ("pending_board_reviews", "forum_boards", "status='pending'", ()),
                ("pending_thread_reviews", "forum_threads", "status='pending'", ()),
                ("violations_total", "secure_violations", "", ()),
                ("audit_entries", "secure_audit", "", ()),
                ("uploaded_files", "uploaded_files", "deleted_at IS NULL", ()),
                ("quarantined_files", "uploaded_files", "scan_status='quarantined' OR risk_level='blocked'", ()),
                ("unknown_encrypted_files", "uploaded_files", "risk_level='unknown_encrypted'", ()),
            ):
                value, err = safe_count(conn, table, where, params)
                counts[key] = value
                if err:
                    errors[key] = err
            return counts, errors
        finally:
            conn.close()

    def readiness_summary():
        settings = get_system_settings()
        db = db_integrity_summary()
        audit_state = audit_integrity_summary()
        checks = []

        def add_check(name, ok, detail="", severity="critical"):
            checks.append({"name": name, "ok": bool(ok), "detail": detail, "severity": severity})

        add_check("database_integrity", db["ok"], f"schema={db['schema_version']}/{db['expected_schema_version']}")
        add_check("database_file", os.path.exists(DB_PATH), DB_PATH)
        add_check("chat_dir", os.path.isdir(CHAT_DIR), CHAT_DIR, severity="degraded")
        add_check("log_dir", os.path.isdir(LOG_DIR), LOG_DIR, severity="degraded")
        add_check("anchor_dir", os.path.isdir(ANCHOR_DIR), ANCHOR_DIR, severity="degraded")
        if STORAGE_DIR:
            add_check("storage_dir", os.path.isdir(STORAGE_DIR), STORAGE_DIR, severity="degraded")
        add_check("audit_chain", audit_state["ok"] is not False, audit_state["details"], severity="critical")
        add_check("maintenance_mode", not bool(settings.get("maintenance_mode", False)), "maintenance_mode=true" if settings.get("maintenance_mode", False) else "off", severity="degraded")

        if snapshot_service:
            try:
                snapshots = snapshot_service.list_snapshots(actor={"id": 0, "username": "system"})
                add_check("snapshot_service", True, f"snapshots={len(snapshots)}", severity="degraded")
            except Exception as exc:
                add_check("snapshot_service", False, str(exc), severity="degraded")
        else:
            add_check("snapshot_service", False, "unavailable", severity="degraded")
        if integrity_guard:
            try:
                integrity = integrity_guard.status()
                high_pending = int((integrity.get("summary") or {}).get("high_risk_pending") or 0)
                pending = int((integrity.get("summary") or {}).get("pending") or 0)
                add_check("integrity_guard", high_pending == 0, f"pending={pending},high={high_pending}", severity="critical")
            except Exception as exc:
                add_check("integrity_guard", False, str(exc), severity="critical")

        status = "ok"
        if any((not item["ok"]) and item["severity"] == "critical" for item in checks):
            status = "critical"
        elif any(not item["ok"] for item in checks):
            status = "degraded"
        return {"status": status, "checks": checks, "database": db, "audit_integrity": audit_state}

    def anomaly_summary():
        counts, errors = health_counts()
        audit_state = audit_integrity_summary()
        settings = get_system_settings()
        signals = []

        def signal(name, level, value, threshold, detail=""):
            signals.append({"name": name, "level": level, "value": value, "threshold": threshold, "detail": detail})

        if audit_state["ok"] is False:
            signal("audit_chain_broken", "critical", audit_state["broken_at"], "ok", audit_state["details"])
        if settings.get("maintenance_mode", False):
            signal("maintenance_mode", "warning", True, False, "site is in maintenance mode")
        pending_chat_threshold = int(settings.get("security_pending_chat_reports_threshold", 10) or 10)
        pending_appeals_threshold = int(settings.get("security_pending_appeals_threshold", 10) or 10)
        pending_mod_threshold = int(settings.get("security_pending_moderation_proposals_threshold", 10) or 10)
        quarantined_threshold = int(settings.get("security_quarantined_files_threshold", 0) or 0)
        unknown_encrypted_threshold = int(settings.get("security_unknown_encrypted_files_threshold", 50) or 50)
        if counts.get("pending_chat_reports", 0) >= pending_chat_threshold:
            signal("pending_chat_reports", "warning", counts["pending_chat_reports"], pending_chat_threshold)
        if counts.get("pending_appeals", 0) >= pending_appeals_threshold:
            signal("pending_appeals", "warning", counts["pending_appeals"], pending_appeals_threshold)
        if counts.get("pending_moderation_proposals", 0) >= pending_mod_threshold:
            signal("pending_moderation_proposals", "warning", counts["pending_moderation_proposals"], pending_mod_threshold)
        if counts.get("quarantined_files", 0) > quarantined_threshold:
            signal("quarantined_files", "warning", counts["quarantined_files"], quarantined_threshold)
        if counts.get("unknown_encrypted_files", 0) >= unknown_encrypted_threshold:
            signal("unknown_encrypted_files", "info", counts["unknown_encrypted_files"], unknown_encrypted_threshold)
        if errors:
            signal("count_errors", "warning", len(errors), 0, str(errors))

        level_rank = {"ok": 0, "info": 1, "warning": 2, "critical": 3}
        status = "ok"
        for item in signals:
            if level_rank[item["level"]] > level_rank[status]:
                status = item["level"]
        return {"status": status, "signals": signals, "counts": counts, "errors": errors, "audit_integrity": audit_state}

    SECURITY_SETTING_KEYS = (
        "maintenance_mode",
        "server_ssl_enabled",
        "audit_chain_enabled",
        "ip_blocking_enabled",
        "login_violation_enabled",
        "rate_limit_violation_enabled",
        "root_ip_whitelist_enabled",
        "root_ip_whitelist",
        "browser_only_mode_enabled",
        "integrity_guard_enabled",
        "integrity_guard_strict_mode",
    )
    SECURITY_THRESHOLD_KEYS = (
        "max_login_failures",
        "block_duration_minutes",
        "security_pending_chat_reports_threshold",
        "security_pending_appeals_threshold",
        "security_pending_moderation_proposals_threshold",
        "security_quarantined_files_threshold",
        "security_unknown_encrypted_files_threshold",
        "security_log_tail_lines",
    )

    def tail_file(path, max_lines=200):
        try:
            max_lines = max(1, min(int(max_lines), 1000))
        except Exception:
            max_lines = 200
        if not path or not os.path.exists(path):
            return {"path": path or "", "exists": False, "lines": []}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-max_lines:]
            return {"path": path, "exists": True, "lines": [line.rstrip("\n") for line in lines]}
        except Exception as exc:
            return {"path": path, "exists": True, "error": str(exc), "lines": []}

    def recent_secure_audit(limit=50):
        limit = max(1, min(int(limit or 50), 200))
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, ts, action, ip, user, success, ua, detail, chain_hash "
                "FROM secure_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "timestamp": row["ts"],
                    "action": row["action"],
                    "ip": row["ip"],
                    "actor": row["user"],
                    "success": bool(row["success"]),
                    "ua": row["ua"],
                    "details": row["detail"],
                    "_chain_hash": row["chain_hash"],
                }
                for row in rows
            ]
        except Exception:
            return []
        finally:
            conn.close()

    def security_center_payload():
        settings = get_system_settings()
        log_lines = int(settings.get("security_log_tail_lines", 200) or 200)
        return {
            "readiness": readiness_summary(),
            "anomaly": anomaly_summary(),
            "audit_integrity": audit_integrity_summary(),
            "audit_entries": recent_secure_audit(50),
            "server_log": tail_file(SERVER_LOG_PATH, log_lines),
            "server_output": get_server_output(limit=log_lines),
            "settings": {key: settings.get(key) for key in SECURITY_SETTING_KEYS},
            "thresholds": {key: settings.get(key) for key in SECURITY_THRESHOLD_KEYS},
            "features": get_feature_settings(),
            "mode": server_mode_service.get_current_mode() if server_mode_service else None,
            "profiles": server_mode_service.list_profiles() if server_mode_service else [],
        }

    def security_profile_payload(data):
        settings = data.get("settings") or {}
        thresholds = data.get("thresholds") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings or "{}")
            except Exception:
                return None, "settings JSON 格式錯誤"
        if isinstance(thresholds, str):
            try:
                thresholds = json.loads(thresholds or "{}")
            except Exception:
                return None, "thresholds JSON 格式錯誤"
        if not isinstance(settings, dict):
            return None, "settings 必須是 JSON object"
        if not isinstance(thresholds, dict):
            return None, "thresholds 必須是 JSON object"

        unknown_settings = sorted(str(key) for key in settings if key not in SECURITY_SETTING_KEYS)
        unknown_thresholds = sorted(str(key) for key in thresholds if key not in SECURITY_THRESHOLD_KEYS)
        if unknown_settings:
            return None, f"不支援的 settings key：{', '.join(unknown_settings)}"
        if unknown_thresholds:
            return None, f"不支援的 thresholds key：{', '.join(unknown_thresholds)}"

        normalized_thresholds = {}
        for key, value in thresholds.items():
            try:
                number = int(value)
            except Exception:
                return None, f"{key} 必須是整數"
            if number < 0 or number > 100000:
                return None, f"{key} 必須介於 0-100000"
            normalized_thresholds[key] = number

        return {"settings": {key: settings[key] for key in settings}, "thresholds": normalized_thresholds}, None

    @app.route("/api/admin/health", methods=["GET"])
    @require_csrf_safe
    def admin_health():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可查看伺服器健康度"}), 403

        settings = get_system_settings()
        audit_enabled = is_audit_chain_enabled()
        if audit_enabled:
            audit_ok, audit_broken, audit_details = verify_audit_integrity()
            if not audit_ok:
                activate_emergency_lockdown(f"audit_chain_broken_at={audit_broken}; {audit_details}")
                settings = get_system_settings()
        else:
            audit_ok, audit_broken, audit_details = None, None, "audit chain disabled"

        counts, count_errors = health_counts()
        counts["pending_reports"] = counts.get("pending_chat_reports", 0)

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        chat_stats = dir_stats(CHAT_DIR, ".jsonl")
        log_stats = dir_stats(LOG_DIR)
        anchor_stats = dir_stats(ANCHOR_DIR)
        storage_stats = dir_stats(STORAGE_DIR)
        capacity_conn = get_db()
        try:
            storage_capacity = audit_storage_capacity(capacity_conn, STORAGE_DIR)
        finally:
            capacity_conn.close()
        readiness = readiness_summary()
        anomaly = anomaly_summary()
        status = "critical" if ((audit_enabled and audit_ok is False) or settings.get("maintenance_mode", False) or readiness["status"] == "critical") else "ok"
        if storage_capacity["status"] == "critical":
            status = "critical"
        if status == "ok" and (readiness["status"] == "degraded" or anomaly["status"] in {"warning", "critical"} or count_errors):
            status = "degraded"
        if status == "ok" and storage_capacity["status"] == "warning":
            status = "degraded"
        return json_resp({
            "ok": True,
            "status": status,
            "maintenance_mode": settings.get("maintenance_mode", False),
            "audit_integrity": {"enabled": audit_enabled, "ok": audit_ok, "broken_at": audit_broken, "details": audit_details},
            "counts": counts,
            "count_errors": count_errors,
            "storage": {
                "database_bytes": db_size,
                "chat_files": chat_stats["files"],
                "chat_bytes": chat_stats["bytes"],
                "chat_dir": "chats/",
                "log_files": log_stats["files"],
                "log_bytes": log_stats["bytes"],
                "anchor_files": anchor_stats["files"],
                "anchor_bytes": anchor_stats["bytes"],
                "storage_files": storage_stats["files"],
                "storage_bytes": storage_stats["bytes"],
                "capacity_audit": storage_capacity,
            },
            "readiness": readiness,
            "anomaly": anomaly,
        })

    @app.route("/api/admin/environment", methods=["GET"])
    @require_csrf_safe
    def admin_environment():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可查看系統環境"}), 403

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        log_files = [name for name in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, name))] if os.path.isdir(LOG_DIR) else []
        chat_files = [name for name in os.listdir(CHAT_DIR) if os.path.isfile(os.path.join(CHAT_DIR, name))] if os.path.isdir(CHAT_DIR) else []
        anchor_files = [name for name in os.listdir(ANCHOR_DIR) if os.path.isfile(os.path.join(ANCHOR_DIR, name))] if os.path.isdir(ANCHOR_DIR) else []
        return json_resp({
            "ok": True,
            "environment": {
                "platform": platform.platform(),
                "python_version": sys.version.split()[0],
                "pid": os.getpid(),
                "base_dir": BASE_DIR,
                "database_path": DB_PATH,
                "log_dir": LOG_DIR,
                "chat_dir": CHAT_DIR,
                "anchor_dir": ANCHOR_DIR,
                "database_bytes": db_size,
                "log_files": len(log_files),
                "chat_files": len(chat_files),
                "anchor_files": len(anchor_files),
            }
        })

    @app.route("/api/admin/health/readiness", methods=["GET"])
    @require_csrf_safe
    def admin_health_readiness():
        _, error = require_super_admin_actor()
        if error:
            return error
        summary = readiness_summary()
        return json_resp({"ok": True, "readiness": summary})

    @app.route("/api/admin/health/anomaly", methods=["GET"])
    @require_csrf_safe
    def admin_health_anomaly():
        _, error = require_super_admin_actor()
        if error:
            return error
        return json_resp({"ok": True, "anomaly": anomaly_summary()})

    @app.route("/api/admin/health/audit-chain", methods=["GET"])
    @require_csrf_safe
    def admin_health_audit_chain():
        _, error = require_super_admin_actor()
        if error:
            return error
        return json_resp({"ok": True, "audit_integrity": audit_integrity_summary()})

    @app.route("/api/admin/health/db-integrity", methods=["GET"])
    @require_csrf_safe
    def admin_health_db_integrity():
        _, error = require_super_admin_actor()
        if error:
            return error
        return json_resp({"ok": True, "database": db_integrity_summary()})

    @app.route("/api/admin/security-center", methods=["GET"])
    @require_csrf_safe
    def admin_security_center():
        _, error = require_root_actor()
        if error:
            return error
        return json_resp({"ok": True, "security_center": security_center_payload()})

    @app.route("/api/admin/server-output", methods=["GET"])
    @require_csrf_safe
    def admin_server_output():
        _, error = require_root_actor()
        if error:
            return error
        limit = request.args.get("limit", 200)
        return json_resp({"ok": True, "server_output": get_server_output(limit=limit)})

    @app.route("/api/root/security-tests", methods=["GET"])
    @require_csrf_safe
    def root_security_tests():
        _, error = require_root_actor()
        if error:
            return error
        with SECURITY_TEST_JOBS_LOCK:
            jobs = [_security_test_job_payload(job) for job in SECURITY_TEST_JOBS.values()]
        jobs.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return json_resp({"ok": True, "jobs": jobs[:20], "report_root": os.path.relpath(_security_test_report_root(), BASE_DIR)})

    @app.route("/api/root/security-tests/<job_id>", methods=["GET"])
    @require_csrf_safe
    def root_security_test_detail(job_id):
        _, error = require_root_actor()
        if error:
            return error
        with SECURITY_TEST_JOBS_LOCK:
            job = SECURITY_TEST_JOBS.get(job_id)
            payload = _security_test_job_payload(job) if job else None
        if not payload:
            return json_resp({"ok": False, "msg": "找不到測試任務"}), 404
        return json_resp({"ok": True, "job": payload})

    @app.route("/api/root/security-tests/pentest", methods=["POST"])
    @require_csrf
    def root_security_test_pentest():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        target = str(data.get("target") or request.host_url or "").strip().rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-_\[\]:]+(?::\d+)?(?:/.*)?", target):
            return json_resp({"ok": False, "msg": "target 必須是 http(s) URL"}), 400
        tool_timeout = _safe_security_test_int(data.get("tool_timeout_seconds"), 180, 1, 3600)
        if tool_timeout is None:
            return json_resp({"ok": False, "msg": "tool_timeout_seconds 必須介於 1-3600"}), 400
        report_root = _security_test_report_root()
        command = [
            os.path.join(BASE_DIR, "security", "run_pentest.sh"),
            "--target", target,
            "--out", report_root,
            "--tool-timeout", str(tool_timeout),
        ]
        only = str(data.get("only") or "").strip()
        skip = str(data.get("skip") or "").strip()
        if only:
            command.extend(["--only", only])
        if skip:
            command.extend(["--skip", skip])
        if bool(data.get("i_own_this_target")):
            command.append("--i-own-this-target")
        env = {}
        for key in ("ROOT_PASSWORD", "MANAGER_PASSWORD", "TEST_PASSWORD"):
            value = str(data.get(key.lower()) or "").strip()
            if value:
                env[key] = value
        username_env_keys = {
            "root_username": "PENTEST_ROOT_USERNAME",
            "manager_username": "PENTEST_MANAGER_USERNAME",
            "user_username": "PENTEST_USER_USERNAME",
        }
        for payload_key, env_key in username_env_keys.items():
            value = str(data.get(payload_key) or "").strip()
            if value:
                env[env_key] = value
        job = _start_security_test_job(
            "pentest",
            command,
            command_label=["security/run_pentest.sh", "--target", target],
            report_root=report_root,
            report_prefix="20",
            actor=actor,
            env=env,
        )
        return json_resp({"ok": True, "msg": "滲透測試已啟動", "job": _security_test_job_payload(job)}, 202)

    @app.route("/api/root/security-tests/functional", methods=["POST"])
    @require_csrf
    def root_security_test_functional():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        port = _safe_security_test_int(data.get("port"), 50741, 1, 65535)
        if port is None:
            return json_resp({"ok": False, "msg": "port 必須介於 1-65535"}), 400
        report_root = _security_test_report_root()
        command = [
            os.path.join(BASE_DIR, "security", "run_functional_smoke.sh"),
            "--port", str(port),
            "--out", report_root,
        ]
        if bool(data.get("keep_runtime")):
            command.append("--keep-runtime")
        env = {}
        for key in ("ROOT_PASSWORD", "ROOT_CHANGED_PASSWORD", "MANAGER_PASSWORD", "TEST_PASSWORD"):
            value = str(data.get(key.lower()) or "").strip()
            if value:
                env[key] = value
        job = _start_security_test_job(
            "functional",
            command,
            command_label=["security/run_functional_smoke.sh", "--port", str(port)],
            report_root=report_root,
            report_prefix="functional_",
            actor=actor,
            env=env,
        )
        return json_resp({"ok": True, "msg": "全功能測試已啟動", "job": _security_test_job_payload(job)}, 202)

    @app.route("/api/admin/security-center/thresholds", methods=["PUT"])
    @require_csrf_safe
    def admin_security_center_thresholds():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        updates = {}
        for key in SECURITY_THRESHOLD_KEYS:
            if key not in data:
                continue
            try:
                value = int(data.get(key))
            except Exception:
                return json_resp({"ok": False, "msg": f"{key} 必須是整數"}), 400
            if value < 0 or value > 100000:
                return json_resp({"ok": False, "msg": f"{key} 必須介於 0-100000"}), 400
            updates[key] = value
        if not updates:
            return json_resp({"ok": False, "msg": "沒有可寫入的閾值"}), 400
        before_settings = get_system_settings()
        saved = save_settings(updates)
        _audit_settings_changed("SECURITY_THRESHOLDS_CHANGED", actor, before_settings, saved, scope="security_thresholds")
        return json_resp({"ok": True, "msg": "安全閾值已更新", "thresholds": {key: get_system_settings().get(key) for key in SECURITY_THRESHOLD_KEYS}})

    @app.route("/api/admin/security-center/controls", methods=["PUT"])
    @require_csrf_safe
    def admin_security_center_controls():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        updates = {key: data[key] for key in SECURITY_SETTING_KEYS if key in data}
        if not updates:
            return json_resp({"ok": False, "msg": "沒有可寫入的安全機制開關"}), 400
        before_settings = get_system_settings()
        saved = save_settings(updates)
        _audit_settings_changed("SECURITY_CONTROLS_CHANGED", actor, before_settings, saved, scope="security_controls")
        return json_resp({"ok": True, "msg": "安全機制設定已更新", "settings": {key: get_system_settings().get(key) for key in SECURITY_SETTING_KEYS}})

    @app.route("/api/admin/security-center/profiles", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_security_profiles():
        if not server_mode_service:
            return json_resp({"ok": False, "msg": "server mode service unavailable"}), 503
        if request.method == "GET":
            _, error = require_super_admin_actor()
            if error:
                return error
            return json_resp({"ok": True, "profiles": server_mode_service.list_profiles()})
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        profile_payload, err = security_profile_payload(data)
        if err:
            return json_resp({"ok": False, "msg": err}), 400
        result = server_mode_service.save_profile(
            name=data.get("name"),
            label=data.get("label"),
            description=data.get("description") or "",
            settings=profile_payload["settings"],
            thresholds=profile_payload["thresholds"],
            actor=actor,
        )
        if result.get("ok"):
            audit("SECURITY_PROFILE_SAVED", get_client_ip(), user=actor["username"], success=True, detail=f"profile={result['profile']['name']}")
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/integrity/status", methods=["GET"])
    @require_csrf_safe
    def root_integrity_status():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        return json_resp({"ok":True,"integrity":integrity_guard.status()})

    @app.route("/api/root/integrity/rescan", methods=["POST"])
    @require_csrf
    def root_integrity_rescan():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        result = integrity_guard.scan(actor=actor["username"], create_initial_manifest=True)
        audit("INTEGRITY_RESCAN", get_client_ip(), user=actor["username"], success=bool(result.get("ok")), detail=f"status={result.get('status') or result.get('last_scan', {}).get('status')}")
        return json_resp({"ok":bool(result.get("ok", True)),"integrity":result}), (200 if result.get("ok", True) else 500)

    @app.route("/api/root/integrity/findings", methods=["GET"])
    @require_csrf_safe
    def root_integrity_findings():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        status = request.args.get("status") or None
        return json_resp({"ok":True,"findings":integrity_guard.list_findings(status=status)})

    @app.route("/api/root/integrity/findings/<int:finding_id>", methods=["GET"])
    @require_csrf_safe
    def root_integrity_finding(finding_id):
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        finding = integrity_guard.get_finding(finding_id)
        if not finding:
            return json_resp({"ok":False,"msg":"找不到 integrity finding"}), 404
        return json_resp({"ok":True,"finding":finding})

    def handle_integrity_review(finding_id, action):
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        result = integrity_guard.review_finding(
            finding_id,
            action=action,
            actor=actor,
            note=data.get("note") or "",
            confirm=data.get("confirm") or "",
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/integrity/findings/bulk-review", methods=["POST"])
    @require_csrf
    def root_integrity_bulk_review():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        action = str(data.get("action") or "").strip().lower()
        if action not in {"approve", "reject", "ignore"}:
            return json_resp({"ok":False,"msg":"unsupported integrity action"}), 400
        raw_ids = data.get("finding_ids") or data.get("ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return json_resp({"ok":False,"msg":"finding_ids 不可為空"}), 400
        try:
            finding_ids = [int(item) for item in raw_ids]
        except Exception:
            return json_resp({"ok":False,"msg":"finding_ids 格式錯誤"}), 400
        confirm = str(data.get("confirm") or "")
        if action == "approve" and confirm != CONFIRM_APPROVE:
            return json_resp({"ok":False,"msg":"approve confirmation mismatch"}), 400
        note = str(data.get("note") or "")[:1000]
        results = []
        ok_count = 0
        for finding_id in finding_ids:
            result = integrity_guard.review_finding(
                finding_id,
                action=action,
                actor=actor,
                note=note,
                confirm=confirm,
            )
            result["finding_id"] = finding_id
            results.append(result)
            if result.get("ok"):
                ok_count += 1
        audit(
            f"INTEGRITY_FINDING_BULK_{action.upper()}",
            get_client_ip(),
            user=actor["username"],
            success=ok_count == len(finding_ids),
            ua=get_ua(),
            detail=f"ids={finding_ids}, ok={ok_count}/{len(finding_ids)}, note={note}",
        )
        return json_resp({"ok": ok_count == len(finding_ids), "action": action, "reviewed": ok_count, "total": len(finding_ids), "results": results}), (200 if ok_count == len(finding_ids) else 400)

    @app.route("/api/root/integrity/findings/<int:finding_id>/approve", methods=["POST"])
    @require_csrf
    def root_integrity_approve(finding_id):
        return handle_integrity_review(finding_id, "approve")

    @app.route("/api/root/integrity/findings/<int:finding_id>/reject", methods=["POST"])
    @require_csrf
    def root_integrity_reject(finding_id):
        return handle_integrity_review(finding_id, "reject")

    @app.route("/api/root/integrity/findings/<int:finding_id>/ignore", methods=["POST"])
    @require_csrf
    def root_integrity_ignore(finding_id):
        return handle_integrity_review(finding_id, "ignore")

    @app.route("/api/root/integrity/report", methods=["GET"])
    @require_csrf_safe
    def root_integrity_report():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg":"integrity guard unavailable"}), 503
        return json_resp({"ok":True,"report":integrity_guard.export_report(),"approve_confirm":CONFIRM_APPROVE})

    # ── Root Web Terminal: libvirt/KVM edition ────────────────────────────────
    @app.route("/api/root/web-terminal/qemu/config", methods=["GET"])
    @require_csrf_safe
    def root_web_terminal_qemu_config():
        actor, error = require_root_actor()
        if error:
            return error
        config = public_config(web_terminal_manager.config())
        return json_resp({
            "ok": True,
            "config": config,
            "websocket_available": sock is not None,
            "provider": "libvirt-qemu",
        })

    @app.route("/api/root/web-terminal/qemu/health", methods=["GET", "POST"])
    @require_csrf_safe
    def root_web_terminal_qemu_health():
        actor, error = require_root_actor()
        if error:
            return error
        result = web_terminal_manager.health()
        audit(
            "WEB_TERMINAL_QEMU_HEALTH_CHECK",
            get_client_ip(),
            user=actor["username"],
            success=bool(result.get("ok")),
            ua=get_ua(),
            detail=json.dumps({
                "ok": result.get("ok"),
                "summary": result.get("summary"),
                "failed": result.get("failed_checks") or [r["name"] for r in result.get("checks", []) if not r.get("ok")],
                "config": result.get("config"),
            }, ensure_ascii=False),
        )
        status = 200 if result.get("ok") else 503
        return json_resp({"ok": bool(result.get("ok")), "health": result, "websocket_available": sock is not None}), status

    @app.route("/api/root/web-terminal/qemu/sessions", methods=["GET", "POST"])
    @require_csrf_safe
    def root_web_terminal_qemu_sessions():
        actor, error = require_root_actor()
        if error:
            return error
        if request.method == "GET":
            return json_resp({"ok": True, "sessions": web_terminal_manager.list_sessions()})
        if sock is None:
            audit("WEB_TERMINAL_QEMU_SESSION_CREATE_BLOCKED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail="flask-sock unavailable")
            return json_resp({"ok": False, "msg": "WebSocket 支援尚未安裝，請執行 ./install_web_terminal_qemu_dependencies.sh --python"}), 503
        session, err = web_terminal_manager.create_session(actor=dict(actor), ip=get_client_ip(), ua=get_ua())
        if err:
            return json_resp({"ok": False, "msg": err, "health": web_terminal_manager.health()}), 503
        return json_resp({"ok": True, "session": session}), 202

    @app.route("/api/root/web-terminal/qemu/sessions/<session_id>", methods=["GET", "DELETE"])
    @require_csrf_safe
    def root_web_terminal_qemu_session_detail(session_id):
        actor, error = require_root_actor()
        if error:
            return error
        session = web_terminal_manager.refresh_session_status(session_id)
        if not session:
            return json_resp({"ok": False, "msg": "找不到 terminal session"}), 404
        if request.method == "GET":
            return json_resp({"ok": True, "session": session.payload()})
        ok, msg = web_terminal_manager.close_session(session_id, actor=dict(actor), ip=get_client_ip(), reason="root_delete")
        if not ok:
            return json_resp({"ok": False, "msg": msg}), 500
        return json_resp({"ok": True, "msg": "terminal session 已關閉"})

    if sock is not None:
        @sock.route("/api/root/web-terminal/qemu/sessions/<session_id>/ws")
        def root_web_terminal_qemu_ws(ws, session_id):
            actor, error = require_root_actor()
            if error:
                try:
                    ws.send("未授權或非 root，連線關閉。\r\n")
                finally:
                    ws.close()
                return
            session = web_terminal_manager.get_session(session_id)
            if not session:
                ws.send("找不到 terminal session。\r\n")
                ws.close()
                return
            try:
                command = web_terminal_manager.websocket_ssh_command(session_id)
                audit("WEB_TERMINAL_QEMU_WS_OPEN", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=json.dumps({"session_id": session_id, "vm_name": session.vm_name}, ensure_ascii=False))
                close_reason = bridge_ssh_to_websocket(
                    command,
                    ws,
                    idle_timeout_seconds=web_terminal_manager.config()["idle_timeout_seconds"],
                    initial_rows=getattr(session, "terminal_rows", 51),
                    initial_cols=getattr(session, "terminal_cols", 209),
                )
                audit("WEB_TERMINAL_QEMU_WS_CLOSE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=json.dumps({"session_id": session_id, "vm_name": session.vm_name, "reason": close_reason}, ensure_ascii=False))
                web_terminal_manager.close_session(session_id, actor=dict(actor), ip=get_client_ip(), reason=close_reason or "ws_closed")
            except Exception as exc:
                audit("WEB_TERMINAL_QEMU_WS_FAILED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=json.dumps({"session_id": session_id, "error": str(exc)}, ensure_ascii=False))
                try:
                    ws.send(f"Web Terminal session 已關閉：{exc}\r\n")
                finally:
                    ws.close()
                    web_terminal_manager.close_session(session_id, actor=dict(actor), ip=get_client_ip(), reason="ws_failed")

    # ── 系統參數（超級管理者 only）───────────────────────────────────────────────
    @app.route("/api/admin/settings", methods=["GET","PUT"])
    @require_csrf_safe
    def admin_settings():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有最高管理者可修改系統參數"}), 403

        if request.method == "GET":
            settings = get_system_settings()
            return json_resp({
                "ok": True,
                "settings": settings,
                "server_bind": server_bind_settings_payload(
                    settings,
                    current_host=CURRENT_SERVER_BIND_STATE.get("host"),
                    current_port=CURRENT_SERVER_BIND_STATE.get("port"),
                ),
                "server_ssl": server_ssl_payload(settings),
                "cloud_drive_storage": cloud_drive_storage_payload(settings),
            })

        # PUT
        try:
            data = request.get_json(force=True)
        except:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        if "server_listen_host" in data:
            host = validate_listen_host(data.get("server_listen_host"), allow_empty=True)
            if host is None:
                return json_resp({"ok":False,"msg":"server_listen_host 必須是 IP、localhost，或留空沿用環境變數"}), 400
            data["server_listen_host"] = host
        if "server_listen_port" in data:
            port = validate_listen_port(data.get("server_listen_port"), allow_empty=True)
            if port is None:
                return json_resp({"ok":False,"msg":"server_listen_port 必須是 1-65535，或 0/空值沿用環境變數"}), 400
            data["server_listen_port"] = port
        if "server_ssl_enabled" in data:
            data["server_ssl_enabled"] = bool(data.get("server_ssl_enabled"))
        if "comfyui_api_host" in data:
            host = validate_comfyui_api_host(data.get("comfyui_api_host"))
            if host is None:
                return json_resp({"ok":False,"msg":"comfyui_api_host 必須是主機名稱或 IP，不可包含 http://、路徑、帳密或特殊字元"}), 400
            data["comfyui_api_host"] = host
        if "comfyui_api_port" in data:
            try:
                port = int(data.get("comfyui_api_port"))
            except Exception:
                return json_resp({"ok":False,"msg":"comfyui_api_port 必須是 1-65535"}), 400
            if port < 1 or port > 65535:
                return json_resp({"ok":False,"msg":"comfyui_api_port 必須是 1-65535"}), 400
            data["comfyui_api_port"] = port
        if "comfyui_max_batch_size" in data:
            try:
                batch_size = int(data.get("comfyui_max_batch_size"))
            except Exception:
                return json_resp({"ok":False,"msg":"comfyui_max_batch_size 必須是 1-8"}), 400
            if batch_size < 1 or batch_size > 8:
                return json_resp({"ok":False,"msg":"comfyui_max_batch_size 必須是 1-8"}), 400
            data["comfyui_max_batch_size"] = batch_size
        if "cloud_drive_storage_root" in data:
            raw_root = str(data.get("cloud_drive_storage_root") or "").strip()
            if raw_root:
                try:
                    data["cloud_drive_storage_root"] = str(validate_storage_root(raw_root, base_dir=BASE_DIR, create=False))
                except ValueError as exc:
                    return json_resp({"ok":False,"msg":f"cloud_drive_storage_root 不安全或格式錯誤：{exc}"}), 400
            else:
                data["cloud_drive_storage_root"] = ""
        if "web_terminal_enabled" in data:
            data["web_terminal_enabled"] = bool(data.get("web_terminal_enabled"))
        if "web_terminal_qemu_distro" in data:
            distro = str(data.get("web_terminal_qemu_distro") or "").strip()
            if distro not in {"ubuntu-22.04", "ubuntu-24.04"}:
                return json_resp({"ok":False,"msg":"web_terminal_qemu_distro 必須是 ubuntu-22.04 或 ubuntu-24.04"}), 400
            data["web_terminal_qemu_distro"] = distro
        if "web_terminal_qemu_network_mode" in data:
            mode = str(data.get("web_terminal_qemu_network_mode") or "").strip()
            if mode not in {"none", "nat", "restricted", "user"}:
                return json_resp({"ok":False,"msg":"web_terminal_qemu_network_mode 必須是 none、nat、restricted 或 user"}), 400
            data["web_terminal_qemu_network_mode"] = mode
        if "web_terminal_qemu_libvirt_uri" in data:
            uri = str(data.get("web_terminal_qemu_libvirt_uri") or "").strip()
            if uri != "qemu:///system":
                return json_resp({"ok":False,"msg":"第一版只允許 qemu:///system"}), 400
            data["web_terminal_qemu_libvirt_uri"] = uri
        if "web_terminal_qemu_storage_dir" in data:
            raw_dir = str(data.get("web_terminal_qemu_storage_dir") or "").strip()
            try:
                # This validates an absolute non-project host path without creating it.
                web_terminal_manager.config()  # keep manager initialized for tests
                from services.web_terminal_qemu import validate_vm_root
                data["web_terminal_qemu_storage_dir"] = str(validate_vm_root(raw_dir, project_base_dir=BASE_DIR))
            except Exception as exc:
                return json_resp({"ok":False,"msg":f"web_terminal_qemu_storage_dir 不安全或格式錯誤：{exc}"}), 400
        if "web_terminal_qemu_base_image_path" in data:
            raw_image = str(data.get("web_terminal_qemu_base_image_path") or "").strip()
            if raw_image and (not os.path.isabs(raw_image) or ".." in Path(raw_image).parts):
                return json_resp({"ok":False,"msg":"web_terminal_qemu_base_image_path 必須是安全的絕對路徑"}), 400
            data["web_terminal_qemu_base_image_path"] = raw_image
        for key, lo, hi in (
            ("web_terminal_qemu_vcpus", 1, 4),
            ("web_terminal_qemu_memory_mb", 512, 8192),
            ("web_terminal_qemu_disk_gb", 5, 100),
            ("web_terminal_qemu_idle_timeout_seconds", 0, 86400),
            ("web_terminal_qemu_terminal_rows", 12, 200),
            ("web_terminal_qemu_terminal_cols", 80, 400),
        ):
            if key in data:
                try:
                    value = int(data.get(key))
                except Exception:
                    return json_resp({"ok":False,"msg":f"{key} 必須是 {lo}-{hi} 的整數"}), 400
                if value < lo or value > hi:
                    return json_resp({"ok":False,"msg":f"{key} 必須是 {lo}-{hi} 的整數"}), 400
                data[key] = value
        if "captcha_mode" in data:
            raw_mode = str(data.get("captcha_mode") or "").strip().lower()
            if raw_mode and normalize_captcha_mode(raw_mode) != raw_mode:
                return json_resp({"ok":False,"msg":"captcha_mode 必須是 none、math、image 或 turnstile"}), 400
            data["captcha_mode"] = normalize_captcha_mode(raw_mode)
        if "captcha_ttl_seconds" in data:
            try:
                ttl_seconds = int(data.get("captcha_ttl_seconds"))
            except Exception:
                return json_resp({"ok":False,"msg":"captcha_ttl_seconds 必須是 60-3600 秒"}), 400
            if ttl_seconds < 60 or ttl_seconds > 3600:
                return json_resp({"ok":False,"msg":"captcha_ttl_seconds 必須是 60-3600 秒"}), 400
            data["captcha_ttl_seconds"] = ttl_seconds
        if "storage_trash_retention_days" in data:
            try:
                retention_days = int(data.get("storage_trash_retention_days"))
            except Exception:
                return json_resp({"ok":False,"msg":"storage_trash_retention_days 必須是 0-3650"}), 400
            if retention_days < 0 or retention_days > 3650:
                return json_resp({"ok":False,"msg":"storage_trash_retention_days 必須是 0-3650"}), 400
            data["storage_trash_retention_days"] = retention_days
        if "storage_maintenance_daily_time" in data:
            if not re.fullmatch(r"\d{2}:\d{2}", str(data.get("storage_maintenance_daily_time") or "")):
                return json_resp({"ok":False,"msg":"storage_maintenance_daily_time 必須是 HH:MM"}), 400

        before_settings = get_system_settings()
        settings = save_settings(data)
        if not settings:
            return json_resp({"ok":False,"msg":"沒有可寫入的設定欄位"}), 400

        _audit_settings_changed("SETTINGS_CHANGED", actor, before_settings, settings, scope="system_settings")
        return json_resp({
            "ok": True,
            "msg": "系統參數已更新",
            "settings": settings,
            "server_bind": server_bind_settings_payload(
                get_system_settings(),
                current_host=CURRENT_SERVER_BIND_STATE.get("host"),
                current_port=CURRENT_SERVER_BIND_STATE.get("port"),
            ),
            "server_ssl": server_ssl_payload(get_system_settings()),
            "cloud_drive_storage": cloud_drive_storage_payload(get_system_settings()),
        })

    @app.route("/api/admin/cloud-drive/security-policy", methods=["GET", "PUT"])
    @require_csrf_safe
    def admin_cloud_drive_security_policy():
        actor, error = require_root_actor()
        if error:
            return error
        conn = get_db()
        try:
            ensure_upload_security_schema(conn)
            if request.method == "GET":
                return json_resp({"ok":True,"policy":get_cloud_drive_security_policy(conn)})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
            policy, err = update_cloud_drive_security_policy(conn, data)
            if err:
                return json_resp({"ok":False,"msg":err}), 400
            conn.commit()
            audit("CLOUD_DRIVE_POLICY_UPDATED", get_client_ip(), user=actor["username"], success=True,
                  detail=str(policy))
            return json_resp({"ok":True,"msg":"雲端硬碟安全政策已更新","policy":policy})
        finally:
            conn.close()

    @app.route("/api/admin/features", methods=["GET", "PUT"])
    @require_csrf_safe
    def admin_features():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可修改功能開關"}), 403

        if request.method == "GET":
            return json_resp({"ok":True,"features":get_feature_settings()})

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        before_settings = get_system_settings()
        updates = save_feature_settings(data)
        if not updates:
            return json_resp({"ok":False,"msg":"沒有可寫入的功能開關"}), 400
        _audit_settings_changed("FEATURE_FLAGS_CHANGED", actor, before_settings, updates, scope="feature_flags")
        return json_resp({"ok":True,"msg":"功能開關已更新","features":updates})

    @app.route("/api/admin/access-controls", methods=["GET", "PUT"])
    @require_csrf_safe
    def admin_access_controls():
        actor, error = require_root_actor()
        if error:
            return error
        if request.method == "GET":
            return json_resp({"ok":True,"access_controls":access_control_settings_payload(get_system_settings())})
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        updates = {}
        for key in ("root_ip_whitelist_enabled", "root_ip_whitelist", "browser_only_mode_enabled"):
            if key in data:
                updates[key] = data[key]
        if "clear_maintenance_bypass_token" in data and data.get("clear_maintenance_bypass_token"):
            updates["maintenance_bypass_token_hash"] = ""
            updates["maintenance_bypass_token_expires_at"] = ""
        if "clear_internal_test_token" in data and data.get("clear_internal_test_token"):
            updates["internal_test_login_token_hash"] = ""
            updates["internal_test_login_token_expires_at"] = ""
        if not updates:
            return json_resp({"ok":False,"msg":"沒有可寫入的存取控制設定"}), 400
        before_settings = get_system_settings()
        saved = save_settings(updates)
        _audit_settings_changed("ACCESS_CONTROLS_CHANGED", actor, before_settings, saved, scope="access_controls")
        return json_resp({"ok":True,"msg":"存取控制設定已更新","access_controls":access_control_settings_payload(get_system_settings())})

    @app.route("/api/admin/access-controls/maintenance-bypass-token", methods=["POST"])
    @require_csrf
    def admin_rotate_maintenance_bypass_token():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        if data.get("confirm") != "ROTATE":
            return json_resp({"ok":False,"msg":"confirm 必須等於 ROTATE"}), 400
        ttl_minutes = data.get("ttl_minutes", 30)
        try:
            ttl_minutes = max(1, min(int(ttl_minutes), 24 * 60))
        except Exception:
            ttl_minutes = 30
        token = generate_maintenance_bypass_token()
        expires_at = maintenance_bypass_expires_at(ttl_minutes)
        before_settings = get_system_settings()
        saved = save_settings({
            "maintenance_bypass_token_hash": hash_maintenance_bypass_token(token),
            "maintenance_bypass_token_expires_at": expires_at,
        })
        _audit_settings_changed(
            "MAINTENANCE_BYPASS_TOKEN_ROTATED",
            actor,
            before_settings,
            saved,
            scope="maintenance_bypass_token",
            extra={"ttl_minutes": ttl_minutes, "expires_at": expires_at},
        )
        return json_resp({
            "ok": True,
            "msg": "maintenance bypass token 已更新，token 只會顯示這一次",
            "token": token,
            "expires_at": expires_at,
            "ttl_minutes": ttl_minutes,
            "access_controls": access_control_settings_payload(get_system_settings()),
        })

    @app.route("/api/admin/access-controls/internal-test-token", methods=["POST"])
    @require_csrf
    def admin_rotate_internal_test_token():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        if data.get("confirm") != "ROTATE_INTERNAL_TEST_TOKEN":
            return json_resp({"ok":False,"msg":"confirm 必須等於 ROTATE_INTERNAL_TEST_TOKEN"}), 400
        ttl_minutes = data.get("ttl_minutes", 24 * 60)
        try:
            ttl_minutes = max(5, min(int(ttl_minutes), 30 * 24 * 60))
        except Exception:
            ttl_minutes = 24 * 60
        token = generate_internal_test_token()
        expires_at = maintenance_bypass_expires_at(ttl_minutes)
        before_settings = get_system_settings()
        saved = save_settings({
            "internal_test_login_token_hash": hash_internal_test_token(token),
            "internal_test_login_token_expires_at": expires_at,
        })
        _audit_settings_changed(
            "INTERNAL_TEST_TOKEN_ROTATED",
            actor,
            before_settings,
            saved,
            scope="internal_test_token",
            extra={"ttl_minutes": ttl_minutes, "expires_at": expires_at},
        )
        return json_resp({
            "ok": True,
            "msg": "內測登入 token 已更新，token 只會顯示這一次",
            "token": token,
            "expires_at": expires_at,
            "ttl_minutes": ttl_minutes,
            "access_controls": access_control_settings_payload(get_system_settings()),
        })

    @app.route("/api/admin/member-level-rules", methods=["GET"])
    @require_csrf_safe
    def admin_member_level_rules():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可管理會員等級規則"}), 403

        conn = get_db()
        try:
            ensure_member_level_rules_schema(conn)
            conn.commit()
            rows = conn.execute("SELECT * FROM member_level_rules").fetchall()
            by_level = {row["level"]: dict(row) for row in rows}
            rules = []
            for level in DEFAULT_MEMBER_LEVEL_RULES:
                row = by_level.get(level)
                if row:
                    rules.append(serialize_member_level_rule(row))
            return json_resp({"ok":True,"rules":rules})
        finally:
            conn.close()

    @app.route("/api/admin/member-level-rules/<level>", methods=["PUT"])
    @require_csrf_safe
    def admin_update_member_level_rule(level):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可管理會員等級規則"}), 403

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400

        conn = get_db()
        try:
            rule, err = update_member_level_rule(conn, level, data)
            if err:
                return json_resp({"ok":False,"msg":err}), 400
            conn.commit()
            audit("MEMBER_LEVEL_RULE_UPDATED", get_client_ip(), user=actor["username"], success=True,
                  detail=f"level={level}, rule={rule}")
            return json_resp({"ok":True,"msg":"會員等級規則已更新","rule":rule})
        finally:
            conn.close()

    @app.route("/api/admin/snapshots", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_snapshots():
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        if request.method == "GET":
            return json_resp({"ok":True,"snapshots":snapshot_service.list_snapshots(actor=actor)})
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        snapshot_type = data.get("type") or "manual"
        if snapshot_type == "before_superweak" and actor["username"] != "root":
            return json_resp({"ok":False,"msg":"before_superweak snapshot 必須由 root 建立"}), 403
        result = snapshot_service.create_snapshot(snapshot_type=snapshot_type, actor=actor, notes=data.get("notes") or "")
        if not result.ok:
            return json_resp({"ok":False,"msg":"snapshot 建立失敗","error":result.error,"snapshot_id":result.snapshot_id}), 500
        block_result = _force_points_block("snapshot_create", actor)
        payload = {"ok":True,"snapshot_id":result.snapshot_id,"status":result.status}
        if block_result:
            payload["points_block"] = block_result
        return json_resp(payload)

    @app.route("/api/admin/snapshots/daily", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_daily_snapshots():
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        settings = get_system_settings()
        if request.method == "GET":
            return json_resp({"ok":True,"daily":snapshot_service.daily_snapshot_status(settings=settings)})
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        if data.get("confirm") != "RUN_DAILY_SNAPSHOT":
            return json_resp({"ok":False,"msg":"confirm 必須等於 RUN_DAILY_SNAPSHOT"}), 400
        result = snapshot_service.create_daily_snapshot_if_due(
            actor=actor,
            settings=settings,
            save_settings=save_settings,
            force=bool(data.get("force")),
            notes=data.get("notes") or "",
        )
        if result.get("ok") and result.get("created"):
            result["points_block"] = _force_points_block("daily_snapshot", actor)
        return json_resp(result), (200 if result.get("ok") else 500)

    @app.route("/api/admin/system-reset", methods=["POST"])
    @require_csrf
    def admin_system_reset():
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        result = snapshot_service.reset_runtime_state(
            actor=actor,
            confirm=data.get("confirm"),
            reason=data.get("reason") or "",
        )
        if result.get("ok"):
            try:
                restart = schedule_server_restart(reason="system-reset", delay_seconds=1.25)
            except Exception as exc:
                result["restart_scheduled"] = False
                result["restart_error"] = str(exc)
                result["msg"] = "runtime state reset，但重啟排程失敗"
                return json_resp(result), 500
            result["restart_scheduled"] = True
            result["restart"] = restart
            result["msg"] = "runtime state reset，服務器正在重啟"
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/snapshots/<snapshot_id>", methods=["GET", "DELETE"])
    @require_csrf_safe
    def admin_snapshot_detail(snapshot_id):
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            if request.method == "GET":
                snapshot = snapshot_service.get_snapshot(snapshot_id=snapshot_id, actor=actor)
                if not snapshot:
                    return json_resp({"ok":False,"msg":"找不到 snapshot"}), 404
                return json_resp({"ok":True,"snapshot":snapshot})
            result = snapshot_service.delete_snapshot(snapshot_id=snapshot_id, actor=actor, reason=request.args.get("reason") or "root delete")
            return json_resp(result)
        except ValueError as exc:
            return json_resp({"ok":False,"msg":str(exc)}), 400

    @app.route("/api/admin/snapshots/<snapshot_id>/download", methods=["GET"])
    @require_csrf_safe
    def admin_snapshot_download(snapshot_id):
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            result = snapshot_service.export_snapshot_archive(snapshot_id=snapshot_id, actor=actor)
        except ValueError as exc:
            return json_resp({"ok":False,"msg":str(exc)}), 400
        if not result.get("ok"):
            return json_resp(result), 400
        return send_file(
            result["path"],
            as_attachment=True,
            download_name=result["filename"],
            mimetype="application/gzip",
        )

    @app.route("/api/admin/snapshots/upload-restore", methods=["POST"])
    @require_csrf
    def admin_snapshot_upload_restore():
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        if "file" not in request.files:
            return json_resp({"ok":False,"msg":"缺少 snapshot 檔案"}), 400
        dry_run = str(request.form.get("dry_run") or "").strip().lower() in {"1", "true", "yes", "on"}
        confirm = request.form.get("confirm") or ""
        if dry_run:
            if confirm != "DRY_RUN":
                return json_resp({"ok":False,"msg":"dry_run confirm 必須等於 DRY_RUN"}), 400
        elif confirm != "RESTORE":
            return json_resp({"ok":False,"msg":"confirm 必須等於 RESTORE"}), 400
        result = snapshot_service.restore_snapshot_archive(
            actor=actor,
            file_storage=request.files["file"],
            reason=request.form.get("reason") or "",
            dry_run=dry_run,
        )
        if result.get("ok") and not dry_run:
            result["points_block"] = _force_points_block("snapshot_restore_upload", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/snapshots/<snapshot_id>/restore", methods=["POST"])
    @require_csrf
    def admin_snapshot_restore(snapshot_id):
        if not snapshot_service:
            return json_resp({"ok":False,"msg":"snapshot service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        dry_run = bool(data.get("dry_run"))
        confirm = data.get("confirm")
        if dry_run:
            if confirm != "DRY_RUN":
                return json_resp({"ok":False,"msg":"dry_run confirm 必須等於 DRY_RUN"}), 400
        elif confirm != "RESTORE":
            return json_resp({"ok":False,"msg":"confirm 必須等於 RESTORE"}), 400
        try:
            result = snapshot_service.restore_snapshot(
                snapshot_id=snapshot_id,
                actor=actor,
                reason=data.get("reason") or "",
                dry_run=dry_run,
            )
        except ValueError as exc:
            return json_resp({"ok":False,"msg":str(exc)}), 400
        if result.get("ok") and not dry_run:
            result["points_block"] = _force_points_block("snapshot_restore", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/server-mode", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_server_mode():
        if not server_mode_service:
            return json_resp({"ok":False,"msg":"server mode service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        if request.method == "GET":
            return json_resp({"ok":True,"mode":server_mode_service.get_current_mode(),"profiles":server_mode_service.list_profiles()})
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        result = server_mode_service.switch_mode(
            target_mode=data.get("mode"),
            actor=actor,
            confirm=data.get("confirm"),
            notes=data.get("notes") or "",
        )
        if result.get("ok"):
            result["points_block"] = _force_points_block("server_mode_change", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/server-mode/exit-superweak", methods=["POST"])
    @require_csrf
    def admin_exit_superweak():
        if not server_mode_service:
            return json_resp({"ok":False,"msg":"server mode service unavailable"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        result = server_mode_service.exit_superweak(
            actor=actor,
            action=data.get("action"),
            confirm=data.get("confirm"),
            reason=data.get("reason") or "",
        )
        if result.get("ok"):
            result["points_block"] = _force_points_block("superweak_exit", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/integrity/repair", methods=["POST"])
    @require_csrf
    def admin_repair_integrity_chains():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可處理鏈異常"}), 403

        audit_before = verify_audit_integrity() if is_audit_chain_enabled() else (None, None, "audit chain disabled")
        audit_result = repair_audit_chain(reason=f"manual_repair_by={actor['username']}")
        violation_result = repair_violation_chains()
        before_settings = get_system_settings()
        saved = save_settings({"maintenance_mode": False})
        _audit_settings_changed("SETTINGS_CHANGED", actor, before_settings, saved, scope="integrity_repair")
        audit_after = verify_audit_integrity() if is_audit_chain_enabled() else (None, None, "audit chain disabled")

        audit(
            "INTEGRITY_CHAINS_RESEALED",
            get_client_ip(),
            user=actor["username"],
            success=True,
            detail=(
                f"audit_before={audit_before[2]}; audit_resealed={audit_result['entries_resealed']}; "
                f"violations_resealed={violation_result['entries_resealed']}; maintenance_mode=False"
            ),
        )
        return json_resp({
            "ok": True,
            "msg": "鏈異常已重新封鏈，維護模式已關閉",
            "audit": {
                "before": {"ok": audit_before[0], "broken_at": audit_before[1], "details": audit_before[2]},
                "after": {"ok": audit_after[0], "broken_at": audit_after[1], "details": audit_after[2]},
                **audit_result,
            },
            "violations": violation_result,
            "maintenance_mode": False,
        })

    # ── 重啟服務器（超級管理者 only）─────────────────────────────────────────────
    @app.route("/api/admin/restart", methods=["POST"])
    @require_csrf
    def admin_restart():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有最高管理者可重啟服務器"}), 403

        audit("SERVER_RESTART", get_client_ip(), user=actor["username"], detail="initiated by admin")
        try:
            restart = schedule_server_restart(reason="manual-restart", delay_seconds=1.25)
        except Exception as exc:
            return json_resp({"ok":False,"msg":"重啟排程失敗","error":str(exc)}), 500
        return json_resp({"ok":True,"msg":"服務器正在重啟，請稍後重新整理頁面","restart_scheduled":True,"restart":restart})

    @app.route("/api/admin/platform-stats", methods=["GET"])
    @require_csrf_safe
    def admin_platform_stats():
        actor, error = require_super_admin_actor()
        if error:
            return error

        conn = get_db()
        try:
            now = datetime.utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
            today_start = now.strftime("%Y-%m-%d 00:00:00")

            total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

            new_users_month = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE created_at >= ?", (month_start,)
            ).fetchone()["c"]

            try:
                active_sessions = conn.execute(
                    "SELECT COUNT(*) AS c FROM sessions WHERE last_active_at >= datetime('now', '-15 minutes')"
                ).fetchone()["c"]
            except Exception:
                active_sessions = 0

            try:
                pv_today = conn.execute(
                    "SELECT COUNT(*) AS c FROM page_views WHERE viewed_at >= ?", (today_start,)
                ).fetchone()["c"]
            except Exception:
                pv_today = 0

            try:
                total_points = conn.execute("SELECT COALESCE(SUM(points), 0) AS c FROM users").fetchone()["c"]
            except Exception:
                total_points = 0

            try:
                points_earned_month = conn.execute(
                    "SELECT COALESCE(SUM(delta), 0) AS c FROM point_transactions WHERE delta > 0 AND created_at >= ?",
                    (month_start,)
                ).fetchone()["c"]
            except Exception:
                points_earned_month = 0

            try:
                points_spent_month = abs(int(conn.execute(
                    "SELECT COALESCE(SUM(delta), 0) AS c FROM point_transactions WHERE delta < 0 AND created_at >= ?",
                    (month_start,)
                ).fetchone()["c"] or 0))
            except Exception:
                points_spent_month = 0

            return json_resp({
                "ok": True,
                "stats": {
                    "total_users": total_users,
                    "new_users_month": new_users_month,
                    "active_sessions": active_sessions,
                    "page_views_today": pv_today,
                    "total_points": total_points,
                    "points_earned_month": points_earned_month,
                    "points_spent_month": points_spent_month,
                    "points_net_month": points_earned_month - points_spent_month,
                }
            })
        finally:
            conn.close()

    @app.route("/<path:invalid>", methods=["GET", "POST", "OPTIONS"], provide_automatic_options=False)
    def catch_all(invalid):
        ip, ua = get_client_ip(), get_ua()
        audit("404_CATCHALL", ip, ua=ua, detail=f"path={invalid}")
        resp = json_resp({"ok":False,"msg":"Not found"})
        if request.method == "OPTIONS":
            resp.headers["Allow"] = "GET, POST, HEAD, OPTIONS"
        return resp, 404
