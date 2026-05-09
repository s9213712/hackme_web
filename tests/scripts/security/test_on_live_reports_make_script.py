import argparse
import json
import os
import urllib.error
from pathlib import Path

from scripts.security.gate import on_live_reports_make as helper


ROOT = Path(__file__).resolve().parents[3]

def test_root_wrapper_is_removed_and_helper_is_direct_entrypoint():
    assert not (ROOT / "on_live_reports_make.sh").exists()
    helper_source = (ROOT / "scripts" / "security" / "gate" / "on_live_reports_make.py").read_text(encoding="utf-8")
    assert 'tester="scripts/security/gate/on_live_reports_make.py"' in helper_source


def test_live_report_helper_covers_all_required_report_types_and_runtime_outputs():
    helper = (ROOT / "scripts" / "security" / "gate" / "on_live_reports_make.py").read_text(encoding="utf-8")

    assert "PRODUCTION_REQUIRED_REPORT_TYPES" in helper
    assert 'security_reports_root() / "production_gate"' in helper
    assert 'runtime/reports/security/production_gate/runs/<RUN_ID>/' in helper
    assert 'runtime/reports/security/production_gate/' in helper
    assert '"/api/root/server-mode/logs/verify"' in helper
    assert '"/api/root/integrity/report"' in helper
    assert '"/api/root/integrity/findings?status=pending"' in helper
    assert '"/api/root/integrity/findings/bulk-review"' in helper
    assert '"/api/root/production-report/upload"' in helper
    assert "run_functional_smoke.sh" in helper
    assert "run_pentest.sh" in helper
    assert "functional_permission_pentest.py" in helper
    assert "trading_stress_pentest.py" in helper
    assert "args.target_root_password" not in helper
    assert '"ROOT_PASSWORD": args.root_password' in helper
    assert '"USER_A_USERNAME": "test"' in helper
    assert '"USER_B_USERNAME": "admin"' in helper
    assert "rotate_to=args.root_new_password" in helper
    assert "rerun with --root-new-password" in helper
    assert "--server-mode-timeout" in helper
    assert '--permission-timeout' in helper
    assert "deployment_review_pending" in helper
    assert "canonical_json=_report_paths(out_root, report_type)[0]" in helper
    assert "--runtime-dir" in helper
    assert "retryable=True" in helper
    assert "client.fetch_csrf()" in helper
    assert "MODE_CONFIRM_PHRASES" in helper
    assert "functional_port" in helper
    assert '{"production", "internal_test", "test", "dev_ready"}' in helper
    assert '_switch_live_mode(client, "dev_ready", notes="go_live trading stress precheck")' in helper


def test_integrity_report_refreshes_csrf_before_mutating_calls():
    helper_source = (ROOT / "scripts" / "security" / "gate" / "on_live_reports_make.py").read_text(encoding="utf-8")

    assert "client.fetch_csrf()\n    review_status, review_payload, _ = client._request(\n        \"/api/root/integrity/findings/bulk-review\"" in helper_source
    assert "client.fetch_csrf()\n    rescan_status, rescan_payload, _ = client._request(\"/api/root/integrity/rescan\", method=\"POST\", body={})" in helper_source


def test_docs_and_frontend_expose_the_same_canonical_production_gate_paths():
    qa_docs = (ROOT / "docs" / "11_QA_TESTING.md").read_text(encoding="utf-8")
    prod_docs = (ROOT / "docs" / "02_DEPLOY_PRODUCTION.md").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert "python3 scripts/security/gate/on_live_reports_make.py --base-url https://127.0.0.1:5000 --root-password '<ROOT_PASSWORD>'" in qa_docs
    assert "python3 scripts/security/gate/on_live_reports_make.py --base-url https://<host> --root-password '<ROOT_PASSWORD>'" in prod_docs
    assert "runtime/reports/security/production_gate/log_chain_verify_report.json" in qa_docs
    assert "runtime/reports/security/production_gate/integrity_guard_report.json" in qa_docs
    assert "GET /api/root/server-mode/logs/verify" in qa_docs
    assert "`POST /api/root/integrity/rescan` + `GET /api/root/integrity/report`" in qa_docs
    assert "GET /api/root/server-mode/logs/verify" in admin_js
    assert "POST /api/root/integrity/rescan ＋ GET /api/root/integrity/report" in admin_js


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_live_client_retries_transient_get_errors(monkeypatch):
    client = helper.LiveClient("https://127.0.0.1:5002", timeout=1, max_retries=3, retry_backoff=0)
    attempts = {"count": 0}

    def fake_open(req, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.URLError("handshake timeout")
        return _FakeResponse({"ok": True, "csrf_token": "token-123"})

    monkeypatch.setattr(client.opener, "open", fake_open)
    status, payload, text = client._request("/api/csrf-token")

    assert attempts["count"] == 2
    assert status == 200
    assert payload["ok"] is True
    assert "token-123" in text


def test_resolve_output_root_prefers_runtime_dir(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "fresh-runtime"
    args = argparse.Namespace(runtime_dir=str(runtime_dir), out="")

    monkeypatch.delenv("HACKME_RUNTIME_DIR", raising=False)
    out_root = helper._resolve_output_root(args)

    assert out_root == (runtime_dir / "reports" / "security" / "production_gate").resolve()
    assert Path(os.environ["HACKME_RUNTIME_DIR"]).resolve() == runtime_dir.resolve()


def test_pick_available_port_falls_back_when_preferred_is_busy(monkeypatch):
    class _BusySocket:
        def bind(self, addr):
            raise OSError("busy")

        def close(self):
            return None

    class _FreeSocket:
        def __init__(self):
            self.bound = None

        def bind(self, addr):
            self.bound = addr

        def getsockname(self):
            return ("127.0.0.1", 54321)

        def close(self):
            return None

    sockets = [_BusySocket(), _FreeSocket()]
    monkeypatch.setattr(helper.socket, "socket", lambda *args, **kwargs: sockets.pop(0))

    chosen = helper._pick_available_port(50741)

    assert chosen == 54321


def test_make_payload_uses_meta_server_mode_by_default(tmp_path):
    captured = {}

    class _Signer:
        def build(self, **kwargs):
            captured.update(kwargs)
            return {
                "report_type": kwargs["report_type"],
                "test_result": kwargs["test_result"],
                "pass": kwargs["passed"],
                "report_hash": "sha256:" + ("a" * 64),
                "key_version": "local-dev-v1",
                "target_branch": kwargs["target_branch"],
                "target_commit": kwargs["target_commit"],
                "server_mode": kwargs["server_mode"],
                "report_source": kwargs["report_source"],
                "raw_report": kwargs["raw_report"],
            }

    payload = helper._make_payload(
        "clean_smoke",
        {
            "report_type": "clean_smoke",
            "status": "pass",
            "summary": "ok",
            "artifacts": {},
        },
        passed=True,
        tester="tests/scripts/security/test_on_live_reports_make_script.py",
        report_source="tests/scripts/security/test_on_live_reports_make_script.py",
        meta={
            "target_commit": "deadbeef",
            "target_branch": "main",
            "server_mode": "dev_ready",
        },
        canonical_json=tmp_path / "clean_smoke_report.json",
        canonical_md=tmp_path / "clean_smoke_report.md",
        signer=_Signer(),
    )

    assert captured["server_mode"] == "dev_ready"
    assert payload["server_mode"] == "dev_ready"
