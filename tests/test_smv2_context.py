"""Phase 1 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — request-context module.

Locks in the four contracts of services/server_mode_context.py:

1. SmV2Context is immutable.
2. attach_to_g binds a fresh ctx to flask.g for the current request.
3. current_ctx raises if called before attach (no silent prod-default).
4. tester_id is None for plain session-cookie users; only filled when a
   request authenticates via a tester-token header.
"""

import pytest
from dataclasses import FrozenInstanceError

import hashlib
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, request

from services.server_mode import context as smv2
from services.server.request_guards import enforce_mode_restrictions
from services.server import security_runtime
from services.snapshots import ensure_snapshot_schema


def test_smv2_context_is_frozen():
    ctx = smv2.SmV2Context(mode="production", tester_id=None, actor_role=None, request_id="r1")
    with pytest.raises(FrozenInstanceError):
        ctx.mode = "test"  # type: ignore[misc]


def test_attach_to_g_outside_request_raises():
    with pytest.raises(RuntimeError):
        smv2.attach_to_g(mode_reader=lambda: "production")


def test_current_ctx_outside_request_raises():
    with pytest.raises(RuntimeError):
        smv2.current_ctx()


def test_current_ctx_before_attach_raises():
    """A request that never ran the attach hook must NOT silently default."""
    app = Flask(__name__)
    with app.test_request_context("/probe"):
        with pytest.raises(RuntimeError):
            smv2.current_ctx()


def test_attach_and_read_basic():
    app = Flask(__name__)
    with app.test_request_context("/probe"):
        ctx = smv2.attach_to_g(
            mode_reader=lambda: "internal_test",
            tester_id_reader=lambda: 7,
            actor_role_reader=lambda: "user",
        )
        assert ctx.mode == "internal_test"
        assert ctx.tester_id == 7
        assert ctx.actor_role == "user"
        assert ctx.request_id and isinstance(ctx.request_id, str)
        assert smv2.current_ctx() is ctx


def test_request_id_is_unique_per_attach():
    app = Flask(__name__)
    seen = set()
    for _ in range(20):
        with app.test_request_context("/probe"):
            ctx = smv2.attach_to_g(mode_reader=lambda: "test")
            seen.add(ctx.request_id)
    assert len(seen) == 20  # no collision in 20 attaches


def test_ctx_does_not_leak_between_requests():
    """Each request gets its own ctx — flask.g is request-scoped."""
    app = Flask(__name__)
    with app.test_request_context("/a"):
        ctx_a = smv2.attach_to_g(mode_reader=lambda: "production")
        assert ctx_a.mode == "production"
    with app.test_request_context("/b"):
        # New request: no ctx attached yet.
        with pytest.raises(RuntimeError):
            smv2.current_ctx()
        ctx_b = smv2.attach_to_g(mode_reader=lambda: "internal_test")
        assert ctx_b.mode == "internal_test"
        assert ctx_b.request_id != ctx_a.request_id


def test_mode_reader_failure_falls_back_to_test_not_production():
    """If the mode reader raises, ctx.mode must NOT silently become 'production'."""
    app = Flask(__name__)
    def boom():
        raise RuntimeError("DB unavailable")

    with app.test_request_context("/probe"):
        ctx = smv2.attach_to_g(mode_reader=boom)
        assert ctx.mode != "production"
        assert ctx.mode == "test"


def test_tester_id_reader_returns_none_by_default():
    app = Flask(__name__)
    with app.test_request_context("/probe"):
        ctx = smv2.attach_to_g(mode_reader=lambda: "test")
        assert ctx.tester_id is None
        assert ctx.actor_role is None


def test_tester_id_reader_coerces_to_int_or_none():
    app = Flask(__name__)
    with app.test_request_context("/a"):
        ctx = smv2.attach_to_g(
            mode_reader=lambda: "test",
            tester_id_reader=lambda: "42",  # str int
        )
        assert ctx.tester_id == 42
    with app.test_request_context("/b"):
        ctx = smv2.attach_to_g(
            mode_reader=lambda: "test",
            tester_id_reader=lambda: "not-a-number",
        )
        assert ctx.tester_id is None


def test_assert_ctx_refuses_none():
    """Service-layer guard rejects None — never silently default."""
    with pytest.raises(RuntimeError):
        smv2.assert_ctx(None)
    sample = smv2.SmV2Context(mode="production", tester_id=None, actor_role=None, request_id="r")
    assert smv2.assert_ctx(sample) is sample


def test_attach_via_before_request_hook():
    """Integration: hook-style usage matches the server.py wiring."""
    app = Flask(__name__)
    app.testing = True

    captured = []

    @app.before_request
    def attach():
        smv2.attach_to_g(mode_reader=lambda: "internal_test", tester_id_reader=lambda: 9)

    @app.route("/echo")
    def echo():
        ctx = smv2.current_ctx()
        captured.append(ctx)
        return {"mode": ctx.mode, "tester_id": ctx.tester_id, "request_id": ctx.request_id}

    client = app.test_client()
    r1 = client.get("/echo").get_json()
    r2 = client.get("/echo").get_json()
    assert r1["mode"] == "internal_test"
    assert r1["tester_id"] == 9
    assert r2["request_id"] != r1["request_id"]  # no leak across requests


def test_options_requests_skip_mode_restriction_ctx_lookup():
    app = Flask(__name__)

    def boom():
        raise AssertionError("smv2_current_ctx should not run for OPTIONS")

    with app.test_request_context("/api/unknown", method="OPTIONS"):
        result = enforce_mode_restrictions(
            request,
            get_system_settings=lambda: {},
            smv2_current_ctx=boom,
            has_valid_maintenance_bypass_func=lambda settings: False,
            get_current_user_ctx=lambda: None,
            path_is_root_recovery_allowed_during_lockdown_func=lambda path: False,
            revoke_user_sessions=lambda user_id: None,
            audit=lambda *args, **kwargs: None,
            get_client_ip=lambda: "127.0.0.1",
            maintenance_bypass_required_payload=lambda msg: {"ok": False, "msg": msg},
            json_resp=lambda payload, status=200: (payload, status),
            session_cookie_samesite="Lax",
            session_cookie_secure=False,
        )
        assert result is None


def test_tester_token_identity_reader_hydrates_ctx_and_caches_request_lookup(tmp_path):
    db_path = tmp_path / "tester.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_snapshot_schema(conn)
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            member_level TEXT,
            base_level TEXT,
            effective_level TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, role, status, member_level, base_level, effective_level) "
        "VALUES (7, 'smokeuser', 'user', 'active', 'normal', 'normal', 'normal')"
    )
    conn.execute("UPDATE server_modes SET current_mode='internal_test' WHERE id=1")
    token = "hmt_test_ctx"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now()
    conn.execute(
        """
        INSERT INTO tester_tokens
        (id, token_hash, tester_user_id, mode_scope_json, route_scope_json, method_scope_json,
         allowed_features_json, allowed_routes_json, expires_at, issued_at, nonce,
         max_requests_per_minute, can_modify_own_role, can_modify_own_points, can_run_security_tests,
         created_by, created_at, hmac_signature, key_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, '', '')
        """,
        (
            "tester_ctx",
            token_hash,
            7,
            '["test","internal_test"]',
            '["/api/trading"]',
            '["GET","POST"]',
            "[]",
            '["/api/trading"]',
            (now + timedelta(hours=1)).isoformat(),
            now.isoformat(),
            "nonce-ctx",
            60,
            now.isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    def get_db():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    app = Flask(__name__)
    with app.test_request_context("/api/trading/orders", method="POST", headers={"X-Tester-Token": token}):
        identity_1 = security_runtime.tester_token_identity_from_request(
            request,
            get_db=get_db,
            ensure_snapshot_schema=ensure_snapshot_schema,
            get_runtime_server_mode_func=lambda: "internal_test",
            record_security_event=lambda *args, **kwargs: None,
            get_client_ip_func=lambda: "127.0.0.1",
        )
        identity_2 = security_runtime.tester_token_identity_from_request(
            request,
            get_db=get_db,
            ensure_snapshot_schema=ensure_snapshot_schema,
            get_runtime_server_mode_func=lambda: "internal_test",
            record_security_event=lambda *args, **kwargs: None,
            get_client_ip_func=lambda: "127.0.0.1",
        )
        ctx = smv2.attach_to_g(
            mode_reader=lambda: "internal_test",
            tester_id_reader=lambda: security_runtime.tester_token_identity_from_request(
                request,
                get_db=get_db,
                ensure_snapshot_schema=ensure_snapshot_schema,
                get_runtime_server_mode_func=lambda: "internal_test",
                record_security_event=lambda *args, **kwargs: None,
                get_client_ip_func=lambda: "127.0.0.1",
            )["tester_id"],
            actor_role_reader=lambda: security_runtime.tester_token_identity_from_request(
                request,
                get_db=get_db,
                ensure_snapshot_schema=ensure_snapshot_schema,
                get_runtime_server_mode_func=lambda: "internal_test",
                record_security_event=lambda *args, **kwargs: None,
                get_client_ip_func=lambda: "127.0.0.1",
            )["actor_role"],
        )

    conn = get_db()
    request_logs = conn.execute(
        "SELECT COUNT(*) AS c FROM tester_token_request_log WHERE token_id='tester_ctx'"
    ).fetchone()["c"]
    conn.close()

    assert identity_1 == {"username": "smokeuser", "tester_id": 7, "actor_role": "user"}
    assert identity_2 == identity_1
    assert ctx.tester_id == 7
    assert ctx.actor_role == "user"
    assert request_logs == 1
