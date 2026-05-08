import pytest

from services.server import startup


class _LoopExit(BaseException):
    pass


class _ThreadStub:
    def __init__(self, *, target, name=None, daemon=None):
        self.target = target
        self.name = name
        self.daemon = daemon

    def start(self):
        return None


def _capture_thread(monkeypatch):
    holder = {}

    def factory(*, target, name=None, daemon=None):
        thread = _ThreadStub(target=target, name=name, daemon=daemon)
        holder["thread"] = thread
        return thread

    monkeypatch.setattr(startup.threading, "Thread", factory)
    return holder


def test_points_worker_skips_when_economy_feature_disabled(monkeypatch):
    holder = _capture_thread(monkeypatch)
    calls = {"backup": 0, "seal": 0}

    class PointsStub:
        def create_scheduled_backup_if_due(self):
            calls["backup"] += 1
            return {"created": False}

        def seal_due_block(self, **kwargs):
            calls["seal"] += 1
            return {"sealed": False}

    monkeypatch.setattr(startup.time, "sleep", lambda seconds: (_ for _ in ()).throw(_LoopExit()))

    startup.start_points_chain_block_worker(
        points_service=PointsStub(),
        audit=lambda *args, **kwargs: None,
        default_block_ledger_threshold=10,
        default_block_max_interval_seconds=60,
        get_system_settings=lambda: {"feature_economy_enabled": False},
    )

    with pytest.raises(_LoopExit):
        holder["thread"].target()

    assert calls == {"backup": 0, "seal": 0}


def test_trading_liquidation_worker_skips_when_trading_feature_disabled(monkeypatch):
    holder = _capture_thread(monkeypatch)
    calls = {"match": 0, "liquidate": 0}

    class TradingStub:
        def match_open_limit_orders(self, **kwargs):
            calls["match"] += 1
            return {"matched": [], "errors": []}

        def scan_margin_liquidations(self, **kwargs):
            calls["liquidate"] += 1
            return {"liquidated": [], "errors": []}

    monkeypatch.setattr(startup.time, "sleep", lambda seconds: (_ for _ in ()).throw(_LoopExit()))

    startup.start_trading_liquidation_worker(
        trading_service=TradingStub(),
        audit=lambda *args, **kwargs: None,
        get_system_settings=lambda: {
            "feature_economy_enabled": True,
            "feature_trading_enabled": False,
        },
    )

    with pytest.raises(_LoopExit):
        holder["thread"].target()

    assert calls == {"match": 0, "liquidate": 0}


def test_points_worker_honors_pre_set_shutdown_event(monkeypatch):
    holder = _capture_thread(monkeypatch)
    calls = {"backup": 0, "seal": 0}

    class PointsStub:
        def create_scheduled_backup_if_due(self):
            calls["backup"] += 1
            return {"created": False}

        def seal_due_block(self, **kwargs):
            calls["seal"] += 1
            return {"sealed": False}

    stop_event = startup.threading.Event()
    stop_event.set()

    startup.start_points_chain_block_worker(
        points_service=PointsStub(),
        audit=lambda *args, **kwargs: None,
        default_block_ledger_threshold=10,
        default_block_max_interval_seconds=60,
        get_system_settings=lambda: {"feature_economy_enabled": True},
        shutdown_event=stop_event,
    )

    holder["thread"].target()
    assert calls == {"backup": 0, "seal": 0}


def test_trading_bot_worker_honors_pre_set_shutdown_event(monkeypatch):
    holder = _capture_thread(monkeypatch)
    calls = {"scan": 0}

    class TradingStub:
        def get_root_settings(self):
            return {"settings": {"enabled": True, "bot_auto_scan_enabled": True, "bot_auto_scan_interval_seconds": 30}}

        def run_due_trading_bots(self, **kwargs):
            calls["scan"] += 1
            return {"triggered": [], "failed": [], "scanned": 0}

    stop_event = startup.threading.Event()
    stop_event.set()

    startup.start_trading_bot_worker(
        trading_service=TradingStub(),
        audit=lambda *args, **kwargs: None,
        get_system_settings=lambda: {"feature_economy_enabled": True, "feature_trading_enabled": True},
        shutdown_event=stop_event,
    )

    holder["thread"].target()
    assert calls == {"scan": 0}
