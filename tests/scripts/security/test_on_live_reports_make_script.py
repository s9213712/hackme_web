from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_root_wrapper_delegates_to_security_gate_helper():
    wrapper = (ROOT / "on_live_reports_make.sh").read_text(encoding="utf-8")

    assert 'exec python3 "$REPO_ROOT/scripts/security/gate/on_live_reports_make.py" "$@"' in wrapper


def test_live_report_helper_covers_all_required_report_types_and_runtime_outputs():
    helper = (ROOT / "scripts" / "security" / "gate" / "on_live_reports_make.py").read_text(encoding="utf-8")

    assert "PRODUCTION_REQUIRED_REPORT_TYPES" in helper
    assert 'security_reports_root() / "production_gate"' in helper
    assert 'runtime/reports/security/production_gate/runs/<RUN_ID>/' in helper
    assert 'runtime/reports/security/production_gate/' in helper
    assert '"/api/root/server-mode/logs/verify"' in helper
    assert '"/api/root/integrity/report"' in helper
    assert '"/api/root/production-report/upload"' in helper
    assert "run_functional_smoke.sh" in helper
    assert "run_pentest.sh" in helper
    assert "functional_permission_pentest.py" in helper
    assert "trading_stress_pentest.py" in helper


def test_docs_and_frontend_expose_the_same_canonical_production_gate_paths():
    qa_docs = (ROOT / "docs" / "11_QA_TESTING.md").read_text(encoding="utf-8")
    prod_docs = (ROOT / "docs" / "02_DEPLOY_PRODUCTION.md").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert "./on_live_reports_make.sh --base-url https://127.0.0.1:5000 --root-password '<ROOT_PASSWORD>'" in qa_docs
    assert "./on_live_reports_make.sh --base-url https://<host> --root-password '<ROOT_PASSWORD>'" in prod_docs
    assert "runtime/reports/security/production_gate/log_chain_verify_report.json" in qa_docs
    assert "runtime/reports/security/production_gate/integrity_guard_report.json" in qa_docs
    assert "GET /api/root/server-mode/logs/verify" in qa_docs
    assert "`POST /api/root/integrity/rescan` + `GET /api/root/integrity/report`" in qa_docs
    assert "GET /api/root/server-mode/logs/verify" in admin_js
    assert "POST /api/root/integrity/rescan ＋ GET /api/root/integrity/report" in admin_js
