import json
import math
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.notifications import create_notification_if_enabled


ASSET_SCALE = 100_000_000
USDT_TO_POINTS_RATE = 1
ROOT_SIMULATED_INITIAL_POINTS = 10_000
TRIAL_CREDIT_INITIAL_POINTS = 1_000
TRIAL_CREDIT_DAYS = 7
MARGIN_MIN_COLLATERAL_BPS = 3000
SUPPORTED_EXECUTION_MODES = {"house_counterparty", "pvp_matching", "hybrid_liquidity"}
OPEN_ORDER_STATUSES = {"open", "partially_filled"}
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
LIVE_PRICE_MARKETS = {
    "BTC/POINTS": "BTCUSDT",
    "BTC/USDT": "BTCUSDT",
    "ETH/POINTS": "ETHUSDT",
    "ETH/USDT": "ETHUSDT",
}


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
            funding_mode TEXT NOT NULL DEFAULT 'points_chain',
            execution_mode TEXT NOT NULL DEFAULT 'house_counterparty',
            quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
            limit_price_points INTEGER,
            execution_price_points INTEGER,
            status TEXT NOT NULL DEFAULT 'open',
            frozen_points INTEGER NOT NULL DEFAULT 0,
            trial_frozen_points INTEGER NOT NULL DEFAULT 0 CHECK (trial_frozen_points >= 0),
            chain_frozen_points INTEGER NOT NULL DEFAULT 0 CHECK (chain_frozen_points >= 0),
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
            funding_mode TEXT NOT NULL DEFAULT 'points_chain',
            quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
            price_points INTEGER NOT NULL CHECK (price_points > 0),
            notional_points INTEGER NOT NULL CHECK (notional_points >= 0),
            fee_points INTEGER NOT NULL DEFAULT 0,
            reserve_delta_points INTEGER NOT NULL DEFAULT 0,
            trial_repaid_points INTEGER NOT NULL DEFAULT 0 CHECK (trial_repaid_points >= 0),
            trial_profit_points INTEGER NOT NULL DEFAULT 0 CHECK (trial_profit_points >= 0),
            points_ledger_uuids_json TEXT,
            created_at TEXT NOT NULL,
            CHECK (side IN ('buy', 'sell'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_spot_realized_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pnl_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            order_id INTEGER NOT NULL REFERENCES trading_orders(id) ON DELETE CASCADE,
            fill_id INTEGER NOT NULL UNIQUE REFERENCES trading_fills(id) ON DELETE CASCADE,
            funding_mode TEXT NOT NULL DEFAULT 'points_chain',
            quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
            avg_cost_points INTEGER NOT NULL DEFAULT 0,
            sell_price_points INTEGER NOT NULL CHECK (sell_price_points > 0),
            gross_cost_points INTEGER NOT NULL DEFAULT 0,
            gross_proceeds_points INTEGER NOT NULL DEFAULT 0,
            buy_fee_estimate_points INTEGER NOT NULL DEFAULT 0,
            sell_fee_points INTEGER NOT NULL DEFAULT 0,
            net_pnl_points INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_sim_accounts (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            balance_points INTEGER NOT NULL DEFAULT 0 CHECK (balance_points >= 0),
            locked_points INTEGER NOT NULL DEFAULT 0 CHECK (locked_points >= 0),
            initial_balance_points INTEGER NOT NULL DEFAULT 10000,
            updated_at TEXT NOT NULL,
            reset_at TEXT,
            reset_by INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_trial_credits (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            initial_points INTEGER NOT NULL DEFAULT 1000 CHECK (initial_points >= 0),
            available_points INTEGER NOT NULL DEFAULT 0 CHECK (available_points >= 0),
            locked_points INTEGER NOT NULL DEFAULT 0 CHECK (locked_points >= 0),
            deployed_points INTEGER NOT NULL DEFAULT 0 CHECK (deployed_points >= 0),
            status TEXT NOT NULL DEFAULT 'active',
            activated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            reclaimed_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK (status IN ('active', 'expired', 'depleted', 'reclaimed'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_trial_position_costs (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL REFERENCES trading_markets(symbol),
            quantity_units INTEGER NOT NULL DEFAULT 0 CHECK (quantity_units >= 0),
            trial_cost_points INTEGER NOT NULL DEFAULT 0 CHECK (trial_cost_points >= 0),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, market_symbol)
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
        CREATE TABLE IF NOT EXISTS trading_margin_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            position_type TEXT NOT NULL,
            quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
            entry_price_points INTEGER NOT NULL CHECK (entry_price_points > 0),
            principal_points INTEGER NOT NULL DEFAULT 0 CHECK (principal_points >= 0),
            collateral_points INTEGER NOT NULL CHECK (collateral_points > 0),
            open_fee_points INTEGER NOT NULL DEFAULT 0,
            close_fee_points INTEGER NOT NULL DEFAULT 0,
            interest_bps_daily INTEGER NOT NULL DEFAULT 0,
            interest_points INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            updated_at TEXT NOT NULL,
            collateral_trial_points INTEGER NOT NULL DEFAULT 0 CHECK (collateral_trial_points >= 0),
            collateral_chain_points INTEGER NOT NULL DEFAULT 0 CHECK (collateral_chain_points >= 0),
            open_fee_trial_points INTEGER NOT NULL DEFAULT 0 CHECK (open_fee_trial_points >= 0),
            open_fee_chain_points INTEGER NOT NULL DEFAULT 0 CHECK (open_fee_chain_points >= 0),
            CHECK (position_type IN ('margin_long', 'short')),
            CHECK (status IN ('open', 'closed', 'liquidated'))
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
        ("trading.borrowing_enabled", "true"),
        ("trading.borrow_interest_bps_daily", "10"),
        ("trading.margin_liquidation_enabled", "true"),
        ("trading.margin_maintenance_bps", "1500"),
        ("trading.max_price_staleness_seconds", "900"),
        ("trading.price_source", "binance_public_api"),
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
            ) VALUES (?, ?, 'POINTS', ?, ?, 'binance_public_api')
            """,
            (symbol, asset, price, now),
        )
    for table in ("trading_orders", "trading_fills"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "funding_mode" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN funding_mode TEXT NOT NULL DEFAULT 'points_chain'")
    order_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_orders)").fetchall()}
    if "trial_frozen_points" not in order_cols:
        conn.execute("ALTER TABLE trading_orders ADD COLUMN trial_frozen_points INTEGER NOT NULL DEFAULT 0")
    if "chain_frozen_points" not in order_cols:
        conn.execute("ALTER TABLE trading_orders ADD COLUMN chain_frozen_points INTEGER NOT NULL DEFAULT 0")
    fill_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_fills)").fetchall()}
    if "trial_repaid_points" not in fill_cols:
        conn.execute("ALTER TABLE trading_fills ADD COLUMN trial_repaid_points INTEGER NOT NULL DEFAULT 0")
    if "trial_profit_points" not in fill_cols:
        conn.execute("ALTER TABLE trading_fills ADD COLUMN trial_profit_points INTEGER NOT NULL DEFAULT 0")
    margin_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_margin_positions)").fetchall()}
    if "collateral_trial_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN collateral_trial_points INTEGER NOT NULL DEFAULT 0")
    if "collateral_chain_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN collateral_chain_points INTEGER NOT NULL DEFAULT 0")
    if "open_fee_trial_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN open_fee_trial_points INTEGER NOT NULL DEFAULT 0")
    if "open_fee_chain_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN open_fee_chain_points INTEGER NOT NULL DEFAULT 0")


class TradingEngineService:
    def __init__(self, *, get_db, points_service, audit=None, live_price_provider=None):
        self.get_db = get_db
        self.points_service = points_service
        self.audit = audit or (lambda *args, **kwargs: None)
        self.live_price_provider = live_price_provider

    def ensure_schema(self, conn):
        self.points_service.ensure_schema(conn)
        ensure_trading_schema(conn)

    def _actor_id(self, actor):
        try:
            return int(actor.get("id") if hasattr(actor, "get") else actor["id"])
        except Exception:
            return None

    def _actor_username(self, actor):
        try:
            return str(actor.get("username") if hasattr(actor, "get") else actor["username"])
        except Exception:
            return ""

    def _is_root_actor(self, actor):
        return self._actor_username(actor) == "root"

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
        item["display_symbol"] = str(item["symbol"] or "").replace("/POINTS", "/USDT")
        return item

    def _settings_payload(self, conn):
        rows = conn.execute("SELECT key, value, updated_at, updated_by FROM trading_settings ORDER BY key").fetchall()
        raw = {row["key"]: row["value"] for row in rows}
        return {
            "enabled": str(raw.get("trading.enabled", "true")).lower() in {"true", "1", "yes"},
            "futures_enabled": str(raw.get("trading.futures_enabled", "false")).lower() in {"true", "1", "yes"},
            "pvp_matching_enabled": str(raw.get("trading.pvp_matching_enabled", "false")).lower() in {"true", "1", "yes"},
            "borrowing_enabled": str(raw.get("trading.borrowing_enabled", "true")).lower() in {"true", "1", "yes"},
            "borrow_interest_bps_daily": _to_int(raw.get("trading.borrow_interest_bps_daily", "10"), name="borrow_interest_bps_daily", minimum=0, maximum=10000),
            "margin_liquidation_enabled": str(raw.get("trading.margin_liquidation_enabled", "true")).lower() in {"true", "1", "yes"},
            "margin_maintenance_bps": _to_int(raw.get("trading.margin_maintenance_bps", "1500"), name="margin_maintenance_bps", minimum=0, maximum=10000),
            "max_price_staleness_seconds": _to_int(raw.get("trading.max_price_staleness_seconds", "900"), name="max_price_staleness_seconds", minimum=0, maximum=86400),
            "price_source": raw.get("trading.price_source", "binance_public_api"),
            "raw": raw,
        }

    def get_root_settings(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return {
                "settings": self._settings_payload(conn),
                "markets": [self._market_payload(row) for row in conn.execute("SELECT * FROM trading_markets ORDER BY symbol").fetchall()],
                "reserve_pool": dict(self._reserve(conn)),
            }
        finally:
            conn.close()

    def update_root_settings(self, *, actor, settings=None, markets=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            now = _now()
            settings = settings if isinstance(settings, dict) else {}
            market_updates = markets if isinstance(markets, list) else []
            setting_changes = {}
            bool_keys = {
                "enabled": "trading.enabled",
                "futures_enabled": "trading.futures_enabled",
                "pvp_matching_enabled": "trading.pvp_matching_enabled",
                "borrowing_enabled": "trading.borrowing_enabled",
                "margin_liquidation_enabled": "trading.margin_liquidation_enabled",
            }
            for input_key, storage_key in bool_keys.items():
                if input_key in settings:
                    value = "true" if bool(settings.get(input_key)) else "false"
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
            if "borrow_interest_bps_daily" in settings:
                value = str(_to_int(settings.get("borrow_interest_bps_daily"), name="borrow_interest_bps_daily", minimum=0, maximum=10000))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_interest_bps_daily", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.borrow_interest_bps_daily"] = value
            if "margin_maintenance_bps" in settings:
                value = str(_to_int(settings.get("margin_maintenance_bps"), name="margin_maintenance_bps", minimum=0, maximum=10000))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.margin_maintenance_bps", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.margin_maintenance_bps"] = value
            if "max_price_staleness_seconds" in settings:
                value = str(_to_int(settings.get("max_price_staleness_seconds"), name="max_price_staleness_seconds", minimum=0, maximum=86400))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.max_price_staleness_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.max_price_staleness_seconds"] = value
            if "price_source" in settings:
                value = str(settings.get("price_source") or "").strip()
                if value not in {"binance_public_api", "manual_root"}:
                    raise ValueError("price_source must be binance_public_api or manual_root")
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_source", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_source"] = value
            changed_markets = []
            for row in market_updates:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").strip().upper()
                market = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (symbol,)).fetchone()
                if not market:
                    raise ValueError(f"market not found: {symbol}")
                updates = {}
                for key, max_value in (
                    ("fee_bps", 5000),
                    ("min_order_points", 10**9),
                    ("max_order_points", 10**12),
                ):
                    if key in row:
                        updates[key] = _to_int(row.get(key), name=key, minimum=0 if key != "max_order_points" else 1, maximum=max_value)
                if "enabled" in row:
                    updates["enabled"] = 1 if bool(row.get("enabled")) else 0
                if not updates:
                    continue
                if "min_order_points" in updates and "max_order_points" in updates and updates["min_order_points"] > updates["max_order_points"]:
                    raise ValueError(f"{symbol} minimum order exceeds maximum order")
                effective_min = int(updates.get("min_order_points", market["min_order_points"]))
                effective_max = int(updates.get("max_order_points", market["max_order_points"]))
                if effective_min > effective_max:
                    raise ValueError(f"{symbol} minimum order exceeds maximum order")
                updates["updated_at"] = now
                updates["updated_by"] = self._actor_id(actor)
                assignments = ", ".join(f"{key}=?" for key in updates)
                conn.execute(f"UPDATE trading_markets SET {assignments} WHERE symbol=?", [*updates.values(), symbol])
                changed_markets.append({"symbol": symbol, **updates})
            if setting_changes:
                self._audit_event(conn, "TRADING_SETTINGS_UPDATED", "root updated trading settings", actor=actor, metadata=setting_changes)
            if changed_markets:
                self._audit_event(conn, "TRADING_MARKET_BILLING_UPDATED", "root updated trading billing parameters", actor=actor, metadata={"markets": changed_markets})
            if not setting_changes and not changed_markets:
                raise ValueError("no trading settings changes")
            conn.commit()
            return {"ok": True, **self.get_root_settings()}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _live_price_symbol(self, market_symbol):
        return LIVE_PRICE_MARKETS.get(str(market_symbol or "").strip().upper())

    def _fetch_live_price_points(self, market_symbol):
        symbol = self._live_price_symbol(market_symbol)
        if not symbol:
            raise ValueError("live price is not supported for this market")
        if self.live_price_provider:
            price = self.live_price_provider(str(market_symbol or "").strip().upper())
        else:
            req = Request(
                f"{BINANCE_TICKER_URL}?{urlencode({'symbol': symbol})}",
                headers={"User-Agent": "hackme_web/1.0 trading-price"},
            )
            with urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            price = payload.get("price") if isinstance(payload, dict) else None
        try:
            price_points = int(round(float(price) * USDT_TO_POINTS_RATE))
        except Exception as exc:
            raise ValueError("live trading price format is invalid") from exc
        if price_points <= 0:
            raise ValueError("live trading price is invalid")
        return price_points

    def _current_market_price_points(self, conn, market):
        symbol = market["symbol"]
        settings = self._settings_payload(conn)
        configured_source = settings.get("price_source") or "binance_public_api"
        if configured_source == "manual_root" or not self._live_price_symbol(symbol):
            return int(market["manual_price_points"]), str(market["price_source"] or "manual_root")
        old_price = int(market["manual_price_points"] or 0)
        old_source = str(market["price_source"] or "")
        try:
            price = self._fetch_live_price_points(symbol)
        except Exception as exc:
            max_stale = int(settings.get("max_price_staleness_seconds") or 0)
            try:
                updated_at = datetime.fromisoformat(str(market["updated_at"]))
                stale_seconds = int((datetime.now() - updated_at).total_seconds())
            except Exception:
                stale_seconds = max_stale + 1
            if old_price > 0 and max_stale > 0 and stale_seconds <= max_stale and old_source in {"binance_public_api", "binance_public_api_cached"}:
                self._audit_event(
                    conn,
                    "TRADING_PRICE_FALLBACK_USED",
                    "live trading price unavailable; using cached last-good price",
                    market_symbol=symbol,
                    severity="warning",
                    metadata={"error": str(exc), "cached_price_points": old_price, "stale_seconds": stale_seconds, "max_stale_seconds": max_stale},
                )
                return old_price, "binance_public_api_cached"
            raise ValueError(f"live trading price unavailable for {symbol}: {exc}") from exc
        has_live_history = bool(conn.execute(
            """
            SELECT 1
            FROM trading_orders
            WHERE market_symbol=?
            UNION ALL
            SELECT 1 FROM trading_margin_positions WHERE market_symbol=?
            UNION ALL
            SELECT 1 FROM trading_futures_positions WHERE market_symbol=?
            LIMIT 1
            """,
            (symbol, symbol, symbol),
        ).fetchone())
        if old_price > 0 and old_source == "binance_public_api" and has_live_history:
            jump_bps = int(abs(price - old_price) * 10_000 / old_price) if old_price else 0
            allowed_bps = int(market["max_price_jump_bps"] or 0)
            if allowed_bps and jump_bps > allowed_bps:
                self._audit_event(
                    conn,
                    "TRADING_PRICE_CIRCUIT_BREAKER",
                    "live trading price jump exceeded market threshold",
                    market_symbol=symbol,
                    severity="critical",
                    metadata={"old_price_points": old_price, "new_price_points": price, "jump_bps": jump_bps, "allowed_bps": allowed_bps},
                )
                raise ValueError(f"live trading price jump {jump_bps} bps exceeds max {allowed_bps} for {symbol}")
        now = _now()
        conn.execute(
            "UPDATE trading_markets SET manual_price_points=?, price_source='binance_public_api', updated_at=? WHERE symbol=?",
            (price, now, symbol),
        )
        return price, "binance_public_api"

    def _root_sim_account(self, conn, user_id, *, actor=None):
        user_id = int(user_id)
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_sim_accounts (
                user_id, balance_points, locked_points, initial_balance_points, updated_at
            ) VALUES (?, ?, 0, ?, ?)
            """,
            (user_id, ROOT_SIMULATED_INITIAL_POINTS, ROOT_SIMULATED_INITIAL_POINTS, now),
        )
        return conn.execute("SELECT * FROM trading_sim_accounts WHERE user_id=?", (user_id,)).fetchone()

    def _sim_delta(self, conn, user_id, *, balance_delta=0, locked_delta=0):
        account = self._root_sim_account(conn, user_id)
        next_balance = int(account["balance_points"] or 0) + int(balance_delta)
        next_locked = int(account["locked_points"] or 0) + int(locked_delta)
        if next_balance < 0:
            raise ValueError("root simulated trading points are insufficient")
        if next_locked < 0:
            raise ValueError("root simulated locked points are inconsistent")
        conn.execute(
            "UPDATE trading_sim_accounts SET balance_points=?, locked_points=?, updated_at=? WHERE user_id=?",
            (next_balance, next_locked, _now(), int(user_id)),
        )
        return conn.execute("SELECT * FROM trading_sim_accounts WHERE user_id=?", (int(user_id),)).fetchone()

    def _is_root_user_id(self, conn, user_id):
        row = conn.execute("SELECT username FROM users WHERE id=?", (int(user_id),)).fetchone()
        return bool(row and row["username"] == "root")

    def _system_actor(self):
        return {"username": "system", "role": "system"}

    def _trial_credit_row(self, conn, user_id):
        return conn.execute("SELECT * FROM trading_trial_credits WHERE user_id=?", (int(user_id),)).fetchone()

    def _ensure_trial_credit(self, conn, user_id, *, actor=None, allow_reclaim=True):
        user_id = int(user_id)
        if self._is_root_user_id(conn, user_id):
            return None
        row = self._trial_credit_row(conn, user_id)
        now = _now()
        if not row:
            expires_at = (datetime.fromisoformat(now) + timedelta(days=TRIAL_CREDIT_DAYS)).isoformat()
            conn.execute(
                """
                INSERT INTO trading_trial_credits (
                    user_id, initial_points, available_points, locked_points, deployed_points,
                    status, activated_at, expires_at, updated_at
                ) VALUES (?, ?, ?, 0, 0, 'active', ?, ?, ?)
                """,
                (user_id, TRIAL_CREDIT_INITIAL_POINTS, TRIAL_CREDIT_INITIAL_POINTS, now, expires_at, now),
            )
            self._audit_event(
                conn,
                "TRADING_TRIAL_CREDIT_GRANTED",
                "exchange trial credit granted as system loan",
                actor=actor or self._system_actor(),
                target_user_id=user_id,
                severity="info",
                metadata={
                    "loan_type": "exchange_trial_credit",
                    "amount_points": TRIAL_CREDIT_INITIAL_POINTS,
                    "expires_at": expires_at,
                    "reclaim_policy": "principal_only; user keeps realized profit",
                },
            )
            row = self._trial_credit_row(conn, user_id)
        if allow_reclaim and row and row["status"] == "active":
            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except Exception:
                expires_at = None
            if expires_at and datetime.fromisoformat(_now()) >= expires_at:
                self._reclaim_trial_credit(conn, user_id, actor=actor or self._system_actor(), reason="TRIAL_CREDIT_EXPIRED")
                row = self._trial_credit_row(conn, user_id)
        return row

    def _trial_position(self, conn, user_id, symbol):
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_trial_position_costs
                (user_id, market_symbol, quantity_units, trial_cost_points, updated_at)
            VALUES (?, ?, 0, 0, ?)
            """,
            (int(user_id), symbol, now),
        )
        return conn.execute(
            "SELECT * FROM trading_trial_position_costs WHERE user_id=? AND market_symbol=?",
            (int(user_id), symbol),
        ).fetchone()

    def _trial_delta(self, conn, user_id, *, available_delta=0, locked_delta=0, deployed_delta=0, status=None, reclaimed=False):
        row = self._ensure_trial_credit(conn, user_id, allow_reclaim=False)
        if not row:
            return None
        next_available = int(row["available_points"] or 0) + int(available_delta)
        next_locked = int(row["locked_points"] or 0) + int(locked_delta)
        next_deployed = int(row["deployed_points"] or 0) + int(deployed_delta)
        if min(next_available, next_locked, next_deployed) < 0:
            raise ValueError("trial credit accounting would become negative")
        next_status = status or row["status"]
        if next_status == "active" and next_available == 0 and next_locked == 0 and next_deployed == 0:
            next_status = "depleted"
        conn.execute(
            """
            UPDATE trading_trial_credits
            SET available_points=?, locked_points=?, deployed_points=?, status=?,
                reclaimed_at=CASE WHEN ? THEN ? ELSE reclaimed_at END,
                updated_at=?
            WHERE user_id=?
            """,
            (next_available, next_locked, next_deployed, next_status, 1 if reclaimed else 0, _now(), _now(), int(user_id)),
        )
        return self._trial_credit_row(conn, user_id)

    def _trial_lock_for_buy(self, conn, user_id, total_points):
        row = self._ensure_trial_credit(conn, user_id)
        if not row or row["status"] != "active":
            return 0
        amount = min(int(total_points or 0), int(row["available_points"] or 0))
        if amount <= 0:
            return 0
        self._trial_delta(conn, user_id, available_delta=-amount, locked_delta=amount)
        return amount

    def _trial_spend(self, conn, user_id, amount):
        row = self._ensure_trial_credit(conn, user_id)
        if not row or row["status"] != "active":
            return 0
        amount = min(int(amount or 0), int(row["available_points"] or 0))
        if amount <= 0:
            return 0
        self._trial_delta(conn, user_id, available_delta=-amount)
        return amount

    def _trial_deploy(self, conn, user_id, amount):
        row = self._ensure_trial_credit(conn, user_id)
        if not row or row["status"] != "active":
            return 0
        amount = min(int(amount or 0), int(row["available_points"] or 0))
        if amount <= 0:
            return 0
        self._trial_delta(conn, user_id, available_delta=-amount, deployed_delta=amount)
        return amount

    def _trial_unlock(self, conn, user_id, amount):
        amount = int(amount or 0)
        if amount <= 0:
            return
        self._trial_delta(conn, user_id, available_delta=amount, locked_delta=-amount)

    def _trial_mark_buy_executed(self, conn, *, user_id, market_symbol, quantity_units, trial_used_points, total_points):
        trial_used_points = int(trial_used_points or 0)
        if trial_used_points <= 0:
            return 0
        total_points = max(1, int(total_points or 0))
        trial_units = int(quantity_units) if trial_used_points >= total_points else int((int(quantity_units) * trial_used_points) // total_points)
        if trial_units <= 0:
            trial_units = 1
        trial_units = min(int(quantity_units), trial_units)
        self._trial_delta(conn, user_id, locked_delta=-trial_used_points, deployed_delta=trial_used_points)
        trial_pos = self._trial_position(conn, user_id, market_symbol)
        conn.execute(
            """
            UPDATE trading_trial_position_costs
            SET quantity_units=?, trial_cost_points=?, updated_at=?
            WHERE user_id=? AND market_symbol=?
            """,
            (
                int(trial_pos["quantity_units"] or 0) + trial_units,
                int(trial_pos["trial_cost_points"] or 0) + trial_used_points,
                _now(),
                int(user_id),
                market_symbol,
            ),
        )
        return trial_units

    def _trial_allocate_sell(self, conn, *, user_id, market_symbol, quantity_units, net_credit_points):
        trial_pos = self._trial_position(conn, user_id, market_symbol)
        available_trial_units = int(trial_pos["quantity_units"] or 0)
        trial_cost_total = int(trial_pos["trial_cost_points"] or 0)
        quantity_units = int(quantity_units)
        net_credit_points = int(net_credit_points or 0)
        if available_trial_units <= 0 or trial_cost_total <= 0 or quantity_units <= 0 or net_credit_points <= 0:
            return {"trial_units": 0, "trial_cost_points": 0, "trial_repaid_points": 0, "trial_profit_points": 0, "wallet_credit_points": net_credit_points}
        trial_units = min(available_trial_units, quantity_units)
        if trial_units == available_trial_units:
            trial_cost = trial_cost_total
        else:
            trial_cost = int(math.ceil(trial_cost_total * trial_units / available_trial_units))
        trial_net_credit = int(math.floor(net_credit_points * trial_units / quantity_units))
        trial_repaid = min(trial_net_credit, trial_cost)
        trial_profit = max(0, trial_net_credit - trial_cost)
        wallet_credit = max(0, net_credit_points - trial_repaid)
        remaining_units = max(0, available_trial_units - trial_units)
        remaining_cost = max(0, trial_cost_total - trial_cost)
        conn.execute(
            """
            UPDATE trading_trial_position_costs
            SET quantity_units=?, trial_cost_points=?, updated_at=?
            WHERE user_id=? AND market_symbol=?
            """,
            (remaining_units, remaining_cost, _now(), int(user_id), market_symbol),
        )
        self._trial_delta(conn, user_id, available_delta=trial_repaid, deployed_delta=-trial_cost)
        return {
            "trial_units": trial_units,
            "trial_cost_points": trial_cost,
            "trial_repaid_points": trial_repaid,
            "trial_profit_points": trial_profit,
            "wallet_credit_points": wallet_credit,
        }

    def _reclaim_trial_credit(self, conn, user_id, *, actor=None, reason="TRIAL_CREDIT_RECLAIM"):
        row = self._trial_credit_row(conn, user_id)
        if not row or row["status"] != "active":
            return row
        actor = actor or self._system_actor()
        reclaimed_before_sell = int(row["available_points"] or 0)
        for order in conn.execute(
            """
            SELECT * FROM trading_orders
            WHERE user_id=? AND side='buy' AND status IN ('open', 'partially_filled')
              AND trial_frozen_points > 0
            ORDER BY id ASC
            """,
            (int(user_id),),
        ).fetchall():
            trial_frozen = int(order["trial_frozen_points"] or 0)
            chain_frozen = int(order["chain_frozen_points"] or 0)
            if trial_frozen:
                self._trial_delta(conn, user_id, locked_delta=-trial_frozen)
            if chain_frozen:
                self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="unfreeze",
                    amount=chain_frozen,
                    action_type="trading_unfreeze",
                    reference_type="trading_order",
                    reference_id=order["order_uuid"],
                    idempotency_key=f"trading:trial_reclaim_cancel_unfreeze:{order['order_uuid']}",
                    reason="TRIAL_CREDIT_RECLAIM_CANCEL_ORDER",
                    public_metadata={"order_id": order["id"], "market": order["market_symbol"], "side": order["side"]},
                    actor=actor,
                )
            conn.execute(
                """
                UPDATE trading_orders
                SET status='cancelled', frozen_points=0, trial_frozen_points=0, chain_frozen_points=0,
                    reason=?, updated_at=?
                WHERE id=?
                """,
                (f"{reason}: trial credit reclaimed", _now(), order["id"]),
            )
            self._audit_event(
                conn,
                "TRADING_TRIAL_CREDIT_ORDER_CANCELLED",
                "open trial-funded buy order cancelled during trial credit reclaim",
                actor=actor,
                target_user_id=int(user_id),
                order_id=order["id"],
                market_symbol=order["market_symbol"],
                severity="warning",
                metadata={"reason": reason, "trial_frozen_points": trial_frozen, "chain_frozen_points": chain_frozen},
            )
        for trial_pos in conn.execute(
            "SELECT * FROM trading_trial_position_costs WHERE user_id=? AND quantity_units>0 ORDER BY market_symbol",
            (int(user_id),),
        ).fetchall():
            position = self._position(conn, user_id, trial_pos["market_symbol"])
            sell_units = min(int(position["quantity_units"] or 0), int(trial_pos["quantity_units"] or 0))
            if sell_units <= 0:
                continue
            market = self._market(conn, trial_pos["market_symbol"])
            current_price, price_source = self._current_market_price_points(conn, market)
            order_uuid = str(uuid.uuid4())
            now = _now()
            conn.execute(
                """
                UPDATE trading_spot_positions
                SET quantity_units=quantity_units-?, locked_quantity_units=locked_quantity_units+?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (sell_units, sell_units, now, int(user_id), trial_pos["market_symbol"]),
            )
            cur = conn.execute(
                """
                INSERT INTO trading_orders (
                    order_uuid, user_id, market_symbol, side, order_type, funding_mode, execution_mode,
                    quantity_units, limit_price_points, execution_price_points, status,
                    frozen_points, trial_frozen_points, chain_frozen_points, fee_points,
                    filled_quantity_units, reason, created_at, updated_at
                ) VALUES (?, ?, ?, 'sell', 'market', 'trial_mixed', 'house_counterparty',
                    ?, NULL, ?, 'open', 0, 0, 0, 0, 0, ?, ?, ?)
                """,
                (order_uuid, int(user_id), trial_pos["market_symbol"], sell_units, current_price, reason, now, now),
            )
            order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (cur.lastrowid,)).fetchone()
            fill = self._execute_order(conn, order, market, actor=actor)
            self._audit_event(
                conn,
                "TRADING_TRIAL_CREDIT_FORCED_SELL",
                "trial credit expiry forced spot liquidation",
                actor=actor,
                target_user_id=int(user_id),
                order_id=order["id"],
                market_symbol=market["symbol"],
                severity="warning",
                metadata={"fill_id": fill["id"], "price_source": price_source, "reason": reason},
            )
        final = self._trial_credit_row(conn, user_id)
        reclaimed_after_sell = int(final["available_points"] or 0)
        lost_points = int(final["deployed_points"] or 0)
        conn.execute(
            """
            UPDATE trading_trial_credits
            SET available_points=0, locked_points=0, deployed_points=0, status='expired',
                reclaimed_at=?, updated_at=?
            WHERE user_id=?
            """,
            (_now(), _now(), int(user_id)),
        )
        conn.execute(
            "UPDATE trading_trial_position_costs SET quantity_units=0, trial_cost_points=0, updated_at=? WHERE user_id=?",
            (_now(), int(user_id)),
        )
        self._audit_event(
            conn,
            "TRADING_TRIAL_CREDIT_RECLAIMED",
            "exchange trial credit reclaimed from user",
            actor=actor,
            target_user_id=int(user_id),
            severity="warning",
            metadata={
                "loan_type": "exchange_trial_credit",
                "reason": reason,
                "reclaimed_available_before_sell": reclaimed_before_sell,
                "reclaimed_available_after_sell": reclaimed_after_sell,
                "lost_points": lost_points,
                "profit_policy": "realized profit remains with user",
            },
        )
        return self._trial_credit_row(conn, user_id)

    def _funding_payload(self, conn, user_id):
        user = conn.execute("SELECT username FROM users WHERE id=?", (int(user_id),)).fetchone()
        if user and user["username"] == "root":
            account = self._root_sim_account(conn, user_id)
            return {
                "mode": "root_simulated",
                "available_points": int(account["balance_points"] or 0),
                "locked_points": int(account["locked_points"] or 0),
                "initial_balance_points": int(account["initial_balance_points"] or ROOT_SIMULATED_INITIAL_POINTS),
                "note": "root 模擬交易資金不寫入 PointsChain，也不影響帳戶積分",
            }
        trial = self._ensure_trial_credit(conn, user_id)
        wallet = self.points_service.ensure_wallet(conn, user_id)
        payload = self.points_service.serialize_wallet(wallet)
        wallet_available = int(payload.get("points_balance") or 0)
        wallet_locked = int(payload.get("points_frozen") or 0)
        trial_payload = None
        if trial:
            trial_payload = {
                "initial_points": int(trial["initial_points"] or 0),
                "available_points": int(trial["available_points"] or 0),
                "locked_points": int(trial["locked_points"] or 0),
                "deployed_points": int(trial["deployed_points"] or 0),
                "status": trial["status"],
                "activated_at": trial["activated_at"],
                "expires_at": trial["expires_at"],
                "reclaimed_at": trial["reclaimed_at"],
                "days_valid": TRIAL_CREDIT_DAYS,
            }
        return {
            "mode": "points_chain",
            "available_points": wallet_available + int(trial["available_points"] or 0) if trial else wallet_available,
            "locked_points": wallet_locked + int(trial["locked_points"] or 0) if trial else wallet_locked,
            "wallet_available_points": wallet_available,
            "wallet_locked_points": wallet_locked,
            "trial_credit": trial_payload,
            "note": "一般用戶交易會優先使用交易所體驗金，體驗金到期或賠光後停止使用；已實現獲利保留給用戶",
        }

    def _position_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["locked_quantity"] = units_to_quantity(item["locked_quantity_units"])
        return item

    def _position_payload_with_metrics(self, row, *, market=None, realized_points=0, total_fees=0):
        item = self._position_payload(row)
        quantity_units = int(item["quantity_units"] or 0) + int(item["locked_quantity_units"] or 0)
        avg_cost = int(item["avg_cost_points"] or 0)
        current_price = int((market or {}).get("manual_price_points") or 0)
        fee_bps = int((market or {}).get("fee_bps") or 0)
        gross_cost = notional_points(quantity_units, avg_cost) if quantity_units and avg_cost else 0
        current_value = notional_points(quantity_units, current_price) if quantity_units and current_price else 0
        estimated_buy_fee = fee_points(gross_cost, fee_bps) if gross_cost else 0
        estimated_exit_fee = fee_points(current_value, fee_bps) if current_value else 0
        cost_basis = gross_cost + estimated_buy_fee + estimated_exit_fee
        unrealized = current_value - cost_basis if quantity_units else 0
        item.update({
            "available_quantity_units": int(item["quantity_units"] or 0),
            "total_quantity_units": quantity_units,
            "total_quantity": units_to_quantity(quantity_units),
            "current_price_points": current_price,
            "gross_cost_points": gross_cost,
            "current_value_points": current_value,
            "estimated_buy_fee_points": estimated_buy_fee,
            "estimated_exit_fee_points": estimated_exit_fee,
            "cost_basis_points": cost_basis,
            "unrealized_pnl_points": unrealized,
            "realized_pnl_points": int(realized_points or 0),
            "total_pnl_points": int(realized_points or 0) + unrealized,
            "total_fee_points": int(total_fees or 0),
        })
        item["pnl_percent"] = round((unrealized / cost_basis) * 100, 4) if cost_basis else 0
        return item

    def _futures_position_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        return item

    def _margin_position_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["position_label"] = "融資做多" if item["position_type"] == "margin_long" else "借券放空"
        return item

    def _borrowing_settings(self, conn):
        settings = self._settings_payload(conn)
        return {
            "enabled": bool(settings.get("borrowing_enabled")),
            "interest_bps_daily": int(settings.get("borrow_interest_bps_daily") or 0),
        }

    def _assert_borrowing_enabled(self, conn):
        settings = self._borrowing_settings(conn)
        if not settings["enabled"]:
            raise ValueError("borrow trading is disabled")
        return settings

    def _margin_interest_points(self, row, now_text=None):
        principal = int(row["principal_points"] or 0)
        bps = int(row["interest_bps_daily"] or 0)
        if principal <= 0 or bps <= 0:
            return 0
        try:
            opened_at = datetime.fromisoformat(str(row["opened_at"]))
            closed_at = datetime.fromisoformat(str(now_text or _now()))
        except Exception:
            return 0
        seconds = max(0, (closed_at - opened_at).total_seconds())
        days = int(seconds // 86400)
        if days <= 0:
            return 0
        return int(math.ceil(principal * bps * days / 10_000))

    def _margin_risk_payload(self, conn, position, market=None, *, now_text=None):
        market = market or self._market(conn, position["market_symbol"])
        price, price_source = self._current_market_price_points(conn, market)
        quantity_units = int(position["quantity_units"])
        exit_notional = notional_points(quantity_units, price)
        close_fee = fee_points(exit_notional, int(market["fee_bps"] or 0))
        interest = self._margin_interest_points(position, now_text=now_text)
        collateral = int(position["collateral_points"] or 0)
        principal = int(position["principal_points"] or 0)
        if position["position_type"] == "margin_long":
            equity_after = exit_notional - principal - interest - close_fee
            delta = equity_after - collateral
        else:
            delta = principal - exit_notional - interest - close_fee
            equity_after = collateral + delta
        settings = self._settings_payload(conn)
        maintenance_bps = int(settings.get("margin_maintenance_bps") or 0)
        maintenance_points = int(math.ceil(exit_notional * maintenance_bps / 10_000))
        return {
            "price_points": price,
            "price_source": price_source,
            "exit_notional_points": exit_notional,
            "close_fee_points": close_fee,
            "interest_points": interest,
            "collateral_points": collateral,
            "principal_points": principal,
            "delta_points": delta,
            "equity_after_points": equity_after,
            "maintenance_bps": maintenance_bps,
            "maintenance_points": maintenance_points,
            "liquidation_required": equity_after <= maintenance_points,
        }

    def _fill_payload(self, row, realized=None):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["points_ledger_uuids"] = _json_loads(item.get("points_ledger_uuids_json"), [])
        if realized is not None:
            item["realized_pnl_points"] = int(realized["net_pnl_points"] or 0)
            item["gross_cost_points"] = int(realized["gross_cost_points"] or 0)
            item["buy_fee_estimate_points"] = int(realized["buy_fee_estimate_points"] or 0)
        return item

    def _spot_realized_map(self, conn, user_id):
        return {
            row["market_symbol"]: int(row["realized_pnl_points"] or 0)
            for row in conn.execute(
                """
                SELECT market_symbol, COALESCE(SUM(net_pnl_points), 0) AS realized_pnl_points
                FROM trading_spot_realized_pnl
                WHERE user_id=?
                GROUP BY market_symbol
                """,
                (int(user_id),),
            ).fetchall()
        }

    def _spot_fee_map(self, conn, user_id):
        return {
            row["market_symbol"]: int(row["total_fee_points"] or 0)
            for row in conn.execute(
                """
                SELECT market_symbol, COALESCE(SUM(fee_points), 0) AS total_fee_points
                FROM trading_fills
                WHERE user_id=?
                GROUP BY market_symbol
                """,
                (int(user_id),),
            ).fetchall()
        }

    def _spot_summary_payload(self, positions):
        return {
            "current_value_points": sum(int(row.get("current_value_points") or 0) for row in positions),
            "cost_basis_points": sum(int(row.get("cost_basis_points") or 0) for row in positions),
            "unrealized_pnl_points": sum(int(row.get("unrealized_pnl_points") or 0) for row in positions),
            "realized_pnl_points": sum(int(row.get("realized_pnl_points") or 0) for row in positions),
            "total_pnl_points": sum(int(row.get("total_pnl_points") or 0) for row in positions),
            "total_fee_points": sum(int(row.get("total_fee_points") or 0) for row in positions),
        }

    def _notify_trade_filled(self, conn, fill):
        try:
            side_label = "買入" if fill["side"] == "buy" else "賣出"
            quantity = units_to_quantity(fill["quantity_units"])
            create_notification_if_enabled(
                conn,
                user_id=fill["user_id"],
                type="trading_order_filled",
                title="交易已成交",
                body=(
                    f"{fill['market_symbol']} {side_label} {quantity} 已成交，"
                    f"成交價 {int(fill['price_points'])}，成交額 {int(fill['notional_points'])}，"
                    f"手續費 {int(fill['fee_points'] or 0)}。"
                ),
                link="/trading",
            )
        except Exception:
            pass

    def _is_insufficient_error(self, exc):
        lowered = str(exc or "").lower()
        return any(term in lowered for term in ("insufficient", "餘額不足", "積分不足", "持倉不足"))

    def _notify_insufficient_balance(self, *, user_id, market_symbol, side, order_type, quantity, error):
        conn = self.get_db()
        try:
            create_notification_if_enabled(
                conn,
                user_id=user_id,
                type="trading_balance_insufficient",
                title="交易未成立：餘額不足",
                body=(
                    f"{market_symbol or '交易市場'} {side or '-'} {order_type or '-'} "
                    f"數量 {quantity} 未成立：{str(error)[:180]}"
                ),
                link="/trading",
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    def _notify_margin_liquidated(self, conn, *, user_id, position, risk):
        try:
            create_notification_if_enabled(
                conn,
                user_id=user_id,
                type="trading_margin_liquidated",
                title="進階交易倉位已被強制平倉",
                body=(
                    f"{position['market_symbol']} {position['position_type']} 已低於維持保證金並自動清算；"
                    f"結算價 {int(risk.get('price_points') or 0)}，"
                    f"損益 {int(risk.get('delta_points') or 0)} 點。"
                ),
                link="/trading",
            )
        except Exception:
            pass

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
            self._ensure_trial_credit(conn, user_id)
            conn.commit()
            state = self._state(conn)
            markets = [self._market_payload(row) for row in conn.execute("SELECT * FROM trading_markets WHERE enabled=1 ORDER BY symbol").fetchall()]
            market_map = {row["symbol"]: row for row in markets}
            realized_map = self._spot_realized_map(conn, user_id)
            fee_map = self._spot_fee_map(conn, user_id)
            positions = [
                self._position_payload_with_metrics(
                    row,
                    market=market_map.get(row["market_symbol"]),
                    realized_points=realized_map.get(row["market_symbol"], 0),
                    total_fees=fee_map.get(row["market_symbol"], 0),
                )
                for row in conn.execute("SELECT * FROM trading_spot_positions WHERE user_id=? ORDER BY market_symbol", (int(user_id),)).fetchall()
            ]
            futures_positions = [
                self._futures_position_payload(row)
                for row in conn.execute("SELECT * FROM trading_futures_positions WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            margin_positions = [
                self._margin_position_payload(row)
                for row in conn.execute("SELECT * FROM trading_margin_positions WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            orders = [
                self._order_payload(row)
                for row in conn.execute("SELECT * FROM trading_orders WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            fill_rows = conn.execute("SELECT * FROM trading_fills WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            pnl_by_fill = {
                row["fill_id"]: row
                for row in conn.execute(
                    """
                    SELECT *
                    FROM trading_spot_realized_pnl
                    WHERE user_id=? AND fill_id IN (
                        SELECT id FROM trading_fills WHERE user_id=? ORDER BY id DESC LIMIT 50
                    )
                    """,
                    (int(user_id), int(user_id)),
                ).fetchall()
            }
            fills = [self._fill_payload(row, realized=pnl_by_fill.get(row["id"])) for row in fill_rows]
            return {
                "state": state,
                "settings": self._settings_payload(conn),
                "funding": self._funding_payload(conn, user_id),
                "markets": markets,
                "positions": positions,
                "spot_summary": self._spot_summary_payload(positions),
                "futures_positions": futures_positions,
                "margin_positions": margin_positions,
                "orders": orders,
                "fills": fills,
            }
        finally:
            conn.close()

    def _is_executable(self, market, *, side, order_type, limit_price, current_price):
        current_price = int(current_price)
        if order_type == "market":
            return True, current_price
        limit_price = int(limit_price or 0)
        if side == "buy" and limit_price >= current_price:
            return True, current_price
        if side == "sell" and limit_price <= current_price:
            return True, current_price
        return False, None

    def place_order(self, *, actor, market_symbol, side, order_type, quantity, limit_price_points=None, emergency_close=False):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        side = str(side or "").lower()
        order_type = str(order_type or "").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        emergency_close = bool(emergency_close)
        if emergency_close and (side != "sell" or order_type != "market"):
            raise ValueError("emergency close only supports market sell")
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
            current_price, price_source = self._current_market_price_points(conn, market)
            if order_type == "limit":
                limit_price = _to_int(limit_price_points, name="limit_price_points", minimum=1)
            else:
                limit_price = None
            check_price = int(limit_price or current_price)
            estimated_notional = notional_points(quantity_units, check_price)
            effective_fee_bps = int(market["fee_bps"] or 0) * (2 if emergency_close else 1)
            fee = fee_points(estimated_notional, effective_fee_bps)
            total_points = estimated_notional + fee
            if estimated_notional < int(market["min_order_points"]):
                raise ValueError("order notional is below market minimum")
            if estimated_notional > int(market["max_order_points"]):
                raise ValueError("order notional exceeds market maximum")
            if side == "sell" and estimated_notional - fee <= 0:
                raise ValueError("sell notional after fee must be positive")

            executable, execution_price = self._is_executable(
                market,
                side=side,
                order_type=order_type,
                limit_price=limit_price,
                current_price=current_price,
            )
            now = _now()
            order_uuid = str(uuid.uuid4())
            funding_mode = "root_simulated" if self._is_root_actor(actor) else "points_chain"
            trial_frozen = 0
            chain_frozen = 0
            if side == "buy" and funding_mode != "root_simulated":
                trial_frozen = self._trial_lock_for_buy(conn, user_id, total_points)
                chain_frozen = total_points - trial_frozen
                funding_mode = "trial_mixed" if trial_frozen else "points_chain"
            elif side == "sell" and funding_mode != "root_simulated":
                trial_position = self._trial_position(conn, user_id, market["symbol"])
                if int(trial_position["quantity_units"] or 0) > 0:
                    funding_mode = "trial_mixed"
            frozen_points = total_points if side == "buy" else 0
            order_reason = "EMERGENCY_MARKET_CLOSE" if emergency_close else ""
            cur = conn.execute(
                """
                INSERT INTO trading_orders (
                    order_uuid, user_id, market_symbol, side, order_type, funding_mode, execution_mode,
                    quantity_units, limit_price_points, execution_price_points, status,
                    frozen_points, trial_frozen_points, chain_frozen_points, fee_points,
                    filled_quantity_units, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'house_counterparty', ?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    order_uuid,
                    user_id,
                    market["symbol"],
                    side,
                    order_type,
                    funding_mode,
                    quantity_units,
                    limit_price,
                    execution_price,
                    frozen_points,
                    trial_frozen,
                    chain_frozen,
                    fee,
                    order_reason,
                    now,
                    now,
                ),
            )
            order_id = cur.lastrowid
            ledger_rows = []
            if side == "buy":
                if funding_mode == "root_simulated":
                    self._sim_delta(conn, user_id, balance_delta=-total_points, locked_delta=total_points)
                elif chain_frozen > 0:
                    ledger_rows.append(self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="freeze",
                        amount=chain_frozen,
                        action_type="trading_freeze",
                        reference_type="trading_order",
                        reference_id=order_uuid,
                        idempotency_key=f"trading:freeze:{order_uuid}",
                        reason="TRADING_FREEZE",
                        public_metadata={
                            "order_id": order_id,
                            "market": market["symbol"],
                            "side": side,
                            "order_type": order_type,
                            "price_source": price_source,
                            "fee_bps": effective_fee_bps,
                            "trial_frozen_points": trial_frozen,
                            "chain_frozen_points": chain_frozen,
                        },
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
                event_type = "TRADING_EMERGENCY_MARKET_CLOSE" if emergency_close else "TRADING_ORDER_FILLED"
                message = "emergency market close filled" if emergency_close else "spot order filled"
                self._audit_event(conn, event_type, message, actor=actor, target_user_id=user_id, order_id=order_id, market_symbol=market["symbol"], severity="warning" if emergency_close else "info", metadata={"fill_id": fill["id"], "price_source": price_source, "execution_price_points": execution_price, "fee_bps": effective_fee_bps})
                self._notify_trade_filled(conn, fill)
            else:
                order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (order_id,)).fetchone()
                self._audit_event(conn, "TRADING_ORDER_OPEN", "limit order stored as open order", actor=actor, target_user_id=user_id, order_id=order_id, market_symbol=market["symbol"], metadata={"price_source": price_source, "current_price_points": current_price})
            conn.commit()
            return {"ok": True, "order": self._order_payload(order), "executed": executable}
        except Exception as exc:
            conn.rollback()
            if self._is_insufficient_error(exc):
                self._notify_insufficient_balance(
                    user_id=user_id,
                    market_symbol=market_symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    error=exc,
                )
            raise
        finally:
            conn.close()

    def match_open_limit_orders(self, *, actor=None, market_symbol=None, limit=200):
        limit = _to_int(limit or 200, name="limit", minimum=1, maximum=1000)
        actor = actor or {"username": "system", "role": "system"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            params = []
            where = "WHERE order_type='limit' AND status IN ('open', 'partially_filled')"
            if market_symbol:
                where += " AND market_symbol=?"
                params.append(str(market_symbol or "").strip().upper())
            order_uuids = [
                row["order_uuid"]
                for row in conn.execute(
                    f"SELECT order_uuid FROM trading_orders {where} ORDER BY id ASC LIMIT ?",
                    (*params, limit),
                ).fetchall()
            ]
        finally:
            conn.close()

        matched = []
        skipped = 0
        errors = []
        for order_uuid in order_uuids:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                self._assert_writable(conn)
                order = conn.execute("SELECT * FROM trading_orders WHERE order_uuid=?", (order_uuid,)).fetchone()
                if not order or order["status"] not in OPEN_ORDER_STATUSES or order["order_type"] != "limit":
                    conn.rollback()
                    skipped += 1
                    continue
                market = self._market(conn, order["market_symbol"])
                current_price, price_source = self._current_market_price_points(conn, market)
                executable, execution_price = self._is_executable(
                    market,
                    side=order["side"],
                    order_type=order["order_type"],
                    limit_price=order["limit_price_points"],
                    current_price=current_price,
                )
                if not executable:
                    conn.rollback()
                    skipped += 1
                    continue
                conn.execute(
                    "UPDATE trading_orders SET execution_price_points=?, updated_at=? WHERE id=?",
                    (execution_price, _now(), order["id"]),
                )
                order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (order["id"],)).fetchone()
                fill = self._execute_order(conn, order, market, actor=actor)
                self._audit_event(
                    conn,
                    "TRADING_LIMIT_ORDER_MATCHED",
                    "limit order matched by scheduled matcher",
                    actor=actor,
                    target_user_id=int(order["user_id"]),
                    order_id=order["id"],
                    market_symbol=market["symbol"],
                    metadata={"fill_id": fill["id"], "price_source": price_source, "execution_price_points": execution_price},
                )
                self._notify_trade_filled(conn, fill)
                conn.commit()
                matched.append({
                    "order_uuid": order["order_uuid"],
                    "fill_uuid": fill["fill_uuid"],
                    "market_symbol": market["symbol"],
                    "side": order["side"],
                    "execution_price_points": execution_price,
                })
            except Exception as exc:
                conn.rollback()
                errors.append({"order_uuid": order_uuid, "error": str(exc)})
            finally:
                conn.close()
        return {"ok": not errors, "scanned": len(order_uuids), "matched": matched, "skipped": skipped, "errors": errors}

    def _execute_order(self, conn, order, market, *, actor):
        side = order["side"]
        user_id = int(order["user_id"])
        quantity_units = int(order["quantity_units"])
        price = int(order["execution_price_points"] or market["manual_price_points"])
        notional = notional_points(quantity_units, price)
        emergency_close = str(order["reason"] or "") == "EMERGENCY_MARKET_CLOSE"
        effective_fee_bps = int(market["fee_bps"] or 0) * (2 if emergency_close else 1)
        fee = fee_points(notional, effective_fee_bps)
        total = notional + fee
        ledger_uuids = []
        funding_mode = order["funding_mode"] if "funding_mode" in order.keys() else "points_chain"
        sell_pnl_data = None
        trial_repaid = 0
        trial_profit = 0
        if side == "buy":
            frozen_amount = int(order["frozen_points"] or total)
            trial_frozen = int(order["trial_frozen_points"] or 0) if "trial_frozen_points" in order.keys() else 0
            chain_frozen = int(order["chain_frozen_points"] or 0) if "chain_frozen_points" in order.keys() else (0 if funding_mode == "root_simulated" else frozen_amount)
            if funding_mode == "root_simulated":
                refund = max(0, frozen_amount - total)
                self._sim_delta(conn, user_id, balance_delta=refund, locked_delta=-frozen_amount)
            else:
                trial_used = min(trial_frozen, total)
                trial_refund = max(0, trial_frozen - trial_used)
                if trial_refund:
                    self._trial_unlock(conn, user_id, trial_refund)
                if trial_used:
                    self._trial_mark_buy_executed(
                        conn,
                        user_id=user_id,
                        market_symbol=market["symbol"],
                        quantity_units=quantity_units,
                        trial_used_points=trial_used,
                        total_points=total,
                    )
                chain_spend = max(0, total - trial_used)
                chain_refund = max(0, chain_frozen - chain_spend)
                if chain_frozen > 0:
                    ledger_uuids.append(self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="unfreeze",
                        amount=chain_frozen,
                        action_type="trading_unfreeze",
                        reference_type="trading_order",
                        reference_id=order["order_uuid"],
                        idempotency_key=f"trading:unfreeze:settle:{order['order_uuid']}",
                        reason="TRADING_UNFREEZE_SETTLEMENT",
                        public_metadata={"order_id": order["id"], "market": market["symbol"], "side": side, "chain_refund_points": chain_refund},
                        actor=actor,
                    )["ledger_uuid"])
                if chain_spend > 0:
                    ledger_uuids.append(self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="debit",
                        amount=chain_spend,
                        action_type="trading_spot_buy",
                        reference_type="trading_order",
                        reference_id=order["order_uuid"],
                        idempotency_key=f"trading:spot_buy:{order['order_uuid']}",
                        reason="TRADING_SPOT_BUY",
                        public_metadata={
                            "order_id": order["id"],
                            "market": market["symbol"],
                            "price": price,
                            "quantity": units_to_quantity(quantity_units),
                            "notional": notional,
                            "fee": fee,
                            "trial_used_points": trial_used,
                            "chain_spend_points": chain_spend,
                        },
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
            reserve_delta = 0 if funding_mode == "root_simulated" else min(fee, max(0, total - trial_used if funding_mode != "root_simulated" else fee))
            if funding_mode != "root_simulated" and reserve_delta:
                self._reserve_delta(conn, delta=reserve_delta, event_type="fee_retained", reason="TRADING_FEE", actor=actor, order_id=order["id"])
        else:
            if notional <= 0:
                raise ValueError("sell notional is too small")
            net_credit = notional - fee
            if net_credit <= 0:
                raise ValueError("sell notional is too small after fee")
            if funding_mode == "root_simulated":
                self._sim_delta(conn, user_id, balance_delta=net_credit)
            else:
                trial_allocation = self._trial_allocate_sell(
                    conn,
                    user_id=user_id,
                    market_symbol=market["symbol"],
                    quantity_units=quantity_units,
                    net_credit_points=net_credit,
                )
                trial_repaid = int(trial_allocation["trial_repaid_points"] or 0)
                trial_profit = int(trial_allocation["trial_profit_points"] or 0)
                wallet_credit = int(trial_allocation["wallet_credit_points"] or 0)
                if wallet_credit > 0:
                    ledger_uuids.append(self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="credit",
                        amount=wallet_credit,
                        action_type="trading_spot_sell",
                        reference_type="trading_order",
                        reference_id=order["order_uuid"],
                        idempotency_key=f"trading:spot_sell:{order['order_uuid']}",
                        reason="TRADING_SPOT_SELL",
                        public_metadata={
                            "order_id": order["id"],
                            "market": market["symbol"],
                            "price": price,
                            "quantity": units_to_quantity(quantity_units),
                            "notional": notional,
                            "fee": fee,
                            "trial_repaid_points": trial_repaid,
                            "trial_profit_points": trial_profit,
                        },
                        actor=actor,
                    )["ledger_uuid"])
                if fee:
                    self._reserve_delta(conn, delta=fee, event_type="fee_retained", reason="TRADING_FEE", actor=actor, order_id=order["id"])
            position = self._position(conn, user_id, market["symbol"])
            if int(position["locked_quantity_units"]) < quantity_units:
                raise ValueError("insufficient locked spot position")
            avg_cost = int(position["avg_cost_points"] or 0)
            gross_cost = notional_points(quantity_units, avg_cost) if avg_cost else 0
            buy_fee_estimate = fee_points(gross_cost, int(market["fee_bps"] or 0)) if gross_cost else 0
            net_pnl = net_credit - gross_cost - buy_fee_estimate
            sell_pnl_data = {
                "avg_cost_points": avg_cost,
                "gross_cost_points": gross_cost,
                "buy_fee_estimate_points": buy_fee_estimate,
                "net_pnl_points": net_pnl,
            }
            next_total_units = int(position["quantity_units"] or 0) + int(position["locked_quantity_units"] or 0) - quantity_units
            next_avg_cost = avg_cost if next_total_units > 0 else 0
            conn.execute(
                """
                UPDATE trading_spot_positions
                SET locked_quantity_units=locked_quantity_units-?, avg_cost_points=?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (quantity_units, next_avg_cost, _now(), user_id, market["symbol"]),
            )
            reserve_delta = 0 if funding_mode == "root_simulated" else fee
        fill_uuid = str(uuid.uuid4())
        cur = conn.execute(
            """
            INSERT INTO trading_fills (
                fill_uuid, order_id, user_id, market_symbol, side, funding_mode, quantity_units,
                price_points, notional_points, fee_points, reserve_delta_points,
                trial_repaid_points, trial_profit_points, points_ledger_uuids_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_uuid,
                order["id"],
                user_id,
                market["symbol"],
                side,
                funding_mode,
                quantity_units,
                price,
                notional,
                fee,
                reserve_delta,
                trial_repaid,
                trial_profit,
                _json_dumps(ledger_uuids),
                _now(),
            ),
        )
        fill_id = cur.lastrowid
        if sell_pnl_data is not None:
            conn.execute(
                """
                INSERT INTO trading_spot_realized_pnl (
                    pnl_uuid, user_id, market_symbol, order_id, fill_id, funding_mode,
                    quantity_units, avg_cost_points, sell_price_points, gross_cost_points,
                    gross_proceeds_points, buy_fee_estimate_points, sell_fee_points,
                    net_pnl_points, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    market["symbol"],
                    order["id"],
                    fill_id,
                    funding_mode,
                    quantity_units,
                    sell_pnl_data["avg_cost_points"],
                    price,
                    sell_pnl_data["gross_cost_points"],
                    notional,
                    sell_pnl_data["buy_fee_estimate_points"],
                    fee,
                    sell_pnl_data["net_pnl_points"],
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
        return conn.execute("SELECT * FROM trading_fills WHERE id=?", (fill_id,)).fetchone()

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
            funding_mode = order["funding_mode"] if "funding_mode" in order.keys() else "points_chain"
            if order["side"] == "buy" and int(order["frozen_points"] or 0) > 0:
                trial_frozen = int(order["trial_frozen_points"] or 0) if "trial_frozen_points" in order.keys() else 0
                chain_frozen = int(order["chain_frozen_points"] or 0) if "chain_frozen_points" in order.keys() else int(order["frozen_points"] or 0)
                if trial_frozen:
                    self._trial_unlock(conn, user_id, trial_frozen)
                if funding_mode == "root_simulated":
                    frozen = int(order["frozen_points"] or 0)
                    self._sim_delta(conn, user_id, balance_delta=frozen, locked_delta=-frozen)
                elif chain_frozen > 0:
                    self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="unfreeze",
                        amount=chain_frozen,
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

    def open_margin_position(self, *, actor, market_symbol, position_type, quantity, collateral_points):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        position_type = str(position_type or "").strip().lower()
        if position_type not in {"margin_long", "short"}:
            raise ValueError("position_type must be margin_long or short")
        quantity_units = quantity_to_units(quantity)
        collateral = _to_int(collateral_points, name="collateral_points", minimum=1, maximum=10**12)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            borrow_settings = self._assert_borrowing_enabled(conn)
            market = self._market(conn, market_symbol)
            price, price_source = self._current_market_price_points(conn, market)
            notional = notional_points(quantity_units, price)
            min_collateral = int(math.ceil(notional * MARGIN_MIN_COLLATERAL_BPS / 10_000))
            if collateral < min_collateral:
                raise ValueError(f"collateral below minimum {min_collateral}")
            fee = fee_points(notional, int(market["fee_bps"] or 0))
            principal = max(0, notional - collateral) if position_type == "margin_long" else notional
            position_uuid = str(uuid.uuid4())
            ledger_uuids = []
            trial_fee = self._trial_spend(conn, user_id, fee)
            chain_fee = fee - trial_fee
            trial_collateral = self._trial_deploy(conn, user_id, collateral)
            chain_collateral = collateral - trial_collateral
            if chain_collateral:
                ledger_uuids.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="freeze",
                    amount=chain_collateral,
                    action_type="trading_margin_collateral_freeze",
                    reference_type="trading_margin_position",
                    reference_id=position_uuid,
                    idempotency_key=f"trading:margin:collateral:{position_uuid}",
                    reason="TRADING_MARGIN_COLLATERAL",
                    public_metadata={
                        "position_type": position_type,
                        "market": market["symbol"],
                        "quantity": units_to_quantity(quantity_units),
                        "notional": notional,
                        "trial_collateral_points": trial_collateral,
                        "chain_collateral_points": chain_collateral,
                    },
                    actor=actor,
                )["ledger_uuid"])
            if chain_fee:
                ledger_uuids.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="debit",
                    amount=chain_fee,
                    action_type="trading_margin_open_fee",
                    reference_type="trading_margin_position",
                    reference_id=position_uuid,
                    idempotency_key=f"trading:margin:open_fee:{position_uuid}",
                    reason="TRADING_MARGIN_OPEN_FEE",
                    public_metadata={
                        "position_type": position_type,
                        "market": market["symbol"],
                        "fee_bps": int(market["fee_bps"] or 0),
                        "trial_fee_points": trial_fee,
                        "chain_fee_points": chain_fee,
                    },
                    actor=actor,
                )["ledger_uuid"])
            if fee:
                self._reserve_delta(conn, delta=fee, event_type="margin_fee_retained", reason="TRADING_MARGIN_OPEN_FEE", actor=actor)
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO trading_margin_positions (
                    position_uuid, user_id, market_symbol, position_type, quantity_units,
                    entry_price_points, principal_points, collateral_points, open_fee_points,
                    interest_bps_daily, status, opened_at, updated_at,
                    collateral_trial_points, collateral_chain_points, open_fee_trial_points, open_fee_chain_points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
                """,
                (
                    position_uuid,
                    user_id,
                    market["symbol"],
                    position_type,
                    quantity_units,
                    price,
                    principal,
                    collateral,
                    fee,
                    int(borrow_settings["interest_bps_daily"]),
                    now,
                    now,
                    trial_collateral,
                    chain_collateral,
                    trial_fee,
                    chain_fee,
                ),
            )
            self._audit_event(
                conn,
                "TRADING_MARGIN_POSITION_OPENED",
                "margin borrow position opened",
                actor=actor,
                target_user_id=user_id,
                market_symbol=market["symbol"],
                metadata={
                    "position_id": cur.lastrowid,
                    "position_uuid": position_uuid,
                    "position_type": position_type,
                    "quantity": units_to_quantity(quantity_units),
                    "entry_price_points": price,
                    "price_source": price_source,
                    "principal_points": principal,
                    "collateral_points": collateral,
                    "open_fee_points": fee,
                    "trial_collateral_points": trial_collateral,
                    "chain_collateral_points": chain_collateral,
                    "trial_fee_points": trial_fee,
                    "chain_fee_points": chain_fee,
                    "ledger_uuids": ledger_uuids,
                },
            )
            conn.commit()
            row = conn.execute("SELECT * FROM trading_margin_positions WHERE id=?", (cur.lastrowid,)).fetchone()
            return {"ok": True, "position": self._margin_position_payload(row), "funding": self._funding_payload(conn, user_id)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close_margin_position(self, *, actor, position_uuid, force_liquidation=False):
        actor_user_id = self._actor_id(actor)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            position = conn.execute(
                "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
                (str(position_uuid or ""),),
            ).fetchone()
            if not position:
                raise ValueError("margin position not found")
            user_id = int(position["user_id"])
            if not force_liquidation and int(user_id) != int(actor_user_id or 0):
                raise ValueError("cannot close another user's margin position")
            if position["status"] != "open":
                raise ValueError("margin position is not open")
            market = self._market(conn, position["market_symbol"])
            risk = self._margin_risk_payload(conn, position, market)
            if force_liquidation and not risk.get("liquidation_required"):
                raise ValueError("margin position recovered above liquidation threshold")
            price = risk["price_points"]
            price_source = risk["price_source"]
            close_fee = risk["close_fee_points"]
            interest = risk["interest_points"]
            collateral = int(position["collateral_points"] or 0)
            collateral_trial = int(position["collateral_trial_points"] or 0) if "collateral_trial_points" in position.keys() else 0
            collateral_chain = int(position["collateral_chain_points"] or 0) if "collateral_chain_points" in position.keys() else collateral
            delta = risk["delta_points"]
            ledger_uuids = []
            if collateral_chain:
                ledger_uuids.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="unfreeze",
                    amount=collateral_chain,
                    action_type="trading_margin_collateral_unfreeze",
                    reference_type="trading_margin_position",
                    reference_id=position["position_uuid"],
                    idempotency_key=f"trading:margin:collateral_unfreeze:{position['position_uuid']}",
                    reason="TRADING_MARGIN_COLLATERAL_RELEASE",
                    public_metadata={
                        "position_type": position["position_type"],
                        "market": market["symbol"],
                        "trial_collateral_points": collateral_trial,
                        "chain_collateral_points": collateral_chain,
                    },
                    actor=actor,
                )["ledger_uuid"])
            if delta > 0:
                if collateral_trial:
                    self._trial_delta(conn, user_id, available_delta=collateral_trial, deployed_delta=-collateral_trial)
                ledger_uuids.append(self._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="credit",
                    amount=delta,
                    action_type="trading_margin_profit",
                    reference_type="trading_margin_position",
                    reference_id=position["position_uuid"],
                    idempotency_key=f"trading:margin:profit:{position['position_uuid']}",
                    reason="TRADING_MARGIN_PROFIT",
                    public_metadata={"position_type": position["position_type"], "market": market["symbol"], "exit_price_points": price},
                    actor=actor,
                )["ledger_uuid"])
            elif delta < 0:
                remaining_loss = abs(delta)
                if collateral_trial:
                    trial_loss = min(collateral_trial, remaining_loss)
                    trial_return = collateral_trial - trial_loss
                    self._trial_delta(conn, user_id, available_delta=trial_return, deployed_delta=-collateral_trial)
                    remaining_loss -= trial_loss
                wallet = self.points_service.ensure_wallet(conn, user_id)
                wallet_balance = int(wallet["soft_balance"] or 0) + int(wallet["hard_balance"] or 0)
                debit_amount = min(remaining_loss, wallet_balance)
                bad_debt = remaining_loss - debit_amount
                if debit_amount:
                    ledger_uuids.append(self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="debit",
                        amount=debit_amount,
                        action_type="trading_margin_loss",
                        reference_type="trading_margin_position",
                        reference_id=position["position_uuid"],
                        idempotency_key=f"trading:margin:loss:{position['position_uuid']}",
                        reason="TRADING_MARGIN_LIQUIDATION_LOSS" if force_liquidation else "TRADING_MARGIN_LOSS",
                        public_metadata={"position_type": position["position_type"], "market": market["symbol"], "exit_price_points": price, "bad_debt_points": bad_debt},
                        actor=actor,
                    )["ledger_uuid"])
                if bad_debt:
                    self._audit_event(
                        conn,
                        "TRADING_MARGIN_BAD_DEBT",
                        "margin position closed with bad debt",
                        actor=actor,
                        target_user_id=user_id,
                        market_symbol=market["symbol"],
                        severity="critical",
                        metadata={"position_uuid": position["position_uuid"], "bad_debt_points": bad_debt, "risk": risk},
                    )
            elif collateral_trial:
                self._trial_delta(conn, user_id, available_delta=collateral_trial, deployed_delta=-collateral_trial)
            if close_fee:
                self._reserve_delta(conn, delta=close_fee, event_type="margin_fee_retained", reason="TRADING_MARGIN_CLOSE_FEE", actor=actor)
            if interest:
                self._reserve_delta(conn, delta=interest, event_type="margin_interest_retained", reason="TRADING_MARGIN_INTEREST", actor=actor)
            now = _now()
            next_status = "liquidated" if force_liquidation else "closed"
            conn.execute(
                """
                UPDATE trading_margin_positions
                SET close_fee_points=?, interest_points=?, status=?, closed_at=?, updated_at=?
                WHERE id=?
                """,
                (close_fee, interest, next_status, now, now, position["id"]),
            )
            event_type = "TRADING_MARGIN_POSITION_LIQUIDATED" if force_liquidation else "TRADING_MARGIN_POSITION_CLOSED"
            self._audit_event(
                conn,
                event_type,
                "margin borrow position liquidated" if force_liquidation else "margin borrow position closed",
                actor=actor,
                target_user_id=user_id,
                market_symbol=market["symbol"],
                severity="warning" if force_liquidation else "info",
                metadata={
                    "position_id": position["id"],
                    "position_uuid": position["position_uuid"],
                    "position_type": position["position_type"],
                    "entry_price_points": int(position["entry_price_points"]),
                    "exit_price_points": price,
                    "price_source": price_source,
                    "delta_points": delta,
                    "interest_points": interest,
                    "close_fee_points": close_fee,
                    "risk": risk,
                    "ledger_uuids": ledger_uuids,
                },
            )
            if force_liquidation:
                self._notify_margin_liquidated(conn, user_id=user_id, position=position, risk=risk)
            conn.commit()
            row = conn.execute("SELECT * FROM trading_margin_positions WHERE id=?", (position["id"],)).fetchone()
            return {
                "ok": True,
                "position": self._margin_position_payload(row),
                "delta_points": delta,
                "interest_points": interest,
                "close_fee_points": close_fee,
                "funding": self._funding_payload(conn, user_id),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def scan_margin_liquidations(self, *, actor=None, limit=100):
        limit = _to_int(limit or 100, name="limit", minimum=1, maximum=500)
        actor = actor or {"username": "system", "role": "system"}
        conn = self.get_db()
        candidates = []
        errors = []
        scanned = 0
        try:
            self.ensure_schema(conn)
            settings = self._settings_payload(conn)
            if not settings.get("borrowing_enabled"):
                return {"ok": True, "enabled": False, "reason": "borrowing_disabled", "scanned": 0, "candidates": [], "liquidated": [], "errors": []}
            if not settings.get("margin_liquidation_enabled"):
                return {"ok": True, "enabled": False, "reason": "liquidation_disabled", "scanned": 0, "candidates": [], "liquidated": [], "errors": []}
            state = self._state(conn)
            if state.get("safe_mode"):
                return {"ok": True, "enabled": False, "reason": "trading_safe_mode", "scanned": 0, "candidates": [], "liquidated": [], "errors": []}
            rows = conn.execute(
                "SELECT * FROM trading_margin_positions WHERE status='open' ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            scanned = len(rows)
            for position in rows:
                try:
                    risk = self._margin_risk_payload(conn, position)
                    if risk.get("liquidation_required"):
                        candidates.append({
                            "position_uuid": position["position_uuid"],
                            "user_id": int(position["user_id"]),
                            "market_symbol": position["market_symbol"],
                            "position_type": position["position_type"],
                            "risk": risk,
                        })
                except Exception as exc:
                    errors.append({
                        "position_uuid": position["position_uuid"],
                        "user_id": int(position["user_id"]),
                        "error": str(exc),
                    })
        finally:
            conn.close()

        liquidated = []
        for candidate in candidates:
            try:
                result = self.close_margin_position(
                    actor=actor,
                    position_uuid=candidate["position_uuid"],
                    force_liquidation=True,
                )
                liquidated.append({
                    "position_uuid": candidate["position_uuid"],
                    "user_id": candidate["user_id"],
                    "market_symbol": candidate["market_symbol"],
                    "delta_points": int(result.get("delta_points") or 0),
                    "interest_points": int(result.get("interest_points") or 0),
                    "close_fee_points": int(result.get("close_fee_points") or 0),
                    "risk": candidate["risk"],
                })
            except Exception as exc:
                errors.append({
                    "position_uuid": candidate["position_uuid"],
                    "user_id": candidate["user_id"],
                    "error": str(exc),
                })
        return {
            "ok": not errors,
            "enabled": True,
            "scanned": scanned,
            "candidates": candidates,
            "liquidated": liquidated,
            "errors": errors,
        }

    def update_market(self, *, actor, symbol, manual_price_points=None, max_price_jump_bps=None, fee_bps=None, min_order_points=None, max_order_points=None, enabled=None, confirm_jump=False):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
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

    def open_root_contract_position(self, *, actor, market_symbol, side, quantity, leverage, margin_points):
        if not self._is_root_actor(actor):
            raise ValueError("only root can use contract trading")
        user_id = self._actor_id(actor)
        side = str(side or "").strip().lower()
        if side not in {"long", "short"}:
            raise ValueError("contract side must be long or short")
        quantity_units = quantity_to_units(quantity)
        leverage = _to_int(leverage, name="leverage", minimum=1, maximum=20)
        margin_points = _to_int(margin_points, name="margin_points", minimum=1, maximum=ROOT_SIMULATED_INITIAL_POINTS)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            market = self._market(conn, market_symbol)
            price, price_source = self._current_market_price_points(conn, market)
            exposure = notional_points(quantity_units, price)
            if exposure > margin_points * leverage:
                raise ValueError("contract exposure exceeds margin and leverage")
            self._sim_delta(conn, user_id, balance_delta=-margin_points)
            position_uuid = str(uuid.uuid4())
            now = _now()
            liquidation_price = None
            if side == "long":
                liquidation_price = max(1, price - int(margin_points * ASSET_SCALE / quantity_units))
            else:
                liquidation_price = price + int(margin_points * ASSET_SCALE / quantity_units)
            cur = conn.execute(
                """
                INSERT INTO trading_futures_positions (
                    position_uuid, user_id, market_symbol, side, quantity_units,
                    entry_price_points, leverage, margin_points, liquidation_price_points,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (
                    position_uuid,
                    user_id,
                    market["symbol"],
                    side,
                    quantity_units,
                    price,
                    leverage,
                    margin_points,
                    liquidation_price,
                    now,
                    now,
                ),
            )
            self._audit_event(
                conn,
                "TRADING_ROOT_CONTRACT_OPENED",
                "root opened simulated contract position",
                actor=actor,
                market_symbol=market["symbol"],
                severity="warning",
                metadata={"position_id": cur.lastrowid, "side": side, "quantity": units_to_quantity(quantity_units), "entry_price_points": price, "price_source": price_source, "leverage": leverage, "margin_points": margin_points},
            )
            conn.commit()
            row = conn.execute("SELECT * FROM trading_futures_positions WHERE id=?", (cur.lastrowid,)).fetchone()
            return {"ok": True, "position": self._futures_position_payload(row), "funding": self._funding_payload(conn, user_id)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close_root_contract_position(self, *, actor, position_uuid):
        if not self._is_root_actor(actor):
            raise ValueError("only root can use contract trading")
        user_id = self._actor_id(actor)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            position = conn.execute(
                "SELECT * FROM trading_futures_positions WHERE position_uuid=?",
                (str(position_uuid or ""),),
            ).fetchone()
            if not position:
                raise ValueError("contract position not found")
            if int(position["user_id"]) != int(user_id):
                raise ValueError("cannot close another user's contract position")
            if position["status"] != "open":
                raise ValueError("contract position is not open")
            market = self._market(conn, position["market_symbol"])
            current_price, price_source = self._current_market_price_points(conn, market)
            entry_price = int(position["entry_price_points"])
            quantity_units = int(position["quantity_units"])
            price_delta = notional_points(quantity_units, abs(current_price - entry_price))
            pnl = price_delta if current_price >= entry_price else -price_delta
            if position["side"] == "short":
                pnl = -pnl
            margin = int(position["margin_points"])
            credit = max(0, margin + pnl)
            self._sim_delta(conn, user_id, balance_delta=credit)
            now = _now()
            conn.execute(
                "UPDATE trading_futures_positions SET status='closed', updated_at=? WHERE id=?",
                (now, position["id"]),
            )
            self._audit_event(
                conn,
                "TRADING_ROOT_CONTRACT_CLOSED",
                "root closed simulated contract position",
                actor=actor,
                market_symbol=position["market_symbol"],
                severity="warning",
                metadata={"position_id": position["id"], "position_uuid": position["position_uuid"], "entry_price_points": entry_price, "exit_price_points": current_price, "price_source": price_source, "pnl_points": pnl, "credited_points": credit},
            )
            conn.commit()
            row = conn.execute("SELECT * FROM trading_futures_positions WHERE id=?", (position["id"],)).fetchone()
            return {"ok": True, "position": self._futures_position_payload(row), "pnl_points": pnl, "credited_points": credit, "funding": self._funding_payload(conn, user_id)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reset_root_simulated_balance(self, *, actor):
        if not self._is_root_actor(actor):
            raise ValueError("only root can reset simulated trading points")
        user_id = self._actor_id(actor)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._root_sim_account(conn, user_id, actor=actor)
            now = _now()
            deleted_counts = {
                "orders": int(conn.execute("SELECT COUNT(*) FROM trading_orders WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
                "fills": int(conn.execute("SELECT COUNT(*) FROM trading_fills WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
                "spot_positions": int(conn.execute("SELECT COUNT(*) FROM trading_spot_positions WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
                "futures_positions": int(conn.execute("SELECT COUNT(*) FROM trading_futures_positions WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
                "margin_positions": int(conn.execute("SELECT COUNT(*) FROM trading_margin_positions WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
                "pending_profit": int(conn.execute("SELECT COUNT(*) FROM trading_pending_profit WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
                "spot_realized_pnl": int(conn.execute("SELECT COUNT(*) FROM trading_spot_realized_pnl WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            }
            conn.execute("DELETE FROM trading_spot_realized_pnl WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_fills WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_orders WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_spot_positions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_futures_positions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_margin_positions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_pending_profit WHERE user_id=?", (user_id,))
            conn.execute(
                """
                UPDATE trading_sim_accounts
                SET balance_points=?, locked_points=0, initial_balance_points=?, updated_at=?, reset_at=?, reset_by=?
                WHERE user_id=?
                """,
                (ROOT_SIMULATED_INITIAL_POINTS, ROOT_SIMULATED_INITIAL_POINTS, now, now, user_id, user_id),
            )
            self._audit_event(
                conn,
                "TRADING_ROOT_SIM_BALANCE_RESET",
                "root reset simulated trading state",
                actor=actor,
                severity="warning",
                metadata={"balance_points": ROOT_SIMULATED_INITIAL_POINTS, "deleted": deleted_counts},
            )
            conn.commit()
            account = self._root_sim_account(conn, user_id)
            return {
                "ok": True,
                "funding": {
                    "mode": "root_simulated",
                    "available_points": int(account["balance_points"] or 0),
                    "locked_points": int(account["locked_points"] or 0),
                    "initial_balance_points": int(account["initial_balance_points"] or ROOT_SIMULATED_INITIAL_POINTS),
                },
                "deleted": deleted_counts,
                "cancelled_open_orders": deleted_counts["orders"],
                "closed_open_contracts": deleted_counts["futures_positions"],
            }
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
        fills = conn.execute(
            """
            SELECT f.*, o.order_uuid, o.chain_frozen_points
            FROM trading_fills f
            JOIN trading_orders o ON o.id=f.order_id
            ORDER BY f.id ASC
            """
        ).fetchall()
        ledger_by_uuid = {
            row["ledger_uuid"]: row
            for row in conn.execute(
                """
                SELECT *
                FROM points_ledger
                WHERE reference_type='trading_order'
                  AND action_type IN (
                    'trading_unfreeze',
                    'trading_spot_buy',
                    'trading_spot_sell',
                    'trading_fee'
                  )
                """
            ).fetchall()
        }
        for fill in fills:
            funding_mode = fill["funding_mode"] if "funding_mode" in fill.keys() else "points_chain"
            if funding_mode == "root_simulated":
                continue
            ledger_uuids = _json_loads(fill["points_ledger_uuids_json"], [])
            if not isinstance(ledger_uuids, list) or not ledger_uuids:
                if funding_mode != "trial_mixed":
                    errors.append({
                        "type": "fill_ledger_refs_missing",
                        "fill_id": fill["id"],
                        "fill_uuid": fill["fill_uuid"],
                        "order_id": fill["order_id"],
                    })
                continue
            ledgers = []
            for ledger_uuid in ledger_uuids:
                ledger = ledger_by_uuid.get(str(ledger_uuid or ""))
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
                required = {"trading_unfreeze", "trading_spot_buy"} if int(fill["chain_frozen_points"] or 0) > 0 else set()
            else:
                required = {"trading_spot_sell"} if ledgers else set()
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
            funding_mode = order["funding_mode"] if "funding_mode" in order.keys() else "points_chain"
            if funding_mode == "root_simulated":
                continue
            if order["side"] == "buy":
                expected_total = int(order["trial_frozen_points"] or 0) + int(order["chain_frozen_points"] or 0)
                actual_total = int(order["frozen_points"] or 0) if order["status"] in OPEN_ORDER_STATUSES else 0
                if order["status"] in OPEN_ORDER_STATUSES and expected_total != actual_total:
                    errors.append({
                        "type": "open_order_total_frozen_points_mismatch",
                        "order_id": order["id"],
                        "order_uuid": order["order_uuid"],
                        "status": order["status"],
                        "expected_frozen_points": expected_total,
                        "actual_frozen_points": actual_total,
                    })
            expected = (
                int(order["chain_frozen_points"] or 0)
                if order["side"] == "buy" and order["status"] in OPEN_ORDER_STATUSES and "chain_frozen_points" in order.keys()
                else (int(order["frozen_points"] or 0) if order["side"] == "buy" and order["status"] in OPEN_ORDER_STATUSES else 0)
            )
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
            WHERE event_type = 'fee_retained'
            """
        ).fetchone()[0] or 0)
        if fill_delta != trade_event_delta:
            errors.append({
                "type": "reserve_trade_event_replay_mismatch",
                "expected_trade_delta_points": fill_delta,
                "actual_trade_event_delta_points": trade_event_delta,
            })
        margin_delta = int(conn.execute(
            """
            SELECT COALESCE(SUM(delta_points), 0)
            FROM trading_reserve_pool_events
            WHERE event_type IN ('margin_fee_retained', 'margin_interest_retained')
            """
        ).fetchone()[0] or 0)
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
        allocation_ledgers = {
            row["ledger_uuid"]: row
            for row in conn.execute(
                "SELECT * FROM points_ledger WHERE action_type='trading_reserve_allocation' ORDER BY id ASC"
            ).fetchall()
        }
        for event in conn.execute("SELECT * FROM trading_reserve_pool_events WHERE event_type='root_reserve_allocation' ORDER BY id ASC").fetchall():
            ledger = allocation_ledgers.get(str(event["points_ledger_uuid"] or ""))
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
        expected_balance = fill_delta + margin_delta + allocation_delta
        reserve = self._reserve(conn)
        actual_balance = int(reserve["balance_points"] or 0)
        if expected_balance != actual_balance:
            errors.append({
                "type": "reserve_pool_replay_mismatch",
                "expected_balance_points": expected_balance,
                "actual_balance_points": actual_balance,
                "fill_delta_points": fill_delta,
                "margin_delta_points": margin_delta,
                "allocation_delta_points": allocation_delta,
            })

    def _verify_sim_accounts(self, conn, errors):
        expected_locked = {}
        for order in conn.execute(
            """
            SELECT user_id, frozen_points
            FROM trading_orders
            WHERE funding_mode='root_simulated'
              AND side='buy'
              AND status IN ('open', 'partially_filled')
            """
        ).fetchall():
            user_id = int(order["user_id"])
            expected_locked[user_id] = expected_locked.get(user_id, 0) + int(order["frozen_points"] or 0)
        for account in conn.execute("SELECT * FROM trading_sim_accounts ORDER BY user_id").fetchall():
            user_id = int(account["user_id"])
            expected = expected_locked.pop(user_id, 0)
            actual = int(account["locked_points"] or 0)
            if expected != actual:
                errors.append({
                    "type": "root_simulated_locked_points_mismatch",
                    "user_id": user_id,
                    "expected_locked_points": expected,
                    "actual_locked_points": actual,
                })
        for user_id, expected in expected_locked.items():
            if expected:
                errors.append({
                    "type": "root_simulated_account_missing",
                    "user_id": user_id,
                    "expected_locked_points": expected,
                })

    def _verify_margin_position_locks(self, conn, errors):
        ledger_net = {}
        for row in conn.execute(
            """
            SELECT reference_id, direction, amount
            FROM points_ledger
            WHERE reference_type='trading_margin_position'
              AND action_type IN ('trading_margin_collateral_freeze', 'trading_margin_collateral_unfreeze')
            ORDER BY id ASC
            """
        ).fetchall():
            reference_id = row["reference_id"]
            if not reference_id:
                continue
            ledger_net.setdefault(reference_id, 0)
            if row["direction"] == "freeze":
                ledger_net[reference_id] += int(row["amount"] or 0)
            elif row["direction"] == "unfreeze":
                ledger_net[reference_id] -= int(row["amount"] or 0)
        for position in conn.execute("SELECT * FROM trading_margin_positions ORDER BY id ASC").fetchall():
            position_uuid = position["position_uuid"]
            expected = int(position["collateral_points"] or 0) if position["status"] == "open" else 0
            actual = ledger_net.pop(position_uuid, 0)
            if expected != actual:
                errors.append({
                    "type": "margin_collateral_lock_mismatch",
                    "position_id": position["id"],
                    "position_uuid": position_uuid,
                    "status": position["status"],
                    "expected_frozen_points": expected,
                    "actual_frozen_points": actual,
                })
        for position_uuid, actual in ledger_net.items():
            if actual:
                errors.append({
                    "type": "margin_collateral_orphan_lock",
                    "position_uuid": position_uuid,
                    "actual_frozen_points": actual,
                })

    def _verify_spot_realized_pnl(self, conn, errors):
        seen_fills = set()
        rows = conn.execute(
            """
            SELECT p.*, f.side, f.quantity_units AS fill_quantity_units,
                   f.price_points, f.notional_points, f.fee_points AS fill_fee_points
            FROM trading_spot_realized_pnl p
            LEFT JOIN trading_fills f ON f.id=p.fill_id
            ORDER BY p.id ASC
            """
        ).fetchall()
        for row in rows:
            fill_id = row["fill_id"]
            if fill_id in seen_fills:
                errors.append({"type": "spot_realized_pnl_duplicate_fill", "fill_id": fill_id, "pnl_id": row["id"]})
            seen_fills.add(fill_id)
            if row["side"] != "sell":
                errors.append({"type": "spot_realized_pnl_fill_not_sell", "fill_id": fill_id, "pnl_id": row["id"], "side": row["side"]})
                continue
            if int(row["quantity_units"] or 0) != int(row["fill_quantity_units"] or 0):
                errors.append({"type": "spot_realized_pnl_quantity_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
            if int(row["sell_price_points"] or 0) != int(row["price_points"] or 0):
                errors.append({"type": "spot_realized_pnl_price_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
            if int(row["gross_proceeds_points"] or 0) != int(row["notional_points"] or 0):
                errors.append({"type": "spot_realized_pnl_proceeds_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
            if int(row["sell_fee_points"] or 0) != int(row["fill_fee_points"] or 0):
                errors.append({"type": "spot_realized_pnl_sell_fee_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
            expected = (
                int(row["gross_proceeds_points"] or 0)
                - int(row["sell_fee_points"] or 0)
                - int(row["gross_cost_points"] or 0)
                - int(row["buy_fee_estimate_points"] or 0)
            )
            if int(row["net_pnl_points"] or 0) != expected:
                errors.append({
                    "type": "spot_realized_pnl_replay_mismatch",
                    "fill_id": fill_id,
                    "pnl_id": row["id"],
                    "expected_net_pnl_points": expected,
                    "actual_net_pnl_points": int(row["net_pnl_points"] or 0),
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
        self._verify_sim_accounts(conn, errors)
        self._verify_margin_position_locks(conn, errors)
        self._verify_spot_realized_pnl(conn, errors)
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
                "settings": self._settings_payload(conn),
                "reserve_pool": dict(reserve),
                "markets": markets,
                "reserve_events": reserve_events,
                "audit_events": audit_events,
                "verification": self._verify_state_on_conn(conn, enter_safe_mode=False),
            }
        finally:
            conn.close()
