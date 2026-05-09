import json
import os
import threading
import time
from datetime import datetime
from flask import request

from services.governance.records import (
    ensure_governance_records_schema,
    record_moderation_action,
)
from services.users.member_levels import apply_member_level_change
from services.governance.moderation import (
    VOTES,
    cast_action_value,
    create_moderation_proposal,
    ensure_moderation_proposals_schema,
    governance_policy_for_action,
    proposal_row_to_dict,
    proposal_vote_state,
    refresh_proposal_vote_counts,
)

_VIOLATION_INTEGRITY_CACHE = {
    "head_id": None,
    "checked_at": 0.0,
    "payload": None,
}
_VIOLATION_INTEGRITY_CACHE_LOCK = threading.Lock()


def register_moderation_routes(app, deps):
    AUDIT_LOG_PATH = deps["AUDIT_LOG_PATH"]
    activate_emergency_lockdown = deps["activate_emergency_lockdown"]
    add_violation = deps["add_violation"]
    audit = deps["audit"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_audit_db = deps.get("get_audit_db", deps["get_db"])
    get_db = deps["get_db"]
    is_feature_enabled = deps.get("is_feature_enabled", lambda key: True)
    is_audit_chain_enabled = deps["is_audit_chain_enabled"]
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_positive_int = deps["parse_positive_int"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    revoke_user_sessions = deps.get("revoke_user_sessions", lambda user_id: 0)
    role_rank = deps["role_rank"]
    secure_add_violation = deps["secure_add_violation"]
    verify_audit_integrity = deps["verify_audit_integrity"]
    verify_violation_integrity = deps["verify_violation_integrity"]

    def ensure_community_report_schema(conn):
        post_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forum_posts' LIMIT 1"
        ).fetchone()
        thread_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forum_threads' LIMIT 1"
        ).fetchone()
        if not post_table or not thread_table:
            return False
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forum_post_reports (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id          INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
                thread_id        INTEGER NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
                reporter_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reported_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                reason           TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'pending',
                reviewed_by      TEXT,
                reviewed_at      TEXT,
                review_note      TEXT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(post_id, reason)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forum_post_reports_status ON forum_post_reports(status, created_at)")
        return True

    def actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def actor_role(actor):
        return "super_admin" if actor and actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")

    def require_moderation_governance_actor(actor):
        if not actor:
            return False, "未登入", 401
        if not is_feature_enabled("feature_member_governance_enabled"):
            return False, "會員治理功能目前已關閉", 503
        if role_rank(actor_role(actor)) < role_rank("manager"):
            return False, "權限不足", 403
        return True, "", 200

    def require_moderator_actor(actor):
        if not actor:
            return False, "未登入", 401
        if not is_feature_enabled("feature_member_governance_enabled"):
            return False, "會員治理功能目前已關閉", 503
        if role_rank(actor_role(actor)) < role_rank("moderator"):
            return False, "權限不足", 403
        return True, "", 200

    def can_govern_target(actor, target):
        if not actor or not target:
            return False
        if actor_value(actor, "username") == "root":
            return actor_value(target, "username") != "root"
        return role_rank(actor_role(target)) < role_rank(actor_role(actor))

    def proposal_payload(conn, row):
        proposal = proposal_row_to_dict(row)
        if not proposal:
            return None
        target = conn.execute("SELECT id, username, role, status, member_level FROM users WHERE id=?", (proposal["target_user_id"],)).fetchone()
        proposer = conn.execute("SELECT id, username, role FROM users WHERE id=?", (proposal["proposed_by_user_id"],)).fetchone()
        proposal["target"] = dict(target) if target else None
        proposal["proposed_by"] = dict(proposer) if proposer else None
        votes = conn.execute(
            "SELECT v.id, v.vote, v.comment, v.created_at, u.username AS voter_username "
            "FROM moderation_votes v JOIN users u ON u.id=v.voter_user_id "
            "WHERE v.proposal_id=? ORDER BY v.id ASC",
            (proposal["id"],),
        ).fetchall()
        proposal["votes"] = [dict(vote) for vote in votes]
        proposal.update(proposal_vote_state(conn, proposal))
        return proposal

    def execute_proposal_action(conn, proposal, actor):
        target = conn.execute(
            "SELECT id, username, role, status, member_level FROM users WHERE id=?",
            (proposal["target_user_id"],),
        ).fetchone()
        if not target:
            return None, "找不到目標帳號", None
        if target["username"] == "root":
            return None, "不可對 root 執行治理提案", None
        if not can_govern_target(actor, target):
            return None, "不可對同級或更高權限帳號執行治理提案", None

        action_type = proposal["action_type"]
        action_value = proposal["action_value"]
        now = datetime.now().isoformat()
        revoke_target_sessions = False
        if action_type == "warn":
            secure_add_violation(
                target["id"],
                target["username"],
                target["role"],
                1,
                proposal["reason"],
                actor_role(actor),
                actor["username"],
            )
        elif action_type == "mute":
            conn.execute("UPDATE users SET status='muted', updated_at=? WHERE id=?", (now, target["id"]))
            revoke_target_sessions = True
        elif action_type == "restrict":
            apply_member_level_change(
                conn,
                target["id"],
                actor=actor["username"],
                source="vote" if actor["username"] != "root" else "root",
                sanction_status="restricted",
                sanction_until=proposal.get("action_value") if proposal.get("action_value") else None,
                reason=proposal["reason"],
            )
            revoke_target_sessions = True
        elif action_type == "suspend":
            apply_member_level_change(
                conn,
                target["id"],
                actor=actor["username"],
                source="vote" if actor["username"] != "root" else "root",
                sanction_status="suspended",
                sanction_until=proposal.get("action_value") if proposal.get("action_value") else None,
                reason=proposal["reason"],
            )
            revoke_target_sessions = True
        elif action_type == "delete":
            conn.execute("UPDATE users SET status='deleted', deleted_at=?, updated_at=? WHERE id=?", (now, now, target["id"]))
            revoke_target_sessions = True
        elif action_type == "downgrade_level":
            apply_member_level_change(
                conn,
                target["id"],
                actor=actor["username"],
                source="vote" if actor["username"] != "root" else "root",
                base_level=action_value or "restricted",
                reason=proposal["reason"],
            )
        elif action_type == "force_password_reset":
            conn.execute("UPDATE users SET must_change_password=1, updated_at=? WHERE id=?", (now, target["id"]))
            revoke_target_sessions = True
        else:
            return None, "不支援的提案動作", None
        record_moderation_action(
            conn,
            moderator_id=actor["id"],
            action_type=action_type,
            target_type="user",
            target_id=target["id"],
            reason=proposal["reason"],
            is_auto=False,
        )
        return target, None, revoke_target_sessions

    @app.route("/api/admin/moderation-actions", methods=["GET"])
    @require_csrf_safe
    def moderation_actions():
        actor = get_current_user_ctx()
        ok, msg, status_code = require_moderator_actor(actor)
        if not ok:
            return json_resp({"ok":False,"msg":msg}), status_code
        limit = parse_positive_int(request.args.get("limit", 50), default=50, min_value=1, max_value=200)
        page = parse_positive_int(request.args.get("page", 0), default=0, min_value=0)
        if limit is None or page is None:
            return json_resp({"ok":False,"msg":"分頁參數錯誤"}), 400
        conn = get_db()
        try:
            ensure_governance_records_schema(conn)
            rows = conn.execute(
                "SELECT a.id, a.action_type, a.target_type, a.target_id, a.reason, a.is_auto, a.created_at, "
                "u.username AS moderator_username "
                "FROM moderation_actions a JOIN users u ON u.id=a.moderator_id "
                "ORDER BY a.id DESC LIMIT ? OFFSET ?",
                (limit, page * limit),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS c FROM moderation_actions").fetchone()["c"]
            return json_resp({
                "ok": True,
                "actions": [{**dict(row), "is_auto": bool(row["is_auto"])} for row in rows],
                "total": total,
                "page": page,
                "limit": limit,
            })
        finally:
            conn.close()

    @app.route("/api/admin/mod-notes/<int:user_id>", methods=["GET", "POST"])
    @require_csrf_safe
    def user_mod_notes(user_id):
        actor = get_current_user_ctx()
        ok, msg, status_code = require_moderator_actor(actor)
        if not ok:
            return json_resp({"ok":False,"msg":msg}), status_code
        conn = get_db()
        try:
            ensure_governance_records_schema(conn)
            target = conn.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            if request.method == "GET":
                rows = conn.execute(
                    "SELECT n.id, n.note, n.created_at, u.username AS moderator_username "
                    "FROM user_mod_notes n JOIN users u ON u.id=n.moderator_id "
                    "WHERE n.user_id=? ORDER BY n.id DESC LIMIT 100",
                    (user_id,),
                ).fetchall()
                return json_resp({"ok":True,"target":dict(target),"notes":[dict(row) for row in rows]})

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
            note = normalize_text(data.get("note")) if isinstance(data, dict) else ""
            if not note:
                return json_resp({"ok":False,"msg":"備註不可為空"}), 400
            conn.execute(
                "INSERT INTO user_mod_notes (moderator_id, user_id, note, created_at) VALUES (?, ?, ?, ?)",
                (actor["id"], user_id, note[:2000], datetime.now().isoformat()),
            )
            record_moderation_action(
                conn,
                moderator_id=actor["id"],
                action_type="mod_note",
                target_type="user",
                target_id=user_id,
                reason=note[:1000],
                is_auto=False,
            )
            conn.commit()
            audit("USER_MOD_NOTE_CREATED", get_client_ip(), user=actor["username"], success=True,
                  detail=f"target={target['username']}")
            return json_resp({"ok":True,"msg":"版主備註已新增"})
        finally:
            conn.close()

    @app.route("/api/account/reputation/history", methods=["GET"])
    @require_csrf_safe
    def account_reputation_history():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if not is_feature_enabled("feature_member_governance_enabled"):
            return json_resp({"ok":False,"msg":"會員治理功能目前已關閉"}), 503
        limit = parse_positive_int(request.args.get("limit", 50), default=50, min_value=1, max_value=200)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數錯誤"}), 400
        conn = get_db()
        try:
            ensure_governance_records_schema(conn)
            rows = conn.execute(
                "SELECT id, delta, reason, source_user_id, source_post_id, created_at "
                "FROM reputation_events WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (actor["id"], limit),
            ).fetchall()
            return json_resp({"ok":True,"events":[dict(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/account/reputation/summary", methods=["GET"])
    @require_csrf_safe
    def account_reputation_summary():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if not is_feature_enabled("feature_member_governance_enabled"):
            return json_resp({"ok":False,"msg":"會員治理功能目前已關閉"}), 503
        conn = get_db()
        try:
            ensure_governance_records_schema(conn)
            current = conn.execute("SELECT reputation FROM users WHERE id=?", (actor["id"],)).fetchone()
            totals = conn.execute(
                "SELECT "
                "COALESCE(SUM(delta), 0) AS total_delta, "
                "COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-30 days') THEN delta ELSE 0 END), 0) AS last_30_days, "
                "COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-365 days') THEN delta ELSE 0 END), 0) AS last_365_days "
                "FROM reputation_events WHERE user_id=?",
                (actor["id"],),
            ).fetchone()
            return json_resp({
                "ok": True,
                "summary": {
                    "current_reputation": int(current["reputation"] or 0) if current else 0,
                    "total_delta": int(totals["total_delta"] or 0),
                    "last_30_days": int(totals["last_30_days"] or 0),
                    "last_365_days": int(totals["last_365_days"] or 0),
                }
            })
        finally:
            conn.close()

    @app.route("/api/admin/moderation/proposals", methods=["GET", "POST"])
    @require_csrf_safe
    def moderation_proposals():
        actor = get_current_user_ctx()
        ok, msg, status_code = require_moderation_governance_actor(actor)
        if not ok:
            return json_resp({"ok":False,"msg":msg}), status_code

        conn = get_db()
        try:
            ensure_moderation_proposals_schema(conn)
            if request.method == "GET":
                status_filter = normalize_text(request.args.get("status")) or ""
                params = []
                where = "1=1"
                if status_filter:
                    where += " AND status=?"
                    params.append(status_filter)
                rows = conn.execute(
                    f"SELECT * FROM moderation_proposals WHERE {where} ORDER BY id DESC LIMIT 100",
                    tuple(params),
                ).fetchall()
                return json_resp({"ok":True,"proposals":[proposal_payload(conn, row) for row in rows]})

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
            if not isinstance(data, dict):
                return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
            target_user_id = data.get("target_user_id")
            action_type = normalize_text(data.get("action_type"))
            action_value = cast_action_value(data.get("action_value"))
            target = conn.execute("SELECT id, username, role FROM users WHERE id=?", (target_user_id,)).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到目標帳號"}), 404
            if int(target["id"]) == int(actor["id"]):
                return json_resp({"ok":False,"msg":"不可對自己建立治理提案"}), 403
            if target["username"] == "root":
                return json_resp({"ok":False,"msg":"不可對 root 建立治理提案"}), 403
            if not can_govern_target(actor, target):
                return json_resp({"ok":False,"msg":"不可對同級或更高權限帳號建立治理提案"}), 403
            policy = governance_policy_for_action(action_type, target["role"])
            proposal, err = create_moderation_proposal(
                conn,
                target_user_id=target["id"],
                action_type=action_type,
                action_value=action_value,
                proposed_by_user_id=actor["id"],
                reason=normalize_text(data.get("reason")),
                required_votes=policy["required_votes"],
                risk_level=policy["risk_level"],
                required_root_approval=policy["required_root_approval"],
                required_manager_approvals=policy["required_manager_approvals"],
                ttl_hours=data.get("ttl_hours", 72),
            )
            if err:
                return json_resp({"ok":False,"msg":err}), 400
            conn.commit()
            audit("MODERATION_PROPOSAL_CREATED", get_client_ip(), user=actor["username"], success=True,
                  detail=f"proposal_id={proposal['id']},target={target['username']},action={action_type},risk={proposal.get('risk_level')}")
            return json_resp({"ok":True,"msg":"治理提案已建立","proposal":proposal_payload(conn, conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal["id"],)).fetchone())})
        finally:
            conn.close()

    @app.route("/api/admin/moderation/proposals/<int:proposal_id>", methods=["GET"])
    @require_csrf_safe
    def moderation_proposal_detail(proposal_id):
        actor = get_current_user_ctx()
        ok, msg, status_code = require_moderation_governance_actor(actor)
        if not ok:
            return json_resp({"ok":False,"msg":msg}), status_code
        conn = get_db()
        try:
            ensure_moderation_proposals_schema(conn)
            row = conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not row:
                return json_resp({"ok":False,"msg":"找不到治理提案"}), 404
            return json_resp({"ok":True,"proposal":proposal_payload(conn, row)})
        finally:
            conn.close()

    @app.route("/api/admin/moderation/proposals/<int:proposal_id>/vote", methods=["POST"])
    @require_csrf
    def moderation_proposal_vote(proposal_id):
        actor = get_current_user_ctx()
        ok, msg, status_code = require_moderation_governance_actor(actor)
        if not ok:
            return json_resp({"ok":False,"msg":msg}), status_code
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        vote = normalize_text(data.get("vote")) if isinstance(data, dict) else ""
        if vote not in VOTES:
            return json_resp({"ok":False,"msg":"投票值錯誤"}), 400

        conn = get_db()
        try:
            ensure_moderation_proposals_schema(conn)
            proposal = conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not proposal:
                return json_resp({"ok":False,"msg":"找不到治理提案"}), 404
            proposal = refresh_proposal_vote_counts(conn, proposal_id)
            if proposal["status"] != "pending":
                conn.commit()
                return json_resp({"ok":False,"msg":"此提案目前不可投票","status":proposal["status"]}), 409
            if int(proposal.get("proposed_by_user_id") or 0) == int(actor["id"]):
                conn.commit()
                return json_resp({"ok":False,"msg":"提案者不可投票"}), 403
            if int(proposal.get("target_user_id") or 0) == int(actor["id"]):
                conn.commit()
                return json_resp({"ok":False,"msg":"治理對象不可投票"}), 403
            try:
                conn.execute(
                    "INSERT INTO moderation_votes (proposal_id, voter_user_id, vote, comment, created_at) VALUES (?, ?, ?, ?, ?)",
                    (proposal_id, actor["id"], vote, normalize_text(data.get("comment"))[:500], datetime.now().isoformat()),
                )
            except Exception:
                return json_resp({"ok":False,"msg":"同一管理員不可重複投票"}), 409
            proposal = refresh_proposal_vote_counts(conn, proposal_id)
            conn.commit()
            audit("MODERATION_PROPOSAL_VOTED", get_client_ip(), user=actor["username"], success=True,
                  detail=f"proposal_id={proposal_id},vote={vote},status={proposal['status']}")
            return json_resp({"ok":True,"msg":"已完成投票","proposal":proposal_payload(conn, conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone())})
        finally:
            conn.close()

    @app.route("/api/admin/moderation/proposals/<int:proposal_id>/execute", methods=["POST"])
    @require_csrf
    def moderation_proposal_execute(proposal_id):
        actor = get_current_user_ctx()
        ok, msg, status_code = require_moderation_governance_actor(actor)
        if not ok:
            return json_resp({"ok":False,"msg":msg}), status_code
        conn = get_db()
        revoke_target_sessions = False
        target = None
        try:
            ensure_moderation_proposals_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            proposal = refresh_proposal_vote_counts(conn, proposal_id)
            if not proposal:
                conn.rollback()
                return json_resp({"ok":False,"msg":"找不到治理提案"}), 404
            if proposal["status"] != "approved":
                conn.rollback()
                return json_resp({"ok":False,"msg":"提案通過後才可執行","status":proposal["status"]}), 409
            if proposal.get("risk_level") == "high" and actor["username"] != "root":
                conn.rollback()
                return json_resp({"ok":False,"msg":"高風險治理提案通過後仍必須由 root 執行"}), 403
            if int(proposal.get("target_user_id") or 0) == int(actor["id"]):
                conn.rollback()
                return json_resp({"ok":False,"msg":"治理對象不可執行自己的提案"}), 403
            now = datetime.now().isoformat()
            conn.execute("UPDATE moderation_proposals SET status='executing', updated_at=? WHERE id=?", (now, proposal_id))
            conn.commit()
            target, err, revoke_target_sessions = execute_proposal_action(conn, proposal, actor)
            if err:
                rollback_now = datetime.now().isoformat()
                conn.execute("UPDATE moderation_proposals SET status='approved', updated_at=? WHERE id=?", (rollback_now, proposal_id))
                conn.commit()
                return json_resp({"ok":False,"msg":err}), 400
            now = datetime.now().isoformat()
            conn.execute("UPDATE moderation_proposals SET status='executed', executed_at=?, updated_at=? WHERE id=?", (now, now, proposal_id))
            conn.commit()
            if revoke_target_sessions:
                revoke_user_sessions(target["id"])
            audit("MODERATION_PROPOSAL_EXECUTED", get_client_ip(), user=actor["username"], success=True,
                  detail=f"proposal_id={proposal_id},target={target['username']},action={proposal['action_type']}")
            return json_resp({"ok":True,"msg":"治理提案已執行","proposal_id":proposal_id})
        finally:
            conn.close()

    @app.route("/api/root/moderation/proposals/<int:proposal_id>/override", methods=["POST"])
    @require_csrf
    def root_moderation_proposal_override(proposal_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可 override 治理提案"}), 403
        if not is_feature_enabled("feature_member_governance_enabled"):
            return json_resp({"ok":False,"msg":"會員治理功能目前已關閉"}), 503

        conn = get_db()
        revoke_target_sessions = False
        target = None
        try:
            ensure_moderation_proposals_schema(conn)
            proposal = conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not proposal:
                return json_resp({"ok":False,"msg":"找不到治理提案"}), 404
            proposal = proposal_row_to_dict(proposal)
            if proposal["status"] == "executed":
                return json_resp({"ok":False,"msg":"提案已執行"}), 409
            conn.commit()
            audit("MODERATION_PROPOSAL_ROOT_OVERRIDE_BLOCKED", get_client_ip(), user=actor["username"], success=False,
                  detail=f"proposal_id={proposal_id},action={proposal['action_type']}")
            return json_resp({"ok":False,"msg":"root 不可跳過治理投票；請在提案中投同意票，並等待必要管理者同意"}), 403
        finally:
            conn.close()

    # ── 查詢所有違規記錄（可驗證 integrity）──────────────────────────────────────
    @app.route("/api/admin/violations", methods=["GET"])
    @require_csrf_safe
    def admin_violations():
        """列出所有用戶的最新違規狀態 + integrity 驗證結果"""
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        page = parse_positive_int(request.args.get("page", 0), min_value=0)
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 50), max_value=200)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = page * limit
        username_filter = request.args.get("username", "").strip() or None

        conn = get_db()
        try:
            users_all = conn.execute(
                "SELECT username, violation_count FROM users WHERE username<>'root' ORDER BY id ASC"
            ).fetchall()
            where = "WHERE username<>'root'"
            params = []
            if username_filter:
                where += " AND username=?"
                params.append(username_filter)
            total = conn.execute(
                f"SELECT COUNT(*) as c FROM secure_violations {where}",
                tuple(params)
            ).fetchone()["c"]
            rows = conn.execute(
                "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at, entry_hash "
                f"FROM secure_violations {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                tuple(params + [limit, offset])
            ).fetchall()
            result = [{
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "points": r["points"],
                "reason": r["reason"],
                "triggered_by": r["triggered_by"],
                "actor": r["actor_username"],
                "timestamp": r["created_at"],
                "created_at": r["created_at"],
                "chain_hash": r["entry_hash"][:32] + "...",
                "_chain_hash": r["entry_hash"],
            } for r in rows]

            integrity_ok = True
            integrity_broken = None
            integrity_details = "no entries"
            if username_filter:
                target = conn.execute(
                    "SELECT id FROM users WHERE username=?", (username_filter,)
                ).fetchone()
                if target:
                    integrity_ok, integrity_broken, integrity_details = verify_violation_integrity(target["id"])
            else:
                head_row = conn.execute("SELECT MAX(id) AS head_id FROM secure_violations").fetchone()
                head_id = head_row["head_id"] if head_row else None
                cached = None
                with _VIOLATION_INTEGRITY_CACHE_LOCK:
                    if (
                        _VIOLATION_INTEGRITY_CACHE["payload"] is not None
                        and _VIOLATION_INTEGRITY_CACHE["head_id"] == head_id
                        and time.monotonic() - _VIOLATION_INTEGRITY_CACHE["checked_at"] < 300
                    ):
                        cached = dict(_VIOLATION_INTEGRITY_CACHE["payload"])
                if cached is None:
                    cached = {"ok": True, "broken_at": None, "details": "integrity OK"}
                    for u in conn.execute("SELECT id FROM users WHERE username<>'root' ORDER BY id ASC").fetchall():
                        ok, broken_at, details = verify_violation_integrity(u["id"])
                        if not ok:
                            cached = {"ok": False, "broken_at": broken_at, "details": details}
                            break
                    with _VIOLATION_INTEGRITY_CACHE_LOCK:
                        _VIOLATION_INTEGRITY_CACHE.update({
                            "head_id": head_id,
                            "checked_at": time.monotonic(),
                            "payload": dict(cached),
                        })
                integrity_ok = cached["ok"]
                integrity_broken = cached["broken_at"]
                integrity_details = cached["details"]

            return json_resp({
                "ok":      True,
                "entries": result,
                "total":   total,
                "page":    page,
                "limit":   limit,
                "users":   [{"username": u["username"], "violation_count": u["violation_count"]} for u in users_all],
                "integrity": {
                    "ok":        integrity_ok,
                    "broken_at": integrity_broken,
                    "details":   integrity_details,
                }
            })
        finally:
            conn.close()

    # ── 重置單一用戶違規計次（super_admin only）────────────────────────────────────
    @app.route("/api/admin/users/<int:user_id>/reset-violations", methods=["POST"])
    @require_csrf
    def admin_reset_violations(user_id):
        """超級管理者將用戶違規歸零"""
        actor = get_current_user_ctx()
        if not actor or actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有最高管理者可執行此操作"}), 403

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role, violation_count FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404

            secure_add_violation(
                user_id,
                target["username"],
                target["role"],
                0,
                f"violations_reset by {actor['username']} (previous: {target['violation_count']})",
                "super_admin",
                actor["username"],
                update_user_counter=False,
            )
            conn.execute("UPDATE users SET violation_count=0 WHERE id=?", (user_id,))
            conn.commit()
            audit("VIOLATIONS_RESET", get_client_ip(), user=actor["username"],
                  detail=f"target_id={user_id} previous_count={target['violation_count']}")
            return json_resp({"ok":True,"msg":f"已重置 {target['username']} 的違規計次"})
        finally:
            conn.close()

    # ── 審計日誌（僅 root 可檢視）────────────────────────────────
    @app.route("/api/admin/audit", methods=["GET"])
    @require_csrf_safe
    def admin_audit():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可檢視審計紀錄"}), 403

        page = parse_positive_int(request.args.get("page", 0), min_value=0)
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 50), max_value=200)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = page * limit

        # 讀取 secure_audit 表（hash chain）
        conn = get_audit_db()
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM secure_audit").fetchone()["c"]
            rows  = conn.execute(
                "SELECT id, ts, action, ip, user, success, ua, detail, chain_hash "
                "FROM secure_audit ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            entries = []
            for r in rows:
                entries.append({
                    "id":        r["id"],
                    "ts":        r["ts"],
                    "timestamp": r["ts"],
                    "action":    r["action"],
                    "actor":     r["user"],
                    "ip":        r["ip"],
                    "user":      r["user"],
                    "success":   bool(r["success"]),
                    "ua":        r["ua"],
                    "detail":    r["detail"],
                    "details":   r["detail"],
                    "chain_hash": r["chain_hash"][:32] + "...",  # 只顯示前 32 字符
                    "_chain_hash": r["chain_hash"],
                })

            # Legacy fallback：audit.log JSONL（避免 table 還沒同步時前端顯示空白）
            if total == 0 and not entries:
                if os.path.exists(AUDIT_LOG_PATH):
                    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                        raw_lines = [ln.strip() for ln in f if ln.strip()]
                    normalized_lines = list(reversed(raw_lines))
                    page_lines = normalized_lines[offset:offset + limit]
                    for idx, line in enumerate(page_lines):
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        entries.append({
                            "id":            total + idx + 1,
                            "ts":            obj.get("ts", ""),
                            "timestamp":     obj.get("ts", ""),
                            "action":        obj.get("action", ""),
                            "actor":         obj.get("user", ""),
                            "ip":            obj.get("ip", ""),
                            "user":          obj.get("user", ""),
                            "success":       bool(obj.get("success", False)),
                            "ua":            obj.get("ua", ""),
                            "detail":        obj.get("detail", ""),
                            "details":       obj.get("detail", ""),
                            "chain_hash":    "",
                            "_chain_hash":    "",
                            "source":        "legacy_log",
                        })
                    total = len(raw_lines)

            # Integrity 驗證
            if is_audit_chain_enabled():
                ok, broken_at, details = verify_audit_integrity()
                integrity = {
                    "enabled": True,
                    "ok": ok,
                    "broken_at": broken_at,
                    "details": details,
                    "operator_action_required": ok is False,
                    "auto_lockdown_applied": False,
                }
            else:
                integrity = {
                    "enabled": False,
                    "ok": None,
                    "broken_at": None,
                    "details": "audit chain disabled",
                    "operator_action_required": False,
                    "auto_lockdown_applied": False,
                }

            return json_resp({
                "ok": True,
                "entries": entries,
                "total": total,
                "page": page,
                "limit": limit,
                "integrity": integrity
            })
        finally:
            conn.close()

    @app.route("/api/admin/message-reports", methods=["GET"])
    @require_csrf_safe
    def admin_message_reports():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可審核檢舉"}), 403
        status = normalize_text(request.args.get("status")) or "pending"
        if status not in ("pending", "approved", "rejected"):
            return json_resp({"ok":False,"msg":"狀態參數錯誤"}), 400
        page = parse_positive_int(request.args.get("page", 0), min_value=0)
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 30), min_value=1, max_value=100)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = page * limit

        conn = get_db()
        try:
            has_community_reports = ensure_community_report_schema(conn)
            chat_total = conn.execute(
                "SELECT COUNT(*) AS c FROM chat_message_reports WHERE status=?", (status,)
            ).fetchone()["c"]
            community_total = 0
            chat_rows = conn.execute(
                "SELECT r.id, r.message_id, r.room_id, r.reason, r.status, r.reviewed_by, r.reviewed_at, r.review_note, r.created_at, "
                "reporter.username AS reporter_username, reported.username AS reported_username, m.content "
                "FROM chat_message_reports r "
                "LEFT JOIN users reporter ON reporter.id=r.reporter_user_id "
                "LEFT JOIN users reported ON reported.id=r.reported_user_id "
                "LEFT JOIN chat_messages m ON m.id=r.message_id "
                "WHERE r.status=? ORDER BY r.id DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
            community_rows = []
            if has_community_reports:
                community_total = conn.execute(
                    "SELECT COUNT(*) AS c FROM forum_post_reports WHERE status=?", (status,)
                ).fetchone()["c"]
                community_rows = conn.execute(
                    "SELECT r.id, r.post_id, r.thread_id, r.reason, r.status, r.reviewed_by, r.reviewed_at, r.review_note, r.created_at, "
                    "reporter.username AS reporter_username, reported.username AS reported_username, p.content "
                    "FROM forum_post_reports r "
                    "LEFT JOIN users reporter ON reporter.id=r.reporter_user_id "
                    "LEFT JOIN users reported ON reported.id=r.reported_user_id "
                    "LEFT JOIN forum_posts p ON p.id=r.post_id "
                    "WHERE r.status=? ORDER BY r.id DESC LIMIT ? OFFSET ?",
                    (status, limit, offset)
                ).fetchall()
            items = [{
                "kind": "chat",
                "id": r["id"],
                "message_id": r["message_id"],
                "room_id": r["room_id"],
                "reason": r["reason"],
                "status": r["status"],
                "reporter_username": r["reporter_username"] or "",
                "reported_username": r["reported_username"] or "",
                "content": r["content"] or "",
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"],
                "review_note": r["review_note"],
                "created_at": r["created_at"],
            } for r in chat_rows]
            items.extend({
                "kind": "community_post",
                "id": r["id"],
                "message_id": r["post_id"],
                "room_id": r["thread_id"],
                "reason": r["reason"],
                "status": r["status"],
                "reporter_username": r["reporter_username"] or "system",
                "reported_username": r["reported_username"] or "",
                "content": r["content"] or "",
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"],
                "review_note": r["review_note"],
                "created_at": r["created_at"],
            } for r in community_rows)
            items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
            items = items[:limit]
            return json_resp({
                "ok": True,
                "total": chat_total + community_total,
                "page": page,
                "limit": limit,
                "items": items
            })
        finally:
            conn.close()

    @app.route("/api/admin/message-reports/<int:report_id>/review", methods=["POST"])
    @require_csrf
    def admin_message_report_review(report_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可審核檢舉"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        action = normalize_text(data.get("action"))
        note = normalize_text(data.get("note"))
        if action not in ("approve", "reject"):
            return json_resp({"ok":False,"msg":"審核動作錯誤"}), 400

        conn = get_db()
        try:
            report = conn.execute(
                "SELECT r.*, u.username AS reported_username, u.role AS reported_role "
                "FROM chat_message_reports r LEFT JOIN users u ON u.id=r.reported_user_id WHERE r.id=?",
                (report_id,)
            ).fetchone()
            if not report:
                return json_resp({"ok":False,"msg":"找不到檢舉"}), 404
            if report["status"] != "pending":
                return json_resp({"ok":False,"msg":"此檢舉已審核"}), 409
            final_status = "approved" if action == "approve" else "rejected"
            reviewed_at = datetime.now().isoformat()
            msg = "已駁回檢舉"
            if action == "approve":
                role = "super_admin" if report["reported_username"] == "root" else (report["reported_role"] or "user")
                _, msg, _ = add_violation(
                    report["reported_user_id"], report["reported_username"], role, points=1,
                    reason=f"訊息檢舉成立：{report['reason']}", triggered_by="message_report", actor_username=actor["username"]
                )
            conn.execute(
                "UPDATE chat_message_reports SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                (final_status, actor["username"], reviewed_at, note, report_id)
            )
            conn.commit()
            audit("CHAT_MESSAGE_REPORT_REVIEWED", get_client_ip(), user=actor["username"],
                  detail=f"report_id={report_id},action={action},reported={report['reported_username']}")
            return json_resp({"ok":True,"msg":msg})
        finally:
            conn.close()

    @app.route("/api/admin/community-post-reports/<int:report_id>/review", methods=["POST"])
    @require_csrf
    def admin_community_post_report_review(report_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可審核檢舉"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        action = normalize_text(data.get("action"))
        note = normalize_text(data.get("note"))
        if action not in ("approve", "reject"):
            return json_resp({"ok":False,"msg":"審核動作錯誤"}), 400

        conn = get_db()
        try:
            if not ensure_community_report_schema(conn):
                return json_resp({"ok":False,"msg":"找不到社群留言檢舉"}), 404
            report = conn.execute(
                "SELECT r.*, u.username AS reported_username, u.role AS reported_role "
                "FROM forum_post_reports r LEFT JOIN users u ON u.id=r.reported_user_id WHERE r.id=?",
                (report_id,)
            ).fetchone()
            if not report:
                return json_resp({"ok":False,"msg":"找不到檢舉"}), 404
            if report["status"] != "pending":
                return json_resp({"ok":False,"msg":"此檢舉已審核"}), 409
            final_status = "approved" if action == "approve" else "rejected"
            reviewed_at = datetime.now().isoformat()
            msg = "已駁回檢舉，留言已恢復顯示"
            if action == "approve":
                role = "super_admin" if report["reported_username"] == "root" else (report["reported_role"] or "user")
                _, msg, _ = add_violation(
                    report["reported_user_id"], report["reported_username"], role, points=1,
                    reason=f"社群留言檢舉成立：{report['reason']}", triggered_by="community_post_report", actor_username=actor["username"]
                )
            else:
                conn.execute(
                    "UPDATE forum_posts SET is_hidden=0, hidden_reason=NULL, updated_at=? WHERE id=?",
                    (reviewed_at, report["post_id"])
                )
            conn.execute(
                "UPDATE forum_post_reports SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                (final_status, actor["username"], reviewed_at, note, report_id)
            )
            conn.commit()
            audit("COMMUNITY_POST_REPORT_REVIEWED", get_client_ip(), user=actor["username"],
                  detail=f"report_id={report_id},action={action},reported={report['reported_username']}")
            return json_resp({"ok":True,"msg":msg})
        finally:
            conn.close()
