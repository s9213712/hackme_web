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

from flask import Flask

from services import server_mode_context as smv2


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
