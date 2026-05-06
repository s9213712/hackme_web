from services.server.startup import measure_backtest_capacity_if_needed
from services.trading import backtest_capacity as backtest_capacity_module


def test_measure_backtest_capacity_if_needed_skips_when_measurement_already_exists():
    class FakeTradingService:
        def get_backtest_capacity_measurement(self):
            return {"measured_at": "2026-05-06T12:00:00"}

    audit_calls = []
    worker = measure_backtest_capacity_if_needed(
        trading_service=FakeTradingService(),
        audit=lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )

    assert worker is None
    assert audit_calls == []


def test_measure_backtest_capacity_if_needed_records_probe_result(monkeypatch):
    class FakeTradingService:
        def __init__(self):
            self.recorded = None

        def get_backtest_capacity_measurement(self):
            return {}

        def get_backtest_capacity_time_budget_seconds(self):
            return 75

        def record_backtest_capacity_measurement(self, **kwargs):
            self.recorded = kwargs

    fake_result = {
        "measured_capacity_min": 12345,
        "measured_capacity_max": 67890,
        "measured_at": "2026-05-06T12:34:56",
        "bottleneck_strategy": "workflow:swing_bb_ma50",
        "fastest_strategy": "conditional",
    }
    monkeypatch.setattr(backtest_capacity_module, "measure_backtest_capacity", lambda **kwargs: fake_result)

    audit_calls = []
    service = FakeTradingService()
    worker = measure_backtest_capacity_if_needed(
        trading_service=service,
        audit=lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )
    assert worker is not None
    worker.join(timeout=2)

    assert service.recorded == {
        "measured_capacity_min": 12345,
        "measured_capacity_max": 67890,
        "measured_at": "2026-05-06T12:34:56",
        "bottleneck_strategy": "workflow:swing_bb_ma50",
        "fastest_strategy": "conditional",
        "actor_id": "system-startup",
    }
    assert audit_calls
    assert audit_calls[0][0][0] == "TRADING_BACKTEST_CAPACITY_PROBE_DONE"
    assert audit_calls[0][1]["success"] is True
