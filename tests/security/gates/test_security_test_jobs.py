import time
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes import system_admin
from routes.system_admin import register_system_admin_routes


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


class _FakeServerModeService:
    def __init__(self):
        self.prepared = []
        self.uploaded = []

    def get_current_mode(self):
        return {"current_mode": "dev_ready"}

    def _prepare_production_report_attestation(self, **kwargs):
        self.prepared.append(kwargs)
        return {
            "ok": True,
            "report_hash": "sha256:" + ("a" * 64),
            "signature": "hmac_sha256:" + ("b" * 64),
            "key_version": "test-key-v1",
        }

    def upload_production_report(self, **kwargs):
        self.uploaded.append(kwargs)
        return {"ok": True, "report_id": f"prodrep_{len(self.uploaded)}"}


def _app(tmp_path, actor=None, server_mode_service=None):
    app = Flask(__name__)
    app.testing = True
    base_dir = tmp_path
    (base_dir / "reports").mkdir(parents=True)

    register_system_admin_routes(app, {
        "ANCHOR_DIR": str(base_dir / "anchors"),
        "BASE_DIR": str(base_dir),
        "CHAT_DIR": str(base_dir / "chats"),
        "CURRENT_SERVER_BIND_STATE": {"host": "127.0.0.1", "port": 5443, "ssl_enabled": False},
        "DB_PATH": str(base_dir / "database.db"),
        "LOG_DIR": str(base_dir / "logs"),
        "REPORTS_DIR": str(base_dir / "reports"),
        "SERVER_LOG_PATH": str(base_dir / "logs" / "server.log"),
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor or {"id": 1, "username": "root", "role": "super_admin"},
        "get_db": lambda: None,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: {},
        "get_ua": lambda: "pytest",
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": lambda data: data,
        "server_mode_service": server_mode_service,
        "snapshot_service": None,
        "verify_audit_integrity": lambda: (True, None, "ok"),
    })
    return app


class _FakeProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.returncode = 0

    def wait(self):
        self.returncode = 0
        return 0


def _wait_for_job_done(client, job_id):
    for _ in range(20):
        res = client.get(f"/api/root/security-tests/{job_id}")
        data = res.get_json()
        if data["job"]["status"] != "running":
            return data["job"]
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _sqlite_row_actor():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE actors (id INTEGER, username TEXT, role TEXT)")
    conn.execute("INSERT INTO actors VALUES (1, 'root', 'super_admin')")
    row = conn.execute("SELECT * FROM actors").fetchone()
    conn.close()
    return row


def test_root_security_job_accepts_sqlite_row_actor(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    monkeypatch.setattr(system_admin.subprocess, "Popen", _FakeProcess)
    client = _app(tmp_path, actor=_sqlite_row_actor()).test_client()

    res = client.post("/api/root/security-tests/functional", json={"port": 50741})
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert data["job"]["kind"] == "functional"
    assert job["status"] == "passed"
    assert job["log_tail"][0].startswith("$ scripts/security/pentest/run_functional_smoke.sh")


def test_root_can_start_functional_smoke_job(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    monkeypatch.setattr(system_admin.subprocess, "Popen", _FakeProcess)
    client = _app(tmp_path).test_client()

    res = client.post("/api/root/security-tests/functional", json={"port": 50741})
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert data["job"]["kind"] == "functional"
    assert job["status"] == "passed"
    assert job["progress_percent"] == 100
    assert job["log_path"].endswith(".log")
    assert job["log_tail"][0].startswith("$ scripts/security/pentest/run_functional_smoke.sh")


def test_root_can_start_privilege_job(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    commands = []
    envs = []

    class CaptureProcess(_FakeProcess):
        def __init__(self, command, **kwargs):
            commands.append(command)
            envs.append(kwargs.get("env") or {})
            super().__init__(command, **kwargs)

    monkeypatch.setattr(system_admin.subprocess, "Popen", CaptureProcess)
    monkeypatch.setenv("HTML_LEARNING_ROOT_PASSWORD", "root")
    monkeypatch.setenv("HTML_LEARNING_MANAGER_PASSWORD", "admin")
    monkeypatch.setenv("HTML_LEARNING_TEST_PASSWORD", "test")
    client = _app(tmp_path).test_client()

    res = client.post("/api/root/security-tests/privilege", json={
        "target": "https://127.0.0.1:5443",
        "destructive": True,
    })
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert data["job"]["kind"] == "privilege"
    assert job["status"] == "passed"
    assert any(item.endswith("scripts/security/pentest/functional_permission_pentest.py") for item in commands[0])
    assert "--base-url" in commands[0]
    assert "https://127.0.0.1:5443" in commands[0]
    assert "--destructive" in commands[0]
    assert envs[0]["ROOT_PASSWORD"] == "root"
    assert envs[0]["MANAGER_PASSWORD"] == "admin"
    assert envs[0]["TEST_PASSWORD"] == "test"
    assert envs[0]["PENTEST_ROOT_USERNAME"] == "root"
    assert envs[0]["PENTEST_MANAGER_USERNAME"] == "admin"
    assert envs[0]["PENTEST_USER_USERNAME"] == "test"


def test_root_can_start_pentest_job_with_authorized_target(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    commands = []
    envs = []

    class CaptureProcess(_FakeProcess):
        def __init__(self, command, **kwargs):
            commands.append(command)
            envs.append(kwargs.get("env") or {})
            super().__init__(command, **kwargs)

    monkeypatch.setattr(system_admin.subprocess, "Popen", CaptureProcess)
    client = _app(tmp_path).test_client()

    res = client.post("/api/root/security-tests/pentest", json={
        "target": "https://example.test",
        "i_own_this_target": True,
        "only": "nmap",
        "root_password": "RootSecret123!",
        "root_username": "root-checker",
        "manager_username": "manager-checker",
        "user_username": "user-checker",
    })
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert data["job"]["kind"] == "pentest"
    assert job["status"] == "passed"
    assert "--i-own-this-target" in commands[0]
    assert "nmap" in commands[0]
    assert envs[0]["ROOT_PASSWORD"] == "RootSecret123!"
    assert envs[0]["PENTEST_ROOT_USERNAME"] == "root-checker"
    assert envs[0]["PENTEST_MANAGER_USERNAME"] == "manager-checker"
    assert envs[0]["PENTEST_USER_USERNAME"] == "user-checker"


def test_root_pentest_defaults_to_quick_scan_and_server_default_credentials(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    commands = []
    envs = []

    class CaptureProcess(_FakeProcess):
        def __init__(self, command, **kwargs):
            commands.append(command)
            envs.append(kwargs.get("env") or {})
            super().__init__(command, **kwargs)

    monkeypatch.setattr(system_admin.subprocess, "Popen", CaptureProcess)
    monkeypatch.setenv("HTML_LEARNING_ROOT_PASSWORD", "root")
    monkeypatch.setenv("HTML_LEARNING_MANAGER_PASSWORD", "admin")
    monkeypatch.setenv("HTML_LEARNING_TEST_PASSWORD", "test")
    client = _app(tmp_path).test_client()

    res = client.post("/api/root/security-tests/pentest", json={
        "target": "https://example.test",
    })
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert job["status"] == "passed"
    assert "--only" in commands[0]
    assert "curl-baseline,functional-permissions,session-security,header-security" in commands[0]
    assert envs[0]["ROOT_PASSWORD"] == "root"
    assert envs[0]["MANAGER_PASSWORD"] == "admin"
    assert envs[0]["TEST_PASSWORD"] == "test"


def test_root_can_start_stress_job(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    commands = []

    class CaptureProcess(_FakeProcess):
        def __init__(self, command, **kwargs):
            commands.append(command)
            super().__init__(command, **kwargs)

    monkeypatch.setattr(system_admin.subprocess, "Popen", CaptureProcess)
    client = _app(tmp_path).test_client()

    res = client.post("/api/root/security-tests/stress", json={
        "target": "https://127.0.0.1:5443",
        "requests": 25,
        "concurrency": 5,
        "paths": "/,/api/version",
    })
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert data["job"]["kind"] == "stress"
    assert job["status"] == "passed"
    assert job["progress_percent"] == 100
    assert any(item.endswith("scripts/security/pentest/stress_test.py") for item in commands[0])
    assert "--requests" in commands[0]
    assert "25" in commands[0]
    assert "--concurrency" in commands[0]
    assert "5" in commands[0]


def test_root_can_start_duration_stress_job(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    commands = []

    class CaptureProcess(_FakeProcess):
        def __init__(self, command, **kwargs):
            commands.append(command)
            super().__init__(command, **kwargs)

    monkeypatch.setattr(system_admin.subprocess, "Popen", CaptureProcess)
    client = _app(tmp_path).test_client()

    res = client.post("/api/root/security-tests/stress", json={
        "target": "https://127.0.0.1:5443",
        "mode": "duration",
        "duration_seconds": 15,
        "max_requests": 800,
        "concurrency": 8,
        "burst_size": 20,
        "burst_interval_ms": 250,
    })
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert data["job"]["kind"] == "stress"
    assert job["status"] == "passed"
    assert "--mode" in commands[0]
    assert "duration" in commands[0]
    assert "--duration-seconds" in commands[0]
    assert "15" in commands[0]
    assert "--max-requests" in commands[0]
    assert "800" in commands[0]
    assert "--burst-size" in commands[0]
    assert "20" in commands[0]
    assert "--burst-interval-ms" in commands[0]
    assert "250" in commands[0]


def test_successful_security_job_auto_uploads_production_report(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    service = _FakeServerModeService()
    monkeypatch.setattr(system_admin.subprocess, "Popen", _FakeProcess)
    client = _app(tmp_path, server_mode_service=service).test_client()

    res = client.post("/api/root/security-tests/functional", json={"port": 50741})
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert job["status"] == "passed"
    assert job["production_report"]["ok"] is True
    assert job["production_report"]["report_type"] == "functional"
    assert service.prepared[0]["report_type"] == "functional"
    assert service.uploaded[0]["report_type"] == "functional"
    assert service.uploaded[0]["test_result"] == "pass"


def test_stress_job_does_not_upload_production_report_when_requests_fail(tmp_path, monkeypatch):
    system_admin.SECURITY_TEST_JOBS.clear()
    service = _FakeServerModeService()

    class CaptureProcess(_FakeProcess):
        def __init__(self, command, **kwargs):
            out_dir = command[command.index("--out") + 1]
            report_json = Path(out_dir) / "stress_20260508T000000Z.json"
            report_md = report_json.with_suffix(".md")
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(
                '{"failed_count": 2, "server_error_count": 0, "ok_count": 8, "requests": 10}',
                encoding="utf-8",
            )
            report_md.write_text("# stress\n", encoding="utf-8")
            super().__init__(command, **kwargs)

    monkeypatch.setattr(system_admin.subprocess, "Popen", CaptureProcess)
    client = _app(tmp_path, server_mode_service=service).test_client()

    res = client.post("/api/root/security-tests/stress", json={
        "target": "https://127.0.0.1:5443",
        "requests": 10,
        "concurrency": 2,
    })
    data = res.get_json()
    job = _wait_for_job_done(client, data["job"]["job_id"])

    assert res.status_code == 202
    assert job["status"] == "passed"
    assert job["production_report"]["ok"] is False
    assert job["production_report"]["skipped"] is True
    assert job["production_report"]["reason"] == "report_not_clean"
    assert service.uploaded == []


def test_security_test_jobs_are_root_only(tmp_path):
    system_admin.SECURITY_TEST_JOBS.clear()
    client = _app(tmp_path, actor={"id": 2, "username": "admin", "role": "manager"}).test_client()

    assert client.get("/api/root/security-tests").status_code == 403
    assert client.post("/api/root/security-tests/functional", json={"port": 50741}).status_code == 403
    assert client.post("/api/root/security-tests/privilege", json={"target": "https://127.0.0.1:5443"}).status_code == 403
    assert client.post("/api/root/security-tests/stress", json={"target": "https://127.0.0.1:5443"}).status_code == 403
