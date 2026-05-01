import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import request


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
USDT_TO_POINTS_RATE = 1
REFERENCE_PRICE_MARKETS = {
    "BTC/POINTS": "BTCUSDT",
    "BTC/USDT": "BTCUSDT",
    "ETH/POINTS": "ETHUSDT",
    "ETH/USDT": "ETHUSDT",
}
REFERENCE_PRICE_INTERVALS = {"5m", "15m", "1h", "4h", "1d"}
REFERENCE_PRICE_CACHE = {}
REFERENCE_PRICE_CACHE_TTL_SECONDS = 1.0


def register_trading_routes(app, deps):
    trading_service = deps["trading_service"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
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
        if "insufficient" in lowered:
            status = 409
            if "root simulated trading points" in lowered:
                msg = "root 模擬交易資金不足，請降低保證金/數量，或在交易所重置 root 模擬資金"
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

    @app.route("/api/trading/reference-prices", methods=["GET"])
    @require_csrf_safe
    def trading_reference_prices():
        actor, err = actor_or_401()
        if err:
            return err
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
        query = urlencode({"symbol": binance_symbol, "interval": interval, "limit": limit})
        req = Request(
            f"{BINANCE_KLINES_URL}?{query}",
            headers={"User-Agent": "hackme_web/1.0 reference-price-proxy"},
        )
        try:
            with urlopen(req, timeout=6) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return json_resp({"ok": False, "msg": "Binance 參考價格讀取失敗"}), 502
        if not isinstance(payload, list):
            return json_resp({"ok": False, "msg": "Binance 參考價格格式錯誤"}), 502
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
            candle = {
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
            }
            candles.append(candle)
        if not candles:
            return json_resp({"ok": False, "msg": "Binance 參考價格沒有可用資料"}), 502
        result = {
            "ok": True,
            "source": "binance_public_api",
            "market": market_symbol,
            "display_market": display_market_symbol(market_symbol),
            "symbol": binance_symbol,
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

    @app.route("/api/trading/margin/open", methods=["POST"])
    @require_csrf
    def trading_margin_open():
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = trading_service.open_margin_position(
                actor=actor,
                market_symbol=data.get("market_symbol"),
                position_type=data.get("position_type"),
                quantity=data.get("quantity"),
                collateral_points=data.get("collateral_points"),
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
        try:
            result = trading_service.update_root_settings(
                actor=actor,
                settings=data.get("settings") if isinstance(data.get("settings"), dict) else {},
                markets=data.get("markets") if isinstance(data.get("markets"), list) else [],
            )
            audit("TRADING_SETTINGS_UPDATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail="root billing settings")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

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
        try:
            result = trading_service.update_market(
                actor=actor,
                symbol=symbol,
                manual_price_points=data.get("manual_price_points"),
                max_price_jump_bps=data.get("max_price_jump_bps"),
                fee_bps=data.get("fee_bps"),
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
