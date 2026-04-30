from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def test_admin_users_post_uses_method_aware_csrf_guard():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")

    assert "def require_csrf_by_method(fn):" in users
    assert "strict = require_csrf(fn)" in users
    assert 'if request.method in {"GET", "HEAD", "OPTIONS"}:' in users
    assert '@app.route("/api/admin/users", methods=["GET","POST"])\n    @require_csrf_by_method' in users


def test_upload_security_rejects_shell_scanner_commands():
    upload_security = (ROOT / "services" / "upload_security.py").read_text(encoding="utf-8")

    assert 'ALLOWED_CLAMAV_COMMANDS = {"clamdscan", "clamscan"}' in upload_security
    assert 'ALLOWED_YARA_COMMANDS = {"yara"}' in upload_security
    assert "shlex.split" not in upload_security
    assert '"scanner_command 僅可為 clamdscan 或 clamscan' in upload_security
    assert '"yara_command 僅可為 yara' in upload_security


def test_upload_records_do_not_store_client_controlled_public_mime():
    upload_security = (ROOT / "services" / "upload_security.py").read_text(encoding="utf-8")

    assert "def safe_public_mime_type(" in upload_security
    assert "UNSAFE_PUBLIC_MIME_TYPES" in upload_security
    assert "safe_public_mime_type(original_filename, mime_type)" in upload_security
    assert "None if is_e2ee else (mime_type or None)" not in upload_security


def test_docker_web_terminal_disallows_host_network_mode():
    web_terminal = (ROOT / "services" / "web_terminal.py").read_text(encoding="utf-8")

    assert 'DEFAULT_NETWORK_MODE = "none"' in web_terminal
    assert 'ALLOWED_NETWORK_MODES = {"none", "bridge"}' in web_terminal
    assert '"host"' not in web_terminal
