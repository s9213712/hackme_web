import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.web_terminal import register_web_terminal_routes
from services.web_terminal import (
    WebTerminalPolicy,
    build_container_command,
    normalize_web_terminal_distribution,
    normalize_web_terminal_network_mode,
    root_terminal_mount_path,
    web_terminal_image_for_distribution,
)


ROOT = Path(__file__).resolve().parents[1]


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


class FakeTerminalManager:
    def status_payload(self, actor, *, feature_enabled=True):
        return {
            "enabled": bool(feature_enabled and actor and actor.get("username") == "root"),
            "websocket_available": False,
            "runtime_available": False,
            "image_available": False,
            "image": "hackme-web-terminal:ubuntu-24.04",
            "distribution": "ubuntu-24.04",
            "limits": {"network": "bridge"},
        }


def _build_app(db_path, storage_root, *, feature_enabled=True, actor=None):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_web_terminal_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_current_user_ctx": lambda: actor or {"id": 1, "username": "root", "role": "super_admin"},
        "get_db": get_db,
        "is_feature_enabled": lambda key: feature_enabled if key == "web_terminal" else True,
        "json_resp": _json_resp,
        "require_csrf_safe": _passthrough,
        "verify_csrf_token": lambda token, username: bool(token or username),
        "web_terminal_manager": FakeTerminalManager(),
    })
    return app


def test_container_command_keeps_terminal_sandboxed(tmp_path):
    mount_path = tmp_path / "storage" / "users" / "1"
    mount_path.mkdir(parents=True)
    command = build_container_command(
        session_id="abc123",
        mount_path=mount_path,
        policy=WebTerminalPolicy(image="hackme-web-terminal:base"),
    )
    joined = " ".join(command)

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--user" in command
    assert f"{mount_path.stat().st_uid}:{mount_path.stat().st_gid}" in command
    assert "--network bridge" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in command
    assert "/run:rw,nosuid,nodev,noexec,size=16m" in command
    assert "/var/tmp:rw,nosuid,nodev,noexec,size=64m" in command
    assert "--pids-limit 128" in joined
    assert f"{mount_path}:/home/root:rw" in command
    assert "HOME=/home/root" in command
    assert "/var/run/docker.sock" not in joined
    assert f"{ROOT}:" not in joined
    assert " /:/home/root" not in joined
    assert " /etc:" not in joined
    assert command[-2:] == ["/bin/bash", "-l"]


def test_web_terminal_network_modes_are_normalized():
    assert normalize_web_terminal_network_mode("none") == "none"
    assert normalize_web_terminal_network_mode("bridge") == "bridge"
    assert normalize_web_terminal_network_mode("host") == "host"
    assert normalize_web_terminal_network_mode("bad") == "bridge"


def test_web_terminal_distribution_selects_image():
    assert normalize_web_terminal_distribution("ubuntu-24.04") == "ubuntu-24.04"
    assert normalize_web_terminal_distribution("ubuntu-22.04") == "ubuntu-22.04"
    assert normalize_web_terminal_distribution("bad") == "ubuntu-24.04"
    assert web_terminal_image_for_distribution("ubuntu-24.04") == "hackme-web-terminal:ubuntu-24.04"
    assert web_terminal_image_for_distribution("ubuntu-22.04") == "hackme-web-terminal:ubuntu-22.04"


def test_root_mount_path_stays_inside_cloud_drive_storage(tmp_path):
    storage_root = tmp_path / "cloud-drive"
    path = root_terminal_mount_path(storage_root, 7)

    assert path == storage_root / "users" / "7"
    assert path.is_dir()


def test_status_runs_environment_check_and_reports_feature_state(tmp_path):
    db_path = tmp_path / "terminal.db"
    client = _build_app(db_path, tmp_path / "storage", feature_enabled=False).test_client()

    res = client.get("/api/root/web-terminal/status")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["terminal"]["enabled"] is False
    assert payload["terminal"]["websocket_available"] is False
    assert payload["terminal"]["runtime_available"] is False
    assert payload["terminal"]["image_available"] is False


def test_status_accepts_sqlite_row_actor(tmp_path):
    db_path = tmp_path / "terminal.db"
    actor_db = tmp_path / "actor.db"
    conn = sqlite3.connect(actor_db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("INSERT INTO users (id, username, role) VALUES (1, 'root', 'super_admin')")
    conn.commit()
    actor = conn.execute("SELECT * FROM users WHERE username='root'").fetchone()
    conn.close()

    client = _build_app(db_path, tmp_path / "storage", feature_enabled=True, actor=actor).test_client()
    res = client.get("/api/root/web-terminal/status")

    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["terminal"]["enabled"] is True


def test_frontend_checks_environment_before_opening_session():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    web_terminal_js = (ROOT / "public" / "js" / "39-web-terminal.js").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert 'id="tab-module-web-terminal"' in index_html
    assert 'id="module-web-terminal"' in index_html
    assert "/vendor/xterm/xterm.js" not in index_html
    assert "/js/39-web-terminal.js?v=20260429-web-terminal-ubuntu" in index_html
    assert 'id="web-terminal-check-btn"' in index_html
    assert "/vendor/xterm/xterm.js" in web_terminal_js
    assert "loadWebTerminalAssets" in web_terminal_js
    assert "loadWebTerminalStatus({ notify: true })" in admin_js
    assert "webTerminalCheckItems" in web_terminal_js
    assert "window.Terminal" in web_terminal_js
    assert "image_available" in web_terminal_js
    assert "runtime_available" in web_terminal_js
    assert "先修 Docker 權限並重開 server" in web_terminal_js
    assert "不要只用 sudo check" in web_terminal_js
    assert "Docker socket 屬於" in web_terminal_js
    assert "sg ${sock.group} -c 'scripts/run_prod.sh'" in web_terminal_js
    assert "webTerminalCloseRequested" in web_terminal_js
    assert "Web Terminal session 未成功建立就關閉" in web_terminal_js
    assert "websocket_available" in web_terminal_js
    assert "網路模式" in web_terminal_js
    assert "發行版" in web_terminal_js
    assert "web_terminal" in core_js
    assert "JetBrains Mono" in web_terminal_js
    assert "scrollback: 4000" in web_terminal_js


def test_web_terminal_image_uses_ubuntu_base_with_apt_tools():
    dockerfile = (ROOT / "docker" / "web-terminal" / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG UBUNTU_VERSION=24.04" in dockerfile
    assert "FROM ubuntu:${UBUNTU_VERSION}" in dockerfile
    assert "apt-get update" in dockerfile
    assert "apt-get install" in dockerfile
    assert "ubuntu-standard" in dockerfile
    assert "apt-utils" in dockerfile
    assert "man-db" in dockerfile
    assert "openssh-client" in dockerfile
    assert "tmux" in dockerfile
    assert "LANG=C.UTF-8" in dockerfile
    assert 'CMD ["/bin/bash", "-l"]' in dockerfile


def test_web_terminal_installer_and_docs_are_self_service():
    installer = (ROOT / "install_web_terminal_dependencies.sh").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "WEB_TERMINAL.md").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    run_prod = (ROOT / "scripts" / "run_prod.sh").read_text(encoding="utf-8")

    assert "--doctor" in installer
    assert "sudo docker info" in installer
    assert "WARNING: this check is running as root" in installer
    assert "current_process_in_group" in installer
    assert "Account groups from user database" in installer
    assert "sg docker -c 'scripts/run_prod.sh'" in installer
    assert "TERMINAL_IMAGE_VARIANTS" in installer
    assert "hackme-web-terminal:ubuntu-24.04" in installer
    assert "hackme-web-terminal:ubuntu-22.04" in installer
    assert "python3-venv" in installer
    assert "./install_web_terminal_dependencies.sh --all --venv .venv" in readme
    assert "docker info` must work without" in readme
    assert "./install_web_terminal_dependencies.sh --doctor --venv .venv" in guide
    assert "id -nG \"$USER\"" in guide
    assert "Network Modes" in guide
    assert "Ubuntu Versions" in guide
    assert "`bridge`" in guide
    assert "`host`" in guide
    assert "`ubuntu-24.04`" in guide
    assert "`ubuntu-22.04`" in guide
    assert "flask-sock" in requirements
    assert "official Ubuntu LTS" in guide
    assert "simple-websocket" in requirements
    assert "activate_or_create_venv" in run_prod
    assert "ensure_python_dependencies" in run_prod
    assert "scripts/run_prod.sh" in readme


def test_status_payload_reports_docker_daemon_access_separately(tmp_path):
    from services import web_terminal as web_terminal_service

    class FakeStat:
        st_uid = 1000
        st_gid = 1000
        st_mode = 0o660

    def fake_run(command, **kwargs):
        class Result:
            returncode = 1
            stderr = "permission denied while trying to connect to the docker API"
        return Result()

    manager = web_terminal_service.WebTerminalManager(
        get_db=lambda: sqlite3.connect(":memory:"),
        storage_root=tmp_path,
        audit=lambda *args, **kwargs: None,
    )

    original_which = web_terminal_service.shutil.which
    original_run = web_terminal_service.subprocess.run
    original_stat = web_terminal_service.os.stat
    try:
        web_terminal_service.shutil.which = lambda name: "/usr/bin/docker" if name == "docker" else None
        web_terminal_service.subprocess.run = fake_run
        web_terminal_service.os.stat = lambda path: FakeStat()
        payload = manager.status_payload({"id": 1, "username": "root"}, feature_enabled=True)
    finally:
        web_terminal_service.shutil.which = original_which
        web_terminal_service.subprocess.run = original_run
        web_terminal_service.os.stat = original_stat

    assert payload["runtime_binary_available"] is True
    assert payload["runtime_available"] is False
    assert "permission denied" in payload["runtime_error"]
    assert payload["image_available"] is False
    assert payload["process"]["docker_sock"]["exists"] is True


def test_websocket_csrf_verification_uses_actor_username():
    route_source = (ROOT / "routes" / "web_terminal.py").read_text(encoding="utf-8")

    assert "def verify_websocket_csrf(token, actor):" in route_source
    assert 'username = actor.get("username") if actor else ""' in route_source
    assert "verify_csrf_token(token, username)" in route_source
