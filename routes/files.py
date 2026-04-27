from services.upload_security import (
    get_cloud_drive_safety_summary,
    get_cloud_drive_security_policy,
    get_user_cloud_drive_usage,
)


def register_file_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_member_level_rule = deps["get_member_level_rule"]
    json_resp = deps["json_resp"]
    require_csrf_safe = deps["require_csrf_safe"]

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入"}, 401)
        return actor, None

    @app.route("/api/files/quota", methods=["GET"])
    @require_csrf_safe
    def file_quota():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=rule)
            return json_resp({"ok": True, "quota": usage})
        finally:
            conn.close()

    @app.route("/api/files/security-policy", methods=["GET"])
    @require_csrf_safe
    def file_security_policy():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            summary = get_cloud_drive_safety_summary(conn, actor, member_rule=rule)
            return json_resp({"ok": True, "security": summary})
        finally:
            conn.close()

    @app.route("/api/files/privacy-modes", methods=["GET"])
    @require_csrf_safe
    def file_privacy_modes():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            policy = get_cloud_drive_security_policy(conn)
            return json_resp({
                "ok": True,
                "modes": {
                    "public_attachment": {
                        "label": "公開附件",
                        "server_can_read": True,
                        "server_scan": "required",
                        "e2ee": False,
                        "warning": "請勿上傳需要端到端保密的資料。",
                    },
                    "private_scannable": {
                        "label": "私密可掃描",
                        "server_can_read": "temporary_for_scan",
                        "server_scan": "required",
                        "e2ee": False,
                        "warning": "提供伺服器端掃毒與加密保存，但不是端到端加密。",
                    },
                    "e2ee_vault": {
                        "label": "端到端加密保險庫",
                        "server_can_read": False,
                        "server_scan": "metadata_only",
                        "e2ee": True,
                        "warning": "站方無法讀取內容，也無法完整掃毒；遺失金鑰可能無法救回。",
                    },
                    "e2ee_vault_with_client_scan": {
                        "label": "E2EE + 本機檢查",
                        "server_can_read": False,
                        "server_scan": "client_report_untrusted",
                        "e2ee": True,
                        "warning": "本機掃描回報不可完全信任，伺服器仍無法驗證全部內容。",
                    },
                },
                "policy": policy,
            })
        finally:
            conn.close()
