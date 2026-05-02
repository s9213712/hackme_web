from datetime import datetime, timedelta
from flask import request

from services.sanction_notices import restore_admin_sanction_context


def register_appeal_routes(app, deps):
    VIOLATION_APPEAL_WINDOW_HOURS = deps["VIOLATION_APPEAL_WINDOW_HOURS"]
    audit = deps["audit"]
    check_user_rate_limit = deps["check_user_rate_limit"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_latest_violation = deps["get_latest_violation"]
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_iso_to_datetime = deps["parse_iso_to_datetime"]
    parse_positive_int = deps["parse_positive_int"]
    points_service = deps.get("points_service")
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps["role_rank"]

    def _serialize_appeal_row(r):
        if not r:
            return None
        return {
            "id": r["id"],
            "user_id": r["user_id"] if "user_id" in r.keys() else None,
            "username": r["username"] if "username" in r.keys() else "",
            "latest_violation_id": r["latest_violation_id"],
            "violation_count_snapshot": r["violation_count_snapshot"],
            "penalty_points": r["penalty_points"],
            "pre_status": r["pre_status"] if ("pre_status" in r.keys()) else None,
            "pre_role": r["pre_role"] if ("pre_role" in r.keys()) else None,
            "reason": r["reason"],
            "status": r["status"],
            "reviewed_by": r["reviewed_by"],
            "reviewed_at": r["reviewed_at"],
            "review_note": r["review_note"],
            "created_at": r["created_at"],
        }

    def _serialize_violation_row(r):
        if not r:
            return None
        keys = r.keys() if hasattr(r, "keys") else {}
        return {
            "id": r["id"],
            "user_id": r["user_id"],
            "username": r["username"],
            "points": r["points"],
            "reason": r["reason"],
            "triggered_by": r["triggered_by"],
            "actor_username": r["actor_username"],
            "created_at": r["created_at"],
            "is_governance_notice": bool(r["is_governance_notice"]) if "is_governance_notice" in keys else False,
        }

    @app.route("/api/appeals", methods=["GET"])
    @require_csrf_safe
    def violation_appeals_list():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401

        conn = get_db()
        try:
            user_id = actor["id"]
            actor_username = actor["username"]
            user_row = conn.execute(
                "SELECT violation_count FROM users WHERE id=?", (user_id,)
            ).fetchone()
            latest_violation = get_latest_violation(conn, user_id)
            violation_rows = conn.execute(
                "SELECT sv.id, sv.user_id, sv.username, sv.points, sv.reason, sv.triggered_by, sv.actor_username, sv.created_at, "
                "  CASE WHEN asc2.id IS NOT NULL THEN 1 ELSE 0 END AS is_governance_notice "
                "FROM secure_violations sv "
                "LEFT JOIN admin_sanction_appeal_contexts asc2 ON asc2.violation_id = sv.id "
                "WHERE sv.user_id=? ORDER BY sv.id DESC LIMIT 50",
                (user_id,)
            ).fetchall()
            rows = conn.execute(
                "SELECT id, latest_violation_id, violation_count_snapshot, penalty_points, reason, status, reviewed_by, reviewed_at, review_note, created_at "
                "FROM violation_appeals WHERE user_id=? ORDER BY id DESC LIMIT 20",
                (user_id,)
            ).fetchall()
            appeal_by_violation = {}
            violation_ids = [row["id"] for row in violation_rows]
            if violation_ids:
                placeholders = ",".join("?" for _ in violation_ids)
                appeal_rows = conn.execute(
                    "SELECT id, latest_violation_id, violation_count_snapshot, penalty_points, reason, status, reviewed_by, reviewed_at, review_note, created_at "
                    f"FROM violation_appeals WHERE user_id=? AND latest_violation_id IN ({placeholders}) ORDER BY id DESC",
                    [user_id, *violation_ids]
                ).fetchall()
                for appeal in appeal_rows:
                    vid = appeal["latest_violation_id"]
                    if vid and vid not in appeal_by_violation:
                        appeal_by_violation[vid] = appeal

            now = datetime.now()
            latest_dt = parse_iso_to_datetime(latest_violation["created_at"]) if latest_violation else None
            remaining_seconds = 0
            latest_ok = False
            if latest_dt:
                elapsed = now - latest_dt
                if elapsed <= timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS):
                    remaining_seconds = int((timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS) - elapsed).total_seconds())
                    latest_ok = True

            pending_row = conn.execute(
                "SELECT 1 FROM violation_appeals WHERE user_id=? AND status='pending' LIMIT 1",
                (user_id,)
            ).fetchone()
            violations = []
            for row in violation_rows:
                created_dt = parse_iso_to_datetime(row["created_at"])
                row_remaining = 0
                within_window = False
                if created_dt:
                    elapsed = now - created_dt
                    if elapsed <= timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS):
                        row_remaining = int((timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS) - elapsed).total_seconds())
                        within_window = True
                appeal = appeal_by_violation.get(row["id"])
                item = _serialize_violation_row(row)
                item["remaining_seconds"] = row_remaining
                appeal_status = appeal["status"] if appeal else None
                item["is_resolved"] = appeal_status == "approved"
                item["can_appeal"] = bool(within_window and not appeal and actor_username != "root")
                item["appeal"] = _serialize_appeal_row(appeal) if appeal else None
                violations.append(item)

            return json_resp({
                "ok": True,
                "latest_violation": _serialize_violation_row(latest_violation),
                "can_appeal": bool(latest_violation and latest_ok and not pending_row and actor_username != "root"),
                "remaining_seconds": remaining_seconds,
                "violation_count": user_row["violation_count"] if user_row else 0,
                "appeals": [_serialize_appeal_row(r) for r in rows],
                "violations": violations,
            })
        finally:
            conn.close()

    @app.route("/api/appeals", methods=["POST"])
    @require_csrf
    def submit_violation_appeal():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_username = actor["username"]
        if actor_username == "root":
            return json_resp({"ok":False,"msg":"最高管理者無需申覆"}), 403

        conn = get_db()
        try:
            user_id = actor["id"]
            blocked, info = check_user_rate_limit(user_id, "appeal_submit", max_req=5, window_sec=3600)
            if blocked:
                return json_resp({"ok":False,"msg":f"申覆提交過於頻繁（每小時最多 {info['limit']} 次）"}), 429
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
            if not isinstance(data, dict):
                return json_resp({"ok":False,"msg":"Invalid request"}), 400

            violation_id = parse_positive_int(data.get("violation_id"), default=None)
            if violation_id is None:
                latest_violation = get_latest_violation(conn, user_id)
            else:
                latest_violation = conn.execute(
                    "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at "
                    "FROM secure_violations WHERE id=? AND user_id=?",
                    (violation_id, user_id)
                ).fetchone()
            if not latest_violation:
                return json_resp({"ok":False,"msg":"找不到可申覆的違規紀錄"}), 400

            latest_dt = parse_iso_to_datetime(latest_violation["created_at"])
            if not latest_dt or datetime.now() - latest_dt > timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS):
                return json_resp({"ok":False,"msg":"超過申覆時限（24 小時）"}), 409

            existing = conn.execute(
                "SELECT 1 FROM violation_appeals WHERE user_id=? AND latest_violation_id=? LIMIT 1",
                (user_id, latest_violation["id"])
            ).fetchone()
            if existing:
                return json_resp({"ok":False,"msg":"這筆違規已提交過申覆"}), 409
            reason = normalize_text(data.get("reason"))
            if not reason:
                return json_resp({"ok":False,"msg":"請填寫申覆原因"}), 400
            if len(reason) > 200:
                return json_resp({"ok":False,"msg":"申覆原因請控制在 200 字以內"}), 400

            user_row = conn.execute(
                "SELECT id, username, violation_count, status, role FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            if not user_row:
                return json_resp({"ok":False,"msg":"帳號不存在"}), 404

            conn.execute(
                "INSERT INTO violation_appeals "
                "(user_id, username, latest_violation_id, violation_count_snapshot, penalty_points, pre_status, pre_role, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    user_row["username"],
                    latest_violation["id"],
                    user_row["violation_count"],
                    latest_violation["points"],
                    user_row["status"],
                    user_row["role"],
                    reason,
                    datetime.now().isoformat()
                )
            )
            conn.commit()
            audit("VIOLATION_APPEAL_SUBMITTED", get_client_ip(), user=actor_username,
                  detail=f"user_id={user_id} latest_violation_id={latest_violation['id']}")
            return json_resp({"ok":True,"msg":"申覆已提交，等待超級管理員審核"})
        finally:
            conn.close()

    @app.route("/api/admin/appeals", methods=["GET"])
    @require_csrf_safe
    def admin_violation_appeals():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        status = normalize_text(request.args.get("status","")) or "pending"
        page = parse_positive_int(request.args.get("page", 1))
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 20), max_value=100)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = (page - 1) * limit

        conn = get_db()
        try:
            where = "WHERE 1=1"
            params = []
            if status in ("pending","approved","rejected"):
                where = "WHERE status=?"
                params.append(status)
            count_query = "SELECT COUNT(*) as c FROM violation_appeals " + where
            total = conn.execute(count_query, params).fetchone()["c"]
            rows = conn.execute(
                "SELECT id, user_id, username, latest_violation_id, violation_count_snapshot, penalty_points, pre_status, pre_role, reason, status, reviewed_by, reviewed_at, review_note, created_at "
                f"FROM violation_appeals {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
            ).fetchall()

            items = []
            for r in rows:
                items.append({
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "latest_violation_id": r["latest_violation_id"],
                    "violation_count_snapshot": r["violation_count_snapshot"],
                    "penalty_points": r["penalty_points"],
                    "pre_status": r["pre_status"],
                    "pre_role": r["pre_role"],
                    "reason": r["reason"],
                    "status": r["status"],
                    "reviewed_by": r["reviewed_by"],
                    "reviewed_at": r["reviewed_at"],
                    "review_note": r["review_note"],
                    "created_at": r["created_at"]
                })
            return json_resp({
                "ok": True,
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "status": status
            })
        finally:
            conn.close()

    @app.route("/api/admin/appeals/<int:appeal_id>/review", methods=["POST"])
    @require_csrf
    def admin_violation_appeal_review(appeal_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if actor_role != "super_admin":
            return json_resp({"ok":False,"msg":"只有最高管理者可審核申覆"}), 403

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        action = (normalize_text(data.get("action")) or "").lower()
        if action not in ("approve", "reject"):
            return json_resp({"ok":False,"msg":"action 必須是 approve 或 reject"}), 400
        note = (normalize_text(data.get("note")) or "")[:200]

        conn = get_db()
        try:
            appeal = conn.execute(
                "SELECT * FROM violation_appeals WHERE id=?", (appeal_id,)
            ).fetchone()
            if not appeal:
                return json_resp({"ok":False,"msg":"找不到申覆申請"}), 404
            if appeal["status"] != "pending":
                return json_resp({"ok":False,"msg":"申覆申請已處理"}), 409

            user_row = conn.execute(
                "SELECT id, username, status, role, violation_count FROM users WHERE id=?",
                (appeal["user_id"],)
            ).fetchone()
            if not user_row:
                return json_resp({"ok":False,"msg":"申覆帳號已不存在"}), 404

            final_status = "approved" if action == "approve" else "rejected"
            reviewed_at = datetime.now().isoformat()
            points_ledger_uuid = None
            points_rollback = None

            if action == "approve":
                context = conn.execute(
                    "SELECT points_ledger_uuid FROM admin_sanction_appeal_contexts WHERE violation_id=? AND user_id=?",
                    (appeal["latest_violation_id"], appeal["user_id"]),
                ).fetchone()
                points_ledger_uuid = context["points_ledger_uuid"] if context and context["points_ledger_uuid"] else None
                if points_ledger_uuid and points_service:
                    try:
                        points_rollback = points_service.rollback_ledger(
                            actor=actor,
                            ledger_uuid=points_ledger_uuid,
                            reason=f"appeal approved #{appeal_id}: {note or 'root approved'}",
                        )
                    except Exception as exc:
                        audit("VIOLATION_APPEAL_POINTS_ROLLBACK_FAILED", get_client_ip(), user=actor["username"], success=False,
                              detail=f"appeal_id={appeal_id} ledger_uuid={points_ledger_uuid} error={exc}")
                        return json_resp({
                            "ok": False,
                            "msg": "申覆點數帳本 rollback 失敗，申覆狀態尚未變更，請修復後重試",
                            "points_ledger_uuid": points_ledger_uuid,
                        }), 500
                penalty_points = appeal["penalty_points"] or 0
                restored_count = max(0, (appeal["violation_count_snapshot"] or 0) - (penalty_points or 0))
                restored_sanction = restore_admin_sanction_context(
                    conn,
                    user_id=appeal["user_id"],
                    violation_id=appeal["latest_violation_id"],
                )
                if restored_sanction:
                    conn.execute(
                        "UPDATE users SET violation_count=?, updated_at=? WHERE id=?",
                        (restored_count, reviewed_at, appeal["user_id"]),
                    )
                else:
                    # 申覆成立→恢復申覆前狀態
                    conn.execute(
                        "UPDATE users SET status=?, role=?, violation_count=?, blocked_until=CASE WHEN ?='active' THEN NULL ELSE blocked_until END WHERE id=?",
                        (appeal["pre_status"], appeal["pre_role"], restored_count, appeal["pre_status"], appeal["user_id"])
                    )
            else:
                # 若維持原處分，保留目前狀態，但可記錄檢閱備註
                pass

            conn.execute(
                "UPDATE violation_appeals SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                (final_status, actor["username"], reviewed_at, note, appeal_id)
            )
            conn.commit()
            audit("VIOLATION_APPEAL_REVIEWED", get_client_ip(), user=actor["username"],
                  detail=f"appeal_id={appeal_id} action={action}")
            return json_resp({"ok":True,"msg": "已核准撤銷" if action == "approve" else "已維持原處分", "points_rollback": points_rollback})
        finally:
            conn.close()
