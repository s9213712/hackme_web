from pathlib import Path

import pytest

from services.sqlite_safe import table_columns


ROOT = Path(__file__).resolve().parents[1]


def test_admin_mutation_routes_use_single_use_csrf_guards():
    system_admin = (ROOT / "routes" / "system_admin.py").read_text(encoding="utf-8")
    auth = (ROOT / "services" / "auth.py").read_text(encoding="utf-8")

    assert '@app.route("/api/admin/security-center/thresholds", methods=["PUT"])\n    @require_csrf' in system_admin
    assert '@app.route("/api/admin/security-center/controls", methods=["PUT"])\n    @require_csrf' in system_admin
    assert 'if request.method not in {"GET", "HEAD", "OPTIONS"}:' in auth
    assert "delete_csrf_token(csrf_tok)" in auth


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


def test_root_economy_catalog_write_uses_single_use_csrf():
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")

    assert '@app.route("/api/root/economy/catalog", methods=["GET"])\n    @require_csrf_safe' in economy
    assert '@app.route("/api/root/economy/catalog", methods=["POST"])\n    @require_csrf' in economy


def test_avatar_admin_endpoint_uses_role_rank():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")

    assert 'role_rank(actor_role) < role_rank("manager")' in users
    assert 'actor_role not in {"admin", "super_admin"}' not in users


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


def test_storage_upgrade_purchase_rechecks_capacity_after_points_spend():
    files = (ROOT / "routes" / "files.py").read_text(encoding="utf-8")

    assert '_refund_storage_upgrade_spend' in files
    assert 'conn.execute("BEGIN IMMEDIATE")' in files
    assert "storage allocation failed after debit" in files
    assert files.count("can_allocate_storage_bytes(conn, storage_root, additional_bytes)") >= 2


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


def test_trading_fill_ledger_verification_uses_batch_lookup():
    trading_engine = (ROOT / "services" / "trading_engine.py").read_text(encoding="utf-8")
    verifier = trading_engine.split("def _verify_fill_ledgers", 1)[1].split("def _verify_open_order_locks", 1)[0]

    assert "ledger_by_uuid" in verifier
    assert "self._ledger_row" not in verifier
