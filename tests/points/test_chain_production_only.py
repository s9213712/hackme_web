"""Phase 7 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — chain sealing mode guard.

Locks PointsChain block sealing to production and isolated dev_ready
runtimes. Production is the live sealing mode; dev_ready is allowed so
pre-release load tests can exercise block packaging before the runtime is
cleared for launch.

Each test exercises the guard with a different mode and asserts:
1. Disallowed modes raise ChainModeViolation BEFORE any SQL runs.
2. The violation records a `chain_mode_violation` security event.
3. Allowed modes let the seal path proceed (we don't drive the
   actual seal — just verify the guard returns).
4. Mode-reader exceptions / missing reader fail closed (refuse the write).
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from services import points_chain


def _service(mode_reader, recorder=None):
    db_path = Path(tempfile.mkdtemp()) / "phase7.sqlite"

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    return points_chain.PointsLedgerService(
        get_db=get_db,
        chain_secret="phase7-test-secret",
        mode_reader=mode_reader,
        security_event_recorder=recorder or (lambda *a, **kw: None),
    )


def test_seal_block_in_internal_test_raises():
    svc = _service(mode_reader=lambda: "internal_test")
    with pytest.raises(points_chain.ChainModeViolation) as exc:
        svc.seal_block()
    assert exc.value.mode == "internal_test"
    assert exc.value.action == "seal_block"


def test_seal_block_in_test_raises():
    svc = _service(mode_reader=lambda: "test")
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_seal_block_in_dev_ready_passes_guard():
    svc = _service(mode_reader=lambda: "dev_ready")
    try:
        result = svc.seal_block()
    except points_chain.ChainModeViolation:
        pytest.fail("dev_ready mode unexpectedly raised ChainModeViolation")
    except Exception:
        pass
    else:
        assert isinstance(result, dict)


def test_seal_block_in_maintenance_raises():
    svc = _service(mode_reader=lambda: "maintenance")
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_seal_block_in_incident_lockdown_raises():
    svc = _service(mode_reader=lambda: "incident_lockdown")
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_seal_block_in_superweak_raises():
    """superweak weakens many controls but NOT chain writes. Chain stays
    production-only regardless of how broken the rest of the surface is."""
    svc = _service(mode_reader=lambda: "superweak")
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_no_mode_reader_fails_closed():
    """If no mode_reader is configured, refuse the write — never default
    to production. Chain integrity > convenience."""
    db_path = Path(tempfile.mkdtemp()) / "phase7.sqlite"

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    svc = points_chain.PointsLedgerService(
        get_db=get_db,
        chain_secret="phase7-test-secret",
        # mode_reader unset
    )
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_mode_reader_exception_fails_closed():
    """Mode reader that raises must be treated as non-production."""
    def boom():
        raise RuntimeError("DB unavailable")

    svc = _service(mode_reader=boom)
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_violation_records_security_event():
    events = []

    def record(event_type, **kwargs):
        events.append({"event_type": event_type, **kwargs})

    svc = _service(mode_reader=lambda: "internal_test", recorder=record)
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()
    assert any(ev["event_type"] == "chain_mode_violation" for ev in events), events
    sample = next(ev for ev in events if ev["event_type"] == "chain_mode_violation")
    assert "internal_test" in sample.get("detail", "")
    assert "seal_block" in sample.get("detail", "")


def test_violation_recorder_exception_does_not_swallow_violation():
    """Even if the recorder itself crashes, the violation must still raise."""
    def bad_recorder(event_type, **kwargs):
        raise ValueError("recorder broken")

    svc = _service(mode_reader=lambda: "test", recorder=bad_recorder)
    with pytest.raises(points_chain.ChainModeViolation):
        svc.seal_block()


def test_production_mode_passes_guard():
    """In production the guard returns without raising. The seal then
    proceeds to ensure_schema / BEGIN — we don't drive the real seal here,
    just confirm the guard itself is the only thing that matters for this test."""
    svc = _service(mode_reader=lambda: "production")
    # The seal path will fail later (no schema, no ledger rows), but it
    # must NOT fail with ChainModeViolation.
    try:
        result = svc.seal_block()
    except points_chain.ChainModeViolation:
        pytest.fail("production mode unexpectedly raised ChainModeViolation")
    except Exception:
        # Other failures (e.g. schema / DB state) are out of scope here.
        pass
    else:
        # If it actually succeeded, that's also fine.
        assert isinstance(result, dict)


def test_strict_equality_for_allowed_modes():
    """Only exact allowed mode strings pass. Case, aliases, and partial
    matches are treated as disallowed."""
    for spoof in ("PRODUCTION", "prod", "production ", " production", "produc", "produktion", "DEV_READY", "dev", "dev_ready ", " dev_ready", ""):
        svc = _service(mode_reader=lambda spoof=spoof: spoof)
        with pytest.raises(points_chain.ChainModeViolation):
            svc.seal_block()
