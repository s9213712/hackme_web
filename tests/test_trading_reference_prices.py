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


def _app(actor):
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


def test_trading_reference_prices_defaults_to_fastest_supported_spot_interval(monkeypatch):
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
    assert payload["interval"] == "1s"
    assert "interval=1s" in captured["url"]


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

    first = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=1s")
    second = client.get("/api/trading/reference-prices?market=BTC/USDT&interval=1s")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["count"] == 1


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
