import sqlite3

from flask import Flask, jsonify, make_response

from routes.system_admin import register_system_admin_routes
from services import settings
from server import feature_gate_for_path


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def test_feature_settings_roundtrip_and_ignore_unknown_keys(tmp_path):
    db_path = tmp_path / "settings.db"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    original_state = dict(settings._STATE)
    original_cache = settings._SYSTEM_SETTINGS
    try:
        settings.configure_settings_service(get_db=get_db, load_json=lambda path: {}, base_dir=str(tmp_path))
        conn = get_db()
        settings.init_system_settings_table(conn)
        settings._seed_missing_settings_to_db(conn)
        conn.commit()
        conn.close()
        settings.refresh_system_settings()

        updates = settings.save_feature_settings({
            "feature_chat_enabled": False,
            "feature_dm_enabled": True,
            "maintenance_mode": True,
            "unknown": True,
        })
        features = settings.get_feature_settings()

        assert updates == {"feature_chat_enabled": False, "feature_dm_enabled": True}
        assert features["feature_chat_enabled"] is False
        assert features["feature_dm_enabled"] is True
        assert settings.get_system_settings()["maintenance_mode"] is False
    finally:
        settings._STATE.clear()
        settings._STATE.update(original_state)
        settings._SYSTEM_SETTINGS = original_cache


def test_feature_gate_maps_existing_modules():
    assert feature_gate_for_path("/api/chat/rooms") == "feature_chat_enabled"
    assert feature_gate_for_path("/api/community/boards") == "feature_community_enabled"
    assert feature_gate_for_path("/api/admin/users") == "feature_accounts_enabled"
    assert feature_gate_for_path("/api/admin/users/7/violation") == "feature_violation_center_enabled"
    assert feature_gate_for_path("/api/admin/audit") == "feature_audit_log_enabled"
    assert feature_gate_for_path("/api/admin/message-reports") == "feature_reports_enabled"
    assert feature_gate_for_path("/api/admin/settings") is None


def test_admin_features_endpoint_is_root_only():
    app = Flask(__name__)
    app.testing = True
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    feature_state = {"feature_chat_enabled": True, "feature_dm_enabled": False}

    register_system_admin_routes(app, {
        "ANCHOR_DIR": ".",
        "BASE_DIR": ".",
        "CHAT_DIR": ".",
        "DB_PATH": "missing.db",
        "LOG_DIR": ".",
        "SERVER_LOG_PATH": "server.log",
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": lambda: None,
        "get_feature_settings": lambda: dict(feature_state),
        "get_system_settings": lambda: {},
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {k: bool(v) for k, v in data.items() if k in feature_state},
        "save_settings": lambda data: data,
        "verify_audit_integrity": lambda: (True, None, "ok"),
    })
    client = app.test_client()

    res = client.get("/api/admin/features")
    assert res.status_code == 200
    assert res.get_json()["features"] == feature_state

    res = client.put("/api/admin/features", json={"feature_chat_enabled": False, "maintenance_mode": True})
    assert res.status_code == 200
    assert res.get_json()["features"] == {"feature_chat_enabled": False}

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    res = client.get("/api/admin/features")
    assert res.status_code == 403


def test_admin_member_level_rules_endpoint_is_root_only(tmp_path):
    db_path = tmp_path / "rules.db"
    app = Flask(__name__)
    app.testing = True
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_system_admin_routes(app, {
        "ANCHOR_DIR": ".",
        "BASE_DIR": ".",
        "CHAT_DIR": ".",
        "DB_PATH": str(db_path),
        "LOG_DIR": ".",
        "SERVER_LOG_PATH": "server.log",
        "activate_emergency_lockdown": lambda reason: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: {},
        "is_audit_chain_enabled": lambda: False,
        "json_resp": _json_resp,
        "repair_audit_chain": lambda **kwargs: {"entries_resealed": 0},
        "repair_violation_chains": lambda: {"entries_resealed": 0},
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "save_feature_settings": lambda data: {},
        "save_settings": lambda data: data,
        "verify_audit_integrity": lambda: (True, None, "ok"),
    })
    client = app.test_client()

    res = client.get("/api/admin/member-level-rules")
    assert res.status_code == 200
    assert any(rule["level"] == "normal" for rule in res.get_json()["rules"])

    res = client.put("/api/admin/member-level-rules/normal", json={"can_post": False, "daily_post_limit": 4})
    assert res.status_code == 200
    assert res.get_json()["rule"]["can_post"] is False
    assert res.get_json()["rule"]["daily_post_limit"] == 4

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    res = client.get("/api/admin/member-level-rules")
    assert res.status_code == 403
