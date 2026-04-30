import json
import math
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN


ASSET_SCALE = 100_000_000
SUPPORTED_EXECUTION_MODES = {"house_counterparty", "pvp_matching", "hybrid_liquidity"}
OPEN_ORDER_STATUSES = {"open", "partially_filled"}


def _now():
    return datetime.now().isoformat()


def _json_dumps(value):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def _to_int(value, *, name, minimum=0, maximum=10**12):
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} out of range")
    return number


def quantity_to_units(value):
    try:
        dec = Decimal(str(value or "")).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("quantity must be a positive number") from exc
    if dec <= 0:
        raise ValueError("quantity must be positive")
    units = int(dec * ASSET_SCALE)
    if units <= 0:
        raise ValueError("quantity is too small")
    return units


def units_to_quantity(units):
    units = int(units or 0)
    text = f"{units // ASSET_SCALE}.{units % ASSET_SCALE:08d}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def notional_points(quantity_units, price_points):
    quantity_units = int(quantity_units)
    price_points = int(price_points)
    return int(math.ceil((quantity_units * price_points) / ASSET_SCALE))


def fee_points(notional, fee_bps):
    return int(math.ceil((int(notional) * int(fee_bps or 0)) / 10_000))


def ensure_trading_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_markets (
            symbol TEXT PRIMARY KEY,
            base_asset TEXT NOT NULL,
            quote_currency TEXT NOT NULL DEFAULT 'POINTS',
            enabled INTEGER NOT NULL DEFAULT 1,
            spot_enabled INTEGER NOT NULL DEFAULT 1,
            futures_enabled INTEGER NOT NULL DEFAULT 0,
            pvp_matching_enabled INTEGER NOT NULL DEFAULT 0,
            execution_mode TEXT NOT NULL DEFAULT 'house_counterparty',
            manual_price_points INTEGER NOT NULL CHECK (manual_price_points > 0),
            max_price_jump_bps INTEGER NOT NULL DEFAULT 1000,
            min_order_points INTEGER NOT NULL DEFAULT 1,
            max_order_points INTEGER NOT NULL DEFAULT 100000,
            fee_bps INTEGER NOT NULL DEFAULT 30,
            updated_at TEXT NOT NULL,
            updated_by INTEGER,
            price_source TEXT NOT NULL DEFAULT 'manual_root',
            CHECK (execution_mode IN ('house_counterparty', 'pvp_matching', 'hybrid_liquidity'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL REFERENCES trading_markets(symbol),
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            execution_mode TEXT NOT NULL DEFAULT 'house_counterparty',
            quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
            limit_price_points INTEGER,
            execution_price_points INTEGER,
            status TEXT NOT NULL DEFAULT 'open',
            frozen_points INTEGER NOT NULL DEFAULT 0,
            fee_points INTEGER NOT NULL DEFAULT 0,
            filled_quantity_units INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (side IN ('buy', 'sell')),
            CHECK (order_type IN ('market', 'limit')),
            CHECK (status IN ('open', 'partially_filled', 'filled', 'cancelled', 'rejected')),
            CHECK (execution_mode IN ('house_counterparty', 'pvp_matching', 'hybrid_liquidity'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fill_uuid TEXT NOT NULL UNIQUE,
            order_id INTEGER NOT NULL REFERENCES trading_orders(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
            price_points INTEGER NOT NULL CHECK (price_points > 0),
            notional_points INTEGER NOT NULL CHECK (notional_points >= 0),
            fee_points INTEGER NOT NULL DEFAULT 0,
            reserve_delta_points INTEGER NOT NULL DEFAULT 0,
            points_ledger_uuids_json TEXT,
            created_at TEXT NOT NULL,
            CHECK (side IN ('buy', 'sell'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_spot_positions (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL REFERENCES trading_markets(symbol),
            quantity_units INTEGER NOT NULL DEFAULT 0 CHECK (quantity_units >= 0),
            locked_quantity_units INTEGER NOT NULL DEFAULT 0 CHECK (locked_quantity_units >= 0),
            avg_cost_points INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, market_symbol)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_futures_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity_units INTEGER NOT NULL,
            entry_price_points INTEGER NOT NULL,
            leverage INTEGER NOT NULL DEFAULT 1,
            margin_points INTEGER NOT NULL,
            liquidation_price_points INTEGER,
            status TEXT NOT NULL DEFAULT 'disabled',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (status IN ('disabled', 'open', 'closed', 'liquidated'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_pending_profit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            amount_points INTEGER NOT NULL CHECK (amount_points > 0),
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            created_at TEXT NOT NULL,
            released_at TEXT,
            CHECK (status IN ('pending', 'released', 'rejected'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_reserve_pool (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            balance_points INTEGER NOT NULL DEFAULT 0 CHECK (balance_points >= 0),
            updated_at TEXT NOT NULL,
            updated_by INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_reserve_pool_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_uuid TEXT NOT NULL UNIQUE,
            delta_points INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            reason TEXT,
            actor_user_id INTEGER,
            source_user_id INTEGER,
            order_id INTEGER,
            fill_id INTEGER,
            points_ledger_uuid TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_uuid TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            actor_user_id INTEGER,
            target_user_id INTEGER,
            order_id INTEGER,
            market_symbol TEXT,
            message TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            safe_mode INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            verification_json TEXT,
            updated_at TEXT NOT NULL,
            updated_by INTEGER
        )
        """
    )
    now = _now()
    conn.execute(
        "INSERT OR IGNORE INTO trading_reserve_pool (id, balance_points, updated_at) VALUES (1, 0, ?)",
        (now,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO trading_state (id, safe_mode, reason, verification_json, updated_at) VALUES (1, 0, '', '{}', ?)",
        (now,),
    )
    defaults = [
        ("trading.enabled", "true"),
        ("trading.futures_enabled", "false"),
        ("trading.pvp_matching_enabled", "false"),
        ("trading.price_source", "manual_root"),
    ]
    for key, value in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO trading_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
    for symbol, asset, price in (
        ("BTC/POINTS", "BTC", 100000),
        ("ETH/POINTS", "ETH", 5000),
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_markets (
                symbol, base_asset, quote_currency, manual_price_points, updated_at, price_source
            ) VALUES (?, ?, 'POINTS', ?, ?, 'manual_root')
            """,
            (symbol, asset, price, now),
        )


class TradingEngineService:
    def __init__(self, *, get_db, points_service, audit=None):
        self.get_db = get_db
        self.points_service = points_service
        self.audit = audit or (lambda *args, **kwargs: None)

    def ensure_schema(self, conn):
        self.points_service.ensure_schema(conn)
        ensure_trading_schema(conn)

    def _actor_id(self, actor):
        try:
            return int(actor.get("id") if hasattr(actor, "get") else actor["id"])
        except Exception:
            return None

    def _audit_event(self, conn, event_type, message, *, actor=None, target_user_id=None, order_id=None, market_symbol=None, severity="info", metadata=None):
        conn.execute(
            """
            INSERT INTO trading_audit_events (
                event_uuid, event_type, severity, actor_user_id, target_user_id,
                order_id, market_symbol, message, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                event_type,
                severity,
                self._actor_id(actor),
                int(target_user_id) if target_user_id is not None else None,
                int(order_id) if order_id is not None else None,
                market_symbol,
                message,
                _json_dumps(metadata or {}),
                _now(),
            ),
        )

    def _state(self, conn):
        row = conn.execute("SELECT * FROM trading_state WHERE id=1").fetchone()
        if not row:
            ensure_trading_schema(conn)
            row = conn.execute("SELECT * FROM trading_state WHERE id=1").fetchone()
        return {
            "safe_mode": bool(row["safe_mode"]),
            "reason": row["reason"] or "",
            "verification": _json_loads(row["verification_json"], {}),
            "updated_at": row["updated_at"],
        }

    def _assert_writable(self, conn):
        state = self._state(conn)
        if state["safe_mode"]:
            raise ValueError(f"Trading safe mode active: {state['reason'] or 'verification failed'}")
        enabled = conn.execute("SELECT value FROM trading_settings WHERE key='trading.enabled'").fetchone()
        if enabled and str(enabled["value"]).lower() not in {"true", "1", "yes"}:
            raise ValueError("trading is disabled")

    def _market(self, conn, symbol):
        row = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (str(symbol or "").strip().upper(),)).fetchone()
        if not row:
            raise ValueError("market not found")
        if not int(row["enabled"] or 0) or not int(row["spot_enabled"] or 0):
            raise ValueError("spot trading is disabled for this market")
        if row["execution_mode"] != "house_counterparty":
            raise ValueError("only house_counterparty execution is enabled in v1")
        return row

    def _position(self, conn, user_id, symbol):
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_spot_positions
                (user_id, market_symbol, quantity_units, locked_quantity_units, avg_cost_points, updated_at)
            VALUES (?, ?, 0, 0, 0, ?)
            """,
            (int(user_id), symbol, now),
        )
        return conn.execute(
            "SELECT * FROM trading_spot_positions WHERE user_id=? AND market_symbol=?",
            (int(user_id), symbol),
        ).fetchone()

    def _reserve(self, conn):
        row = conn.execute("SELECT * FROM trading_reserve_pool WHERE id=1").fetchone()
        if not row:
            ensure_trading_schema(conn)
            row = conn.execute("SELECT * FROM trading_reserve_pool WHERE id=1").fetchone()
        return row

    def _reserve_delta(self, conn, *, delta, event_type, reason, actor=None, source_user_id=None, order_id=None, fill_id=None, points_ledger_uuid=None):
        reserve = self._reserve(conn)
        balance = int(reserve["balance_points"] or 0)
        next_balance = balance + int(delta)
        if next_balance < 0:
            raise ValueError("trading reserve pool is insufficient")
        now = _now()
        conn.execute(
            "UPDATE trading_reserve_pool SET balance_points=?, updated_at=?, updated_by=? WHERE id=1",
            (next_balance, now, self._actor_id(actor)),
        )
        conn.execute(
            """
            INSERT INTO trading_reserve_pool_events (
                event_uuid, delta_points, balance_after, event_type, reason, actor_user_id,
                source_user_id, order_id, fill_id, points_ledger_uuid, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                int(delta),
                next_balance,
                event_type,
                reason or "",
                self._actor_id(actor),
                int(source_user_id) if source_user_id else None,
                int(order_id) if order_id else None,
                int(fill_id) if fill_id else None,
                points_ledger_uuid,
                now,
            ),
        )
        return next_balance

    def _ledger(self, conn, **kwargs):
        return self.points_service._record_transaction(conn, **kwargs)[0]

    def _order_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["filled_quantity"] = units_to_quantity(item["filled_quantity_units"])
        return item

    def _market_payload(self, row):
        item = dict(row)
        item["futures_enabled"] = bool(item["futures_enabled"])
        item["pvp_matching_enabled"] = bool(item["pvp_matching_enabled"])
        item["enabled"] = bool(item["enabled"])
        item["spot_enabled"] = bool(item["spot_enabled"])
        return item

    def _position_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["locked_quantity"] = units_to_quantity(item["locked_quantity_units"])
        return item

    def _fill_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["points_ledger_uuids"] = _json_loads(item.get("points_ledger_uuids_json"), [])
        return item

    def list_markets(self, *, include_disabled=False):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            where = "" if include_disabled else "WHERE enabled=1 AND spot_enabled=1"
            rows = conn.execute(f"SELECT * FROM trading_markets {where} ORDER BY symbol").fetchall()
            return [self._market_payload(row) for row in rows]
        finally:
            conn.close()

    def user_dashboard(self, *, user_id):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            state = self._state(conn)
            markets = [self._market_payload(row) for row in conn.execute("SELECT * FROM trading_markets WHERE enabled=1 ORDER BY symbol").fetchall()]
            positions = [
                self._position_payload(row)
                for row in conn.execute("SELECT * FROM trading_spot_positions WHERE user_id=? ORDER BY market_symbol", (int(user_id),)).fetchall()
            ]
            orders = [
                self._order_payload(row)
                for row in conn.execute("SELECT * FROM trading_orders WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            fills = [
                self._fill_payload(row)
                for row in conn.execute("SELECT * FROM trading_fills WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            return {"state": state, "markets": markets, "positions": positions, "orders": orders, "fills": fills}
        finally:
            conn.close()

    def _is_executable(self, market, *, side, order_type, limit_price):
        current_price = int(market["manual_price_points"])
        if order_type == "market":
            return True, current_price
        limit_price = int(limit_price or 0)
        if side == "buy" and limit_price >= current_price:
            return True, current_price
        if side == "sell" and limit_price <= current_price:
            return True, current_price
        return False, None

    def place_order(self, *, actor, market_symbol, side, order_type, quantity, limit_price_points=None):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        side = str(side or "").lower()
        order_type = str(order_type or "").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        quantity_units = quantity_to_units(quantity)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            market = self._market(conn, market_symbol)
            if int(market["futures_enabled"] or 0):
                raise ValueError("futures interface is reserved but not enabled in v1")
            if int(market["pvp_matching_enabled"] or 0):
                raise ValueError("pvp matching interface is reserved but not enabled in v1")
            if order_type == "limit":
                limit_price = _to_int(limit_price_points, name="limit_price_points", minimum=1)
            else:
                limit_price = None
            check_price = int(limit_price or market["manual_price_points"])
            estimated_notional = notional_points(quantity_units, check_price)
            fee = fee_points(estimated_notional, market["fee_bps"])
            total_points = estimated_notional + fee
            if estimated_notional < int(market["min_order_points"]):
                raise ValueError("order notional is below market minimum")
            if estimated_notional > int(market["max_order_points"]):
                raise ValueError("order notional exceeds market maximum")
            if side == "sell" and estimated_notional - fee <= 0:
                raise ValueError("sell notional after fee must be positive")

            executable, execution_price = self._is_executable(market, side=side, order_type=order_type, limit_price=limit_price)
            now = _now()
            order_uuid = str(uuid.uuid4())
            frozen_points = total_points if side == "buy" else 0
            cur = conn.execute(
                """
                INSERT INTO trading_orders (
                    order_uuid, user_id, market_symbol, side, order_type, execution_mode,
                    quantity_units, limit_price_points, execution_price_points, status,
                    frozen_points, fee_points, filled_quantity_units, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'house_counterparty', ?, ?, ?, 'open', ?, ?, 0, '', ?, ?)
                """,
                (
                    order_uuid,
                    user_id,
                    market["symbol"],
                    side,
                    order_type,
                    quantity_units,
                    limit_price,
                    execution_price,
                    frozen_points,
                    fee,
                    now,
                    now,
                ),
            )
            order_id = cur.lastrowid
            ledger_rows = []
            if side == "buy":
                ledger_rows.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="freeze",
                    amount=total_points,
                    action_type="trading_freeze",
                    reference_type="trading_order",
                    reference_id=order_uuid,
                    idempotency_key=f"trading:freeze:{order_uuid}",
                    reason="TRADING_FREEZE",
                    public_metadata={"order_id": order_id, "market": market["symbol"], "side": side, "order_type": order_type},
                    actor=actor,
                ))
            else:
                position = self._position(conn, user_id, market["symbol"])
                if int(position["quantity_units"]) < quantity_units:
                    raise ValueError("insufficient spot position")
                conn.execute(
                    """
                    UPDATE trading_spot_positions
                    SET quantity_units=quantity_units-?, locked_quantity_units=locked_quantity_units+?, updated_at=?
                    WHERE user_id=? AND market_symbol=?
                    """,
                    (quantity_units, quantity_units, now, user_id, market["symbol"]),
                )

            if executable:
                order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (order_id,)).fetchone()
                fill = self._execute_order(conn, order, market, actor=actor)
                order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (order_id,)).fetchone()
                self._audit_event(conn, "TRADING_ORDER_FILLED", "spot order filled", actor=actor, target_user_id=user_id, order_id=order_id, market_symbol=market["symbol"], metadata={"fill_id": fill["id"]})
            else:
                order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (order_id,)).fetchone()
                self._audit_event(conn, "TRADING_ORDER_OPEN", "limit order stored as open order", actor=actor, target_user_id=user_id, order_id=order_id, market_symbol=market["symbol"])
            conn.commit()
            return {"ok": True, "order": self._order_payload(order), "executed": executable}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _execute_order(self, conn, order, market, *, actor):
        side = order["side"]
        user_id = int(order["user_id"])
        quantity_units = int(order["quantity_units"])
        price = int(order["execution_price_points"] or market["manual_price_points"])
        notional = notional_points(quantity_units, price)
        fee = fee_points(notional, market["fee_bps"])
        total = notional + fee
        ledger_uuids = []
        if side == "buy":
            frozen_amount = int(order["frozen_points"] or total)
            ledger_uuids.append(self._ledger(
                conn,
                user_id=user_id,
                currency_type="points",
                direction="unfreeze",
                amount=frozen_amount,
                action_type="trading_unfreeze",
                reference_type="trading_order",
                reference_id=order["order_uuid"],
                idempotency_key=f"trading:unfreeze:settle:{order['order_uuid']}",
                reason="TRADING_UNFREEZE_SETTLEMENT",
                public_metadata={"order_id": order["id"], "market": market["symbol"], "side": side},
                actor=actor,
            )["ledger_uuid"])
            ledger_uuids.append(self._ledger(
                conn,
                user_id=user_id,
                currency_type="points",
                direction="debit",
                amount=notional,
                action_type="trading_spot_buy",
                reference_type="trading_order",
                reference_id=order["order_uuid"],
                idempotency_key=f"trading:spot_buy:{order['order_uuid']}",
                reason="TRADING_SPOT_BUY",
                public_metadata={"order_id": order["id"], "market": market["symbol"], "price": price, "quantity": units_to_quantity(quantity_units), "notional": notional},
                actor=actor,
            )["ledger_uuid"])
            if fee:
                ledger_uuids.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="debit",
                    amount=fee,
                    action_type="trading_fee",
                    reference_type="trading_order",
                    reference_id=order["order_uuid"],
                    idempotency_key=f"trading:fee:{order['order_uuid']}",
                    reason="TRADING_FEE",
                    public_metadata={"order_id": order["id"], "market": market["symbol"], "fee_bps": int(market["fee_bps"])},
                    actor=actor,
                )["ledger_uuid"])
            position = self._position(conn, user_id, market["symbol"])
            prev_qty = int(position["quantity_units"])
            prev_cost = int(position["avg_cost_points"] or 0)
            next_qty = prev_qty + quantity_units
            next_avg = int(round(((prev_qty * prev_cost) + (quantity_units * price)) / next_qty)) if next_qty else 0
            conn.execute(
                """
                UPDATE trading_spot_positions
                SET quantity_units=?, avg_cost_points=?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (next_qty, next_avg, _now(), user_id, market["symbol"]),
            )
            reserve_delta = total
            self._reserve_delta(conn, delta=reserve_delta, event_type="trade_buy_in", reason="TRADING_SPOT_BUY_AND_FEE", actor=actor, order_id=order["id"])
        else:
            if notional <= 0:
                raise ValueError("sell notional is too small")
            net_credit = notional - fee
            if net_credit <= 0:
                raise ValueError("sell notional is too small after fee")
            self._reserve_delta(conn, delta=-notional, event_type="trade_sell_out", reason="TRADING_SPOT_SELL", actor=actor, order_id=order["id"])
            ledger_uuids.append(self._ledger(
                conn,
                user_id=user_id,
                currency_type="points",
                direction="credit",
                amount=notional,
                action_type="trading_spot_sell",
                reference_type="trading_order",
                reference_id=order["order_uuid"],
                idempotency_key=f"trading:spot_sell:{order['order_uuid']}",
                reason="TRADING_SPOT_SELL",
                public_metadata={"order_id": order["id"], "market": market["symbol"], "price": price, "quantity": units_to_quantity(quantity_units), "notional": notional},
                actor=actor,
            )["ledger_uuid"])
            if fee:
                ledger_uuids.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="debit",
                    amount=fee,
                    action_type="trading_fee",
                    reference_type="trading_order",
                    reference_id=order["order_uuid"],
                    idempotency_key=f"trading:fee:{order['order_uuid']}",
                    reason="TRADING_FEE",
                    public_metadata={"order_id": order["id"], "market": market["symbol"], "fee_bps": int(market["fee_bps"]), "side": side},
                    actor=actor,
                )["ledger_uuid"])
                self._reserve_delta(conn, delta=fee, event_type="fee_retained", reason="TRADING_FEE", actor=actor, order_id=order["id"])
            position = self._position(conn, user_id, market["symbol"])
            if int(position["locked_quantity_units"]) < quantity_units:
                raise ValueError("insufficient locked spot position")
            conn.execute(
                """
                UPDATE trading_spot_positions
                SET locked_quantity_units=locked_quantity_units-?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (quantity_units, _now(), user_id, market["symbol"]),
            )
            reserve_delta = -net_credit
        fill_uuid = str(uuid.uuid4())
        cur = conn.execute(
            """
            INSERT INTO trading_fills (
                fill_uuid, order_id, user_id, market_symbol, side, quantity_units,
                price_points, notional_points, fee_points, reserve_delta_points,
                points_ledger_uuids_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_uuid,
                order["id"],
                user_id,
                market["symbol"],
                side,
                quantity_units,
                price,
                notional,
                fee,
                reserve_delta,
                _json_dumps(ledger_uuids),
                _now(),
            ),
        )
        conn.execute(
            """
            UPDATE trading_orders
            SET status='filled', execution_price_points=?, fee_points=?, filled_quantity_units=?, frozen_points=0, updated_at=?
            WHERE id=?
            """,
            (price, fee, quantity_units, _now(), order["id"]),
        )
        return conn.execute("SELECT * FROM trading_fills WHERE id=?", (cur.lastrowid,)).fetchone()

    def cancel_order(self, *, actor, order_uuid):
        user_id = self._actor_id(actor)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            order = conn.execute("SELECT * FROM trading_orders WHERE order_uuid=?", (str(order_uuid or ""),)).fetchone()
            if not order:
                raise ValueError("order not found")
            if int(order["user_id"]) != int(user_id):
                raise ValueError("cannot cancel another user's order")
            if order["status"] not in OPEN_ORDER_STATUSES:
                raise ValueError("order is not open")
            if order["side"] == "buy" and int(order["frozen_points"] or 0) > 0:
                self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="unfreeze",
                    amount=int(order["frozen_points"]),
                    action_type="trading_unfreeze",
                    reference_type="trading_order",
                    reference_id=order["order_uuid"],
                    idempotency_key=f"trading:cancel_unfreeze:{order['order_uuid']}",
                    reason="TRADING_ORDER_CANCELLED",
                    public_metadata={"order_id": order["id"], "market": order["market_symbol"], "side": order["side"]},
                    actor=actor,
                )
            if order["side"] == "sell":
                cur = conn.execute(
                    """
                    UPDATE trading_spot_positions
                    SET quantity_units=quantity_units+?, locked_quantity_units=locked_quantity_units-?, updated_at=?
                    WHERE user_id=? AND market_symbol=? AND locked_quantity_units>=?
                    """,
                    (order["quantity_units"], order["quantity_units"], _now(), user_id, order["market_symbol"], order["quantity_units"]),
                )
                if cur.rowcount < 1:
                    raise ValueError("spot position unlock failed")
            conn.execute("UPDATE trading_orders SET status='cancelled', frozen_points=0, updated_at=? WHERE id=?", (_now(), order["id"]))
            self._audit_event(conn, "TRADING_ORDER_CANCELLED", "order cancelled", actor=actor, target_user_id=user_id, order_id=order["id"], market_symbol=order["market_symbol"])
            conn.commit()
            return {"ok": True, "order_uuid": order["order_uuid"], "status": "cancelled"}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_market(self, *, actor, symbol, manual_price_points=None, max_price_jump_bps=None, fee_bps=None, min_order_points=None, max_order_points=None, enabled=None, confirm_jump=False):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            market = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (str(symbol or "").strip().upper(),)).fetchone()
            if not market:
                raise ValueError("market not found")
            updates = {}
            if manual_price_points is not None:
                new_price = _to_int(manual_price_points, name="manual_price_points", minimum=1)
                old_price = int(market["manual_price_points"])
                jump_bps = int(abs(new_price - old_price) * 10_000 / old_price) if old_price else 0
                allowed_bps = int(market["max_price_jump_bps"] or 0)
                if jump_bps > allowed_bps and not confirm_jump:
                    raise ValueError(f"price jump {jump_bps} bps exceeds max {allowed_bps}; confirmation required")
                updates["manual_price_points"] = new_price
                updates["price_source"] = "manual_root"
            for key, value, max_value in (
                ("max_price_jump_bps", max_price_jump_bps, 100_000),
                ("fee_bps", fee_bps, 5000),
                ("min_order_points", min_order_points, 10**9),
                ("max_order_points", max_order_points, 10**12),
            ):
                if value is not None:
                    updates[key] = _to_int(value, name=key, minimum=0 if key != "max_order_points" else 1, maximum=max_value)
            if enabled is not None:
                updates["enabled"] = 1 if bool(enabled) else 0
            if not updates:
                raise ValueError("no market changes")
            updates["updated_at"] = _now()
            updates["updated_by"] = self._actor_id(actor)
            assignments = ", ".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE trading_markets SET {assignments} WHERE symbol=?", [*updates.values(), market["symbol"]])
            self._audit_event(conn, "TRADING_MARKET_UPDATED", "root updated manual market settings", actor=actor, market_symbol=market["symbol"], metadata=updates)
            conn.commit()
            updated = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (market["symbol"],)).fetchone()
            return {"ok": True, "market": self._market_payload(updated)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def allocate_reserve(self, *, actor, source_user_id, amount_points, reason):
        amount = _to_int(amount_points, name="amount_points", minimum=1)
        if str(reason or "").strip() != "ROOT_RESERVE_ALLOCATION":
            raise ValueError("reason must be ROOT_RESERVE_ALLOCATION")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            ledger = self._ledger(
                conn,
                user_id=int(source_user_id),
                currency_type="points",
                direction="debit",
                amount=amount,
                action_type="trading_reserve_allocation",
                reference_type="trading_reserve_pool",
                reference_id="reserve:points",
                idempotency_key=f"trading:reserve:{uuid.uuid4()}",
                reason="ROOT_RESERVE_ALLOCATION",
                public_metadata={"reason": "ROOT_RESERVE_ALLOCATION", "allocated_by": self._actor_id(actor)},
                actor=actor,
                risk_flag="admin_action",
                risk_score=80,
            )
            balance = self._reserve_delta(
                conn,
                delta=amount,
                event_type="root_reserve_allocation",
                reason="ROOT_RESERVE_ALLOCATION",
                actor=actor,
                source_user_id=source_user_id,
                points_ledger_uuid=ledger["ledger_uuid"],
            )
            self._audit_event(conn, "TRADING_RESERVE_ALLOCATED", "root allocated points to trading reserve", actor=actor, target_user_id=source_user_id, severity="warning", metadata={"amount_points": amount, "reason": "ROOT_RESERVE_ALLOCATION", "ledger_uuid": ledger["ledger_uuid"]})
            conn.commit()
            return {"ok": True, "balance_points": balance, "ledger_uuid": ledger["ledger_uuid"]}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _replay_positions(self, conn):
        totals = {}
        for row in conn.execute("SELECT market_symbol, user_id, side, quantity_units FROM trading_fills ORDER BY id ASC").fetchall():
            key = (int(row["user_id"]), row["market_symbol"])
            totals.setdefault(key, 0)
            if row["side"] == "buy":
                totals[key] += int(row["quantity_units"])
            else:
                totals[key] -= int(row["quantity_units"])
        return totals

    def _ledger_row(self, conn, ledger_uuid):
        return conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (str(ledger_uuid or ""),)).fetchone()

    def _verify_fill_ledgers(self, conn, errors):
        for fill in conn.execute(
            """
            SELECT f.*, o.order_uuid
            FROM trading_fills f
            JOIN trading_orders o ON o.id=f.order_id
            ORDER BY f.id ASC
            """
        ).fetchall():
            ledger_uuids = _json_loads(fill["points_ledger_uuids_json"], [])
            if not isinstance(ledger_uuids, list) or not ledger_uuids:
                errors.append({
                    "type": "fill_ledger_refs_missing",
                    "fill_id": fill["id"],
                    "fill_uuid": fill["fill_uuid"],
                    "order_id": fill["order_id"],
                })
                continue
            ledgers = []
            for ledger_uuid in ledger_uuids:
                ledger = self._ledger_row(conn, ledger_uuid)
                if not ledger:
                    errors.append({
                        "type": "fill_ledger_ref_not_found",
                        "fill_id": fill["id"],
                        "fill_uuid": fill["fill_uuid"],
                        "ledger_uuid": ledger_uuid,
                    })
                    continue
                ledgers.append(ledger)
                if int(ledger["user_id"]) != int(fill["user_id"]) or ledger["reference_id"] != fill["order_uuid"]:
                    errors.append({
                        "type": "fill_ledger_ref_mismatch",
                        "fill_id": fill["id"],
                        "ledger_uuid": ledger_uuid,
                        "expected_user_id": int(fill["user_id"]),
                        "actual_user_id": int(ledger["user_id"]),
                        "expected_reference_id": fill["order_uuid"],
                        "actual_reference_id": ledger["reference_id"],
                    })
            actions = {row["action_type"] for row in ledgers}
            if fill["side"] == "buy":
                required = {"trading_unfreeze", "trading_spot_buy"}
            else:
                required = {"trading_spot_sell"}
            if int(fill["fee_points"] or 0) > 0:
                required.add("trading_fee")
            missing = sorted(required - actions)
            if missing:
                errors.append({
                    "type": "fill_ledger_actions_missing",
                    "fill_id": fill["id"],
                    "fill_uuid": fill["fill_uuid"],
                    "missing_actions": missing,
                    "actual_actions": sorted(actions),
                })

    def _verify_open_order_locks(self, conn, errors):
        ledger_net = {}
        for row in conn.execute(
            """
            SELECT reference_id, direction, amount
            FROM points_ledger
            WHERE reference_type='trading_order'
              AND action_type IN ('trading_freeze', 'trading_unfreeze')
            ORDER BY id ASC
            """
        ).fetchall():
            reference_id = row["reference_id"]
            if not reference_id:
                continue
            ledger_net.setdefault(reference_id, 0)
            if row["direction"] == "freeze":
                ledger_net[reference_id] += int(row["amount"])
            elif row["direction"] == "unfreeze":
                ledger_net[reference_id] -= int(row["amount"])
        order_rows = conn.execute("SELECT * FROM trading_orders ORDER BY id ASC").fetchall()
        for order in order_rows:
            expected = int(order["frozen_points"] or 0) if order["side"] == "buy" and order["status"] in OPEN_ORDER_STATUSES else 0
            actual = ledger_net.get(order["order_uuid"], 0)
            if expected != actual:
                errors.append({
                    "type": "open_order_frozen_points_mismatch",
                    "order_id": order["id"],
                    "order_uuid": order["order_uuid"],
                    "status": order["status"],
                    "expected_frozen_points": expected,
                    "actual_frozen_points": actual,
                })
        locked_expected = {}
        for order in order_rows:
            if order["side"] == "sell" and order["status"] in OPEN_ORDER_STATUSES:
                key = (int(order["user_id"]), order["market_symbol"])
                locked_expected[key] = locked_expected.get(key, 0) + int(order["quantity_units"])
        for row in conn.execute("SELECT user_id, market_symbol, locked_quantity_units FROM trading_spot_positions ORDER BY user_id, market_symbol").fetchall():
            key = (int(row["user_id"]), row["market_symbol"])
            expected = locked_expected.pop(key, 0)
            actual = int(row["locked_quantity_units"] or 0)
            if expected != actual:
                errors.append({
                    "type": "open_sell_locked_quantity_mismatch",
                    "user_id": key[0],
                    "market_symbol": key[1],
                    "expected_locked_quantity_units": expected,
                    "actual_locked_quantity_units": actual,
                })
        for key, expected in locked_expected.items():
            if expected:
                errors.append({
                    "type": "open_sell_locked_position_missing",
                    "user_id": key[0],
                    "market_symbol": key[1],
                    "expected_locked_quantity_units": expected,
                    "actual_locked_quantity_units": 0,
                })

    def _verify_reserve_pool(self, conn, errors):
        fill_delta = int(conn.execute("SELECT COALESCE(SUM(reserve_delta_points), 0) FROM trading_fills").fetchone()[0] or 0)
        trade_event_delta = int(conn.execute(
            """
            SELECT COALESCE(SUM(delta_points), 0)
            FROM trading_reserve_pool_events
            WHERE event_type IN ('trade_buy_in', 'trade_sell_out', 'fee_retained')
            """
        ).fetchone()[0] or 0)
        if fill_delta != trade_event_delta:
            errors.append({
                "type": "reserve_trade_event_replay_mismatch",
                "expected_trade_delta_points": fill_delta,
                "actual_trade_event_delta_points": trade_event_delta,
            })
        allocation_delta = 0
        running_balance = 0
        for event in conn.execute("SELECT * FROM trading_reserve_pool_events ORDER BY id ASC").fetchall():
            running_balance += int(event["delta_points"] or 0)
            if running_balance != int(event["balance_after"] or 0):
                errors.append({
                    "type": "reserve_event_balance_after_mismatch",
                    "event_id": event["id"],
                    "event_uuid": event["event_uuid"],
                    "expected_balance_after": running_balance,
                    "actual_balance_after": int(event["balance_after"] or 0),
                })
        for event in conn.execute("SELECT * FROM trading_reserve_pool_events WHERE event_type='root_reserve_allocation' ORDER BY id ASC").fetchall():
            ledger = self._ledger_row(conn, event["points_ledger_uuid"])
            if not ledger:
                errors.append({
                    "type": "reserve_allocation_ledger_missing",
                    "event_id": event["id"],
                    "event_uuid": event["event_uuid"],
                    "ledger_uuid": event["points_ledger_uuid"],
                })
                continue
            if ledger["action_type"] != "trading_reserve_allocation" or ledger["direction"] != "debit":
                errors.append({
                    "type": "reserve_allocation_ledger_mismatch",
                    "event_id": event["id"],
                    "event_uuid": event["event_uuid"],
                    "ledger_uuid": ledger["ledger_uuid"],
                    "actual_action_type": ledger["action_type"],
                    "actual_direction": ledger["direction"],
                })
            if int(event["delta_points"]) != int(ledger["amount"]):
                errors.append({
                    "type": "reserve_allocation_amount_mismatch",
                    "event_id": event["id"],
                    "event_uuid": event["event_uuid"],
                    "expected_delta_points": int(ledger["amount"]),
                    "actual_delta_points": int(event["delta_points"]),
                })
            allocation_delta += int(event["delta_points"] or 0)
        expected_balance = fill_delta + allocation_delta
        reserve = self._reserve(conn)
        actual_balance = int(reserve["balance_points"] or 0)
        if expected_balance != actual_balance:
            errors.append({
                "type": "reserve_pool_replay_mismatch",
                "expected_balance_points": expected_balance,
                "actual_balance_points": actual_balance,
                "fill_delta_points": fill_delta,
                "allocation_delta_points": allocation_delta,
            })

    def _verify_state_on_conn(self, conn, *, enter_safe_mode=False):
        errors = []
        totals = self._replay_positions(conn)
        rows = conn.execute("SELECT * FROM trading_spot_positions ORDER BY user_id, market_symbol").fetchall()
        seen = set()
        for row in rows:
            key = (int(row["user_id"]), row["market_symbol"])
            seen.add(key)
            expected_total = totals.get(key, 0)
            actual_total = int(row["quantity_units"]) + int(row["locked_quantity_units"])
            if expected_total != actual_total:
                errors.append({
                    "type": "spot_position_replay_mismatch",
                    "user_id": key[0],
                    "market_symbol": key[1],
                    "expected_total_units": expected_total,
                    "actual_total_units": actual_total,
                })
        for key, expected_total in totals.items():
            if key not in seen and expected_total:
                errors.append({
                    "type": "spot_position_missing",
                    "user_id": key[0],
                    "market_symbol": key[1],
                    "expected_total_units": expected_total,
                    "actual_total_units": 0,
                })
        self._verify_open_order_locks(conn, errors)
        self._verify_fill_ledgers(conn, errors)
        self._verify_reserve_pool(conn, errors)
        result = {"ok": not errors, "errors": errors, "checked_at": _now()}
        if errors and enter_safe_mode:
            conn.execute(
                "UPDATE trading_state SET safe_mode=1, reason=?, verification_json=?, updated_at=?, updated_by=NULL WHERE id=1",
                ("trading_state_verification_failed", _json_dumps(result), _now()),
            )
            self._audit_event(conn, "TRADING_SAFE_MODE_ENTERED", "trading state verification failed", severity="critical", metadata=result)
        return result

    def verify_state(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            result = self._verify_state_on_conn(conn, enter_safe_mode=True)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def root_report(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            state = self._state(conn)
            reserve = self._reserve(conn)
            markets = [self._market_payload(row) for row in conn.execute("SELECT * FROM trading_markets ORDER BY symbol").fetchall()]
            reserve_events = [dict(row) for row in conn.execute("SELECT * FROM trading_reserve_pool_events ORDER BY id DESC LIMIT 50").fetchall()]
            audit_events = [dict(row) for row in conn.execute("SELECT * FROM trading_audit_events ORDER BY id DESC LIMIT 80").fetchall()]
            return {
                "state": state,
                "reserve_pool": dict(reserve),
                "markets": markets,
                "reserve_events": reserve_events,
                "audit_events": audit_events,
                "verification": self._verify_state_on_conn(conn, enter_safe_mode=False),
            }
        finally:
            conn.close()
