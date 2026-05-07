from types import SimpleNamespace

import pytest

from scripts.security.pentest import stress_test


def _args(**overrides):
    base = {
        "target": "http://127.0.0.1:5000",
        "mode": "count",
        "requests": 6,
        "duration_seconds": 1,
        "max_requests": 20,
        "concurrency": 2,
        "burst_size": 1,
        "burst_interval_ms": 0,
        "paths": "/,/api/version",
        "timeout": 1.0,
        "out": "runtime/reports/security",
        "i_own_this_target": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_stress_run_count_mode_completes_requested_count(monkeypatch):
    monkeypatch.setattr(
        stress_test,
        "request_once",
        lambda base_url, path, timeout: {"path": path, "status": 200, "elapsed_ms": 5.0},
    )

    summary = stress_test.run(_args(requests=7, concurrency=3))

    assert summary["mode"] == "count"
    assert summary["requests"] == 7
    assert summary["request_goal"] == 7
    assert summary["duration_seconds_requested"] is None
    assert summary["failed_count"] == 0


def test_stress_run_duration_mode_stops_at_safety_cap(monkeypatch):
    monkeypatch.setattr(
        stress_test,
        "request_once",
        lambda base_url, path, timeout: {"path": path, "status": 200, "elapsed_ms": 2.0},
    )

    summary = stress_test.run(
        _args(
            mode="duration",
            duration_seconds=30,
            max_requests=9,
            concurrency=4,
            burst_size=3,
            burst_interval_ms=1,
        )
    )

    assert summary["mode"] == "duration"
    assert summary["requests"] == 9
    assert summary["request_goal"] is None
    assert summary["duration_seconds_requested"] == 30
    assert summary["max_requests"] == 9
    assert summary["burst_size"] == 3
    assert summary["burst_interval_ms"] == 1


def test_stress_refuses_non_local_target_without_explicit_opt_in():
    with pytest.raises(SystemExit, match="Refusing non-local target"):
        stress_test.run(_args(target="https://example.com", i_own_this_target=False))
