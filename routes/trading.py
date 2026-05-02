import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import request


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"
COINBASE_CANDLES_URL_TEMPLATE = "https://api.exchange.coinbase.com/products/{product_id}/candles"
KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
GEMINI_CANDLES_URL_TEMPLATE = "https://api.gemini.com/v2/candles/{symbol}/{timeframe}"
BITSTAMP_OHLC_URL_TEMPLATE = "https://www.bitstamp.net/api/v2/ohlc/{pair}/"
USDT_TO_POINTS_RATE = 1
REFERENCE_PRICE_MARKETS = {
    "BTC/POINTS": "BTCUSDT",
    "BTC/USDT": "BTCUSDT",
    "ETH/POINTS": "ETHUSDT",
    "ETH/USDT": "ETHUSDT",
}
COINBASE_REFERENCE_PRODUCTS = {
    "BTC/POINTS": "BTC-USD",
    "BTC/USDT": "BTC-USD",
    "ETH/POINTS": "ETH-USD",
    "ETH/USDT": "ETH-USD",
}
OKX_REFERENCE_INSTRUMENTS = {
    "BTC/POINTS": "BTC-USDT",
    "BTC/USDT": "BTC-USDT",
    "ETH/POINTS": "ETH-USDT",
    "ETH/USDT": "ETH-USDT",
}
KRAKEN_REFERENCE_PAIRS = {
    "BTC/POINTS": "XBTUSD",
    "BTC/USDT": "XBTUSD",
    "ETH/POINTS": "ETHUSD",
    "ETH/USDT": "ETHUSD",
}
GEMINI_REFERENCE_SYMBOLS = {
    "BTC/POINTS": "btcusd",
    "BTC/USDT": "btcusd",
    "ETH/POINTS": "ethusd",
    "ETH/USDT": "ethusd",
}
BITSTAMP_REFERENCE_PAIRS = {
    "BTC/POINTS": "btcusd",
    "BTC/USDT": "btcusd",
    "ETH/POINTS": "ethusd",
    "ETH/USDT": "ethusd",
}
REFERENCE_PRICE_INTERVALS = {"5m", "15m", "1h", "4h", "1d"}
OKX_BAR_INTERVALS = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
COINBASE_GRANULARITY_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
KRAKEN_INTERVAL_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
GEMINI_TIMEFRAMES = {"5m": "5m", "15m": "15m", "1h": "1hr", "1d": "1day"}
BITSTAMP_STEP_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
REFERENCE_PRICE_CACHE = {}
REFERENCE_PRICE_CACHE_TTL_SECONDS = 1.0
BTC_TRADE_SIGNAL_KEYS = {"bar_ts", "signal_ok", "ml_ok", "position", "current_price", "entry_checks", "ml_status"}
BTC_TRADE_TIMEFRAME_SECONDS = {"4h": 4 * 60 * 60}


def _expand_server_path(raw_path):
    value = str(raw_path or "").strip()
    if not value:
        return None
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _load_json_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_btc_trade_time(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _btc_trade_next_prediction(signal, *, timeframe="4h", fallback_updated_at=None):
    interval = BTC_TRADE_TIMEFRAME_SECONDS.get(str(timeframe or "4h").lower(), 4 * 60 * 60)
    base = _parse_btc_trade_time(signal.get("bar_ts")) or _parse_btc_trade_time(fallback_updated_at)
    if not base:
        return None
    now = datetime.now(timezone.utc)
    next_at = base + timedelta(seconds=interval)
    while next_at <= now:
        next_at += timedelta(seconds=interval)
    return {
        "next_prediction_at": next_at.isoformat(),
        "next_prediction_seconds": max(0, int((next_at - now).total_seconds())),
        "prediction_interval_seconds": interval,
    }


def btc_trade_status(project_dir):
    root = _expand_server_path(project_dir)
    if not root:
        return {
            "configured": False,
            "available": False,
            "needs_initialization": True,
            "message": "root 尚未設定 BTC_trade 專案資料夾",
        }
    runtime = root / "runtime"
    report_path = runtime / "report_log_4h.jsonl"
    portfolio_path = runtime / "portfolio_state_4h.json"
    trade_log_path = runtime / "trade_log_4h.json"
    checks = {
        "project_dir": root.is_dir(),
        "hourly_check": (root / "hourly_check.py").is_file(),
        "update_data": (root / "update_data.py").is_file(),
        "backtest_report": (root / "backtest_report.py").is_file(),
        "runtime_dir": runtime.is_dir(),
        "report_log": report_path.is_file(),
    }
    missing = [name for name, ok in checks.items() if not ok]
    payload = {
        "configured": True,
        "available": False,
        "needs_initialization": bool(missing),
        "checks": checks,
        "missing": missing,
        "message": "",
        "commands": [
            "python3 update_data.py",
            "python3 hourly_check.py --timeframe 4h",
            "python3 backtest_report.py --timeframe 4h",
        ],
    }
    if missing:
        payload["message"] = "BTC_trade 專案尚未可用，請先在該資料夾執行初始化或產生信號報告"
        return payload
    latest_line = ""
    try:
        with open(report_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    latest_line = line.strip()
        if not latest_line:
            raise ValueError("empty report log")
        latest = json.loads(latest_line)
        if not isinstance(latest, dict):
            raise ValueError("latest report is not an object")
    except Exception as exc:
        payload["needs_initialization"] = True
        payload["message"] = f"BTC_trade 信號報告無法讀取：{exc.__class__.__name__}"
        return payload
    signal = {key: latest.get(key) for key in BTC_TRADE_SIGNAL_KEYS if key in latest}
    signal["timeframe"] = "4h"
    signal["source"] = "BTC_trade/report_log_4h.jsonl"
    try:
        stat = report_path.stat()
        signal["updated_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        signal["age_seconds"] = max(0, int(time.time() - stat.st_mtime))
    except Exception:
        pass
    if portfolio_path.is_file():
        try:
            portfolio = _load_json_file(portfolio_path)
            if isinstance(portfolio, dict):
                signal["portfolio"] = {
                    "position": portfolio.get("position"),
                    "cash": portfolio.get("cash"),
                    "btc": portfolio.get("btc"),
                    "updated_at": portfolio.get("updated_at") or portfolio.get("timestamp"),
                }
        except Exception:
            pass
    if trade_log_path.is_file():
        try:
            trades = _load_json_file(trade_log_path)
            if isinstance(trades, list) and trades:
                last_trade = trades[-1] if isinstance(trades[-1], dict) else {}
                signal["last_trade"] = {
                    "action": last_trade.get("action"),
                    "timestamp": last_trade.get("timestamp"),
                    "pnl_pct": last_trade.get("pnl_pct"),
                    "exit_reason": last_trade.get("exit_reason"),
                }
        except Exception:
            pass
    next_prediction = _btc_trade_next_prediction(signal, timeframe=signal["timeframe"], fallback_updated_at=signal.get("updated_at"))
    if next_prediction:
        signal.update(next_prediction)
    payload["available"] = True
    payload["needs_initialization"] = False
    payload["message"] = "BTC_trade 信號可用"
    payload["signal"] = signal
    return payload


def register_trading_routes(app, deps):
    trading_service = deps["trading_service"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    check_user_rate_limit = deps.get("check_user_rate_limit", lambda *args, **kwargs: (False, {}))
    audit = deps.get("audit", lambda *args, **kwargs: None)
    role_rank = deps.get("role_rank", lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0))

    def actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "未登入"}, 401)
        return actor, None

    def root_or_403():
        actor, err = actor_or_401()
        if err:
            return None, err
        if actor_value(actor, "username") != "root":
            return None, json_resp({"ok": False, "msg": "只有 root 可執行此操作"}, 403)
        return actor, None

    def manager_or_403():
        actor, err = actor_or_401()
        if err:
            return None, err
        role = "super_admin" if actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")
        if role_rank(role) < role_rank("manager"):
            return None, json_resp({"ok": False, "msg": "需要管理員權限"}, 403)
        return actor, None

    def parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "Invalid JSON"}, 400)
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "Invalid request"}, 400)
        return data, None

    def service_error(exc):
        msg = str(exc) or exc.__class__.__name__
        status = 400
        lowered = msg.lower()
        if "spot position" in lowered or "持倉不足" in lowered:
            status = 409
            msg = "現貨持倉不足，請降低賣出數量或確認可賣現貨。"
        elif "insufficient" in lowered or "不足" in lowered:
            status = 409
            if msg.startswith("root 模擬交易資金不足"):
                msg = msg
            elif "root simulated trading points" in lowered:
                msg = "root 模擬交易資金不足，請降低保證金/數量，或在交易所重置 root 模擬資金"
            elif msg.startswith("交易資金不足"):
                msg = msg
            else:
                msg = "交易資金不足，請降低數量或補足可用積分"
        if "safe mode" in lowered:
            status = 423
        if lowered.startswith("collateral below minimum"):
            minimum = msg.rsplit(" ", 1)[-1]
            msg = f"保證金不足，至少需要 {minimum} 點"
            status = 400
        elif lowered.startswith("borrow trading is disabled"):
            msg = "進階交易尚未啟用，請由 root 到設定 > 計費 > 交易所參數開啟借貸交易"
            status = 403
        elif lowered.startswith("contract trading is disabled"):
            msg = "合約交易尚未啟用，請由 root 到設定 > 計費 > 交易所參數開啟 futures_enabled"
            status = 403
        elif lowered.startswith("position_type must be"):
            msg = "進階交易類型錯誤，請選擇融資買入或借券放空"
            status = 400
        elif lowered.startswith("quantity must be"):
            msg = "交易數量必須是大於 0 的數字"
            status = 400
        elif lowered.startswith("collateral_points must be"):
            msg = "保證金必須是大於 0 的整數"
            status = 400
        if lowered.startswith("market not found"):
            msg = "交易市場不存在，請重新整理交易所參數後再試"
            status = 400
        elif "not found" in lowered:
            status = 404
        if "another user" in lowered or "another user's" in lowered:
            status = 403
        return json_resp({"ok": False, "msg": msg}), status

    def price_to_points(value):
        return round(float(value) * USDT_TO_POINTS_RATE, 8)

    def display_market_symbol(symbol):
        return str(symbol or "").upper().replace("/POINTS", "/USDT")

    def fetch_json_url(url, *, timeout=6, user_agent="hackme_web/1.0 reference-price-proxy"):
        req = Request(url, headers={"User-Agent": user_agent})
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def candle_payload(open_time_ms, open_price, high_price, low_price, close_price):
        open_price = float(open_price)
        high_price = float(high_price)
        low_price = float(low_price)
        close_price = float(close_price)
        if min(open_price, high_price, low_price, close_price) <= 0:
            return None
        return {
            "time": int(open_time_ms),
            "time_iso": datetime.fromtimestamp(int(open_time_ms) / 1000, tz=timezone.utc).isoformat(),
            "open_usdt": open_price,
            "high_usdt": high_price,
            "low_usdt": low_price,
            "close_usdt": close_price,
            "open_points": price_to_points(open_price),
            "high_points": price_to_points(high_price),
            "low_points": price_to_points(low_price),
            "close_points": price_to_points(close_price),
            "price_usdt": close_price,
            "price_points": price_to_points(close_price),
        }

    def fetch_binance_reference_candles(binance_symbol, interval, limit):
        query = urlencode({"symbol": binance_symbol, "interval": interval, "limit": limit})
        payload = fetch_json_url(f"{BINANCE_KLINES_URL}?{query}")
        if not isinstance(payload, list):
            raise ValueError("Binance 參考價格格式錯誤")
        candles = []
        for item in payload:
            try:
                candle = candle_payload(int(item[0]), item[1], item[2], item[3], item[4])
            except Exception:
                continue
            if candle:
                candles.append(candle)
        return {"source": "binance_public_api", "symbol": binance_symbol, "candles": candles}

    def fetch_okx_reference_candles(instrument, interval, limit):
        bar = OKX_BAR_INTERVALS.get(interval)
        if not instrument or not bar:
            raise ValueError("OKX 不支援此市場或週期")
        query = urlencode({"instId": instrument, "bar": bar, "limit": limit})
        payload = fetch_json_url(
            f"{OKX_CANDLES_URL}?{query}",
            user_agent="hackme_web/1.0 reference-price-proxy okx",
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ValueError("OKX 參考價格格式錯誤")
        candles = []
        for item in sorted(data, key=lambda row: int(float(row[0])) if isinstance(row, list) and row else 0)[-limit:]:
            try:
                candle = candle_payload(int(float(item[0])), item[1], item[2], item[3], item[4])
            except Exception:
                continue
            if candle:
                candles.append(candle)
        return {"source": "okx_public_api", "symbol": instrument, "candles": candles}

    def fetch_coinbase_reference_candles(product_id, interval, limit):
        granularity = COINBASE_GRANULARITY_SECONDS.get(interval)
        if not product_id or not granularity:
            raise ValueError("Coinbase 不支援此市場或週期")
        query = urlencode({"granularity": granularity})
        payload = fetch_json_url(
            f"{COINBASE_CANDLES_URL_TEMPLATE.format(product_id=product_id)}?{query}",
            user_agent="hackme_web/1.0 reference-price-proxy coinbase",
        )
        if not isinstance(payload, list):
            raise ValueError("Coinbase 參考價格格式錯誤")
        candles = []
        for item in sorted(payload, key=lambda row: int(float(row[0])) if isinstance(row, list) and row else 0)[-limit:]:
            try:
                candle = candle_payload(int(float(item[0])) * 1000, item[3], item[2], item[1], item[4])
            except Exception:
                continue
            if candle:
                candles.append(candle)
        return {"source": "coinbase_exchange", "symbol": product_id, "candles": candles}

    def fetch_kraken_reference_candles(pair, interval, limit):
        minutes = KRAKEN_INTERVAL_MINUTES.get(interval)
        if not pair or not minutes:
            raise ValueError("Kraken 不支援此市場或週期")
        query = urlencode({"pair": pair, "interval": minutes})
        payload = fetch_json_url(
            f"{KRAKEN_OHLC_URL}?{query}",
            user_agent="hackme_web/1.0 reference-price-proxy kraken",
        )
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(f"Kraken 參考價格錯誤：{payload.get('error') if isinstance(payload, dict) else 'invalid payload'}")
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        ohlc = []
        provider_symbol = pair
        for key, value in result.items():
            if key == "last":
                continue
            provider_symbol = key
            ohlc = value if isinstance(value, list) else []
            break
        candles = []
        for item in ohlc[-limit:]:
            try:
                candle = candle_payload(int(float(item[0])) * 1000, item[1], item[2], item[3], item[4])
            except Exception:
                continue
            if candle:
                candles.append(candle)
        return {"source": "kraken_public_api", "symbol": provider_symbol, "candles": candles}

    def fetch_gemini_reference_candles(symbol, interval, limit):
        timeframe = GEMINI_TIMEFRAMES.get(interval)
        if not symbol or not timeframe:
            raise ValueError("Gemini 不支援此市場或週期")
        payload = fetch_json_url(
            GEMINI_CANDLES_URL_TEMPLATE.format(symbol=symbol, timeframe=timeframe),
            user_agent="hackme_web/1.0 reference-price-proxy gemini",
        )
        if not isinstance(payload, list):
            raise ValueError("Gemini 參考價格格式錯誤")
        candles = []
        for item in sorted(payload, key=lambda row: int(float(row[0])) if isinstance(row, list) and row else 0)[-limit:]:
            try:
                candle = candle_payload(int(float(item[0])), item[1], item[2], item[3], item[4])
            except Exception:
                continue
            if candle:
                candles.append(candle)
        return {"source": "gemini_public_api", "symbol": symbol, "candles": candles}

    def fetch_bitstamp_reference_candles(pair, interval, limit):
        step = BITSTAMP_STEP_SECONDS.get(interval)
        if not pair or not step:
            raise ValueError("Bitstamp 不支援此市場或週期")
        query = urlencode({"step": step, "limit": limit})
        payload = fetch_json_url(
            f"{BITSTAMP_OHLC_URL_TEMPLATE.format(pair=pair)}?{query}",
            user_agent="hackme_web/1.0 reference-price-proxy bitstamp",
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        ohlc = data.get("ohlc") if isinstance(data, dict) else None
        if not isinstance(ohlc, list):
            raise ValueError("Bitstamp 參考價格格式錯誤")
        candles = []
        for item in sorted(ohlc, key=lambda row: int(float(row.get("timestamp", 0))) if isinstance(row, dict) else 0)[-limit:]:
            try:
                candle = candle_payload(int(float(item["timestamp"])) * 1000, item["open"], item["high"], item["low"], item["close"])
            except Exception:
                continue
            if candle:
                candles.append(candle)
        return {"source": "bitstamp_public_api", "symbol": pair, "candles": candles}

    def fetch_reference_candles_with_fallback(market_symbol, interval, limit):
        providers = (
            lambda: fetch_binance_reference_candles(REFERENCE_PRICE_MARKETS.get(market_symbol), interval, limit),
            lambda: fetch_okx_reference_candles(OKX_REFERENCE_INSTRUMENTS.get(market_symbol), interval, limit),
            lambda: fetch_coinbase_reference_candles(COINBASE_REFERENCE_PRODUCTS.get(market_symbol), interval, limit),
            lambda: fetch_kraken_reference_candles(KRAKEN_REFERENCE_PAIRS.get(market_symbol), interval, limit),
            lambda: fetch_gemini_reference_candles(GEMINI_REFERENCE_SYMBOLS.get(market_symbol), interval, limit),
            lambda: fetch_bitstamp_reference_candles(BITSTAMP_REFERENCE_PAIRS.get(market_symbol), interval, limit),
        )
        errors = []
        for provider in providers:
            try:
                result = provider()
                if result.get("candles"):
                    return result
                errors.append(f"{result.get('source', 'provider')}: no candles")
            except Exception as exc:
                errors.append(str(exc)[:160])
        raise ValueError("; ".join(errors) or "all reference price providers failed")

    def parse_time_ms(value):
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            number = int(float(text))
            return number if number > 10_000_000_000 else number * 1000
        except Exception:
            pass
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            raise ValueError("backtest time must be ISO datetime or unix timestamp")

    def fetch_reference_candles_for_backtest(data):
        market_symbol = str(data.get("market_symbol") or data.get("market") or "BTC/USDT").strip().upper()
        binance_symbol = REFERENCE_PRICE_MARKETS.get(market_symbol)
        if not binance_symbol:
            raise ValueError("unsupported backtest market")
        interval = str(data.get("timeframe") or data.get("interval") or "15m").strip()
        if interval not in REFERENCE_PRICE_INTERVALS:
            raise ValueError("unsupported backtest interval")
        try:
            limit = int(data.get("limit") or data.get("candle_limit") or 500)
        except Exception:
            raise ValueError("backtest candle limit is invalid")
        query = {
            "symbol": binance_symbol,
            "interval": interval,
            "limit": max(2, min(limit, 1000)),
        }
        start_ms = parse_time_ms(data.get("start_time"))
        end_ms = parse_time_ms(data.get("end_time"))
        if start_ms is not None:
            query["startTime"] = start_ms
        if end_ms is not None:
            query["endTime"] = end_ms
        req = Request(
            f"{BINANCE_KLINES_URL}?{urlencode(query)}",
            headers={"User-Agent": "hackme_web/1.0 trading-backtest"},
        )
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("backtest price provider returned invalid data")
        candles = []
        for item in payload:
            try:
                open_time = int(item[0])
                open_price = float(item[1])
                high_price = float(item[2])
                low_price = float(item[3])
                close_price = float(item[4])
            except Exception:
                continue
            if min(open_price, high_price, low_price, close_price) <= 0:
                continue
            candles.append({
                "time": open_time,
                "time_iso": datetime.fromtimestamp(open_time / 1000, tz=timezone.utc).isoformat(),
                "open_usdt": open_price,
                "high_usdt": high_price,
                "low_usdt": low_price,
                "close_usdt": close_price,
                "open_points": price_to_points(open_price),
                "high_points": price_to_points(high_price),
                "low_points": price_to_points(low_price),
                "close_points": price_to_points(close_price),
                "price_usdt": close_price,
                "price_points": price_to_points(close_price),
            })
        if len(candles) < 2:
            raise ValueError("backtest price provider returned too few candles")
        return candles

    @app.route("/api/trading/markets", methods=["GET"])
    @require_csrf_safe
    def trading_markets():
        actor, err = actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "markets": trading_service.list_markets()})

    @app.route("/api/trading/dashboard", methods=["GET"])
    @require_csrf_safe
    def trading_dashboard():
        actor, err = actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "trading": trading_service.user_dashboard(user_id=actor["id"])})

    @app.route("/api/trading/btc-signal", methods=["GET"])
    @require_csrf_safe
    def trading_btc_signal():
        actor, err = actor_or_401()
        if err:
            return err
        market_symbol = str(request.args.get("market") or "BTC/USDT").strip().upper()
        if market_symbol.replace("/POINTS", "/USDT") != "BTC/USDT":
            return json_resp({"ok": True, "available": False, "hidden": True, "msg": "僅 BTC/USDT 顯示 BTC_trade 信號"})
        try:
            settings = trading_service.get_root_settings().get("settings", {})
            status = btc_trade_status(settings.get("btc_trade_project_dir"))
        except Exception:
            return json_resp({"ok": True, "available": False, "hidden": True, "msg": "BTC_trade 信號暫不可用"})
        return json_resp({
            "ok": True,
            "available": bool(status.get("available")),
            "hidden": not bool(status.get("available")),
            "signal": status.get("signal") if status.get("available") else None,
            "msg": status.get("message") or "",
        })

    @app.route("/api/trading/reference-prices", methods=["GET"])
    @require_csrf_safe
    def trading_reference_prices():
        actor, err = actor_or_401()
        if err:
            return err
        blocked, info = check_user_rate_limit(actor_value(actor, "id", 0), "trading_reference_prices", max_req=120, window_sec=60)
        if blocked:
            retry_after = int(info.get("retry_after", 60)) if isinstance(info, dict) else 60
            return json_resp({
                "ok": False,
                "msg": "參考價格查詢過於頻繁，請稍後再試",
                "retry_after": retry_after,
            }), 429
        market_symbol = str(request.args.get("market") or "BTC/USDT").strip().upper()
        binance_symbol = REFERENCE_PRICE_MARKETS.get(market_symbol)
        if not binance_symbol:
            return json_resp({"ok": False, "msg": "不支援的參考價格市場"}), 400
        interval = str(request.args.get("interval") or "15m").strip()
        if interval not in REFERENCE_PRICE_INTERVALS:
            return json_resp({"ok": False, "msg": "不支援的參考價格週期"}), 400
        latest_only = str(request.args.get("latest") or "").strip().lower() in {"1", "true", "yes"}
        try:
            limit = int(request.args.get("limit") or 60)
        except Exception:
            return json_resp({"ok": False, "msg": "參考價格筆數格式錯誤"}), 400
        limit = 1 if latest_only else max(12, min(limit, 96))
        cache_key = (binance_symbol, interval, limit, latest_only)
        now = time.monotonic()
        cached = REFERENCE_PRICE_CACHE.get(cache_key)
        if cached and now - cached["cached_at"] <= REFERENCE_PRICE_CACHE_TTL_SECONDS:
            return json_resp(cached["payload"])
        try:
            provider_result = fetch_reference_candles_with_fallback(market_symbol, interval, limit)
        except Exception as exc:
            if cached:
                fallback = dict(cached["payload"])
                fallback["source"] = f"{fallback.get('source') or 'reference_price'}_cached"
                fallback["stale"] = True
                fallback["msg"] = "參考價格來源暫時無法讀取，已使用最後可用快取"
                fallback["cache_age_seconds"] = round(now - cached["cached_at"], 3)
                return json_resp(fallback)
            return json_resp({"ok": False, "msg": "參考價格讀取失敗", "detail": str(exc)[:240]}), 502
        candles = provider_result["candles"]
        result = {
            "ok": True,
            "source": provider_result["source"],
            "market": market_symbol,
            "display_market": display_market_symbol(market_symbol),
            "symbol": provider_result["symbol"],
            "interval": interval,
            "latest_only": latest_only,
            "usdt_to_points_rate": USDT_TO_POINTS_RATE,
            "candles": candles,
            "points": candles,
        }
        REFERENCE_PRICE_CACHE[cache_key] = {"cached_at": now, "payload": result}
        return json_resp(result)

    @app.route("/api/trading/orders", methods=["POST"])
    @require_csrf
    def trading_place_order():
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.place_order(
                actor=actor,
                market_symbol=data.get("market_symbol"),
                side=data.get("side"),
                order_type=data.get("order_type"),
                quantity=data.get("quantity"),
                limit_price_points=data.get("limit_price_points"),
                emergency_close=bool(data.get("emergency_close")),
            )
            audit(
                "TRADING_ORDER_SUBMITTED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"order_uuid={result['order'].get('order_uuid')}, market={result['order'].get('market_symbol')}, side={result['order'].get('side')}, status={result['order'].get('status')}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/orders/<order_uuid>/cancel", methods=["POST"])
    @require_csrf
    def trading_cancel_order(order_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        try:
            result = trading_service.cancel_order(actor=actor, order_uuid=order_uuid)
            audit("TRADING_ORDER_CANCELLED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"order_uuid={order_uuid}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/bots", methods=["GET"])
    @require_csrf_safe
    def trading_bots_list():
        actor, err = actor_or_401()
        if err:
            return err
        try:
            return json_resp(trading_service.list_trading_bots(actor=actor))
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/bots", methods=["POST"])
    @require_csrf
    def trading_bots_create():
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.save_trading_bot(actor=actor, payload=data)
            audit("TRADING_BOT_CREATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"bot_uuid={result['bot'].get('bot_uuid')}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/bots/backtest", methods=["POST"])
    @require_csrf
    def trading_bots_backtest():
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            if not isinstance(data.get("candles"), list):
                data["candles"] = fetch_reference_candles_for_backtest(data)
            result = trading_service.backtest_trading_bot(actor=actor, payload=data)
            audit(
                "TRADING_BOT_BACKTEST",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"market={result.get('market_symbol')}, strategy={result.get('strategy')}, trades={result.get('trade_count')}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/bots/<bot_uuid>", methods=["PUT"])
    @require_csrf
    def trading_bots_update(bot_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.save_trading_bot(actor=actor, payload=data, bot_uuid=bot_uuid)
            audit("TRADING_BOT_UPDATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"bot_uuid={bot_uuid}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/bots/<bot_uuid>", methods=["DELETE"])
    @require_csrf
    def trading_bots_delete(bot_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        try:
            result = trading_service.delete_trading_bot(actor=actor, bot_uuid=bot_uuid)
            audit("TRADING_BOT_DELETED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"bot_uuid={bot_uuid}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/bots/scan", methods=["POST"])
    @require_csrf
    def trading_bots_scan():
        actor, err = actor_or_401()
        if err:
            return err
        data = {}
        if request.data:
            data, err = parse_json_body()
            if err:
                return err
        try:
            result = trading_service.run_trading_bots(
                actor=actor,
                limit=data.get("limit", 50) if isinstance(data, dict) else 50,
            )
            audit(
                "TRADING_BOT_SCAN",
                get_client_ip(),
                user=actor["username"],
                success=bool(result.get("ok")),
                ua=get_ua(),
                detail=f"scanned={result.get('scanned')}, triggered={len(result.get('triggered') or [])}, failed={len(result.get('failed') or [])}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/margin/open", methods=["POST"])
    @require_csrf
    def trading_margin_open():
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        idempotency_key = str(data.get("idempotency_key") or request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key:
            return json_resp({"ok": False, "msg": "idempotency_key required"}), 400
        try:
            result = trading_service.open_margin_position(
                actor=actor,
                market_symbol=data.get("market_symbol"),
                position_type=data.get("position_type"),
                quantity=data.get("quantity"),
                collateral_points=data.get("collateral_points"),
                idempotency_key=idempotency_key,
            )
            audit("TRADING_MARGIN_POSITION_OPENED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"position_uuid={result['position'].get('position_uuid')}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/margin/<position_uuid>/close", methods=["POST"])
    @require_csrf
    def trading_margin_close(position_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        try:
            result = trading_service.close_margin_position(actor=actor, position_uuid=position_uuid)
            audit("TRADING_MARGIN_POSITION_CLOSED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"position_uuid={position_uuid}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/trading/margin/<position_uuid>/collateral", methods=["POST"])
    @require_csrf
    def trading_margin_add_collateral(position_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.add_margin_collateral(
                actor=actor,
                position_uuid=position_uuid,
                amount_points=data.get("amount_points"),
                idempotency_key=data.get("idempotency_key"),
            )
            audit(
                "TRADING_MARGIN_COLLATERAL_ADDED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"position_uuid={position_uuid}, amount={data.get('amount_points')}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/trading/report", methods=["GET"])
    @require_csrf_safe
    def admin_trading_report():
        actor, err = root_or_403()
        if err:
            return err
        return json_resp({"ok": True, "report": trading_service.root_report()})

    @app.route("/api/root/trading/settings", methods=["GET"])
    @require_csrf_safe
    def root_trading_settings():
        actor, err = root_or_403()
        if err:
            return err
        return json_resp({"ok": True, **trading_service.get_root_settings()})

    @app.route("/api/root/trading/settings", methods=["POST"])
    @require_csrf
    def root_trading_settings_update():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        if settings.get("price_source") == "manual_root":
            return json_resp({"ok": False, "msg": "交易價格來源不可切換為 root 手動價格，請使用 Binance 與最後健康快取"}), 400
        try:
            result = trading_service.update_root_settings(
                actor=actor,
                settings=settings,
                markets=data.get("markets") if isinstance(data.get("markets"), list) else [],
            )
            audit("TRADING_SETTINGS_UPDATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail="root billing settings")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/btc-trade/check", methods=["POST"])
    @require_csrf
    def root_trading_btc_trade_check():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        project_dir = data.get("project_dir")
        try:
            status = btc_trade_status(project_dir)
            root = _expand_server_path(project_dir)
            if root:
                status["project_dir"] = str(root)
            return json_resp({"ok": True, "status": status})
        except Exception as exc:
            return json_resp({"ok": False, "msg": f"BTC_trade 狀態檢查失敗：{exc.__class__.__name__}"}), 400

    @app.route("/api/root/trading/liquidations/scan", methods=["POST"])
    @require_csrf
    def root_trading_liquidations_scan():
        actor, err = root_or_403()
        if err:
            return err
        data = {}
        if request.data:
            data, err = parse_json_body()
            if err:
                return err
        try:
            result = trading_service.scan_margin_liquidations(
                actor=actor,
                limit=data.get("limit", 100) if isinstance(data, dict) else 100,
            )
            audit(
                "TRADING_LIQUIDATION_SCAN",
                get_client_ip(),
                user=actor["username"],
                success=bool(result.get("ok")),
                ua=get_ua(),
                detail=(
                    f"scanned={result.get('scanned')}, "
                    f"candidates={len(result.get('candidates') or [])}, "
                    f"liquidated={len(result.get('liquidated') or [])}, "
                    f"errors={len(result.get('errors') or [])}"
                ),
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/orders/match", methods=["POST"])
    @require_csrf
    def root_trading_orders_match():
        actor, err = root_or_403()
        if err:
            return err
        data = {}
        if request.data:
            data, err = parse_json_body()
            if err:
                return err
        try:
            result = trading_service.match_open_limit_orders(
                actor=actor,
                market_symbol=data.get("market_symbol") if isinstance(data, dict) else None,
                limit=data.get("limit", 200) if isinstance(data, dict) else 200,
            )
            audit(
                "TRADING_LIMIT_ORDER_MATCH_SCAN",
                get_client_ip(),
                user=actor["username"],
                success=bool(result.get("ok")),
                ua=get_ua(),
                detail=(
                    f"scanned={result.get('scanned')}, "
                    f"matched={len(result.get('matched') or [])}, "
                    f"errors={len(result.get('errors') or [])}"
                ),
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/markets/<path:symbol>", methods=["POST"])
    @require_csrf
    def root_trading_market_update(symbol):
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        if data.get("manual_price_points") is not None:
            return json_resp({"ok": False, "msg": "不允許 root 手動改價；交易價格只能來自 Binance 或最後健康快取"}), 400
        try:
            result = trading_service.update_market(
                actor=actor,
                symbol=symbol,
                manual_price_points=data.get("manual_price_points"),
                max_price_jump_percent=data.get("max_price_jump_percent"),
                fee_rate_percent=data.get("fee_rate_percent"),
                min_order_points=data.get("min_order_points"),
                max_order_points=data.get("max_order_points"),
                enabled=data.get("enabled") if "enabled" in data else None,
                confirm_jump=bool(data.get("confirm_jump")),
            )
            audit("TRADING_MARKET_UPDATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"symbol={symbol}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/reserve/allocate", methods=["POST"])
    @require_csrf
    def root_trading_reserve_allocate():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.allocate_reserve(
                actor=actor,
                source_user_id=data.get("source_user_id"),
                amount_points=data.get("amount_points"),
                reason=data.get("reason"),
            )
            audit(
                "TRADING_RESERVE_ALLOCATED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"source_user_id={data.get('source_user_id')}, amount={data.get('amount_points')}, reason=ROOT_RESERVE_ALLOCATION",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/simulated-balance/reset", methods=["POST"])
    @require_csrf
    def root_trading_simulated_balance_reset():
        actor, err = root_or_403()
        if err:
            return err
        try:
            result = trading_service.reset_root_simulated_balance(actor=actor)
            audit(
                "TRADING_ROOT_SIM_BALANCE_RESET",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=(
                    f"balance={result.get('funding', {}).get('available_points')}, "
                    f"deleted={result.get('deleted', {})}"
                ),
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/contracts", methods=["POST"])
    @require_csrf
    def root_trading_contract_open():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.open_root_contract_position(
                actor=actor,
                market_symbol=data.get("market_symbol"),
                side=data.get("side"),
                quantity=data.get("quantity"),
                leverage=data.get("leverage"),
                margin_points=data.get("margin_points"),
            )
            audit(
                "TRADING_ROOT_CONTRACT_OPENED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"position_uuid={result.get('position', {}).get('position_uuid')}, market={data.get('market_symbol')}, side={data.get('side')}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/contracts/<position_uuid>/close", methods=["POST"])
    @require_csrf
    def root_trading_contract_close(position_uuid):
        actor, err = root_or_403()
        if err:
            return err
        try:
            result = trading_service.close_root_contract_position(actor=actor, position_uuid=position_uuid)
            audit(
                "TRADING_ROOT_CONTRACT_CLOSED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"position_uuid={position_uuid}, pnl={result.get('pnl_points')}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/trading/verify", methods=["GET"])
    @require_csrf_safe
    def root_trading_verify():
        actor, err = root_or_403()
        if err:
            return err
        try:
            return json_resp({"ok": True, "verification": trading_service.verify_state()})
        except Exception as exc:
            return service_error(exc)
