from pathlib import Path

import pytest

from services.sqlite_safe import table_columns


ROOT = Path(__file__).resolve().parents[1]


def test_admin_mutation_routes_use_session_scoped_csrf_guards():
    system_admin = (ROOT / "routes" / "system_admin.py").read_text(encoding="utf-8")
    auth = (ROOT / "services" / "auth.py").read_text(encoding="utf-8")

    assert '@app.route("/api/admin/security-center/thresholds", methods=["PUT"])\n    @require_csrf' in system_admin
    assert '@app.route("/api/admin/security-center/controls", methods=["PUT"])\n    @require_csrf' in system_admin
    assert 'CSRF_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}' in auth
    assert "delete_csrf_token(csrf_tok)" not in auth
    assert '"error": "csrf_invalid"' in auth


def test_community_combo_mutation_routes_dispatch_to_single_use_csrf():
    community = (ROOT / "routes" / "community.py").read_text(encoding="utf-8")

    assert "def require_csrf_by_method(fn):" in community
    assert "strict = require_csrf(fn)" in community
    assert 'if request.method in {"GET", "HEAD", "OPTIONS"}:' in community
    assert community.count("@require_csrf_by_method") >= 6
    assert '@app.route("/api/community/announcements", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/categories", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/boards", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/boards/<int:board_id>/moderators", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/boards/<int:board_id>/threads", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/threads/<int:thread_id>", methods=["GET", "PUT", "DELETE"])\n    @require_csrf_by_method' in community


def test_points_spend_route_does_not_trust_client_ledger_provenance():
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")

    assert 'reference_type="price_catalog"' in economy
    assert 'reference_id=f"catalog:{item_key}"' in economy
    assert "metadata={}" in economy
    assert "_stable_spend_key" in economy
    stable_key = economy.split("def _stable_spend_key", 1)[1].split("def service_error", 1)[0]
    assert "minute_bucket" in stable_key
    assert "int(time.time() // 60)" in stable_key
    assert 'f"spend:{user_id}:{item_key}:{quantity}"' not in stable_key


def test_economy_admin_user_id_validation_does_not_leak_type_errors():
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")
    pending_route = economy.split('def admin_points_pending_rewards():', 1)[1].split(
        '@app.route("/api/admin/points/pending-rewards/<int:pending_reward_id>/review"',
        1,
    )[0]

    assert "def parse_required_user_id" in economy
    assert 'return json_resp({"ok": False, "msg": "user_id required"}), 400' in pending_route
    assert 'user_id=int(data.get("user_id"))' not in pending_route


def test_moderation_execute_claims_proposal_under_write_lock():
    moderation = (ROOT / "routes" / "moderation.py").read_text(encoding="utf-8")
    execute_route = moderation.split("def moderation_proposal_execute", 1)[1].split(
        '@app.route("/api/root/moderation/proposals/<int:proposal_id>/override"',
        1,
    )[0]

    assert 'conn.execute("BEGIN IMMEDIATE")' in execute_route
    assert "status='executing'" in execute_route
    assert execute_route.index('conn.execute("BEGIN IMMEDIATE")') < execute_route.index("refresh_proposal_vote_counts")
    assert execute_route.index("status='executing'") < execute_route.index("execute_proposal_action")


def test_root_economy_catalog_write_uses_single_use_csrf():
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")

    assert '@app.route("/api/root/economy/catalog", methods=["GET"])\n    @require_csrf_safe' in economy
    assert '@app.route("/api/root/economy/catalog", methods=["POST"])\n    @require_csrf' in economy


def test_avatar_admin_endpoint_uses_role_rank():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")
    avatar_get = users.split('def user_avatar_get(user_id):', 1)[1].split('@app.route("/api/admin/users/<int:user_id>", methods=["PUT", "DELETE"])', 1)[0]

    assert "Avatars are public identity assets inside authenticated areas" in avatar_get
    assert 'role_rank(actor_role) < role_rank("manager")' not in avatar_get
    assert 'actor_role not in {"admin", "super_admin"}' not in avatar_get


def test_admin_users_post_uses_method_aware_csrf_guard():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")

    assert "def require_csrf_by_method(fn):" in users
    assert "strict = require_csrf(fn)" in users
    assert 'if request.method in {"GET", "HEAD", "OPTIONS"}:' in users
    assert '@app.route("/api/admin/users", methods=["GET","POST"])\n    @require_csrf_by_method' in users


def test_user_demote_accepts_optional_json_body_and_frontend_sends_json():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")
    auth_users_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    demote_route = users.split('def admin_user_demote(user_id):', 1)[1].split('def admin_user_violation', 1)[0]
    demote_frontend = auth_users_js.split('async function demoteUser', 1)[1].split('// ── Module', 1)[0]

    assert 'request.get_json(silent=True) or {}' in demote_route
    assert 'request.get_json(force=True) or {}' not in demote_route
    assert '"Content-Type": "application/json"' in demote_frontend
    assert 'body: JSON.stringify({})' in demote_frontend


def test_user_promote_button_is_rendered_and_frontend_sends_json():
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")
    auth_users_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    promote_frontend = auth_users_js.split('async function promoteUser', 1)[1].split('async function updateUserMemberLevel', 1)[0]

    assert 'currentRole === "super_admin" && u.role === "user" && !isSelf' in users_js
    assert 'promoteUser(u.id, u.username)' in users_js
    assert '"Content-Type": "application/json"' in promote_frontend
    assert 'body: JSON.stringify({})' in promote_frontend


def test_manual_points_adjustment_reports_insufficient_balance():
    economy_route = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")
    adjust_frontend = economy_js.split("async function submitEconomyAdjustment", 1)[1].split("async function reviewEconomyPendingReward", 1)[0]

    assert "點數不足，無法扣除；本次調整未寫入帳本" in economy_route
    assert '"code": "insufficient_balance"' in economy_route
    assert "economyRequestId(\"admin-adjust\")" in adjust_frontend
    assert "alert(message)" in adjust_frontend


def test_member_rights_changes_send_notice_and_appeal_path():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")
    appeals = (ROOT / "routes" / "appeals.py").read_text(encoding="utf-8")
    notices = (ROOT / "services" / "sanction_notices.py").read_text(encoding="utf-8")
    violations = (ROOT / "services" / "violations.py").read_text(encoding="utf-8")

    assert "def _send_member_governance_notice" in users
    assert "governance_notice_needed = True" in users
    assert 'action_label=f"違規點數 +{points}"' in users
    assert 'action_label=f"角色 {from_role} -> {to_role}"' in users
    assert "def notify_member_points_action" in economy
    assert "會員點數權益變更" in economy
    assert "POINTS_ADMIN_ADJUST" in economy
    assert "POINTS_WALLET_SANCTION" in economy
    assert "points_ledger_uuid" in notices
    assert "points_service.rollback_ledger" in appeals
    assert 'link="/appeals"' in notices
    assert "你可以到「申覆」分頁提出申覆" in notices
    assert "violation_id = cur.lastrowid" in violations
    assert "return_violation_id=True" in users
    assert "return_violation_id=True" in economy
    assert "def _latest_violation_id" not in users
    assert "SELECT id FROM secure_violations WHERE user_id=? ORDER BY id DESC LIMIT 1" not in economy


def test_appeal_approval_rolls_back_points_before_committing_review():
    appeals = (ROOT / "routes" / "appeals.py").read_text(encoding="utf-8")
    review = appeals.split("def admin_violation_appeal_review", 1)[1].split("def ", 1)[0]

    assert "申覆點數帳本 rollback 失敗，申覆狀態尚未變更，請修復後重試" in review
    assert review.index("points_service.rollback_ledger") < review.index("UPDATE violation_appeals SET status=?")
    assert review.index("points_service.rollback_ledger") < review.index("conn.commit()")


def test_album_share_links_revoked_and_deleted_albums_not_resolved():
    storage_albums = (ROOT / "services" / "storage_albums.py").read_text(encoding="utf-8")
    files = (ROOT / "routes" / "files.py").read_text(encoding="utf-8")
    revoke = storage_albums.split("def revoke_album_share_links", 1)[1].split("def _is_album_media_storage_row", 1)[0]
    resolver = storage_albums.split("def resolve_album_share_token", 1)[1].split("def mark_album_share_link_accessed", 1)[0]

    assert 'album["deleted_at"]' not in revoke
    assert "UPDATE album_share_links SET revoked_at=?" in revoke
    assert "a.deleted_at IS NULL" in resolver
    assert "def _html_safe_json" in files
    assert "safe_token = _html_safe_json(token)" in files
    assert 'safe_token = json.dumps(str(token or ""))' not in files


def test_manual_points_adjustment_is_root_only():
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")
    adjust_route = economy.split("def admin_points_adjust():", 1)[1].split(
        '@app.route("/api/admin/points/pending-rewards"',
        1,
    )[0]

    assert "actor, err = root_or_403()" in adjust_route
    assert "actor, err = manager_or_403()" not in adjust_route


def test_storage_upgrade_purchase_rechecks_capacity_after_points_spend():
    files = (ROOT / "routes" / "files.py").read_text(encoding="utf-8")

    assert '_refund_storage_upgrade_spend' in files
    assert 'conn.execute("BEGIN IMMEDIATE")' in files
    assert "storage allocation failed after debit" in files
    assert files.count("can_allocate_storage_bytes(conn, storage_root, additional_bytes)") >= 2
    assert "會員承諾容量已達或超過 Host 可用容量，目前停用容量購買" in files
    assert '"host_storage_total_commitment_exceeds_available" in set(capacity_audit.get("reasons") or [])' in files
    assert '"host_storage_overcommitted" in set(capacity_audit.get("reasons") or [])' in files


def test_upload_records_do_not_store_client_controlled_public_mime():
    upload_security = (ROOT / "services" / "upload_security.py").read_text(encoding="utf-8")

    assert "def safe_public_mime_type(" in upload_security
    assert "UNSAFE_PUBLIC_MIME_TYPES" in upload_security
    assert "safe_public_mime_type(original_filename, mime_type)" in upload_security
    assert "None if is_e2ee else (mime_type or None)" not in upload_security


def test_secure_cookie_defaults_are_secure():
    server = (ROOT / "server.py").read_text(encoding="utf-8")

    assert 'FORCE_HTTPS = _env_bool("FORCE_HTTPS", default=True)' in server
    assert 'SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=True)' in server


def test_trading_stress_pentest_covers_margin_risk_controls():
    script = (ROOT / "security" / "trading_stress_pentest.py").read_text(encoding="utf-8")

    assert "functional_correctness" in script
    assert "abnormal_operations" in script
    assert "security_pentest" in script
    assert "traceback_leaked" in script
    assert "error_response_not_json" in script
    assert "margin long rejects below initial margin" in script
    assert "short selling rejects below initial margin" in script
    assert "margin risk exposes initial and maintenance margin" in script
    assert "margin_add_collateral" in script
    assert "initial_margin_points" in script
    assert "maintenance_margin_points" in script


def test_trading_bot_tables_are_snapshot_scoped():
    snapshots = (ROOT / "services" / "snapshots.py").read_text(encoding="utf-8")
    trading = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")

    assert '"trading_bots"' in snapshots
    assert '"trading_bot_runs"' in snapshots
    assert "CREATE TABLE IF NOT EXISTS trading_bots" in trading
    assert "CREATE TABLE IF NOT EXISTS trading_bot_runs" in trading
    assert "bot_type TEXT NOT NULL DEFAULT 'conditional'" in trading
    assert "budget_points INTEGER NOT NULL DEFAULT 0" in trading
    assert "def backtest_trading_bot" in trading


def test_table_columns_rejects_unsafe_identifiers(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "safe.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    assert table_columns(conn, "users") == {"id", "username"}
    with pytest.raises(ValueError, match="unsafe SQLite identifier"):
        table_columns(conn, 'users); SELECT * FROM sqlite_master;--')


def test_trading_write_guard_does_not_full_replay_on_every_write():
    trading_engine = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")
    guard = trading_engine.split("def _assert_writable", 1)[1].split("def _market", 1)[0]

    assert "_verify_state_on_conn" not in guard
    assert "trading.enabled" in guard


def test_trading_market_update_remains_available_in_safe_mode():
    trading_engine = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")
    update_market = trading_engine.split("def update_market", 1)[1].split("def allocate_reserve", 1)[0]

    assert "self._assert_writable(conn)" not in update_market
    assert "TRADING_MARKET_UPDATED" in update_market


def test_trading_fill_ledger_verification_uses_batch_lookup():
    trading_engine = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")
    verifier = trading_engine.split("def _verify_fill_ledgers", 1)[1].split("def _verify_open_order_locks", 1)[0]

    assert "ledger_by_uuid" in verifier
    assert "self._ledger_row" not in verifier


def test_root_margin_trading_uses_simulated_funds_not_pointschain():
    trading_engine = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")
    open_margin = trading_engine.split("def open_margin_position", 1)[1].split("def close_margin_position", 1)[0]
    close_margin = trading_engine.split("def close_margin_position", 1)[1].split("def scan_margin_liquidations", 1)[0]
    sim_verify = trading_engine.split("def _verify_sim_accounts", 1)[1].split("def _verify_margin_position_locks", 1)[0]
    margin_verify = trading_engine.split("def _verify_margin_position_locks", 1)[1].split("def _verify_spot_realized_pnl", 1)[0]

    assert "is_root_simulated = self._is_root_actor(actor)" in open_margin
    assert "self._sim_delta(conn, user_id, balance_delta=-(collateral + fee), locked_delta=collateral)" in open_margin
    assert '"funding_mode": "root_simulated"' in open_margin
    assert "is_root_simulated = self._is_root_user_id(conn, user_id)" in close_margin
    assert "simulated_return = max(0, collateral + delta)" in close_margin
    assert "self._sim_delta(conn, user_id, balance_delta=simulated_return, locked_delta=-collateral)" in close_margin
    assert "TRADING_ROOT_SIM_MARGIN_BAD_DEBT" in close_margin
    assert "FROM trading_margin_positions p" in sim_verify
    assert "u.username='root'" in sim_verify
    assert 'expected = int(position["collateral_chain_points"] or 0)' in margin_verify


def test_trading_margin_errors_are_user_readable():
    trading_routes = (ROOT / "routes" / "trading.py").read_text(encoding="utf-8")
    service_error = trading_routes.split("def service_error", 1)[1].split("def price_to_points", 1)[0]

    assert "保證金不足，至少需要" in service_error
    assert "root 模擬交易資金不足" in service_error
    assert "進階交易尚未啟用" in service_error


def test_margin_collateral_and_account_maintenance_are_supported():
    trading_engine = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")
    trading_routes = (ROOT / "routes" / "trading.py").read_text(encoding="utf-8")
    dashboard = trading_engine.split("def user_dashboard", 1)[1].split("def _is_executable", 1)[0]

    assert "maintenance_ratio_percent" in trading_engine
    assert "liquidation_price_points" in trading_engine
    assert "unrealized_pnl_points" in trading_engine
    assert "margin_long_financing_bps" in trading_engine
    assert "short_collateral_bps" in trading_engine
    assert "def _minimum_margin_collateral_points" in trading_engine
    assert "risk_reason" in trading_engine
    assert "借券放空在價格上漲時會虧損" in trading_engine
    assert "def add_margin_collateral" in trading_engine
    assert "TRADING_MARGIN_COLLATERAL_ADDED" in trading_engine
    assert '"margin_summary": self._margin_summary_payload(margin_positions)' in dashboard
    assert '@app.route("/api/trading/margin/<position_uuid>/collateral", methods=["POST"])' in trading_routes
