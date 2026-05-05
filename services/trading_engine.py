import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.notifications import create_notification_if_enabled, create_root_notification_if_enabled
from services.trading_markets import (
    list_live_price_markets,
    list_seed_markets,
    market_display_symbol,
    market_provider_id,
    market_sort_key,
    market_supports_btc_trade,
    market_supports_live_price,
    normalize_market_symbol,
)


ASSET_SCALE = 100_000_000
POINT_MICRO_SCALE = 1_000_000
USDT_TO_POINTS_RATE = 1
ROOT_SIMULATED_INITIAL_POINTS = 10_000
TRIAL_CREDIT_INITIAL_POINTS = 1_000
TRIAL_CREDIT_DAYS = 7
TRADING_FUNDING_POOL_INITIAL_POINTS = 10_000
TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER = 4.0
MARGIN_LONG_FINANCING_RATE_PERCENT = 90.0
SHORT_COLLATERAL_RATE_PERCENT = 60.0
SUPPORTED_EXECUTION_MODES = {"house_counterparty", "pvp_matching", "hybrid_liquidity"}
OPEN_ORDER_STATUSES = {"open", "partially_filled"}
TRADING_BOT_TRIGGER_TYPES = {"always", "price_above", "price_below"}
TRADING_BOT_TYPES = {"conditional", "dca"}
BACKTEST_SEGMENT_CANDLES = 10_000
MAX_BACKTEST_CANDLES = 20_000
TRADING_BOT_AUDIT_INTERVAL_SECONDS = 300
TRADING_BOT_AUDIT_LIMIT = 50
TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS = 86_400
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
BINANCE_DEPTH_URL = "https://api.binance.com/api/v3/depth"
OKX_BOOKS_URL = "https://www.okx.com/api/v5/market/books"
COINBASE_BOOK_URL_TEMPLATE = "https://api.exchange.coinbase.com/products/{product_id}/book"
KRAKEN_DEPTH_URL = "https://api.kraken.com/0/public/Depth"
GEMINI_BOOK_URL_TEMPLATE = "https://api.gemini.com/v1/book/{symbol}"
BITSTAMP_ORDER_BOOK_URL_TEMPLATE = "https://www.bitstamp.net/api/v2/order_book/{pair}/"
FUSED_PRICE_SOURCE = "fused_weighted"
PRICE_FUSION_MODES = {"auto_depth", "manual_weights"}
WEIGHTED_PRICE_PROVIDERS = (
    "binance_public_api",
    "okx_public_api",
    "coinbase_exchange",
    "kraken_public_api",
    "gemini_public_api",
    "bitstamp_public_api",
)
PRICE_PROVIDER_LABELS = {
    "binance_public_api": "Binance",
    "okx_public_api": "OKX",
    "coinbase_exchange": "Coinbase",
    "kraken_public_api": "Kraken",
    "gemini_public_api": "Gemini",
    "bitstamp_public_api": "Bitstamp",
    "coingecko_simple_price": "CoinGecko",
}
DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS = {
    "binance_public_api": 40.0,
    "okx_public_api": 25.0,
    "coinbase_exchange": 15.0,
    "kraken_public_api": 10.0,
    "bitstamp_public_api": 8.0,
    "gemini_public_api": 2.0,
}
DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT = 1.0
DEFAULT_PRICE_FUSION_DEPTH_LEVELS = 100
MAX_PRICE_FUSION_DEPTH_LEVELS = 1000
DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT = 0.5
DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT = 40.0
DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS = 15
DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS = 2500
DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT = 0.50
DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO = 0.10
DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT = 3
DEFAULT_SPOT_FEE_RATE_PERCENT = 0.10
DEFAULT_GRID_FEE_DISCOUNT_PERCENT = 25.0
GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT = Decimal("0.10")
DEFAULT_BORROW_APR_BTC_ETH_PERCENT = 8.0
DEFAULT_BORROW_APR_USDT_POINTS_PERCENT = 10.0
DEFAULT_BORROW_INTEREST_INTERVAL_HOURS = 1
DEFAULT_BORROW_INTEREST_MINIMUM_HOURS = 1
APR_DAYS_PER_YEAR = Decimal("365")
UNLIMITED_BOT_MAX_RUNS = 2_147_483_647
LIVE_PRICE_SOURCE_NAMES = {
    FUSED_PRICE_SOURCE,
    "binance_public_api",
    "okx_public_api",
    "coinbase_exchange",
    "kraken_public_api",
    "gemini_public_api",
    "bitstamp_public_api",
    "coingecko_simple_price",
    "test_live_price_provider",
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


def _to_decimal(value, *, name, minimum=None, maximum=None):
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and number < Decimal(str(minimum)):
        raise ValueError(f"{name} out of range")
    if maximum is not None and number > Decimal(str(maximum)):
        raise ValueError(f"{name} out of range")
    return number


def _to_price_float(value, *, name, minimum=0.00000001, maximum=10**12):
    return float(
        _to_decimal(value, name=name, minimum=minimum, maximum=maximum).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_HALF_UP,
        )
    )


def _decimal_text(value, *, places="0.00000001"):
    dec = Decimal(str(value or 0)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    text = format(dec, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _normalize_price_fusion_manual_weights(raw):
    out = {}
    source = raw if isinstance(raw, dict) else {}
    for provider in WEIGHTED_PRICE_PROVIDERS:
        value = source.get(provider, DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS.get(provider, 1.0))
        try:
            number = float(value)
        except Exception:
            number = DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS.get(provider, 1.0)
        if not math.isfinite(number):
            number = DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS.get(provider, 1.0)
        out[provider] = max(0.0, min(number, 1000.0))
    return out


def _median_float(values):
    numbers = sorted(float(value) for value in (values or []))
    if not numbers:
        return 0.0
    middle = len(numbers) // 2
    if len(numbers) % 2:
        return numbers[middle]
    return (numbers[middle - 1] + numbers[middle]) / 2.0


def _bot_max_runs_from_storage(value):
    number = int(value or 0)
    return -1 if number >= UNLIMITED_BOT_MAX_RUNS else number


def _bot_max_runs_to_storage(value, *, allow_unlimited=False, maximum=1000):
    raw = str(value).strip() if value is not None else ""
    if allow_unlimited and raw == "-1":
        return UNLIMITED_BOT_MAX_RUNS
    return _to_int(value, name="max_runs", minimum=1, maximum=maximum)


def _bot_max_runs_has_remaining(run_count, max_runs):
    max_runs = int(max_runs or 0)
    if max_runs >= UNLIMITED_BOT_MAX_RUNS:
        return True
    return int(run_count or 0) < max_runs


def _borrow_apr_group_for_asset(asset_symbol):
    asset = str(asset_symbol or "").strip().upper()
    if asset in {"BTC", "ETH"}:
        return "btc_eth"
    return "usdt_points"


def _daily_percent_from_apr(apr_percent):
    dec = Decimal(str(apr_percent or 0))
    if dec <= 0:
        return 0.0
    return float((dec / APR_DAYS_PER_YEAR).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _apr_percent_from_daily(daily_percent):
    dec = Decimal(str(daily_percent or 0))
    if dec <= 0:
        return 0.0
    return float((dec * APR_DAYS_PER_YEAR).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _normalize_borrow_interest_timing(interval_hours=None, minimum_hours=None):
    interval = int(interval_hours or DEFAULT_BORROW_INTEREST_INTERVAL_HOURS)
    minimum = int(minimum_hours or DEFAULT_BORROW_INTEREST_MINIMUM_HOURS)
    interval = max(1, min(interval, 168))
    minimum = max(1, min(minimum, 168))
    return interval, minimum


def _billable_interest_hours_from_elapsed_seconds(seconds, *, interval_hours=1, minimum_hours=1):
    seconds = max(0.0, float(seconds or 0))
    interval_hours, minimum_hours = _normalize_borrow_interest_timing(interval_hours, minimum_hours)
    if seconds <= 0:
        return 0
    interval_seconds = interval_hours * 3600.0
    billed_hours = int(math.ceil(seconds / interval_seconds)) * interval_hours
    return max(minimum_hours, billed_hours)


def quantity_to_units(value):
    try:
        dec = Decimal(str(value or "")).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("quantity must be a positive number") from exc
    if not dec.is_finite():
        raise ValueError("quantity must be a positive number")
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


def _condition_label(cond):
    if not isinstance(cond, dict):
        return str(cond)
    if "AND" in cond:
        parts = cond["AND"] if isinstance(cond["AND"], list) else []
        return "AND(" + ", ".join(_condition_label(p) for p in parts) + ")"
    if "OR" in cond:
        parts = cond["OR"] if isinstance(cond["OR"], list) else []
        return "OR(" + ", ".join(_condition_label(p) for p in parts) + ")"
    if "NOT" in cond:
        return "NOT(" + _condition_label(cond["NOT"]) + ")"
    ctype = str(cond.get("type") or "always")
    value = cond.get("value")
    period = cond.get("period")
    position = cond.get("position")
    labels = {
        "always": "無條件", "price_above": f"價格≥{value}", "price_below": f"價格≤{value}",
        "rsi_above": f"RSI≥{value}", "rsi_below": f"RSI≤{value}",
        "kd_above": f"KD≥{value}", "kd_below": f"KD≤{value}",
        "ma_position": f"MA{period}{' 上方' if position == 'above' else ' 下方'}",
        "bb_position": f"BB {position}", "has_position": f"持倉={'是' if value else '否'}",
        "stop_loss_percent": f"止損≤-{value}%", "take_profit_percent": f"止盈≥{value}%",
    }
    return labels.get(ctype, ctype)


def notional_points(quantity_units, price_points):
    quantity_units = int(quantity_units)
    if quantity_units <= 0:
        return 0
    price_decimal = _to_decimal(price_points, name="price_points", minimum=0)
    exact_notional = (Decimal(quantity_units) * price_decimal) / Decimal(ASSET_SCALE)
    if exact_notional <= 0:
        return 0
    return int(exact_notional.quantize(Decimal("1"), rounding=ROUND_CEILING))


def fee_points(notional, fee_rate_percent):
    exact_fee = (Decimal(int(notional or 0)) * Decimal(str(fee_rate_percent or 0))) / Decimal("100")
    if exact_fee <= 0:
        return 0
    return int(exact_fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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
            fee_rate_percent REAL NOT NULL DEFAULT 0.1,
            updated_at TEXT NOT NULL,
            updated_by INTEGER,
            price_source TEXT NOT NULL DEFAULT 'fused_weighted',
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
            exit_price_points INTEGER,
            realized_pnl_points INTEGER NOT NULL DEFAULT 0,
            interest_percent_daily REAL NOT NULL DEFAULT 0,
            interest_points INTEGER NOT NULL DEFAULT 0,
            interest_paid_points INTEGER NOT NULL DEFAULT 0,
            interest_accrued_hours INTEGER NOT NULL DEFAULT 0,
            interest_carry_micropoints INTEGER NOT NULL DEFAULT 0,
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
        CREATE TABLE IF NOT EXISTS trading_user_volume_stats (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            total_notional_points INTEGER NOT NULL DEFAULT 0 CHECK (total_notional_points >= 0),
            spot_notional_points INTEGER NOT NULL DEFAULT 0 CHECK (spot_notional_points >= 0),
            margin_notional_points INTEGER NOT NULL DEFAULT 0 CHECK (margin_notional_points >= 0),
            total_fee_points INTEGER NOT NULL DEFAULT 0 CHECK (total_fee_points >= 0),
            total_trade_count INTEGER NOT NULL DEFAULT 0 CHECK (total_trade_count >= 0),
            last_trade_at TEXT,
            updated_at TEXT NOT NULL
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
            enabled_at TEXT,
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_grid_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            market_symbol TEXT NOT NULL REFERENCES trading_markets(symbol),
            upper_price_points INTEGER NOT NULL CHECK (upper_price_points > 0),
            lower_price_points INTEGER NOT NULL CHECK (lower_price_points > 0),
            grid_count INTEGER NOT NULL CHECK (grid_count >= 2 AND grid_count <= 200),
            order_amount_points INTEGER NOT NULL CHECK (order_amount_points > 0),
            enabled INTEGER NOT NULL DEFAULT 1,
            total_profit_points INTEGER NOT NULL DEFAULT 0,
            total_trades INTEGER NOT NULL DEFAULT 0,
            initial_price_points INTEGER NOT NULL DEFAULT 0,
            grid_levels_json TEXT,
            last_scan_at TEXT,
            last_error TEXT,
            enabled_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (upper_price_points > lower_price_points)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_grid_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_uuid TEXT NOT NULL UNIQUE,
            grid_bot_id INTEGER NOT NULL REFERENCES trading_grid_bots(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            level_index INTEGER NOT NULL,
            price_points INTEGER NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            trading_order_uuid TEXT,
            filled_quantity_units INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_bot_audit_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uuid TEXT NOT NULL UNIQUE,
            bot_kind TEXT NOT NULL CHECK (bot_kind IN ('trading_bot', 'grid_bot')),
            bot_uuid TEXT NOT NULL,
            bot_id INTEGER,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            market_symbol TEXT NOT NULL,
            audit_status TEXT NOT NULL CHECK (audit_status IN ('green', 'yellow', 'red')),
            eligible_reason TEXT NOT NULL,
            findings_json TEXT,
            finding_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            blocker_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_bot_audit_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES trading_bot_audit_runs(id) ON DELETE CASCADE,
            severity TEXT NOT NULL CHECK (severity IN ('warning', 'blocker')),
            code TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    now = _now()
    conn.execute(
        "INSERT OR IGNORE INTO trading_reserve_pool (id, balance_points, updated_at) VALUES (1, 0, ?)",
        (now,),
    )
    initial_event = conn.execute(
        "SELECT 1 FROM trading_reserve_pool_events WHERE event_type='initial_funding' LIMIT 1"
    ).fetchone()
    if not initial_event:
        reserve = conn.execute("SELECT * FROM trading_reserve_pool WHERE id=1").fetchone()
        balance = int(reserve["balance_points"] or 0) if reserve else 0
        next_balance = balance + TRADING_FUNDING_POOL_INITIAL_POINTS
        conn.execute(
            "UPDATE trading_reserve_pool SET balance_points=?, updated_at=?, updated_by=NULL WHERE id=1",
            (next_balance, now),
        )
        conn.execute(
            """
            INSERT INTO trading_reserve_pool_events (
                event_uuid, delta_points, balance_after, event_type, reason,
                actor_user_id, source_user_id, order_id, fill_id, points_ledger_uuid, created_at
            ) VALUES (?, ?, ?, 'initial_funding', 'TRADING_FUNDING_POOL_INITIAL', NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (str(uuid.uuid4()), TRADING_FUNDING_POOL_INITIAL_POINTS, next_balance, now),
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
        conn.execute("ALTER TABLE trading_markets ADD COLUMN fee_rate_percent REAL NOT NULL DEFAULT 0.1")
        if legacy_fee_col in market_cols:
            conn.execute(f"UPDATE trading_markets SET fee_rate_percent=CAST({legacy_fee_col} AS REAL) / 100.0")
    conn.execute(
        """
        UPDATE trading_markets
        SET fee_rate_percent=?, updated_at=?
        WHERE ABS(COALESCE(fee_rate_percent, 0) - 0.3) < 0.0000001
          AND updated_by IS NULL
        """,
        (DEFAULT_SPOT_FEE_RATE_PERCENT, now),
    )
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
        ("trading.borrow_interest_percent_daily", str(_daily_percent_from_apr(DEFAULT_BORROW_APR_USDT_POINTS_PERCENT))),
        ("trading.borrow_apr_btc_eth_percent", str(DEFAULT_BORROW_APR_BTC_ETH_PERCENT)),
        ("trading.borrow_apr_usdt_points_percent", str(DEFAULT_BORROW_APR_USDT_POINTS_PERCENT)),
        ("trading.borrow_interest_pool_pressure_multiplier", str(TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER)),
        ("trading.borrow_interest_interval_hours", str(DEFAULT_BORROW_INTEREST_INTERVAL_HOURS)),
        ("trading.borrow_interest_minimum_hours", str(DEFAULT_BORROW_INTEREST_MINIMUM_HOURS)),
        ("trading.margin_long_financing_percent", str(MARGIN_LONG_FINANCING_RATE_PERCENT)),
        ("trading.short_collateral_percent", str(SHORT_COLLATERAL_RATE_PERCENT)),
        ("trading.margin_liquidation_enabled", "true"),
        ("trading.margin_maintenance_percent", "15"),
        ("trading.grid_fee_discount_percent", str(DEFAULT_GRID_FEE_DISCOUNT_PERCENT)),
        ("trading.max_price_staleness_seconds", "900"),
        ("trading.price_source", FUSED_PRICE_SOURCE),
        ("trading.price_fusion_mode", "auto_depth"),
        ("trading.price_fusion_manual_weights_json", _json_dumps(DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS)),
        ("trading.price_fusion_depth_band_percent", str(DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT)),
        ("trading.price_fusion_depth_levels", str(DEFAULT_PRICE_FUSION_DEPTH_LEVELS)),
        ("trading.price_fusion_min_orderbook_coverage_percent", str(DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT)),
        ("trading.price_fusion_max_single_provider_weight_percent", str(DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT)),
        ("trading.price_fusion_min_provider_count", str(DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT)),
        ("trading.btc_trade_enabled", "false"),
        ("trading.btc_trade_repo_url", "https://github.com/s9213712/BTC_trade.git"),
        ("trading.btc_trade_branch", "strategy/v15b-plus"),
        ("trading.bot_auto_scan_enabled", "true"),
        ("trading.bot_auto_scan_interval_seconds", "30"),
        ("trading.bot_auto_scan_limit", "50"),
    ]
    for key, value in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO trading_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
    for definition in list_seed_markets():
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_markets (
                symbol, base_asset, quote_currency, manual_price_points, fee_rate_percent, updated_at, price_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                definition["symbol"],
                definition["base_asset"],
                definition.get("quote_currency") or "POINTS",
                definition.get("default_manual_price_points") or 1,
                DEFAULT_SPOT_FEE_RATE_PERCENT,
                now,
                FUSED_PRICE_SOURCE,
            ),
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
    if "interest_paid_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN interest_paid_points INTEGER NOT NULL DEFAULT 0")
    if "interest_accrued_hours" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN interest_accrued_hours INTEGER NOT NULL DEFAULT 0")
    if "interest_carry_micropoints" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN interest_carry_micropoints INTEGER NOT NULL DEFAULT 0")
    if "interest_interval_hours" not in margin_cols:
        conn.execute(
            f"ALTER TABLE trading_margin_positions ADD COLUMN interest_interval_hours INTEGER NOT NULL DEFAULT {DEFAULT_BORROW_INTEREST_INTERVAL_HOURS}"
        )
    if "interest_minimum_hours" not in margin_cols:
        conn.execute(
            f"ALTER TABLE trading_margin_positions ADD COLUMN interest_minimum_hours INTEGER NOT NULL DEFAULT {DEFAULT_BORROW_INTEREST_MINIMUM_HOURS}"
        )
    if "borrowed_asset_symbol" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN borrowed_asset_symbol TEXT NOT NULL DEFAULT 'POINTS'")
    if "exit_price_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN exit_price_points INTEGER")
    if "realized_pnl_points" not in margin_cols:
        conn.execute("ALTER TABLE trading_margin_positions ADD COLUMN realized_pnl_points INTEGER NOT NULL DEFAULT 0")
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
    if "enabled_at" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN enabled_at TEXT")
        conn.execute("UPDATE trading_bots SET enabled_at=COALESCE(created_at, updated_at) WHERE enabled=1 AND COALESCE(enabled_at, '')=''")
    if "last_scan_at" not in bot_cols:
        conn.execute("ALTER TABLE trading_bots ADD COLUMN last_scan_at TEXT")
    grid_bot_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_grid_bots)").fetchall()}
    if "enabled_at" not in grid_bot_cols:
        conn.execute("ALTER TABLE trading_grid_bots ADD COLUMN enabled_at TEXT")
        conn.execute("UPDATE trading_grid_bots SET enabled_at=COALESCE(created_at, updated_at) WHERE enabled=1 AND COALESCE(enabled_at, '')=''")


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

    def _actor_role(self, actor):
        try:
            return str(actor.get("role") if hasattr(actor, "get") else actor["role"]) or "user"
        except Exception:
            return "user"

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
        row = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (normalize_market_symbol(symbol),)).fetchone()
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

    def _funding_pool_outstanding_principal(self, conn):
        lent = int(conn.execute(
            """
            SELECT COALESCE(SUM(delta_points), 0)
            FROM trading_reserve_pool_events
            WHERE event_type='margin_principal_lent'
            """
        ).fetchone()[0] or 0)
        repaid = int(conn.execute(
            """
            SELECT COALESCE(SUM(delta_points), 0)
            FROM trading_reserve_pool_events
            WHERE event_type='margin_principal_repaid'
            """
        ).fetchone()[0] or 0)
        return max(0, abs(lent) - repaid)

    def _borrow_apr_percent_for_asset(self, settings, *, asset_symbol):
        group = _borrow_apr_group_for_asset(asset_symbol)
        if group == "btc_eth":
            return float(settings.get("borrow_apr_btc_eth_percent") or DEFAULT_BORROW_APR_BTC_ETH_PERCENT)
        return float(settings.get("borrow_apr_usdt_points_percent") or DEFAULT_BORROW_APR_USDT_POINTS_PERCENT)

    def _margin_borrowed_asset_symbol(self, market, position_type):
        market_row = dict(market) if market is not None and not isinstance(market, dict) else (market or {})
        if str(position_type or "").strip().lower() == "short":
            return str(market_row.get("base_asset") or "").strip().upper() or "BTC"
        return str(market_row.get("quote_currency") or "POINTS").strip().upper() or "POINTS"

    def _grid_fee_rate_percent(self, base_fee_rate_percent, settings):
        discount = float(settings.get("grid_fee_discount_percent") or DEFAULT_GRID_FEE_DISCOUNT_PERCENT)
        discount = max(0.0, min(discount, 100.0))
        return max(0.0, float(base_fee_rate_percent or 0) * ((100.0 - discount) / 100.0))

    def _funding_pool_payload(self, conn, *, requested_principal=0, borrowed_asset=None):
        reserve = self._reserve(conn)
        settings = self._settings_payload(conn)
        balance = int(reserve["balance_points"] or 0)
        outstanding = self._funding_pool_outstanding_principal(conn)
        requested = max(0, int(requested_principal or 0))
        capacity = max(0, balance + outstanding)
        projected_balance = max(0, balance - requested)
        projected_outstanding = outstanding + requested
        projected_capacity = max(0, projected_balance + projected_outstanding)
        utilization = (outstanding / capacity) if capacity > 0 else 0.0
        projected_utilization = (projected_outstanding / projected_capacity) if projected_capacity > 0 else 1.0
        borrowed_asset = str(borrowed_asset or "POINTS").strip().upper() or "POINTS"
        base_apr = self._borrow_apr_percent_for_asset(settings, asset_symbol=borrowed_asset)
        base_rate = _daily_percent_from_apr(base_apr)
        raw_pressure = settings.get("borrow_interest_pool_pressure_multiplier")
        pressure = float(TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER if raw_pressure is None else raw_pressure)
        effective_rate = base_rate * (1.0 + max(0.0, utilization) * max(0.0, pressure))
        projected_rate = base_rate * (1.0 + max(0.0, projected_utilization) * max(0.0, pressure))
        return {
            "name": "資金池",
            "initial_points": TRADING_FUNDING_POOL_INITIAL_POINTS,
            "balance_points": balance,
            "available_points": balance,
            "outstanding_principal_points": outstanding,
            "capacity_points": capacity,
            "utilization_percent": round(utilization * 100, 4),
            "projected_utilization_percent": round(projected_utilization * 100, 4),
            "borrowed_asset_symbol": borrowed_asset,
            "base_interest_apr_percent": round(base_apr, 8),
            "effective_interest_apr_percent": round(_apr_percent_from_daily(effective_rate), 8),
            "projected_interest_apr_percent": round(_apr_percent_from_daily(projected_rate), 8),
            "base_interest_percent_daily": round(base_rate, 8),
            "interest_pool_pressure_multiplier": round(pressure, 8),
            "effective_interest_percent_daily": round(effective_rate, 8),
            "projected_interest_percent_daily": round(projected_rate, 8),
        }

    def _reserve_delta(self, conn, *, delta, event_type, reason, actor=None, source_user_id=None, order_id=None, fill_id=None, points_ledger_uuid=None):
        reserve = self._reserve(conn)
        balance = int(reserve["balance_points"] or 0)
        next_balance = balance + int(delta)
        if next_balance < 0:
            raise ValueError("trading funding pool is insufficient")
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

    def _user_volume_stats(self, conn, user_id):
        user_id = int(user_id)
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_user_volume_stats (
                user_id, total_notional_points, spot_notional_points, margin_notional_points,
                total_fee_points, total_trade_count, last_trade_at, updated_at
            ) VALUES (?, 0, 0, 0, 0, 0, NULL, ?)
            """,
            (user_id, now),
        )
        return conn.execute("SELECT * FROM trading_user_volume_stats WHERE user_id=?", (user_id,)).fetchone()

    def _record_user_trade_volume(self, conn, *, user_id, trade_kind, notional_points, fee_points=0, occurred_at=None):
        user_id = int(user_id)
        notional_points = max(0, int(notional_points or 0))
        fee_points = max(0, int(fee_points or 0))
        now = str(occurred_at or _now())
        current = self._user_volume_stats(conn, user_id)
        total_notional = int(current["total_notional_points"] or 0) + notional_points
        spot_notional = int(current["spot_notional_points"] or 0) + (notional_points if trade_kind == "spot" else 0)
        margin_notional = int(current["margin_notional_points"] or 0) + (notional_points if trade_kind == "margin" else 0)
        total_fee = int(current["total_fee_points"] or 0) + fee_points
        total_trade_count = int(current["total_trade_count"] or 0) + 1
        conn.execute(
            """
            UPDATE trading_user_volume_stats
            SET total_notional_points=?, spot_notional_points=?, margin_notional_points=?,
                total_fee_points=?, total_trade_count=?, last_trade_at=?, updated_at=?
            WHERE user_id=?
            """,
            (
                total_notional,
                spot_notional,
                margin_notional,
                total_fee,
                total_trade_count,
                now,
                now,
                user_id,
            ),
        )
        return conn.execute("SELECT * FROM trading_user_volume_stats WHERE user_id=?", (user_id,)).fetchone()

    def _order_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["filled_quantity"] = units_to_quantity(item["filled_quantity_units"])
        return item

    def _bot_payload(self, row):
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["max_runs"] = _bot_max_runs_from_storage(item.get("max_runs"))
        item["can_run"] = bool(item["enabled"]) and _bot_max_runs_has_remaining(item.get("run_count"), row["max_runs"])
        item["next_run_at"] = None
        if item["can_run"]:
            try:
                if item.get("last_run_at"):
                    next_dt = datetime.fromisoformat(str(item["last_run_at"])) + timedelta(seconds=int(item.get("cooldown_seconds") or 0))
                    item["next_run_at"] = next_dt.isoformat(timespec="seconds")
                else:
                    item["next_run_at"] = _now()
            except Exception:
                item["next_run_at"] = None
        item["display_symbol"] = market_display_symbol(item.get("market_symbol"))
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
        item["display_symbol"] = market_display_symbol(item.get("symbol"), item.get("quote_currency"))
        item["live_price_supported"] = market_supports_live_price(item.get("symbol"))
        item["btc_trade_supported"] = market_supports_btc_trade(item.get("symbol"))
        return item

    def _settings_payload(self, conn):
        rows = conn.execute("SELECT key, value, updated_at, updated_by FROM trading_settings ORDER BY key").fetchall()
        raw = {row["key"]: row["value"] for row in rows}
        borrow_apr_btc_eth = _to_float(raw.get("trading.borrow_apr_btc_eth_percent", str(DEFAULT_BORROW_APR_BTC_ETH_PERCENT)), name="borrow_apr_btc_eth_percent", minimum=0, maximum=100000)
        borrow_apr_usdt_points = _to_float(raw.get("trading.borrow_apr_usdt_points_percent", str(DEFAULT_BORROW_APR_USDT_POINTS_PERCENT)), name="borrow_apr_usdt_points_percent", minimum=0, maximum=100000)
        borrow_interest_interval_hours = _to_int(raw.get("trading.borrow_interest_interval_hours", str(DEFAULT_BORROW_INTEREST_INTERVAL_HOURS)), name="borrow_interest_interval_hours", minimum=1, maximum=168)
        borrow_interest_minimum_hours = _to_int(raw.get("trading.borrow_interest_minimum_hours", str(DEFAULT_BORROW_INTEREST_MINIMUM_HOURS)), name="borrow_interest_minimum_hours", minimum=1, maximum=168)
        return {
            "enabled": str(raw.get("trading.enabled", "true")).lower() in {"true", "1", "yes"},
            "futures_enabled": str(raw.get("trading.futures_enabled", "false")).lower() in {"true", "1", "yes"},
            "pvp_matching_enabled": str(raw.get("trading.pvp_matching_enabled", "false")).lower() in {"true", "1", "yes"},
            "borrowing_enabled": str(raw.get("trading.borrowing_enabled", "true")).lower() in {"true", "1", "yes"},
            "borrow_apr_btc_eth_percent": borrow_apr_btc_eth,
            "borrow_apr_usdt_points_percent": borrow_apr_usdt_points,
            "borrow_interest_percent_daily": _daily_percent_from_apr(borrow_apr_usdt_points),
            "borrow_interest_pool_pressure_multiplier": _to_float(raw.get("trading.borrow_interest_pool_pressure_multiplier", str(TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER)), name="borrow_interest_pool_pressure_multiplier", minimum=0, maximum=100),
            "borrow_interest_interval_hours": borrow_interest_interval_hours,
            "borrow_interest_minimum_hours": borrow_interest_minimum_hours,
            "margin_long_financing_percent": _to_float(raw.get("trading.margin_long_financing_percent", str(MARGIN_LONG_FINANCING_RATE_PERCENT)), name="margin_long_financing_percent", minimum=0, maximum=100),
            "short_collateral_percent": _to_float(raw.get("trading.short_collateral_percent", str(SHORT_COLLATERAL_RATE_PERCENT)), name="short_collateral_percent", minimum=0, maximum=100),
            "margin_liquidation_enabled": str(raw.get("trading.margin_liquidation_enabled", "true")).lower() in {"true", "1", "yes"},
            "margin_maintenance_percent": _to_float(raw.get("trading.margin_maintenance_percent", "15"), name="margin_maintenance_percent", minimum=0, maximum=100),
            "grid_fee_discount_percent": _to_float(raw.get("trading.grid_fee_discount_percent", str(DEFAULT_GRID_FEE_DISCOUNT_PERCENT)), name="grid_fee_discount_percent", minimum=0, maximum=100),
            "max_price_staleness_seconds": _to_int(raw.get("trading.max_price_staleness_seconds", "900"), name="max_price_staleness_seconds", minimum=0, maximum=86400),
            "price_source": raw.get("trading.price_source", FUSED_PRICE_SOURCE),
            "price_fusion_mode": raw.get("trading.price_fusion_mode", "auto_depth") if raw.get("trading.price_fusion_mode", "auto_depth") in PRICE_FUSION_MODES else "auto_depth",
            "price_fusion_manual_weights": _normalize_price_fusion_manual_weights(_json_loads(raw.get("trading.price_fusion_manual_weights_json"), DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS)),
            "price_fusion_provider_labels": dict(PRICE_PROVIDER_LABELS),
            "price_fusion_providers": list(WEIGHTED_PRICE_PROVIDERS),
            "price_fusion_live_markets": list_live_price_markets(),
            "price_fusion_depth_band_percent": _to_float(raw.get("trading.price_fusion_depth_band_percent", str(DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT)), name="price_fusion_depth_band_percent", minimum=0.1, maximum=10),
            "price_fusion_depth_levels": _to_int(raw.get("trading.price_fusion_depth_levels", str(DEFAULT_PRICE_FUSION_DEPTH_LEVELS)), name="price_fusion_depth_levels", minimum=10, maximum=MAX_PRICE_FUSION_DEPTH_LEVELS),
            "price_fusion_min_orderbook_coverage_percent": _to_float(raw.get("trading.price_fusion_min_orderbook_coverage_percent", str(DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT)), name="price_fusion_min_orderbook_coverage_percent", minimum=0.1, maximum=10),
            "price_fusion_max_single_provider_weight_percent": _to_float(raw.get("trading.price_fusion_max_single_provider_weight_percent", str(DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT)), name="price_fusion_max_single_provider_weight_percent", minimum=0, maximum=100),
            "price_fusion_max_provider_age_seconds": DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS,
            "price_fusion_max_provider_latency_ms": DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS,
            "price_fusion_max_midpoint_deviation_percent": DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT,
            "price_fusion_min_side_balance_ratio_percent": round(DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2),
            "price_fusion_min_provider_count": _to_int(raw.get("trading.price_fusion_min_provider_count", str(DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT)), name="price_fusion_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS)),
            "btc_trade_enabled": str(raw.get("trading.btc_trade_enabled", "false")).lower() in {"true", "1", "yes"},
            "btc_trade_project_dir": raw.get("trading.btc_trade_project_dir", ""),
            "btc_trade_repo_url": raw.get("trading.btc_trade_repo_url", "https://github.com/s9213712/BTC_trade.git"),
            "btc_trade_branch": raw.get("trading.btc_trade_branch", "strategy/v15b-plus"),
            "bot_auto_scan_enabled": str(raw.get("trading.bot_auto_scan_enabled", "true")).lower() in {"true", "1", "yes"},
            "bot_auto_scan_interval_seconds": _to_int(raw.get("trading.bot_auto_scan_interval_seconds", "30"), name="bot_auto_scan_interval_seconds", minimum=10, maximum=3600),
            "bot_auto_scan_limit": _to_int(raw.get("trading.bot_auto_scan_limit", "50"), name="bot_auto_scan_limit", minimum=1, maximum=200),
            "bot_audit_enabled": str(raw.get("trading.bot_audit_enabled", "true")).lower() in {"true", "1", "yes"},
            "bot_audit_interval_seconds": _to_int(raw.get("trading.bot_audit_interval_seconds", str(TRADING_BOT_AUDIT_INTERVAL_SECONDS)), name="bot_audit_interval_seconds", minimum=60, maximum=86400),
            "bot_audit_limit": _to_int(raw.get("trading.bot_audit_limit", str(TRADING_BOT_AUDIT_LIMIT)), name="bot_audit_limit", minimum=1, maximum=200),
            "bot_audit_min_enabled_seconds": _to_int(raw.get("trading.bot_audit_min_enabled_seconds", str(TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS)), name="bot_audit_min_enabled_seconds", minimum=3600, maximum=604800),
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
                "funding_pool": self._funding_pool_payload(conn),
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
                "bot_auto_scan_enabled": "trading.bot_auto_scan_enabled",
                "bot_audit_enabled": "trading.bot_audit_enabled",
                "btc_trade_enabled": "trading.btc_trade_enabled",
            }
            for input_key, storage_key in bool_keys.items():
                if input_key in settings:
                    value = "true" if bool(settings.get(input_key)) else "false"
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
            for input_key, storage_key, default_value in (
                ("borrow_apr_btc_eth_percent", "trading.borrow_apr_btc_eth_percent", DEFAULT_BORROW_APR_BTC_ETH_PERCENT),
                ("borrow_apr_usdt_points_percent", "trading.borrow_apr_usdt_points_percent", DEFAULT_BORROW_APR_USDT_POINTS_PERCENT),
            ):
                if input_key in settings:
                    numeric = _to_float(settings.get(input_key), name=input_key, minimum=0, maximum=100)
                    value = str(numeric)
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
                    if input_key == "borrow_apr_usdt_points_percent":
                        legacy_daily = str(_daily_percent_from_apr(numeric))
                        conn.execute(
                            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                            ("trading.borrow_interest_percent_daily", legacy_daily, now, self._actor_id(actor)),
                        )
                        setting_changes["trading.borrow_interest_percent_daily"] = legacy_daily
            if "borrow_interest_percent_daily" in settings and "borrow_apr_usdt_points_percent" not in settings:
                legacy_daily = _to_float(settings.get("borrow_interest_percent_daily"), name="borrow_interest_percent_daily", minimum=0, maximum=100)
                apr_value = str(_apr_percent_from_daily(legacy_daily))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_apr_usdt_points_percent", apr_value, now, self._actor_id(actor)),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_interest_percent_daily", str(legacy_daily), now, self._actor_id(actor)),
                )
                setting_changes["trading.borrow_apr_usdt_points_percent"] = apr_value
                setting_changes["trading.borrow_interest_percent_daily"] = str(legacy_daily)
            if "borrow_interest_pool_pressure_multiplier" in settings:
                value = str(_to_float(settings.get("borrow_interest_pool_pressure_multiplier"), name="borrow_interest_pool_pressure_multiplier", minimum=0, maximum=100))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_interest_pool_pressure_multiplier", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.borrow_interest_pool_pressure_multiplier"] = value
            for input_key, storage_key in (
                ("borrow_interest_interval_hours", "trading.borrow_interest_interval_hours"),
                ("borrow_interest_minimum_hours", "trading.borrow_interest_minimum_hours"),
            ):
                if input_key in settings:
                    value = str(_to_int(settings.get(input_key), name=input_key, minimum=1, maximum=168))
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
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
            if "grid_fee_discount_percent" in settings:
                value = str(_to_float(settings.get("grid_fee_discount_percent"), name="grid_fee_discount_percent", minimum=0, maximum=100))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.grid_fee_discount_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.grid_fee_discount_percent"] = value
            if "max_price_staleness_seconds" in settings:
                value = str(_to_int(settings.get("max_price_staleness_seconds"), name="max_price_staleness_seconds", minimum=0, maximum=86400))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.max_price_staleness_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.max_price_staleness_seconds"] = value
            if "bot_auto_scan_interval_seconds" in settings:
                value = str(_to_int(settings.get("bot_auto_scan_interval_seconds"), name="bot_auto_scan_interval_seconds", minimum=10, maximum=3600))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_auto_scan_interval_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_auto_scan_interval_seconds"] = value
            if "bot_auto_scan_limit" in settings:
                value = str(_to_int(settings.get("bot_auto_scan_limit"), name="bot_auto_scan_limit", minimum=1, maximum=200))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_auto_scan_limit", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_auto_scan_limit"] = value
            if "bot_audit_interval_seconds" in settings:
                value = str(_to_int(settings.get("bot_audit_interval_seconds"), name="bot_audit_interval_seconds", minimum=60, maximum=86400))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_audit_interval_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_audit_interval_seconds"] = value
            if "bot_audit_limit" in settings:
                value = str(_to_int(settings.get("bot_audit_limit"), name="bot_audit_limit", minimum=1, maximum=200))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_audit_limit", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_audit_limit"] = value
            if "bot_audit_min_enabled_seconds" in settings:
                value = str(_to_int(settings.get("bot_audit_min_enabled_seconds"), name="bot_audit_min_enabled_seconds", minimum=3600, maximum=604800))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_audit_min_enabled_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_audit_min_enabled_seconds"] = value
            if "price_source" in settings:
                value = str(settings.get("price_source") or "").strip()
                if value not in {FUSED_PRICE_SOURCE, "binance_public_api", "manual_root"}:
                    raise ValueError("price_source must be fused_weighted, binance_public_api, or manual_root")
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_source", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_source"] = value
            if "price_fusion_mode" in settings:
                value = str(settings.get("price_fusion_mode") or "").strip()
                if value not in PRICE_FUSION_MODES:
                    raise ValueError("price_fusion_mode must be auto_depth or manual_weights")
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_mode", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_mode"] = value
            if "price_fusion_manual_weights" in settings:
                value = _normalize_price_fusion_manual_weights(settings.get("price_fusion_manual_weights"))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_manual_weights_json", _json_dumps(value), now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_manual_weights_json"] = value
            if "price_fusion_depth_levels" in settings:
                value = str(_to_int(settings.get("price_fusion_depth_levels"), name="price_fusion_depth_levels", minimum=10, maximum=MAX_PRICE_FUSION_DEPTH_LEVELS))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_depth_levels", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_depth_levels"] = value
            if "price_fusion_depth_band_percent" in settings:
                value = str(_to_float(settings.get("price_fusion_depth_band_percent"), name="price_fusion_depth_band_percent", minimum=0.1, maximum=10))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_depth_band_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_depth_band_percent"] = value
            if "price_fusion_min_orderbook_coverage_percent" in settings:
                value = str(_to_float(settings.get("price_fusion_min_orderbook_coverage_percent"), name="price_fusion_min_orderbook_coverage_percent", minimum=0.1, maximum=10))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_min_orderbook_coverage_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_min_orderbook_coverage_percent"] = value
            if "price_fusion_max_single_provider_weight_percent" in settings:
                value = str(_to_float(settings.get("price_fusion_max_single_provider_weight_percent"), name="price_fusion_max_single_provider_weight_percent", minimum=0, maximum=100))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_max_single_provider_weight_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_max_single_provider_weight_percent"] = value
            if "price_fusion_min_provider_count" in settings:
                value = str(_to_int(settings.get("price_fusion_min_provider_count"), name="price_fusion_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS)))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_min_provider_count", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_min_provider_count"] = value
            if "btc_trade_project_dir" in settings:
                value = str(settings.get("btc_trade_project_dir") or "").strip()
                if len(value) > 500:
                    raise ValueError("btc_trade_project_dir too long")
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.btc_trade_project_dir", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.btc_trade_project_dir"] = value
            for input_key, storage_key in (
                ("btc_trade_repo_url", "trading.btc_trade_repo_url"),
                ("btc_trade_branch", "trading.btc_trade_branch"),
            ):
                if input_key in settings:
                    value = str(settings.get(input_key) or "").strip()
                    if input_key == "btc_trade_repo_url" and not value:
                        value = "https://github.com/s9213712/BTC_trade.git"
                    if input_key == "btc_trade_branch" and not value:
                        value = "strategy/v15b-plus"
                    if len(value) > 500:
                        raise ValueError(f"{input_key} too long")
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
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
        return market_provider_id(market_symbol, "binance_public_api")

    def _fetch_json_url(self, url, *, timeout=5, user_agent="hackme_web/1.0 trading-price", with_meta=False):
        req = Request(url, headers={"User-Agent": user_agent})
        started = time.perf_counter()
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        fetched_at = _now()
        payload = json.loads(raw)
        if not with_meta:
            return payload
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return payload, {
            "fetched_at": fetched_at,
            "latency_ms": latency_ms,
        }

    def _price_points_from_float(self, price, *, source):
        try:
            price_points = _to_price_float(
                Decimal(str(price)) * Decimal(str(USDT_TO_POINTS_RATE)),
                name=f"{source} price_points",
            )
        except Exception as exc:
            raise ValueError(f"{source} price format is invalid") from exc
        if price_points <= 0:
            raise ValueError(f"{source} price is invalid")
        return price_points

    def _fetch_binance_price_points(self, market_symbol):
        symbol = market_provider_id(market_symbol, "binance_public_api")
        if not symbol:
            raise ValueError("binance price is not supported for this market")
        payload = self._fetch_json_url(
            f"{BINANCE_TICKER_URL}?{urlencode({'symbol': symbol})}",
            timeout=5,
        )
        price = payload.get("price") if isinstance(payload, dict) else None
        return self._price_points_from_float(price, source="binance_public_api")

    def _fetch_okx_price_points(self, market_symbol):
        instrument = market_provider_id(market_symbol, "okx_public_api")
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
        product_id = market_provider_id(market_symbol, "coinbase_exchange")
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
        pair = market_provider_id(market_symbol, "kraken_public_api")
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
        symbol = market_provider_id(market_symbol, "gemini_public_api")
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
        pair = market_provider_id(market_symbol, "bitstamp_public_api")
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
        coin_id = market_provider_id(market_symbol, "coingecko_simple_price")
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

    def _price_fusion_depth_levels(self, settings):
        try:
            return int((settings or {}).get("price_fusion_depth_levels") or DEFAULT_PRICE_FUSION_DEPTH_LEVELS)
        except Exception:
            return DEFAULT_PRICE_FUSION_DEPTH_LEVELS

    def _price_fusion_depth_band_percent(self, settings):
        try:
            return float((settings or {}).get("price_fusion_depth_band_percent") or DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT)
        except Exception:
            return DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT

    def _price_fusion_min_orderbook_coverage_percent(self, settings):
        try:
            return float((settings or {}).get("price_fusion_min_orderbook_coverage_percent") or DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT)
        except Exception:
            return DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT

    def _price_fusion_provider_weight_cap_percent(self, settings):
        try:
            return float((settings or {}).get("price_fusion_max_single_provider_weight_percent") or DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT)
        except Exception:
            return DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT

    def _price_fusion_min_provider_count(self, settings):
        try:
            return int((settings or {}).get("price_fusion_min_provider_count") or DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT)
        except Exception:
            return DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT

    def _provider_quantity_unit_info(self, source):
        return {
            "quantity_unit": "base_asset",
            "quantity_unit_label": "base asset",
            "quantity_unit_confirmed": True,
            "quantity_unit_note": f"{PRICE_PROVIDER_LABELS.get(source, source)} spot order book quantity is parsed as base asset size.",
            "contract_size_adjusted": False,
        }

    def _price_fusion_warning(self, code, message, *, severity="warning"):
        return {
            "code": str(code or "").strip(),
            "message": str(message or "").strip(),
            "severity": str(severity or "warning").strip() or "warning",
        }

    def _append_price_fusion_warning(self, warnings, code, message, *, severity="warning"):
        warning = self._price_fusion_warning(code, message, severity=severity)
        if not warning["code"]:
            return warnings
        existing = list(warnings or [])
        if not any(str(item.get("code") or "") == warning["code"] for item in existing if isinstance(item, dict)):
            existing.append(warning)
        return existing

    def _primary_price_fusion_warning(self, warnings):
        for warning in warnings or []:
            if isinstance(warning, dict) and str(warning.get("code") or "").strip():
                return warning
        return {}

    def _price_usage_label(self, price_type):
        normalized = str(price_type or "reference").strip().lower()
        if normalized == "risk_grade":
            return "融資 / 強平 / 保證金 / PnL / bot 風控 / 交易限制"
        return "展示 / 一般估值 / K 線 / 非風控參考"

    def _price_source_label(self, source):
        normalized = str(source or "").strip()
        if not normalized:
            return "未知價格來源"
        if normalized == "manual_root":
            return "root 手動價格"
        if normalized.endswith("_cached"):
            base = normalized[:-7]
            return f"{self._price_source_label(base)}（最後健康快取）"
        if normalized == FUSED_PRICE_SOURCE:
            return "融合價格"
        if normalized == "ticker_fallback":
            return "單一 ticker 降級價格"
        if normalized == "scan_window_replay":
            return "掃描視窗回放價格"
        if normalized == "reference_price":
            return "參考價格"
        if normalized == "test_live_price_provider":
            return "測試 live price provider"
        return PRICE_PROVIDER_LABELS.get(normalized, normalized)

    def _price_context_confidence(self, *, price_type, source, health, degraded, stale, provider_count, high_risk_blocked):
        normalized_source = str(source or "").strip()
        normalized_health = str(health or "healthy").strip().lower()
        normalized_type = str(price_type or "reference").strip().lower()
        providers = max(0, int(provider_count or 0))
        if normalized_source == "manual_root":
            return "manual"
        if stale or high_risk_blocked or normalized_health in {"conservative", "fallback"}:
            return "low"
        if degraded:
            return "medium"
        if normalized_type == "risk_grade" and providers < max(1, DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT):
            return "medium"
        return "high"

    def _build_price_context(self, *, market_symbol, price_type, price_points, price_source, price_meta):
        meta = price_meta or {}
        normalized_type = str(price_type or "reference").strip().lower() or "reference"
        health = str(meta.get("price_health") or "healthy").strip() or "healthy"
        warnings = list(meta.get("warnings") or [])
        source = str(meta.get("resolved_source") or price_source or "manual_root").strip() or "manual_root"
        stale = bool(meta.get("stale"))
        degraded = bool(meta.get("degraded")) or health in {"fallback", "degraded", "conservative"} or bool(warnings) or bool(meta.get("excluded_sources"))
        provider_key = "risk_grade_provider_count" if normalized_type == "risk_grade" else "reference_provider_count"
        provider_count = max(0, int(meta.get(provider_key) or 0))
        high_risk_blocked = bool(meta.get("high_risk_blocked")) if normalized_type == "risk_grade" else False
        warning_message = str(meta.get("high_risk_block_reason") or meta.get("fallback_reason") or "").strip()
        if not warning_message:
            warning_message = str(self._primary_price_fusion_warning(warnings).get("message") or "").strip()
        if not warning_message and source == "manual_root":
            warning_message = "目前使用手動價格，請勿將此價格視為正常即時市場深度。"
        if not warning_message and stale:
            warning_message = "目前使用最後健康快取，請留意價格可能已過時。"
        confidence = self._price_context_confidence(
            price_type=normalized_type,
            source=source,
            health=health,
            degraded=degraded,
            stale=stale,
            provider_count=provider_count,
            high_risk_blocked=high_risk_blocked,
        )
        return {
            "price_type": normalized_type,
            "market_symbol": str(market_symbol or "").strip().upper(),
            "price_points": None if price_points in (None, "") else float(_to_decimal(price_points, name="price_points", minimum=0)),
            "source": source,
            "source_label": self._price_source_label(source),
            "confidence": confidence,
            "stale": stale,
            "degraded": degraded,
            "provider_count": provider_count,
            "health": health,
            "purpose": self._price_usage_label(normalized_type),
            "warning_message": warning_message,
            "high_risk_blocked": high_risk_blocked,
            "excluded_sources": list(meta.get("excluded_sources") or []),
            "warnings": warnings,
        }

    def _attach_market_price_contexts(self, market, *, reference_context, risk_grade_context):
        item = dict(market or {})
        item["reference_price_points"] = reference_context.get("price_points")
        item["risk_grade_price_points"] = risk_grade_context.get("price_points")
        item["reference_price_context"] = reference_context
        item["risk_grade_price_context"] = risk_grade_context
        return item

    def _stored_market_price_contexts(self, market):
        source = str((market or {}).get("price_source") or "manual_root").strip() or "manual_root"
        price_value = (market or {}).get("manual_price_points") or 0
        price_meta = {
            "price_health": "healthy",
            "fallback_reason": "",
            "excluded_sources": [],
            "warnings": [],
            "high_risk_blocked": False,
            "high_risk_block_reason": "",
            "requested_price_mode": "reference",
            "reference_price_points": price_value,
            "risk_grade_price_points": price_value,
            "resolved_source": source,
            "reference_provider_count": 1 if source and source != "manual_root" else 0,
            "risk_grade_provider_count": 1 if source and source != "manual_root" else 0,
            "stale": source.endswith("_cached"),
            "degraded": source == "manual_root" or source.endswith("_cached"),
        }
        if source == "manual_root":
            price_meta["warnings"] = self._append_price_fusion_warning(
                [],
                "manual_price_active",
                "目前使用手動價格，請勿視為正常即時市場深度。",
                severity="warning",
            )
            price_meta["fallback_reason"] = "目前使用手動價格"
        elif source.endswith("_cached"):
            price_meta["price_health"] = "fallback"
            price_meta["warnings"] = self._append_price_fusion_warning(
                [],
                "cached_price_active",
                "目前使用最後健康快取，請留意價格可能已過時。",
                severity="warning",
            )
            price_meta["fallback_reason"] = "目前使用最後健康快取"
        reference_context = self._build_price_context(
            market_symbol=(market or {}).get("symbol"),
            price_type="reference",
            price_points=price_value,
            price_source=source,
            price_meta=price_meta,
        )
        risk_context = self._build_price_context(
            market_symbol=(market or {}).get("symbol"),
            price_type="risk_grade",
            price_points=price_value,
            price_source=source,
            price_meta=price_meta,
        )
        return reference_context, risk_context

    def _price_fusion_effective_score(self, snapshot):
        try:
            return max(float(snapshot.get("effective_depth_score")), 0.0)
        except Exception:
            try:
                return max(float(snapshot.get("depth_score") or 0.0), 0.0)
            except Exception:
                return 0.0

    def _price_fusion_reference_score(self, snapshot):
        try:
            density_score = max(float(snapshot.get("depth_density_score") or 0.0), 0.0)
            if density_score > 0:
                return density_score
        except Exception:
            pass
        try:
            return max(float(snapshot.get("depth_score") or 0.0), 0.0)
        except Exception:
            return 0.0

    def _assert_price_meta_allows_high_risk_use(self, conn, *, actor=None, market_symbol="", usage="", price_meta=None):
        meta = price_meta or {}
        if not bool(meta.get("high_risk_blocked")):
            return
        reason = str(meta.get("high_risk_block_reason") or meta.get("fallback_reason") or "price source is in conservative mode").strip()
        self._audit_event(
            conn,
            "TRADING_PRICE_HEALTH_BLOCKED",
            "high-risk trading path blocked by degraded fused price health",
            actor=actor,
            market_symbol=market_symbol,
            severity="critical",
            metadata={
                "usage": usage,
                "reason": reason,
                "price_health": meta.get("price_health"),
                "warnings": meta.get("warnings") or [],
                "excluded_sources": meta.get("excluded_sources") or [],
            },
        )
        raise ValueError(f"{usage or 'high-risk trading action'} is blocked while fused price is in conservative mode: {reason}")

    def _provider_depth_request_limit(self, source, depth_levels):
        requested = max(1, int(depth_levels or DEFAULT_PRICE_FUSION_DEPTH_LEVELS))
        if source == "binance_public_api":
            for value in (5, 10, 20, 50, 100, 500, 1000, 5000):
                if requested <= value:
                    return value
            return 5000
        if source == "okx_public_api":
            return max(1, min(requested, 400))
        if source == "kraken_public_api":
            return max(1, min(requested, 500))
        if source == "gemini_public_api":
            return max(1, min(requested, 500))
        return requested

    def _parse_orderbook_side(self, rows, *, max_levels):
        raw_rows = list(rows or [])
        parsed = []
        for row in raw_rows[:max_levels]:
            if isinstance(row, dict):
                price = row.get("price")
                quantity = row.get("amount", row.get("quantity", row.get("size")))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                price, quantity = row[0], row[1]
            else:
                continue
            try:
                parsed.append((float(price), float(quantity)))
            except Exception:
                continue
        return {
            "raw_count": len(raw_rows),
            "used_count": len(parsed),
            "levels": parsed,
        }

    def _depth_notional_snapshot(self, bids, asks, *, max_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        bid_info = self._parse_orderbook_side(bids, max_levels=max_levels)
        ask_info = self._parse_orderbook_side(asks, max_levels=max_levels)
        bid_levels = bid_info["levels"]
        ask_levels = ask_info["levels"]
        if not bid_levels or not ask_levels:
            raise ValueError("order book is empty")
        best_bid = bid_levels[0][0]
        best_ask = ask_levels[0][0]
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            raise ValueError("order book spread is invalid")
        midpoint = (best_bid + best_ask) / 2.0
        lower_bound = midpoint * (1.0 - band_percent / 100.0)
        upper_bound = midpoint * (1.0 + band_percent / 100.0)
        min_bid = min(price for price, _quantity in bid_levels)
        max_ask = max(price for price, _quantity in ask_levels)
        bid_coverage_percent = min(
            max(((midpoint - min_bid) / midpoint) * 100.0, 0.0) if midpoint > 0 else 0.0,
            float(band_percent),
        )
        ask_coverage_percent = min(
            max(((max_ask - midpoint) / midpoint) * 100.0, 0.0) if midpoint > 0 else 0.0,
            float(band_percent),
        )
        bid_reached_lower_bound = min_bid <= lower_bound + 1e-12
        ask_reached_upper_bound = max_ask >= upper_bound - 1e-12
        orderbook_truncated = not (bid_reached_lower_bound and ask_reached_upper_bound)
        bid_notional = sum(price * quantity for price, quantity in bid_levels if price >= lower_bound)
        ask_notional = sum(price * quantity for price, quantity in ask_levels if price <= upper_bound)
        score = min(bid_notional, ask_notional)
        if score <= 0:
            score = (bid_notional + ask_notional) / 2.0
        if score <= 0:
            raise ValueError("order book depth score is invalid")
        coverage_ratio = 1.0
        if float(band_percent) > 0:
            coverage_ratio = max(0.0, min(min(bid_coverage_percent, ask_coverage_percent) / float(band_percent), 1.0))
        effective_depth_score = score * coverage_ratio
        min_coverage_percent = min(float(bid_coverage_percent or 0.0), float(ask_coverage_percent or 0.0))
        depth_density_score = (score / min_coverage_percent) if min_coverage_percent > 0 else 0.0
        spread_points = best_ask - best_bid
        spread_percent = (spread_points / midpoint * 100.0) if midpoint > 0 else 0.0
        stronger_side = max(bid_notional, ask_notional)
        side_balance_ratio = (score / stronger_side) if stronger_side > 0 else 0.0
        return {
            "midpoint": midpoint,
            "depth_score": score,
            "effective_depth_score": effective_depth_score,
            "depth_density_score": depth_density_score,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_points": spread_points,
            "spread_percent": spread_percent,
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "side_balance_ratio": side_balance_ratio,
            "bid_coverage_percent": bid_coverage_percent,
            "ask_coverage_percent": ask_coverage_percent,
            "bid_reached_lower_bound": bid_reached_lower_bound,
            "ask_reached_upper_bound": ask_reached_upper_bound,
            "orderbook_truncated": orderbook_truncated,
            "coverage_ratio_percent": coverage_ratio * 100.0,
            "raw_bid_levels_count": bid_info["raw_count"],
            "raw_ask_levels_count": ask_info["raw_count"],
            "used_bid_levels_count": bid_info["used_count"],
            "used_ask_levels_count": ask_info["used_count"],
            "band_percent": float(band_percent),
            "depth_levels_requested": int(max_levels),
        }

    def _depth_notional_score(self, bids, asks, *, max_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        snapshot = self._depth_notional_snapshot(bids, asks, max_levels=max_levels, band_percent=band_percent)
        return snapshot["midpoint"], snapshot["depth_score"]

    def _build_orderbook_snapshot(self, *, source, bids, asks, fetch_meta=None, max_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, request_limit=None):
        stats = self._depth_notional_snapshot(bids, asks, max_levels=max_levels, band_percent=band_percent)
        fetched_at = str((fetch_meta or {}).get("fetched_at") or _now())
        latency_ms = round(float((fetch_meta or {}).get("latency_ms") or 0.0), 2)
        try:
            age_seconds = max(0.0, round((datetime.now() - datetime.fromisoformat(fetched_at)).total_seconds(), 3))
        except Exception:
            age_seconds = 0.0
        snapshot = {
            "source": source,
            "price_points": self._price_points_from_float(stats["midpoint"], source=source),
            "midpoint_points": round(float(stats["midpoint"]), 8),
            "depth_score": round(float(stats["depth_score"]), 8),
            "effective_depth_score": round(float(stats["effective_depth_score"]), 8),
            "depth_density_score": round(float(stats["depth_density_score"]), 8),
            "best_bid_points": round(float(stats["best_bid"]), 8),
            "best_ask_points": round(float(stats["best_ask"]), 8),
            "spread_points": round(float(stats["spread_points"]), 8),
            "spread_percent": round(float(stats["spread_percent"]), 8),
            "bid_notional_points": round(float(stats["bid_notional"]), 8),
            "ask_notional_points": round(float(stats["ask_notional"]), 8),
            "side_balance_ratio_percent": round(float(stats["side_balance_ratio"]) * 100.0, 4),
            "bid_coverage_percent": round(float(stats["bid_coverage_percent"]), 6),
            "ask_coverage_percent": round(float(stats["ask_coverage_percent"]), 6),
            "bid_reached_lower_bound": bool(stats["bid_reached_lower_bound"]),
            "ask_reached_upper_bound": bool(stats["ask_reached_upper_bound"]),
            "orderbook_truncated": bool(stats["orderbook_truncated"]),
            "coverage_ratio_percent": round(float(stats["coverage_ratio_percent"]), 4),
            "raw_bid_levels_count": int(stats["raw_bid_levels_count"]),
            "raw_ask_levels_count": int(stats["raw_ask_levels_count"]),
            "used_bid_levels_count": int(stats["used_bid_levels_count"]),
            "used_ask_levels_count": int(stats["used_ask_levels_count"]),
            "depth_levels_requested": int(stats["depth_levels_requested"]),
            "provider_depth_request_limit": int(request_limit or max_levels or DEFAULT_PRICE_FUSION_DEPTH_LEVELS),
            "provider_depth_limit_reached": bool(request_limit and (
                int(stats["raw_bid_levels_count"]) >= int(request_limit)
                or int(stats["raw_ask_levels_count"]) >= int(request_limit)
            )),
            "depth_band_percent": round(float(stats["band_percent"]), 4),
            "fetched_at": fetched_at,
            "age_seconds": age_seconds,
            "latency_ms": latency_ms,
        }
        snapshot.update(self._provider_quantity_unit_info(source))
        return snapshot

    def _normalize_orderbook_fetch_result(self, fetch_result):
        if isinstance(fetch_result, tuple) and len(fetch_result) == 2:
            payload, fetch_meta = fetch_result
            return payload, fetch_meta if isinstance(fetch_meta, dict) else {}
        return fetch_result, {}

    def _fetch_binance_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        symbol = market_provider_id(market_symbol, "binance_public_api")
        if not symbol:
            raise ValueError("binance order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("binance_public_api", depth_levels)
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            f"{BINANCE_DEPTH_URL}?{urlencode({'symbol': symbol, 'limit': request_limit})}",
            timeout=5,
            with_meta=True,
        ))
        return self._build_orderbook_snapshot(
            source="binance_public_api",
            bids=payload.get("bids") or [],
            asks=payload.get("asks") or [],
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
        )

    def _fetch_okx_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        instrument = market_provider_id(market_symbol, "okx_public_api")
        if not instrument:
            raise ValueError("okx order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("okx_public_api", depth_levels)
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            f"{OKX_BOOKS_URL}?{urlencode({'instId': instrument, 'sz': request_limit})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-depth okx",
            with_meta=True,
        ))
        data = payload.get("data") if isinstance(payload, dict) else None
        book = data[0] if isinstance(data, list) and data else None
        if not isinstance(book, dict):
            raise ValueError("okx order book payload is invalid")
        return self._build_orderbook_snapshot(
            source="okx_public_api",
            bids=book.get("bids") or [],
            asks=book.get("asks") or [],
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
        )

    def _fetch_coinbase_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        product_id = market_provider_id(market_symbol, "coinbase_exchange")
        if not product_id:
            raise ValueError("coinbase order book is not supported for this market")
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            f"{COINBASE_BOOK_URL_TEMPLATE.format(product_id=product_id)}?{urlencode({'level': 2})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-depth coinbase",
            with_meta=True,
        ))
        return self._build_orderbook_snapshot(
            source="coinbase_exchange",
            bids=payload.get("bids") or [],
            asks=payload.get("asks") or [],
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=2,
        )

    def _fetch_kraken_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        pair = market_provider_id(market_symbol, "kraken_public_api")
        if not pair:
            raise ValueError("kraken order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("kraken_public_api", depth_levels)
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            f"{KRAKEN_DEPTH_URL}?{urlencode({'pair': pair, 'count': request_limit})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-depth kraken",
            with_meta=True,
        ))
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(f"kraken depth error: {payload.get('error') if isinstance(payload, dict) else 'invalid payload'}")
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        book = next(iter(result.values()), None)
        if not isinstance(book, dict):
            raise ValueError("kraken order book payload is invalid")
        return self._build_orderbook_snapshot(
            source="kraken_public_api",
            bids=book.get("bids") or [],
            asks=book.get("asks") or [],
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
        )

    def _fetch_gemini_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        symbol = market_provider_id(market_symbol, "gemini_public_api")
        if not symbol:
            raise ValueError("gemini order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("gemini_public_api", depth_levels)
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            f"{GEMINI_BOOK_URL_TEMPLATE.format(symbol=symbol)}?{urlencode({'limit_bids': request_limit, 'limit_asks': request_limit})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-depth gemini",
            with_meta=True,
        ))
        bids = [[row.get("price"), row.get("amount")] for row in (payload.get("bids") or []) if isinstance(row, dict)]
        asks = [[row.get("price"), row.get("amount")] for row in (payload.get("asks") or []) if isinstance(row, dict)]
        return self._build_orderbook_snapshot(
            source="gemini_public_api",
            bids=bids,
            asks=asks,
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
        )

    def _fetch_bitstamp_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        pair = market_provider_id(market_symbol, "bitstamp_public_api")
        if not pair:
            raise ValueError("bitstamp order book is not supported for this market")
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            BITSTAMP_ORDER_BOOK_URL_TEMPLATE.format(pair=pair),
            timeout=5,
            user_agent="hackme_web/1.0 trading-depth bitstamp",
            with_meta=True,
        ))
        return self._build_orderbook_snapshot(
            source="bitstamp_public_api",
            bids=payload.get("bids") or [],
            asks=payload.get("asks") or [],
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=depth_levels,
        )

    def _price_fusion_manual_weights(self, settings):
        return _normalize_price_fusion_manual_weights((settings or {}).get("price_fusion_manual_weights"))

    def _apply_price_fusion_weight_cap(self, weighted_rows, *, max_single_provider_weight_percent):
        total_raw = sum(max(float(weight), 0.0) for _snap, weight in weighted_rows)
        if total_raw <= 0:
            raise ValueError("weighted fused price has no positive provider weight")
        normalized = {
            snap["source"]: max(float(weight), 0.0) / total_raw
            for snap, weight in weighted_rows
        }
        cap_fraction = max(0.0, min(float(max_single_provider_weight_percent or 0.0), 100.0)) / 100.0
        if cap_fraction <= 0 or cap_fraction >= 1.0:
            return normalized, False, False
        if len(weighted_rows) * cap_fraction < 1.0 - 1e-9:
            return normalized, False, True
        remaining = {snap["source"]: max(float(weight), 0.0) for snap, weight in weighted_rows}
        capped = {}
        remaining_fraction = 1.0
        while remaining:
            raw_sum = sum(remaining.values())
            if raw_sum <= 0 or remaining_fraction <= 1e-9:
                break
            over = [
                source
                for source, value in remaining.items()
                if (value / raw_sum) * remaining_fraction > cap_fraction + 1e-12
            ]
            if not over:
                for source, value in remaining.items():
                    capped[source] = (value / raw_sum) * remaining_fraction
                remaining = {}
                break
            for source in over:
                capped[source] = cap_fraction
                del remaining[source]
                remaining_fraction -= cap_fraction
                if remaining_fraction <= 1e-9:
                    remaining_fraction = 0.0
                    break
        if remaining:
            raw_sum = sum(remaining.values())
            if raw_sum > 0 and remaining_fraction > 0:
                for source, value in remaining.items():
                    capped[source] = (value / raw_sum) * remaining_fraction
        cap_applied = any(abs(capped.get(source, 0.0) - normalized.get(source, 0.0)) > 1e-12 for source in normalized)
        return capped or normalized, cap_applied, False

    def _build_price_fusion_weight_model(self, snapshots, *, mode, weight_map, max_single_provider_weight_percent, score_getter):
        rows = []
        resolved_mode = mode
        if mode == "manual_weights":
            manual_positive_total = 0.0
            for snap in snapshots:
                weight = float(weight_map.get(snap["source"], 0.0))
                if weight > 0:
                    rows.append((snap, weight))
                    manual_positive_total += weight
            if manual_positive_total <= 0:
                resolved_mode = "auto_depth_fallback"
                rows = []
        if not rows:
            rows = [(snap, float(score_getter(snap))) for snap in snapshots]
        total_raw_weight = sum(max(float(weight), 0.0) for _snap, weight in rows)
        if total_raw_weight <= 0:
            equal_weight = 1.0 / len(snapshots)
            resolved_mode = "equal_weight_fallback"
            rows = [(snap, equal_weight) for snap in snapshots]
            total_raw_weight = sum(weight for _snap, weight in rows)
        normalized_weights, cap_applied, cap_unenforceable = self._apply_price_fusion_weight_cap(
            rows,
            max_single_provider_weight_percent=max_single_provider_weight_percent,
        )
        return {
            "rows": rows,
            "resolved_mode": resolved_mode,
            "total_raw_weight": total_raw_weight,
            "normalized_weights": normalized_weights,
            "cap_applied": cap_applied,
            "cap_unenforceable": cap_unenforceable,
        }

    def _fetch_weighted_fused_price_points(self, market_symbol, *, settings):
        market_symbol = str(market_symbol or "").strip().upper()
        snapshots = []
        errors = []
        provider_failures = {}
        warnings = []
        depth_levels = self._price_fusion_depth_levels(settings)
        depth_band_percent = self._price_fusion_depth_band_percent(settings)
        min_orderbook_coverage_percent = self._price_fusion_min_orderbook_coverage_percent(settings)
        max_single_provider_weight_percent = self._price_fusion_provider_weight_cap_percent(settings)
        min_provider_count = self._price_fusion_min_provider_count(settings)
        fetchers = (
            ("binance_public_api", self._fetch_binance_orderbook_snapshot),
            ("okx_public_api", self._fetch_okx_orderbook_snapshot),
            ("coinbase_exchange", self._fetch_coinbase_orderbook_snapshot),
            ("kraken_public_api", self._fetch_kraken_orderbook_snapshot),
            ("gemini_public_api", self._fetch_gemini_orderbook_snapshot),
            ("bitstamp_public_api", self._fetch_bitstamp_orderbook_snapshot),
        )
        for source, fetcher in fetchers:
            try:
                try:
                    snapshots.append(fetcher(market_symbol, depth_levels=depth_levels, band_percent=depth_band_percent))
                except TypeError:
                    try:
                        snapshots.append(fetcher(market_symbol, depth_levels=depth_levels))
                    except TypeError:
                        snapshots.append(fetcher(market_symbol))
            except Exception as exc:
                short_error = str(exc)[:120]
                errors.append(f"{source}: {short_error}")
                provider_failures[source] = short_error
        if not snapshots:
            try:
                fallback_price, fallback_source = self._fetch_live_price_points(market_symbol)
                warnings = self._append_price_fusion_warning(
                    warnings,
                    "orderbook_unavailable",
                    f"多交易所 order book 全部失敗，已降級為單一 ticker 價格來源 {PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source)}",
                    severity="critical",
                )
                warnings = self._append_price_fusion_warning(
                    warnings,
                    "provider_count_low",
                    f"風控級可用 order book 來源只剩 1 家，低於建議下限 {min_provider_count} 家",
                    severity="critical",
                )
                primary_warning = self._primary_price_fusion_warning(warnings)
                excluded = [
                    {
                        "source": source,
                        "label": PRICE_PROVIDER_LABELS.get(source, source),
                        "reason": "fetch_failed",
                        "error": provider_failures.get(source, ""),
                    }
                    for source, _fetcher in fetchers
                ]
                fallback_value = float(_to_decimal(fallback_price, name="fallback_price", minimum=0.00000001))
                return fallback_price, {
                    "requested_mode": str((settings or {}).get("price_fusion_mode") or "auto_depth").strip(),
                    "mode": "emergency_single_source",
                    "reference_mode": "ticker_fallback",
                    "risk_grade_mode": "unavailable",
                    "warnings": warnings,
                    "warning_code": str(primary_warning.get("code") or ""),
                    "warning_message": "；".join(
                        warning.get("message") or ""
                        for warning in warnings
                        if isinstance(warning, dict) and str(warning.get("message") or "").strip()
                    ),
                    "degraded": True,
                    "fallback_active": True,
                    "conservative_mode": True,
                    "high_risk_blocked": True,
                    "high_risk_block_reason": "目前可用 order book 來源不足，只能提供 degraded reference price",
                    "providers_used": [{
                        "source": fallback_source,
                        "label": PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
                        "price_points": fallback_value,
                        "midpoint_points": fallback_value,
                        "depth_score": 0.0,
                        "effective_depth_score": 0.0,
                        "depth_density_score": 0.0,
                        "reference_weight_percent": 100.0,
                        "risk_grade_weight_percent": 0.0,
                        "normalized_weight_percent": 100.0,
                        "raw_normalized_weight_percent": 100.0,
                        "risk_grade_eligible": False,
                        "coverage_insufficient": True,
                        "coverage_warning_message": "資料截斷，不代表該交易所真實深度不足；目前僅納入 reference price，不納入高風險風控權重。",
                        "quantity_unit": "n/a",
                        "quantity_unit_label": "n/a",
                        "quantity_unit_confirmed": False,
                        "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                        "best_bid_points": None,
                        "best_ask_points": None,
                        "spread_percent": None,
                        "bid_notional_points": None,
                        "ask_notional_points": None,
                        "fetched_at": _now(),
                        "age_seconds": 0.0,
                        "latency_ms": 0.0,
                        "midpoint_deviation_percent": 0.0,
                        "raw_bid_levels_count": 0,
                        "raw_ask_levels_count": 0,
                        "used_bid_levels_count": 0,
                        "used_ask_levels_count": 0,
                        "bid_coverage_percent": 0.0,
                        "ask_coverage_percent": 0.0,
                        "bid_reached_lower_bound": False,
                        "ask_reached_upper_bound": False,
                        "orderbook_truncated": True,
                        "coverage_ratio_percent": 0.0,
                        "depth_levels_requested": depth_levels,
                        "provider_depth_request_limit": 0,
                        "provider_depth_limit_reached": False,
                    }],
                    "excluded_providers": excluded,
                    "provider_errors": errors,
                    "resolved_source": fallback_source,
                    "reference_price_points": fallback_value,
                    "risk_grade_price_points": None,
                    "reference_provider_count": 1,
                    "risk_grade_provider_count": 0,
                    "reference_weights_sum_percent": 100.0,
                    "risk_grade_weights_sum_percent": 0.0,
                    "depth_levels": depth_levels,
                    "depth_band_percent": depth_band_percent,
                    "min_orderbook_coverage_percent": min_orderbook_coverage_percent,
                    "max_single_provider_weight_percent": max_single_provider_weight_percent,
                    "min_provider_count": min_provider_count,
                    "median_midpoint_points": fallback_value,
                }
            except Exception as fallback_exc:
                errors.append(f"single_source_fallback: {str(fallback_exc)[:120]}")
                raise ValueError("; ".join(errors) or "all fused price providers failed") from fallback_exc

        median_midpoint = _median_float([snap.get("midpoint_points") or snap.get("price_points") or 0.0 for snap in snapshots])
        weight_map = self._price_fusion_manual_weights(settings)
        excluded_providers = [
            {
                "source": source,
                "label": PRICE_PROVIDER_LABELS.get(source, source),
                "reason": "fetch_failed",
                "error": provider_failures.get(source, ""),
                "manual_weight": round(float(weight_map.get(source, 0.0)), 8),
            }
            for source, _fetcher in fetchers
            if source in provider_failures
        ]

        reference_snapshots = []
        for snap in snapshots:
            midpoint = float(snap.get("midpoint_points") or snap.get("price_points") or 0.0)
            deviation_percent = 0.0
            if median_midpoint > 0 and midpoint > 0:
                deviation_percent = abs(midpoint - median_midpoint) * 100.0 / median_midpoint
            snap["midpoint_deviation_percent"] = round(deviation_percent, 8)
            age_seconds = snap.get("age_seconds")
            latency_ms = snap.get("latency_ms")
            side_balance_ratio_percent = snap.get("side_balance_ratio_percent")
            bid_coverage_percent = float(snap.get("bid_coverage_percent") or 0.0)
            ask_coverage_percent = float(snap.get("ask_coverage_percent") or 0.0)
            coverage_insufficient = bid_coverage_percent < min_orderbook_coverage_percent or ask_coverage_percent < min_orderbook_coverage_percent
            snap["risk_grade_eligible"] = not coverage_insufficient
            snap["coverage_insufficient"] = coverage_insufficient
            snap["coverage_warning_message"] = (
                "資料截斷，不代表該交易所真實深度不足；目前僅納入 reference price，不納入高風險風控權重。"
                if coverage_insufficient or bool(snap.get("orderbook_truncated"))
                else ""
            )
            reason = ""
            message = ""
            if age_seconds is not None and float(age_seconds or 0.0) > DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS:
                reason = "stale_orderbook"
                message = f"order book age {snap.get('age_seconds')}s exceeds {DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS}s"
            elif latency_ms is not None and float(latency_ms or 0.0) > DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS:
                reason = "latency_too_high"
                message = f"order book latency {snap.get('latency_ms')}ms exceeds {DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS}ms"
            elif side_balance_ratio_percent is not None and float(side_balance_ratio_percent or 0.0) < DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0:
                reason = "one_sided_depth"
                message = f"single-sided depth ratio {snap.get('side_balance_ratio_percent')}% is below {round(DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2)}%"
            elif deviation_percent > DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT:
                reason = "midpoint_deviation_exceeded"
                message = f"midpoint deviates {round(deviation_percent, 4)}% from median"
            if reason:
                excluded_providers.append({
                    "source": snap["source"],
                    "label": PRICE_PROVIDER_LABELS.get(snap["source"], snap["source"]),
                    "reason": reason,
                    "error": message,
                    "manual_weight": round(float(weight_map.get(snap["source"], 0.0)), 8),
                    "price_points": round(float(snap.get("price_points") or 0.0), 8),
                    "midpoint_deviation_percent": round(float(deviation_percent), 8),
                    "latency_ms": round(float(snap.get("latency_ms") or 0.0), 2),
                    "age_seconds": round(float(snap.get("age_seconds") or 0.0), 3),
                    "side_balance_ratio_percent": round(float(snap.get("side_balance_ratio_percent") or 0.0), 4),
                    "best_bid_points": snap.get("best_bid_points"),
                    "best_ask_points": snap.get("best_ask_points"),
                    "spread_percent": snap.get("spread_percent"),
                    "bid_notional_points": snap.get("bid_notional_points"),
                    "ask_notional_points": snap.get("ask_notional_points"),
                    "depth_density_score": snap.get("depth_density_score"),
                    "raw_bid_levels_count": snap.get("raw_bid_levels_count"),
                    "raw_ask_levels_count": snap.get("raw_ask_levels_count"),
                    "used_bid_levels_count": snap.get("used_bid_levels_count"),
                    "used_ask_levels_count": snap.get("used_ask_levels_count"),
                    "provider_depth_request_limit": snap.get("provider_depth_request_limit"),
                    "provider_depth_limit_reached": bool(snap.get("provider_depth_limit_reached")),
                    "bid_coverage_percent": round(bid_coverage_percent, 6),
                    "ask_coverage_percent": round(ask_coverage_percent, 6),
                    "bid_reached_lower_bound": bool(snap.get("bid_reached_lower_bound")),
                    "ask_reached_upper_bound": bool(snap.get("ask_reached_upper_bound")),
                    "orderbook_truncated": bool(snap.get("orderbook_truncated")),
                    "coverage_ratio_percent": round(float(snap.get("coverage_ratio_percent") or 0.0), 4),
                    "quantity_unit_label": snap.get("quantity_unit_label"),
                })
                continue
            reference_snapshots.append(snap)

        snapshots = reference_snapshots
        if not snapshots:
            try:
                fallback_price, fallback_source = self._fetch_live_price_points(market_symbol)
                warnings = self._append_price_fusion_warning(
                    warnings,
                    "orderbook_quality_rejected",
                    f"多交易所 order book 已抓到，但全部被品質規則排除，已降級為單一 ticker 價格來源 {PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source)}",
                    severity="critical",
                )
                warnings = self._append_price_fusion_warning(
                    warnings,
                    "provider_count_low",
                    f"風控級可用 order book 來源只剩 1 家，低於建議下限 {min_provider_count} 家",
                    severity="critical",
                )
                primary_warning = self._primary_price_fusion_warning(warnings)
                fallback_value = float(_to_decimal(fallback_price, name="fallback_price", minimum=0.00000001))
                return fallback_price, {
                    "requested_mode": str((settings or {}).get("price_fusion_mode") or "auto_depth").strip(),
                    "mode": "quality_filtered_single_source",
                    "reference_mode": "ticker_fallback",
                    "risk_grade_mode": "unavailable",
                    "warnings": warnings,
                    "warning_code": str(primary_warning.get("code") or ""),
                    "warning_message": "；".join(
                        warning.get("message") or ""
                        for warning in warnings
                        if isinstance(warning, dict) and str(warning.get("message") or "").strip()
                    ),
                    "degraded": True,
                    "fallback_active": True,
                    "conservative_mode": True,
                    "high_risk_blocked": True,
                    "high_risk_block_reason": "目前可用 order book 來源不足，只能提供 degraded reference price",
                    "providers_used": [{
                        "source": fallback_source,
                        "label": PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
                        "price_points": fallback_value,
                        "midpoint_points": fallback_value,
                        "depth_score": 0.0,
                        "effective_depth_score": 0.0,
                        "depth_density_score": 0.0,
                        "reference_weight_percent": 100.0,
                        "risk_grade_weight_percent": 0.0,
                        "normalized_weight_percent": 100.0,
                        "raw_normalized_weight_percent": 100.0,
                        "risk_grade_eligible": False,
                        "coverage_insufficient": True,
                        "coverage_warning_message": "資料截斷，不代表該交易所真實深度不足；目前僅納入 reference price，不納入高風險風控權重。",
                        "quantity_unit": "n/a",
                        "quantity_unit_label": "n/a",
                        "quantity_unit_confirmed": False,
                        "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                        "best_bid_points": None,
                        "best_ask_points": None,
                        "spread_percent": None,
                        "bid_notional_points": None,
                        "ask_notional_points": None,
                        "fetched_at": _now(),
                        "age_seconds": 0.0,
                        "latency_ms": 0.0,
                        "midpoint_deviation_percent": 0.0,
                        "raw_bid_levels_count": 0,
                        "raw_ask_levels_count": 0,
                        "used_bid_levels_count": 0,
                        "used_ask_levels_count": 0,
                        "bid_coverage_percent": 0.0,
                        "ask_coverage_percent": 0.0,
                        "bid_reached_lower_bound": False,
                        "ask_reached_upper_bound": False,
                        "orderbook_truncated": True,
                        "coverage_ratio_percent": 0.0,
                        "depth_levels_requested": depth_levels,
                        "provider_depth_request_limit": 0,
                        "provider_depth_limit_reached": False,
                    }],
                    "excluded_providers": excluded_providers,
                    "provider_errors": errors,
                    "resolved_source": fallback_source,
                    "reference_price_points": fallback_value,
                    "risk_grade_price_points": None,
                    "reference_provider_count": 1,
                    "risk_grade_provider_count": 0,
                    "reference_weights_sum_percent": 100.0,
                    "risk_grade_weights_sum_percent": 0.0,
                    "depth_levels": depth_levels,
                    "depth_band_percent": depth_band_percent,
                    "min_orderbook_coverage_percent": min_orderbook_coverage_percent,
                    "max_single_provider_weight_percent": max_single_provider_weight_percent,
                    "min_provider_count": min_provider_count,
                    "median_midpoint_points": median_midpoint,
                }
            except Exception as fallback_exc:
                errors.append(f"quality_filtered_single_source: {str(fallback_exc)[:120]}")
                raise ValueError("; ".join(errors) or "all fused price providers failed quality checks") from fallback_exc

        mode = str((settings or {}).get("price_fusion_mode") or "auto_depth").strip()
        manual_positive_reference = sum(max(float(weight_map.get(snap["source"], 0.0)), 0.0) for snap in snapshots)
        if mode == "manual_weights" and manual_positive_reference > 0:
            weighted_reference_snapshots = []
            for snap in snapshots:
                if max(float(weight_map.get(snap["source"], 0.0)), 0.0) > 0:
                    weighted_reference_snapshots.append(snap)
                    continue
                excluded_providers.append({
                    "source": snap["source"],
                    "label": PRICE_PROVIDER_LABELS.get(snap["source"], snap["source"]),
                    "reason": "manual_weight_zero",
                    "error": "",
                    "manual_weight": round(float(weight_map.get(snap["source"], 0.0)), 8),
                    "price_points": round(float(snap.get("price_points") or 0.0), 8),
                    "midpoint_deviation_percent": round(float(snap.get("midpoint_deviation_percent") or 0.0), 8),
                    "latency_ms": round(float(snap.get("latency_ms") or 0.0), 2),
                    "age_seconds": round(float(snap.get("age_seconds") or 0.0), 3),
                    "side_balance_ratio_percent": round(float(snap.get("side_balance_ratio_percent") or 0.0), 4),
                    "best_bid_points": snap.get("best_bid_points"),
                    "best_ask_points": snap.get("best_ask_points"),
                    "spread_percent": snap.get("spread_percent"),
                    "bid_notional_points": snap.get("bid_notional_points"),
                    "ask_notional_points": snap.get("ask_notional_points"),
                    "depth_density_score": snap.get("depth_density_score"),
                    "raw_bid_levels_count": snap.get("raw_bid_levels_count"),
                    "raw_ask_levels_count": snap.get("raw_ask_levels_count"),
                    "used_bid_levels_count": snap.get("used_bid_levels_count"),
                    "used_ask_levels_count": snap.get("used_ask_levels_count"),
                    "provider_depth_request_limit": snap.get("provider_depth_request_limit"),
                    "provider_depth_limit_reached": bool(snap.get("provider_depth_limit_reached")),
                    "bid_coverage_percent": round(float(snap.get("bid_coverage_percent") or 0.0), 6),
                    "ask_coverage_percent": round(float(snap.get("ask_coverage_percent") or 0.0), 6),
                    "bid_reached_lower_bound": bool(snap.get("bid_reached_lower_bound")),
                    "ask_reached_upper_bound": bool(snap.get("ask_reached_upper_bound")),
                    "orderbook_truncated": bool(snap.get("orderbook_truncated")),
                    "coverage_ratio_percent": round(float(snap.get("coverage_ratio_percent") or 0.0), 4),
                    "quantity_unit_label": snap.get("quantity_unit_label"),
                })
            snapshots = weighted_reference_snapshots
        reference_mode_input = mode
        if mode == "manual_weights" and manual_positive_reference <= 0:
            warnings = self._append_price_fusion_warning(
                warnings,
                "manual_weights_invalid",
                "root 手動權重全部為 0，已改用自動深度權重",
            )
        reference_model = self._build_price_fusion_weight_model(
            snapshots,
            mode=reference_mode_input,
            weight_map=weight_map,
            max_single_provider_weight_percent=max_single_provider_weight_percent,
            score_getter=self._price_fusion_reference_score,
        )
        if mode == "manual_weights" and manual_positive_reference <= 0:
            warnings = self._append_price_fusion_warning(
                warnings,
                "manual_weights_unusable",
                "root 手動權重目前沒有可用來源，已改用自動深度權重",
            )
        if reference_model["resolved_mode"] == "equal_weight_fallback":
            warnings = self._append_price_fusion_warning(
                warnings,
                "depth_score_invalid",
                "所有來源 reference price 分數都無效，已改用等權平均",
            )
        if reference_model["cap_unenforceable"]:
            warnings = self._append_price_fusion_warning(
                warnings,
                "provider_weight_cap_unenforceable",
                f"目前 reference price 可用來源太少，無法滿足單一來源權重上限 {max_single_provider_weight_percent:.2f}%",
            )
        elif reference_model["cap_applied"]:
            warnings = self._append_price_fusion_warning(
                warnings,
                "provider_weight_cap_applied",
                f"已套用單一來源權重上限 {max_single_provider_weight_percent:.2f}%",
            )

        risk_snapshots = [snap for snap in snapshots if bool(snap.get("risk_grade_eligible"))]
        manual_positive_risk = sum(max(float(weight_map.get(snap["source"], 0.0)), 0.0) for snap in risk_snapshots)
        risk_model = None
        if risk_snapshots:
            risk_mode_input = mode
            risk_model = self._build_price_fusion_weight_model(
                risk_snapshots,
                mode=risk_mode_input,
                weight_map=weight_map,
                max_single_provider_weight_percent=max_single_provider_weight_percent,
                score_getter=self._price_fusion_effective_score,
            )
        reference_weights = reference_model["normalized_weights"]
        reference_rows = reference_model["rows"]
        reference_total_raw_weight = reference_model["total_raw_weight"]
        reference_raw_map = {
            snap["source"]: float(weight)
            for snap, weight in reference_rows
        }
        risk_weights = risk_model["normalized_weights"] if risk_model else {}
        risk_rows = risk_model["rows"] if risk_model else []
        risk_total_raw_weight = risk_model["total_raw_weight"] if risk_model else 0.0
        risk_raw_map = {
            snap["source"]: float(weight)
            for snap, weight in risk_rows
        }

        reference_price = sum(
            float(_to_decimal(snap["price_points"], name="price_points", minimum=0.00000001)) * float(reference_weights.get(snap["source"], 0.0))
            for snap in snapshots
        )
        risk_grade_price = None
        if risk_rows:
            risk_grade_price = sum(
                float(_to_decimal(snap["price_points"], name="price_points", minimum=0.00000001)) * float(risk_weights.get(snap["source"], 0.0))
                for snap in risk_snapshots
            )

        if any(bool(snap.get("orderbook_truncated")) or bool(snap.get("coverage_insufficient")) for snap in snapshots):
            warnings = self._append_price_fusion_warning(
                warnings,
                "provider_coverage_partial",
                "部分來源資料截斷，不代表該交易所真實深度不足；reference price 仍會納入，但不作為高風險風控權重。",
            )
        reference_sources = {snap["source"] for snap in snapshots}
        risk_sources = {snap["source"] for snap in risk_snapshots}
        conservative_mode = len(risk_sources) < min_provider_count
        if conservative_mode:
            warnings = self._append_price_fusion_warning(
                warnings,
                "provider_count_low",
                f"風控級可用 order book 來源只剩 {len(risk_sources)} 家，低於建議下限 {min_provider_count} 家",
                severity="critical",
            )

        for source, _fetcher in fetchers:
            if source in reference_sources or source in provider_failures:
                continue
            if any(str(item.get("source") or "") == source for item in excluded_providers if isinstance(item, dict)):
                continue
            if mode == "manual_weights" and float(weight_map.get(source, 0.0)) <= 0:
                excluded_providers.append({
                    "source": source,
                    "label": PRICE_PROVIDER_LABELS.get(source, source),
                    "reason": "manual_weight_zero",
                    "error": "",
                    "manual_weight": round(float(weight_map.get(source, 0.0)), 8),
                })

        primary_warning = self._primary_price_fusion_warning(warnings)
        warning_message = "；".join(
            warning.get("message") or ""
            for warning in warnings
            if isinstance(warning, dict) and str(warning.get("message") or "").strip()
        )
        degraded = bool(excluded_providers) or bool(warnings) or reference_model["resolved_mode"] != mode or conservative_mode
        reference_value = float(Decimal(str(reference_price)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))
        risk_value = float(Decimal(str(risk_grade_price)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)) if risk_grade_price is not None else None
        return reference_value, {
            "requested_mode": mode,
            "mode": reference_model["resolved_mode"],
            "reference_mode": "reference_price",
            "risk_grade_mode": risk_model["resolved_mode"] if risk_model else "unavailable",
            "warnings": warnings,
            "warning_code": str(primary_warning.get("code") or ""),
            "warning_message": warning_message,
            "degraded": degraded,
            "fallback_active": reference_model["resolved_mode"] in {"auto_depth_fallback", "equal_weight_fallback"},
            "conservative_mode": conservative_mode,
            "high_risk_blocked": conservative_mode,
            "high_risk_block_reason": "目前風控級可用來源數不足，只能提供 reference price" if conservative_mode else "",
            "reference_price_points": reference_value,
            "risk_grade_price_points": risk_value,
            "reference_provider_count": len(reference_sources),
            "risk_grade_provider_count": len(risk_sources),
            "providers_used": [
                {
                    "source": snap["source"],
                    "label": PRICE_PROVIDER_LABELS.get(snap["source"], snap["source"]),
                    "price_points": float(_to_decimal(snap["price_points"], name="price_points", minimum=0.00000001)),
                    "midpoint_points": round(float(snap.get("midpoint_points") or snap["price_points"]), 8),
                    "best_bid_points": round(float(snap.get("best_bid_points") or 0.0), 8),
                    "best_ask_points": round(float(snap.get("best_ask_points") or 0.0), 8),
                    "spread_points": round(float(snap.get("spread_points") or 0.0), 8),
                    "spread_percent": round(float(snap.get("spread_percent") or 0.0), 8),
                    "bid_notional_points": round(float(snap.get("bid_notional_points") or 0.0), 8),
                    "ask_notional_points": round(float(snap.get("ask_notional_points") or 0.0), 8),
                    "depth_score": round(float(snap.get("depth_score") or 0.0), 8),
                    "effective_depth_score": round(float(self._price_fusion_effective_score(snap)), 8),
                    "depth_density_score": round(float(snap.get("depth_density_score") or 0.0), 8),
                    "weight": round(float(reference_weights.get(snap["source"], 0.0)), 8),
                    "raw_weight": round(float(reference_raw_map.get(snap["source"], 0.0)), 8),
                    "normalized_weight": round(float(reference_weights.get(snap["source"], 0.0)), 8),
                    "raw_normalized_weight": round((float(reference_raw_map.get(snap["source"], 0.0)) / reference_total_raw_weight) if reference_total_raw_weight > 0 else 0.0, 8),
                    "normalized_weight_percent": round(float(reference_weights.get(snap["source"], 0.0)) * 100.0, 4),
                    "raw_normalized_weight_percent": round(((float(reference_raw_map.get(snap["source"], 0.0)) / reference_total_raw_weight) * 100.0) if reference_total_raw_weight > 0 else 0.0, 4),
                    "reference_weight_percent": round(float(reference_weights.get(snap["source"], 0.0)) * 100.0, 4),
                    "risk_grade_weight_percent": round(float(risk_weights.get(snap["source"], 0.0)) * 100.0, 4),
                    "risk_grade_eligible": bool(snap.get("risk_grade_eligible")),
                    "coverage_insufficient": bool(snap.get("coverage_insufficient")),
                    "coverage_warning_message": str(snap.get("coverage_warning_message") or ""),
                    "weight_cap_applied": abs(float(reference_weights.get(snap["source"], 0.0)) - ((float(reference_raw_map.get(snap["source"], 0.0)) / reference_total_raw_weight) if reference_total_raw_weight > 0 else 0.0)) > 1e-12,
                    "fetched_at": str(snap.get("fetched_at") or ""),
                    "age_seconds": round(float(snap.get("age_seconds") or 0.0), 3),
                    "latency_ms": round(float(snap.get("latency_ms") or 0.0), 2),
                    "midpoint_deviation_percent": round(float(snap.get("midpoint_deviation_percent") or 0.0), 8),
                    "raw_bid_levels_count": int(snap.get("raw_bid_levels_count") or 0),
                    "raw_ask_levels_count": int(snap.get("raw_ask_levels_count") or 0),
                    "used_bid_levels_count": int(snap.get("used_bid_levels_count") or 0),
                    "used_ask_levels_count": int(snap.get("used_ask_levels_count") or 0),
                    "depth_levels_requested": int(snap.get("depth_levels_requested") or depth_levels),
                    "provider_depth_request_limit": int(snap.get("provider_depth_request_limit") or snap.get("depth_levels_requested") or depth_levels),
                    "provider_depth_limit_reached": bool(snap.get("provider_depth_limit_reached")),
                    "depth_band_percent": round(float(snap.get("depth_band_percent") or DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT), 4),
                    "bid_coverage_percent": round(float(snap.get("bid_coverage_percent") or 0.0), 6),
                    "ask_coverage_percent": round(float(snap.get("ask_coverage_percent") or 0.0), 6),
                    "bid_reached_lower_bound": bool(snap.get("bid_reached_lower_bound")),
                    "ask_reached_upper_bound": bool(snap.get("ask_reached_upper_bound")),
                    "orderbook_truncated": bool(snap.get("orderbook_truncated")),
                    "coverage_ratio_percent": round(float(snap.get("coverage_ratio_percent") or 0.0), 4),
                    "side_balance_ratio_percent": round(float(snap.get("side_balance_ratio_percent") or 0.0), 4),
                    "quantity_unit": str(snap.get("quantity_unit") or "base_asset"),
                    "quantity_unit_label": str(snap.get("quantity_unit_label") or "base asset"),
                    "quantity_unit_confirmed": bool(snap.get("quantity_unit_confirmed")),
                    "quantity_unit_note": str(snap.get("quantity_unit_note") or ""),
                    "contract_size_adjusted": bool(snap.get("contract_size_adjusted")),
                }
                for snap in snapshots
            ],
            "excluded_providers": excluded_providers,
            "provider_errors": errors,
            "resolved_source": FUSED_PRICE_SOURCE,
            "depth_levels": depth_levels,
            "depth_band_percent": round(float(depth_band_percent), 4),
            "min_orderbook_coverage_percent": round(float(min_orderbook_coverage_percent), 4),
            "max_single_provider_weight_percent": round(float(max_single_provider_weight_percent), 4),
            "min_provider_count": min_provider_count,
            "median_midpoint_points": round(float(median_midpoint), 8),
            "reference_weights_sum_percent": round(sum(float(reference_weights.get(snap["source"], 0.0)) * 100.0 for snap in snapshots), 4),
            "risk_grade_weights_sum_percent": round(sum(float(risk_weights.get(snap["source"], 0.0)) * 100.0 for snap in snapshots), 4),
        }

    def _default_price_fusion_market_symbol(self, conn):
        rows = conn.execute("SELECT symbol FROM trading_markets").fetchall()
        sorted_symbols = sorted((str(row["symbol"] or "").strip().upper() for row in rows), key=market_sort_key)
        for symbol in sorted_symbols:
            if self._live_price_symbol(symbol):
                return symbol
        catalog_symbols = list_live_price_markets()
        return catalog_symbols[0] if catalog_symbols else ""

    def _root_price_fusion_status_on_conn(self, conn, *, market_symbol=""):
        settings = self._settings_payload(conn)
        configured_source = str(settings.get("price_source") or FUSED_PRICE_SOURCE)
        requested_mode = str(settings.get("price_fusion_mode") or "auto_depth")
        requested_symbol = str(market_symbol or "").strip().upper()
        resolved_symbol = normalize_market_symbol(requested_symbol) if requested_symbol else ""
        symbol = resolved_symbol or self._default_price_fusion_market_symbol(conn)
        display_symbol = market_display_symbol(symbol)
        live_supported = bool(symbol and self._live_price_symbol(symbol))
        payload = {
            "configured_source": configured_source,
            "configured_source_label": PRICE_PROVIDER_LABELS.get(configured_source, configured_source),
            "requested_mode": requested_mode,
            "market_symbol": symbol,
            "requested_market_symbol": requested_symbol,
            "resolved_market_symbol": symbol,
            "display_market_symbol": display_symbol,
            "live_supported": live_supported,
            "providers_configured": list(WEIGHTED_PRICE_PROVIDERS),
            "manual_weights": self._price_fusion_manual_weights(settings),
            "depth_levels": self._price_fusion_depth_levels(settings),
            "depth_band_percent": float(settings.get("price_fusion_depth_band_percent") or DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT),
            "max_single_provider_weight_percent": float(settings.get("price_fusion_max_single_provider_weight_percent") or DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT),
            "max_provider_age_seconds": int(settings.get("price_fusion_max_provider_age_seconds") or DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS),
            "max_provider_latency_ms": int(settings.get("price_fusion_max_provider_latency_ms") or DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS),
            "max_midpoint_deviation_percent": float(settings.get("price_fusion_max_midpoint_deviation_percent") or DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT),
            "min_side_balance_ratio_percent": float(settings.get("price_fusion_min_side_balance_ratio_percent") or round(DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2)),
            "min_provider_count": int(settings.get("price_fusion_min_provider_count") or DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT),
        }
        if configured_source != FUSED_PRICE_SOURCE:
            payload.update({
                "state": "inactive",
                "message": "目前價格來源不是融合價格；只有切回融合價格後才會計算各 API 即時占比。",
                "degraded": False,
                "fallback_active": False,
                "conservative_mode": False,
                "weights_sum_percent": 0.0,
                "providers_used": [],
                "excluded_providers": [],
                "resolved_mode": requested_mode,
                "resolved_source": configured_source,
                "price_points": None,
            })
            return payload
        if not live_supported:
            payload.update({
                "state": "unsupported",
                "message": "這個市場目前沒有支援即時融合價格來源。",
                "degraded": True,
                "fallback_active": False,
                "conservative_mode": False,
                "weights_sum_percent": 0.0,
                "providers_used": [],
                "excluded_providers": [],
                "resolved_mode": requested_mode,
                "resolved_source": FUSED_PRICE_SOURCE,
                "price_points": None,
            })
            return payload
        price_points, details = self._fetch_weighted_fused_price_points(symbol, settings=settings)
        providers_used = list((details or {}).get("providers_used") or [])
        weights_sum_percent = round(sum(float(row.get("normalized_weight_percent") or 0.0) for row in providers_used), 4)
        degraded = bool((details or {}).get("degraded"))
        conservative_mode = bool((details or {}).get("conservative_mode"))
        high_risk_blocked = bool((details or {}).get("high_risk_blocked"))
        high_risk_block_reason = str((details or {}).get("high_risk_block_reason") or "").strip()
        warnings = list((details or {}).get("warnings") or [])
        warning_message = str((details or {}).get("warning_message") or "").strip()
        if conservative_mode and not warning_message:
            warning_message = "價格來源降級：目前已退回單一 ticker，建議暫停高風險交易。"
        elif degraded and not warning_message and (details or {}).get("excluded_providers"):
            warning_message = "部分交易所來源已被排除，系統已用剩餘健康來源重新分配權重。"
        payload.update({
            "state": "conservative" if conservative_mode else ("degraded" if degraded else "healthy"),
            "message": warning_message,
            "degraded": degraded,
            "fallback_active": bool((details or {}).get("fallback_active")),
            "conservative_mode": conservative_mode,
            "high_risk_blocked": high_risk_blocked,
            "high_risk_block_reason": high_risk_block_reason,
            "weights_sum_percent": weights_sum_percent,
            "providers_used": providers_used,
            "excluded_providers": list((details or {}).get("excluded_providers") or []),
            "resolved_mode": str((details or {}).get("mode") or requested_mode),
            "reference_mode": str((details or {}).get("reference_mode") or "reference_price"),
            "risk_grade_mode": str((details or {}).get("risk_grade_mode") or "unavailable"),
            "resolved_source": str((details or {}).get("resolved_source") or FUSED_PRICE_SOURCE),
            "price_points": float(_to_decimal(price_points, name="price_points", minimum=0.00000001)),
            "reference_price_points": (details or {}).get("reference_price_points"),
            "risk_grade_price_points": (details or {}).get("risk_grade_price_points"),
            "reference_provider_count": int((details or {}).get("reference_provider_count") or 0),
            "risk_grade_provider_count": int((details or {}).get("risk_grade_provider_count") or 0),
            "median_midpoint_points": (details or {}).get("median_midpoint_points"),
            "warnings": warnings,
            "warning_code": str((details or {}).get("warning_code") or ""),
            "provider_errors": list((details or {}).get("provider_errors") or []),
            "reference_weights_sum_percent": float((details or {}).get("reference_weights_sum_percent") or 0.0),
            "risk_grade_weights_sum_percent": float((details or {}).get("risk_grade_weights_sum_percent") or 0.0),
        })
        return payload

    def get_root_price_fusion_status(self, *, market_symbol=""):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._root_price_fusion_status_on_conn(conn, market_symbol=market_symbol)
        finally:
            conn.close()

    def get_live_market_quote(self, *, market_symbol=""):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            requested_symbol = str(market_symbol or "").strip().upper()
            symbol = normalize_market_symbol(requested_symbol)
            defaulted_market = not bool(symbol)
            if symbol:
                market_row = self._market(conn, symbol)
            else:
                market_row = conn.execute(
                    "SELECT * FROM trading_markets WHERE enabled=1 AND spot_enabled=1"
                ).fetchall()
                market_row = next(iter(sorted(market_row, key=lambda row: market_sort_key(row["symbol"]))), None)
                if not market_row:
                    raise ValueError("market not found")
            market = self._market_payload(market_row)
            current_price, price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True)
            updated_row = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (market["symbol"],)).fetchone()
            conn.commit()
            payload = self._market_payload(updated_row or market_row)
            payload["manual_price_points"] = current_price
            payload["price_source"] = str(price_source or payload.get("price_source") or "manual_root")
            resolved_symbol = str(payload.get("symbol") or "").strip().upper()
            reference_context = self._build_price_context(
                market_symbol=resolved_symbol,
                price_type="reference",
                price_points=(price_meta or {}).get("reference_price_points") if price_meta else current_price,
                price_source=payload["price_source"],
                price_meta=price_meta,
            )
            risk_grade_context = self._build_price_context(
                market_symbol=resolved_symbol,
                price_type="risk_grade",
                price_points=(price_meta or {}).get("risk_grade_price_points") if price_meta else current_price,
                price_source=payload["price_source"],
                price_meta=price_meta,
            )
            payload = self._attach_market_price_contexts(
                payload,
                reference_context=reference_context,
                risk_grade_context=risk_grade_context,
            )
            return {
                "market": payload,
                "requested_market_symbol": requested_symbol,
                "resolved_market_symbol": resolved_symbol,
                "display_market_symbol": market_display_symbol(resolved_symbol),
                "refresh_interval_ms": 2000,
                "server_time": _now(),
                "price_type": reference_context["price_type"],
                "source": reference_context["source"],
                "confidence": reference_context["confidence"],
                "stale": reference_context["stale"],
                "degraded": reference_context["degraded"],
                "provider_count": reference_context["provider_count"],
                "price_health": str((price_meta or {}).get("price_health") or "healthy"),
                "fallback_reason": str((price_meta or {}).get("fallback_reason") or ""),
                "excluded_sources": list((price_meta or {}).get("excluded_sources") or []),
                "warnings": list((price_meta or {}).get("warnings") or []),
                "high_risk_blocked": bool((price_meta or {}).get("high_risk_blocked")),
                "high_risk_block_reason": str((price_meta or {}).get("high_risk_block_reason") or ""),
                "defaulted_market": defaulted_market,
                "reference_price_context": reference_context,
                "risk_grade_price_context": risk_grade_context,
            }
        finally:
            conn.close()

    def _fetch_live_price_points(self, market_symbol):
        market_symbol = normalize_market_symbol(market_symbol)
        if not self._live_price_symbol(market_symbol):
            raise ValueError("live price is not supported for this market")
        if self.live_price_provider:
            price = self.live_price_provider(market_symbol)
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
        if self.live_price_provider:
            return []
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
                    "time_ms": int(item[0]),
                    "open_points": float(item[1]) * USDT_TO_POINTS_RATE,
                    "high_points": float(item[2]) * USDT_TO_POINTS_RATE,
                    "low_points": float(item[3]) * USDT_TO_POINTS_RATE,
                    "close_points": float(item[4]) * USDT_TO_POINTS_RATE,
                })
            except Exception:
                continue
        return candles

    def _parse_candle_time_ms(self, candle, *, interval_seconds=60):
        if not isinstance(candle, dict):
            return None
        raw = candle.get("time_ms")
        if raw not in (None, ""):
            try:
                return int(raw)
            except Exception:
                return None
        raw = candle.get("time_iso")
        if raw:
            try:
                return int(datetime.fromisoformat(str(raw)).timestamp() * 1000)
            except Exception:
                return None
        raw = candle.get("time")
        if raw in (None, ""):
            return None
        try:
            value = float(raw)
        except Exception:
            return None
        if value > 10**12:
            return int(value)
        if value > 10**9:
            return int(value * 1000)
        if value > 10**6:
            return int(value)
        return int(value * 1000)

    def _recent_price_window(self, market_symbol, *, lookback_seconds=60, since_time_text=None, interval="1m"):
        lookback = max(60, int(lookback_seconds or 60))
        interval_seconds = 60 if interval == "1m" else 900
        limit = max(2, min(int(math.ceil(lookback / interval_seconds)) + 2, 240))
        candles = self._fetch_indicator_candles(market_symbol, limit=limit, interval=interval)
        if not candles:
            return None
        since_ms = None
        if since_time_text:
            try:
                since_ms = int(datetime.fromisoformat(str(since_time_text)).timestamp() * 1000)
            except Exception:
                since_ms = None
        lows = []
        highs = []
        included = 0
        for candle in candles:
            if not isinstance(candle, dict):
                continue
            start_ms = self._parse_candle_time_ms(candle, interval_seconds=interval_seconds)
            if since_ms is not None and start_ms is not None and (start_ms + interval_seconds * 1000) <= since_ms:
                continue
            try:
                low_value = _to_decimal(candle.get("low_points") or candle.get("low_usdt") or 0, name="low_points", minimum=0)
                high_value = _to_decimal(candle.get("high_points") or candle.get("high_usdt") or 0, name="high_points", minimum=0)
            except Exception:
                continue
            if low_value <= 0 or high_value <= 0:
                continue
            lows.append(low_value)
            highs.append(high_value)
            included += 1
        if not lows or not highs:
            return None
        return {
            "interval": interval,
            "lookback_seconds": lookback,
            "candle_count": included,
            "low_points": float(min(lows)),
            "high_points": float(max(highs)),
        }

    def _workflow_live_context(self, conn, *, market, user_id, observed_price, observed_low=None, observed_high=None):
        position = self._position(conn, int(user_id), market["symbol"])
        qty = int(position["quantity_units"] or 0)
        locked = int(position["locked_quantity_units"] or 0)
        avg_cost = float(_to_decimal(position["avg_cost_points"] or 0, name="avg_cost_points", minimum=0))
        has_pos = qty > locked
        low_price = float(observed_low or observed_price or 0)
        high_price = float(observed_high or observed_price or 0)
        pnl_percent = None
        pnl_low_percent = None
        pnl_high_percent = None
        if has_pos and avg_cost > 0 and observed_price and observed_price > 0:
            pnl_percent = round((observed_price - avg_cost) * 100.0 / avg_cost, 4)
            if low_price > 0:
                pnl_low_percent = round((low_price - avg_cost) * 100.0 / avg_cost, 4)
            if high_price > 0:
                pnl_high_percent = round((high_price - avg_cost) * 100.0 / avg_cost, 4)
        context = {
            "price": observed_price,
            "window_low_price": low_price or observed_price,
            "window_high_price": high_price or observed_price,
            "has_position": has_pos,
            "avg_cost": avg_cost,
            "pnl_percent": pnl_percent,
            "pnl_low_percent": pnl_low_percent,
            "pnl_high_percent": pnl_high_percent,
        }
        try:
            candles = self._fetch_indicator_candles(market["symbol"])
            if candles:
                latest = dict(candles[-1])
                latest["close_points"] = observed_price
                candles = [*candles[:-1], latest]
                context.update(self._workflow_indicator_context(candles, len(candles) - 1))
                context["price"] = observed_price
                context["window_low_price"] = low_price or observed_price
                context["window_high_price"] = high_price or observed_price
                context["has_position"] = int(position["quantity_units"] or 0) > int(position["locked_quantity_units"] or 0)
                context["pnl_percent"] = pnl_percent
                context["pnl_low_percent"] = pnl_low_percent
                context["pnl_high_percent"] = pnl_high_percent
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

    def _current_market_price_points(self, conn, market, *, with_meta=False, high_risk=False):
        symbol = market["symbol"]
        settings = self._settings_payload(conn)
        configured_source = settings.get("price_source") or FUSED_PRICE_SOURCE
        price_meta = {
            "price_health": "healthy",
            "fallback_reason": "",
            "excluded_sources": [],
            "warnings": [],
            "high_risk_blocked": False,
            "high_risk_block_reason": "",
            "requested_price_mode": "risk_grade" if high_risk else "reference",
            "reference_price_points": None,
            "risk_grade_price_points": None,
            "resolved_source": "",
            "reference_provider_count": 0,
            "risk_grade_provider_count": 0,
            "stale": False,
            "degraded": False,
        }
        if configured_source == "manual_root" or not self._live_price_symbol(symbol):
            price = market["manual_price_points"]
            source = str(market["price_source"] or "manual_root")
            price_meta["reference_price_points"] = float(Decimal(str(price or "0")))
            price_meta["risk_grade_price_points"] = float(Decimal(str(price or "0")))
            price_meta["resolved_source"] = source
            price_meta["degraded"] = True
            price_meta["warnings"] = self._append_price_fusion_warning(
                price_meta.get("warnings"),
                "manual_price_active",
                "目前使用手動價格，請勿將此價格視為正常即時市場深度。",
                severity="warning",
            )
            price_meta["fallback_reason"] = "目前使用手動價格"
            return (price, source, price_meta) if with_meta else (price, source)
        old_price_decimal = Decimal(str(market["manual_price_points"] or "0"))
        old_price = float(old_price_decimal)
        old_source = str(market["price_source"] or "")
        fusion_details = None
        try:
            if self.live_price_provider:
                price, live_source = self._fetch_live_price_points(symbol)
            elif configured_source == FUSED_PRICE_SOURCE:
                price, fusion_details = self._fetch_weighted_fused_price_points(symbol, settings=settings)
                live_source = str((fusion_details or {}).get("resolved_source") or FUSED_PRICE_SOURCE)
            else:
                price, live_source = self._fetch_live_price_points(symbol)
        except Exception as exc:
            max_stale = int(settings.get("max_price_staleness_seconds") or 0)
            try:
                updated_at = datetime.fromisoformat(str(market["updated_at"]))
                stale_seconds = int((datetime.now() - updated_at).total_seconds())
            except Exception:
                stale_seconds = max_stale + 1
            cached_source = old_source[:-7] if old_source.endswith("_cached") else old_source
            if old_price_decimal > 0 and max_stale > 0 and stale_seconds <= max_stale and cached_source in LIVE_PRICE_SOURCE_NAMES:
                source = f"{cached_source}_cached"
                price_meta.update({
                    "price_health": "fallback",
                    "fallback_reason": str(exc),
                    "excluded_sources": [],
                    "reference_price_points": old_price,
                    "risk_grade_price_points": old_price,
                    "resolved_source": source,
                    "reference_provider_count": 1,
                    "risk_grade_provider_count": 1,
                    "stale": True,
                    "degraded": True,
                })
                self._audit_event(
                    conn,
                    "TRADING_PRICE_FALLBACK_USED",
                    "live trading price unavailable; using cached last-good price",
                    market_symbol=symbol,
                    severity="warning",
                    metadata={"error": str(exc), "cached_price_points": old_price, "stale_seconds": stale_seconds, "max_stale_seconds": max_stale},
                )
                return (old_price, source, price_meta) if with_meta else (old_price, source)
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
        if old_price_decimal > 0 and old_source in LIVE_PRICE_SOURCE_NAMES and has_live_history:
            jump_percent = float((abs(Decimal(str(price)) - old_price_decimal) * Decimal("100")) / old_price_decimal)
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
        if configured_source == FUSED_PRICE_SOURCE and fusion_details and (
            fusion_details.get("degraded") or fusion_details.get("warning_code") or fusion_details.get("excluded_providers")
        ):
            warnings = list(fusion_details.get("warnings") or [])
            primary_warning = self._primary_price_fusion_warning(warnings)
            conservative_mode = bool(fusion_details.get("conservative_mode"))
            fallback_active = bool(fusion_details.get("fallback_active"))
            price_health = "conservative" if conservative_mode else ("fallback" if fallback_active else "degraded")
            reason_text = str(
                fusion_details.get("high_risk_block_reason")
                or fusion_details.get("warning_message")
                or primary_warning.get("message")
                or primary_warning.get("code")
                or ""
            )
            price_meta.update({
                "price_health": price_health,
                "fallback_reason": reason_text,
                "excluded_sources": [
                    str(item.get("source") or "")
                    for item in (fusion_details.get("excluded_providers") or [])
                    if str(item.get("source") or "").strip()
                ],
                "warnings": warnings,
                "high_risk_blocked": bool(fusion_details.get("high_risk_blocked")),
                "high_risk_block_reason": str(fusion_details.get("high_risk_block_reason") or ""),
                "reference_price_points": fusion_details.get("reference_price_points"),
                "risk_grade_price_points": fusion_details.get("risk_grade_price_points"),
                "resolved_source": str(fusion_details.get("resolved_source") or live_source or FUSED_PRICE_SOURCE),
                "reference_provider_count": int(fusion_details.get("reference_provider_count") or 0),
                "risk_grade_provider_count": int(fusion_details.get("risk_grade_provider_count") or 0),
                "stale": False,
                "degraded": True,
            })
            self._audit_event(
                conn,
                "TRADING_PRICE_FUSION_DEGRADED",
                "fused trading price degraded or partially excluded providers",
                market_symbol=symbol,
                severity="critical" if fusion_details.get("conservative_mode") else "warning",
                metadata={
                    "resolved_source": live_source,
                    "requested_mode": fusion_details.get("requested_mode"),
                    "resolved_mode": fusion_details.get("mode"),
                    "warning_code": fusion_details.get("warning_code"),
                    "warnings": warnings,
                    "warning_message": fusion_details.get("warning_message"),
                    "excluded_providers": fusion_details.get("excluded_providers"),
                    "providers_used": fusion_details.get("providers_used"),
                    "provider_errors": fusion_details.get("provider_errors"),
                    "fallback_active": bool(fusion_details.get("fallback_active")),
                    "conservative_mode": bool(fusion_details.get("conservative_mode")),
                    "high_risk_blocked": bool(fusion_details.get("high_risk_blocked")),
                    "high_risk_block_reason": str(fusion_details.get("high_risk_block_reason") or ""),
                    "requested_price_mode": "risk_grade" if high_risk else "reference",
                    "reference_price_points": fusion_details.get("reference_price_points"),
                    "risk_grade_price_points": fusion_details.get("risk_grade_price_points"),
                },
            )
        elif configured_source == FUSED_PRICE_SOURCE and fusion_details:
            price_meta.update({
                "reference_price_points": fusion_details.get("reference_price_points"),
                "risk_grade_price_points": fusion_details.get("risk_grade_price_points"),
                "resolved_source": str(fusion_details.get("resolved_source") or live_source or FUSED_PRICE_SOURCE),
                "reference_provider_count": int(fusion_details.get("reference_provider_count") or 0),
                "risk_grade_provider_count": int(fusion_details.get("risk_grade_provider_count") or 0),
                "stale": False,
                "degraded": False,
            })
        else:
            live_price = float(_to_decimal(price, name="live_price_points", minimum=0.00000001))
            price_meta["reference_price_points"] = live_price
            price_meta["risk_grade_price_points"] = live_price
            price_meta["resolved_source"] = str(live_source or configured_source or "manual_root")
            price_meta["reference_provider_count"] = 1
            price_meta["risk_grade_provider_count"] = 1
            price_meta["stale"] = False
            price_meta["degraded"] = False
        if configured_source == FUSED_PRICE_SOURCE and fusion_details and high_risk and fusion_details.get("risk_grade_price_points") is not None:
            price = float(_to_decimal(fusion_details.get("risk_grade_price_points"), name="risk_grade_price_points", minimum=0.00000001))
        now = _now()
        conn.execute(
            "UPDATE trading_markets SET manual_price_points=?, price_source=?, updated_at=? WHERE symbol=?",
            (price, live_source, now, symbol),
        )
        return (price, live_source, price_meta) if with_meta else (price, live_source)

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
        avg_cost = float(_to_decimal(item["avg_cost_points"] or 0, name="avg_cost_points", minimum=0))
        reference_price = float(
            _to_decimal(
                (market or {}).get("reference_price_points")
                or (market or {}).get("manual_price_points")
                or 0,
                name="reference_price_points",
                minimum=0,
            )
        )
        risk_grade_price = float(
            _to_decimal(
                (market or {}).get("risk_grade_price_points")
                or (market or {}).get("reference_price_points")
                or (market or {}).get("manual_price_points")
                or 0,
                name="risk_grade_price_points",
                minimum=0,
            )
        )
        fee_rate_percent = float((market or {}).get("fee_rate_percent") or 0)
        gross_cost = notional_points(quantity_units, avg_cost) if quantity_units and avg_cost else 0
        reference_current_value = notional_points(quantity_units, reference_price) if quantity_units and reference_price else 0
        risk_grade_current_value = notional_points(quantity_units, risk_grade_price) if quantity_units and risk_grade_price else 0
        estimated_buy_fee = fee_points(gross_cost, fee_rate_percent) if gross_cost else 0
        reference_exit_fee = fee_points(reference_current_value, fee_rate_percent) if reference_current_value else 0
        risk_grade_exit_fee = fee_points(risk_grade_current_value, fee_rate_percent) if risk_grade_current_value else 0
        reference_cost_basis = gross_cost + estimated_buy_fee + reference_exit_fee
        risk_grade_cost_basis = gross_cost + estimated_buy_fee + risk_grade_exit_fee
        reference_unrealized = reference_current_value - reference_cost_basis if quantity_units else 0
        risk_grade_unrealized = risk_grade_current_value - risk_grade_cost_basis if quantity_units else 0
        item.update({
            "available_quantity_units": int(item["quantity_units"] or 0),
            "total_quantity_units": quantity_units,
            "total_quantity": units_to_quantity(quantity_units),
            "reference_price_points": reference_price,
            "risk_grade_price_points": risk_grade_price,
            "current_price_points": reference_price,
            "gross_cost_points": gross_cost,
            "reference_current_value_points": reference_current_value,
            "current_value_points": reference_current_value,
            "risk_grade_current_value_points": risk_grade_current_value,
            "estimated_buy_fee_points": estimated_buy_fee,
            "reference_estimated_exit_fee_points": reference_exit_fee,
            "estimated_exit_fee_points": risk_grade_exit_fee,
            "reference_cost_basis_points": reference_cost_basis,
            "cost_basis_points": risk_grade_cost_basis,
            "reference_unrealized_pnl_points": reference_unrealized,
            "risk_grade_unrealized_pnl_points": risk_grade_unrealized,
            "unrealized_pnl_points": risk_grade_unrealized,
            "realized_pnl_points": int(realized_points or 0),
            "total_pnl_points": int(realized_points or 0) + risk_grade_unrealized,
            "total_fee_points": int(total_fees or 0),
            "reference_price_context": (market or {}).get("reference_price_context") if isinstance(market, dict) else None,
            "risk_grade_price_context": (market or {}).get("risk_grade_price_context") if isinstance(market, dict) else None,
        })
        item["pnl_percent"] = round((risk_grade_unrealized / risk_grade_cost_basis) * 100, 4) if risk_grade_cost_basis else 0
        return item

    def _futures_position_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        return item

    def _margin_position_payload(self, row):
        item = dict(row)
        item["quantity"] = units_to_quantity(item["quantity_units"])
        item["position_label"] = "融資做多" if item["position_type"] == "margin_long" else "借券放空"
        item["exit_price_points"] = float(_to_decimal(item.get("exit_price_points") or 0, name="exit_price_points", minimum=0)) if item.get("exit_price_points") is not None else None
        item["realized_pnl_points"] = int(item.get("realized_pnl_points") or 0)
        item["borrowed_asset_symbol"] = str(item.get("borrowed_asset_symbol") or ("POINTS" if item.get("position_type") == "margin_long" else "")).upper()
        item["interest_interval_hours"] = int(item.get("interest_interval_hours") or DEFAULT_BORROW_INTEREST_INTERVAL_HOURS)
        item["interest_minimum_hours"] = int(item.get("interest_minimum_hours") or DEFAULT_BORROW_INTEREST_MINIMUM_HOURS)
        item["interest_capitalized_points"] = int(item.get("interest_points") or 0)
        item["interest_paid_points"] = int(item.get("interest_paid_points") or 0)
        item["interest_accrued_hours"] = int(item.get("interest_accrued_hours") or 0)
        item["interest_carry_micropoints"] = int(item.get("interest_carry_micropoints") or 0)
        item["interest_apr_percent"] = round(_apr_percent_from_daily(item.get("interest_percent_daily") or 0), 6)
        item["interest_exact_points"] = round(
            item["interest_capitalized_points"] + (item["interest_carry_micropoints"] / POINT_MICRO_SCALE),
            6,
        )
        # Compute total elapsed hours and next interest tick
        try:
            opened_at_dt = datetime.fromisoformat(str(item.get("opened_at") or ""))
            now_dt = datetime.fromisoformat(_now())
            elapsed_sec = max(0.0, (now_dt - opened_at_dt).total_seconds())
            # Display: floor (actual full hours elapsed)
            item["total_elapsed_hours"] = int(elapsed_sec / 3600)
            # Next interest tick respects the stored interval/minimum rules for this position.
            next_billing_hours = _billable_interest_hours_from_elapsed_seconds(
                elapsed_sec,
                interval_hours=item["interest_interval_hours"],
                minimum_hours=item["interest_minimum_hours"],
            )
            if next_billing_hours and next_billing_hours <= item["interest_accrued_hours"]:
                next_billing_hours = item["interest_accrued_hours"] + item["interest_interval_hours"]
            item["next_interest_at"] = (opened_at_dt + timedelta(seconds=next_billing_hours * 3600)).isoformat() if next_billing_hours > 0 else None
        except Exception:
            item["total_elapsed_hours"] = 0
            item["next_interest_at"] = None
        return item

    def _margin_trade_records(self, conn, user_id, *, limit=50):
        records = []
        rows = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (int(user_id), int(limit)),
        ).fetchall()
        for row in rows:
            payload = self._margin_position_payload(row)
            label = payload["position_label"]
            entry_price = float(_to_decimal(row["entry_price_points"] or 0, name="entry_price_points", minimum=0))
            notional = notional_points(int(row["quantity_units"] or 0), entry_price)
            records.append({
                "record_type": "margin_open",
                "fill_uuid": f"margin-open:{row['position_uuid']}",
                "position_uuid": row["position_uuid"],
                "side": f"{label}開倉",
                "market_symbol": row["market_symbol"],
                "quantity": payload["quantity"],
                "price_points": entry_price,
                "notional_points": notional,
                "fee_points": int(row["open_fee_points"] or 0),
                "interest_points": 0,
                "realized_pnl_points": 0,
                "status": "open",
                "created_at": row["opened_at"],
            })
            if row["closed_at"]:
                close_type = "margin_liquidation" if row["status"] == "liquidated" else "margin_close"
                records.append({
                    "record_type": close_type,
                    "fill_uuid": f"{close_type}:{row['position_uuid']}",
                    "position_uuid": row["position_uuid"],
                    "side": f"{label}{'強平' if row['status'] == 'liquidated' else '平倉'}",
                    "market_symbol": row["market_symbol"],
                    "quantity": payload["quantity"],
                    "price_points": float(_to_decimal(row["exit_price_points"] or 0, name="exit_price_points", minimum=0)),
                    "notional_points": notional_points(
                        int(row["quantity_units"] or 0),
                        float(_to_decimal(row["exit_price_points"] or 0, name="exit_price_points", minimum=0)),
                    ) if row["exit_price_points"] else 0,
                    "fee_points": int(row["close_fee_points"] or 0),
                    "interest_points": int(row["interest_points"] or 0),
                    "realized_pnl_points": int(row["realized_pnl_points"] or 0),
                    "status": row["status"],
                    "created_at": row["closed_at"],
                })
        return sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:int(limit)]

    def _borrowing_settings(self, conn):
        settings = self._settings_payload(conn)
        return {
            "enabled": bool(settings.get("borrowing_enabled")),
            "borrow_apr_btc_eth_percent": float(settings.get("borrow_apr_btc_eth_percent") or 0),
            "borrow_apr_usdt_points_percent": float(settings.get("borrow_apr_usdt_points_percent") or 0),
            "interest_percent_daily": float(settings.get("borrow_interest_percent_daily") or 0),
            "pool_pressure_multiplier": float(settings.get("borrow_interest_pool_pressure_multiplier") or 0),
            "interest_interval_hours": int(settings.get("borrow_interest_interval_hours") or DEFAULT_BORROW_INTEREST_INTERVAL_HOURS),
            "interest_minimum_hours": int(settings.get("borrow_interest_minimum_hours") or DEFAULT_BORROW_INTEREST_MINIMUM_HOURS),
        }

    def _assert_borrowing_enabled(self, conn):
        settings = self._borrowing_settings(conn)
        if not settings["enabled"]:
            raise ValueError("borrow trading is disabled")
        return settings

    def _minimum_margin_collateral_points(self, conn, *, position_type, notional, fee_rate_percent=0.0):
        settings = self._settings_payload(conn)
        notional = int(notional or 0)
        maintenance_percent = float(settings.get("margin_maintenance_percent") or 0)
        fee_rate_percent = float(fee_rate_percent or 0)
        safety_minimum = int(math.ceil(notional * max(0.0, maintenance_percent + fee_rate_percent) / 100.0)) + 1
        if position_type == "margin_long":
            financing_percent = float(settings.get("margin_long_financing_percent") or MARGIN_LONG_FINANCING_RATE_PERCENT)
            base_minimum = int(math.ceil(notional * max(0.0, 100.0 - financing_percent) / 100.0))
            return max(base_minimum, safety_minimum)
        short_percent = float(settings.get("short_collateral_percent") or SHORT_COLLATERAL_RATE_PERCENT)
        base_minimum = int(math.ceil(notional * short_percent / 100.0))
        return max(base_minimum, safety_minimum)

    def _margin_interest_total_hours(self, row, now_text=None):
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
        hours = _billable_interest_hours_from_elapsed_seconds(
            seconds,
            interval_hours=int(row["interest_interval_hours"] or DEFAULT_BORROW_INTEREST_INTERVAL_HOURS) if "interest_interval_hours" in row.keys() else DEFAULT_BORROW_INTEREST_INTERVAL_HOURS,
            minimum_hours=int(row["interest_minimum_hours"] or DEFAULT_BORROW_INTEREST_MINIMUM_HOURS) if "interest_minimum_hours" in row.keys() else DEFAULT_BORROW_INTEREST_MINIMUM_HOURS,
        )
        return max(0, hours)

    def _margin_interest_due_points(self, row, *, hours):
        principal = int(row["principal_points"] or 0)
        rate_percent = float(row["interest_percent_daily"] or 0)
        hours = max(0, int(hours or 0))
        if principal <= 0 or rate_percent <= 0 or hours <= 0:
            return 0
        carry = int(row["interest_carry_micropoints"] or 0) if "interest_carry_micropoints" in row.keys() else 0
        total_micro = self._margin_interest_due_micropoints(principal=principal, rate_percent=rate_percent, hours=hours) + carry
        return int(total_micro // POINT_MICRO_SCALE)

    def _margin_interest_due_micropoints(self, *, principal, rate_percent, hours):
        principal = int(principal or 0)
        rate_percent = float(rate_percent or 0)
        hours = max(0, int(hours or 0))
        if principal <= 0 or rate_percent <= 0 or hours <= 0:
            return 0
        hourly_rate = (Decimal(str(rate_percent)) / Decimal("100")) / Decimal("24")
        total_micro = Decimal(principal) * hourly_rate * Decimal(hours) * Decimal(POINT_MICRO_SCALE)
        return int(total_micro.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def _margin_interest_points(self, row, now_text=None):
        accrued_hours = int(row["interest_accrued_hours"] or 0) if "interest_accrued_hours" in row.keys() else 0
        total_hours = self._margin_interest_total_hours(row, now_text=now_text)
        due_hours = max(0, total_hours - accrued_hours)
        capitalized = int(row["interest_points"] or 0)
        carry = int(row["interest_carry_micropoints"] or 0) if "interest_carry_micropoints" in row.keys() else 0
        due_micro = self._margin_interest_due_micropoints(
            principal=int(row["principal_points"] or 0),
            rate_percent=float(row["interest_percent_daily"] or 0),
            hours=due_hours,
        )
        return capitalized + int((carry + due_micro) // POINT_MICRO_SCALE)

    def _accrue_margin_interest(self, conn, position, *, actor=None, now_text=None):
        if not position or position["status"] != "open":
            return position
        if self._is_root_user_id(conn, int(position["user_id"])):
            return position
        total_hours = self._margin_interest_total_hours(position, now_text=now_text)
        accrued_hours = int(position["interest_accrued_hours"] or 0) if "interest_accrued_hours" in position.keys() else 0
        due_hours = max(0, total_hours - accrued_hours)
        if due_hours <= 0:
            return position
        carry = int(position["interest_carry_micropoints"] or 0) if "interest_carry_micropoints" in position.keys() else 0
        due_micro = self._margin_interest_due_micropoints(
            principal=int(position["principal_points"] or 0),
            rate_percent=float(position["interest_percent_daily"] or 0),
            hours=due_hours,
        )
        total_micro = carry + due_micro
        due_points = int(total_micro // POINT_MICRO_SCALE)
        next_carry = int(total_micro % POINT_MICRO_SCALE)
        if due_points <= 0:
            conn.execute(
                "UPDATE trading_margin_positions SET interest_accrued_hours=?, interest_carry_micropoints=?, updated_at=? WHERE id=?",
                (total_hours, next_carry, _now(), position["id"]),
            )
            return conn.execute("SELECT * FROM trading_margin_positions WHERE id=?", (position["id"],)).fetchone()

        user_id = int(position["user_id"])
        wallet = self.points_service.ensure_wallet(conn, user_id)
        available = int(wallet["soft_balance"] or 0) + int(wallet["hard_balance"] or 0)
        paid = min(due_points, available)
        capitalized = due_points - paid
        ledger_uuid = None
        if paid:
            ledger_uuid = self._ledger(
                conn,
                user_id=user_id,
                currency_type="points",
                direction="debit",
                amount=paid,
                action_type="trading_margin_interest_hourly",
                reference_type="trading_margin_position",
                reference_id=position["position_uuid"],
                idempotency_key=f"trading:margin:interest:{position['position_uuid']}:{total_hours}",
                reason="TRADING_MARGIN_HOURLY_INTEREST",
                public_metadata={
                    "market": position["market_symbol"],
                    "position_type": position["position_type"],
                    "charged_hours": due_hours,
                    "total_accrued_hours": total_hours,
                    "capitalized_interest_points": capitalized,
                    "carry_micropoints": next_carry,
                },
                actor=actor,
            )["ledger_uuid"]
            self._reserve_delta(
                conn,
                delta=paid,
                event_type="margin_interest_retained",
                reason="TRADING_MARGIN_HOURLY_INTEREST",
                actor=actor,
                order_id=None,
                fill_id=None,
                points_ledger_uuid=ledger_uuid,
            )

        now = _now()
        conn.execute(
            """
            UPDATE trading_margin_positions
            SET interest_points=interest_points+?,
                interest_paid_points=interest_paid_points+?,
                interest_accrued_hours=?,
                interest_carry_micropoints=?,
                updated_at=?
            WHERE id=?
            """,
            (capitalized, paid, total_hours, next_carry, now, position["id"]),
        )
        self._audit_event(
            conn,
            "TRADING_MARGIN_INTEREST_ACCRUED",
            "margin borrow interest accrued hourly",
            actor=actor,
            target_user_id=user_id,
            market_symbol=position["market_symbol"],
            severity="info" if not capitalized else "warning",
            metadata={
                "position_uuid": position["position_uuid"],
                "due_points": due_points,
                "paid_points": paid,
                "capitalized_points": capitalized,
                "charged_hours": due_hours,
                "total_accrued_hours": total_hours,
                "carry_micropoints": next_carry,
                "ledger_uuid": ledger_uuid,
            },
        )
        return conn.execute("SELECT * FROM trading_margin_positions WHERE id=?", (position["id"],)).fetchone()

    def _margin_risk_payload(self, conn, position, market=None, *, now_text=None, price_override_points=None, price_source_override=None):
        market = market or self._market(conn, position["market_symbol"])
        if price_override_points is None:
            price, price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True, high_risk=True)
        else:
            price = float(_to_decimal(price_override_points, name="price_override_points", minimum=0.00000001))
            price_source = str(price_source_override or "scan_window_replay")
            price_meta = {
                "price_health": "healthy",
                "fallback_reason": "",
                "excluded_sources": [],
                "warnings": [],
                "high_risk_blocked": False,
                "high_risk_block_reason": "",
                "requested_price_mode": "risk_grade",
                "reference_price_points": price,
                "risk_grade_price_points": price,
                "resolved_source": price_source,
                "reference_provider_count": 1,
                "risk_grade_provider_count": 1,
                "stale": False,
                "degraded": False,
            }
        quantity_units = int(position["quantity_units"])
        exit_notional = notional_points(quantity_units, price)
        close_fee = fee_points(exit_notional, float(market["fee_rate_percent"] or 0))
        interest = self._margin_interest_points(position, now_text=now_text)
        collateral = int(position["collateral_points"] or 0)
        principal = int(position["principal_points"] or 0)
        entry_price = float(_to_decimal(position["entry_price_points"] or price, name="entry_price_points", minimum=0.00000001))
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
        fee_rate_decimal = Decimal(str(fee_rate_percent)) / Decimal("100")
        break_even_price_points = None
        quantity_decimal = Decimal(quantity_units)
        if quantity_units > 0:
            if position["position_type"] == "margin_long":
                required_exit_value = Decimal(collateral + principal + int(position["open_fee_points"] or 0)) + Decimal(str(interest))
                denominator = Decimal("1") - fee_rate_decimal
                if denominator > 0:
                    break_even_price_points = float(
                        (
                            required_exit_value * Decimal(ASSET_SCALE) / (quantity_decimal * denominator)
                        ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                    )
            else:
                recoverable_value = Decimal(principal - int(position["open_fee_points"] or 0)) - Decimal(str(interest))
                denominator = Decimal("1") + fee_rate_decimal
                if recoverable_value > 0 and denominator > 0:
                    break_even_price_points = float(
                        (
                            recoverable_value * Decimal(ASSET_SCALE) / (quantity_decimal * denominator)
                        ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                    )
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
            liquidation_price_points = float(
                (
                    Decimal(liquidation_notional) * Decimal(ASSET_SCALE) / Decimal(quantity_units)
                ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
            )
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
            "price_context": self._build_price_context(
                market_symbol=position["market_symbol"],
                price_type="risk_grade",
                price_points=price,
                price_source=price_source,
                price_meta=price_meta,
            ),
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
            "breakeven_price_points": break_even_price_points,
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

    def _margin_position_payload_with_risk(self, conn, row, *, market=None, risk_overrides=None):
        item = self._margin_position_payload(row)
        try:
            risk = self._margin_risk_payload(conn, row, market=market, **(risk_overrides or {}))
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
        item["breakeven_price_points"] = risk.get("breakeven_price_points")
        item["liquidation_price_points"] = risk.get("liquidation_price_points")
        return item

    def _margin_free_margin_points(self, conn, user_id):
        user_id = int(user_id)
        if self._is_root_user_id(conn, user_id):
            account = self._root_sim_account(conn, user_id)
            return int(account["balance_points"] or 0)
        wallet = self.points_service.ensure_wallet(conn, user_id)
        wallet_available = int(wallet["soft_balance"] or 0) + int(wallet["hard_balance"] or 0)
        trial = self._trial_credit_row(conn, user_id)
        trial_available = int(trial["available_points"] or 0) if trial and trial["status"] == "active" else 0
        return max(0, wallet_available + trial_available)

    def _margin_account_payload(self, conn, user_id, rows=None):
        user_id = int(user_id)
        if rows is None:
            rows = [
                self._margin_position_payload_with_risk(conn, row)
                for row in conn.execute(
                    "SELECT * FROM trading_margin_positions WHERE user_id=? AND status='open' ORDER BY id ASC",
                    (user_id,),
                ).fetchall()
            ]
        active = [row for row in rows if row.get("status") == "open"]
        total_position_equity = 0
        total_maintenance = 0
        total_borrowed = 0
        total_unrealized = 0
        warning_count = 0
        unavailable_count = 0
        for row in active:
            risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
            total_position_equity += int(risk.get("equity_after_points") or row.get("equity_after_points") or 0)
            total_maintenance += int(risk.get("maintenance_points") or row.get("maintenance_points") or 0)
            total_borrowed += int(row.get("principal_points") or 0)
            total_unrealized += int(risk.get("unrealized_pnl_points") or row.get("unrealized_pnl_points") or 0)
            status = str(risk.get("risk_status") or row.get("risk_status") or "")
            if status == "unavailable":
                unavailable_count += 1
            elif status == "warning":
                warning_count += 1
        free_margin = self._margin_free_margin_points(conn, user_id) if active else 0
        account_equity = total_position_equity + free_margin
        available_margin = account_equity - total_maintenance
        ratio = round((account_equity / total_maintenance) * 100, 2) if total_maintenance > 0 else None
        liquidation_required = bool(active and total_maintenance > 0 and account_equity <= total_maintenance)
        if liquidation_required:
            status = "liquidation"
            reason = "整戶權益已低於總維持保證金，會依風險順序強制平倉"
        elif unavailable_count:
            status = "unavailable"
            reason = f"{unavailable_count} 筆倉位風險資料無法計算"
        elif active and ratio is not None and ratio < 150.0:
            status = "warning"
            reason = "整戶維持率偏低，建議補保證金、平倉或降低倉位"
        elif warning_count:
            status = "warning"
            reason = f"{warning_count} 筆倉位接近風險區"
        elif active:
            status = "normal"
            reason = "整戶維持率正常"
        else:
            status = "none"
            reason = "目前沒有借貸倉位"
        return {
            "mode": "cross_margin",
            "user_id": user_id,
            "open_count": len(active),
            "account_equity_points": account_equity,
            "total_position_equity_points": total_position_equity,
            "free_margin_points": free_margin,
            "available_margin_points": available_margin,
            "total_borrowed_points": total_borrowed,
            "total_maintenance_requirement_points": total_maintenance,
            "total_maintenance_points": total_maintenance,
            "total_unrealized_pnl_points": total_unrealized,
            "cross_margin_ratio_percent": ratio,
            "maintenance_ratio_percent": ratio,
            "liquidation_required": liquidation_required,
            "liquidation_count": 1 if liquidation_required else 0,
            "warning_count": warning_count + unavailable_count,
            "status": status,
            "reason": reason,
            "auto_transfer_rule": "available wallet/trial/root-simulated balance is counted as free cross margin during risk checks",
        }

    def _margin_summary_payload(self, conn, user_id, rows):
        return self._margin_account_payload(conn, user_id, rows)

    def _margin_liquidation_order_key(self, row):
        risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
        equity = int(risk.get("equity_after_points") or row.get("equity_after_points") or 0)
        maintenance = int(risk.get("maintenance_points") or row.get("maintenance_points") or 0)
        deficit = equity - maintenance
        ratio = risk.get("maintenance_ratio_percent")
        try:
            ratio_value = float(ratio)
        except Exception:
            ratio_value = -999999.0
        return (deficit, ratio_value, -int(row.get("principal_points") or 0), int(row.get("id") or 0))

    def _margin_summary_payload_legacy(self, rows):
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
        reference_context = None
        risk_context = None
        for row in positions:
            if not reference_context and isinstance(row.get("reference_price_context"), dict):
                reference_context = row.get("reference_price_context")
            if not risk_context and isinstance(row.get("risk_grade_price_context"), dict):
                risk_context = row.get("risk_grade_price_context")
        return {
            "current_value_points": sum(int(row.get("current_value_points") or 0) for row in positions),
            "reference_current_value_points": sum(int(row.get("reference_current_value_points") or row.get("current_value_points") or 0) for row in positions),
            "risk_grade_current_value_points": sum(int(row.get("risk_grade_current_value_points") or 0) for row in positions),
            "cost_basis_points": sum(int(row.get("cost_basis_points") or 0) for row in positions),
            "reference_cost_basis_points": sum(int(row.get("reference_cost_basis_points") or 0) for row in positions),
            "unrealized_pnl_points": sum(int(row.get("unrealized_pnl_points") or 0) for row in positions),
            "reference_unrealized_pnl_points": sum(int(row.get("reference_unrealized_pnl_points") or 0) for row in positions),
            "risk_grade_unrealized_pnl_points": sum(int(row.get("risk_grade_unrealized_pnl_points") or row.get("unrealized_pnl_points") or 0) for row in positions),
            "realized_pnl_points": sum(int(row.get("realized_pnl_points") or 0) for row in positions),
            "total_pnl_points": sum(int(row.get("total_pnl_points") or 0) for row in positions),
            "total_fee_points": sum(int(row.get("total_fee_points") or 0) for row in positions),
            "reference_price_context": reference_context,
            "risk_grade_price_context": risk_context,
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
                    f"成交價 {_decimal_text(fill['price_points'])}，成交額 {int(fill['notional_points'])}，"
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
                    f"結算價 {_decimal_text(risk.get('price_points') or 0)}，"
                    f"損益 {int(risk.get('delta_points') or 0)} 點。"
                ),
                link="/trading",
            )
        except Exception:
            pass

    def _has_unread_margin_alert(self, conn, *, user_id, alert_type, position_uuid):
        try:
            row = conn.execute(
                """
                SELECT id FROM notifications
                WHERE user_id=? AND type=? AND is_read=0 AND body LIKE ?
                LIMIT 1
                """,
                (int(user_id), str(alert_type or ""), f"%{str(position_uuid or '')}%"),
            ).fetchone()
            return bool(row)
        except Exception:
            return False

    def _notify_margin_risk_alerts(self, conn, *, position, risk, market):
        try:
            user_id = int(position["user_id"])
            position_uuid = str(position["position_uuid"])
            market_symbol = str(position["market_symbol"])
            position_label = "融資做多" if position["position_type"] == "margin_long" else "借券放空"
            price = float(_to_decimal(risk.get("price_points") or 0, name="price_points", minimum=0))
            entry_price = float(_to_decimal(position["entry_price_points"] or 0, name="entry_price_points", minimum=0))
            ratio = risk.get("maintenance_ratio_percent")
            liquidation_price = risk.get("liquidation_price_points")
            if not risk.get("liquidation_required") and ratio is not None and float(ratio) <= 150.0:
                alert_type = "trading_margin_near_liquidation"
                if not self._has_unread_margin_alert(conn, user_id=user_id, alert_type=alert_type, position_uuid=position_uuid):
                    create_notification_if_enabled(
                        conn,
                        user_id=user_id,
                        type=alert_type,
                        title="進階交易接近強平",
                        body=(
                            f"{market_symbol} {position_label} 倉位接近強平，"
                            f"目前價 {price}，強平價 {liquidation_price or '-'}，"
                            f"整戶維持率 {ratio}%。倉位 {position_uuid}"
                        ),
                        link="/trading",
                    )
            if entry_price > 0 and price > 0:
                move_percent = abs(price - entry_price) * 100.0 / entry_price
                threshold = float(market["max_price_jump_percent"] or 10)
                if move_percent >= threshold:
                    alert_type = "trading_margin_price_jump"
                    if not self._has_unread_margin_alert(conn, user_id=user_id, alert_type=alert_type, position_uuid=position_uuid):
                        direction = "上漲" if price > entry_price else "下跌"
                        create_notification_if_enabled(
                            conn,
                            user_id=user_id,
                            type=alert_type,
                            title="進階交易價格大幅波動",
                            body=(
                                f"{market_symbol} {position_label} 參考價較開倉價{direction} {move_percent:.2f}%，"
                                f"開倉價 {entry_price}，目前價 {price}。倉位 {position_uuid}"
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
            rows = conn.execute(f"SELECT * FROM trading_markets {where}").fetchall()
            payloads = [self._market_payload(row) for row in rows]
            return sorted(payloads, key=lambda item: market_sort_key(item.get("symbol")))
        finally:
            conn.close()

    def user_dashboard(self, *, user_id):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._ensure_trial_credit(conn, user_id)
            conn.commit()
            state = self._state(conn)
            markets = []
            for row in conn.execute("SELECT * FROM trading_markets WHERE enabled=1").fetchall():
                market_item = self._market_payload(row)
                reference_context, risk_grade_context = self._stored_market_price_contexts(market_item)
                markets.append(
                    self._attach_market_price_contexts(
                        market_item,
                        reference_context=reference_context,
                        risk_grade_context=risk_grade_context,
                    )
                )
            markets = sorted(markets, key=lambda item: market_sort_key(item.get("symbol")))
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
            for row in conn.execute(
                "SELECT * FROM trading_margin_positions WHERE user_id=? AND status='open' ORDER BY id ASC",
                (int(user_id),),
            ).fetchall():
                self._accrue_margin_interest(conn, row, actor={"username": "system", "role": "system"})
            conn.commit()
            margin_positions = [
                self._margin_position_payload_with_risk(conn, row, market=market_map.get(row["market_symbol"]))
                for row in conn.execute("SELECT * FROM trading_margin_positions WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            conn.commit()
            bot_order_map = {
                row["order_uuid"]: row["bot_name"]
                for row in conn.execute(
                    """
                    SELECT r.order_uuid, b.name AS bot_name
                    FROM trading_bot_runs r
                    JOIN trading_bots b ON b.id = r.bot_id
                    WHERE r.user_id=? AND r.order_uuid IS NOT NULL
                    """,
                    (int(user_id),),
                ).fetchall()
            }
            for row in conn.execute(
                """
                SELECT go.trading_order_uuid AS order_uuid, gb.name AS bot_name
                FROM trading_grid_orders go
                JOIN trading_grid_bots gb ON gb.id = go.grid_bot_id
                WHERE go.user_id=? AND go.trading_order_uuid IS NOT NULL
                """,
                (int(user_id),),
            ).fetchall():
                bot_order_map[row["order_uuid"]] = row["bot_name"]
            raw_orders = conn.execute("SELECT * FROM trading_orders WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            orders = []
            for row in raw_orders:
                item = self._order_payload(row)
                if item.get("order_uuid") in bot_order_map:
                    item["bot_name"] = bot_order_map[item["order_uuid"]]
                orders.append(item)
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
            fill_order_uuid_map = {
                row["id"]: row["order_uuid"]
                for row in conn.execute(
                    "SELECT f.id, o.order_uuid FROM trading_fills f JOIN trading_orders o ON o.id=f.order_id WHERE f.user_id=? ORDER BY f.id DESC LIMIT 50",
                    (int(user_id),),
                ).fetchall()
            }
            fills = []
            for row in fill_rows:
                item = self._fill_payload(row, realized=pnl_by_fill.get(row["id"]))
                order_uuid = fill_order_uuid_map.get(row["id"])
                if order_uuid:
                    item["order_uuid"] = order_uuid
                if order_uuid and order_uuid in bot_order_map:
                    item["bot_name"] = bot_order_map[order_uuid]
                fills.append(item)
            margin_trade_records = self._margin_trade_records(conn, user_id)
            combined_fills = sorted(
                [*fills, *margin_trade_records],
                key=lambda item: str(item.get("created_at") or ""),
                reverse=True,
            )[:50]
            _market_prices = {
                m["symbol"]: float(_to_decimal(m.get("manual_price_points") or 0, name="manual_price_points", minimum=0))
                for m in markets
            }
            bots = []
            for _row in conn.execute("SELECT * FROM trading_bots WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall():
                _bot = self._bot_payload(_row)
                _cp = _market_prices.get(str(_bot.get("market_symbol") or ""), 0)
                try:
                    _bot["condition_checks"] = self._bot_condition_checks(_bot, _cp)
                except Exception:
                    _bot["condition_checks"] = []
                bots.append(_bot)
            bot_runs = [
                self._bot_run_payload(row)
                for row in conn.execute("SELECT * FROM trading_bot_runs WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(user_id),)).fetchall()
            ]
            return {
                "state": state,
                "settings": self._settings_payload(conn),
                "funding_pool": self._funding_pool_payload(conn),
                "funding": self._funding_payload(conn, user_id),
                "volume_stats": dict(self._user_volume_stats(conn, user_id)),
                "markets": markets,
                "positions": positions,
                "spot_summary": self._spot_summary_payload(positions),
                "futures_positions": futures_positions,
                "margin_positions": margin_positions,
                "margin_summary": self._margin_summary_payload(conn, user_id, margin_positions),
                "orders": orders,
                "fills": combined_fills,
                "spot_fills": fills,
                "margin_trade_records": margin_trade_records,
                "bots": bots,
                "bot_runs": bot_runs,
            }
        finally:
            conn.close()

    def _is_executable(self, market, *, side, order_type, limit_price, current_price):
        current_price = float(_to_decimal(current_price, name="current_price", minimum=0))
        if order_type == "market":
            return True, current_price
        limit_price = float(_to_decimal(limit_price or 0, name="limit_price_points", minimum=0))
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
            limit_price = _to_price_float(payload.get("limit_price_points"), name="limit_price_points", minimum=0.00000001, maximum=10**12)
        trigger_price = None
        if trigger_type != "always":
            trigger_price = _to_price_float(payload.get("trigger_price_points"), name="trigger_price_points", minimum=0.00000001, maximum=10**12)
        max_runs = _bot_max_runs_to_storage(
            payload.get("max_runs", 1),
            allow_unlimited=(bot_type == "dca"),
            maximum=1000,
        )
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
            market_prices = {
                row["symbol"]: float(_to_decimal(row["manual_price_points"] or 0, name="manual_price_points", minimum=0))
                for row in conn.execute("SELECT symbol, manual_price_points FROM trading_markets").fetchall()
            }
            bots = []
            for row in conn.execute("SELECT * FROM trading_bots WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall():
                bot = self._bot_payload(row)
                current_price = market_prices.get(str(bot.get("market_symbol") or ""), 0)
                try:
                    bot["condition_checks"] = self._bot_condition_checks(bot, current_price)
                except Exception:
                    bot["condition_checks"] = []
                bots.append(bot)
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
                        workflow_json=?, execution_state_json='{}', last_error='',
                        enabled_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        data["bot_type"], data["name"], data["market_symbol"], data["side"], data["order_type"], data["quantity_text"],
                        data["limit_price_points"], data["trigger_type"], data["trigger_price_points"],
                        1 if data["enabled"] else 0, data["max_runs"], data["cooldown_seconds"],
                        data["interval_hours"], data["budget_points"], _json_dumps(data["workflow"]) if data["workflow"] else None,
                        now if data["enabled"] and not bool(existing["enabled"]) else (existing["enabled_at"] if data["enabled"] else None),
                        now,
                        existing["id"],
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
                        max_runs, run_count, cooldown_seconds, interval_hours, budget_points, workflow_json, execution_state_json, enabled_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, '{}', ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), user_id, data["bot_type"], data["name"], data["market_symbol"], data["side"], data["order_type"],
                        data["quantity_text"], data["limit_price_points"], data["trigger_type"], data["trigger_price_points"],
                        1 if data["enabled"] else 0, data["max_runs"], data["cooldown_seconds"],
                        data["interval_hours"], data["budget_points"], _json_dumps(data["workflow"]) if data["workflow"] else None,
                        now if data["enabled"] else None,
                        now,
                        now,
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

    def increase_trading_bot_max_runs(self, *, actor, bot_uuid, delta):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        increment = _to_int(delta, name="delta", minimum=1, maximum=1000)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_writable(conn)
            row = conn.execute("SELECT * FROM trading_bots WHERE bot_uuid=?", (str(bot_uuid or ""),)).fetchone()
            if not row:
                raise ValueError("trading bot not found")
            if int(row["user_id"]) != int(user_id):
                raise ValueError("cannot update another user's trading bot")
            if int(row["max_runs"] or 0) >= UNLIMITED_BOT_MAX_RUNS:
                conn.commit()
                return {"ok": True, "bot": self._bot_payload(row), "delta": 0, "unlimited": True}
            next_max_runs = _to_int(int(row["max_runs"] or 0) + increment, name="max_runs", minimum=1, maximum=10000)
            now = _now()
            conn.execute(
                "UPDATE trading_bots SET max_runs=?, updated_at=? WHERE id=?",
                (next_max_runs, now, row["id"]),
            )
            updated = conn.execute("SELECT * FROM trading_bots WHERE id=?", (row["id"],)).fetchone()
            self._audit_event(
                conn,
                "TRADING_BOT_MAX_RUNS_INCREASED",
                "trading bot max runs increased",
                actor=actor,
                target_user_id=user_id,
                market_symbol=row["market_symbol"],
                metadata={
                    "bot_uuid": row["bot_uuid"],
                    "delta": increment,
                    "previous_max_runs": int(row["max_runs"] or 0),
                    "max_runs": next_max_runs,
                },
            )
            conn.commit()
            return {"ok": True, "bot": self._bot_payload(updated), "delta": increment}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Grid Trading Bot ────────────────────────────────────────────────────

    def _grid_levels(self, lower, upper, count, spacing_mode="arithmetic"):
        count = max(2, int(count))
        lower = _to_decimal(lower, name="lower_price_points", minimum=0.00000001)
        upper = _to_decimal(upper, name="upper_price_points", minimum=0.00000002)
        if count == 2:
            return [float(lower), float(upper)]
        if spacing_mode == "geometric":
            ratio = (float(upper) / float(lower)) ** (1 / (count - 1))
            return [
                float(
                    Decimal(str(float(lower) * (ratio ** i))).quantize(
                        Decimal("0.00000001"),
                        rounding=ROUND_HALF_UP,
                    )
                )
                for i in range(count)
            ]
        step = (upper - lower) / Decimal(count - 1)
        return [
            float((lower + (step * Decimal(i))).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))
            for i in range(count)
        ]

    def _grid_quantity_units(self, amount_points, price_points):
        amount = int(amount_points or 0)
        price = _to_decimal(price_points, name="price_points", minimum=0)
        if amount <= 0 or price <= 0:
            return 0
        units = (Decimal(amount) * Decimal(ASSET_SCALE) / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return int(units)

    def _grid_preview_fee_rates(self, market, settings, *, order_mode="maker"):
        mode = str(order_mode or "maker").strip().lower()
        if mode not in {"maker", "taker"}:
            raise ValueError("order_mode must be maker or taker")
        spot_fee_percent = Decimal(str(market["fee_rate_percent"] or 0))
        discount_percent = Decimal(str(settings.get("grid_fee_discount_percent") or DEFAULT_GRID_FEE_DISCOUNT_PERCENT))
        discount_percent = max(Decimal("0"), min(discount_percent, Decimal("100")))
        grid_fee_percent = (spot_fee_percent * (Decimal("100") - discount_percent) / Decimal("100"))
        return {
            "order_mode": mode,
            "spot_fee_percent": spot_fee_percent,
            "grid_discount_percent": discount_percent,
            "maker_fee_percent": spot_fee_percent,
            "taker_fee_percent": spot_fee_percent,
            "buy_fee_percent": grid_fee_percent,
            "sell_fee_percent": grid_fee_percent,
            "round_trip_fee_percent": grid_fee_percent * Decimal("2"),
        }

    def _grid_preview_risk(self, *, min_net_spread_percent, break_even_spread_percent, spacing_percent):
        net_spread = Decimal(str(min_net_spread_percent or 0))
        break_even = Decimal(str(break_even_spread_percent or 0))
        spacing = Decimal(str(spacing_percent or 0))
        if net_spread <= 0:
            return {
                "status": "red",
                "message": f"扣除手續費後預期虧損：每格間距 {_decimal_text(spacing, places='0.0001')}%，但損益兩平至少需要 {_decimal_text(break_even, places='0.0001')}%",
                "blocked": True,
                "requires_confirmation": False,
            }
        if net_spread < GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT:
            return {
                "status": "yellow",
                "message": f"利潤過薄：每格扣費後僅剩 {_decimal_text(net_spread, places='0.0001')}%，可能被滑價吃掉",
                "blocked": False,
                "requires_confirmation": True,
            }
        return {
            "status": "green",
            "message": f"手續費後仍有利潤：每格預估淨利 {_decimal_text(net_spread, places='0.0001')}%",
            "blocked": False,
            "requires_confirmation": False,
        }

    def _grid_preview_summary(self, *, lower_price_points, upper_price_points, grid_count, order_amount_points, spacing_mode, fee_rates):
        grid_levels = self._grid_levels(lower_price_points, upper_price_points, grid_count, spacing_mode)
        if len(grid_levels) < 2:
            raise ValueError("grid_count must be at least 2")
        buy_fee_rate = Decimal(str(fee_rates["buy_fee_percent"])) / Decimal("100")
        sell_fee_rate = Decimal(str(fee_rates["sell_fee_percent"])) / Decimal("100")
        if sell_fee_rate >= Decimal("1"):
            raise ValueError("sell_fee_percent out of range")

        pair_summaries = []
        total_gross = Decimal("0")
        total_fee = Decimal("0")
        total_net = Decimal("0")
        break_even_spread_percent = ((Decimal("1") + buy_fee_rate) / (Decimal("1") - sell_fee_rate) - Decimal("1")) * Decimal("100")
        blocked_reason = ""

        for level_index in range(len(grid_levels) - 1):
            buy_price = Decimal(str(grid_levels[level_index]))
            sell_price = Decimal(str(grid_levels[level_index + 1]))
            quantity_units = self._grid_quantity_units(order_amount_points, buy_price)
            if quantity_units <= 0:
                blocked_reason = "每格金額不足以買入最小單位，請提高每格金額或降低價格區間"
                break
            quantity = Decimal(quantity_units) / Decimal(ASSET_SCALE)
            gross_profit = (sell_price - buy_price) * quantity
            buy_notional = buy_price * quantity
            sell_notional = sell_price * quantity
            buy_fee = buy_notional * buy_fee_rate
            sell_fee = sell_notional * sell_fee_rate
            fees = buy_fee + sell_fee
            net_profit = gross_profit - fees
            spacing_percent = ((sell_price - buy_price) / buy_price) * Decimal("100")
            net_spread_percent = (net_profit / buy_notional) * Decimal("100") if buy_notional > 0 else Decimal("0")
            pair_summary = {
                "level_index": level_index,
                "buy_price_points": float(buy_price),
                "sell_price_points": float(sell_price),
                "quantity_units": quantity_units,
                "quantity": quantity,
                "grid_spacing_points": sell_price - buy_price,
                "grid_spacing_percent": spacing_percent,
                "gross_profit_points": gross_profit,
                "buy_fee_points": buy_fee,
                "sell_fee_points": sell_fee,
                "fee_points": fees,
                "net_profit_points": net_profit,
                "net_spread_percent": net_spread_percent,
            }
            pair_summaries.append(pair_summary)
            total_gross += gross_profit
            total_fee += fees
            total_net += net_profit

        if blocked_reason:
            risk = {
                "status": "red",
                "message": blocked_reason,
                "blocked": True,
                "requires_confirmation": False,
            }
            return {
                "grid_levels": grid_levels,
                "pair_summaries": [],
                "break_even_spread_percent": break_even_spread_percent,
                "risk": risk,
                "pair_count": len(grid_levels) - 1,
                "estimated_total_gross_profit_points": Decimal("0"),
                "estimated_total_fee_points": Decimal("0"),
                "estimated_total_net_profit_points": Decimal("0"),
                "worst_pair": None,
            }

        worst_pair = min(pair_summaries, key=lambda item: (item["net_spread_percent"], item["grid_spacing_percent"], item["level_index"]))
        risk = self._grid_preview_risk(
            min_net_spread_percent=worst_pair["net_spread_percent"],
            break_even_spread_percent=break_even_spread_percent,
            spacing_percent=worst_pair["grid_spacing_percent"],
        )
        return {
            "grid_levels": grid_levels,
            "pair_summaries": pair_summaries,
            "break_even_spread_percent": break_even_spread_percent,
            "risk": risk,
            "pair_count": len(pair_summaries),
            "estimated_total_gross_profit_points": total_gross,
            "estimated_total_fee_points": total_fee,
            "estimated_total_net_profit_points": total_net,
            "worst_pair": worst_pair,
        }

    def preview_grid_bot(self, *, actor, payload):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        source = payload or {}
        market_symbol = str(source.get("market_symbol") or "").strip().upper()
        upper_price = _to_price_float(source.get("upper_price_points", source.get("upper_price")), name="upper_price_points", minimum=0.00000001)
        lower_price = _to_price_float(source.get("lower_price_points", source.get("lower_price")), name="lower_price_points", minimum=0.00000001)
        if upper_price <= lower_price:
            raise ValueError("upper_price_points must be greater than lower_price_points")
        grid_count = _to_int(source.get("grid_count", 10), name="grid_count", minimum=2, maximum=200)
        order_amount_decimal = _to_decimal(source.get("order_amount_points", source.get("investment_amount")), name="order_amount_points", minimum=1, maximum=10**12)
        if order_amount_decimal != order_amount_decimal.to_integral_value():
            raise ValueError("order_amount_points must be an integer")
        order_amount_points = int(order_amount_decimal)
        spacing_mode = str(source.get("spacing_mode") or "arithmetic").strip().lower()
        if spacing_mode not in ("arithmetic", "geometric"):
            spacing_mode = "arithmetic"
        order_mode = str(source.get("order_mode") or "maker").strip().lower()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            market = self._market(conn, market_symbol)
            settings = self._settings_payload(conn)
        finally:
            conn.close()
        fee_rates = self._grid_preview_fee_rates(market, settings, order_mode=order_mode)
        summary = self._grid_preview_summary(
            lower_price_points=lower_price,
            upper_price_points=upper_price,
            grid_count=grid_count,
            order_amount_points=order_amount_points,
            spacing_mode=spacing_mode,
            fee_rates=fee_rates,
        )
        worst_pair = summary["worst_pair"] or {}
        return {
            "ok": True,
            "market_symbol": market_symbol,
            "spacing_mode": spacing_mode,
            "order_mode": order_mode,
            "levels": summary["grid_levels"],
            "pair_count": summary["pair_count"],
            "fee_model": {
                "spot_fee_percent": _decimal_text(fee_rates["spot_fee_percent"], places="0.0001"),
                "grid_discount_percent": _decimal_text(fee_rates["grid_discount_percent"], places="0.0001"),
                "maker_fee_percent": _decimal_text(fee_rates["maker_fee_percent"], places="0.0001"),
                "taker_fee_percent": _decimal_text(fee_rates["taker_fee_percent"], places="0.0001"),
                "buy_fee_percent": _decimal_text(fee_rates["buy_fee_percent"], places="0.0001"),
                "sell_fee_percent": _decimal_text(fee_rates["sell_fee_percent"], places="0.0001"),
                "round_trip_fee_percent": _decimal_text(fee_rates["round_trip_fee_percent"], places="0.0001"),
            },
            "break_even": {
                "min_spread_percent": _decimal_text(summary["break_even_spread_percent"], places="0.0001"),
            },
            "grid_profit": {
                "grid_spacing_percent": _decimal_text(worst_pair.get("grid_spacing_percent", 0), places="0.0001"),
                "grid_spacing_points": _decimal_text(worst_pair.get("grid_spacing_points", 0), places="0.0001"),
                "estimated_net_spread_percent": _decimal_text(worst_pair.get("net_spread_percent", 0), places="0.0001"),
                "estimated_gross_profit_per_grid": _decimal_text(worst_pair.get("gross_profit_points", 0)),
                "estimated_fee_per_grid": _decimal_text(worst_pair.get("fee_points", 0)),
                "estimated_net_profit_per_grid": _decimal_text(worst_pair.get("net_profit_points", 0)),
                "estimated_total_gross_profit": _decimal_text(summary["estimated_total_gross_profit_points"]),
                "estimated_total_fee": _decimal_text(summary["estimated_total_fee_points"]),
                "estimated_total_net_profit": _decimal_text(summary["estimated_total_net_profit_points"]),
                "reference_buy_price_points": _decimal_text(worst_pair.get("buy_price_points", 0), places="0.0001"),
                "reference_sell_price_points": _decimal_text(worst_pair.get("sell_price_points", 0), places="0.0001"),
                "reference_quantity": _decimal_text(worst_pair.get("quantity", 0)),
            },
            "risk": summary["risk"],
        }

    def _grid_bot_payload(self, row, orders=None):
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["grid_levels"] = _json_loads(item.get("grid_levels_json"), [])
        item["orders"] = orders or []
        return item

    def create_grid_bot(self, *, actor, payload):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        payload = payload or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("grid bot name is required")
        if len(name) > 80:
            raise ValueError("grid bot name too long")
        market_symbol = str(payload.get("market_symbol") or "").strip().upper()
        upper_price = _to_price_float(payload.get("upper_price_points"), name="upper_price_points", minimum=0.00000001)
        lower_price = _to_price_float(payload.get("lower_price_points"), name="lower_price_points", minimum=0.00000001)
        if upper_price <= lower_price:
            raise ValueError("upper_price_points must be greater than lower_price_points")
        grid_count = _to_int(payload.get("grid_count", 10), name="grid_count", minimum=2, maximum=200)
        order_amount = _to_int(payload.get("order_amount_points"), name="order_amount_points", minimum=1)
        spacing_mode = str(payload.get("spacing_mode") or "arithmetic").strip()
        if spacing_mode not in ("arithmetic", "geometric"):
            spacing_mode = "arithmetic"
        preview = self.preview_grid_bot(
            actor=actor,
            payload={
                "market_symbol": market_symbol,
                "upper_price_points": upper_price,
                "lower_price_points": lower_price,
                "grid_count": grid_count,
                "order_amount_points": order_amount,
                "spacing_mode": spacing_mode,
                "order_mode": "maker",
            },
        )
        risk = preview.get("risk") or {}
        if risk.get("blocked"):
            raise ValueError(risk.get("message") or "grid preview blocked")
        if risk.get("requires_confirmation") and not bool(payload.get("confirm_thin_profit")):
            raise ValueError(risk.get("message") or "grid profit is too thin; confirmation required")

        # Phase 1: validate market and get current price (read-only)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            market = self._market(conn, market_symbol)
            current_price, _ = self._current_market_price_points(conn, market)
        finally:
            conn.close()

        grid_levels = self._grid_levels(lower_price, upper_price, grid_count, spacing_mode)
        now = _now()
        bot_uuid = str(uuid.uuid4())

        # Phase 2: insert bot row (commit immediately before placing orders)
        conn = self.get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO trading_grid_bots
                  (bot_uuid, user_id, name, market_symbol, upper_price_points, lower_price_points,
                   grid_count, order_amount_points, enabled, initial_price_points, grid_levels_json,
                   enabled_at, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?)
                """,
                (bot_uuid, user_id, name, market_symbol, upper_price, lower_price,
                 grid_count, order_amount, current_price,
                 json.dumps(grid_levels), now, now, now),
            )
            grid_bot_id = conn.execute(
                "SELECT id FROM trading_grid_bots WHERE bot_uuid=?", (bot_uuid,)
            ).fetchone()["id"]
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
        else:
            conn.close()

        # Phase 3: place limit orders for each level (each call opens its own connection)
        bot_actor = {"id": int(user_id), "username": self._actor_username(actor), "role": self._actor_role(actor)}
        placed = []
        errors = []
        for i, level_price in enumerate(grid_levels):
            if level_price < current_price:
                side = "buy"
            elif level_price > current_price:
                side = "sell"
            else:
                continue
            qty_units = self._grid_quantity_units(order_amount, level_price)
            if qty_units <= 0:
                errors.append(f"level {i} price {level_price}: 金額不足以買入最小單位")
                continue
            qty_text = units_to_quantity(qty_units)
            try:
                order_result = self.place_order(
                    actor=bot_actor,
                    market_symbol=market_symbol,
                    side=side,
                    order_type="limit",
                    quantity=qty_text,
                    limit_price_points=level_price,
                    is_grid_order=True,
                )
                trading_order_uuid = (order_result.get("order") or {}).get("order_uuid")
                placed.append({"level_index": i, "price_points": level_price, "side": side,
                               "trading_order_uuid": trading_order_uuid, "qty_units": qty_units})
            except Exception as exc:
                errors.append(f"level {i} price {level_price}: {exc}")

        # Phase 4: record grid_orders for placed orders (single commit)
        if placed:
            conn = self.get_db()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for p in placed:
                    conn.execute(
                        """
                        INSERT INTO trading_grid_orders
                          (order_uuid, grid_bot_id, user_id, level_index, price_points, side,
                           trading_order_uuid, status, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,'open',?,?)
                        """,
                        (str(uuid.uuid4()), grid_bot_id, user_id,
                         p["level_index"], p["price_points"], p["side"],
                         p["trading_order_uuid"], now, now),
                    )
                self._audit_event(conn, "GRID_BOT_CREATED", "grid trading bot created", actor=actor,
                                  target_user_id=user_id, market_symbol=market_symbol,
                                  metadata={"bot_uuid": bot_uuid, "grid_count": grid_count, "placed": len(placed)})
                conn.commit()
            except Exception:
                conn.rollback()
                conn.close()
                raise
            else:
                conn.close()

        # Phase 5: read back final state
        conn = self.get_db()
        try:
            bot_row = conn.execute("SELECT * FROM trading_grid_bots WHERE bot_uuid=?", (bot_uuid,)).fetchone()
            orders = conn.execute(
                "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? ORDER BY level_index ASC",
                (grid_bot_id,),
            ).fetchall()
            return {"ok": True, "bot": self._grid_bot_payload(bot_row, [dict(o) for o in orders]),
                    "placed": placed, "errors": errors, "current_price_points": current_price}
        finally:
            conn.close()

    def list_grid_bots(self, *, actor):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            bots = []
            for row in conn.execute("SELECT * FROM trading_grid_bots WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall():
                orders = conn.execute(
                    "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? ORDER BY level_index ASC, id ASC",
                    (row["id"],),
                ).fetchall()
                bots.append(self._grid_bot_payload(row, [dict(o) for o in orders]))
            return {"ok": True, "bots": bots}
        finally:
            conn.close()

    def toggle_grid_bot(self, *, actor, bot_uuid, enabled):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM trading_grid_bots WHERE bot_uuid=? AND user_id=?", (str(bot_uuid or ""), user_id)).fetchone()
            if not row:
                raise ValueError("grid bot not found")
            now = _now()
            conn.execute(
                "UPDATE trading_grid_bots SET enabled=?, enabled_at=?, updated_at=? WHERE id=?",
                (1 if enabled else 0, now if enabled and not bool(row["enabled"]) else (row["enabled_at"] if enabled else None), now, row["id"]),
            )
            conn.commit()
            return {"ok": True, "bot_uuid": bot_uuid, "enabled": bool(enabled)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_grid_bot(self, *, actor, bot_uuid):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        # Phase 1: read-only — fetch bot and open order UUIDs
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM trading_grid_bots WHERE bot_uuid=? AND user_id=?", (str(bot_uuid or ""), user_id)).fetchone()
            if not row:
                raise ValueError("grid bot not found")
            open_order_uuids = [
                go["trading_order_uuid"]
                for go in conn.execute(
                    "SELECT trading_order_uuid FROM trading_grid_orders WHERE grid_bot_id=? AND status='open'",
                    (row["id"],),
                ).fetchall()
                if go["trading_order_uuid"]
            ]
            bot_id = row["id"]
        finally:
            conn.close()
        # Phase 2: cancel each open limit order (each cancel_order uses its own connection)
        bot_actor = {"id": int(user_id), "username": self._actor_username(actor), "role": self._actor_role(actor)}
        for order_uuid in open_order_uuids:
            try:
                self.cancel_order(actor=bot_actor, order_uuid=order_uuid)
            except Exception:
                pass
        # Phase 3: delete the bot row (CASCADE removes grid_orders)
        conn = self.get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM trading_grid_bots WHERE id=?", (bot_id,))
            conn.commit()
            return {"ok": True, "bot_uuid": bot_uuid}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def scan_grid_bots(self, *, actor):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            bots = conn.execute(
                "SELECT * FROM trading_grid_bots WHERE user_id=? AND enabled=1 ORDER BY id ASC",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        results = []
        for bot in bots:
            try:
                r = self._scan_one_grid_bot(bot, actor=actor)
                results.append(r)
            except Exception as exc:
                conn2 = self.get_db()
                try:
                    conn2.execute("UPDATE trading_grid_bots SET last_error=?, updated_at=? WHERE id=?", (str(exc)[:500], _now(), bot["id"]))
                    conn2.commit()
                except Exception:
                    pass
                finally:
                    conn2.close()
                results.append({"bot_uuid": bot["bot_uuid"], "error": str(exc)})
        return {"ok": True, "scanned": len(bots), "results": results}

    def _scan_one_grid_bot(self, bot, *, actor):
        user_id = int(bot["user_id"])
        bot_id = int(bot["id"])
        bot_actor = {"id": user_id, "username": self._actor_username(actor), "role": self._actor_role(actor)}
        now = _now()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            market = self._market(conn, bot["market_symbol"])
            current_price, _price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True, high_risk=True)
            self._assert_price_meta_allows_high_risk_use(
                conn,
                actor=actor,
                market_symbol=market["symbol"],
                usage="grid bot scan",
                price_meta=price_meta,
            )
            price_window = self._recent_price_window(
                market["symbol"],
                lookback_seconds=65,
                since_time_text=bot["last_scan_at"] if "last_scan_at" in bot.keys() else None,
            )
            window_low = float((price_window or {}).get("low_points") or current_price)
            window_high = float((price_window or {}).get("high_points") or current_price)
            grid_levels = _json_loads(bot["grid_levels_json"], [])
            if not grid_levels:
                grid_levels = self._grid_levels(bot["lower_price_points"], bot["upper_price_points"], bot["grid_count"])
            open_grid_orders = conn.execute(
                "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? AND status='open' ORDER BY level_index ASC",
                (bot_id,),
            ).fetchall()
            fills_processed = []
            counter_orders_placed = []
            profit_delta = 0
            trades_delta = 0
            for go in open_grid_orders:
                if not go["trading_order_uuid"]:
                    continue
                t_order = conn.execute(
                    "SELECT * FROM trading_orders WHERE order_uuid=?",
                    (go["trading_order_uuid"],),
                ).fetchone()
                if not t_order:
                    continue
                if t_order["status"] in ("filled", "partially_filled"):
                    filled_units = int(t_order["filled_quantity_units"] or 0)
                else:
                    executable, _ = self._is_executable(
                        market,
                        side=t_order["side"],
                        order_type=t_order["order_type"],
                        limit_price=t_order["limit_price_points"],
                        current_price=current_price,
                    )
                    if not executable and t_order["order_type"] == "limit":
                        limit_price = float(_to_decimal(t_order["limit_price_points"] or 0, name="limit_price_points", minimum=0))
                        if t_order["side"] == "buy" and limit_price > 0 and window_low <= limit_price:
                            executable = True
                        elif t_order["side"] == "sell" and limit_price > 0 and window_high >= limit_price:
                            executable = True
                    if not executable:
                        continue
                    execution_price = float(t_order["limit_price_points"] or go["price_points"] or current_price)
                    conn.execute(
                        "UPDATE trading_orders SET execution_price_points=?, updated_at=? WHERE id=?",
                        (execution_price, now, t_order["id"]),
                    )
                    t_order = conn.execute("SELECT * FROM trading_orders WHERE id=?", (t_order["id"],)).fetchone()
                    fill = self._execute_order(conn, t_order, market, actor=actor)
                    filled_units = int(fill["quantity_units"] or 0)
                    self._audit_event(
                        conn,
                        "GRID_ORDER_FILLED",
                        "grid order filled by CFD price crossing",
                        actor=actor,
                        target_user_id=user_id,
                        order_id=t_order["id"],
                        market_symbol=market["symbol"],
                        metadata={
                            "bot_uuid": bot["bot_uuid"],
                            "grid_order_uuid": go["order_uuid"],
                            "fill_id": fill["id"],
                            "level_index": int(go["level_index"]),
                            "side": go["side"],
                            "trigger_price_points": current_price,
                            "execution_price_points": execution_price,
                        },
                    )
                    self._notify_trade_filled(conn, fill)
                    conn.commit()
                filled_units = int(filled_units or 0)
                if filled_units <= 0:
                    continue
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE trading_grid_orders SET status='filled', filled_quantity_units=?, updated_at=? WHERE id=?",
                    (filled_units, now, go["id"]),
                )
                conn.commit()
                fills_processed.append({"level_index": go["level_index"], "side": go["side"], "price_points": go["price_points"]})
                level_idx = int(go["level_index"])
                side = str(go["side"])
                filled_price = float(_to_decimal(go["price_points"] or 0, name="grid_price_points", minimum=0))
                if side == "buy":
                    counter_level_idx = level_idx + 1
                    counter_side = "sell"
                else:
                    counter_level_idx = level_idx - 1
                    counter_side = "buy"
                    buy_price = grid_levels[level_idx - 1] if level_idx > 0 else filled_price
                    settings = self._settings_payload(conn)
                    grid_fee_rate_percent = self._grid_fee_rate_percent(float(market["fee_rate_percent"] or 0), settings)
                    buy_notional = notional_points(filled_units, buy_price)
                    sell_notional = notional_points(filled_units, filled_price)
                    gross_profit = sell_notional - buy_notional
                    total_fee = fee_points(buy_notional, grid_fee_rate_percent) + fee_points(sell_notional, grid_fee_rate_percent)
                    profit_delta += gross_profit - total_fee
                    trades_delta += 1
                if 0 <= counter_level_idx < len(grid_levels):
                    counter_price = int(grid_levels[counter_level_idx])
                    existing = conn.execute(
                        "SELECT id FROM trading_grid_orders WHERE grid_bot_id=? AND level_index=? AND status='open'",
                        (bot_id, counter_level_idx),
                    ).fetchone()
                    if not existing:
                        qty_units = filled_units if counter_side == "sell" else self._grid_quantity_units(int(bot["order_amount_points"]), counter_price)
                        if qty_units > 0:
                            qty_text = units_to_quantity(qty_units)
                            try:
                                order_result = self.place_order(
                                    actor=bot_actor,
                                    market_symbol=bot["market_symbol"],
                                    side=counter_side,
                                    order_type="limit",
                                    quantity=qty_text,
                                    limit_price_points=counter_price,
                                    is_grid_order=True,
                                )
                                t_order_uuid = (order_result.get("order") or {}).get("order_uuid")
                                grid_order_uuid = str(uuid.uuid4())
                                conn.execute("BEGIN IMMEDIATE")
                                conn.execute(
                                    """
                                    INSERT INTO trading_grid_orders
                                      (order_uuid, grid_bot_id, user_id, level_index, price_points, side,
                                       trading_order_uuid, status, created_at, updated_at)
                                    VALUES (?,?,?,?,?,?,?,'open',?,?)
                                    """,
                                    (grid_order_uuid, bot_id, user_id, counter_level_idx, counter_price,
                                     counter_side, t_order_uuid, now, now),
                                )
                                conn.commit()
                                counter_orders_placed.append({"level_index": counter_level_idx, "side": counter_side, "price_points": counter_price})
                            except Exception as exc:
                                conn.rollback()
                                pass
            if profit_delta or trades_delta:
                conn.execute(
                    "UPDATE trading_grid_bots SET total_profit_points=total_profit_points+?, total_trades=total_trades+?, last_scan_at=?, last_error=NULL, updated_at=? WHERE id=?",
                    (profit_delta, trades_delta, now, now, bot_id),
                )
                conn.commit()
            else:
                conn.execute("UPDATE trading_grid_bots SET last_scan_at=?, updated_at=? WHERE id=?", (now, now, bot_id))
                conn.commit()
            return {
                "bot_uuid": bot["bot_uuid"],
                "current_price_points": current_price,
                "scan_window_low_points": window_low,
                "scan_window_high_points": window_high,
                "fills_processed": fills_processed,
                "counter_orders_placed": counter_orders_placed,
                "profit_delta": profit_delta,
            }
        finally:
            conn.close()

    # ── End Grid Trading Bot ─────────────────────────────────────────────────

    def _bot_trigger_hit(self, bot, observed_price, *, observed_low=None, observed_high=None):
        if str(bot["bot_type"] or "conditional") == "dca":
            return True
        trigger_type = bot["trigger_type"]
        if trigger_type == "always":
            return True
        trigger_price = float(bot["trigger_price_points"] or 0)
        low_price = float(observed_low or observed_price or 0)
        high_price = float(observed_high or observed_price or 0)
        if trigger_type == "price_above":
            return high_price > 0 and high_price >= trigger_price
        if trigger_type == "price_below":
            return low_price > 0 and low_price <= trigger_price
        return False

    def _quantity_text_from_budget(self, *, budget_points, price_points):
        budget = int(budget_points or 0)
        price = _to_decimal(price_points, name="price_points", minimum=0)
        if budget <= 0 or price <= 0:
            raise ValueError("dca budget or price is invalid")
        units = int((Decimal(budget) * Decimal(ASSET_SCALE) / price).quantize(Decimal("1"), rounding=ROUND_DOWN))
        if units <= 0:
            raise ValueError("dca budget is too small for current price")
        return units_to_quantity(units)

    def _build_workflow_indicator_series(self, candles):
        candles = candles or []
        contexts = [{} for _ in candles]
        closes = []
        highs = []
        lows = []
        prev_close = None
        gain_count = 0
        avg_gain = None
        avg_loss = None
        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                continue
            try:
                close = float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt") or 0)
                high = float(candle.get("high_points") or candle.get("high_usdt") or close)
                low = float(candle.get("low_points") or candle.get("low_usdt") or close)
            except Exception:
                continue
            if not math.isfinite(close) or close <= 0:
                continue
            if not math.isfinite(high) or high <= 0:
                high = close
            if not math.isfinite(low) or low <= 0:
                low = close
            if prev_close is not None:
                delta = close - prev_close
                gain = max(delta, 0.0)
                loss = abs(min(delta, 0.0))
                gain_count += 1
                if gain_count == 14:
                    recent_closes = closes[-13:] + [close]
                    deltas = [recent_closes[i] - recent_closes[i - 1] for i in range(1, len(recent_closes))]
                    gains = [max(value, 0.0) for value in deltas]
                    losses = [abs(min(value, 0.0)) for value in deltas]
                    avg_gain = sum(gains) / 14.0
                    avg_loss = sum(losses) / 14.0
                elif gain_count > 14 and avg_gain is not None and avg_loss is not None:
                    avg_gain = ((avg_gain * 13.0) + gain) / 14.0
                    avg_loss = ((avg_loss * 13.0) + loss) / 14.0
            prev_close = close
            closes.append(close)
            highs.append(high)
            lows.append(low)

            ma20 = sum(closes[-20:]) / 20.0 if len(closes) >= 20 else None
            ma50 = sum(closes[-50:]) / 50.0 if len(closes) >= 50 else None
            ma200 = sum(closes[-200:]) / 200.0 if len(closes) >= 200 else None
            bb_mid = ma20
            bb_upper = None
            bb_lower = None
            bb_std = None
            if ma20 is not None:
                window20 = closes[-20:]
                variance = sum((value - ma20) ** 2 for value in window20) / 20.0
                bb_std = math.sqrt(variance)
                if bb_std > 0:
                    bb_upper = ma20 + 2 * bb_std
                    bb_lower = ma20 - 2 * bb_std
            kd_k = None
            if len(closes) >= 9:
                high9 = max(highs[-9:])
                low9 = min(lows[-9:])
                kd_k = 50.0 if high9 == low9 else ((close - low9) * 100.0 / (high9 - low9))
            rsi_value = None
            if gain_count >= 14 and avg_gain is not None and avg_loss is not None:
                if avg_loss == 0:
                    rsi_value = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi_value = 100.0 - (100.0 / (1.0 + rs))
            contexts[index] = {
                "price": close,
                "ma20": ma20,
                "ma50": ma50,
                "ma200": ma200,
                "bb_mid": bb_mid,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "bb_std": bb_std,
                "rsi": rsi_value,
                "kd": kd_k,
            }
        return contexts

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
            for offset in range(1, len(closes)):
                delta = closes[offset] - closes[offset - 1]
                gains.append(max(delta, 0))
                losses.append(abs(min(delta, 0)))
            if len(gains) < period:
                return None
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            for offset in range(period, len(gains)):
                avg_gain = ((avg_gain * (period - 1)) + gains[offset]) / period
                avg_loss = ((avg_loss * (period - 1)) + losses[offset]) / period
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        ma20 = sma(20)
        ma50 = sma(50)
        bb_mid = ma20
        bb_upper = None
        bb_lower = None
        bb_std = None
        if ma20 is not None and len(closes) >= 20:
            variance = sum((value - ma20) ** 2 for value in closes[-20:]) / 20
            bb_std = math.sqrt(variance)
            if bb_std > 0:
                bb_upper = ma20 + 2 * bb_std
                bb_lower = ma20 - 2 * bb_std
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
            "bb_std": bb_std,
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
        low_price = float(context.get("window_low_price") or price or 0)
        high_price = float(context.get("window_high_price") or price or 0)
        value = float(condition.get("value") or 0)
        if ctype == "always":
            return True
        if ctype == "price_below":
            return low_price > 0 and low_price <= value
        if ctype == "price_above":
            return high_price > 0 and high_price >= value
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
                return (
                    context.get("bb_upper") is not None
                    and float(context.get("bb_std") or 0) > 0
                    and price > float(context["bb_upper"])
                )
            if position == "below_lower":
                return (
                    context.get("bb_lower") is not None
                    and float(context.get("bb_std") or 0) > 0
                    and price < float(context["bb_lower"])
                )
        if ctype == "stop_loss_percent":
            pnl = context.get("pnl_low_percent")
            if pnl is None:
                pnl = context.get("pnl_percent")
            return pnl is not None and bool(context.get("has_position")) and pnl <= -abs(value)
        if ctype == "take_profit_percent":
            pnl = context.get("pnl_high_percent")
            if pnl is None:
                pnl = context.get("pnl_percent")
            return pnl is not None and bool(context.get("has_position")) and pnl >= abs(value)
        return False

    def _bot_condition_checks(self, bot, current_price):
        checks = []
        bot_type = str(bot.get("bot_type") or "conditional")
        if bot_type == "dca":
            interval = int(bot.get("interval_hours") or 24)
            last_run = bot.get("last_run_at")
            if last_run:
                try:
                    next_dt = datetime.fromisoformat(str(last_run)) + timedelta(hours=interval)
                    met = datetime.now() >= next_dt
                    checks.append({"label": f"距上次定投已滿 {interval}h", "met": met})
                except Exception:
                    checks.append({"label": f"定投間隔 {interval}h", "met": True})
            else:
                checks.append({"label": f"定投間隔 {interval}h（尚未執行過）", "met": True})
            return checks
        workflow = bot.get("workflow")
        if workflow and isinstance(workflow, dict):
            branches = workflow.get("branches") or []
            if branches:
                for i, branch in enumerate(branches):
                    cond = branch.get("condition")
                    if cond:
                        ctx = {"price": float(current_price or 0)}
                        met = self._workflow_condition_hit(cond, ctx)
                        label = _condition_label(cond)
                        checks.append({"label": f"分支{i + 1}: {label}", "met": met})
                return checks
            nodes = workflow.get("nodes") or []
            for node in nodes:
                if node.get("type") == "condition":
                    cond = node.get("condition")
                    if cond:
                        ctx = {"price": float(current_price or 0)}
                        met = self._workflow_condition_hit(cond, ctx)
                        label = _condition_label(cond)
                        checks.append({"label": f"節點 {node.get('id', '')}: {label}", "met": met})
            if not checks:
                checks.append({"label": "Workflow（無條件節點）", "met": True})
            return checks
        trigger_type = str(bot.get("trigger_type") or "always")
        if trigger_type == "always":
            checks.append({"label": "無條件觸發", "met": True})
        elif trigger_type == "price_above":
            threshold = float(_to_decimal(bot.get("trigger_price_points") or 0, name="trigger_price_points", minimum=0))
            live_price = float(_to_decimal(current_price or 0, name="current_price", minimum=0))
            met = live_price >= threshold
            checks.append({"label": f"價格 ≥ {_decimal_text(threshold)} 點（現價 {_decimal_text(live_price)}）", "met": met})
        elif trigger_type == "price_below":
            threshold = float(_to_decimal(bot.get("trigger_price_points") or 0, name="trigger_price_points", minimum=0))
            live_price = float(_to_decimal(current_price or 0, name="current_price", minimum=0))
            met = live_price <= threshold
            checks.append({"label": f"價格 ≤ {_decimal_text(threshold)} 點（現價 {_decimal_text(live_price)}）", "met": met})
        if bot.get("run_count") is not None and bot.get("max_runs") is not None:
            run_count = int(bot["run_count"])
            max_runs = int(bot["max_runs"])
            if max_runs == -1:
                checks.append({"label": f"執行次數 {run_count}/不限制", "met": True})
            else:
                checks.append({"label": f"執行次數 {run_count}/{max_runs}", "met": _bot_max_runs_has_remaining(run_count, max_runs)})
        cooldown = int(bot.get("cooldown_seconds") or 0)
        if cooldown > 0 and bot.get("last_run_at"):
            try:
                next_dt = datetime.fromisoformat(str(bot["last_run_at"])) + timedelta(seconds=cooldown)
                met = datetime.now() >= next_dt
                checks.append({"label": f"冷卻 {cooldown}s（{'已解除' if met else '冷卻中'}）", "met": met})
            except Exception:
                pass
        return checks

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
            if action.get("type") != "close_all" and int(action.get("step") or 1) <= int(branch_counts.get(action_id, 0)):
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
        limit_price = float(_to_decimal(action.get("limit_price_points") or 0, name="limit_price_points", minimum=0)) or None
        if atype in {"buy_percent", "buy_amount"}:
            available = int(funding.get("available_points") or 0)
            amount = int(float(action.get("amount_points") or 0))
            if atype == "buy_percent":
                amount = int(available * max(0.0, min(float(action.get("percent") or 0), 100.0)) / 100)
            fee_rate = float(market["fee_rate_percent"] or 0) / 100.0
            spend = max(0, min(amount, available))
            if spend <= 0:
                raise ValueError("workflow buy action has no available funds")
            price_decimal = _to_decimal(price_points or 0, name="price_points", minimum=0.00000001)
            spend_decimal = Decimal(str(spend)) / Decimal(str(1 + fee_rate))
            units = int((spend_decimal * Decimal(ASSET_SCALE) / price_decimal).quantize(Decimal("1"), rounding=ROUND_DOWN))
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

        return self._run_trading_bot_rows(rows)

    def run_trading_bot_once(self, *, actor, bot_uuid):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute(
                """
                SELECT b.*, u.username, u.role
                FROM trading_bots b
                JOIN users u ON u.id=b.user_id
                WHERE b.bot_uuid=? AND b.user_id=?
                LIMIT 1
                """,
                (str(bot_uuid or ""), user_id),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise ValueError("trading bot not found")
        if not bool(row["enabled"]):
            return {"ok": True, "scanned": 1, "triggered": [], "skipped": [{"bot_uuid": row["bot_uuid"], "reason": "disabled"}], "failed": []}
        if not _bot_max_runs_has_remaining(row["run_count"], row["max_runs"]):
            return {"ok": True, "scanned": 1, "triggered": [], "skipped": [{"bot_uuid": row["bot_uuid"], "reason": "max_runs_reached"}], "failed": []}
        return self._run_trading_bot_rows([row])

    def run_due_trading_bots(self, *, actor=None, limit=50):
        limit = _to_int(limit or 50, name="limit", minimum=1, maximum=200)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            settings = self._settings_payload(conn)
            if not settings.get("enabled", True):
                return {"ok": True, "enabled": False, "reason": "trading_disabled", "scanned": 0, "triggered": [], "skipped": [], "failed": []}
            if not settings.get("bot_auto_scan_enabled", True):
                return {"ok": True, "enabled": False, "reason": "bot_auto_scan_disabled", "scanned": 0, "triggered": [], "skipped": [], "failed": []}
            user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            active_clauses = []
            if "status" in user_cols:
                active_clauses.append("COALESCE(u.status, 'active') = 'active'")
            if "deleted_at" in user_cols:
                active_clauses.append("COALESCE(u.deleted_at, '') = ''")
            active_sql = " AND ".join(active_clauses) if active_clauses else "1=1"
            rows = conn.execute(
                f"""
                SELECT b.*, u.username, u.role
                FROM trading_bots b
                JOIN users u ON u.id=b.user_id
                WHERE b.enabled=1 AND b.run_count < b.max_runs AND {active_sql}
                ORDER BY b.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        result = self._run_trading_bot_rows(rows)
        result["enabled"] = True
        return result

    def _run_trading_bot_rows(self, rows):
        scanned = 0
        triggered = []
        skipped = []
        failed = []
        for row in rows:
            scanned += 1
            price_conn = None
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
                settings = self._settings_payload(price_conn)
                observed_price, price_source, price_meta = self._current_market_price_points(price_conn, market, with_meta=True, high_risk=True)
                self._assert_price_meta_allows_high_risk_use(
                    price_conn,
                    actor={"id": int(row["user_id"]), "username": row["username"], "role": row["role"]},
                    market_symbol=market["symbol"],
                    usage="trading bot trigger",
                    price_meta=price_meta,
                )
                price_window = self._recent_price_window(
                    market["symbol"],
                    lookback_seconds=max(60, int(settings.get("bot_auto_scan_interval_seconds") or 30) + 5),
                    since_time_text=row["last_scan_at"] if "last_scan_at" in row.keys() else None,
                )
                observed_low = float((price_window or {}).get("low_points") or observed_price)
                observed_high = float((price_window or {}).get("high_points") or observed_price)
                workflow = _json_loads(row["workflow_json"], None) if "workflow_json" in row.keys() else None
                order_payload = None
                if workflow and str(row["bot_type"] or "conditional") == "conditional":
                    context = self._workflow_live_context(
                        price_conn,
                        market=market,
                        user_id=int(row["user_id"]),
                        observed_price=observed_price,
                        observed_low=observed_low,
                        observed_high=observed_high,
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
                        price_conn = None
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
                        price_conn = None
                        self._record_bot_run(row, status="skipped", observed_price=observed_price, error="workflow_hold")
                        skipped.append({"bot_uuid": row["bot_uuid"], "reason": "workflow_hold", "observed_price_points": observed_price})
                        continue
                price_conn.close()
                price_conn = None
                if not workflow and not self._bot_trigger_hit(row, observed_price, observed_low=observed_low, observed_high=observed_high):
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
                if price_conn is not None:
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
            settings = self._settings_payload(conn)
            fee_rate_percent = float(market["fee_rate_percent"] or 0)
            grid_fee_rate_percent = self._grid_fee_rate_percent(fee_rate_percent, settings)
            if payload.get("max_price_jump_percent") is not None:
                max_price_jump_percent = float(payload.get("max_price_jump_percent"))
            else:
                max_price_jump_percent = max(float(market["max_price_jump_percent"] or 0), 70.0)
        finally:
            conn.close()
        strategy = str(payload.get("strategy") or payload.get("bot_type") or "conditional").strip().lower()
        if strategy == "strategy":
            strategy = "workflow"
        if strategy not in {"conditional", "dca", "workflow", "grid"}:
            raise ValueError("backtest strategy must be conditional, workflow, dca, or grid")
        workflow = None
        if strategy == "workflow":
            workflow = self._validate_workflow(payload.get("workflow_json") or payload.get("workflow"))
        cash = _to_int(payload.get("initial_cash_points", 10_000), name="initial_cash_points", minimum=1, maximum=10**12)
        order_points = _to_int(payload.get("order_points", 100), name="order_points", minimum=1, maximum=10**12)
        trigger_type = str(payload.get("trigger_type") or "price_below").strip().lower()
        trigger_price = float(_to_decimal(payload.get("trigger_price_points") or 0, name="trigger_price_points", minimum=0))
        interval_candles = _to_int(payload.get("interval_candles", 1), name="interval_candles", minimum=1, maximum=10_000)
        initial_cash = cash
        initial_workflow_state = payload.get("initial_workflow_state") if isinstance(payload.get("initial_workflow_state"), dict) else {}
        range_warnings = []
        state = {
            "cash": cash,
            "units": int(payload.get("initial_units") or 0),
            "avg_cost_bt": float(payload.get("initial_avg_cost") or 0),
            "trades": [],
            "equity_curve": [],
            "peak_value": cash,
            "max_drawdown_percent": 0.0,
            "wins": 0,
            "sells": 0,
            "trade_count": int(payload.get("initial_trade_count") or 0),
            "processed_candles": int(payload.get("initial_candle_offset") or 0),
            "workflow_state": {
                "executed_action_ids": set(initial_workflow_state.get("executed_action_ids") or []),
                "branch_step_counts": {
                    str(k): int(v)
                    for k, v in (initial_workflow_state.get("branch_step_counts") or {}).items()
                },
            },
            "grid_initialized": False,
            "grid_state": {},
            "grid_levels": [],
            "grid_order_amount": 0,
            "grid_fee_rate": grid_fee_rate_percent,
            "last_valid_price": None,
            "recent_valid_prices": [],
            "outlier_skipped_count": 0,
        }
        workflow_indicator_series = self._build_workflow_indicator_series(candles) if strategy == "workflow" else []

        def _record_equity(global_index, candle, price):
            equity = state["cash"] + notional_points(state["units"], price)
            state["peak_value"] = max(state["peak_value"], equity)
            if state["peak_value"] > 0:
                state["max_drawdown_percent"] = max(
                    state["max_drawdown_percent"],
                    round((state["peak_value"] - equity) * 100 / state["peak_value"], 4),
                )
            state["equity_curve"].append({
                "index": global_index,
                "time": candle.get("time") or candle.get("time_iso") or global_index,
                "equity_points": equity,
                "price_points": price,
            })

        def _ensure_grid_state(chunk_candles):
            if strategy != "grid" or state["grid_initialized"]:
                return
            g_lower = _to_price_float(payload.get("lower_price_points", 0), name="lower_price_points", minimum=0.00000001)
            g_upper = _to_price_float(payload.get("upper_price_points", 0), name="upper_price_points", minimum=0.00000002)
            g_count = _to_int(payload.get("grid_count", 10), name="grid_count", minimum=2, maximum=500)
            state["grid_order_amount"] = _to_int(payload.get("order_amount_points", 100), name="order_amount_points", minimum=1)
            g_mode = str(payload.get("spacing_mode") or "arithmetic").strip().lower()
            if g_upper <= g_lower:
                raise ValueError("upper_price_points must be greater than lower_price_points")
            if g_mode == "geometric":
                g_ratio = (g_upper / g_lower) ** (1 / (g_count - 1))
                state["grid_levels"] = [
                    float(
                        Decimal(str(g_lower * (g_ratio ** i))).quantize(
                            Decimal("0.00000001"),
                            rounding=ROUND_HALF_UP,
                        )
                    )
                    for i in range(g_count)
                ]
            else:
                g_step = (g_upper - g_lower) / (g_count - 1)
                state["grid_levels"] = [
                    float(
                        Decimal(str(g_lower + g_step * i)).quantize(
                            Decimal("0.00000001"),
                            rounding=ROUND_HALF_UP,
                        )
                    )
                    for i in range(g_count)
                ]
            g_start = 0
            for _c in chunk_candles:
                try:
                    g_start = float(
                        _to_decimal(
                            _c.get("close_points") or _c.get("price_points") or _c.get("close_usdt") or _c.get("price_usdt") or 0,
                            name="grid_start_price",
                            minimum=0,
                        )
                    )
                    if g_start > 0:
                        break
                except Exception:
                    pass
            if g_start <= 0:
                raise ValueError("no valid starting price in candles for grid backtest")
            sell_lvls = [p for p in state["grid_levels"] if p > g_start]
            buy_lvls = [p for p in state["grid_levels"] if p < g_start]
            spot_units_needed = sum(int((state["grid_order_amount"] * ASSET_SCALE) // p) for p in sell_lvls if p > 0)
            spot_cost = notional_points(spot_units_needed, g_start)
            spot_fee_cost = fee_points(spot_cost, fee_rate_percent)
            spot_total = spot_cost + spot_fee_cost
            buy_fee_per = fee_points(state["grid_order_amount"], state["grid_fee_rate"])
            buy_total = len(buy_lvls) * (state["grid_order_amount"] + buy_fee_per)
            if state["cash"] >= spot_total + buy_total:
                state["cash"] -= spot_total
                state["units"] = spot_units_needed
            else:
                affordable_spot = max(0, state["cash"] - buy_total)
                if affordable_spot > 0 and g_start > 0:
                    state["units"] = int(affordable_spot * ASSET_SCALE // g_start)
                    state["cash"] -= notional_points(state["units"], g_start) + fee_points(notional_points(state["units"], g_start), fee_rate_percent)
                    if state["cash"] < 0:
                        state["cash"] = 0
            state["grid_state"] = {}
            for price_level in state["grid_levels"]:
                if price_level < g_start:
                    state["grid_state"][price_level] = "buy"
                elif price_level > g_start:
                    state["grid_state"][price_level] = "sell"
                else:
                    state["grid_state"][price_level] = None
            state["grid_initialized"] = True

        def _run_chunk(chunk_candles):
            _ensure_grid_state(chunk_candles)
            for local_index, candle in enumerate(chunk_candles):
                global_index = state["processed_candles"] + local_index
                try:
                    price = float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt"))
                except Exception:
                    continue
                if not math.isfinite(price) or price <= 0:
                    continue
                anchor_prices = [float(value) for value in (state.get("recent_valid_prices") or []) if float(value or 0) > 0]
                anchor_price = 0
                if anchor_prices:
                    sorted_anchor = sorted(anchor_prices)
                    anchor_price = float(sorted_anchor[len(sorted_anchor) // 2])
                elif state["last_valid_price"]:
                    anchor_price = float(state["last_valid_price"])
                if anchor_price > 0 and max_price_jump_percent > 0:
                    jump_percent = abs(price - anchor_price) * 100.0 / anchor_price
                    if jump_percent > max_price_jump_percent:
                        state["outlier_skipped_count"] += 1
                        if state["outlier_skipped_count"] <= 5:
                            candle_time = candle.get("time_iso") or candle.get("time") or global_index
                            range_warnings.append(
                                f"已略過跳價 {jump_percent:.2f}% 的 K 線（時間 {candle_time}，價格 {price}，參考價 {anchor_price}，上限 {max_price_jump_percent:.2f}%）"
                            )
                        continue
                state["last_valid_price"] = price
                state["recent_valid_prices"].append(price)
                state["recent_valid_prices"] = state["recent_valid_prices"][-5:]

                if strategy == "grid":
                    try:
                        low_p = float(candle.get("low_points") or candle.get("low_usdt") or price)
                        high_p = float(candle.get("high_points") or candle.get("high_usdt") or price)
                    except Exception:
                        low_p = high_p = price
                    state_at_open = dict(state["grid_state"])
                    for lvl in sorted(state_at_open):
                        if state_at_open[lvl] == "sell" and high_p >= lvl:
                            sell_u = int((state["grid_order_amount"] * ASSET_SCALE) // lvl)
                            if state["units"] >= sell_u > 0:
                                gross = notional_points(sell_u, lvl)
                                fee = fee_points(gross, state["grid_fee_rate"])
                                net = max(0, gross - fee)
                                state["cash"] += net
                                state["units"] -= sell_u
                                state["trades"].append({
                                    "index": global_index,
                                    "time": candle.get("time") or candle.get("time_iso") or global_index,
                                    "side": "sell",
                                    "price_points": lvl,
                                    "spend_points": 0,
                                    "fee_points": fee,
                                    "quantity": units_to_quantity(sell_u),
                                })
                                state["trade_count"] += 1
                                state["grid_state"][lvl] = None
                                try:
                                    counter_idx = state["grid_levels"].index(lvl) - 1
                                except ValueError:
                                    counter_idx = -1
                                if counter_idx >= 0:
                                    counter_lvl = state["grid_levels"][counter_idx]
                                    if state["grid_state"].get(counter_lvl) is None:
                                        state["grid_state"][counter_lvl] = "buy"
                                state["sells"] += 1
                                state["wins"] += 1
                    for lvl in sorted(state_at_open, reverse=True):
                        if state_at_open[lvl] == "buy" and low_p <= lvl:
                            fee = fee_points(state["grid_order_amount"], state["grid_fee_rate"])
                            spend = state["grid_order_amount"] + fee
                            if state["cash"] >= spend:
                                buy_u = int((state["grid_order_amount"] * ASSET_SCALE) // lvl)
                                if buy_u > 0:
                                    state["cash"] -= spend
                                    prev_u = state["units"]
                                    state["units"] += buy_u
                                    if state["units"] > 0:
                                        state["avg_cost_bt"] = int((prev_u * state["avg_cost_bt"] + buy_u * lvl) // state["units"])
                                    state["trades"].append({
                                        "index": global_index,
                                        "time": candle.get("time") or candle.get("time_iso") or global_index,
                                        "side": "buy",
                                        "price_points": lvl,
                                        "spend_points": spend,
                                        "fee_points": fee,
                                        "quantity": units_to_quantity(buy_u),
                                    })
                                    state["trade_count"] += 1
                                    state["grid_state"][lvl] = None
                                    try:
                                        counter_idx = state["grid_levels"].index(lvl) + 1
                                    except ValueError:
                                        counter_idx = len(state["grid_levels"])
                                    if counter_idx < len(state["grid_levels"]):
                                        counter_lvl = state["grid_levels"][counter_idx]
                                        if state["grid_state"].get(counter_lvl) is None:
                                            state["grid_state"][counter_lvl] = "sell"
                    _record_equity(global_index, candle, price)
                    continue

                should_buy = False
                should_sell = False
                workflow_spend = order_points
                workflow_sell_percent = 0.0
                decision = None
                if strategy == "dca":
                    should_buy = global_index % interval_candles == 0
                elif strategy == "workflow":
                    context = dict(workflow_indicator_series[global_index] or {})
                    context["price"] = price
                    context["has_position"] = state["units"] > 0
                    context["avg_cost"] = state["avg_cost_bt"]
                    context["pnl_percent"] = round((price - state["avg_cost_bt"]) * 100.0 / state["avg_cost_bt"], 4) if state["units"] > 0 and state["avg_cost_bt"] > 0 else None
                    decision = self._workflow_decision(
                        workflow,
                        context=context,
                        run_count=state["trade_count"],
                        last_run_at=None,
                        execution_state=state["workflow_state"],
                    )
                    action = (decision or {}).get("action") or {}
                    atype = str(action.get("type") or "hold")
                    if atype in {"buy_percent", "buy_amount"}:
                        should_buy = True
                        workflow_spend = int(float(action.get("amount_points") or 0))
                        if atype == "buy_percent":
                            workflow_spend = int(state["cash"] * max(0.0, min(float(action.get("percent") or 0), 100.0)) / 100)
                    elif atype in {"sell_percent", "close_all"}:
                        should_sell = True
                        workflow_sell_percent = 100.0 if atype == "close_all" else max(0.0, min(float(action.get("percent") or 0), 100.0))
                elif trigger_type == "price_below":
                    should_buy = trigger_price > 0 and price <= trigger_price
                elif trigger_type == "price_above":
                    should_buy = trigger_price > 0 and price >= trigger_price
                elif trigger_type == "always":
                    should_buy = True
                if should_sell and state["units"] > 0:
                    sell_units = int(state["units"] * workflow_sell_percent / 100)
                    if sell_units > 0:
                        gross = notional_points(sell_units, price)
                        fee = fee_points(gross, fee_rate_percent)
                        state["cash"] += max(0, gross - fee)
                        state["units"] -= sell_units
                        if state["units"] <= 0:
                            state["avg_cost_bt"] = 0
                        state["trades"].append({
                            "index": global_index,
                            "time": candle.get("time") or candle.get("time_iso") or global_index,
                            "side": "sell",
                            "price_points": price,
                            "spend_points": 0,
                            "fee_points": fee,
                            "pnl_points": max(0, gross - fee),
                            "quantity": units_to_quantity(sell_units),
                        })
                        state["trade_count"] += 1
                        state["sells"] += 1
                        if gross - fee > 0:
                            state["wins"] += 1
                        if strategy == "workflow" and decision:
                            action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                            if action_id:
                                state["workflow_state"]["executed_action_ids"].add(action_id)
                            branch_id = (decision.get("branch") or {}).get("id")
                            if branch_id:
                                state["workflow_state"]["branch_step_counts"][branch_id] = int(state["workflow_state"]["branch_step_counts"].get(branch_id, 0)) + 1
                        _record_equity(global_index, candle, price)
                    else:
                        _record_equity(global_index, candle, price)
                    continue
                if not should_buy or state["cash"] <= 0:
                    _record_equity(global_index, candle, price)
                    continue
                spend = min(workflow_spend, state["cash"])
                fee = fee_points(spend, fee_rate_percent)
                net_spend = max(0, spend - fee)
                buy_units = int((Decimal(str(net_spend)) * Decimal(ASSET_SCALE) / Decimal(str(price))).quantize(Decimal("1"), rounding=ROUND_DOWN))
                if buy_units <= 0:
                    _record_equity(global_index, candle, price)
                    continue
                state["cash"] -= spend
                prev_units = state["units"]
                state["units"] += buy_units
                if state["units"] > 0:
                    state["avg_cost_bt"] = float(((Decimal(str(prev_units)) * Decimal(str(state["avg_cost_bt"]))) + (Decimal(str(buy_units)) * Decimal(str(price)))) / Decimal(str(state["units"])))
                state["trades"].append({
                    "index": global_index,
                    "time": candle.get("time") or candle.get("time_iso") or global_index,
                    "side": "buy",
                    "price_points": price,
                    "spend_points": spend,
                    "fee_points": fee,
                    "quantity": units_to_quantity(buy_units),
                })
                state["trade_count"] += 1
                if strategy == "workflow" and decision:
                    action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                    if action_id:
                        state["workflow_state"]["executed_action_ids"].add(action_id)
                    branch_id = (decision.get("branch") or {}).get("id")
                    if branch_id:
                        state["workflow_state"]["branch_step_counts"][branch_id] = int(state["workflow_state"]["branch_step_counts"].get(branch_id, 0)) + 1
                _record_equity(global_index, candle, price)
            state["processed_candles"] += len(chunk_candles)

        segment_count = max(1, math.ceil(len(candles) / BACKTEST_SEGMENT_CANDLES))
        for segment_index in range(segment_count):
            chunk = candles[
                segment_index * BACKTEST_SEGMENT_CANDLES:
                (segment_index + 1) * BACKTEST_SEGMENT_CANDLES
            ]
            if chunk:
                _run_chunk(chunk)
        last_price = 0
        last_price = float(state["last_valid_price"] or 0)
        position_value = notional_points(state["units"], last_price) if last_price else 0
        final_value = state["cash"] + position_value
        all_candles_raw = payload.get("candles") or []
        if start_time and all_candles_raw:
            first_raw = str(all_candles_raw[0].get("time_iso") or all_candles_raw[0].get("time") or "")
            if first_raw and start_time < first_raw:
                range_warnings.append(f"請求起始時間 {start_time} 早於資料最早 K 線 {first_raw}，實際回測從 {first_raw} 開始")
        if end_time and all_candles_raw:
            last_raw = str(all_candles_raw[-1].get("time_iso") or all_candles_raw[-1].get("time") or "")
            if last_raw and end_time > last_raw:
                range_warnings.append(f"請求結束時間 {end_time} 晚於資料最新 K 線 {last_raw}，實際回測至 {last_raw}")
        if len(all_candles_raw) >= MAX_BACKTEST_CANDLES:
            range_warnings.append(f"K 線數量達到上限 {MAX_BACKTEST_CANDLES} 根，更早的歷史資料可能未被包含")
        if segment_count > 1:
            range_warnings.append(f"回測資料共 {len(candles)} 根 K 線，後端已自動分成 {segment_count} 批連續執行（每批最多 {BACKTEST_SEGMENT_CANDLES} 根）")
        if state["outlier_skipped_count"] > 5:
            range_warnings.append(f"另有 {state['outlier_skipped_count'] - 5} 根跳價 K 線超過 {max_price_jump_percent:.2f}% 已被略過")
        return {
            "ok": True,
            "strategy": strategy,
            "market_symbol": market["symbol"],
            "data_source": str(payload.get("data_source") or ("provided_candles" if payload.get("candles") else "")),
            "provider_symbol": str(payload.get("provider_symbol") or ""),
            "candle_count": len(candles),
            "max_backtest_candles": MAX_BACKTEST_CANDLES,
            "max_backtest_candles_per_batch": BACKTEST_SEGMENT_CANDLES,
            "requested_candle_limit": payload.get("requested_candle_limit") or payload.get("candle_limit") or payload.get("limit") or len(candles),
            "first_candle_time": candles[0].get("time_iso") or candles[0].get("time") if candles else "",
            "last_candle_time": candles[-1].get("time_iso") or candles[-1].get("time") if candles else "",
            "initial_cash_points": initial_cash,
            "cash_points": state["cash"],
            "position_quantity": units_to_quantity(state["units"]),
            "position_value_points": position_value,
            "final_value_points": final_value,
            "pnl_points": final_value - initial_cash,
            "return_percent": round(((final_value - initial_cash) * 100) / initial_cash, 4),
            "max_drawdown_percent": state["max_drawdown_percent"],
            "win_rate_percent": round((state["wins"] * 100 / state["sells"]), 4) if state["sells"] else 0.0,
            "trade_count": len(state["trades"]),
            "trades": state["trades"],
            "equity_curve": state["equity_curve"],
            "start_time": start_time,
            "end_time": end_time,
            "range_warnings": range_warnings,
            "outlier_skipped_count": state["outlier_skipped_count"],
            "max_price_jump_percent": max_price_jump_percent,
            "end_units": state["units"],
            "end_avg_cost": state["avg_cost_bt"],
            "end_cash_points": state["cash"],
            "segmented_backtest": segment_count > 1,
            "segmented_backtest_batches": segment_count,
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
                        "UPDATE trading_bots SET run_count=run_count+1, last_run_at=?, execution_state_json=?, last_error='', last_scan_at=?, updated_at=? WHERE id=?",
                        (now, _json_dumps(execution_state), now, now, int(bot["id"])),
                    )
                else:
                    conn.execute(
                        "UPDATE trading_bots SET run_count=run_count+1, last_run_at=?, last_error='', last_scan_at=?, updated_at=? WHERE id=?",
                        (now, now, now, int(bot["id"])),
                    )
            elif status == "failed":
                conn.execute(
                    "UPDATE trading_bots SET run_count=run_count+1, last_run_at=?, last_error=?, updated_at=? WHERE id=?",
                    (now, str(error or "")[:240], now, int(bot["id"])),
                )
                create_notification_if_enabled(
                    conn,
                    user_id=int(bot["user_id"]),
                    type="trading_bot_failed",
                    title="交易機器人執行失敗",
                    body=f"{bot['name']} 執行失敗：{str(error or '')[:120]}",
                    link="/trading",
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

    def place_order(self, *, actor, market_symbol, side, order_type, quantity, limit_price_points=None, emergency_close=False, is_grid_order=False):
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
        is_grid_order = bool(is_grid_order)
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
            current_price, price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True, high_risk=(order_type == "market"))
            if order_type == "market":
                self._assert_price_meta_allows_high_risk_use(
                    conn,
                    actor=actor,
                    market_symbol=market["symbol"],
                    usage="market order",
                    price_meta=price_meta,
                )
            if order_type == "limit":
                limit_price = _to_price_float(limit_price_points, name="limit_price_points", minimum=0.00000001)
            else:
                limit_price = None
            check_price = float(_to_decimal(limit_price or current_price, name="check_price", minimum=0.00000001))
            estimated_notional = notional_points(quantity_units, check_price)
            base_fee_rate = float(market["fee_rate_percent"] or 0)
            settings = self._settings_payload(conn)
            if emergency_close:
                effective_fee_rate_percent = base_fee_rate * 2
            elif is_grid_order:
                effective_fee_rate_percent = self._grid_fee_rate_percent(base_fee_rate, settings)
            else:
                effective_fee_rate_percent = base_fee_rate
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
            if emergency_close:
                order_reason = "EMERGENCY_MARKET_CLOSE"
            elif is_grid_order:
                order_reason = "GRID_ORDER"
            else:
                order_reason = ""
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
        price = float(_to_decimal(order["execution_price_points"] or market["manual_price_points"], name="execution_price_points", minimum=0.00000001))
        notional = notional_points(quantity_units, price)
        order_reason = str(order["reason"] or "")
        emergency_close = order_reason == "EMERGENCY_MARKET_CLOSE"
        is_grid_order = order_reason == "GRID_ORDER"
        base_fee_rate = float(market["fee_rate_percent"] or 0)
        settings = self._settings_payload(conn)
        if emergency_close:
            effective_fee_rate_percent = base_fee_rate * 2
        elif is_grid_order:
            effective_fee_rate_percent = self._grid_fee_rate_percent(base_fee_rate, settings)
        else:
            effective_fee_rate_percent = base_fee_rate
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
            prev_cost = _to_decimal(position["avg_cost_points"] or 0, name="avg_cost_points", minimum=0)
            next_qty = prev_qty + quantity_units
            next_avg = (
                float(
                    (
                        (
                            (Decimal(prev_qty) * prev_cost)
                            + (Decimal(quantity_units) * Decimal(str(price)))
                        )
                        / Decimal(next_qty)
                    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                )
                if next_qty
                else 0
            )
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
            avg_cost = float(_to_decimal(position["avg_cost_points"] or 0, name="avg_cost_points", minimum=0))
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
        if funding_mode != "root_simulated":
            self._record_user_trade_volume(
                conn,
                user_id=user_id,
                trade_kind="spot",
                notional_points=notional,
                fee_points=fee,
                occurred_at=_now(),
            )
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

    def open_margin_position(self, *, actor, market_symbol, position_type, quantity, collateral_points, idempotency_key=None):
        user_id = self._actor_id(actor)
        if not user_id:
            raise ValueError("login required")
        position_type = str(position_type or "").strip().lower()
        if position_type not in {"margin_long", "short"}:
            raise ValueError("position_type must be margin_long or short")
        quantity_units = quantity_to_units(quantity)
        collateral = _to_int(collateral_points, name="collateral_points", minimum=1, maximum=10**12)
        operation_key = _client_idempotency_key(idempotency_key, prefix=f"margin_open:{user_id}")
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
                    WHERE idempotency_key=? AND operation='margin_open'
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
                    ) VALUES (?, 'margin_open', ?, '', '', ?, ?)
                    """,
                    (operation_key, int(user_id), _now(), _now()),
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
                    raise ValueError("duplicate margin open request is still processing")
            borrow_settings = self._assert_borrowing_enabled(conn)
            market = self._market(conn, market_symbol)
            price, price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True, high_risk=True)
            self._assert_price_meta_allows_high_risk_use(
                conn,
                actor=actor,
                market_symbol=market["symbol"],
                usage="margin financing risk evaluation",
                price_meta=price_meta,
            )
            notional = notional_points(quantity_units, price)
            min_collateral = self._minimum_margin_collateral_points(
                conn,
                position_type=position_type,
                notional=notional,
                fee_rate_percent=float(market["fee_rate_percent"] or 0),
            )
            if collateral < min_collateral:
                raise ValueError(f"collateral below minimum {min_collateral}")
            fee = fee_points(notional, float(market["fee_rate_percent"] or 0))
            if position_type == "margin_long" and collateral >= notional:
                raise ValueError(f"collateral must be lower than notional {notional} for margin long")
            principal = max(0, notional - collateral) if position_type == "margin_long" else notional
            settings = self._settings_payload(conn)
            borrowed_asset_symbol = self._margin_borrowed_asset_symbol(market, position_type)
            interest_interval_hours = int(settings.get("borrow_interest_interval_hours") or DEFAULT_BORROW_INTEREST_INTERVAL_HOURS)
            interest_minimum_hours = int(settings.get("borrow_interest_minimum_hours") or DEFAULT_BORROW_INTEREST_MINIMUM_HOURS)
            funding_pool = self._funding_pool_payload(conn, requested_principal=principal, borrowed_asset=borrowed_asset_symbol)
            if not self._is_root_actor(actor) and principal > int(funding_pool["available_points"] or 0):
                raise ValueError("funding pool is insufficient for requested borrow amount")
            effective_interest_percent_daily = float(funding_pool["projected_interest_percent_daily"] if principal else funding_pool["effective_interest_percent_daily"])
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
            if principal and not is_root_simulated:
                self._reserve_delta(conn, delta=-principal, event_type="margin_principal_lent", reason="TRADING_MARGIN_PRINCIPAL_LENT", actor=actor)
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO trading_margin_positions (
                    position_uuid, user_id, market_symbol, position_type, quantity_units,
                    entry_price_points, principal_points, collateral_points, open_fee_points,
                    interest_percent_daily, interest_paid_points, interest_accrued_hours, interest_interval_hours,
                    interest_minimum_hours, borrowed_asset_symbol, status, opened_at, updated_at,
                    collateral_trial_points, collateral_chain_points, open_fee_trial_points, open_fee_chain_points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
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
                    effective_interest_percent_daily,
                    interest_interval_hours,
                    interest_minimum_hours,
                    borrowed_asset_symbol,
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
                    "funding_pool_available_before": funding_pool["available_points"],
                    "funding_pool_projected_utilization_percent": funding_pool["projected_utilization_percent"],
                    "borrowed_asset_symbol": borrowed_asset_symbol,
                    "base_interest_apr_percent": funding_pool["base_interest_apr_percent"],
                    "effective_interest_apr_percent": funding_pool["projected_interest_apr_percent"] if principal else funding_pool["effective_interest_apr_percent"],
                    "base_interest_percent_daily": funding_pool["base_interest_percent_daily"],
                    "effective_interest_percent_daily": effective_interest_percent_daily,
                    "interest_interval_hours": interest_interval_hours,
                    "interest_minimum_hours": interest_minimum_hours,
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
            if not is_root_simulated:
                self._record_user_trade_volume(
                    conn,
                    user_id=user_id,
                    trade_kind="margin",
                    notional_points=notional,
                    fee_points=fee,
                    occurred_at=now,
                )
            conn.commit()
            row = conn.execute("SELECT * FROM trading_margin_positions WHERE id=?", (cur.lastrowid,)).fetchone()
            result = {"ok": True, "position": self._margin_position_payload(row), "funding": self._funding_payload(conn, user_id)}
            if operation_key:
                conn.execute(
                    """
                    UPDATE trading_operation_idempotency
                    SET reference_uuid=?, response_json=?, updated_at=?
                    WHERE idempotency_key=?
                    """,
                    (position_uuid, _json_dumps(result), _now(), operation_key),
                )
                conn.commit()
            return result
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

    def close_margin_position(self, *, actor, position_uuid, force_liquidation=False, price_override_points=None, price_source_override=None):
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
            position = self._accrue_margin_interest(conn, position, actor=actor)
            market = self._market(conn, position["market_symbol"])
            risk = self._margin_risk_payload(
                conn,
                position,
                market,
                price_override_points=price_override_points,
                price_source_override=price_source_override,
            )
            account_risk = None
            if force_liquidation:
                open_rows = [
                    self._margin_position_payload_with_risk(
                        conn,
                        row,
                        risk_overrides={
                            "price_override_points": price_override_points if row["market_symbol"] == position["market_symbol"] else None,
                            "price_source_override": price_source_override if row["market_symbol"] == position["market_symbol"] else None,
                        } if price_override_points is not None else None,
                    )
                    for row in conn.execute(
                        "SELECT * FROM trading_margin_positions WHERE user_id=? AND status='open' ORDER BY id ASC",
                        (user_id,),
                    ).fetchall()
                ]
                account_risk = self._margin_account_payload(conn, user_id, open_rows)
                if not account_risk.get("liquidation_required"):
                    raise ValueError("margin position recovered above liquidation threshold")
            price = risk["price_points"]
            price_source = risk["price_source"]
            close_fee = risk["close_fee_points"]
            interest = risk["interest_points"]
            principal = int(position["principal_points"] or 0)
            collateral = int(position["collateral_points"] or 0)
            collateral_trial = int(position["collateral_trial_points"] or 0) if "collateral_trial_points" in position.keys() else 0
            collateral_chain = int(position["collateral_chain_points"] or 0) if "collateral_chain_points" in position.keys() else collateral
            delta = risk["delta_points"]
            ledger_uuids = []
            is_root_simulated = self._is_root_user_id(conn, user_id)
            if principal and not is_root_simulated:
                self._reserve_delta(conn, delta=principal, event_type="margin_principal_repaid", reason="TRADING_MARGIN_PRINCIPAL_REPAID", actor=actor)
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
                self._reserve_delta(conn, delta=-delta, event_type="margin_profit_paid", reason="TRADING_MARGIN_PROFIT_PAID", actor=actor)
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
                SET close_fee_points=?, interest_points=?, exit_price_points=?, realized_pnl_points=?, status=?, closed_at=?, updated_at=?
                WHERE id=?
                """,
                (close_fee, interest, price, delta, next_status, now, now, position["id"]),
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
                    "entry_price_points": float(_to_decimal(position["entry_price_points"], name="entry_price_points", minimum=0)),
                    "exit_price_points": price,
                    "price_source": price_source,
                    "delta_points": delta,
                    "interest_points": interest,
                    "close_fee_points": close_fee,
                    "funding_mode": "root_simulated" if is_root_simulated else ("trial_mixed" if collateral_trial else "points_chain"),
                    "risk": risk,
                    "account_risk": account_risk,
                    "ledger_uuids": ledger_uuids,
                },
            )
            if not is_root_simulated:
                self._record_user_trade_volume(
                    conn,
                    user_id=user_id,
                    trade_kind="margin",
                    notional_points=int(risk.get("exit_notional_points") or 0),
                    fee_points=close_fee,
                    occurred_at=now,
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
            positions_by_user = {}
            for position in rows:
                try:
                    position = self._accrue_margin_interest(conn, position, actor=actor)
                    market = self._market(conn, position["market_symbol"])
                    current_price, price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True, high_risk=True)
                    if bool(price_meta.get("high_risk_blocked")):
                        errors.append({
                            "position_uuid": position["position_uuid"],
                            "user_id": int(position["user_id"]),
                            "error": str(price_meta.get("high_risk_block_reason") or "price source is in conservative mode"),
                            "price_health": str(price_meta.get("price_health") or ""),
                        })
                        continue
                    price_window = self._recent_price_window(market["symbol"], lookback_seconds=65, interval="1m")
                    replay_price = float(current_price)
                    if price_window:
                        if position["position_type"] == "margin_long":
                            replay_price = min(float(current_price), float(price_window["low_points"]))
                        else:
                            replay_price = max(float(current_price), float(price_window["high_points"]))
                    payload = self._margin_position_payload_with_risk(
                        conn,
                        position,
                        market=market,
                        risk_overrides={
                            "price_override_points": replay_price,
                            "price_source_override": f"{price_source}+scan_window" if replay_price != current_price else price_source,
                        },
                    )
                    risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
                    self._notify_margin_risk_alerts(conn, position=position, risk=risk, market=market)
                    positions_by_user.setdefault(int(position["user_id"]), []).append(payload)
                except Exception as exc:
                    errors.append({
                        "position_uuid": position["position_uuid"],
                        "user_id": int(position["user_id"]),
                        "error": str(exc),
                    })
            for user_id, user_positions in positions_by_user.items():
                account_risk = self._margin_account_payload(conn, user_id, user_positions)
                if not account_risk.get("liquidation_required"):
                    continue
                ordered = sorted(
                    [row for row in user_positions if row.get("status") == "open"],
                    key=self._margin_liquidation_order_key,
                )
                if not ordered:
                    continue
                first = ordered[0]
                candidates.append({
                    "position_uuid": first["position_uuid"],
                    "user_id": int(first["user_id"]),
                    "market_symbol": first["market_symbol"],
                    "position_type": first["position_type"],
                    "risk": first.get("risk") or {},
                    "account_risk": account_risk,
                    "liquidation_order": [row["position_uuid"] for row in ordered],
                })
            conn.commit()
        finally:
            conn.close()

        liquidated = []
        for candidate in candidates:
            try:
                result = self.close_margin_position(
                    actor=actor,
                    position_uuid=candidate["position_uuid"],
                    force_liquidation=True,
                    price_override_points=(candidate.get("risk") or {}).get("price_points"),
                    price_source_override=(candidate.get("risk") or {}).get("price_source"),
                )
                liquidated.append({
                    "position_uuid": candidate["position_uuid"],
                    "user_id": candidate["user_id"],
                    "market_symbol": candidate["market_symbol"],
                    "delta_points": int(result.get("delta_points") or 0),
                    "interest_points": int(result.get("interest_points") or 0),
                    "close_fee_points": int(result.get("close_fee_points") or 0),
                    "risk": candidate["risk"],
                    "account_risk": candidate.get("account_risk"),
                    "liquidation_order": candidate.get("liquidation_order") or [],
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
                new_price = _to_price_float(manual_price_points, name="manual_price_points", minimum=0.00000001)
                old_price = float(_to_decimal(market["manual_price_points"], name="manual_price_points", minimum=0))
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
            price, price_source, price_meta = self._current_market_price_points(conn, market, with_meta=True, high_risk=True)
            self._assert_price_meta_allows_high_risk_use(
                conn,
                actor=actor,
                market_symbol=market["symbol"],
                usage="contract position open",
                price_meta=price_meta,
            )
            exposure = notional_points(quantity_units, price)
            if exposure > margin_points * leverage:
                raise ValueError("contract exposure exceeds margin and leverage")
            self._sim_delta(conn, user_id, balance_delta=-margin_points)
            position_uuid = str(uuid.uuid4())
            now = _now()
            liquidation_price = None
            if side == "long":
                liquidation_price = max(
                    0.00000001,
                    float(
                        (
                            Decimal(str(price))
                            - (Decimal(margin_points) * Decimal(ASSET_SCALE) / Decimal(quantity_units))
                        ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                    ),
                )
            else:
                liquidation_price = float(
                    (
                        Decimal(str(price))
                        + (Decimal(margin_points) * Decimal(ASSET_SCALE) / Decimal(quantity_units))
                    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                )
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
            entry_price = float(_to_decimal(position["entry_price_points"], name="entry_price_points", minimum=0.00000001))
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
            WHERE event_type IN (
                'margin_fee_retained',
                'margin_interest_retained',
                'margin_principal_lent',
                'margin_principal_repaid',
                'margin_profit_paid'
            )
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
        event_delta = int(conn.execute(
            "SELECT COALESCE(SUM(delta_points), 0) FROM trading_reserve_pool_events"
        ).fetchone()[0] or 0)
        expected_balance = event_delta
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
                "event_delta_points": event_delta,
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
            if _to_decimal(row["sell_price_points"] or 0, name="sell_price_points", minimum=0) != _to_decimal(row["price_points"] or 0, name="price_points", minimum=0):
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

    def _bot_audit_latest_map(self, conn):
        latest = {}
        rows = conn.execute(
            "SELECT * FROM trading_bot_audit_runs ORDER BY id DESC LIMIT 1000"
        ).fetchall()
        for row in rows:
            key = (str(row["bot_kind"]), str(row["bot_uuid"]))
            if key not in latest:
                latest[key] = dict(row)
        return latest

    def _bot_audit_label(self, status):
        mapping = {
            "unaudited": "未稽核",
            "green": "綠燈",
            "yellow": "黃燈",
            "red": "紅燈",
        }
        return mapping.get(str(status or ""), "未稽核")

    def _bot_audit_eligibility_reason_label(self, reason):
        mapping = {
            "has_trade": "已至少成交一筆，納入稽核",
            "aged_24h": "啟用已滿 24 小時，納入稽核",
            "awaiting_first_trade": "尚未成交，且未滿 24 小時",
            "disabled": "機器人目前停用中",
            "audit_disabled": "root 已關閉自動稽核",
        }
        return mapping.get(str(reason or ""), str(reason or ""))

    def _bot_audit_enabled_at(self, row):
        raw = row.get("enabled_at") or row.get("updated_at") or row.get("created_at") or ""
        try:
            return datetime.fromisoformat(str(raw))
        except Exception:
            return datetime.fromisoformat(_now())

    def _bot_audit_is_eligible(self, row, *, bot_kind, min_enabled_seconds):
        if not bool(row.get("enabled")):
            return False, "disabled"
        enabled_at = self._bot_audit_enabled_at(row)
        age_seconds = max(0, int((datetime.fromisoformat(_now()) - enabled_at).total_seconds()))
        has_trade = False
        if bot_kind == "trading_bot":
            has_trade = int(row.get("triggered_run_count") or 0) > 0
        else:
            has_trade = int(row.get("total_trades") or 0) > 0
        if has_trade:
            return True, "has_trade"
        if age_seconds >= int(min_enabled_seconds or TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS):
            return True, "aged_24h"
        return False, "awaiting_first_trade"

    def _bot_audit_run_findings(self, conn, row, *, bot_kind, min_enabled_seconds):
        findings = []
        state = self._state(conn)
        if bool(state.get("safe_mode")):
            findings.append({
                "severity": "blocker",
                "code": "safe_mode_active",
                "message": "交易系統目前處於 safe mode，機器人結果不可信，需先排除全域交易異常。",
                "metadata": {"reason": state.get("reason") or ""},
            })
        eligible, eligible_reason = self._bot_audit_is_eligible(
            row,
            bot_kind=bot_kind,
            min_enabled_seconds=min_enabled_seconds,
        )
        if bot_kind == "trading_bot":
            recent_runs = [
                dict(item)
                for item in conn.execute(
                    "SELECT status, error, created_at, order_uuid FROM trading_bot_runs WHERE bot_id=? ORDER BY id DESC LIMIT 10",
                    (int(row["id"]),),
                ).fetchall()
            ]
            failed_runs = [item for item in recent_runs if item.get("status") == "failed"]
            if str(row.get("last_error") or "").strip():
                findings.append({
                    "severity": "blocker" if failed_runs else "warning",
                    "code": "bot_last_error_present",
                    "message": f"最近一次 bot 執行留下錯誤：{str(row.get('last_error') or '')[:180]}",
                    "metadata": {"last_error": str(row.get("last_error") or "")[:240]},
                })
            if eligible_reason == "aged_24h" and int(row.get("triggered_run_count") or 0) <= 0:
                findings.append({
                    "severity": "warning",
                    "code": "no_trade_after_24h",
                    "message": "機器人啟用已滿 24 小時，但尚未產生任何成交，請檢查條件是否過嚴或市場是否不活躍。",
                    "metadata": {"enabled_at": row.get("enabled_at") or row.get("created_at") or ""},
                })
            if len(failed_runs) >= 3 and int(row.get("triggered_run_count") or 0) <= 0:
                findings.append({
                    "severity": "blocker",
                    "code": "repeated_failed_runs",
                    "message": "最近 bot 巡檢多次失敗且沒有成功成交，請先排除錯誤再繼續啟用。",
                    "metadata": {"failed_runs": len(failed_runs)},
                })
            elif failed_runs:
                findings.append({
                    "severity": "warning",
                    "code": "recent_failed_runs",
                    "message": f"最近 {len(failed_runs)} 次 bot 巡檢失敗，建議 root 追查執行錯誤。",
                    "metadata": {"failed_runs": len(failed_runs)},
                })
        else:
            open_orders = conn.execute(
                "SELECT COUNT(*) AS c FROM trading_grid_orders WHERE grid_bot_id=? AND status='open'",
                (int(row["id"]),),
            ).fetchone()["c"]
            orphan_open_orders = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM trading_grid_orders go
                LEFT JOIN trading_orders o ON o.order_uuid=go.trading_order_uuid
                WHERE go.grid_bot_id=? AND go.status='open' AND (
                    go.trading_order_uuid IS NULL OR o.id IS NULL OR COALESCE(o.status, '') NOT IN ('open', 'partially_filled')
                )
                """,
                (int(row["id"]),),
            ).fetchone()["c"]
            if str(row.get("last_error") or "").strip():
                findings.append({
                    "severity": "blocker",
                    "code": "grid_last_error_present",
                    "message": f"網格機器人最近一次掃描失敗：{str(row.get('last_error') or '')[:180]}",
                    "metadata": {"last_error": str(row.get("last_error") or "")[:240]},
                })
            if int(orphan_open_orders or 0) > 0:
                findings.append({
                    "severity": "blocker",
                    "code": "grid_orphan_open_orders",
                    "message": f"仍有 {int(orphan_open_orders)} 筆網格開單找不到對應 trading_orders 或狀態不同步。",
                    "metadata": {"orphan_open_orders": int(orphan_open_orders or 0)},
                })
            if bool(row.get("enabled")) and int(open_orders or 0) <= 0:
                findings.append({
                    "severity": "warning",
                    "code": "grid_has_no_open_orders",
                    "message": "網格機器人目前啟用中，但沒有任何有效開單，可能已漏掛單或需要人工檢查。",
                    "metadata": {"open_orders": int(open_orders or 0)},
                })
            if eligible_reason == "aged_24h" and int(row.get("total_trades") or 0) <= 0:
                findings.append({
                    "severity": "warning",
                    "code": "grid_no_trade_after_24h",
                    "message": "網格機器人啟用已滿 24 小時，但尚未成交，請檢查網格範圍或市場波動是否不足。",
                    "metadata": {"enabled_at": row.get("enabled_at") or row.get("created_at") or ""},
                })
        blocker_count = sum(1 for item in findings if item["severity"] == "blocker")
        warning_count = sum(1 for item in findings if item["severity"] == "warning")
        audit_status = "red" if blocker_count else ("yellow" if warning_count else "green")
        return {
            "eligible": eligible,
            "eligible_reason": eligible_reason,
            "audit_status": audit_status,
            "findings": findings,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
        }

    def _record_bot_audit_run(self, conn, row, *, bot_kind, audit_result):
        now = _now()
        findings = audit_result.get("findings") or []
        run_uuid = str(uuid.uuid4())
        cur = conn.execute(
            """
            INSERT INTO trading_bot_audit_runs (
                run_uuid, bot_kind, bot_uuid, bot_id, user_id, market_symbol,
                audit_status, eligible_reason, findings_json, finding_count,
                warning_count, blocker_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_uuid,
                bot_kind,
                str(row["bot_uuid"]),
                int(row["id"]),
                int(row["user_id"]),
                str(row["market_symbol"]),
                str(audit_result.get("audit_status") or "green"),
                str(audit_result.get("eligible_reason") or ""),
                _json_dumps(findings),
                len(findings),
                int(audit_result.get("warning_count") or 0),
                int(audit_result.get("blocker_count") or 0),
                now,
            ),
        )
        run_id = cur.lastrowid
        for finding in findings:
            conn.execute(
                """
                INSERT INTO trading_bot_audit_findings (
                    run_id, severity, code, message, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run_id),
                    str(finding.get("severity") or "warning"),
                    str(finding.get("code") or "unknown"),
                    str(finding.get("message") or "")[:500],
                    _json_dumps(finding.get("metadata") or {}),
                    now,
                ),
            )
        if audit_result.get("audit_status") in {"yellow", "red"}:
            label = self._bot_audit_label(audit_result.get("audit_status"))
            name = str(row.get("name") or row.get("market_symbol") or "bot")
            body = f"{name}（{market_display_symbol(row.get('market_symbol'))}）稽核結果 {label}。"
            link = "/trading"
            create_root_notification_if_enabled(
                conn,
                type=f"trading_bot_audit_{audit_result.get('audit_status')}",
                title="交易機器人稽核警示",
                body=body,
                link=link,
                once=True,
            )
            create_notification_if_enabled(
                conn,
                user_id=int(row["user_id"]),
                type="trading_bot_audit_warning",
                title="交易機器人需要檢查",
                body=body,
                link=link,
            )
        self._audit_event(
            conn,
            "TRADING_BOT_AUDIT_RUN",
            "trading bot audit completed",
            actor={"id": None, "username": "system", "role": "system"},
            target_user_id=int(row["user_id"]),
            market_symbol=str(row["market_symbol"]),
            severity="warning" if audit_result.get("audit_status") in {"yellow", "red"} else "info",
            metadata={
                "bot_kind": bot_kind,
                "bot_uuid": str(row["bot_uuid"]),
                "audit_status": str(audit_result.get("audit_status") or "green"),
                "finding_count": len(findings),
                "warning_count": int(audit_result.get("warning_count") or 0),
                "blocker_count": int(audit_result.get("blocker_count") or 0),
            },
        )
        return run_uuid

    def _bot_audit_candidates(self, conn, *, limit):
        user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        active_clauses = []
        if "status" in user_cols:
            active_clauses.append("COALESCE(u.status, 'active') = 'active'")
        if "deleted_at" in user_cols:
            active_clauses.append("COALESCE(u.deleted_at, '') = ''")
        active_sql = " AND ".join(active_clauses) if active_clauses else "1=1"
        bot_rows = [
            {
                **dict(row),
                "bot_kind": "trading_bot",
                "triggered_run_count": row["triggered_run_count"],
            }
            for row in conn.execute(
                f"""
                SELECT b.*, u.username, u.role,
                       (SELECT COUNT(*) FROM trading_bot_runs r WHERE r.bot_id=b.id AND r.status='triggered') AS triggered_run_count
                FROM trading_bots b
                JOIN users u ON u.id=b.user_id
                WHERE {active_sql}
                ORDER BY b.enabled DESC, COALESCE(b.enabled_at, b.created_at, b.updated_at) ASC, b.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
        grid_rows = [
            {**dict(row), "bot_kind": "grid_bot"}
            for row in conn.execute(
                f"""
                SELECT g.*, u.username, u.role
                FROM trading_grid_bots g
                JOIN users u ON u.id=g.user_id
                WHERE {active_sql}
                ORDER BY g.enabled DESC, COALESCE(g.enabled_at, g.created_at, g.updated_at) ASC, g.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
        return [*bot_rows, *grid_rows]

    def _bot_audit_dashboard_on_conn(self, conn, *, limit, settings=None):
        settings = settings or self._settings_payload(conn)
        latest_map = self._bot_audit_latest_map(conn)
        min_enabled_seconds = int(settings.get("bot_audit_min_enabled_seconds") or TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS)
        items = []
        summary = {"unaudited": 0, "green": 0, "yellow": 0, "red": 0}
        for row in self._bot_audit_candidates(conn, limit=_to_int(limit, name="limit", minimum=1, maximum=300)):
            latest = latest_map.get((row["bot_kind"], str(row["bot_uuid"])))
            eligible, eligible_reason = self._bot_audit_is_eligible(
                row,
                bot_kind=row["bot_kind"],
                min_enabled_seconds=min_enabled_seconds,
            )
            audit_status = str((latest or {}).get("audit_status") or "unaudited")
            summary[audit_status] = summary.get(audit_status, 0) + 1
            item = {
                "bot_kind": row["bot_kind"],
                "bot_uuid": str(row["bot_uuid"]),
                "name": str(row.get("name") or row.get("market_symbol") or ""),
                "market_symbol": str(row.get("market_symbol") or ""),
                "display_symbol": str(row.get("market_symbol") or "").replace("/POINTS", "/USDT"),
                "user_id": int(row["user_id"]),
                "username": str(row.get("username") or ""),
                "enabled": bool(row.get("enabled")),
                "enabled_at": row.get("enabled_at") or row.get("created_at") or "",
                "eligible": bool(eligible),
                "eligible_reason": eligible_reason,
                "eligible_reason_label": self._bot_audit_eligibility_reason_label(eligible_reason),
                "audit_status": audit_status,
                "audit_label": self._bot_audit_label(audit_status),
                "last_audited_at": (latest or {}).get("created_at") or "",
                "warning_count": int((latest or {}).get("warning_count") or 0),
                "blocker_count": int((latest or {}).get("blocker_count") or 0),
                "finding_count": int((latest or {}).get("finding_count") or 0),
                "last_error": str(row.get("last_error") or "")[:240],
            }
            if row["bot_kind"] == "trading_bot":
                item["triggered_run_count"] = int(row.get("triggered_run_count") or 0)
                item["run_count"] = int(row.get("run_count") or 0)
            else:
                item["total_trades"] = int(row.get("total_trades") or 0)
                item["open_order_count"] = int(
                    conn.execute(
                        "SELECT COUNT(*) AS c FROM trading_grid_orders WHERE grid_bot_id=? AND status='open'",
                        (int(row["id"]),),
                    ).fetchone()["c"]
                )
            items.append(item)
        recent_runs = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM trading_bot_audit_runs ORDER BY id DESC LIMIT 80"
            ).fetchall()
        ]
        return {
            "ok": True,
            "settings": {
                "bot_audit_enabled": settings.get("bot_audit_enabled", True),
                "bot_audit_interval_seconds": settings.get("bot_audit_interval_seconds", TRADING_BOT_AUDIT_INTERVAL_SECONDS),
                "bot_audit_limit": settings.get("bot_audit_limit", TRADING_BOT_AUDIT_LIMIT),
                "bot_audit_min_enabled_seconds": settings.get("bot_audit_min_enabled_seconds", TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS),
            },
            "summary": summary,
            "items": items,
            "recent_runs": recent_runs,
        }

    def run_due_bot_audits(self, *, actor=None, limit=0, force=False):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            settings = self._settings_payload(conn)
            if not settings.get("bot_audit_enabled", True) and not force:
                return {"ok": True, "enabled": False, "reason": "audit_disabled", "scanned": 0, "audited": [], "skipped": []}
            limit = _to_int(limit or settings.get("bot_audit_limit") or TRADING_BOT_AUDIT_LIMIT, name="bot_audit_limit", minimum=1, maximum=200)
            interval_seconds = int(settings.get("bot_audit_interval_seconds") or TRADING_BOT_AUDIT_INTERVAL_SECONDS)
            min_enabled_seconds = int(settings.get("bot_audit_min_enabled_seconds") or TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS)
            latest_map = self._bot_audit_latest_map(conn)
            audited = []
            skipped = []
            for row in self._bot_audit_candidates(conn, limit=limit):
                latest = latest_map.get((row["bot_kind"], str(row["bot_uuid"])))
                audit_result = self._bot_audit_run_findings(
                    conn,
                    row,
                    bot_kind=row["bot_kind"],
                    min_enabled_seconds=min_enabled_seconds,
                )
                if not audit_result["eligible"]:
                    skipped.append({
                        "bot_kind": row["bot_kind"],
                        "bot_uuid": row["bot_uuid"],
                        "reason": audit_result["eligible_reason"],
                    })
                    continue
                if not force and latest:
                    try:
                        last_dt = datetime.fromisoformat(str(latest["created_at"]))
                    except Exception:
                        last_dt = None
                    if last_dt and (datetime.fromisoformat(_now()) - last_dt).total_seconds() < interval_seconds:
                        skipped.append({
                            "bot_kind": row["bot_kind"],
                            "bot_uuid": row["bot_uuid"],
                            "reason": "interval_not_elapsed",
                        })
                        continue
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                run_uuid = self._record_bot_audit_run(
                    conn,
                    row,
                    bot_kind=row["bot_kind"],
                    audit_result=audit_result,
                )
                conn.commit()
                audited.append({
                    "run_uuid": run_uuid,
                    "bot_kind": row["bot_kind"],
                    "bot_uuid": row["bot_uuid"],
                    "audit_status": audit_result["audit_status"],
                    "finding_count": len(audit_result["findings"]),
                })
            return {
                "ok": True,
                "enabled": True,
                "scanned": len(audited) + len(skipped),
                "audited": audited,
                "skipped": skipped,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_bot_audit_dashboard(self, *, limit=100):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            settings = self._settings_payload(conn)
            return self._bot_audit_dashboard_on_conn(conn, limit=limit, settings=settings)
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
            volume_summary = {
                "totals": dict(
                    conn.execute(
                        """
                        SELECT
                            COALESCE(SUM(total_notional_points), 0) AS total_notional_points,
                            COALESCE(SUM(spot_notional_points), 0) AS spot_notional_points,
                            COALESCE(SUM(margin_notional_points), 0) AS margin_notional_points,
                            COALESCE(SUM(total_fee_points), 0) AS total_fee_points,
                            COALESCE(SUM(total_trade_count), 0) AS total_trade_count
                        FROM trading_user_volume_stats
                        """
                    ).fetchone()
                ),
                "top_users": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT s.*, u.username
                        FROM trading_user_volume_stats s
                        JOIN users u ON u.id=s.user_id
                        ORDER BY s.total_notional_points DESC, s.user_id ASC
                        LIMIT 20
                        """
                    ).fetchall()
                ],
            }
            return {
                "state": state,
                "settings": self._settings_payload(conn),
                "reserve_pool": dict(reserve),
                "funding_pool": self._funding_pool_payload(conn),
                "volume_summary": volume_summary,
                "markets": markets,
                "reserve_events": reserve_events,
                "audit_events": audit_events,
                "bot_audit_dashboard": self._bot_audit_dashboard_on_conn(conn, limit=80),
                "verification": self._verify_state_on_conn(conn, enter_safe_mode=False),
            }
        finally:
            conn.close()
