import sqlite3

from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema
from services.trading_price_streams import TradingPriceStreamHub


def _db(tmp_path):
    path = tmp_path / "trading_websocket_inputs.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO users (username, role, status) VALUES "
        "('alice', 'user', 'active'), "
        "('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _services(tmp_path, *, stream_hub=None):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    prices = {"BTC/POINTS": 80200, "ETH/POINTS": 5000}
    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: prices[symbol],
        stream_hub=stream_hub,
    )
    return get_db, points, trading


def _actor(user_id=2, username="root", role="super_admin"):
    return {"id": user_id, "username": username, "role": role}


class _FakeStreamHub:
    def __init__(self, *, state=None, ticker=None, orderbook=None):
        self.state = dict(state or {})
        self.ticker = ticker
        self.orderbook = orderbook

    def get_provider_state(self, source, market_symbol, *, provider_id=None, stale_after_seconds=10):
        return {
            "provider": source,
            "market_symbol": market_symbol,
            "provider_id": provider_id,
            "ws_supported": True,
            "transport": "websocket",
            "connected": True,
            "fallback": False,
            "stale": False,
            "degraded": False,
            "confidence": "high",
            "provider_count": 1,
            "last_update_at": "2026-05-05T00:00:00",
            "exclusion_reason": "",
            **self.state,
        }

    def get_ticker_snapshot(self, source, market_symbol, *, provider_id=None, stale_after_seconds=10):
        return self.ticker

    def get_orderbook_snapshot(self, source, market_symbol, *, provider_id=None, stale_after_seconds=10):
        return self.orderbook


def test_binance_ws_ticker_message_updates_snapshot():
    hub = TradingPriceStreamHub()
    hub._handle_binance_message("BTC/POINTS", {
        "stream": "btcusdt@ticker",
        "data": {"c": "80123.45", "E": 1_777_777_777_000},
    })

    snapshot = hub.get_ticker_snapshot("binance_public_api", "BTC/POINTS", provider_id="BTCUSDT")

    assert snapshot["price_points"] == 80123.45
    assert snapshot["transport"] == "websocket"
    assert snapshot["stale"] is False
    assert snapshot["degraded"] is False


def test_ws_malformed_ticker_payload_is_rejected():
    hub = TradingPriceStreamHub()
    hub._handle_binance_message("BTC/POINTS", {
        "stream": "btcusdt@ticker",
        "data": {"c": "not-a-number", "E": 1_777_777_777_000},
    })

    snapshot = hub.get_ticker_snapshot("binance_public_api", "BTC/POINTS", provider_id="")
    state = hub._state("binance_public_api", "BTC/POINTS")

    assert snapshot is None
    assert state["degraded"] is True
    assert state["exclusion_reason"] == "binance ticker price is invalid"


def test_ws_malformed_depth_payload_is_rejected():
    hub = TradingPriceStreamHub()
    hub._handle_coinbase_message("BTC/POINTS", {
        "type": "snapshot",
        "bids": [["bad", "1.2"]],
        "asks": [["80200.00", "1.2"]],
    })

    snapshot = hub.get_orderbook_snapshot("coinbase_exchange", "BTC/POINTS", provider_id="")
    state = hub._state("coinbase_exchange", "BTC/POINTS")

    assert snapshot is None
    assert state["degraded"] is True
    assert state["exclusion_reason"] == "coinbase depth snapshot is empty"


def test_binance_price_fetch_prefers_fresh_websocket_ticker(tmp_path, monkeypatch):
    stream_hub = _FakeStreamHub(
        ticker={
            "source": "binance_public_api",
            "price_points": 80321.12,
            "fetched_at": "2026-05-05T00:00:00",
            "latency_ms": 12.5,
            "transport": "websocket",
            "connected": True,
            "fallback": False,
            "stale": False,
            "degraded": False,
            "confidence": "high",
            "last_update_at": "2026-05-05T00:00:00",
            "exclusion_reason": "",
        },
    )
    get_db, _points, trading = _services(tmp_path, stream_hub=stream_hub)
    trading.live_price_provider = None
    with get_db() as conn:
        settings = trading._settings_payload(conn)
    called = {"http": 0}

    def fake_fetch_json(_url, *, timeout=5, user_agent="hackme_web/1.0 trading-price", with_meta=False):
        called["http"] += 1
        raise AssertionError("HTTP polling should not run while websocket ticker is fresh")

    monkeypatch.setattr(trading, "_fetch_json_url", fake_fetch_json)
    price, meta = trading._fetch_binance_price_points("BTC/POINTS", settings=settings, with_meta=True)

    assert price == 80321.12
    assert called["http"] == 0
    assert meta["connected"] is True
    assert meta["fallback"] is False
    assert meta["transport"] == "websocket"


def test_binance_price_fetch_falls_back_to_http_when_ws_unavailable(tmp_path, monkeypatch):
    stream_hub = _FakeStreamHub(
        state={
            "connected": False,
            "fallback": True,
            "degraded": True,
            "confidence": "low",
            "exclusion_reason": "websocket_disconnected",
        },
        ticker=None,
    )
    get_db, _points, trading = _services(tmp_path, stream_hub=stream_hub)
    trading.live_price_provider = None
    with get_db() as conn:
        settings = trading._settings_payload(conn)
    called = {"http": 0}

    def fake_fetch_json(_url, *, timeout=5, user_agent="hackme_web/1.0 trading-price", with_meta=False):
        called["http"] += 1
        payload = {"price": "80111.0"}
        meta = {"fetched_at": "2026-05-05T00:00:01", "latency_ms": 55.0}
        return (payload, meta) if with_meta else payload

    monkeypatch.setattr(trading, "_fetch_json_url", fake_fetch_json)

    price, meta = trading._fetch_binance_price_points("BTC/POINTS", settings=settings, with_meta=True)

    assert price == 80111.0
    assert called["http"] == 1
    assert meta["fallback"] is True
    assert meta["degraded"] is True
    assert meta["exclusion_reason"] == "websocket_disconnected"


def test_risk_grade_price_blocks_degraded_single_source_data(tmp_path, monkeypatch):
    get_db, _points, trading = _services(tmp_path)
    trading.live_price_provider = None
    trading.update_root_settings(
        actor=_actor(),
        settings={
            "price_source": "fused_weighted",
            "price_fusion_mode": "auto_depth",
            "price_fusion_min_provider_count": 3,
        },
        markets=[],
    )

    def qualified(source, quantity):
        return trading._build_orderbook_snapshot(
            source=source,
            bids=[[100.0, quantity], [99.0, quantity]],
            asks=[[100.1, quantity], [100.8, quantity]],
            fetch_meta={"fetched_at": "2026-05-05T00:00:00", "latency_ms": 40.0},
            max_levels=100,
            band_percent=1.0,
            request_limit=1000,
            transport_meta={
                "ws_supported": True,
                "transport": "websocket",
                "connected": True,
                "fallback": False,
                "stale": False,
                "degraded": False,
                "confidence": "high",
                "last_update_at": "2026-05-05T00:00:00",
                "exclusion_reason": "",
            },
        )

    def stale_partial(source):
        return trading._build_orderbook_snapshot(
            source=source,
            bids=[[100.0, 30.0], [99.98, 30.0]],
            asks=[[100.1, 30.0], [100.12, 30.0]],
            fetch_meta={"fetched_at": "2026-05-05T00:00:00", "latency_ms": 110.0},
            max_levels=100,
            band_percent=1.0,
            request_limit=1000,
            transport_meta={
                "ws_supported": True,
                "transport": "http_polling",
                "connected": False,
                "fallback": True,
                "stale": True,
                "degraded": True,
                "confidence": "low",
                "last_update_at": "2026-05-04T23:59:40",
                "exclusion_reason": "stale_websocket_provider",
            },
        )

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol, **_kwargs: stale_partial("binance_public_api"))
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", lambda _symbol, **_kwargs: stale_partial("okx_public_api"))
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", lambda _symbol, **_kwargs: qualified("coinbase_exchange", 400.0))
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", lambda _symbol, **_kwargs: stale_partial("kraken_public_api"))
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", lambda _symbol, **_kwargs: stale_partial("gemini_public_api"))
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", lambda _symbol, **_kwargs: stale_partial("bitstamp_public_api"))
    monkeypatch.setattr(
        trading,
        "_fetch_live_price_points",
        lambda _symbol, *, with_meta=False, settings=None: (
            100.05,
            "bitstamp_public_api",
            {
                "transport": "http_polling",
                "connected": False,
                "fallback": True,
                "stale": True,
                "degraded": True,
                "confidence": "low",
                "provider_count": 1,
                "last_update_at": "2026-05-05T00:00:00",
                "exclusion_reason": "provider_count_low",
                "latency_ms": 80.0,
            },
        ),
    )

    with get_db() as conn:
        settings = trading._settings_payload(conn)
    reference_price, details = trading._fetch_weighted_fused_price_points("BTC/POINTS", settings=settings)

    assert reference_price > 0
    assert details["reference_provider_count"] >= 1
    assert details["warnings"]
    assert details["high_risk_blocked"] is True
    assert details["risk_grade_price_points"] is None
    assert details["transport_state"]["degraded"] is True
    assert any(item["code"] == "provider_count_low" for item in details["warnings"])
