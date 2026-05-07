from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_run_prod_init_db_uses_current_bootstrap_signature():
    script = (ROOT / "one_click_setup.sh").read_text(encoding="utf-8")

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
    script = (ROOT / "one_click_setup.sh").read_text(encoding="utf-8")

    assert "printf '\\n' >&2" in script
    assert 'say "密碼至少建議 12 字元。" >&2' in script
    assert 'say "兩次輸入不一致。" >&2' in script


def test_deploy_helper_supports_skip_install_and_hint_only():
    script = (ROOT / "one_click_setup.sh").read_text(encoding="utf-8")

    assert "--skip-install" in script
    assert "--with-civitai-key" in script
    assert 'if [[ "$SKIP_INSTALL" == "1" ]]; then' in script
    assert 'append_or_replace_env "CIVITAI_API_KEY" "$CIVITAI_API_KEY_VALUE"' in script
    assert 'if [[ "$LITE_HINT" == "1" && "$ORIGINAL_ARGC" == "1" ]]; then' in script


def test_run_prod_check_reports_optional_hls_and_civitai_capabilities():
    script = (ROOT / "one_click_setup.sh").read_text(encoding="utf-8")

    assert '未找到 ffmpeg；影音平台的 HLS 衍生檔/轉檔功能將無法使用' in script
    assert '未找到 ffprobe；影音 metadata 偵測與 HLS 準備流程會失敗' in script
    assert '未設定 CIVITAI_API_KEY；root 仍可使用本地模型上傳' in script
    assert 'say "- HLS tooling: ffmpeg=${has_ffmpeg}, ffprobe=${has_ffprobe}"' in script
    assert 'say "- Civitai search/download: $([[ -n "${CIVITAI_API_KEY:-}" ]] && printf \'configured\' || printf \'disabled (missing CIVITAI_API_KEY)\')"' in script
    assert 'say "- root offline recovery: python3 scripts/admin/root_recovery.py"' in script


def test_one_click_check_runs_post_init_integrity_audit_and_points_chain_checks():
    script = (ROOT / "one_click_setup.sh").read_text(encoding="utf-8")

    assert "run_post_init_checks()" in script
    assert 'server.integrity_guard.scan(actor="one_click_setup", create_initial_manifest=True)' in script
    assert "deployment_review_pending" in script
    assert "server.verify_audit_integrity()" in script
    assert "server.points_service.verify_chain()" in script
    assert 'print("post-init runtime checks")' in script


def test_one_click_gunicorn_default_enables_local_tls_when_server_ssl_is_on():
    script = (ROOT / "one_click_setup.sh").read_text(encoding="utf-8")

    assert "prepare_tls_runtime()" in script
    assert "server.ensure_local_tls_files(server.CERT_FILE, server.KEY_FILE)" in script
    assert '--certfile "$GUNICORN_CERT_FILE"' in script
    assert '--keyfile "$GUNICORN_KEY_FILE"' in script
