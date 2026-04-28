from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes
from services.access_controls import (
    access_control_settings_payload,
    client_ip_allowed,
    hash_maintenance_bypass_token,
    is_browser_user_agent,
    maintenance_bypass_expires_at,
    maintenance_bypass_required_payload,
    maintenance_bypass_token_is_expired,
    parse_ip_whitelist,
    verify_maintenance_bypass_token,
)
from services.server_bind import effective_server_bind, validate_listen_host, validate_listen_port


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _admin_app(settings_state=None, actor=None):
    app = Flask(__name__)
    app.testing = True
    state = settings_state or {
        "root_ip_whitelist_enabled": False,
        "root_ip_whitelist": "",
        "browser_only_mode_enabled": False,
        "maintenance_bypass_token_hash": "",
        "maintenance_bypass_token_expires_at": "",
        "server_listen_host": "",
        "server_listen_port": 0,
        "comfyui_api_port": 8192,
    }

    def save_settings(data):
        state.update(data)
        return dict(data)

    register_system_admin_routes(app, {
        "ANCHOR_DIR": ".",
        "BASE_DIR": ".",
        "CHAT_DIR": ".",
        "CURRENT_SERVER_BIND_STATE": {"host": "0.0.0.0", "port": 5000},
        "DB_PATH": "missing.db",
        "LOG_DIR": ".",
        "SERVER_LOG_PATH": "server.log",
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor or {"id": 1, "username": "root", "role": "super_admin"},
        "get_db": lambda: None,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: dict(state),
        "get_ua": lambda: "pytest",
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": save_settings,
        "server_mode_service": None,
        "snapshot_service": None,
        "verify_audit_integrity": lambda: (True, None, "ok"),
    })
    return app, state


def test_ip_whitelist_supports_exact_ips_and_cidrs():
    assert parse_ip_whitelist("127.0.0.1, 10.0.0.0/24\n::1") == ["127.0.0.1", "10.0.0.0/24", "::1"]
    assert client_ip_allowed("127.0.0.1", "127.0.0.1") is True
    assert client_ip_allowed("10.0.0.8", "10.0.0.0/24") is True
    assert client_ip_allowed("10.0.1.8", "10.0.0.0/24") is False
    assert client_ip_allowed("bad-ip", "127.0.0.1") is False


def test_browser_user_agent_detection_is_conservative():
    assert is_browser_user_agent("Mozilla/5.0 Chrome/120 Safari/537.36") is True
    assert is_browser_user_agent("curl/8.0") is False
    assert is_browser_user_agent("") is False


def test_maintenance_bypass_token_hash_roundtrip():
    stored = hash_maintenance_bypass_token("secret-token")
    assert stored
    assert verify_maintenance_bypass_token("secret-token", stored) is True
    assert verify_maintenance_bypass_token("wrong", stored) is False
    assert verify_maintenance_bypass_token("secret-token", "") is False


def test_maintenance_bypass_token_expiry_is_enforced():
    stored = hash_maintenance_bypass_token("secret-token")
    future = maintenance_bypass_expires_at(30)
    assert verify_maintenance_bypass_token("secret-token", stored, future) is True
    assert verify_maintenance_bypass_token("secret-token", stored, "2000-01-01T00:00:00+00:00") is False
    assert maintenance_bypass_token_is_expired("2000-01-01T00:00:00+00:00") is True


def test_maintenance_bypass_required_payload_names_token_header_not_hash():
    payload = maintenance_bypass_required_payload("need bypass")
    assert payload["requires"] == "maintenance_bypass_token"
    assert payload["header"] == "X-Maintenance-Bypass-Token"
    assert "hash" not in str(payload).lower()


def test_admin_access_controls_endpoint_updates_safe_payload():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/access-controls", json={
        "root_ip_whitelist_enabled": True,
        "root_ip_whitelist": "127.0.0.1,10.0.0.0/24",
        "browser_only_mode_enabled": True,
        "maintenance_bypass_token_hash": "should-not-be-accepted-directly",
    })
    data = res.get_json()
    assert res.status_code == 200
    assert data["access_controls"]["root_ip_whitelist_enabled"] is True
    assert data["access_controls"]["root_ip_whitelist"] == "127.0.0.1,10.0.0.0/24"
    assert data["access_controls"]["browser_only_mode_enabled"] is True
    assert state["maintenance_bypass_token_hash"] == ""


def test_admin_rotates_maintenance_bypass_token_once():
    app, state = _admin_app()
    client = app.test_client()
    res = client.post("/api/admin/access-controls/maintenance-bypass-token", json={"confirm": "ROTATE", "ttl_minutes": 15})
    data = res.get_json()
    assert res.status_code == 200
    assert data["token"]
    assert data["ttl_minutes"] == 15
    assert data["expires_at"]
    assert data["access_controls"]["maintenance_bypass_token_configured"] is True
    assert data["access_controls"]["maintenance_bypass_token_expires_at"] == state["maintenance_bypass_token_expires_at"]
    assert verify_maintenance_bypass_token(data["token"], state["maintenance_bypass_token_hash"], state["maintenance_bypass_token_expires_at"]) is True
    assert "maintenance_bypass_token_hash" not in data["access_controls"]


def test_access_controls_are_root_only():
    app, _ = _admin_app(actor={"id": 2, "username": "admin", "role": "manager"})
    res = app.test_client().get("/api/admin/access-controls")
    assert res.status_code == 403


def test_access_control_settings_payload_never_exposes_token_hash():
    payload = access_control_settings_payload({"maintenance_bypass_token_hash": "hash"})
    assert payload["maintenance_bypass_token_configured"] is True
    assert "maintenance_bypass_token_hash" not in payload


def test_server_bind_validation_accepts_ips_and_rejects_unsafe_values():
    assert validate_listen_host("127.0.0.1") == "127.0.0.1"
    assert validate_listen_host("::1") == "::1"
    assert validate_listen_host("localhost") == "localhost"
    assert validate_listen_host("0.0.0.0/0") is None
    assert validate_listen_host("127.0.0.1,0.0.0.0") is None
    assert validate_listen_port("8080") == 8080
    assert validate_listen_port("0") == 0
    assert validate_listen_port("70000") is None


def test_root_can_configure_server_bind_settings_with_restart_hint():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={
        "server_listen_host": "127.0.0.1",
        "server_listen_port": 8081,
    })
    data = res.get_json()

    assert res.status_code == 200
    assert state["server_listen_host"] == "127.0.0.1"
    assert state["server_listen_port"] == 8081
    assert data["server_bind"]["host"] == "127.0.0.1"
    assert data["server_bind"]["port"] == 8081
    assert data["server_bind"]["restart_required"] is True


def test_invalid_server_bind_settings_are_rejected():
    app, state = _admin_app()
    client = app.test_client()

    bad_host = client.put("/api/admin/settings", json={"server_listen_host": "0.0.0.0/0"})
    bad_port = client.put("/api/admin/settings", json={"server_listen_port": 70000})

    assert bad_host.status_code == 400
    assert bad_port.status_code == 400
    assert state["server_listen_host"] == ""
    assert state["server_listen_port"] == 0


def test_root_can_configure_comfyui_api_port_without_restart_hint():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_api_port": 8193})

    assert res.status_code == 200
    assert state["comfyui_api_port"] == 8193
    assert res.get_json()["settings"]["comfyui_api_port"] == 8193


def test_invalid_comfyui_api_port_is_rejected():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_api_port": 70000})

    assert res.status_code == 400
    assert state["comfyui_api_port"] == 8192


def test_admin_environment_exposes_paths_and_pid():
    app, _ = _admin_app()
    client = app.test_client()

    res = client.get("/api/admin/environment")
    assert res.status_code == 200
    env = res.get_json()["environment"]
    assert env["pid"] > 0
    assert env["base_dir"] == "."
    assert env["database_path"] == "missing.db"


def test_effective_server_bind_falls_back_to_environment():
    bind = effective_server_bind(
        {"server_listen_host": "", "server_listen_port": 0},
        env={"HTML_LEARNING_HOST": "127.0.0.1", "HTML_LEARNING_PORT": "9000"},
    )
    assert bind["host"] == "127.0.0.1"
    assert bind["port"] == 9000
    assert bind["host_source"] == "env"
