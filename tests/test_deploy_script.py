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


def test_prompt_password_only_writes_secret_to_stdout():
    script = (ROOT / "scripts" / "run_prod.sh").read_text(encoding="utf-8")

    assert "printf '\\n' >&2" in script
    assert 'say "密碼至少建議 12 字元。" >&2' in script
    assert 'say "兩次輸入不一致。" >&2' in script


def test_deploy_helper_supports_skip_install_and_hint_only():
    script = (ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "--skip-install" in script
    assert 'if [[ "$SKIP_INSTALL" == "1" ]]; then' in script
    assert 'if [[ "$LITE_HINT" == "1" && "$ORIGINAL_ARGC" == "1" ]]; then' in script
