import json

from flask import Flask, jsonify

import routes.trading as trading_routes
from routes.trading import register_trading_routes


class _FakeBinanceResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _app(actor, check_user_rate_limit=None):
    app = Flask(__name__)
    app.testing = True

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(app, {
        "trading_service": object(),
        "get_current_user_ctx": lambda: actor,
        "json_resp": json_resp,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "check_user_rate_limit": check_user_rate_limit or (lambda *args, **kwargs: (False, {})),
    })
    return app


def _btc_signal_app(actor, project_dir):
    app = Flask(__name__)
    app.testing = True

    class FakeTradingService:
        def get_root_settings(self):
            return {"settings": {"btc_trade_project_dir": str(project_dir or "")}}

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(app, {
        "trading_service": FakeTradingService(),
        "get_current_user_ctx": lambda: actor,
        "json_resp": json_resp,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
    })
    return app


def test_trading_reference_prices_proxy_maps_usdt_markets_to_binance(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _FakeBinanceResponse([
            [1714500000000, "60000", "61000", "59000", "60500.5"],
            [1714503600000, "60500", "62000", "60400", "61800.25"],
        ])

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=1h&limit=48")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["source"] == "binance_public_api"
    assert payload["market"] == "BTC/USDT"
    assert payload["display_market"] == "BTC/USDT"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["usdt_to_points_rate"] == 1
    assert payload["candles"][0]["open_usdt"] == 60000
    assert payload["candles"][0]["high_usdt"] == 61000
    assert payload["candles"][0]["low_usdt"] == 59000
    assert payload["candles"][0]["close_usdt"] == 60500.5
    assert payload["candles"][0]["close_points"] == 60500.5
    assert payload["points"][0]["price_points"] == 60500.5
    assert "symbol=BTCUSDT" in captured["url"]
    assert "interval=1h" in captured["url"]
    assert captured["timeout"] == 6


def test_btc_trade_signal_hidden_when_project_missing(tmp_path):
    client = _btc_signal_app({"id": 1, "username": "alice", "role": "user"}, tmp_path / "missing").test_client()

    response = client.get("/api/trading/btc-signal?market=BTC/USDT")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["available"] is False
    assert payload["hidden"] is True


def test_btc_trade_signal_reads_latest_report(tmp_path):
    project = tmp_path / "BTC_trade"
    runtime = project / "runtime"
    runtime.mkdir(parents=True)
    (project / "hourly_check.py").write_text("# test", encoding="utf-8")
    (project / "update_data.py").write_text("# test", encoding="utf-8")
    (project / "backtest_report.py").write_text("# test", encoding="utf-8")
    (runtime / "report_log_4h.jsonl").write_text(
        "\n".join([
            json.dumps({"bar_ts": "old", "signal_ok": False, "current_price": 1}),
            json.dumps({
                "bar_ts": "2026-05-02T00:00:00",
                "signal_ok": True,
                "ml_ok": True,
                "position": "LONG",
                "current_price": 77059.5,
                "entry_checks": {"MA50": True},
                "ml_status": {"situation": "三多", "blocked": False},
            }),
        ]),
        encoding="utf-8",
    )
    (runtime / "portfolio_state_4h.json").write_text(json.dumps({"position": "LONG", "btc": 0.1}), encoding="utf-8")
    (runtime / "trade_log_4h.json").write_text(json.dumps([{"action": "ENTRY", "timestamp": "2026-05-02"}]), encoding="utf-8")
    client = _btc_signal_app({"id": 1, "username": "alice", "role": "user"}, project).test_client()

    response = client.get("/api/trading/btc-signal?market=BTC/POINTS")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["available"] is True
    assert payload["hidden"] is False
    assert payload["signal"]["current_price"] == 77059.5
    assert payload["signal"]["signal_ok"] is True
    assert payload["signal"]["ml_status"]["situation"] == "三多"
    assert payload["signal"]["portfolio"]["position"] == "LONG"
    assert payload["signal"]["last_trade"]["action"] == "ENTRY"
    assert payload["signal"]["prediction_interval_seconds"] == 14400
    assert payload["signal"]["next_prediction_at"]
    assert payload["signal"]["next_prediction_seconds"] >= 0


def test_root_btc_trade_check_reports_initialization_needed(tmp_path):
    client = _btc_signal_app({"id": 1, "username": "root", "role": "super_admin"}, tmp_path / "BTC_trade").test_client()

    response = client.post("/api/root/trading/btc-trade/check", json={"project_dir": str(tmp_path / "BTC_trade")})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"]["available"] is False
    assert payload["status"]["needs_initialization"] is True
    assert "hourly_check" in payload["status"]["missing"]


def test_trading_reference_prices_defaults_to_15m_chart_interval(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        return _FakeBinanceResponse([
            [1714500000000, "60000", "61000", "59000", "60500.5"],
        ])

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.get("/api/trading/reference-prices?market=BTC/USDT")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["interval"] == "15m"
    assert "interval=15m" in captured["url"]


def test_trading_reference_prices_uses_short_server_side_cache(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    calls = {"count": 0}

    def fake_urlopen(request, timeout=0):
        calls["count"] += 1
        return _FakeBinanceResponse([
            [1714500000000, "60000", "61000", "59000", "60500.5"],
        ])

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    first = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=5m")
    second = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=5m")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["count"] == 1


def test_trading_reference_prices_falls_back_to_last_good_cache(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    clock = {"value": 100.0}

    def fake_monotonic():
        return clock["value"]

    def ok_urlopen(request, timeout=0):
        return _FakeBinanceResponse([
            [1714500000000, "60000", "61000", "59000", "60500.5"],
        ])

    monkeypatch.setattr(trading_routes.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(trading_routes, "urlopen", ok_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    first = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=15m&limit=24")
    assert first.status_code == 200
    assert first.get_json()["source"] == "binance_public_api"

    clock["value"] = 200.0

    def failing_urlopen(*args, **kwargs):
        raise OSError("binance down")

    monkeypatch.setattr(trading_routes, "urlopen", failing_urlopen)
    second = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=15m&limit=24")

    assert second.status_code == 200
    payload = second.get_json()
    assert payload["ok"] is True
    assert payload["source"] == "binance_public_api_cached"
    assert payload["stale"] is True
    assert payload["candles"][0]["close_points"] == 60500.5


def test_trading_reference_prices_falls_back_to_coinbase_candles(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    urls = []

    def fake_urlopen(request, timeout=0):
        urls.append(request.full_url)
        if "api.binance.com" in request.full_url:
            raise OSError("binance down")
        return _FakeBinanceResponse([
            [1714503600, 60400, 62000, 60500, 61800.25, 12.5],
            [1714500000, 59000, 61000, 60000, 60500.5, 10.5],
        ])

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=15m&limit=24")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["source"] == "coinbase_exchange"
    assert payload["symbol"] == "BTC-USD"
    assert payload["candles"][0]["open_usdt"] == 60000
    assert payload["candles"][0]["close_points"] == 60500.5
    assert any("api.binance.com" in url for url in urls)
    assert any("api.exchange.coinbase.com/products/BTC-USD/candles" in url for url in urls)


def test_trading_reference_prices_walks_public_fallback_chain_to_bitstamp(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    urls = []

    def fake_urlopen(request, timeout=0):
        urls.append(request.full_url)
        if "bitstamp.net" in request.full_url:
            return _FakeBinanceResponse({
                "data": {
                    "ohlc": [
                        {
                            "timestamp": "1714500000",
                            "open": "60000",
                            "high": "61000",
                            "low": "59000",
                            "close": "60500.5",
                        },
                        {
                            "timestamp": "1714500900",
                            "open": "60500",
                            "high": "62000",
                            "low": "60400",
                            "close": "61800.25",
                        },
                    ]
                }
            })
        raise OSError("provider unavailable")

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=15m&limit=24")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["source"] == "bitstamp_public_api"
    assert payload["symbol"] == "btcusd"
    assert payload["candles"][0]["open_usdt"] == 60000
    assert payload["candles"][1]["close_points"] == 61800.25
    expected_hosts = (
        "api.binance.com",
        "okx.com",
        "api.exchange.coinbase.com",
        "api.kraken.com",
        "api.gemini.com",
        "bitstamp.net",
    )
    seen_hosts = [host for host in expected_hosts if any(host in url for url in urls)]
    assert seen_hosts == list(expected_hosts)


def test_trading_reference_prices_rejects_too_short_chart_intervals(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    called = {"value": False}

    def fake_urlopen(*args, **kwargs):
        called["value"] = True
        raise AssertionError("network should not be called")

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    for interval in ("1s", "1m"):
        response = client.get(f"/api/trading/reference-prices?market=BTC/USDT&interval={interval}")
        assert response.status_code == 400
        assert response.get_json()["ok"] is False
    assert called["value"] is False


def test_trading_reference_prices_latest_mode_fetches_one_candle(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        return _FakeBinanceResponse([
            [1714500000000, "60000", "61000", "59000", "60500.5"],
        ])

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=15m&limit=96&latest=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["latest_only"] is True
    assert len(payload["candles"]) == 1
    assert "limit=1" in captured["url"]
    assert "interval=15m" in captured["url"]


def test_trading_reference_prices_rejects_unsupported_market_without_network(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    called = {"value": False}

    def fake_urlopen(*args, **kwargs):
        called["value"] = True
        raise AssertionError("network should not be called")

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    client = _app({"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.get("/api/trading/reference-prices?market=DOGE/POINTS")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert called["value"] is False


def test_trading_reference_prices_rate_limits_before_binance_proxy(monkeypatch):
    trading_routes.REFERENCE_PRICE_CACHE.clear()
    called = {"value": False}

    def fake_urlopen(*args, **kwargs):
        called["value"] = True
        raise AssertionError("network should not be called after rate limit")

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)
    seen = {}

    def fake_rate_limit(user_id, action, max_req, window_sec):
        seen.update({"user_id": user_id, "action": action, "max_req": max_req, "window_sec": window_sec})
        return True, {"retry_after": 17}

    client = _app({"id": 7, "username": "alice", "role": "user"}, check_user_rate_limit=fake_rate_limit).test_client()

    response = client.get("/api/trading/reference-prices?market=BTC/USDT")

    assert response.status_code == 429
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["retry_after"] == 17
    assert seen == {"user_id": 7, "action": "trading_reference_prices", "max_req": 120, "window_sec": 60}
    assert called["value"] is False


def test_root_trading_routes_reject_manual_price_cheat_controls():
    class FakeTradingService:
        def update_root_settings(self, **kwargs):
            raise AssertionError("manual price source should be rejected before service call")

        def update_market(self, **kwargs):
            raise AssertionError("manual market price should be rejected before service call")

    app = Flask(__name__)
    app.testing = True

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(app, {
        "trading_service": FakeTradingService(),
        "get_current_user_ctx": lambda: {"id": 1, "username": "root", "role": "super_admin"},
        "json_resp": json_resp,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
    })
    client = app.test_client()

    source_response = client.post("/api/root/trading/settings", json={"settings": {"price_source": "manual_root"}})
    price_response = client.post("/api/root/trading/markets/BTC%2FPOINTS", json={"manual_price_points": 1})

    assert source_response.status_code == 400
    assert source_response.get_json()["ok"] is False
    assert price_response.status_code == 400
    assert price_response.get_json()["ok"] is False
