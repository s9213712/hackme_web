from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_run_prod_init_db_uses_current_bootstrap_signature():
    script = (ROOT / "scripts" / "run_prod.sh").read_text(encoding="utf-8")

    assert "server.init_db(" in script
    assert "server.ensure_secure_audit_columns" in script
    assert "server.ensure_user_columns" in script
    assert "server.ensure_appeal_columns" in script
    assert "server.ensure_session_columns" in script
    assert "server.ensure_security_support_schema" in script
    assert "server.ensure_points_economy_schema" in script
    assert "server.ensure_official_chat_room" in script
    assert "server.hash_password" in script
    assert "server.ensure_trading_schema(conn)" in script
    assert "\ninit_db()\n" not in script
