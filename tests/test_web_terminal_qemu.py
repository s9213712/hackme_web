from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes
from services.web_terminal_qemu import (
    LibvirtQemuProvider,
    TerminalSession,
    _hypervisor_can_probably_read,
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
            "summary": "fake ok" if self.ok else "fake failed",
            "failed_checks": [] if self.ok else ["command:virsh"],
            "checks": [{
                "name": "command:virsh",
                "label": "virsh 指令",
                "ok": self.ok,
                "message": "fake",
                "why": "fake why",
                "repair": "" if self.ok else "fake repair",
            }],
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


def test_qemu_config_accepts_legacy_docker_keys_for_migration():
    config = qemu_config_from_settings({
        "web_terminal_enabled": True,
        "web_terminal_distribution": "ubuntu-24.04",
        "web_terminal_network_mode": "bridge",
    }, base_dir="/tmp/project")

    assert config["enabled"] is True
    assert config["distro"] == "ubuntu-24.04"
    assert config["network_mode"] == "nat"


def test_qemu_config_accepts_user_mode_network_alias():
    config = qemu_config_from_settings({
        "web_terminal_enabled": True,
        "web_terminal_qemu_network_mode": "slirp",
    }, base_dir="/tmp/project")

    assert config["network_mode"] == "user"


def test_user_mode_virt_install_adds_ssh_host_forward():
    class CaptureProvider(LibvirtQemuProvider):
        def __init__(self):
            super().__init__()
            self.last_args = []

        def run(self, args, timeout=None):
            self.last_args = args
            return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    provider = CaptureProvider()
    session = TerminalSession(
        session_id="sid",
        user_id=1,
        username="root",
        vm_name="hackme-term-u1-abcdef1234",
        disk_path="/tmp/disk.qcow2",
        network_mode="user",
        host_ssh_port=22222,
    )

    provider.virt_install(session=session, seed_iso="/tmp/seed.iso", os_variant="ubuntu24.04")

    network_arg = provider.last_args[provider.last_args.index("--network") + 1]
    assert "type=user" in network_arg
    assert "xpath1.set=./portForward/@proto=tcp" in network_arg
    assert "xpath2.set=./portForward/@address=127.0.0.1" in network_arg
    assert "xpath4.set=./portForward/range/@start=22222" in network_arg
    assert "xpath5.set=./portForward/range/@to=22" in network_arg


def test_overlay_disk_uses_unsafe_backing_reference_for_hypervisor_owned_images():
    class CaptureProvider(LibvirtQemuProvider):
        def __init__(self):
            super().__init__()
            self.calls = []

        def run(self, args, timeout=None, input_text=None):
            self.calls.append(list(args))
            return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    provider = CaptureProvider()
    provider.create_overlay_disk(base_image="/var/lib/hackme-vms/base/noble.img", disk_path="/tmp/vm.qcow2", disk_gb=10)

    create_args = provider.calls[0]
    assert create_args[:4] == ["qemu-img", "create", "-f", "qcow2"]
    assert "-u" in create_args
    assert create_args[create_args.index("-b") + 1] == "/var/lib/hackme-vms/base/noble.img"
    assert create_args[-1] == "10G"
    assert len(provider.calls) == 1


def test_user_mode_host_forward_uses_qemu_monitor_command():
    class CaptureProvider(LibvirtQemuProvider):
        def __init__(self):
            super().__init__()
            self.calls = []

        def run(self, args, timeout=None, input_text=None):
            self.calls.append(list(args))
            return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    provider = CaptureProvider()
    provider.add_user_host_forward(vm_name="hackme-term-u1-abcdef1234", host_port=22222, guest_port=22)

    args = provider.calls[0]
    assert args[:4] == ["virsh", "-c", "qemu:///system", "qemu-monitor-command"]
    assert args[-1] == "hostfwd_add tcp:127.0.0.1:22222-:22"


def test_base_image_health_accepts_hypervisor_group_readable_file(tmp_path, monkeypatch):
    image = tmp_path / "base.img"
    image.write_bytes(b"fake")
    image.chmod(0o640)
    monkeypatch.setattr("services.web_terminal_qemu._name_for_gid", lambda gid: "kvm")

    assert _hypervisor_can_probably_read(image) is True


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
    assert data["health"]["checks"][0]["label"]


def test_qemu_health_payload_includes_failure_explanations(tmp_path):
    manager = FakeWebTerminalManager(ok=False)
    client = _app(tmp_path, manager=manager).test_client()
    res = client.get("/api/root/web-terminal/qemu/health")
    data = res.get_json()

    assert res.status_code == 503
    assert data["ok"] is False
    assert "checks" in data["health"]
    assert data["health"]["checks"][0]["message"] == "fake"


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


def test_qemu_health_accepts_spaced_libvirt_network_active_output(tmp_path):
    class FakeProvider(LibvirtQemuProvider):
        def run(self, args, timeout=None):
            command = " ".join(args)
            if args[:2] == ["virsh", "-c"] and "net-info default" in command:
                return {
                    "ok": True,
                    "stdout": "Name: default\nActive:         yes\nPersistent: yes\n",
                    "stderr": "",
                    "returncode": 0,
                }
            if args[:2] == ["virsh", "-c"]:
                return {"ok": True, "stdout": "Id   Name   State\n--------------------\n", "stderr": "", "returncode": 0}
            return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    vm_root = tmp_path / "vms"
    base_dir = tmp_path / "project"
    base_image = vm_root / "base" / "noble-server-cloudimg-amd64.img"
    base_image.parent.mkdir(parents=True)
    base_image.write_bytes(b"fake")
    provider = FakeProvider()

    health = provider.health({
        "enabled": True,
        "base_dir": str(base_dir),
        "vm_root": str(vm_root),
        "base_image": str(base_image),
        "network_mode": "nat",
        "libvirt_uri": "qemu:///system",
        "distro": "ubuntu-24.04",
        "vcpus": 1,
        "memory_mb": 3100,
        "disk_gb": 10,
        "idle_timeout_seconds": 900,
        "cloud_drive_sync": "staged",
    })

    network_check = next(row for row in health["checks"] if row["name"] == "libvirt_default_network")
    assert network_check["ok"] is True


def test_web_terminal_frontend_uses_existing_sanitize_helper():
    js = (Path(__file__).resolve().parents[1] / "public" / "js" / "39-web-terminal-qemu.js").read_text(encoding="utf-8")
    assert "escapeHtml(" not in js
    assert "sanitize(" in js
    assert "所有 WebTerminal 環境檢查已通過" in js
