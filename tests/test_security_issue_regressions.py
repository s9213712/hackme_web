from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_mutation_routes_use_single_use_csrf_guards():
    system_admin = (ROOT / "routes" / "system_admin.py").read_text(encoding="utf-8")
    auth = (ROOT / "services" / "auth.py").read_text(encoding="utf-8")

    assert '@app.route("/api/admin/security-center/thresholds", methods=["PUT"])\n    @require_csrf' in system_admin
    assert '@app.route("/api/admin/security-center/controls", methods=["PUT"])\n    @require_csrf' in system_admin
    assert 'if request.method not in {"GET", "HEAD", "OPTIONS"}:' in auth
    assert "delete_csrf_token(csrf_tok)" in auth


def test_points_spend_route_does_not_trust_client_ledger_provenance():
    economy = (ROOT / "routes" / "economy.py").read_text(encoding="utf-8")

    assert 'reference_type="price_catalog"' in economy
    assert 'reference_id=f"catalog:{item_key}"' in economy
    assert "metadata={}" in economy
    assert "_stable_spend_key" in economy


def test_avatar_admin_endpoint_uses_role_rank():
    users = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")

    assert 'role_rank(actor_role) < role_rank("manager")' in users
    assert 'actor_role not in {"admin", "super_admin"}' not in users


def test_secure_cookie_defaults_are_secure():
    server = (ROOT / "server.py").read_text(encoding="utf-8")

    assert 'FORCE_HTTPS = _env_bool("FORCE_HTTPS", default=True)' in server
    assert 'SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=True)' in server
