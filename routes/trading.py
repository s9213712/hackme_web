from flask import request


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
        if "safe mode" in lowered:
            status = 423
        if "not found" in lowered:
            status = 404
        if "another user" in lowered:
            status = 403
        return json_resp({"ok": False, "msg": msg}), status

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

    @app.route("/api/admin/trading/report", methods=["GET"])
    @require_csrf_safe
    def admin_trading_report():
        actor, err = root_or_403()
        if err:
            return err
        return json_resp({"ok": True, "report": trading_service.root_report()})

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
