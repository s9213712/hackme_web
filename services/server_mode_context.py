"""Server Mode v2 — request-scoped context.

Phase 1 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md.

Centralizes the (mode, tester_id, actor_role, request_id) tuple that
later phases (routing, chain guard, cache, trading dual-engine) all
need to consult. Without this, each before_request hook reads server
mode independently and tester scope information is rebuilt ad hoc.

This module deliberately has **no Flask-app or DB dependencies of its
own** — the integrating module (server.py) injects readers as
callables. That keeps service-layer code testable in isolation.

Spec contracts:
    1. `SmV2Context` is immutable for the lifetime of a request
       (`@dataclass(frozen=True)`).
    2. `attach_to_g` MUST run as the very first before_request hook so
       every later hook / route can read `current_ctx()`.
    3. `current_ctx()` raises if called before attach (defensive — we
       refuse to silently default to production).
    4. `tester_id` is non-None ONLY when the request authenticated via
       a tester token (X-Tester-Token / X-Internal-Test-Token /
       Authorization: Bearer). Plain session-cookie users have
       `tester_id=None` even if their `actor_role == "user"`.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Callable, Optional

from flask import g, has_request_context


@dataclass(frozen=True)
class SmV2Context:
    """Immutable per-request snapshot of Server Mode v2 routing inputs."""

    mode: str
    tester_id: Optional[int]
    actor_role: Optional[str]
    request_id: str


def _new_request_id() -> str:
    return secrets.token_hex(8)


def _safe_call(fn: Optional[Callable], default):
    if fn is None:
        return default
    try:
        return fn()
    except Exception:
        return default


def attach_to_g(
    *,
    mode_reader: Callable[[], str],
    tester_id_reader: Optional[Callable[[], Optional[int]]] = None,
    actor_role_reader: Optional[Callable[[], Optional[str]]] = None,
    request_id_factory: Optional[Callable[[], str]] = None,
) -> SmV2Context:
    """Build a fresh SmV2Context and attach it to flask.g.smv2_ctx.

    Returns the attached context. Raises if called outside a Flask
    request context.

    All four readers are injected so this module has no transitive
    dependency on server.py / DB / auth — making it trivial to unit
    test and reuse.
    """
    if not has_request_context():
        raise RuntimeError("attach_to_g called outside request context")
    mode_value = _safe_call(mode_reader, default="test")
    if not isinstance(mode_value, str) or not mode_value:
        mode_value = "test"
    tester_id_value = _safe_call(tester_id_reader, default=None)
    if tester_id_value is not None:
        try:
            tester_id_value = int(tester_id_value)
        except (TypeError, ValueError):
            tester_id_value = None
    actor_role_value = _safe_call(actor_role_reader, default=None)
    if actor_role_value is not None and not isinstance(actor_role_value, str):
        actor_role_value = str(actor_role_value)
    rid = _safe_call(request_id_factory, default=None) or _new_request_id()
    ctx = SmV2Context(
        mode=mode_value,
        tester_id=tester_id_value,
        actor_role=actor_role_value,
        request_id=rid,
    )
    g.smv2_ctx = ctx
    return ctx


def current_ctx() -> SmV2Context:
    """Return the SmV2Context attached to this request.

    Raises RuntimeError if called before `attach_to_g` ran for the
    current request — this is intentional. Silently defaulting to
    production-mode would let bugs slip through; a loud failure makes
    them visible in the very first test.
    """
    if not has_request_context():
        raise RuntimeError("current_ctx called outside request context")
    ctx = getattr(g, "smv2_ctx", None)
    if ctx is None:
        raise RuntimeError(
            "smv2_ctx not attached — register attach_smv2_ctx as the first before_request hook"
        )
    return ctx


def assert_ctx(ctx: Optional[SmV2Context]) -> SmV2Context:
    """Service-layer guard. Use when receiving a ctx parameter.

    Refuses None — every service that branches on mode MUST be passed
    a real ctx. We never silently default to production-mode, even at
    cost of a noisier API.
    """
    if ctx is None:
        raise RuntimeError("SmV2Context is required; refusing to default")
    return ctx
