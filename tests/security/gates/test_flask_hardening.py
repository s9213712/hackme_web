import json

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge, SecurityError

from services.security.access_controls import (
    hash_maintenance_bypass_token,
    maintenance_bypass_expires_at,
    maintenance_bypass_required_payload,
    verify_maintenance_bypass_token,
)
from services.server.backpressure import install_backpressure
from services.server.request_guards import (
    enforce_browser_only_mode,
    get_request_maintenance_bypass_token,
)
from services.server.security_runtime import get_client_ip


def _hardening_app(*, trusted_hosts=None, max_form_parts=1000, max_form_memory_size=512 * 1024):
    app = Flask(__name__)
    app.testing = True
    app.config["TRUSTED_HOSTS"] = trusted_hosts or ["localhost", "127.0.0.1"]
    app.config["MAX_FORM_PARTS"] = max_form_parts
    app.config["MAX_FORM_MEMORY_SIZE"] = max_form_memory_size

    @app.errorhandler(SecurityError)
    def security_error(_error):
        return jsonify({"ok": False, "error": "untrusted_host", "msg": "Invalid request host"}), 400

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return jsonify({"ok": False, "error": "request_too_large", "msg": "request too large"}), 413

    @app.route("/api/version")
    def version():
        return jsonify({"ok": True, "host": request.host})

    @app.route("/api/form", methods=["POST"])
    def form_probe():
        return jsonify({"ok": True, "form_count": len(request.form), "fields": dict(request.form)})

    return app


def test_trusted_hosts_allow_configured_host_and_reject_evil_empty_and_malformed_hosts():
    client = _hardening_app().test_client()

    allowed = client.get("/api/version", headers={"Host": "localhost"})
    assert allowed.status_code == 200
    assert allowed.get_json()["ok"] is True

    for host in ("evil.com", "", "bad host", "localhost:bad"):
        response = client.get("/api/version", environ_overrides={"HTTP_HOST": host})
        assert response.status_code == 400
        assert response.get_json()["error"] == "untrusted_host"


def test_multipart_limits_reject_part_count_and_memory_abuse_but_allow_small_forms():
    small_client = _hardening_app(max_form_parts=5, max_form_memory_size=1024).test_client()
    small = small_client.post("/api/form", data={"a": "1"}, content_type="multipart/form-data")
    assert small.status_code == 200
    assert small.get_json()["form_count"] == 1

    parts_client = _hardening_app(max_form_parts=2, max_form_memory_size=1024).test_client()
    too_many_parts = parts_client.post(
        "/api/form",
        data={"a": "1", "b": "2", "c": "3"},
        content_type="multipart/form-data",
    )
    assert too_many_parts.status_code == 413
    assert too_many_parts.get_json()["error"] == "request_too_large"

    memory_client = _hardening_app(max_form_parts=5, max_form_memory_size=32).test_client()
    too_large_field = memory_client.post(
        "/api/form",
        data={"a": "x" * 100},
        content_type="multipart/form-data",
    )
    assert too_large_field.status_code == 413
    assert too_large_field.get_json()["error"] == "request_too_large"


def test_maintenance_bypass_accepts_header_only_and_does_not_echo_token_values():
    app = Flask(__name__)
    app.testing = True
    events = []
    token = "secret-maintenance-token"
    state = {
        "browser_only_mode_enabled": True,
        "maintenance_bypass_token_hash": hash_maintenance_bypass_token(token),
        "maintenance_bypass_token_expires_at": maintenance_bypass_expires_at(30),
    }

    def json_resp(payload, status=200):
        response = jsonify(payload)
        response.status_code = status
        return response

    def has_valid_bypass(settings):
        return verify_maintenance_bypass_token(
            get_request_maintenance_bypass_token(request),
            settings.get("maintenance_bypass_token_hash", ""),
            settings.get("maintenance_bypass_token_expires_at", ""),
        )

    @app.before_request
    def guard():
        return enforce_browser_only_mode(
            request,
            get_system_settings=lambda: dict(state),
            has_valid_maintenance_bypass_func=has_valid_bypass,
            is_browser_user_agent=lambda _ua: False,
            get_current_user_ctx=lambda: {"username": "root"},
            record_security_event=lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}),
            get_client_ip=lambda: "127.0.0.1",
            maintenance_bypass_required_payload=maintenance_bypass_required_payload,
            json_resp=json_resp,
        )

    @app.route("/api/private")
    def private():
        return jsonify({"ok": True})

    client = app.test_client()
    query_only = client.get(
        "/api/private?maintenance_bypass_token=secret-maintenance-token",
        headers={"User-Agent": "curl/8"},
    )
    assert query_only.status_code == 403
    assert query_only.get_json()["header"] == "X-Maintenance-Bypass-Token"

    header_ok = client.get(
        "/api/private?maintenance_bypass_token=wrong-query-token",
        headers={"User-Agent": "curl/8", "X-Maintenance-Bypass-Token": token},
    )
    assert header_ok.status_code == 200
    assert header_ok.get_json()["ok"] is True

    header_bad = client.get(
        "/api/private",
        headers={"User-Agent": "curl/8", "X-Maintenance-Bypass-Token": "wrong-header-token"},
    )
    assert header_bad.status_code == 403

    transcript = json.dumps(
        {
            "query_only": query_only.get_json(),
            "header_bad": header_bad.get_json(),
            "events": events,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "secret-maintenance-token" not in transcript
    assert "wrong-query-token" not in transcript
    assert "wrong-header-token" not in transcript


def test_x_forwarded_for_is_ignored_unless_remote_addr_is_trusted_proxy():
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "198.51.100.10"},
        headers={"X-Forwarded-For": "203.0.113.7"},
    ):
        assert get_client_ip(request, use_xff=False, trusted_proxy_ips={"198.51.100.10"}) == "198.51.100.10"
        assert get_client_ip(request, use_xff=True, trusted_proxy_ips={"192.0.2.1"}) == "198.51.100.10"
        assert get_client_ip(request, use_xff=True, trusted_proxy_ips={"198.51.100.10"}) == "203.0.113.7"

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "198.51.100.10"},
        headers={"X-Forwarded-For": "not-an-ip"},
    ):
        assert get_client_ip(request, use_xff=True, trusted_proxy_ips={"198.51.100.10"}) == "198.51.100.10"


def test_backpressure_preserves_fast_lane_root_priority_and_heavy_limits():
    app = Flask(__name__)
    app.testing = True
    install_backpressure(
        app,
        settings_provider=lambda: {
            "server_backpressure_enabled": True,
            "server_backpressure_mode": "manual",
            "server_backpressure_thread_capacity": 6,
            "server_backpressure_normal_limit": 1,
            "server_backpressure_heavy_limit": 1,
            "server_backpressure_root_priority_enabled": True,
            "server_backpressure_root_limit": 1,
            "server_backpressure_fast_lane_reserved": 1,
            "server_backpressure_retry_after_seconds": 2,
            "server_backpressure_refresh_seconds": 60,
        },
        root_priority_detector=lambda: True,
    )

    @app.route("/api/version")
    def version_probe():
        return jsonify({"ok": True})

    @app.route("/api/normal")
    def normal_probe():
        return jsonify({"ok": True})

    @app.route("/api/root/points/report")
    def root_probe():
        return jsonify({"ok": True, "root": True})

    @app.route("/api/files/upload", methods=["POST"])
    def heavy_probe():
        return jsonify({"ok": True})

    client = app.test_client()
    state = app.config["HACKME_BACKPRESSURE"]

    normal_lease = state["normal"].acquire()
    try:
        blocked_normal = client.get("/api/normal")
        assert blocked_normal.status_code == 503
        assert blocked_normal.get_json()["error"] == "server_busy"

        fast_lane = client.get("/api/version")
        assert fast_lane.status_code == 200
        assert fast_lane.get_json()["ok"] is True

        root_priority = client.get("/api/root/points/report")
        assert root_priority.status_code == 200
        assert root_priority.get_json()["root"] is True
    finally:
        normal_lease.release()

    heavy_lease = state["heavy"].acquire()
    try:
        blocked_heavy = client.post("/api/files/upload")
        assert blocked_heavy.status_code == 503
        assert blocked_heavy.get_json()["gate"] == "heavy"
        assert blocked_heavy.headers["Retry-After"] == "2"
    finally:
        heavy_lease.release()
