import re

from flask import request

from services.security.captcha import normalize_captcha_mode
from services.storage.paths import validate_storage_root
from services.upload_security import (
    ensure_upload_security_schema,
    get_cloud_drive_security_policy,
    update_cloud_drive_security_policy,
)
from services.users.member_levels import (
    DEFAULT_MEMBER_LEVEL_RULES,
    ensure_member_level_rules_schema,
    serialize_member_level_rule,
    update_member_level_rule,
)


def register_system_admin_settings_routes(app, ctx):
    BASE_DIR = ctx["BASE_DIR"]
    CURRENT_SERVER_BIND_STATE = ctx["CURRENT_SERVER_BIND_STATE"]

    get_current_user_ctx = ctx["get_current_user_ctx"]
    get_db = ctx["get_db"]
    get_feature_settings = ctx["get_feature_settings"]
    get_system_settings = ctx["get_system_settings"]
    json_resp = ctx["json_resp"]
    save_feature_settings = ctx["save_feature_settings"]
    save_settings = ctx["save_settings"]
    audit = ctx["audit"]
    get_client_ip = ctx["get_client_ip"]
    role_rank = ctx["role_rank"]
    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    require_root_actor = ctx["require_root_actor"]

    access_control_settings_payload = ctx["access_control_settings_payload"]
    audit_settings_changed = ctx["audit_settings_changed"]
    cloud_drive_storage_payload = ctx["cloud_drive_storage_payload"]
    feature_dependency_error_payload = ctx["feature_dependency_error_payload"]
    find_feature_dependency_violations = ctx["find_feature_dependency_violations"]
    generate_internal_test_token = ctx["generate_internal_test_token"]
    generate_maintenance_bypass_token = ctx["generate_maintenance_bypass_token"]
    hash_internal_test_token = ctx["hash_internal_test_token"]
    hash_maintenance_bypass_token = ctx["hash_maintenance_bypass_token"]
    maintenance_bypass_expires_at = ctx["maintenance_bypass_expires_at"]
    normalize_ip_whitelist_or_none = ctx["normalize_ip_whitelist_or_none"]
    parse_int_in_range = ctx["parse_int_in_range"]
    parse_strict_bool = ctx["parse_strict_bool"]
    server_bind_settings_payload = ctx["server_bind_settings_payload"]
    server_ssl_payload = ctx["server_ssl_payload"]
    validate_comfyui_api_host = ctx["validate_comfyui_api_host"]
    validate_comfyui_api_url = ctx["validate_comfyui_api_url"]
    validate_comfyui_relative_script = ctx["validate_comfyui_relative_script"]
    validate_listen_host = ctx["validate_listen_host"]
    validate_listen_port = ctx["validate_listen_port"]
    is_hhmm = ctx["is_hhmm"]

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

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        current_settings = get_system_settings()
        bool_keys = {
            key for key, value in (current_settings or {}).items()
            if isinstance(value, bool)
        }
        for key in bool_keys & set(data.keys()):
            parsed = parse_strict_bool(data.get(key))
            if parsed is None:
                return json_resp({"ok":False,"msg":f"{key} 必須是布林值 true/false"}), 400
            data[key] = parsed
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
        if "comfyui_connection_mode" in data:
            mode = str(data.get("comfyui_connection_mode") or "").strip().lower()
            if mode not in {"local", "remote"}:
                return json_resp({"ok":False,"msg":"comfyui_connection_mode 必須是 local 或 remote"}), 400
            data["comfyui_connection_mode"] = mode
        if "comfyui_remote_api_url" in data:
            api_url = validate_comfyui_api_url(data.get("comfyui_remote_api_url"))
            if api_url is None:
                return json_resp({"ok":False,"msg":"comfyui_remote_api_url 必須是 http(s)://host:port，不可包含帳密、路徑或參數"}), 400
            data["comfyui_remote_api_url"] = api_url
        if "comfyui_base_dir" in data:
            raw_base = str(data.get("comfyui_base_dir") or "").strip()
            if raw_base:
                try:
                    data["comfyui_base_dir"] = str(validate_storage_root(raw_base, base_dir=BASE_DIR, create=False))
                except ValueError as exc:
                    return json_resp({"ok":False,"msg":f"comfyui_base_dir 不安全或格式錯誤：{exc}"}), 400
            else:
                data["comfyui_base_dir"] = ""
        if "comfyui_local_start_script" in data:
            base_dir_for_script = data.get("comfyui_base_dir")
            if base_dir_for_script is None:
                base_dir_for_script = (get_system_settings() or {}).get("comfyui_base_dir")
            script = validate_comfyui_relative_script(
                data.get("comfyui_local_start_script"),
                base_dir=base_dir_for_script,
            )
            if script is None:
                return json_resp({"ok":False,"msg":"comfyui_local_start_script 必須在 ComfyUI 本地資料夾內，可填相對路徑或同資料夾下的絕對路徑"}), 400
            data["comfyui_local_start_script"] = script
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
        if "comfyui_civitai_api_key" in data:
            data["comfyui_civitai_api_key"] = str(data.get("comfyui_civitai_api_key") or "").strip()
        if "comfyui_max_batch_size" in data:
            try:
                batch_size = int(data.get("comfyui_max_batch_size"))
            except Exception:
                return json_resp({"ok":False,"msg":"comfyui_max_batch_size 必須是 1-8"}), 400
            if batch_size < 1 or batch_size > 8:
                return json_resp({"ok":False,"msg":"comfyui_max_batch_size 必須是 1-8"}), 400
            data["comfyui_max_batch_size"] = batch_size
        for key in ("comfyui_default_width", "comfyui_default_height"):
            if key in data:
                try:
                    size = int(data.get(key))
                except Exception:
                    return json_resp({"ok":False,"msg":f"{key} 必須是 64-2048 且為 8 的倍數"}), 400
                if size < 64 or size > 2048 or size % 8 != 0:
                    return json_resp({"ok":False,"msg":f"{key} 必須是 64-2048 且為 8 的倍數"}), 400
                data[key] = size
        if "cloud_drive_storage_root" in data:
            raw_root = str(data.get("cloud_drive_storage_root") or "").strip()
            if raw_root:
                try:
                    data["cloud_drive_storage_root"] = str(validate_storage_root(raw_root, base_dir=BASE_DIR, create=False))
                except ValueError as exc:
                    return json_resp({"ok":False,"msg":f"cloud_drive_storage_root 不安全或格式錯誤：{exc}"}), 400
            else:
                data["cloud_drive_storage_root"] = ""
        if "captcha_mode" in data:
            raw_mode = str(data.get("captcha_mode") or "").strip().lower()
            if raw_mode and normalize_captcha_mode(raw_mode) != raw_mode:
                return json_resp({"ok":False,"msg":"captcha_mode 必須是 none、math、image 或 turnstile"}), 400
            data["captcha_mode"] = normalize_captcha_mode(raw_mode)
        if "password_reset_mode" in data:
            reset_mode = str(data.get("password_reset_mode") or "").strip().lower()
            if reset_mode not in {"admin_review", "email_token"}:
                return json_resp({"ok":False,"msg":"password_reset_mode 必須是 admin_review 或 email_token"}), 400
            data["password_reset_mode"] = reset_mode
        if "captcha_ttl_seconds" in data:
            try:
                ttl_seconds = int(data.get("captcha_ttl_seconds"))
            except Exception:
                return json_resp({"ok":False,"msg":"captcha_ttl_seconds 必須是 60-3600 秒"}), 400
            if ttl_seconds < 60 or ttl_seconds > 3600:
                return json_resp({"ok":False,"msg":"captcha_ttl_seconds 必須是 60-3600 秒"}), 400
            data["captcha_ttl_seconds"] = ttl_seconds
        if "video_tip_fee_percent" in data:
            fee_percent = parse_int_in_range(data.get("video_tip_fee_percent"), 0, 100)
            if fee_percent is None:
                return json_resp({"ok":False,"msg":"video_tip_fee_percent 必須是 0-100"}), 400
            data["video_tip_fee_percent"] = fee_percent
        if "video_tip_min_points" in data:
            minimum_points = parse_int_in_range(data.get("video_tip_min_points"), 1, 1_000_000)
            if minimum_points is None:
                return json_resp({"ok":False,"msg":"video_tip_min_points 必須是 1-1000000"}), 400
            data["video_tip_min_points"] = minimum_points
        if "security_log_tail_lines" in data:
            tail_lines = parse_int_in_range(data.get("security_log_tail_lines"), 1, 10_000)
            if tail_lines is None:
                return json_resp({"ok":False,"msg":"security_log_tail_lines 必須是 1-10000"}), 400
            data["security_log_tail_lines"] = tail_lines
        if "snapshot_daily_time" in data:
            if not is_hhmm(data.get("snapshot_daily_time")):
                return json_resp({"ok":False,"msg":"snapshot_daily_time 必須是 HH:MM"}), 400
            data["snapshot_daily_time"] = str(data.get("snapshot_daily_time")).strip()
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
        violations = find_feature_dependency_violations(current_settings, data)
        if violations:
            return json_resp(feature_dependency_error_payload(violations)), 400

        before_settings = dict(current_settings)
        try:
            settings = save_settings(data)
        except ValueError as exc:
            if "requires" in str(exc):
                violations = find_feature_dependency_violations(current_settings, data)
                return json_resp(feature_dependency_error_payload(violations or [{"feature": "", "feature_label": "功能", "required": "", "required_label": "父功能"}])), 400
            raise
        if not settings:
            return json_resp({"ok":False,"msg":"沒有可寫入的設定欄位"}), 400

        audit_settings_changed("SETTINGS_CHANGED", actor, before_settings, settings, scope="system_settings")
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
            audit("CLOUD_DRIVE_POLICY_UPDATED", get_client_ip(), user=actor["username"], success=True, detail=str(policy))
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
        violations = find_feature_dependency_violations(before_settings, data)
        if violations:
            return json_resp(feature_dependency_error_payload(violations)), 400
        try:
            updates = save_feature_settings(data)
        except ValueError as exc:
            if "requires" in str(exc):
                violations = find_feature_dependency_violations(before_settings, data)
                return json_resp(feature_dependency_error_payload(violations or [{"feature": "", "feature_label": "功能", "required": "", "required_label": "父功能"}])), 400
            raise
        if not updates:
            return json_resp({"ok":False,"msg":"沒有可寫入的功能開關"}), 400
        audit_settings_changed("FEATURE_FLAGS_CHANGED", actor, before_settings, updates, scope="feature_flags")
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
        before_settings = get_system_settings()
        updates = {}
        for key in ("root_ip_whitelist_enabled", "root_ip_whitelist", "browser_only_mode_enabled"):
            if key in data:
                updates[key] = data[key]
        if "root_ip_whitelist" in updates:
            normalized_whitelist, bad_entries = normalize_ip_whitelist_or_none(updates["root_ip_whitelist"])
            if bad_entries:
                return json_resp({"ok":False,"msg":f"無效的 IP / CIDR：{', '.join(bad_entries)}"}), 400
            updates["root_ip_whitelist"] = normalized_whitelist
        if parse_strict_bool(updates.get("root_ip_whitelist_enabled")) and not str(updates.get("root_ip_whitelist") or before_settings.get("root_ip_whitelist") or "").strip():
            return json_resp({"ok":False,"msg":"啟用 root IP 白名單前，至少要填入一個有效的 IP 或 CIDR"}), 400
        if "clear_maintenance_bypass_token" in data and data.get("clear_maintenance_bypass_token"):
            updates["maintenance_bypass_token_hash"] = ""
            updates["maintenance_bypass_token_expires_at"] = ""
        if "clear_internal_test_token" in data and data.get("clear_internal_test_token"):
            updates["internal_test_login_token_hash"] = ""
            updates["internal_test_login_token_expires_at"] = ""
            updates["internal_test_login_token_user_id"] = 0
            updates["internal_test_login_token_username"] = ""
        if not updates:
            return json_resp({"ok":False,"msg":"沒有可寫入的存取控制設定"}), 400
        saved = save_settings(updates)
        audit_settings_changed("ACCESS_CONTROLS_CHANGED", actor, before_settings, saved, scope="access_controls")
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
        issued_value = generate_maintenance_bypass_token()
        expires_at = maintenance_bypass_expires_at(ttl_minutes)
        before_settings = get_system_settings()
        saved = save_settings({
            "maintenance_bypass_token_hash": hash_maintenance_bypass_token(issued_value),
            "maintenance_bypass_token_expires_at": expires_at,
        })
        audit_settings_changed(
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
            "token": issued_value,
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
        target_user_id = data.get("target_user_id")
        target_username = str(data.get("target_username") or "").strip()
        resolved_user = None
        conn = get_db()
        try:
            if target_user_id not in (None, ""):
                try:
                    resolved_user = conn.execute(
                        "SELECT id, username FROM users WHERE id=? LIMIT 1",
                        (int(target_user_id),),
                    ).fetchone()
                except Exception:
                    resolved_user = None
            if not resolved_user and target_username:
                resolved_user = conn.execute(
                    "SELECT id, username FROM users WHERE LOWER(username)=LOWER(?) LIMIT 1",
                    (target_username,),
                ).fetchone()
        finally:
            conn.close()
        if not resolved_user:
            return json_resp({"ok":False,"msg":"請指定存在的綁定帳號（target_user_id 或 target_username）"}), 400
        issued_value = generate_internal_test_token()
        expires_at = maintenance_bypass_expires_at(ttl_minutes)
        before_settings = get_system_settings()
        saved = save_settings({
            "internal_test_login_token_hash": hash_internal_test_token(issued_value),
            "internal_test_login_token_expires_at": expires_at,
            "internal_test_login_token_user_id": int(resolved_user["id"]),
            "internal_test_login_token_username": str(resolved_user["username"] or "").strip(),
        })
        audit_settings_changed(
            "INTERNAL_TEST_TOKEN_ROTATED",
            actor,
            before_settings,
            saved,
            scope="internal_test_token",
            extra={"ttl_minutes": ttl_minutes, "expires_at": expires_at, "target_user_id": int(resolved_user["id"]), "target_username": str(resolved_user["username"] or "").strip()},
        )
        return json_resp({
            "ok": True,
            "msg": "內測登入 token 已更新，token 只會顯示這一次",
            "token": issued_value,
            "expires_at": expires_at,
            "ttl_minutes": ttl_minutes,
            "target_user_id": int(resolved_user["id"]),
            "target_username": str(resolved_user["username"] or "").strip(),
            "access_controls": access_control_settings_payload(get_system_settings()),
        })

    @app.route("/api/admin/member-level-rules", methods=["GET"])
    @require_csrf_safe
    def admin_member_level_rules():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        role = "super_admin" if actor["username"] == "root" else actor.get("role", "user")
        if role_rank(role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"需要管理員權限"}), 403

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
            audit("MEMBER_LEVEL_RULE_UPDATED", get_client_ip(), user=actor["username"], success=True, detail=f"level={level}, rule={rule}")
            return json_resp({"ok":True,"msg":"會員等級規則已更新","rule":rule})
        finally:
            conn.close()
