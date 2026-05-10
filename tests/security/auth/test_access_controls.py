import json

from flask import Flask, jsonify, make_response, request

from routes.system_admin import register_system_admin_routes
from services.security.access_controls import (
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
from services.server.bind import (
    effective_server_bind,
    effective_server_ssl,
    server_ssl_settings_payload,
    validate_listen_host,
    validate_listen_port,
)
from services.server.request_guards import protect_sensitive_static_page


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _admin_app(settings_state=None, actor=None, cert_file=None, key_file=None, current_ssl_enabled=False, audit_log=None):
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
        "server_ssl_enabled": True,
        "comfyui_connection_mode": "remote",
        "comfyui_remote_api_url": "",
        "comfyui_base_dir": "",
        "comfyui_local_start_script": "",
        "comfyui_api_host": "localhost",
        "comfyui_api_port": 8192,
        "comfyui_max_batch_size": 1,
        "comfyui_default_width": 1024,
        "comfyui_default_height": 1024,
    }

    def save_settings(data):
        state.update(data)
        return dict(data)

    register_system_admin_routes(app, {
        "ANCHOR_DIR": ".",
        "BASE_DIR": ".",
        "CERT_FILE": str(cert_file or "missing-cert.pem"),
        "CHAT_DIR": ".",
        "CURRENT_SERVER_BIND_STATE": {"host": "0.0.0.0", "port": 5000, "ssl_enabled": current_ssl_enabled},
        "DB_PATH": "missing.db",
        "KEY_FILE": str(key_file or "missing-key.pem"),
        "LOG_DIR": ".",
        "SERVER_LOG_PATH": "server.log",
        "activate_emergency_lockdown": lambda reason: None,
        "audit": (lambda *args, **kwargs: audit_log.append((args, kwargs))) if audit_log is not None else (lambda *args, **kwargs: None),
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


def test_comfyui_workflow_editor_static_page_requires_login():
    app = Flask(__name__)
    audit_log = []
    with app.test_request_context("/comfyui-workflow-editor.html"):
        resp = protect_sensitive_static_page(
            request,
            get_current_user_ctx=lambda: None,
            audit=lambda *args, **kwargs: audit_log.append((args, kwargs)),
            get_client_ip=lambda: "127.0.0.1",
            get_ua=lambda: "pytest",
            is_feature_enabled=lambda key: True,
            record_security_event=lambda *args, **kwargs: None,
            make_response=make_response,
        )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    assert audit_log
    assert audit_log[-1][0][0] == "STATIC_PAGE_UNAUTH_DENIED"
    assert "path=/comfyui-workflow-editor.html" in audit_log[-1][1]["detail"]


def test_comfyui_workflow_editor_static_page_respects_feature_flag():
    app = Flask(__name__)
    security_events = []
    with app.test_request_context("/comfyui-workflow-editor.html"):
        resp = protect_sensitive_static_page(
            request,
            get_current_user_ctx=lambda: {"id": 1, "username": "root"},
            audit=lambda *args, **kwargs: None,
            get_client_ip=lambda: "127.0.0.1",
            get_ua=lambda: "pytest",
            is_feature_enabled=lambda key: False,
            record_security_event=lambda *args, **kwargs: security_events.append((args, kwargs)),
            make_response=make_response,
        )

    assert resp.status_code == 503
    assert b"ComfyUI workflow editor is disabled" in resp.data
    assert security_events
    assert "feature_comfyui_enabled" in security_events[-1][1]["detail"]


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


def test_admin_access_controls_reject_invalid_root_ip_whitelist_entries():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/access-controls", json={
        "root_ip_whitelist_enabled": True,
        "root_ip_whitelist": "127.0.0.1,javascript:alert(1),999.999.999.999",
    })

    assert res.status_code == 400
    assert "無效的 IP / CIDR" in res.get_json()["msg"]
    assert state["root_ip_whitelist"] == ""
    assert state["root_ip_whitelist_enabled"] is False


def test_admin_access_controls_reject_enabling_empty_root_ip_whitelist():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/access-controls", json={
        "root_ip_whitelist_enabled": True,
        "root_ip_whitelist": "",
    })

    assert res.status_code == 400
    assert "至少要填入一個有效的 IP 或 CIDR" in res.get_json()["msg"]
    assert state["root_ip_whitelist_enabled"] is False


def test_admin_rotates_maintenance_bypass_token_once():
    audit_log = []
    app, state = _admin_app(audit_log=audit_log)
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
    event = next(call for call in audit_log if call[0][0] == "MAINTENANCE_BYPASS_TOKEN_ROTATED")
    detail = json.loads(event[1]["detail"])
    changes = {row["key"]: row for row in detail["changes"]}
    assert changes["maintenance_bypass_token_hash"]["old"] == ""
    assert changes["maintenance_bypass_token_hash"]["new"] == "<redacted>"
    assert data["token"] not in event[1]["detail"]


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


def test_server_ssl_settings_require_root_setting_and_cert_files():
    enabled = effective_server_ssl({"server_ssl_enabled": True}, cert_exists=True)
    disabled_by_setting = effective_server_ssl({"server_ssl_enabled": False}, cert_exists=True)
    missing_cert = effective_server_ssl({"server_ssl_enabled": True}, cert_exists=False)
    restart = server_ssl_settings_payload(
        {"server_ssl_enabled": True},
        current_ssl_enabled=False,
        cert_exists=True,
    )

    assert enabled["enabled"] is True
    assert enabled["scheme"] == "https"
    assert disabled_by_setting["enabled"] is False
    assert disabled_by_setting["scheme"] == "http"
    assert missing_cert["enabled"] is False
    assert missing_cert["cert_required"] is True
    assert restart["restart_required"] is True


def test_root_can_configure_server_ssl_setting_with_restart_hint(tmp_path):
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    cert_file.write_text("cert", encoding="utf-8")
    key_file.write_text("key", encoding="utf-8")
    app, state = _admin_app(cert_file=cert_file, key_file=key_file, current_ssl_enabled=False)
    client = app.test_client()

    initial = client.get("/api/admin/settings").get_json()
    assert initial["server_ssl"]["enabled"] is True
    assert initial["server_ssl"]["restart_required"] is True

    res = client.put("/api/admin/settings", json={"server_ssl_enabled": False})
    data = res.get_json()

    assert res.status_code == 200
    assert state["server_ssl_enabled"] is False
    assert data["server_ssl"]["enabled"] is False
    assert data["server_ssl"]["enabled_by_setting"] is False
    assert data["server_ssl"]["current_enabled"] is False


def test_invalid_server_bind_settings_are_rejected():
    app, state = _admin_app()
    client = app.test_client()

    bad_host = client.put("/api/admin/settings", json={"server_listen_host": "0.0.0.0/0"})
    bad_port = client.put("/api/admin/settings", json={"server_listen_port": 70000})

    assert bad_host.status_code == 400
    assert bad_port.status_code == 400
    assert state["server_listen_host"] == ""
    assert state["server_listen_port"] == 0


def test_admin_settings_reject_invalid_boolean_strings_for_security_flags():
    app, state = _admin_app()
    state["integrity_guard_enabled"] = True
    state["audit_chain_enabled"] = True
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"integrity_guard_enabled": "yes_please"})

    assert res.status_code == 400
    assert state["integrity_guard_enabled"] is True

    res = client.put("/api/admin/settings", json={"audit_chain_enabled": "enable_me"})

    assert res.status_code == 400
    assert state["audit_chain_enabled"] is True


def test_admin_settings_reject_absurd_ranges_and_invalid_snapshot_time():
    app, state = _admin_app()
    state["video_tip_fee_percent"] = 5
    state["video_tip_min_points"] = 1
    state["security_log_tail_lines"] = 200
    state["snapshot_daily_time"] = "03:00"
    client = app.test_client()

    assert client.put("/api/admin/settings", json={"video_tip_fee_percent": -5}).status_code == 400
    assert client.put("/api/admin/settings", json={"video_tip_fee_percent": 99999}).status_code == 400
    assert client.put("/api/admin/settings", data='{"video_tip_fee_percent": NaN}', content_type="application/json").status_code == 400
    assert client.put("/api/admin/settings", data='{"video_tip_fee_percent": Infinity}', content_type="application/json").status_code == 400
    assert client.put("/api/admin/settings", json={"video_tip_min_points": -1}).status_code == 400
    assert client.put("/api/admin/settings", json={"video_tip_min_points": 10**18}).status_code == 400
    assert client.put("/api/admin/settings", json={"security_log_tail_lines": -1}).status_code == 400
    assert client.put("/api/admin/settings", json={"security_log_tail_lines": 10**9}).status_code == 400
    assert client.put("/api/admin/settings", json={"snapshot_daily_time": "25:99"}).status_code == 400
    assert client.put("/api/admin/settings", json={"snapshot_daily_time": "abcd"}).status_code == 400
    assert client.put("/api/admin/settings", json={"snapshot_daily_time": "12:30:45"}).status_code == 400

    assert state["video_tip_fee_percent"] == 5
    assert state["video_tip_min_points"] == 1
    assert state["security_log_tail_lines"] == 200
    assert state["snapshot_daily_time"] == "03:00"


def test_root_can_configure_comfyui_api_endpoint_without_restart_hint():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_api_host": "192.168.1.20", "comfyui_api_port": 8193})

    assert res.status_code == 200
    assert state["comfyui_api_host"] == "192.168.1.20"
    assert state["comfyui_api_port"] == 8193
    assert res.get_json()["settings"]["comfyui_api_host"] == "192.168.1.20"
    assert res.get_json()["settings"]["comfyui_api_port"] == 8193


def test_root_can_configure_local_comfyui_script_with_absolute_path(tmp_path):
    app, state = _admin_app()
    client = app.test_client()
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    comfy_base.mkdir()
    script = comfy_base / "run_in_linux.sh"
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    res = client.put(
        "/api/admin/settings",
        json={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_local_start_script": str(script),
            "comfyui_api_host": "localhost",
            "comfyui_api_port": 8188,
        },
    )

    assert res.status_code == 200
    assert state["comfyui_connection_mode"] == "local"
    assert state["comfyui_base_dir"] == str(comfy_base)
    assert state["comfyui_local_start_script"] == "run_in_linux.sh"
    assert state["comfyui_api_port"] == 8188


def test_root_can_leave_remote_comfyui_url_blank_when_saving_settings():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_connection_mode": "remote", "comfyui_remote_api_url": ""})

    assert res.status_code == 200
    assert state["comfyui_connection_mode"] == "remote"
    assert state["comfyui_remote_api_url"] == ""


def test_remote_comfyui_url_requires_explicit_port():
    app, state = _admin_app()
    client = app.test_client()

    good = client.put("/api/admin/settings", json={"comfyui_remote_api_url": "https://comfy.example.com:8443"})
    bad = client.put("/api/admin/settings", json={"comfyui_remote_api_url": "https://comfy.example.com"})

    assert good.status_code == 200
    assert state["comfyui_remote_api_url"] == "https://comfy.example.com:8443"
    assert bad.status_code == 400


def test_invalid_comfyui_api_endpoint_is_rejected():
    app, state = _admin_app()
    client = app.test_client()

    bad_host = client.put("/api/admin/settings", json={"comfyui_api_host": "http://127.0.0.1:8192/prompt"})
    bad_port = client.put("/api/admin/settings", json={"comfyui_api_port": 70000})

    assert bad_host.status_code == 400
    assert bad_port.status_code == 400
    assert state["comfyui_api_host"] == "localhost"
    assert state["comfyui_api_port"] == 8192


def test_root_can_configure_comfyui_batch_limit_without_restart_hint():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_max_batch_size": 4})

    assert res.status_code == 200
    assert state["comfyui_max_batch_size"] == 4
    assert res.get_json()["settings"]["comfyui_max_batch_size"] == 4


def test_root_can_configure_comfyui_default_dimensions_without_restart_hint():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_default_width": 768, "comfyui_default_height": 1024})

    assert res.status_code == 200
    assert state["comfyui_default_width"] == 768
    assert state["comfyui_default_height"] == 1024
    assert res.get_json()["settings"]["comfyui_default_width"] == 768
    assert res.get_json()["settings"]["comfyui_default_height"] == 1024


def test_invalid_comfyui_default_dimensions_are_rejected():
    app, state = _admin_app()
    client = app.test_client()

    bad_small = client.put("/api/admin/settings", json={"comfyui_default_width": 32})
    bad_step = client.put("/api/admin/settings", json={"comfyui_default_height": 1025})

    assert bad_small.status_code == 400
    assert bad_step.status_code == 400
    assert state["comfyui_default_width"] == 1024
    assert state["comfyui_default_height"] == 1024


def test_invalid_comfyui_batch_limit_is_rejected():
    app, state = _admin_app()
    client = app.test_client()

    res = client.put("/api/admin/settings", json={"comfyui_max_batch_size": 9})

    assert res.status_code == 400
    assert state["comfyui_max_batch_size"] == 1


def test_admin_environment_exposes_relative_paths_and_pid():
    app, _ = _admin_app()
    client = app.test_client()

    res = client.get("/api/admin/environment")
    assert res.status_code == 200
    env = res.get_json()["environment"]
    assert env["pid"] > 0
    assert env["base_dir"] == "."
    assert env["database_path"] == "missing.db"
    assert env["log_dir"] == "."
    assert env["chat_dir"] == "."
    assert env["anchor_dir"] == "."
    for key in ("base_dir", "database_path", "log_dir", "chat_dir", "anchor_dir"):
        assert not str(env[key]).startswith("/")


def test_effective_server_bind_falls_back_to_environment():
    bind = effective_server_bind(
        {"server_listen_host": "", "server_listen_port": 0},
        env={"HTML_LEARNING_HOST": "127.0.0.1", "HTML_LEARNING_PORT": "9000"},
    )
    assert bind["host"] == "127.0.0.1"
    assert bind["port"] == 9000
    assert bind["host_source"] == "env"
