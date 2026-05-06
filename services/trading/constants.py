"""Shared trading-domain constants."""

from decimal import Decimal


ASSET_SCALE = 100_000_000
POINT_MICRO_SCALE = 1_000_000
DEFAULT_SPOT_FEE_RATE_PERCENT = 0.10
DEFAULT_GRID_FEE_DISCOUNT_PERCENT = 25.0
GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT = Decimal("0.10")
APR_DAYS_PER_YEAR = Decimal("365")

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
DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT = 3
REFERENCE_PRICE_CAPABLE_PROVIDERS = {
    "binance_public_api",
    "okx_public_api",
    "coinbase_exchange",
    "kraken_public_api",
    "gemini_public_api",
    "bitstamp_public_api",
}
TICKER_CAPABLE_PROVIDERS = set(REFERENCE_PRICE_CAPABLE_PROVIDERS) | {"coingecko_simple_price"}
DEPTH_CAPABLE_PROVIDERS = set(WEIGHTED_PRICE_PROVIDERS)

TRADING_BOT_TRIGGER_TYPES = {"always", "price_above", "price_below"}
TRADING_BOT_TYPES = {"conditional", "dca"}
TRADING_BOT_AUDIT_INTERVAL_SECONDS = 300
TRADING_BOT_AUDIT_LIMIT = 50
TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS = 86_400
WORKFLOW_CONDITION_TYPES = {
    "always",
    "price_above",
    "price_below",
    "rsi_above",
    "rsi_below",
    "kd_above",
    "kd_below",
    "ma_position",
    "bb_position",
    "has_position",
    "change_percent_up",
    "change_percent_down",
    "stop_loss_percent",
    "take_profit_percent",
}
WORKFLOW_ACTION_TYPES = {"buy_percent", "buy_amount", "sell_percent", "close_all", "hold"}
WORKFLOW_NODE_TYPES = {"start", "condition", "logic", "action", "control"}
WORKFLOW_PORTS = {"in", "out", "true", "false", "then", "wait"}
UNLIMITED_BOT_MAX_RUNS = 2_147_483_647
