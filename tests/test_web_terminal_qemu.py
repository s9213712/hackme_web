from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes
from services.web_terminal_qemu import (
    qemu_config_from_settings,
    validate_vm_root,
)


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


class FakeWebTerminalManager:
    def __init__(self, ok=True):
        self.ok = ok
        self.created = False

    def config(self):
        return qemu_config_from_settings({
            "web_terminal_enabled": True,
            "web_terminal_qemu_storage_dir": "/var/lib/hackme-vms",
        }, base_dir="/tmp/project")

    def health(self):
        return {
            "ok": self.ok,
            "checks": [{"name": "command:virsh", "ok": self.ok, "message": "fake"}],
            "config": self.config(),
        }

    def list_sessions(self):
        return []

    def create_session(self, *, actor, ip="-", ua="-"):
        self.created = True
        if not self.ok:
            return None, "Web Terminal 環境檢查失敗"
        return {"session_id": "abc", "status": "provisioning", "vm_name": "hackme-term-u1-abcdef1234"}, None

    def get_session(self, session_id):
        return None


def _app(tmp_path, *, actor=None, manager=None):
    app = Flask(__name__)
    app.testing = True
    base_dir = tmp_path
    (base_dir / "security" / "reports").mkdir(parents=True)

    register_system_admin_routes(app, {
        "ANCHOR_DIR": str(base_dir / "anchors"),
        "BASE_DIR": str(base_dir),
        "CHAT_DIR": str(base_dir / "chats"),
        "CURRENT_SERVER_BIND_STATE": {"host": "127.0.0.1", "port": 5000, "ssl_enabled": False},
        "DB_PATH": str(base_dir / "database.db"),
        "LOG_DIR": str(base_dir / "logs"),
        "SERVER_LOG_PATH": str(base_dir / "logs" / "server.log"),
        "STORAGE_DIR": str(base_dir / "storage"),
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor or {"id": 1, "username": "root", "role": "super_admin"},
        "get_db": lambda: None,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: {},
        "get_ua": lambda: "pytest",
        "get_server_output": lambda limit=200: {"lines": [], "max_lines": 0},
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": lambda data: data,
        "server_mode_service": None,
        "snapshot_service": None,
        "verify_audit_integrity": lambda: (True, None, "ok"),
        "web_terminal_manager": manager or FakeWebTerminalManager(),
    })
    return app


def test_qemu_config_defaults_are_safe():
    config = qemu_config_from_settings({}, base_dir="/tmp/project")
    assert config["enabled"] is False
    assert config["network_mode"] == "none"
    assert config["libvirt_uri"] == "qemu:///system"
    assert config["distro"] == "ubuntu-22.04"


def test_validate_vm_root_rejects_project_path(tmp_path):
    try:
        validate_vm_root(str(tmp_path), project_base_dir=str(tmp_path))
    except ValueError as exc:
        assert "project" in str(exc)
    else:
        raise AssertionError("project root must be rejected")


def test_root_can_read_qemu_health(tmp_path):
    client = _app(tmp_path, manager=FakeWebTerminalManager(ok=True)).test_client()
    res = client.get("/api/root/web-terminal/qemu/health")
    data = res.get_json()
    assert res.status_code == 200
    assert data["ok"] is True
    assert data["health"]["checks"][0]["name"] == "command:virsh"


def test_web_terminal_qemu_is_root_only(tmp_path):
    client = _app(
        tmp_path,
        actor={"id": 2, "username": "admin", "role": "manager"},
        manager=FakeWebTerminalManager(ok=True),
    ).test_client()
    assert client.get("/api/root/web-terminal/qemu/health").status_code == 403
    assert client.get("/api/root/web-terminal/qemu/sessions").status_code == 403


def test_session_create_refuses_failed_health(tmp_path):
    manager = FakeWebTerminalManager(ok=False)
    client = _app(tmp_path, manager=manager).test_client()
    res = client.post("/api/root/web-terminal/qemu/sessions", json={})
    data = res.get_json()
    assert res.status_code == 503
    assert data["ok"] is False
