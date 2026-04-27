import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from flask import request

from services.access_controls import (
    access_control_settings_payload,
    generate_maintenance_bypass_token,
    hash_maintenance_bypass_token,
)
from services.bootstrap import CURRENT_SCHEMA_VERSION, get_schema_version
from services.member_levels import (
    DEFAULT_MEMBER_LEVEL_RULES,
    ensure_member_level_rules_schema,
    serialize_member_level_rule,
    update_member_level_rule,
)


def register_system_admin_routes(app, deps):
    ANCHOR_DIR = deps["ANCHOR_DIR"]
    BASE_DIR = deps["BASE_DIR"]
    CHAT_DIR = deps["CHAT_DIR"]
    DB_PATH = deps["DB_PATH"]
    LOG_DIR = deps["LOG_DIR"]
    SERVER_LOG_PATH = deps["SERVER_LOG_PATH"]
    STORAGE_DIR = deps.get("STORAGE_DIR")
    activate_emergency_lockdown = deps["activate_emergency_lockdown"]
    audit = deps["audit"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_ua = deps.get("get_ua", lambda: "-")
    get_feature_settings = deps["get_feature_settings"]
    get_system_settings = deps["get_system_settings"]
    is_audit_chain_enabled = deps["is_audit_chain_enabled"]
    json_resp = deps["json_resp"]
    repair_audit_chain = deps["repair_audit_chain"]
    repair_violation_chains = deps["repair_violation_chains"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps["role_rank"]
    save_feature_settings = deps["save_feature_settings"]
    save_settings = deps["save_settings"]
    server_mode_service = deps.get("server_mode_service")
    snapshot_service = deps.get("snapshot_service")
    verify_audit_integrity = deps["verify_audit_integrity"]

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
        if counts.get("pending_chat_reports", 0) >= 10:
            signal("pending_chat_reports", "warning", counts["pending_chat_reports"], 10)
        if counts.get("pending_appeals", 0) >= 10:
            signal("pending_appeals", "warning", counts["pending_appeals"], 10)
        if counts.get("pending_moderation_proposals", 0) >= 10:
            signal("pending_moderation_proposals", "warning", counts["pending_moderation_proposals"], 10)
        if counts.get("quarantined_files", 0) > 0:
            signal("quarantined_files", "warning", counts["quarantined_files"], 0)
        if counts.get("unknown_encrypted_files", 0) >= 50:
            signal("unknown_encrypted_files", "info", counts["unknown_encrypted_files"], 50)
        if errors:
            signal("count_errors", "warning", len(errors), 0, str(errors))

        level_rank = {"ok": 0, "info": 1, "warning": 2, "critical": 3}
        status = "ok"
        for item in signals:
            if level_rank[item["level"]] > level_rank[status]:
                status = item["level"]
        return {"status": status, "signals": signals, "counts": counts, "errors": errors, "audit_integrity": audit_state}

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

        conn = get_db()
        try:
            users_total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            active_users = conn.execute("SELECT COUNT(*) AS c FROM users WHERE status='active'").fetchone()["c"]
            sessions_total = conn.execute("SELECT COUNT(*) AS c FROM sessions WHERE expires_at>?", (datetime.now().isoformat(),)).fetchone()["c"]
            messages_total = conn.execute("SELECT COUNT(*) AS c FROM chat_messages").fetchone()["c"]
            reports_pending = conn.execute("SELECT COUNT(*) AS c FROM chat_message_reports WHERE status='pending'").fetchone()["c"]
            appeals_pending = conn.execute("SELECT COUNT(*) AS c FROM violation_appeals WHERE status='pending'").fetchone()["c"]
            violations_total = conn.execute("SELECT COUNT(*) AS c FROM secure_violations").fetchone()["c"]
            audit_total = conn.execute("SELECT COUNT(*) AS c FROM secure_audit").fetchone()["c"]
        finally:
            conn.close()

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        chat_files = [name for name in os.listdir(CHAT_DIR) if name.endswith(".jsonl")] if os.path.isdir(CHAT_DIR) else []
        chat_size = sum(os.path.getsize(os.path.join(CHAT_DIR, name)) for name in chat_files)
        status = "critical" if ((audit_enabled and audit_ok is False) or settings.get("maintenance_mode", False)) else "ok"
        return json_resp({
            "ok": True,
            "status": status,
            "maintenance_mode": settings.get("maintenance_mode", False),
            "audit_integrity": {"enabled": audit_enabled, "ok": audit_ok, "broken_at": audit_broken, "details": audit_details},
            "counts": {
                "users_total": users_total,
                "active_users": active_users,
                "active_sessions": sessions_total,
                "chat_messages": messages_total,
                "pending_reports": reports_pending,
                "pending_appeals": appeals_pending,
                "violations_total": violations_total,
                "audit_entries": audit_total,
            },
            "storage": {
                "database_bytes": db_size,
                "chat_files": len(chat_files),
                "chat_bytes": chat_size,
                "chat_dir": "chats/",
            }
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
            return json_resp({"ok":True,"settings":get_system_settings()})

        # PUT
        try:
            data = request.get_json(force=True)
        except:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        settings = save_settings(data)
        if not settings:
            return json_resp({"ok":False,"msg":"沒有可寫入的設定欄位"}), 400

        audit("SETTINGS_CHANGED", get_client_ip(), user=actor["username"],
              detail=str(settings))
        return json_resp({"ok":True,"msg":"系統參數已更新","settings":settings})

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

        updates = save_feature_settings(data)
        if not updates:
            return json_resp({"ok":False,"msg":"沒有可寫入的功能開關"}), 400
        audit("FEATURE_FLAGS_CHANGED", get_client_ip(), user=actor["username"], success=True,
              detail=str(updates))
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
        if not updates:
            return json_resp({"ok":False,"msg":"沒有可寫入的存取控制設定"}), 400
        saved = save_settings(updates)
        audit("ACCESS_CONTROLS_CHANGED", get_client_ip(), user=actor["username"], success=True,
              detail=str(access_control_settings_payload({**get_system_settings(), **saved})))
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
        token = generate_maintenance_bypass_token()
        save_settings({"maintenance_bypass_token_hash": hash_maintenance_bypass_token(token)})
        audit("MAINTENANCE_BYPASS_TOKEN_ROTATED", get_client_ip(), user=actor["username"], success=True,
              detail="token_hash_rotated")
        return json_resp({
            "ok": True,
            "msg": "maintenance bypass token 已更新，token 只會顯示這一次",
            "token": token,
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
        return json_resp({"ok":True,"snapshot_id":result.snapshot_id,"status":result.status})

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
            return json_resp({"ok":True,"mode":server_mode_service.get_current_mode()})
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
        save_settings({"maintenance_mode": False})
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
        # 非同步重啟，避免來不及回應
        import threading, subprocess
        def restart_delayed():
            time.sleep(1.5)
            # Kill old server on port 5000
            subprocess.run(["fuser", "-k", "5000/tcp"],
                           cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            # Start new server
            subprocess.Popen(
                ["python3", os.path.join(BASE_DIR, "server.py")],
                cwd=BASE_DIR,
                stdout=open(SERVER_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
        threading.Thread(target=restart_delayed, daemon=True).start()
        return json_resp({"ok":True,"msg":"服務器正在重啟，請稍後重新整理頁面"})

    @app.route("/<path:invalid>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
    def catch_all(invalid):
        ip, ua = get_client_ip(), get_ua()
        audit("404_CATCHALL", ip, ua=ua, detail=f"path={invalid}")
        return json_resp({"ok":False,"msg":"Not found"}), 404
