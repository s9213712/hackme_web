from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_server_entrypoint_exposes_doctor_and_fails_loudly_on_missing_runtime():
    server_py = (ROOT / "server.py").read_text(encoding="utf-8")

    assert 'parser.add_argument("--doctor", action="store_true"' in server_py
    assert "def _doctor_report():" in server_py
    assert "def _print_doctor_report(report):" in server_py
    assert "missing runtime directory:" in server_py
    assert "ENTRYPOINT_DOCTOR_MODE" in server_py
    assert "run_doctor()" in server_py
    assert "doctor: fail" in server_py


def test_dev_launcher_copies_repo_to_tmp_and_bootstraps_dev_friendly_runtime():
    script = (ROOT / "test_for_develop.sh").read_text(encoding="utf-8")

    assert 'RUN_ROOT="${RUN_ROOT:-/tmp/hackme_web_dev_' in script
    assert 'tar -C "$SOURCE_ROOT"' in script
    assert '--exclude=\'./runtime\'' in script
    assert 'HTML_LEARNING_ROOT_PASSWORD="$ROOT_PASSWORD"' in script
    assert 'HTML_LEARNING_MANAGER_PASSWORD="$MANAGER_PASSWORD"' in script
    assert 'HTML_LEARNING_TEST_PASSWORD="$TEST_PASSWORD"' in script
    assert 'HTML_LEARNING_DISABLE_DEFAULT_PASSWORD_POLICY=1' in script
    assert 'HACKME_RUNTIME_OUTPUT_CAPTURE=0 "$PYTHON_BIN" - <<\'PY\'' in script
    assert '"audit_chain_enabled": False' in script
    assert '"integrity_guard_enabled": False' in script
    assert '"production_single_ip_account_lock_enabled": False' in script
    assert '"production_single_account_ip_lock_enabled": False' in script
    assert '"ip_blocking_enabled": False' in script
    assert '"session_idle_timeout_minutes": 1440' in script
    assert "allow_risk_grade_usage=0" in script
    assert 'setsid "$PYTHON_BIN" server.py >"$LOG_CAPTURE" 2>&1 < /dev/null &' in script


def test_legacy_root_wrappers_are_removed():
    assert not (ROOT / "one_click_setup.sh").exists()
    assert not (ROOT / "on_live_reports_make.sh").exists()
    assert not (ROOT / "scripts" / "dev" / "run_tmp_server_py.sh").exists()
    assert not (ROOT / "scripts" / "dev" / "run_tmp_one_click.sh").exists()


def test_ci_workflows_call_current_script_paths():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    secrets = (ROOT / ".github" / "workflows" / "security-secrets-scan.yml").read_text(encoding="utf-8")

    assert "python scripts/prepush/pre_push_checks.py --ci" in ci
    assert "scripts/pre_push_checks.py" not in ci
    assert "python scripts/security/gate/scan_plaintext_secrets.py" in secrets
    assert "scripts/security/scan_plaintext_secrets.py" not in secrets


def test_gitignore_only_ignores_repo_root_runtime_directory():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/runtime/" in gitignore
    assert "\nruntime/\n" not in gitignore
    assert "\nstorage/\n" not in gitignore
