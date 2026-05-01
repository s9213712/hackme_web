import hashlib
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
MARGIN_LONG_FINANCING_RATE_PERCENT = 90.0
SHORT_COLLATERAL_RATE_PERCENT = 60.0
SUPPORTED_EXECUTION_MODES = {"house_counterparty", "pvp_matching", "hybrid_liquidity"}
OPEN_ORDER_STATUSES = {"open", "partially_filled"}
TRADING_BOT_TRIGGER_TYPES = {"always", "price_above", "price_below"}
TRADING_BOT_TYPES = {"conditional", "dca"}
MAX_BACKTEST_CANDLES = 5000
WORKFLOW_CONDITION_TYPES = {
    "price_below",
    "price_above",
    "rsi_above",
    "rsi_below",
    "kd_above",
    "kd_below",
    "ma_position",
    "bb_position",
    "has_position",
    "change_percent_up",
    "change_percent_down",
    "take_profit_percent",
    "stop_loss_percent",
}
WORKFLOW_ACTION_TYPES = {"buy_percent", "buy_amount", "sell_percent", "close_all", "hold"}
WORKFLOW_NODE_TYPES = {"start", "condition", "logic", "action", "control"}
WORKFLOW_PORTS = {"in", "out", "true", "false", "then", "wait"}
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
OKX_TICKER_URL = "https://www.okx.com/api/v5/market/ticker"
COINBASE_TICKER_URL_TEMPLATE = "https://api.exchange.coinbase.com/products/{product_id}/ticker"
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
GEMINI_TICKER_URL_TEMPLATE = "https://api.gemini.com/v2/ticker/{symbol}"
BITSTAMP_TICKER_URL_TEMPLATE = "https://www.bitstamp.net/api/v2/ticker/{pair}/"
COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
LIVE_PRICE_SOURCE_NAMES = {
    "binance_public_api",
    "okx_public_api",
    "coinbase_exchange",
    "kraken_public_api",
    "gemini_public_api",
    "bitstamp_public_api",
    "coingecko_simple_price",
    "test_live_price_provider",
}
LIVE_PRICE_MARKETS = {
    "BTC/POINTS": "BTCUSDT",
    "BTC/USDT": "BTCUSDT",
    "ETH/POINTS": "ETHUSDT",
    "ETH/USDT": "ETHUSDT",
}
COINBASE_PRICE_PRODUCTS = {
    "BTC/POINTS": "BTC-USD",
    "BTC/USDT": "BTC-USD",
    "ETH/POINTS": "ETH-USD",
    "ETH/USDT": "ETH-USD",
}
OKX_PRICE_INSTRUMENTS = {
    "BTC/POINTS": "BTC-USDT",
    "BTC/USDT": "BTC-USDT",
    "ETH/POINTS": "ETH-USDT",
    "ETH/USDT": "ETH-USDT",
}
KRAKEN_PRICE_PAIRS = {
    "BTC/POINTS": "XBTUSD",
    "BTC/USDT": "XBTUSD",
    "ETH/POINTS": "ETHUSD",
    "ETH/USDT": "ETHUSD",
}
GEMINI_PRICE_SYMBOLS = {
    "BTC/POINTS": "btcusd",
    "BTC/USDT": "btcusd",
    "ETH/POINTS": "ethusd",
    "ETH/USDT": "ethusd",
}
BITSTAMP_PRICE_PAIRS = {
    "BTC/POINTS": "btcusd",
    "BTC/USDT": "btcusd",
    "ETH/POINTS": "ethusd",
    "ETH/USDT": "ethusd",
}
COINGECKO_PRICE_IDS = {
    "BTC/POINTS": "bitcoin",
    "BTC/USDT": "bitcoin",
    "ETH/POINTS": "ethereum",
    "ETH/USDT": "ethereum",
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


def _client_idempotency_key(value, *, prefix):
    raw = str(value or "").strip()
    if not raw:
        return ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _to_int(value, *, name, minimum=0, maximum=10**12):
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} out of range")
    return number


def _to_float(value, *, name, minimum=0.0, maximum=10**12):
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a number") from exc
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


def fee_points(notional, fee_rate_percent):
    return int(math.ceil((int(notional) * float(fee_rate_percent or 0)) / 100))


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
            max_price_jump_percent REAL NOT NULL DEFAULT 10,
            min_order_points INTEGER NOT NULL DEFAULT 1,
            max_order_points INTEGER NOT NULL DEFAULT 100000,
            fee_rate_percent REAL NOT NULL DEFAULT 0.3,
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
        CREATE TABLE IF NOT EXISTS trading_operation_idempotency (
            idempotency_key TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            reference_uuid TEXT,
            response_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
            interest_percent_daily REAL NOT NULL DEFAULT 0,
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            bot_type TEXT NOT NULL DEFAULT 'conditional',
            name TEXT NOT NULL,
            market_symbol TEXT NOT NULL REFERENCES trading_markets(symbol),
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            quantity_text TEXT NOT NULL,
            limit_price_points INTEGER,
            trigger_type TEXT NOT NULL DEFAULT 'price_below',
            trigger_price_points INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            max_runs INTEGER NOT NULL DEFAULT 1,
            run_count INTEGER NOT NULL DEFAULT 0,
            cooldown_seconds INTEGER NOT NULL DEFAULT 300,
            interval_hours INTEGER NOT NULL DEFAULT 24,
            budget_points INTEGER NOT NULL DEFAULT 0,
            workflow_json TEXT,
            execution_state_json TEXT,
            last_run_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (bot_type IN ('conditional', 'dca')),
            CHECK (side IN ('buy', 'sell')),
            CHECK (order_type IN ('market', 'limit')),
            CHECK (trigger_type IN ('always', 'price_above', 'price_below')),
            CHECK (max_runs >= 1),
            CHECK (run_count >= 0),
            CHECK (cooldown_seconds >= 0),
            CHECK (interval_hours >= 1),
            CHECK (budget_points >= 0)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_bot_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uuid TEXT NOT NULL UNIQUE,
            bot_id INTEGER NOT NULL REFERENCES trading_bots(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_price_points INTEGER,
            observed_price_points INTEGER,
            status TEXT NOT NULL,
            order_uuid TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            CHECK (status IN ('triggered', 'skipped', 'failed'))
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
    legacy_unit = "b" + "ps"
    market_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_markets)").fetchall()}
    legacy_fee_col = f"fee_{legacy_unit}"
    legacy_jump_col = f"max_price_jump_{legacy_unit}"
    if "fee_rate_percent" not in market_cols:
        conn.execute("ALTER TABLE trading_markets ADD COLUMN fee_rate_percent REAL NOT NULL DEFAULT 0.3")
        if legacy_fee_col in market_cols:
            conn.execute(f"UPDATE trading_markets SET fee_rate_percent=CAST({legacy_fee_col} AS REAL) / 100.0")
    if "max_price_jump_percent" not in market_cols:
        conn.execute("ALTER TABLE trading_markets ADD COLUMN max_price_jump_percent REAL NOT NULL DEFAULT 10")
        if legacy_jump_col in market_cols:
            conn.execute(f"UPDATE trading_markets SET max_price_jump_percent=CAST({legacy_jump_col} AS REAL) / 100.0")
    margin_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_margin_positions)").fetchall()}
    legacy_interest_col = f"interest_{legacy_unit}_daily"
    if "interest_percent_daily" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN interest_percent_daily REAL NOT NULL DEFAULT 0")
        if legacy_interest_col in margin_cols:
            conn.execute(f"UPDATE trading_margin_positions SET interest_percent_daily=CAST({legacy_interest_col} AS REAL) / 100.0")
    defaults = [
        ("trading.enabled", "true"),
        ("trading.futures_enabled", "false"),
        ("trading.pvp_matching_enabled", "false"),
        ("trading.borrowing_enabled", "true"),
        ("trading.borrow_interest_percent_daily", "0.1"),
        ("trading.margin_long_financing_percent", str(MARGIN_LONG_FINANCING_RATE_PERCENT)),
        ("trading.short_collateral_percent", str(SHORT_COLLATERAL_RATE_PERCENT)),
        ("trading.margin_liquidation_enabled", "true"),
        ("trading.margin_maintenance_percent", "15"),
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
    bot_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_bots)").fetchall()}
    if "bot_type" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN bot_type TEXT NOT NULL DEFAULT 'conditional'")
    if "interval_hours" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN interval_hours INTEGER NOT NULL DEFAULT 24")
    if "budget_points" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN budget_points INTEGER NOT NULL DEFAULT 0")
    if "workflow_json" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN workflow_json TEXT")
    if "execution_state_json" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN execution_state_json TEXT")


class TradingEngineService:
    def __init__(self, *, get_db, points_service, audit=None, live_price_provider=None, historical_candles_provider=None):
        self.get_db = get_db
        self.points_service = points_service
        self.audit = audit or (lambda *args, **kwargs: None)
        self.live_price_provider = live_price_provider
        self.historical_candles_provider = historical_candles_provider

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
        try:
            points_state = self.points_service._safe_mode_status(conn)
        except Exception:
            points_state = self.points_service.safe_mode_status()
        if points_state.get("safe_mode"):
            reason = points_state.get("reason") or "points chain verification failed"
            raise ValueError(f"PointsChain safe mode active: {reason}; trading is paused")
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

    def _bot_payload(self, row):
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["can_run"] = bool(item["enabled"]) and int(item["run_count"] or 0) < int(item["max_runs"] or 1)
        item["display_symbol"] = str(item["market_symbol"] or "").replace("/POINTS", "/USDT")
        item["bot_type_label"] = "定投機器人" if item.get("bot_type") == "dca" else "條件機器人"
        item["workflow"] = _json_loads(item.get("workflow_json"), None)
        item["execution_state"] = _json_loads(item.get("execution_state_json"), {}) if "execution_state_json" in row.keys() else {}
        return item

    def _bot_run_payload(self, row):
        return dict(row)

    def _market_payload(self, row):
        item = dict(row)
        legacy_unit = "b" + "ps"
        item.pop(f"fee_{legacy_unit}", None)
        item.pop(f"max_price_jump_{legacy_unit}", None)
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
            "borrow_interest_percent_daily": _to_float(raw.get("trading.borrow_interest_percent_daily", "0.1"), name="borrow_interest_percent_daily", minimum=0, maximum=100),
            "margin_long_financing_percent": _to_float(raw.get("trading.margin_long_financing_percent", str(MARGIN_LONG_FINANCING_RATE_PERCENT)), name="margin_long_financing_percent", minimum=0, maximum=100),
            "short_collateral_percent": _to_float(raw.get("trading.short_collateral_percent", str(SHORT_COLLATERAL_RATE_PERCENT)), name="short_collateral_percent", minimum=0, maximum=100),
            "margin_liquidation_enabled": str(raw.get("trading.margin_liquidation_enabled", "true")).lower() in {"true", "1", "yes"},
            "margin_maintenance_percent": _to_float(raw.get("trading.margin_maintenance_percent", "15"), name="margin_maintenance_percent", minimum=0, maximum=100),
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
            if "borrow_interest_percent_daily" in settings:
                value = str(_to_float(settings.get("borrow_interest_percent_daily"), name="borrow_interest_percent_daily", minimum=0, maximum=100))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_interest_percent_daily", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.borrow_interest_percent_daily"] = value
            for input_key, storage_key in (
                ("margin_long_financing_percent", "trading.margin_long_financing_percent"),
                ("short_collateral_percent", "trading.short_collateral_percent"),
            ):
                if input_key in settings:
                    value = str(_to_float(settings.get(input_key), name=input_key, minimum=0, maximum=100))
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
            if "margin_maintenance_percent" in settings:
                value = str(_to_float(settings.get("margin_maintenance_percent"), name="margin_maintenance_percent", minimum=0, maximum=100))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.margin_maintenance_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.margin_maintenance_percent"] = value
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
                    ("fee_rate_percent", 50.0),
                    ("min_order_points", 10**9),
                    ("max_order_points", 10**12),
                ):
                    if key in row:
                        if key == "fee_rate_percent":
                            updates[key] = _to_float(row.get(key), name=key, minimum=0, maximum=max_value)
                        else:
                            updates[key] = _to_int(row.get(key), name=key, minimum=0 if key != "max_order_points" else 1, maximum=max_value)
                if "enabled" in row:
                    updates["enabled"] = 1 if bool(row.get("enabled")) else 0
                for flag_key in ("spot_enabled", "futures_enabled", "pvp_matching_enabled"):
                    if flag_key in row:
                        updates[flag_key] = 1 if bool(row.get(flag_key)) else 0
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

    def _fetch_json_url(self, url, *, timeout=5, user_agent="hackme_web/1.0 trading-price"):
        req = Request(url, headers={"User-Agent": user_agent})
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _price_points_from_float(self, price, *, source):
        try:
            price_points = int(round(float(price) * USDT_TO_POINTS_RATE))
        except Exception as exc:
            raise ValueError(f"{source} price format is invalid") from exc
        if price_points <= 0:
            raise ValueError(f"{source} price is invalid")
        return price_points

    def _fetch_binance_price_points(self, market_symbol):
        symbol = LIVE_PRICE_MARKETS.get(str(market_symbol or "").strip().upper())
        if not symbol:
            raise ValueError("binance price is not supported for this market")
        payload = self._fetch_json_url(
            f"{BINANCE_TICKER_URL}?{urlencode({'symbol': symbol})}",
            timeout=5,
        )
        price = payload.get("price") if isinstance(payload, dict) else None
        return self._price_points_from_float(price, source="binance_public_api")

    def _fetch_okx_price_points(self, market_symbol):
        instrument = OKX_PRICE_INSTRUMENTS.get(str(market_symbol or "").strip().upper())
        if not instrument:
            raise ValueError("okx price is not supported for this market")
        payload = self._fetch_json_url(
            f"{OKX_TICKER_URL}?{urlencode({'instId': instrument})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-price okx",
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        ticker = data[0] if isinstance(data, list) and data else None
        price = ticker.get("last") if isinstance(ticker, dict) else None
        return self._price_points_from_float(price, source="okx_public_api")

    def _fetch_coinbase_price_points(self, market_symbol):
        product_id = COINBASE_PRICE_PRODUCTS.get(str(market_symbol or "").strip().upper())
        if not product_id:
            raise ValueError("coinbase price is not supported for this market")
        payload = self._fetch_json_url(
            COINBASE_TICKER_URL_TEMPLATE.format(product_id=product_id),
            timeout=5,
            user_agent="hackme_web/1.0 trading-price coinbase",
        )
        price = payload.get("price") if isinstance(payload, dict) else None
        return self._price_points_from_float(price, source="coinbase_exchange")

    def _fetch_kraken_price_points(self, market_symbol):
        pair = KRAKEN_PRICE_PAIRS.get(str(market_symbol or "").strip().upper())
        if not pair:
            raise ValueError("kraken price is not supported for this market")
        payload = self._fetch_json_url(
            f"{KRAKEN_TICKER_URL}?{urlencode({'pair': pair})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-price kraken",
        )
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(f"kraken ticker error: {payload.get('error') if isinstance(payload, dict) else 'invalid payload'}")
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        ticker = next(iter(result.values()), None)
        close = ticker.get("c", [None])[0] if isinstance(ticker, dict) else None
        return self._price_points_from_float(close, source="kraken_public_api")

    def _fetch_gemini_price_points(self, market_symbol):
        symbol = GEMINI_PRICE_SYMBOLS.get(str(market_symbol or "").strip().upper())
        if not symbol:
            raise ValueError("gemini price is not supported for this market")
        payload = self._fetch_json_url(
            GEMINI_TICKER_URL_TEMPLATE.format(symbol=symbol),
            timeout=5,
            user_agent="hackme_web/1.0 trading-price gemini",
        )
        price = payload.get("close") or payload.get("last") if isinstance(payload, dict) else None
        return self._price_points_from_float(price, source="gemini_public_api")

    def _fetch_bitstamp_price_points(self, market_symbol):
        pair = BITSTAMP_PRICE_PAIRS.get(str(market_symbol or "").strip().upper())
        if not pair:
            raise ValueError("bitstamp price is not supported for this market")
        payload = self._fetch_json_url(
            BITSTAMP_TICKER_URL_TEMPLATE.format(pair=pair),
            timeout=5,
            user_agent="hackme_web/1.0 trading-price bitstamp",
        )
        price = payload.get("last") if isinstance(payload, dict) else None
        return self._price_points_from_float(price, source="bitstamp_public_api")

    def _fetch_coingecko_price_points(self, market_symbol):
        coin_id = COINGECKO_PRICE_IDS.get(str(market_symbol or "").strip().upper())
        if not coin_id:
            raise ValueError("coingecko price is not supported for this market")
        payload = self._fetch_json_url(
            f"{COINGECKO_SIMPLE_PRICE_URL}?{urlencode({'ids': coin_id, 'vs_currencies': 'usd', 'include_last_updated_at': 'true'})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-price coingecko",
        )
        coin = payload.get(coin_id) if isinstance(payload, dict) else None
        price = coin.get("usd") if isinstance(coin, dict) else None
        return self._price_points_from_float(price, source="coingecko_simple_price")

    def _fetch_live_price_points(self, market_symbol):
        market_symbol = str(market_symbol or "").strip().upper()
        if not self._live_price_symbol(market_symbol):
            raise ValueError("live price is not supported for this market")
        if self.live_price_provider:
            price = self.live_price_provider(str(market_symbol or "").strip().upper())
            return self._price_points_from_float(price, source="test_live_price_provider"), "test_live_price_provider"
        errors = []
        providers = (
            ("binance_public_api", self._fetch_binance_price_points),
            ("okx_public_api", self._fetch_okx_price_points),
            ("coinbase_exchange", self._fetch_coinbase_price_points),
            ("kraken_public_api", self._fetch_kraken_price_points),
            ("gemini_public_api", self._fetch_gemini_price_points),
            ("bitstamp_public_api", self._fetch_bitstamp_price_points),
            ("coingecko_simple_price", self._fetch_coingecko_price_points),
        )
        for source, fetcher in providers:
            try:
                return fetcher(market_symbol), source
            except Exception as exc:
                errors.append(f"{source}: {str(exc)[:120]}")
        raise ValueError("; ".join(errors) or "all live price providers failed")

    def _fetch_indicator_candles(self, market_symbol, *, limit=240, interval="15m"):
        symbol = self._live_price_symbol(market_symbol)
        if not symbol:
            return []
        if self.historical_candles_provider:
            candles = self.historical_candles_provider(str(market_symbol or "").strip().upper(), interval, limit)
            return candles if isinstance(candles, list) else []
        query = urlencode({"symbol": symbol, "interval": interval, "limit": max(2, min(int(limit or 240), 1000))})
        req = Request(
            f"https://api.binance.com/api/v3/klines?{query}",
            headers={"User-Agent": "hackme_web/1.0 trading-bot-indicators"},
        )
        with urlopen(req, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        candles = []
        for item in payload if isinstance(payload, list) else []:
            try:
                candles.append({
                    "open_points": float(item[1]) * USDT_TO_POINTS_RATE,
                    "high_points": float(item[2]) * USDT_TO_POINTS_RATE,
                    "low_points": float(item[3]) * USDT_TO_POINTS_RATE,
                    "close_points": float(item[4]) * USDT_TO_POINTS_RATE,
                })
            except Exception:
                continue
        return candles

    def _workflow_live_context(self, conn, *, market, user_id, observed_price):
        position = self._position(conn, int(user_id), market["symbol"])
        context = {
            "price": observed_price,
            "has_position": int(position["quantity_units"] or 0) > int(position["locked_quantity_units"] or 0),
        }
        try:
            candles = self._fetch_indicator_candles(market["symbol"])
            if candles:
                latest = dict(candles[-1])
                latest["close_points"] = observed_price
                candles = [*candles[:-1], latest]
                context.update(self._workflow_indicator_context(candles, len(candles) - 1))
                context["price"] = observed_price
                context["has_position"] = int(position["quantity_units"] or 0) > int(position["locked_quantity_units"] or 0)
        except Exception as exc:
            self._audit_event(
                conn,
                "TRADING_BOT_INDICATOR_CONTEXT_UNAVAILABLE",
                "trading bot indicator context unavailable; price-only context used",
                target_user_id=int(user_id),
                market_symbol=market["symbol"],
                severity="warning",
                metadata={"error": str(exc)[:200]},
            )
        return context

    def _current_market_price_points(self, conn, market):
        symbol = market["symbol"]
        settings = self._settings_payload(conn)
        configured_source = settings.get("price_source") or "binance_public_api"
        if configured_source == "manual_root" or not self._live_price_symbol(symbol):
            return int(market["manual_price_points"]), str(market["price_source"] or "manual_root")
        old_price = int(market["manual_price_points"] or 0)
        old_source = str(market["price_source"] or "")
        try:
            price, live_source = self._fetch_live_price_points(symbol)
        except Exception as exc:
            max_stale = int(settings.get("max_price_staleness_seconds") or 0)
            try:
                updated_at = datetime.fromisoformat(str(market["updated_at"]))
                stale_seconds = int((datetime.now() - updated_at).total_seconds())
            except Exception:
                stale_seconds = max_stale + 1
            cached_source = old_source[:-7] if old_source.endswith("_cached") else old_source
            if old_price > 0 and max_stale > 0 and stale_seconds <= max_stale and cached_source in LIVE_PRICE_SOURCE_NAMES:
                self._audit_event(
                    conn,
                    "TRADING_PRICE_FALLBACK_USED",
                    "live trading price unavailable; using cached last-good price",
                    market_symbol=symbol,
                    severity="warning",
                    metadata={"error": str(exc), "cached_price_points": old_price, "stale_seconds": stale_seconds, "max_stale_seconds": max_stale},
                )
                return old_price, f"{cached_source}_cached"
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
        if old_price > 0 and old_source in LIVE_PRICE_SOURCE_NAMES and has_live_history:
            jump_percent = float(abs(price - old_price) * 100 / old_price) if old_price else 0.0
            allowed_percent = float(market["max_price_jump_percent"] or 0)
            if allowed_percent and jump_percent > allowed_percent:
                self._audit_event(
                    conn,
                    "TRADING_PRICE_CIRCUIT_BREAKER",
                    "live trading price jump exceeded market threshold",
                    market_symbol=symbol,
                    severity="critical",
                    metadata={"old_price_points": old_price, "new_price_points": price, "jump_percent": jump_percent, "allowed_percent": allowed_percent},
                )
                raise ValueError(f"live trading price jump {jump_percent:.2f}% exceeds max {allowed_percent:.2f}% for {symbol}")
        now = _now()
        conn.execute(
            "UPDATE trading_markets SET manual_price_points=?, price_source=?, updated_at=? WHERE symbol=?",
            (price, live_source, now, symbol),
        )
        return price, live_source

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

    def _cancel_trial_reclaim_sell_orders(self, conn, user_id, *, actor, reason):
        orders = conn.execute(
            """
            SELECT o.*
            FROM trading_orders o
            JOIN trading_trial_position_costs t
              ON t.user_id=o.user_id AND t.market_symbol=o.market_symbol
            WHERE o.user_id=?
              AND o.side='sell'
              AND o.status IN ('open', 'partially_filled')
              AND t.quantity_units > 0
            ORDER BY o.id ASC
            """,
            (int(user_id),),
        ).fetchall()
        for order in orders:
            remaining_units = max(0, int(order["quantity_units"] or 0) - int(order["filled_quantity_units"] or 0))
            if remaining_units:
                conn.execute(
                    """
                    UPDATE trading_spot_positions
                    SET quantity_units=quantity_units+?,
                        locked_quantity_units=MAX(locked_quantity_units-?, 0),
                        updated_at=?
                    WHERE user_id=? AND market_symbol=?
                    """,
                    (remaining_units, remaining_units, _now(), int(user_id), order["market_symbol"]),
                )
            conn.execute(
                """
                UPDATE trading_orders
                SET status='cancelled', reason=?, updated_at=?
                WHERE id=?
                """,
                (f"{reason}: trial credit reclaim unlocked sell order", _now(), order["id"]),
            )
            self._audit_event(
                conn,
                "TRADING_TRIAL_CREDIT_SELL_ORDER_CANCELLED",
                "open sell order cancelled so expired trial credit positions can be reclaimed",
                actor=actor,
                target_user_id=int(user_id),
                order_id=order["id"],
                market_symbol=order["market_symbol"],
                severity="warning",
                metadata={"reason": reason, "released_quantity_units": remaining_units},
            )

    def _release_trial_margin_collateral(self, conn, user_id, *, collateral_trial, available_delta_if_active=0):
        collateral_trial = int(collateral_trial or 0)
        if collateral_trial <= 0:
            return
        row = self._trial_credit_row(conn, user_id)
        if not row:
            return
        deployed_release = min(collateral_trial, int(row["deployed_points"] or 0))
        if deployed_release <= 0:
            return
        available_delta = int(available_delta_if_active or 0) if row["status"] == "active" else 0
        self._trial_delta(conn, user_id, available_delta=available_delta, deployed_delta=-deployed_release)

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
        self._cancel_trial_reclaim_sell_orders(conn, user_id, actor=actor, reason=reason)
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
        open_margin_trial = int(conn.execute(
            """
            SELECT COALESCE(SUM(collateral_trial_points), 0)
            FROM trading_margin_positions
            WHERE user_id=? AND status='open' AND collateral_trial_points > 0
            """,
            (int(user_id),),
        ).fetchone()[0] or 0)
        final_deployed = int(final["deployed_points"] or 0)
        open_margin_trial = min(open_margin_trial, final_deployed)
        lost_points = max(0, final_deployed - open_margin_trial)
        conn.execute(
            """
            UPDATE trading_trial_credits
            SET available_points=0, locked_points=0, deployed_points=?, status='expired',
                reclaimed_at=?, updated_at=?
            WHERE user_id=?
            """,
            (open_margin_trial, _now(), _now(), int(user_id)),
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
        fee_rate_percent = float((market or {}).get("fee_rate_percent") or 0)
        gross_cost = notional_points(quantity_units, avg_cost) if quantity_units and avg_cost else 0
        current_value = notional_points(quantity_units, current_price) if quantity_units and current_price else 0
        estimated_buy_fee = fee_points(gross_cost, fee_rate_percent) if gross_cost else 0
        estimated_exit_fee = fee_points(current_value, fee_rate_percent) if current_value else 0
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
            "interest_percent_daily": float(settings.get("borrow_interest_percent_daily") or 0),
        }

    def _assert_borrowing_enabled(self, conn):
        settings = self._borrowing_settings(conn)
        if not settings["enabled"]:
            raise ValueError("borrow trading is disabled")
        return settings

    def _minimum_margin_collateral_points(self, conn, *, position_type, notional):
        settings = self._settings_payload(conn)
        notional = int(notional or 0)
        if position_type == "margin_long":
            financing_percent = float(settings.get("margin_long_financing_percent") or MARGIN_LONG_FINANCING_RATE_PERCENT)
            return int(math.ceil(notional * max(0.0, 100.0 - financing_percent) / 100.0))
        short_percent = float(settings.get("short_collateral_percent") or SHORT_COLLATERAL_RATE_PERCENT)
        return int(math.ceil(notional * short_percent / 100.0))

    def _margin_interest_points(self, row, now_text=None):
        principal = int(row["principal_points"] or 0)
        rate_percent = float(row["interest_percent_daily"] or 0)
        if principal <= 0 or rate_percent <= 0:
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
        return int(math.ceil(principal * rate_percent * days / 100.0))

    def _margin_risk_payload(self, conn, position, market=None, *, now_text=None):
        market = market or self._market(conn, position["market_symbol"])
        price, price_source = self._current_market_price_points(conn, market)
        quantity_units = int(position["quantity_units"])
        exit_notional = notional_points(quantity_units, price)
        close_fee = fee_points(exit_notional, float(market["fee_rate_percent"] or 0))
        interest = self._margin_interest_points(position, now_text=now_text)
        collateral = int(position["collateral_points"] or 0)
        principal = int(position["principal_points"] or 0)
        entry_price = int(position["entry_price_points"] or price)
        entry_notional = notional_points(quantity_units, entry_price)
        initial_margin_percent = round((collateral * 100.0) / entry_notional, 4) if entry_notional > 0 else 0.0
        if position["position_type"] == "margin_long":
            equity_after = exit_notional - principal - interest - close_fee
            delta = equity_after - collateral
        else:
            delta = principal - exit_notional - interest - close_fee
            equity_after = collateral + delta
        settings = self._settings_payload(conn)
        maintenance_percent = float(settings.get("margin_maintenance_percent") or 0)
        maintenance_points = int(math.ceil(exit_notional * maintenance_percent / 100.0))
        fee_rate_percent = float(market["fee_rate_percent"] or 0)
        denominator_percent = None
        liquidation_notional = None
        if position["position_type"] == "margin_long":
            denominator_percent = 100.0 - fee_rate_percent - maintenance_percent
            if denominator_percent > 0:
                liquidation_notional = int(math.ceil((principal + interest) * 100.0 / denominator_percent))
        else:
            denominator_percent = 100.0 + fee_rate_percent + maintenance_percent
            liquidation_base = collateral + principal - interest
            if denominator_percent > 0 and liquidation_base > 0:
                liquidation_notional = int(math.ceil(liquidation_base * 100.0 / denominator_percent))
        liquidation_price_points = None
        if liquidation_notional is not None and quantity_units > 0:
            liquidation_price_points = int(math.ceil((liquidation_notional * ASSET_SCALE) / quantity_units))
        maintenance_ratio_percent = round((equity_after * 100.0) / maintenance_points, 2) if maintenance_points > 0 else 0.0
        if equity_after <= maintenance_points:
            risk_status = "liquidation"
            risk_reason = "權益已低於維持保證金，會被列入強制平倉"
        elif maintenance_ratio_percent < 150.0:
            risk_status = "warning"
            risk_reason = "整體維持率偏低，建議補保證金或降低倉位"
        elif position["position_type"] == "short":
            risk_status = "short_price_risk"
            risk_reason = "借券放空在價格上漲時會虧損，價格越高維持率越低"
        else:
            risk_status = "normal"
            risk_reason = "融資做多在價格下跌時會虧損，價格越低維持率越低"
        return {
            "price_points": price,
            "price_source": price_source,
            "exit_notional_points": exit_notional,
            "close_fee_points": close_fee,
            "interest_points": interest,
            "collateral_points": collateral,
            "initial_margin_points": collateral,
            "original_margin_points": collateral,
            "initial_margin_percent": initial_margin_percent,
            "entry_notional_points": entry_notional,
            "principal_points": principal,
            "delta_points": delta,
            "unrealized_pnl_points": delta,
            "equity_after_points": equity_after,
            "maintenance_percent": maintenance_percent,
            "maintenance_points": maintenance_points,
            "maintenance_margin_percent": maintenance_percent,
            "maintenance_margin_points": maintenance_points,
            "liquidation_notional_points": liquidation_notional,
            "liquidation_price_points": liquidation_price_points,
            "maintenance_ratio_percent": maintenance_ratio_percent,
            "risk_status": risk_status,
            "risk_reason": risk_reason,
            "liquidation_required": equity_after <= maintenance_points,
        }

    def _margin_position_payload_with_risk(self, conn, row, *, market=None):
        item = self._margin_position_payload(row)
        try:
            risk = self._margin_risk_payload(conn, row, market=market)
        except Exception as exc:
            risk = {
                "risk_status": "unavailable",
                "risk_reason": f"風險資料暫時無法計算：{str(exc)[:160]}",
                "liquidation_required": False,
            }
        item["risk"] = risk
        item["maintenance_ratio_percent"] = risk.get("maintenance_ratio_percent")
        item["risk_status"] = risk.get("risk_status")
        item["risk_reason"] = risk.get("risk_reason")
        item["equity_after_points"] = risk.get("equity_after_points")
        item["maintenance_points"] = risk.get("maintenance_points")
        item["maintenance_margin_points"] = risk.get("maintenance_margin_points")
        item["maintenance_margin_percent"] = risk.get("maintenance_margin_percent")
        item["initial_margin_points"] = risk.get("initial_margin_points")
        item["original_margin_points"] = risk.get("original_margin_points")
        item["initial_margin_percent"] = risk.get("initial_margin_percent")
        item["entry_notional_points"] = risk.get("entry_notional_points")
        item["current_price_points"] = risk.get("price_points")
        item["unrealized_pnl_points"] = risk.get("unrealized_pnl_points")
        item["liquidation_price_points"] = risk.get("liquidation_price_points")
        return item

    def _margin_summary_payload(self, rows):
        active = [row for row in rows if row.get("status") == "open"]
        total_equity = 0
        total_maintenance = 0
        liquidation_count = 0
        warning_count = 0
        for row in active:
            risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
            total_equity += int(risk.get("equity_after_points") or 0)
            total_maintenance += int(risk.get("maintenance_points") or 0)
            if risk.get("liquidation_required"):
                liquidation_count += 1
            elif str(risk.get("risk_status") or "") in {"warning", "unavailable"}:
                warning_count += 1
        ratio = round((total_equity / total_maintenance) * 100, 2) if total_maintenance > 0 else None
        if liquidation_count:
            status = "liquidation"
            reason = f"{liquidation_count} 筆倉位低於維持保證金"
        elif warning_count:
            status = "warning"
            reason = f"{warning_count} 筆倉位需要注意"
        elif active:
            status = "normal"
            reason = "整戶維持率正常"
        else:
            status = "none"
            reason = "目前沒有借貸倉位"
        return {
            "open_count": len(active),
            "total_equity_after_points": total_equity,
            "total_maintenance_points": total_maintenance,
            "maintenance_ratio_percent": ratio,
            "status": status,
            "reason": reason,
            "liquidation_count": liquidation_count,
            "warning_count": warning_count,
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
        return any(term in lowered for term in ("insufficient", "餘額不足", "積分不足", "資金不足", "持倉不足"))

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
                self._margin_position_payload_with_risk(conn, row, market=market_map.get(row["market_symbol"]))
                for row in conn.execute("SELECT * FROM trading_margin_positions WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            conn.commit()
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
            bots = [
                self._bot_payload(row)
                for row in conn.execute("SELECT * FROM trading_bots WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            bot_runs = [
                self._bot_run_payload(row)
                for row in conn.execute("SELECT * FROM trading_bot_runs WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            return {
                "state": state,
                "settings": self._settings_payload(conn),
                "funding": self._funding_payload(conn, user_id),
                "markets": markets,
                "positions": positions,
                "spot_summary": self._spot_summary_payload(positions),
                "futures_positions": futures_positions,
                "margin_positions": margin_positions,
                "margin_summary": self._margin_summary_payload(margin_positions),
                "orders": orders,
                "fills": fills,
                "bots": bots,
                "bot_runs": bot_runs,
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

    def _legacy_workflow(self, *, trigger_type, trigger_price, side, quantity_text, order_type, limit_price, max_runs, cooldown_seconds):
        condition = {"type": "always"}
        if trigger_type == "price_above":
            condition = {"type": "price_above", "value": int(trigger_price or 0)}
        elif trigger_type == "price_below":
            condition = {"type": "price_below", "value": int(trigger_price or 0)}
        action = {"type": "buy_amount", "amount_points": 100, "step": 1}
        if side == "sell":
            action = {"type": "sell_percent", "percent": 100, "step": 1}
        return {
            "version": 1,
            "strategy_kind": "workflow",
            "source": "legacy_condition",
            "branches": [{
                "id": "branch_1",
                "name": "預設策略",
                "priority": 10,
                "logic": "AND",
                "cooldown_seconds": int(cooldown_seconds or 0),
                "max_runs": int(max_runs or 1),
                "conditions": [condition],
                "actions": [{**action, "order_type": order_type, "limit_price_points": limit_price, "quantity": quantity_text}],
            }],
        }

    def _validate_workflow(self, value):
        if not value:
            return None
        if isinstance(value, str):
            try:
                workflow = json.loads(value)
            except Exception as exc:
                raise ValueError("workflow_json must be valid JSON") from exc
        elif isinstance(value, dict):
            workflow = value
        else:
            raise ValueError("workflow_json must be an object")
        nodes = workflow.get("nodes")
        edges = workflow.get("edges")
        if isinstance(nodes, list) or isinstance(edges, list):
            return self._validate_workflow_graph(workflow)
        branches = workflow.get("branches")
        if not isinstance(branches, list) or not branches:
            raise ValueError("workflow must contain at least one branch")
        clean_branches = []
        for index, branch in enumerate(branches[:20], start=1):
            if not isinstance(branch, dict):
                raise ValueError("workflow branch must be an object")
            logic = str(branch.get("logic") or "AND").upper()
            if logic not in {"AND", "OR"}:
                raise ValueError("workflow branch logic must be AND or OR")
            conditions = branch.get("conditions") or [{"type": "always"}]
            actions = branch.get("actions") or [{"type": "hold", "step": 1}]
            if not isinstance(conditions, list) or not isinstance(actions, list):
                raise ValueError("workflow branch conditions/actions must be arrays")
            clean_conditions = []
            for condition in conditions[:20]:
                if not isinstance(condition, dict):
                    raise ValueError("workflow condition must be an object")
                ctype = str(condition.get("type") or "always").strip()
                if ctype != "always" and ctype not in WORKFLOW_CONDITION_TYPES:
                    raise ValueError(f"unsupported workflow condition: {ctype}")
                clean = {"type": ctype}
                for key in ("value", "period", "position", "operator"):
                    if key in condition:
                        clean[key] = condition.get(key)
                clean_conditions.append(clean)
            clean_actions = []
            for action in actions[:20]:
                if not isinstance(action, dict):
                    raise ValueError("workflow action must be an object")
                atype = str(action.get("type") or "hold").strip()
                if atype not in WORKFLOW_ACTION_TYPES:
                    raise ValueError(f"unsupported workflow action: {atype}")
                clean = {
                    "type": atype,
                    "step": _to_int(action.get("step", len(clean_actions) + 1), name="workflow action step", minimum=1, maximum=1000),
                    "order_type": str(action.get("order_type") or "market").strip().lower(),
                }
                if clean["order_type"] not in {"market", "limit"}:
                    raise ValueError("workflow action order_type must be market or limit")
                for key in ("percent", "amount_points", "limit_price_points"):
                    if key in action and action.get(key) not in (None, ""):
                        clean[key] = float(action.get(key))
                clean_actions.append(clean)
            clean_branches.append({
                "id": str(branch.get("id") or f"branch_{index}")[:80],
                "name": str(branch.get("name") or f"策略分支 {index}")[:80],
                "priority": _to_int(branch.get("priority", 0), name="workflow priority", minimum=-1000, maximum=1000),
                "logic": logic,
                "cooldown_seconds": _to_int(branch.get("cooldown_seconds", 0), name="workflow cooldown_seconds", minimum=0, maximum=86400),
                "max_runs": _to_int(branch.get("max_runs", 1000), name="workflow max_runs", minimum=1, maximum=1000),
                "conditions": clean_conditions,
                "actions": clean_actions,
            })
        clean = {"version": 1, "strategy_kind": "workflow", "branches": clean_branches}
        if workflow.get("source"):
            clean["source"] = str(workflow.get("source"))[:80]
        return clean

    def _validate_workflow_graph(self, workflow):
        nodes = workflow.get("nodes")
        edges = workflow.get("edges")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("workflow graph must contain nodes")
        if not isinstance(edges, list):
            raise ValueError("workflow graph edges must be an array")
        clean_nodes = []
        node_ids = set()
        start_count = 0
        for index, node in enumerate(nodes[:100], start=1):
            if not isinstance(node, dict):
                raise ValueError("workflow graph node must be an object")
            node_id = str(node.get("id") or f"node_{index}")[:80]
            if not node_id or node_id in node_ids:
                raise ValueError("workflow graph node ids must be unique")
            node_ids.add(node_id)
            node_type = str(node.get("type") or "condition").strip().lower()
            if node_type not in WORKFLOW_NODE_TYPES:
                raise ValueError(f"unsupported workflow node type: {node_type}")
            clean = {
                "id": node_id,
                "type": node_type,
                "label": str(node.get("label") or node.get("name") or node_id)[:80],
                "x": _to_int(node.get("x", index * 120), name="node x", minimum=-100000, maximum=100000),
                "y": _to_int(node.get("y", 120), name="node y", minimum=-100000, maximum=100000),
                "inputs": [str(port)[:24] for port in (node.get("inputs") or ["in"]) if str(port) in WORKFLOW_PORTS],
                "outputs": [str(port)[:24] for port in (node.get("outputs") or ["out"]) if str(port) in WORKFLOW_PORTS],
                "priority": _to_int(node.get("priority", 0), name="node priority", minimum=-1000, maximum=1000),
            }
            if node_type == "start":
                start_count += 1
                clean["inputs"] = []
                clean["outputs"] = ["out"]
            elif node_type == "condition":
                condition = node.get("condition") if isinstance(node.get("condition"), dict) else node
                ctype = str(condition.get("type") or "always").strip()
                if ctype != "always" and ctype not in WORKFLOW_CONDITION_TYPES and not any(key in condition for key in ("AND", "OR", "NOT")):
                    raise ValueError(f"unsupported workflow condition: {ctype}")
                clean["condition"] = condition
                clean["outputs"] = ["true", "false"]
            elif node_type == "logic":
                operator = str(node.get("operator") or node.get("logic") or "AND").strip().upper()
                if operator not in {"AND", "OR", "NOT"}:
                    raise ValueError("workflow logic node must be AND, OR, or NOT")
                clean["operator"] = operator
                clean["outputs"] = ["true", "false"]
            elif node_type == "action":
                action = node.get("action") if isinstance(node.get("action"), dict) else node
                atype = str(action.get("type") or "hold").strip()
                if atype not in WORKFLOW_ACTION_TYPES:
                    raise ValueError(f"unsupported workflow action: {atype}")
                clean_action = {
                    "type": atype,
                    "step": _to_int(action.get("step", 1), name="workflow action step", minimum=1, maximum=1000),
                    "order_type": str(action.get("order_type") or "market").strip().lower(),
                }
                if clean_action["order_type"] not in {"market", "limit"}:
                    raise ValueError("workflow action order_type must be market or limit")
                for key in ("percent", "amount_points", "limit_price_points"):
                    if key in action and action.get(key) not in (None, ""):
                        clean_action[key] = float(action.get(key))
                clean["action"] = clean_action
                clean["outputs"] = ["out"]
            elif node_type == "control":
                clean["cooldown_seconds"] = _to_int(node.get("cooldown_seconds", 0), name="node cooldown_seconds", minimum=0, maximum=86400)
                clean["max_runs"] = _to_int(node.get("max_runs", 1000), name="node max_runs", minimum=1, maximum=1000)
                clean["outputs"] = ["then", "wait"]
            clean_nodes.append(clean)
        if start_count > 1:
            raise ValueError("workflow graph can contain at most one start node")
        clean_edges = []
        seen_edges = set()
        for index, edge in enumerate(edges[:200], start=1):
            if not isinstance(edge, dict):
                raise ValueError("workflow graph edge must be an object")
            source = str(edge.get("from") or edge.get("source") or "")[:80]
            target = str(edge.get("to") or edge.get("target") or "")[:80]
            if source not in node_ids or target not in node_ids:
                raise ValueError("workflow graph edge references unknown node")
            from_port = str(edge.get("from_port") or edge.get("source_port") or "out").strip().lower()
            to_port = str(edge.get("to_port") or edge.get("target_port") or "in").strip().lower()
            if from_port not in WORKFLOW_PORTS or to_port not in WORKFLOW_PORTS:
                raise ValueError("workflow graph edge port is invalid")
            source_node = next((node for node in clean_nodes if node["id"] == source), None)
            target_node = next((node for node in clean_nodes if node["id"] == target), None)
            if source_node and from_port not in set(source_node.get("outputs") or []):
                raise ValueError("workflow graph edge uses unavailable source port")
            if target_node and to_port not in set(target_node.get("inputs") or ["in"]):
                raise ValueError("workflow graph edge uses unavailable target port")
            edge_id = str(edge.get("id") or f"edge_{index}")[:80]
            edge_key = (source, from_port, target, to_port)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            clean_edges.append({"id": edge_id, "from": source, "from_port": from_port, "to": target, "to_port": to_port})
        action_ids = {node["id"] for node in clean_nodes if node["type"] == "action"}
        if not action_ids:
            raise ValueError("workflow graph must contain at least one action node")
        start_node_id = str(workflow.get("start_node_id") or next((node["id"] for node in clean_nodes if node["type"] == "start"), clean_nodes[0]["id"]))[:80]
        if start_node_id not in node_ids:
            raise ValueError("workflow graph start_node_id references unknown node")
        outgoing = {}
        for edge in clean_edges:
            outgoing.setdefault(edge["from"], []).append(edge["to"])
        reachable = set()
        stack = [start_node_id]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            stack.extend(outgoing.get(node_id, []))
        if not action_ids & reachable:
            raise ValueError("workflow graph action nodes must be reachable from start")
        clean = {
            "version": 2,
            "strategy_kind": "workflow_graph",
            "source": str(workflow.get("source") or "workflow_editor")[:80],
            "name": str(workflow.get("name") or "Workflow Strategy")[:80],
            "description": str(workflow.get("description") or "")[:160],
            "start_node_id": start_node_id,
            "nodes": clean_nodes,
            "edges": clean_edges,
        }
        return clean

    def _validate_bot_payload(self, conn, payload):
        payload = payload or {}
        market = self._market(conn, payload.get("market_symbol"))
        bot_type = str(payload.get("bot_type") or "conditional").strip().lower()
        if bot_type not in TRADING_BOT_TYPES:
            raise ValueError("bot_type must be conditional or dca")
        side = str(payload.get("side") or "").strip().lower()
        order_type = str(payload.get("order_type") or "").strip().lower()
        has_workflow_payload = payload.get("workflow_json") is not None or payload.get("workflow") is not None
        trigger_type = str(payload.get("trigger_type") or ("always" if has_workflow_payload else "")).strip().lower()
        if bot_type == "dca":
            side = "buy"
            order_type = "market"
            trigger_type = "always"
        if side not in {"buy", "sell"}:
            raise ValueError("bot side must be buy or sell")
        if order_type not in {"market", "limit"}:
            raise ValueError("bot order_type must be market or limit")
        if trigger_type not in TRADING_BOT_TRIGGER_TYPES:
            raise ValueError("bot trigger_type must be always, price_above, or price_below")
        budget_points = _to_int(payload.get("budget_points", 0), name="budget_points", minimum=0, maximum=10**12)
        if bot_type == "dca":
            if budget_points <= 0:
                raise ValueError("dca budget_points must be positive")
            quantity_text = "0.00000001"
        else:
            quantity_text = str(payload.get("quantity") or payload.get("quantity_text") or "").strip()
            quantity_to_units(quantity_text)
        limit_price = None
        if order_type == "limit":
            limit_price = _to_int(payload.get("limit_price_points"), name="limit_price_points", minimum=1, maximum=10**12)
        trigger_price = None
        if trigger_type != "always":
            trigger_price = _to_int(payload.get("trigger_price_points"), name="trigger_price_points", minimum=1, maximum=10**12)
        max_runs = _to_int(payload.get("max_runs", 1), name="max_runs", minimum=1, maximum=1000)
        cooldown_seconds = _to_int(payload.get("cooldown_seconds", 300), name="cooldown_seconds", minimum=0, maximum=86400)
        interval_hours = _to_int(payload.get("interval_hours", 24), name="interval_hours", minimum=1, maximum=8760)
        if bot_type == "dca":
            cooldown_seconds = max(cooldown_seconds, interval_hours * 3600)
        workflow = None
        if bot_type == "conditional":
            workflow = self._validate_workflow(payload.get("workflow_json") or payload.get("workflow"))
            if workflow is None:
                workflow = self._legacy_workflow(
                    trigger_type=trigger_type,
                    trigger_price=trigger_price,
                    side=side,
                    quantity_text=quantity_text,
                    order_type=order_type,
                    limit_price=limit_price,
                    max_runs=max_runs,
                    cooldown_seconds=cooldown_seconds,
                )
        name = str(payload.get("name") or "").strip()[:80] or f"{market['symbol']} {bot_type}"
        return {
            "bot_type": bot_type,
            "name": name,
            "market_symbol": market["symbol"],
            "side": side,
            "order_type": order_type,
            "quantity_text": quantity_text,
            "limit_price_points": limit_price,
            "trigger_type": trigger_type,
            "trigger_price_points": trigger_price,
            "enabled": bool(payload.get("enabled", True)),
            "max_runs": max_runs,
            "cooldown_seconds": cooldown_seconds,
            "interval_hours": interval_hours,
            "budget_points": budget_points,
            "workflow": workflow,
        }

    def list_trading_bots(self, *, actor):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            bots = [
                self._bot_payload(row)
                for row in conn.execute("SELECT * FROM trading_bots WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()
            ]
            runs = [
                self._bot_run_payload(row)
                for row in conn.execute("SELECT * FROM trading_bot_runs WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()
            ]
            return {"ok": True, "bots": bots, "runs": runs}
        finally:
            conn.close()

    def save_trading_bot(self, *, actor, payload, bot_uuid=None):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            data = self._validate_bot_payload(conn, payload)
            now = _now()
            if bot_uuid:
                existing = conn.execute("SELECT * FROM trading_bots WHERE bot_uuid=?", (str(bot_uuid),)).fetchone()
                if not existing:
                    raise ValueError("trading bot not found")
                if int(existing["user_id"]) != int(user_id):
                    raise ValueError("cannot update another user's trading bot")
                conn.execute(
                    """
                    UPDATE trading_bots
                    SET bot_type=?, name=?, market_symbol=?, side=?, order_type=?, quantity_text=?,
                        limit_price_points=?, trigger_type=?, trigger_price_points=?,
                        enabled=?, max_runs=?, cooldown_seconds=?, interval_hours=?, budget_points=?,
                        workflow_json=?, execution_state_json='{}', last_error='', updated_at=?
                    WHERE id=?
                    """,
                    (
                        data["bot_type"], data["name"], data["market_symbol"], data["side"], data["order_type"], data["quantity_text"],
                        data["limit_price_points"], data["trigger_type"], data["trigger_price_points"],
                        1 if data["enabled"] else 0, data["max_runs"], data["cooldown_seconds"],
                        data["interval_hours"], data["budget_points"], _json_dumps(data["workflow"]) if data["workflow"] else None,
                        now, existing["id"],
                    ),
                )
                bot_id = existing["id"]
                event_type = "TRADING_BOT_UPDATED"
            else:
                cur = conn.execute(
                    """
                    INSERT INTO trading_bots (
                        bot_uuid, user_id, bot_type, name, market_symbol, side, order_type, quantity_text,
                        limit_price_points, trigger_type, trigger_price_points, enabled,
                        max_runs, run_count, cooldown_seconds, interval_hours, budget_points, workflow_json, execution_state_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, '{}', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), user_id, data["bot_type"], data["name"], data["market_symbol"], data["side"], data["order_type"],
                        data["quantity_text"], data["limit_price_points"], data["trigger_type"], data["trigger_price_points"],
                        1 if data["enabled"] else 0, data["max_runs"], data["cooldown_seconds"],
                        data["interval_hours"], data["budget_points"], _json_dumps(data["workflow"]) if data["workflow"] else None,
                        now, now,
                    ),
                )
                bot_id = cur.lastrowid
                event_type = "TRADING_BOT_CREATED"
            row = conn.execute("SELECT * FROM trading_bots WHERE id=?", (bot_id,)).fetchone()
            self._audit_event(conn, event_type, "trading bot workflow saved", actor=actor, target_user_id=user_id, market_symbol=row["market_symbol"], metadata={"bot_uuid": row["bot_uuid"], "bot_type": row["bot_type"], "trigger_type": row["trigger_type"], "side": row["side"], "order_type": row["order_type"]})
            conn.commit()
            return {"ok": True, "bot": self._bot_payload(row)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_trading_bot(self, *, actor, bot_uuid):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM trading_bots WHERE bot_uuid=?", (str(bot_uuid or ""),)).fetchone()
            if not row:
                raise ValueError("trading bot not found")
            if int(row["user_id"]) != int(user_id):
                raise ValueError("cannot delete another user's trading bot")
            conn.execute("DELETE FROM trading_bots WHERE id=?", (row["id"],))
            self._audit_event(conn, "TRADING_BOT_DELETED", "trading bot workflow deleted", actor=actor, target_user_id=user_id, market_symbol=row["market_symbol"], metadata={"bot_uuid": row["bot_uuid"]})
            conn.commit()
            return {"ok": True, "bot_uuid": row["bot_uuid"]}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _bot_trigger_hit(self, bot, observed_price):
        if str(bot["bot_type"] or "conditional") == "dca":
            return True
        trigger_type = bot["trigger_type"]
        if trigger_type == "always":
            return True
        trigger_price = int(bot["trigger_price_points"] or 0)
        if trigger_type == "price_above":
            return int(observed_price) >= trigger_price
        if trigger_type == "price_below":
            return int(observed_price) <= trigger_price
        return False

    def _quantity_text_from_budget(self, *, budget_points, price_points):
        budget = int(budget_points or 0)
        price = int(price_points or 0)
        if budget <= 0 or price <= 0:
            raise ValueError("dca budget or price is invalid")
        units = int((budget * ASSET_SCALE) // price)
        if units <= 0:
            raise ValueError("dca budget is too small for current price")
        return units_to_quantity(units)

    def _workflow_indicator_context(self, candles, index):
        candles = candles or []
        index = max(0, min(int(index or 0), len(candles) - 1)) if candles else 0
        closes = []
        highs = []
        lows = []
        for candle in candles[:index + 1]:
            try:
                closes.append(float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt") or 0))
                highs.append(float(candle.get("high_points") or candle.get("high_usdt") or closes[-1]))
                lows.append(float(candle.get("low_points") or candle.get("low_usdt") or closes[-1]))
            except Exception:
                continue
        if not closes:
            return {}
        def sma(period):
            period = int(period)
            if len(closes) < period:
                return None
            return sum(closes[-period:]) / period
        def rsi(period=14):
            if len(closes) <= period:
                return None
            gains = []
            losses = []
            for offset in range(len(closes) - period, len(closes)):
                delta = closes[offset] - closes[offset - 1]
                gains.append(max(delta, 0))
                losses.append(abs(min(delta, 0)))
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        ma20 = sma(20)
        ma50 = sma(50)
        bb_mid = ma20
        bb_upper = None
        bb_lower = None
        if ma20 is not None and len(closes) >= 20:
            variance = sum((value - ma20) ** 2 for value in closes[-20:]) / 20
            std = math.sqrt(variance)
            bb_upper = ma20 + 2 * std
            bb_lower = ma20 - 2 * std
        kd_k = None
        if len(closes) >= 9 and highs and lows:
            high9 = max(highs[-9:])
            low9 = min(lows[-9:])
            kd_k = 50.0 if high9 == low9 else ((closes[-1] - low9) * 100 / (high9 - low9))
        return {
            "price": closes[-1],
            "ma20": ma20,
            "ma50": ma50,
            "ma200": sma(200),
            "bb_mid": bb_mid,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "rsi": rsi(14),
            "kd": kd_k,
        }

    def _workflow_condition_hit(self, condition, context):
        if not isinstance(condition, dict):
            return False
        if "AND" in condition:
            items = condition.get("AND") if isinstance(condition.get("AND"), list) else []
            return bool(items) and all(self._workflow_condition_hit(item, context) for item in items)
        if "OR" in condition:
            items = condition.get("OR") if isinstance(condition.get("OR"), list) else []
            return bool(items) and any(self._workflow_condition_hit(item, context) for item in items)
        if "NOT" in condition:
            target = condition.get("NOT")
            return not self._workflow_condition_hit(target if isinstance(target, dict) else {"type": str(target)}, context)
        ctype = str(condition.get("type") or "always")
        price = float(context.get("price") or 0)
        value = float(condition.get("value") or 0)
        if ctype == "always":
            return True
        if ctype == "price_below":
            return price > 0 and price <= value
        if ctype == "price_above":
            return price > 0 and price >= value
        if ctype == "has_position":
            return bool(context.get("has_position")) == bool(condition.get("value", True))
        if ctype == "rsi_above":
            return context.get("rsi") is not None and float(context["rsi"]) >= value
        if ctype == "rsi_below":
            return context.get("rsi") is not None and float(context["rsi"]) <= value
        if ctype == "kd_above":
            return context.get("kd") is not None and float(context["kd"]) >= value
        if ctype == "kd_below":
            return context.get("kd") is not None and float(context["kd"]) <= value
        if ctype == "ma_position":
            period = int(condition.get("period") or 50)
            ma_value = context.get(f"ma{period}")
            position = str(condition.get("position") or "above")
            return ma_value is not None and ((price >= ma_value) if position == "above" else (price <= ma_value))
        if ctype == "bb_position":
            position = str(condition.get("position") or "above_mid")
            if position == "above_mid":
                return context.get("bb_mid") is not None and price >= float(context["bb_mid"])
            if position == "below_mid":
                return context.get("bb_mid") is not None and price <= float(context["bb_mid"])
            if position == "above_upper":
                return context.get("bb_upper") is not None and price >= float(context["bb_upper"])
            if position == "below_lower":
                return context.get("bb_lower") is not None and price <= float(context["bb_lower"])
        return False

    def _workflow_graph_decision(self, workflow, *, context, run_count=0, last_run_at=None, execution_state=None):
        nodes = {node["id"]: node for node in workflow.get("nodes") or []}
        incoming = {}
        outgoing = {}
        for edge in workflow.get("edges") or []:
            incoming.setdefault(edge["to"], []).append(edge)
            outgoing.setdefault(edge["from"], []).append(edge)
        memo = {}
        visiting = set()

        def node_value(node_id):
            if node_id in memo:
                return memo[node_id]
            if node_id in visiting:
                raise ValueError("workflow graph contains a cycle")
            node = nodes.get(node_id)
            if not node:
                return False
            visiting.add(node_id)
            ntype = node.get("type")
            if ntype == "start":
                result = True
            elif ntype == "condition":
                result = self._workflow_condition_hit(node.get("condition") or {}, context)
            elif ntype == "logic":
                values = [edge_value(edge) for edge in incoming.get(node_id, [])]
                operator = str(node.get("operator") or "AND").upper()
                if operator == "OR":
                    result = any(values)
                elif operator == "NOT":
                    result = not (values[0] if values else False)
                else:
                    result = bool(values) and all(values)
            elif ntype == "control":
                cooldown = int(node.get("cooldown_seconds") or 0)
                max_runs = int(node.get("max_runs") or 1000)
                result = int(run_count or 0) < max_runs
                if result and cooldown and last_run_at:
                    try:
                        result = (datetime.now() - datetime.fromisoformat(str(last_run_at))).total_seconds() >= cooldown
                    except Exception:
                        result = True
                if result:
                    result = all(edge_value(edge) for edge in incoming.get(node_id, [])) if incoming.get(node_id) else True
            else:
                result = all(edge_value(edge) for edge in incoming.get(node_id, [])) if incoming.get(node_id) else False
            visiting.remove(node_id)
            memo[node_id] = bool(result)
            return memo[node_id]

        def edge_value(edge):
            value = node_value(edge["from"])
            if edge.get("from_port") == "false":
                return not value
            if edge.get("from_port") in {"true", "then", "out"}:
                return value
            return value

        executed = set((execution_state or {}).get("executed_action_ids") or [])
        branch_counts = (execution_state or {}).get("branch_step_counts") or {}
        actions = sorted(
            (node for node in nodes.values() if node.get("type") == "action"),
            key=lambda node: (-int(node.get("priority") or 0), int((node.get("action") or {}).get("step") or 1)),
        )
        for node in actions:
            action = node.get("action") or {"type": "hold", "step": 1}
            action_id = node["id"]
            if action.get("type") != "close_all" and action_id in executed:
                continue
            if action.get("type") != "close_all" and int(action.get("step") or 1) <= int(branch_counts.get(action_id, run_count or 0)):
                continue
            gates = incoming.get(action_id) or []
            matched = all(edge_value(edge) for edge in gates) if gates else False
            if matched:
                return {"branch": node, "action": action, "reason": node.get("label") or action_id, "action_id": action_id}
        return None

    def _workflow_decision(self, workflow, *, context, run_count=0, last_run_at=None, execution_state=None):
        workflow = self._validate_workflow(workflow)
        if workflow.get("strategy_kind") == "workflow_graph":
            return self._workflow_graph_decision(workflow, context=context, run_count=run_count, last_run_at=last_run_at, execution_state=execution_state)
        branches = sorted(workflow["branches"], key=lambda row: int(row.get("priority") or 0), reverse=True)
        now_dt = datetime.now()
        branch_counts = (execution_state or {}).get("branch_step_counts") or {}
        for branch in branches:
            cooldown = int(branch.get("cooldown_seconds") or 0)
            if cooldown and last_run_at:
                try:
                    if (now_dt - datetime.fromisoformat(str(last_run_at))).total_seconds() < cooldown:
                        continue
                except Exception:
                    pass
            conditions = branch.get("conditions") or [{"type": "always"}]
            hits = [self._workflow_condition_hit(condition, context) for condition in conditions]
            matched = all(hits) if branch.get("logic") == "AND" else any(hits)
            if not matched:
                continue
            fallback_count = int(run_count or 0) if workflow.get("source") == "legacy_condition" else 0
            step = int(branch_counts.get(branch.get("id"), fallback_count)) + 1
            actions = sorted(branch.get("actions") or [], key=lambda row: int(row.get("step") or 1))
            action = next((row for row in actions if int(row.get("step") or 1) >= step), None)
            if not action:
                continue
            return {"branch": branch, "action": action, "reason": branch.get("name") or branch.get("id") or "workflow"}
        return None

    def _workflow_order_from_decision(self, conn, *, user_id, actor, market, decision, price_points):
        action = decision.get("action") or {}
        atype = str(action.get("type") or "hold")
        if atype == "hold":
            return None
        funding = self._funding_payload(conn, user_id)
        position = self._position(conn, user_id, market["symbol"])
        order_type = str(action.get("order_type") or "market").lower()
        limit_price = int(action.get("limit_price_points") or 0) or None
        if atype in {"buy_percent", "buy_amount"}:
            available = int(funding.get("available_points") or 0)
            amount = int(float(action.get("amount_points") or 0))
            if atype == "buy_percent":
                amount = int(available * max(0.0, min(float(action.get("percent") or 0), 100.0)) / 100)
            fee_rate = float(market["fee_rate_percent"] or 0) / 100.0
            spend = max(0, min(amount, available))
            if spend <= 0:
                raise ValueError("workflow buy action has no available funds")
            units = int((spend / (1 + fee_rate)) * ASSET_SCALE // int(price_points or 1))
            if units <= 0:
                raise ValueError("workflow buy action is too small")
            return {"side": "buy", "order_type": order_type, "quantity": units_to_quantity(units), "limit_price_points": limit_price}
        if atype in {"sell_percent", "close_all"}:
            sellable_units = max(0, int(position["quantity_units"] or 0) - int(position["locked_quantity_units"] or 0))
            percent = 100.0 if atype == "close_all" else max(0.0, min(float(action.get("percent") or 0), 100.0))
            units = int(sellable_units * percent / 100)
            if units <= 0:
                raise ValueError("workflow sell action has no sellable position")
            return {"side": "sell", "order_type": order_type, "quantity": units_to_quantity(units), "limit_price_points": limit_price}
        return None

    def run_trading_bots(self, *, actor, limit=50):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        limit = _to_int(limit or 50, name="limit", minimum=1, maximum=200)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT b.*, u.username, u.role
                FROM trading_bots b
                JOIN users u ON u.id=b.user_id
                WHERE b.user_id=? AND b.enabled=1 AND b.run_count < b.max_runs
                ORDER BY b.id ASC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        finally:
            conn.close()

        scanned = 0
        triggered = []
        skipped = []
        failed = []
        for row in rows:
            scanned += 1
            now_dt = datetime.now()
            workflow_state = _json_loads(row["execution_state_json"], {}) if "execution_state_json" in row.keys() else {}
            if not isinstance(workflow_state, dict):
                workflow_state = {}
            workflow_state.setdefault("executed_action_ids", [])
            workflow_state.setdefault("branch_step_counts", {})
            decision = None
            if row["last_run_at"]:
                try:
                    last_run = datetime.fromisoformat(str(row["last_run_at"]))
                    if (now_dt - last_run).total_seconds() < int(row["cooldown_seconds"] or 0):
                        skipped.append({"bot_uuid": row["bot_uuid"], "reason": "cooldown"})
                        continue
                except Exception:
                    pass
            observed_price = None
            try:
                price_conn = self.get_db()
                self.ensure_schema(price_conn)
                market = self._market(price_conn, row["market_symbol"])
                observed_price, price_source = self._current_market_price_points(price_conn, market)
                workflow = _json_loads(row["workflow_json"], None) if "workflow_json" in row.keys() else None
                order_payload = None
                if workflow and str(row["bot_type"] or "conditional") == "conditional":
                    context = self._workflow_live_context(
                        price_conn,
                        market=market,
                        user_id=int(row["user_id"]),
                        observed_price=observed_price,
                    )
                    decision = self._workflow_decision(
                        workflow,
                        context=context,
                        run_count=int(row["run_count"] or 0),
                        last_run_at=row["last_run_at"],
                        execution_state=workflow_state,
                    )
                    if not decision:
                        skipped_reason = "condition_not_met" if workflow.get("source") == "legacy_condition" else "workflow_not_matched"
                        price_conn.close()
                        self._record_bot_run(row, status="skipped", observed_price=observed_price, error=skipped_reason)
                        skipped.append({"bot_uuid": row["bot_uuid"], "reason": skipped_reason, "observed_price_points": observed_price})
                        continue
                    order_payload = self._workflow_order_from_decision(
                        price_conn,
                        user_id=int(row["user_id"]),
                        actor={"id": int(row["user_id"]), "username": row["username"], "role": row["role"]},
                        market=market,
                        decision=decision,
                        price_points=observed_price,
                    )
                    if not order_payload:
                        price_conn.close()
                        self._record_bot_run(row, status="skipped", observed_price=observed_price, error="workflow_hold")
                        skipped.append({"bot_uuid": row["bot_uuid"], "reason": "workflow_hold", "observed_price_points": observed_price})
                        continue
                price_conn.close()
                if not workflow and not self._bot_trigger_hit(row, observed_price):
                    self._record_bot_run(row, status="skipped", observed_price=observed_price, error="condition_not_met")
                    skipped.append({"bot_uuid": row["bot_uuid"], "reason": "condition_not_met", "observed_price_points": observed_price})
                    continue
                quantity_text = row["quantity_text"]
                if str(row["bot_type"] or "conditional") == "dca":
                    quantity_text = self._quantity_text_from_budget(
                        budget_points=int(row["budget_points"] or 0),
                        price_points=observed_price,
                    )
                bot_actor = {"id": int(row["user_id"]), "username": row["username"], "role": row["role"]}
                if order_payload:
                    quantity_text = order_payload["quantity"]
                    order_type = order_payload["order_type"]
                    side = order_payload["side"]
                    limit_price_points = order_payload.get("limit_price_points")
                else:
                    order_type = row["order_type"]
                    side = row["side"]
                    limit_price_points = row["limit_price_points"]
                result = self.place_order(
                    actor=bot_actor,
                    market_symbol=row["market_symbol"],
                    side=side,
                    order_type=order_type,
                    quantity=quantity_text,
                    limit_price_points=limit_price_points,
                )
                order_uuid = (result.get("order") or {}).get("order_uuid")
                if workflow and decision:
                    action = decision.get("action") or {}
                    action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                    if action_id:
                        counts = workflow_state.setdefault("branch_step_counts", {})
                        counts[action_id] = int(counts.get(action_id, 0)) + 1
                        if action.get("type") != "close_all":
                            executed = workflow_state.setdefault("executed_action_ids", [])
                            if action_id not in executed:
                                executed.append(action_id)
                self._record_bot_run(row, status="triggered", observed_price=observed_price, order_uuid=order_uuid, execution_state=workflow_state)
                triggered.append({"bot_uuid": row["bot_uuid"], "order_uuid": order_uuid, "observed_price_points": observed_price, "executed": bool(result.get("executed"))})
            except Exception as exc:
                if "price_conn" in locals():
                    try:
                        price_conn.close()
                    except Exception:
                        pass
                self._record_bot_run(row, status="failed", observed_price=observed_price, error=str(exc))
                failed.append({"bot_uuid": row["bot_uuid"], "error": str(exc), "observed_price_points": observed_price})
        return {"ok": not failed, "scanned": scanned, "triggered": triggered, "skipped": skipped, "failed": failed}

    def backtest_trading_bot(self, *, actor, payload):
        if not self._actor_id(actor):
            raise ValueError("login required")
        payload = payload or {}
        bot_config = payload.get("bot_config") if isinstance(payload.get("bot_config"), dict) else {}
        if bot_config:
            payload = {**bot_config, **payload}
        candles = payload.get("candles") or []
        if not isinstance(candles, list) or len(candles) < 2:
            raise ValueError("candles are required for backtest")
        if len(candles) > MAX_BACKTEST_CANDLES:
            raise ValueError(f"candles length must be <= {MAX_BACKTEST_CANDLES}")
        start_time = str(payload.get("start_time") or "").strip()
        end_time = str(payload.get("end_time") or "").strip()
        if start_time or end_time:
            filtered = []
            for candle in candles:
                stamp = str(candle.get("time_iso") or candle.get("time") or "")
                if start_time and stamp < start_time:
                    continue
                if end_time and stamp > end_time:
                    continue
                filtered.append(candle)
            candles = filtered
            if len(candles) < 2:
                raise ValueError("candles are required for selected backtest range")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            market = self._market(conn, payload.get("market_symbol"))
            fee_rate_percent = float(market["fee_rate_percent"] or 0)
        finally:
            conn.close()
        strategy = str(payload.get("strategy") or payload.get("bot_type") or "conditional").strip().lower()
        if strategy == "strategy":
            strategy = "workflow"
        if strategy not in {"conditional", "dca", "workflow"}:
            raise ValueError("backtest strategy must be conditional, workflow, or dca")
        workflow = None
        if strategy == "workflow":
            workflow = self._validate_workflow(payload.get("workflow_json") or payload.get("workflow"))
        cash = _to_int(payload.get("initial_cash_points", 10_000), name="initial_cash_points", minimum=1, maximum=10**12)
        order_points = _to_int(payload.get("order_points", 100), name="order_points", minimum=1, maximum=10**12)
        trigger_type = str(payload.get("trigger_type") or "price_below").strip().lower()
        trigger_price = int(payload.get("trigger_price_points") or 0)
        interval_candles = _to_int(payload.get("interval_candles", 1), name="interval_candles", minimum=1, maximum=10_000)
        initial_cash = cash
        units = 0
        trades = []
        equity_curve = []
        peak_value = initial_cash
        max_drawdown_percent = 0.0
        wins = 0
        sells = 0
        workflow_state = {"executed_action_ids": set(), "branch_step_counts": {}}
        for index, candle in enumerate(candles):
            try:
                price = int(round(float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt"))))
            except Exception:
                continue
            if price <= 0:
                continue
            should_buy = False
            should_sell = False
            workflow_spend = order_points
            workflow_sell_percent = 0.0
            if strategy == "dca":
                should_buy = index % interval_candles == 0
            elif strategy == "workflow":
                context = self._workflow_indicator_context(candles, index)
                context["price"] = price
                context["has_position"] = units > 0
                decision = self._workflow_decision(workflow, context=context, run_count=len(trades), last_run_at=None, execution_state=workflow_state)
                action = (decision or {}).get("action") or {}
                atype = str(action.get("type") or "hold")
                if atype in {"buy_percent", "buy_amount"}:
                    should_buy = True
                    workflow_spend = int(float(action.get("amount_points") or 0))
                    if atype == "buy_percent":
                        workflow_spend = int(cash * max(0.0, min(float(action.get("percent") or 0), 100.0)) / 100)
                elif atype in {"sell_percent", "close_all"}:
                    should_sell = True
                    workflow_sell_percent = 100.0 if atype == "close_all" else max(0.0, min(float(action.get("percent") or 0), 100.0))
            elif trigger_type == "price_below":
                should_buy = trigger_price > 0 and price <= trigger_price
            elif trigger_type == "price_above":
                should_buy = trigger_price > 0 and price >= trigger_price
            elif trigger_type == "always":
                should_buy = True
            if should_sell and units > 0:
                sell_units = int(units * workflow_sell_percent / 100)
                if sell_units > 0:
                    gross = notional_points(sell_units, price)
                    fee = fee_points(gross, fee_rate_percent)
                    cash += max(0, gross - fee)
                    units -= sell_units
                    trades.append({
                        "index": index,
                        "time": candle.get("time") or candle.get("time_iso") or index,
                        "side": "sell",
                        "price_points": price,
                        "spend_points": 0,
                        "fee_points": fee,
                        "pnl_points": max(0, gross - fee),
                        "quantity": units_to_quantity(sell_units),
                    })
                    sells += 1
                    if gross - fee > 0:
                        wins += 1
                    if strategy == "workflow" and decision:
                        action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                        if action_id:
                            workflow_state["executed_action_ids"].add(action_id)
                        branch_id = (decision.get("branch") or {}).get("id")
                        if branch_id:
                            workflow_state["branch_step_counts"][branch_id] = int(workflow_state["branch_step_counts"].get(branch_id, 0)) + 1
                    equity = cash + notional_points(units, price)
                    peak_value = max(peak_value, equity)
                    if peak_value > 0:
                        max_drawdown_percent = max(max_drawdown_percent, round((peak_value - equity) * 100 / peak_value, 4))
                    equity_curve.append({"index": index, "time": candle.get("time") or candle.get("time_iso") or index, "equity_points": equity, "price_points": price})
                continue
            if not should_buy or cash <= 0:
                equity = cash + notional_points(units, price)
                peak_value = max(peak_value, equity)
                if peak_value > 0:
                    max_drawdown_percent = max(max_drawdown_percent, round((peak_value - equity) * 100 / peak_value, 4))
                equity_curve.append({"index": index, "time": candle.get("time") or candle.get("time_iso") or index, "equity_points": equity, "price_points": price})
                continue
            spend = min(workflow_spend, cash)
            fee = fee_points(spend, fee_rate_percent)
            net_spend = max(0, spend - fee)
            buy_units = int((net_spend * ASSET_SCALE) // price)
            if buy_units <= 0:
                continue
            cash -= spend
            units += buy_units
            trades.append({
                "index": index,
                "time": candle.get("time") or candle.get("time_iso") or index,
                "side": "buy",
                "price_points": price,
                "spend_points": spend,
                "fee_points": fee,
                "quantity": units_to_quantity(buy_units),
            })
            if strategy == "workflow" and decision:
                action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                if action_id:
                    workflow_state["executed_action_ids"].add(action_id)
                branch_id = (decision.get("branch") or {}).get("id")
                if branch_id:
                    workflow_state["branch_step_counts"][branch_id] = int(workflow_state["branch_step_counts"].get(branch_id, 0)) + 1
            equity = cash + notional_points(units, price)
            peak_value = max(peak_value, equity)
            if peak_value > 0:
                max_drawdown_percent = max(max_drawdown_percent, round((peak_value - equity) * 100 / peak_value, 4))
            equity_curve.append({"index": index, "time": candle.get("time") or candle.get("time_iso") or index, "equity_points": equity, "price_points": price})
        last_price = 0
        for candle in reversed(candles):
            try:
                last_price = int(round(float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt"))))
                if last_price > 0:
                    break
            except Exception:
                continue
        position_value = notional_points(units, last_price) if last_price else 0
        final_value = cash + position_value
        return {
            "ok": True,
            "strategy": strategy,
            "market_symbol": market["symbol"],
            "initial_cash_points": initial_cash,
            "cash_points": cash,
            "position_quantity": units_to_quantity(units),
            "position_value_points": position_value,
            "final_value_points": final_value,
            "pnl_points": final_value - initial_cash,
            "return_percent": round(((final_value - initial_cash) * 100) / initial_cash, 4),
            "max_drawdown_percent": max_drawdown_percent,
            "win_rate_percent": round((wins * 100 / sells), 4) if sells else 0.0,
            "trade_count": len(trades),
            "trades": trades,
            "equity_curve": equity_curve,
            "start_time": start_time,
            "end_time": end_time,
        }

    def _record_bot_run(self, bot, *, status, observed_price=None, order_uuid=None, error="", execution_state=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            now = _now()
            conn.execute(
                """
                INSERT INTO trading_bot_runs (
                    run_uuid, bot_id, user_id, market_symbol, trigger_type, trigger_price_points,
                    observed_price_points, status, order_uuid, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    int(bot["id"]),
                    int(bot["user_id"]),
                    bot["market_symbol"],
                    bot["trigger_type"],
                    bot["trigger_price_points"],
                    observed_price,
                    status,
                    order_uuid,
                    str(error or "")[:240],
                    now,
                ),
            )
            if status == "triggered":
                if execution_state is not None:
                    conn.execute(
                        "UPDATE trading_bots SET run_count=run_count+1, last_run_at=?, execution_state_json=?, last_error='', updated_at=? WHERE id=?",
                        (now, _json_dumps(execution_state), now, int(bot["id"])),
                    )
                else:
                    conn.execute(
                        "UPDATE trading_bots SET run_count=run_count+1, last_run_at=?, last_error='', updated_at=? WHERE id=?",
                        (now, now, int(bot["id"])),
                    )
            elif status == "failed":
                conn.execute(
                    "UPDATE trading_bots SET last_error=?, updated_at=? WHERE id=?",
                    (str(error or "")[:240], now, int(bot["id"])),
                )
            self._audit_event(
                conn,
                "TRADING_BOT_RUN",
                f"trading bot {status}",
                actor={"id": int(bot["user_id"]), "username": bot["username"], "role": bot["role"]},
                target_user_id=int(bot["user_id"]),
                market_symbol=bot["market_symbol"],
                severity="warning" if status == "failed" else "info",
                metadata={"bot_uuid": bot["bot_uuid"], "status": status, "observed_price_points": observed_price, "order_uuid": order_uuid, "error": str(error or "")[:240]},
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
            effective_fee_rate_percent = float(market["fee_rate_percent"] or 0) * (2 if emergency_close else 1)
            fee = fee_points(estimated_notional, effective_fee_rate_percent)
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
            if side == "buy" and funding_mode == "root_simulated":
                account = self._root_sim_account(conn, user_id)
                root_available = int(account["balance_points"] or 0)
                if total_points > root_available:
                    raise ValueError(f"root 模擬交易資金不足：需要 {total_points} 點，目前可用 {root_available} 點")
            elif side == "buy" and funding_mode != "root_simulated":
                trial = self._ensure_trial_credit(conn, user_id)
                trial_available = int(trial["available_points"] or 0) if trial and trial["status"] == "active" else 0
                wallet = self.points_service.ensure_wallet(conn, user_id)
                wallet_payload = self.points_service.serialize_wallet(wallet)
                wallet_available = int(wallet_payload.get("points_balance") or 0)
                total_available = trial_available + wallet_available
                if total_points > total_available:
                    raise ValueError(
                        f"交易資金不足：需要 {total_points} 點，目前可用 {total_available} 點"
                        f"（體驗金 {trial_available} + 真實積分 {wallet_available}）"
                    )
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
                            "fee_rate_percent": effective_fee_rate_percent,
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
                self._audit_event(conn, event_type, message, actor=actor, target_user_id=user_id, order_id=order_id, market_symbol=market["symbol"], severity="warning" if emergency_close else "info", metadata={"fill_id": fill["id"], "price_source": price_source, "execution_price_points": execution_price, "fee_rate_percent": effective_fee_rate_percent})
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
        effective_fee_rate_percent = float(market["fee_rate_percent"] or 0) * (2 if emergency_close else 1)
        fee = fee_points(notional, effective_fee_rate_percent)
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
            buy_fee_estimate = fee_points(gross_cost, float(market["fee_rate_percent"] or 0)) if gross_cost else 0
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
            min_collateral = self._minimum_margin_collateral_points(conn, position_type=position_type, notional=notional)
            if collateral < min_collateral:
                raise ValueError(f"collateral below minimum {min_collateral}")
            fee = fee_points(notional, float(market["fee_rate_percent"] or 0))
            principal = max(0, notional - collateral) if position_type == "margin_long" else notional
            position_uuid = str(uuid.uuid4())
            ledger_uuids = []
            is_root_simulated = self._is_root_actor(actor)
            if is_root_simulated:
                self._sim_delta(conn, user_id, balance_delta=-(collateral + fee), locked_delta=collateral)
                trial_fee = 0
                chain_fee = 0
                trial_collateral = 0
                chain_collateral = 0
            else:
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
                        "fee_rate_percent": float(market["fee_rate_percent"] or 0),
                        "trial_fee_points": trial_fee,
                        "chain_fee_points": chain_fee,
                    },
                    actor=actor,
                )["ledger_uuid"])
            if fee and not is_root_simulated:
                self._reserve_delta(conn, delta=fee, event_type="margin_fee_retained", reason="TRADING_MARGIN_OPEN_FEE", actor=actor)
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO trading_margin_positions (
                    position_uuid, user_id, market_symbol, position_type, quantity_units,
                    entry_price_points, principal_points, collateral_points, open_fee_points,
                    interest_percent_daily, status, opened_at, updated_at,
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
                    float(borrow_settings["interest_percent_daily"]),
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
                    "funding_mode": "root_simulated" if is_root_simulated else ("trial_mixed" if (trial_collateral or trial_fee) else "points_chain"),
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

    def add_margin_collateral(self, *, actor, position_uuid, amount_points, idempotency_key=None):
        actor_user_id = self._actor_id(actor)
        if not actor_user_id:
            raise ValueError("login required")
        amount = _to_int(amount_points, name="collateral_points", minimum=1, maximum=10**12)
        fallback_key = idempotency_key or f"{position_uuid}:{amount}:{int(datetime.now().timestamp() // 60)}"
        operation_key = _client_idempotency_key(
            fallback_key,
            prefix=f"margin_collateral_add:{actor_user_id}:{position_uuid}",
        )
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            if operation_key:
                existing_operation = conn.execute(
                    """
                    SELECT response_json FROM trading_operation_idempotency
                    WHERE idempotency_key=? AND operation='margin_collateral_add'
                    """,
                    (operation_key,),
                ).fetchone()
                if existing_operation and existing_operation["response_json"]:
                    result = _json_loads(existing_operation["response_json"], {"ok": True})
                    conn.rollback()
                    return result
                insert_cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO trading_operation_idempotency (
                        idempotency_key, operation, user_id, reference_uuid, response_json, created_at, updated_at
                    ) VALUES (?, 'margin_collateral_add', ?, ?, '', ?, ?)
                    """,
                    (operation_key, int(actor_user_id), str(position_uuid or ""), _now(), _now()),
                )
                if insert_cur.rowcount == 0:
                    existing_operation = conn.execute(
                        "SELECT response_json FROM trading_operation_idempotency WHERE idempotency_key=?",
                        (operation_key,),
                    ).fetchone()
                    if existing_operation and existing_operation["response_json"]:
                        result = _json_loads(existing_operation["response_json"], {"ok": True})
                        conn.rollback()
                        return result
                    raise ValueError("duplicate margin collateral request is still processing")
            position = conn.execute(
                "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
                (str(position_uuid or ""),),
            ).fetchone()
            if not position:
                raise ValueError("margin position not found")
            user_id = int(position["user_id"])
            if int(user_id) != int(actor_user_id):
                raise ValueError("cannot update another user's margin position")
            if position["status"] != "open":
                raise ValueError("margin position is not open")
            is_root_simulated = self._is_root_user_id(conn, user_id)
            ledger_uuids = []
            trial_added = 0
            chain_added = 0
            if is_root_simulated:
                self._sim_delta(conn, user_id, balance_delta=-amount, locked_delta=amount)
            else:
                trial_added = self._trial_deploy(conn, user_id, amount)
                chain_added = amount - trial_added
                if chain_added:
                    ledger_uuids.append(self._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="freeze",
                        amount=chain_added,
                        action_type="trading_margin_collateral_freeze",
                        reference_type="trading_margin_position",
                        reference_id=position["position_uuid"],
                        idempotency_key=f"trading:margin:collateral_add:{operation_key}",
                        reason="TRADING_MARGIN_COLLATERAL_ADD",
                        public_metadata={
                            "position_type": position["position_type"],
                            "market": position["market_symbol"],
                            "trial_collateral_points": trial_added,
                            "chain_collateral_points": chain_added,
                        },
                        actor=actor,
                    )["ledger_uuid"])
            now = _now()
            conn.execute(
                """
                UPDATE trading_margin_positions
                SET collateral_points=collateral_points+?,
                    collateral_trial_points=collateral_trial_points+?,
                    collateral_chain_points=collateral_chain_points+?,
                    updated_at=?
                WHERE id=?
                """,
                (amount, trial_added, chain_added, now, position["id"]),
            )
            self._audit_event(
                conn,
                "TRADING_MARGIN_COLLATERAL_ADDED",
                "margin collateral added",
                actor=actor,
                target_user_id=user_id,
                market_symbol=position["market_symbol"],
                metadata={
                    "position_id": position["id"],
                    "position_uuid": position["position_uuid"],
                    "amount_points": amount,
                    "funding_mode": "root_simulated" if is_root_simulated else ("trial_mixed" if trial_added else "points_chain"),
                    "trial_collateral_points": trial_added,
                    "chain_collateral_points": chain_added,
                    "ledger_uuids": ledger_uuids,
                },
            )
            row = conn.execute("SELECT * FROM trading_margin_positions WHERE id=?", (position["id"],)).fetchone()
            result = {
                "ok": True,
                "position": self._margin_position_payload_with_risk(conn, row),
                "funding": self._funding_payload(conn, user_id),
            }
            if operation_key:
                conn.execute(
                    """
                    UPDATE trading_operation_idempotency
                    SET response_json=?, updated_at=?
                    WHERE idempotency_key=?
                    """,
                    (_json_dumps(result), _now(), operation_key),
                )
            conn.commit()
            return result
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
            is_root_simulated = self._is_root_user_id(conn, user_id)
            if is_root_simulated:
                simulated_return = max(0, collateral + delta)
                self._sim_delta(conn, user_id, balance_delta=simulated_return, locked_delta=-collateral)
                if collateral + delta < 0:
                    self._audit_event(
                        conn,
                        "TRADING_ROOT_SIM_MARGIN_BAD_DEBT",
                        "root simulated margin position closed below collateral",
                        actor=actor,
                        target_user_id=user_id,
                        market_symbol=market["symbol"],
                        severity="warning",
                        metadata={"position_uuid": position["position_uuid"], "simulated_bad_debt_points": abs(collateral + delta), "risk": risk},
                    )
            elif collateral_chain:
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
            if is_root_simulated:
                pass
            elif delta > 0:
                if collateral_trial:
                    self._release_trial_margin_collateral(
                        conn,
                        user_id,
                        collateral_trial=collateral_trial,
                        available_delta_if_active=collateral_trial,
                    )
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
                    self._release_trial_margin_collateral(
                        conn,
                        user_id,
                        collateral_trial=collateral_trial,
                        available_delta_if_active=trial_return,
                    )
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
                self._release_trial_margin_collateral(
                    conn,
                    user_id,
                    collateral_trial=collateral_trial,
                    available_delta_if_active=collateral_trial,
                )
            if close_fee and not is_root_simulated:
                self._reserve_delta(conn, delta=close_fee, event_type="margin_fee_retained", reason="TRADING_MARGIN_CLOSE_FEE", actor=actor)
            if interest and not is_root_simulated:
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
                    "funding_mode": "root_simulated" if is_root_simulated else ("trial_mixed" if collateral_trial else "points_chain"),
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

    def update_market(self, *, actor, symbol, manual_price_points=None, max_price_jump_percent=None, fee_rate_percent=None, min_order_points=None, max_order_points=None, enabled=None, confirm_jump=False):
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
                jump_percent = float(abs(new_price - old_price) * 100 / old_price) if old_price else 0.0
                allowed_percent = float(market["max_price_jump_percent"] or 0)
                if jump_percent > allowed_percent and not confirm_jump:
                    raise ValueError(f"price jump {jump_percent:.2f}% exceeds max {allowed_percent:.2f}%; confirmation required")
                updates["manual_price_points"] = new_price
                updates["price_source"] = "manual_root"
            for key, value, max_value in (
                ("max_price_jump_percent", max_price_jump_percent, 1000.0),
                ("fee_rate_percent", fee_rate_percent, 50.0),
                ("min_order_points", min_order_points, 10**9),
                ("max_order_points", max_order_points, 10**12),
            ):
                if value is not None:
                    if key in {"max_price_jump_percent", "fee_rate_percent"}:
                        updates[key] = _to_float(value, name=key, minimum=0, maximum=max_value)
                    else:
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
            settings = self._settings_payload(conn)
            if not settings.get("futures_enabled") or not int(market["futures_enabled"] or 0):
                raise ValueError("contract trading is disabled")
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
                "bots": int(conn.execute("SELECT COUNT(*) FROM trading_bots WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            }
            conn.execute("DELETE FROM trading_bot_runs WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM trading_bots WHERE user_id=?", (user_id,))
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
        for position in conn.execute(
            """
            SELECT p.user_id, p.collateral_points
            FROM trading_margin_positions p
            JOIN users u ON u.id=p.user_id
            WHERE u.username='root'
              AND p.status='open'
            """
        ).fetchall():
            user_id = int(position["user_id"])
            expected_locked[user_id] = expected_locked.get(user_id, 0) + int(position["collateral_points"] or 0)
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
        root_user_ids = {
            int(row["id"])
            for row in conn.execute("SELECT id FROM users WHERE username='root'").fetchall()
        }
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
            user_id = int(position["user_id"])
            is_root_simulated = user_id in root_user_ids
            collateral_points = int(position["collateral_points"] or 0)
            collateral_trial = int(position["collateral_trial_points"] or 0) if "collateral_trial_points" in position.keys() else 0
            collateral_chain = int(position["collateral_chain_points"] or 0) if "collateral_chain_points" in position.keys() else collateral_points
            split_total = collateral_trial + collateral_chain
            if not is_root_simulated and collateral_points != split_total:
                errors.append({
                    "type": "margin_collateral_lock_mismatch",
                    "position_id": position["id"],
                    "position_uuid": position_uuid,
                    "status": position["status"],
                    "expected_collateral_points": split_total,
                    "actual_collateral_points": collateral_points,
                })
            expected = 0 if is_root_simulated else (int(position["collateral_chain_points"] or 0) if position["status"] == "open" else 0)
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
