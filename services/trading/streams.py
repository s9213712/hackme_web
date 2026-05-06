import json
import math
import ssl
import threading
import time
from datetime import datetime

import websocket


WS_CAPABLE_PRICE_PROVIDERS = (
    "binance_public_api",
    "okx_public_api",
    "coinbase_exchange",
    "kraken_public_api",
)

_MAX_STORED_BOOK_LEVELS = 1200


def _now():
    return datetime.now().isoformat()


def _iso_from_exchange_ms(value):
    try:
        number = int(float(value))
    except Exception:
        return ""
    if number <= 0:
        return ""
    return datetime.fromtimestamp(number / 1000.0).isoformat()


def _ms_from_iso(value):
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except Exception:
        return None


def _float_or_none(value):
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _bool(value):
    return bool(value)


def _sorted_book_levels(levels_map, *, reverse):
    rows = []
    for price, size in (levels_map or {}).items():
        if price <= 0 or size <= 0:
            continue
        rows.append((float(price), float(size)))
    rows.sort(key=lambda row: row[0], reverse=reverse)
    return rows[:_MAX_STORED_BOOK_LEVELS]


def _kraken_ws_pair(provider_id):
    pair = str(provider_id or "").strip().upper()
    if pair == "XBTUSD":
        return "XBT/USD"
    if pair.endswith("USD") and len(pair) > 3:
        return f"{pair[:-3]}/USD"
    return pair


class TradingPriceStreamHub:
    def __init__(self, *, audit=None):
        self.audit = audit or (lambda *args, **kwargs: None)
        self._lock = threading.RLock()
        self._states = {}
        self._workers = {}

    def _key(self, provider, market_symbol):
        return (str(provider or "").strip(), str(market_symbol or "").strip().upper())

    def _state(self, provider, market_symbol):
        key = self._key(provider, market_symbol)
        with self._lock:
            return dict(self._states.get(key) or {})

    def _update_state(self, provider, market_symbol, **updates):
        key = self._key(provider, market_symbol)
        with self._lock:
            current = dict(self._states.get(key) or {})
            current.update(updates)
            current.setdefault("provider", key[0])
            current.setdefault("market_symbol", key[1])
            current.setdefault("ws_supported", key[0] in WS_CAPABLE_PRICE_PROVIDERS)
            current.setdefault("transport", "websocket")
            current.setdefault("fallback", False)
            current.setdefault("connected", False)
            current.setdefault("stale", False)
            current.setdefault("degraded", False)
            current.setdefault("confidence", "low")
            current.setdefault("provider_count", 1)
            current.setdefault("last_update_at", "")
            current.setdefault("exclusion_reason", "")
            current.setdefault("ticker_price_points", None)
            current.setdefault("ticker_updated_at", "")
            current.setdefault("depth_updated_at", "")
            current.setdefault("ticker_latency_ms", 0.0)
            current.setdefault("depth_latency_ms", 0.0)
            current.setdefault("bids_map", {})
            current.setdefault("asks_map", {})
            current.setdefault("error_count", 0)
            current.setdefault("malformed_count", 0)
            current.setdefault("disconnect_count", 0)
            self._states[key] = current

    def _mark_connected(self, provider, market_symbol):
        self._update_state(
            provider,
            market_symbol,
            connected=True,
            fallback=False,
            degraded=False,
            stale=False,
            confidence="high",
            exclusion_reason="",
        )

    def _mark_disconnected(self, provider, market_symbol, *, reason):
        current = self._state(provider, market_symbol)
        self._update_state(
            provider,
            market_symbol,
            connected=False,
            fallback=True,
            degraded=True,
            confidence="low",
            exclusion_reason=str(reason or "websocket disconnected")[:200],
            disconnect_count=int(current.get("disconnect_count") or 0) + 1,
            error_count=int(current.get("error_count") or 0) + 1,
        )

    def _mark_malformed(self, provider, market_symbol, *, reason):
        current = self._state(provider, market_symbol)
        self._update_state(
            provider,
            market_symbol,
            degraded=True,
            confidence="low",
            exclusion_reason=str(reason or "malformed websocket payload")[:200],
            malformed_count=int(current.get("malformed_count") or 0) + 1,
            error_count=int(current.get("error_count") or 0) + 1,
        )

    def _publish_ticker(self, provider, market_symbol, *, price_points, exchange_ms=None):
        now_iso = _now()
        latency_ms = 0.0
        if exchange_ms:
            latency_ms = max(0.0, round((time.time() * 1000.0) - float(exchange_ms), 2))
        self._update_state(
            provider,
            market_symbol,
            connected=True,
            fallback=False,
            stale=False,
            degraded=False,
            confidence="high",
            transport="websocket",
            exclusion_reason="",
            ticker_price_points=float(price_points),
            ticker_updated_at=now_iso,
            last_update_at=now_iso,
            ticker_exchange_time=_iso_from_exchange_ms(exchange_ms),
            ticker_latency_ms=latency_ms,
        )

    def _publish_depth(self, provider, market_symbol, *, bids_map, asks_map, exchange_ms=None):
        now_iso = _now()
        latency_ms = 0.0
        if exchange_ms:
            latency_ms = max(0.0, round((time.time() * 1000.0) - float(exchange_ms), 2))
        self._update_state(
            provider,
            market_symbol,
            connected=True,
            fallback=False,
            stale=False,
            degraded=False,
            confidence="high",
            transport="websocket",
            exclusion_reason="",
            bids_map=dict(bids_map or {}),
            asks_map=dict(asks_map or {}),
            depth_updated_at=now_iso,
            last_update_at=now_iso,
            depth_exchange_time=_iso_from_exchange_ms(exchange_ms),
            depth_latency_ms=latency_ms,
        )

    def _ensure_worker(self, provider, market_symbol, provider_id):
        if provider not in WS_CAPABLE_PRICE_PROVIDERS or not provider_id:
            return
        key = self._key(provider, market_symbol)
        with self._lock:
            worker = self._workers.get(key)
            if worker and worker.is_alive():
                return
            worker = threading.Thread(
                target=self._run_worker,
                name=f"trade-ws-{provider}-{market_symbol.replace('/', '_')}",
                args=(provider, market_symbol, provider_id),
                daemon=True,
            )
            self._workers[key] = worker
            worker.start()

    def _provider_url_and_subscriptions(self, provider, provider_id):
        if provider == "binance_public_api":
            symbol = str(provider_id or "").strip().lower()
            streams = f"{symbol}@ticker/{symbol}@depth20@100ms"
            return f"wss://stream.binance.com:9443/stream?streams={streams}", []
        if provider == "okx_public_api":
            return "wss://ws.okx.com:8443/ws/v5/public", [
                {"op": "subscribe", "args": [
                    {"channel": "tickers", "instId": provider_id},
                    {"channel": "books", "instId": provider_id},
                ]}
            ]
        if provider == "coinbase_exchange":
            return "wss://ws-feed.exchange.coinbase.com", [
                {"type": "subscribe", "product_ids": [provider_id], "channels": ["ticker", "level2"]},
            ]
        if provider == "kraken_public_api":
            pair = _kraken_ws_pair(provider_id)
            return "wss://ws.kraken.com", [
                {"event": "subscribe", "pair": [pair], "subscription": {"name": "ticker"}},
                {"event": "subscribe", "pair": [pair], "subscription": {"name": "book", "depth": 1000}},
            ]
        raise ValueError("unsupported websocket provider")

    def _run_worker(self, provider, market_symbol, provider_id):
        url, subscriptions = self._provider_url_and_subscriptions(provider, provider_id)
        backoff_seconds = 1.0
        while True:
            ws = None
            try:
                ws = websocket.create_connection(
                    url,
                    timeout=10,
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED},
                )
                self._mark_connected(provider, market_symbol)
                for payload in subscriptions:
                    ws.send(json.dumps(payload))
                backoff_seconds = 1.0
                while True:
                    raw = ws.recv()
                    if raw in (None, ""):
                        raise RuntimeError("websocket closed")
                    self._handle_message(provider, market_symbol, provider_id, raw)
            except Exception as exc:
                self._mark_disconnected(provider, market_symbol, reason=str(exc))
                time.sleep(min(backoff_seconds, 10.0))
                backoff_seconds = min(backoff_seconds * 2.0, 10.0)
            finally:
                try:
                    if ws is not None:
                        ws.close()
                except Exception:
                    pass

    def _handle_message(self, provider, market_symbol, provider_id, raw):
        try:
            payload = json.loads(raw)
        except Exception as exc:
            self._mark_malformed(provider, market_symbol, reason=f"invalid json: {exc}")
            return
        if provider == "binance_public_api":
            self._handle_binance_message(market_symbol, payload)
            return
        if provider == "okx_public_api":
            self._handle_okx_message(market_symbol, payload)
            return
        if provider == "coinbase_exchange":
            self._handle_coinbase_message(market_symbol, payload)
            return
        if provider == "kraken_public_api":
            self._handle_kraken_message(market_symbol, payload)
            return
        self._mark_malformed(provider, market_symbol, reason="unsupported websocket provider")

    def _handle_binance_message(self, market_symbol, payload):
        stream_name = str(payload.get("stream") or "").strip().lower()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            self._mark_malformed("binance_public_api", market_symbol, reason="binance websocket payload is invalid")
            return
        if stream_name.endswith("@ticker"):
            price = _float_or_none(data.get("c"))
            if not price or price <= 0:
                self._mark_malformed("binance_public_api", market_symbol, reason="binance ticker price is invalid")
                return
            self._publish_ticker("binance_public_api", market_symbol, price_points=price, exchange_ms=data.get("E"))
            return
        if "@depth" in stream_name:
            bids = self._levels_to_map(data.get("b") or [])
            asks = self._levels_to_map(data.get("a") or [])
            if not bids or not asks:
                self._mark_malformed("binance_public_api", market_symbol, reason="binance depth snapshot is empty")
                return
            self._publish_depth("binance_public_api", market_symbol, bids_map=bids, asks_map=asks, exchange_ms=data.get("E"))

    def _handle_okx_message(self, market_symbol, payload):
        if not isinstance(payload, dict):
            self._mark_malformed("okx_public_api", market_symbol, reason="okx websocket payload is invalid")
            return
        if payload.get("event"):
            return
        arg = payload.get("arg") if isinstance(payload.get("arg"), dict) else {}
        channel = str(arg.get("channel") or "")
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        if not rows:
            return
        row = rows[0] if isinstance(rows[0], dict) else {}
        if channel == "tickers":
            price = _float_or_none(row.get("last"))
            if not price or price <= 0:
                self._mark_malformed("okx_public_api", market_symbol, reason="okx ticker price is invalid")
                return
            self._publish_ticker("okx_public_api", market_symbol, price_points=price, exchange_ms=row.get("ts"))
            return
        if channel == "books":
            bids = self._levels_to_map(row.get("bids") or [])
            asks = self._levels_to_map(row.get("asks") or [])
            if not bids or not asks:
                self._mark_malformed("okx_public_api", market_symbol, reason="okx depth snapshot is empty")
                return
            self._publish_depth("okx_public_api", market_symbol, bids_map=bids, asks_map=asks, exchange_ms=row.get("ts"))

    def _handle_coinbase_message(self, market_symbol, payload):
        if not isinstance(payload, dict):
            self._mark_malformed("coinbase_exchange", market_symbol, reason="coinbase websocket payload is invalid")
            return
        msg_type = str(payload.get("type") or "")
        if msg_type in {"subscriptions", "heartbeat"}:
            return
        if msg_type == "ticker":
            price = _float_or_none(payload.get("price"))
            if not price or price <= 0:
                self._mark_malformed("coinbase_exchange", market_symbol, reason="coinbase ticker price is invalid")
                return
            exchange_ms = _ms_from_iso(payload.get("time"))
            self._publish_ticker("coinbase_exchange", market_symbol, price_points=price, exchange_ms=exchange_ms)
            return
        current = self._state("coinbase_exchange", market_symbol)
        bids_map = dict(current.get("bids_map") or {})
        asks_map = dict(current.get("asks_map") or {})
        if msg_type == "snapshot":
            bids_map = self._levels_to_map(payload.get("bids") or [])
            asks_map = self._levels_to_map(payload.get("asks") or [])
        elif msg_type == "l2update":
            for change in (payload.get("changes") or []):
                if not isinstance(change, (list, tuple)) or len(change) < 3:
                    continue
                side = str(change[0] or "").strip().lower()
                price = _float_or_none(change[1])
                size = _float_or_none(change[2])
                if not price or price <= 0 or size is None:
                    continue
                if side in {"buy", "bid"}:
                    if size <= 0:
                        bids_map.pop(price, None)
                    else:
                        bids_map[price] = size
                elif side in {"sell", "ask"}:
                    if size <= 0:
                        asks_map.pop(price, None)
                    else:
                        asks_map[price] = size
        else:
            return
        if not bids_map or not asks_map:
            self._mark_malformed("coinbase_exchange", market_symbol, reason="coinbase depth snapshot is empty")
            return
        exchange_ms = _ms_from_iso(payload.get("time"))
        self._publish_depth("coinbase_exchange", market_symbol, bids_map=bids_map, asks_map=asks_map, exchange_ms=exchange_ms)

    def _handle_kraken_message(self, market_symbol, payload):
        if isinstance(payload, dict):
            if payload.get("event"):
                return
            return
        if not isinstance(payload, list) or len(payload) < 3:
            self._mark_malformed("kraken_public_api", market_symbol, reason="kraken websocket payload is invalid")
            return
        channel = str(payload[-2] if len(payload) >= 2 else "")
        data = payload[1]
        if channel == "ticker" and isinstance(data, dict):
            close = data.get("c")
            price = _float_or_none(close[0] if isinstance(close, list) and close else None)
            if not price or price <= 0:
                self._mark_malformed("kraken_public_api", market_symbol, reason="kraken ticker price is invalid")
                return
            self._publish_ticker("kraken_public_api", market_symbol, price_points=price)
            return
        if channel.startswith("book") and isinstance(data, dict):
            current = self._state("kraken_public_api", market_symbol)
            bids_map = dict(current.get("bids_map") or {})
            asks_map = dict(current.get("asks_map") or {})
            if data.get("bs") or data.get("as"):
                bids_map = self._levels_to_map(data.get("bs") or [])
                asks_map = self._levels_to_map(data.get("as") or [])
            if data.get("b"):
                bids_map = self._kraken_apply_book_changes(bids_map, data.get("b") or [])
            if data.get("a"):
                asks_map = self._kraken_apply_book_changes(asks_map, data.get("a") or [])
            if not bids_map or not asks_map:
                self._mark_malformed("kraken_public_api", market_symbol, reason="kraken depth snapshot is empty")
                return
            self._publish_depth("kraken_public_api", market_symbol, bids_map=bids_map, asks_map=asks_map)

    def _kraken_apply_book_changes(self, levels_map, rows):
        updated = dict(levels_map or {})
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price = _float_or_none(row[0])
            size = _float_or_none(row[1])
            if not price or price <= 0 or size is None:
                continue
            if size <= 0:
                updated.pop(price, None)
            else:
                updated[price] = size
        return updated

    def _levels_to_map(self, rows):
        levels_map = {}
        for row in rows or []:
            price = None
            size = None
            if isinstance(row, dict):
                price = row.get("price")
                size = row.get("size", row.get("qty", row.get("amount")))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                price, size = row[0], row[1]
            parsed_price = _float_or_none(price)
            parsed_size = _float_or_none(size)
            if parsed_price is None or parsed_size is None or parsed_price <= 0:
                continue
            if parsed_size <= 0:
                continue
            levels_map[parsed_price] = parsed_size
        return levels_map

    def _state_snapshot(self, provider, market_symbol, *, stale_after_seconds):
        current = self._state(provider, market_symbol)
        if not current:
            return {}
        last_update_at = str(current.get("last_update_at") or "")
        stale = False
        if stale_after_seconds > 0:
            last_ms = _ms_from_iso(last_update_at)
            if last_ms is None:
                stale = True
            else:
                stale = ((time.time() * 1000.0) - last_ms) > (float(stale_after_seconds) * 1000.0)
        current["stale"] = stale
        current["degraded"] = stale or not bool(current.get("connected"))
        current["confidence"] = "low" if current["degraded"] else "high"
        if stale and not current.get("exclusion_reason"):
            current["exclusion_reason"] = "websocket data is stale"
        return current

    def get_provider_state(self, provider, market_symbol, *, provider_id="", stale_after_seconds=15):
        if provider not in WS_CAPABLE_PRICE_PROVIDERS or not provider_id:
            return {
                "provider": provider,
                "market_symbol": str(market_symbol or "").strip().upper(),
                "ws_supported": False,
                "transport": "http_polling",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": False,
                "confidence": "medium",
                "provider_count": 1,
                "last_update_at": "",
                "exclusion_reason": "",
            }
        self._ensure_worker(provider, market_symbol, provider_id)
        snapshot = self._state_snapshot(provider, market_symbol, stale_after_seconds=stale_after_seconds)
        if not snapshot:
            return {
                "provider": provider,
                "market_symbol": str(market_symbol or "").strip().upper(),
                "ws_supported": True,
                "transport": "websocket",
                "connected": False,
                "fallback": False,
                "stale": True,
                "degraded": True,
                "confidence": "low",
                "provider_count": 1,
                "last_update_at": "",
                "exclusion_reason": "websocket not ready",
            }
        return {
            "provider": provider,
            "market_symbol": str(market_symbol or "").strip().upper(),
            "ws_supported": True,
            "transport": "websocket",
            "connected": bool(snapshot.get("connected")),
            "fallback": bool(snapshot.get("fallback")),
            "stale": bool(snapshot.get("stale")),
            "degraded": bool(snapshot.get("degraded")),
            "confidence": str(snapshot.get("confidence") or "low"),
            "provider_count": 1,
            "last_update_at": str(snapshot.get("last_update_at") or ""),
            "exclusion_reason": str(snapshot.get("exclusion_reason") or ""),
            "ticker_updated_at": str(snapshot.get("ticker_updated_at") or ""),
            "depth_updated_at": str(snapshot.get("depth_updated_at") or ""),
            "ticker_latency_ms": float(snapshot.get("ticker_latency_ms") or 0.0),
            "depth_latency_ms": float(snapshot.get("depth_latency_ms") or 0.0),
        }

    def get_ticker_snapshot(self, provider, market_symbol, *, provider_id="", stale_after_seconds=15):
        state = self.get_provider_state(provider, market_symbol, provider_id=provider_id, stale_after_seconds=stale_after_seconds)
        if not state.get("ws_supported"):
            return None
        raw = self._state_snapshot(provider, market_symbol, stale_after_seconds=stale_after_seconds)
        price_points = _float_or_none(raw.get("ticker_price_points")) if raw else None
        if price_points is None or price_points <= 0:
            return None
        return {
            **state,
            "price_points": price_points,
            "fetched_at": str(raw.get("ticker_updated_at") or raw.get("last_update_at") or ""),
            "latency_ms": float(raw.get("ticker_latency_ms") or 0.0),
        }

    def get_orderbook_snapshot(self, provider, market_symbol, *, provider_id="", stale_after_seconds=15):
        state = self.get_provider_state(provider, market_symbol, provider_id=provider_id, stale_after_seconds=stale_after_seconds)
        if not state.get("ws_supported"):
            return None
        raw = self._state_snapshot(provider, market_symbol, stale_after_seconds=stale_after_seconds)
        if not raw:
            return None
        bids = _sorted_book_levels(raw.get("bids_map") or {}, reverse=True)
        asks = _sorted_book_levels(raw.get("asks_map") or {}, reverse=False)
        if not bids or not asks:
            return None
        return {
            **state,
            "bids": bids,
            "asks": asks,
            "fetched_at": str(raw.get("depth_updated_at") or raw.get("last_update_at") or ""),
            "latency_ms": float(raw.get("depth_latency_ms") or 0.0),
        }
