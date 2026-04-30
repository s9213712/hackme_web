from pathlib import Path


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
