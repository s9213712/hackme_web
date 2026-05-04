from copy import deepcopy


TRADING_MARKET_CATALOG = (
    {
        "symbol": "BTC/POINTS",
        "base_asset": "BTC",
        "quote_currency": "POINTS",
        "display_quote_currency": "USDT",
        "default_manual_price_points": 100000,
        "sort_order": 10,
        "live_price_enabled": True,
        "reference_price_enabled": True,
        "btc_trade_enabled": True,
        "provider_ids": {
            "binance_public_api": "BTCUSDT",
            "okx_public_api": "BTC-USDT",
            "coinbase_exchange": "BTC-USD",
            "kraken_public_api": "XBTUSD",
            "gemini_public_api": "btcusd",
            "bitstamp_public_api": "btcusd",
            "coingecko_simple_price": "bitcoin",
        },
    },
    {
        "symbol": "ETH/POINTS",
        "base_asset": "ETH",
        "quote_currency": "POINTS",
        "display_quote_currency": "USDT",
        "default_manual_price_points": 5000,
        "sort_order": 20,
        "live_price_enabled": True,
        "reference_price_enabled": True,
        "btc_trade_enabled": False,
        "provider_ids": {
            "binance_public_api": "ETHUSDT",
            "okx_public_api": "ETH-USDT",
            "coinbase_exchange": "ETH-USD",
            "kraken_public_api": "ETHUSD",
            "gemini_public_api": "ethusd",
            "bitstamp_public_api": "ethusd",
            "coingecko_simple_price": "ethereum",
        },
    },
)


def _normalize_symbol(value):
    return str(value or "").strip().upper()


def _display_symbol(entry):
    quote = str(entry.get("display_quote_currency") or entry.get("quote_currency") or "").strip().upper()
    return f"{entry['base_asset']}/{quote}" if quote else str(entry["symbol"])


_CATALOG_BY_SYMBOL = {}
_ALIAS_TO_SYMBOL = {}
for item in TRADING_MARKET_CATALOG:
    symbol = _normalize_symbol(item.get("symbol"))
    if not symbol:
        continue
    normalized = {
        **item,
        "symbol": symbol,
        "base_asset": str(item.get("base_asset") or "").strip().upper(),
        "quote_currency": str(item.get("quote_currency") or "").strip().upper(),
        "display_quote_currency": str(item.get("display_quote_currency") or item.get("quote_currency") or "").strip().upper(),
        "display_symbol": _display_symbol(item),
        "provider_ids": dict(item.get("provider_ids") or {}),
    }
    _CATALOG_BY_SYMBOL[symbol] = normalized
    _ALIAS_TO_SYMBOL[symbol] = symbol
    _ALIAS_TO_SYMBOL[normalized["display_symbol"]] = symbol


def normalize_market_symbol(value):
    symbol = _normalize_symbol(value)
    return _ALIAS_TO_SYMBOL.get(symbol, symbol)


def get_market_definition(value):
    symbol = normalize_market_symbol(value)
    item = _CATALOG_BY_SYMBOL.get(symbol)
    return deepcopy(item) if item else None


def list_market_definitions():
    rows = [deepcopy(item) for item in _CATALOG_BY_SYMBOL.values()]
    return sorted(rows, key=lambda item: (int(item.get("sort_order") or 9999), item["symbol"]))


def list_seed_markets():
    return [item for item in list_market_definitions() if item.get("quote_currency") == "POINTS"]


def list_live_price_markets():
    return [item["symbol"] for item in list_market_definitions() if item.get("live_price_enabled")]


def list_reference_price_markets():
    return [item["symbol"] for item in list_market_definitions() if item.get("reference_price_enabled")]


def market_display_symbol(symbol, quote_currency=None):
    item = get_market_definition(symbol)
    if item:
        return item["display_symbol"]
    normalized = normalize_market_symbol(symbol)
    quote = str(quote_currency or "").strip().upper()
    if normalized.endswith("/POINTS"):
        return normalized[:-7] + "/USDT"
    if quote == "POINTS" and "/" in normalized:
        base, _sep, _tail = normalized.partition("/")
        return f"{base}/USDT"
    return normalized


def market_provider_id(symbol, provider):
    item = get_market_definition(symbol)
    if not item:
        return ""
    return str((item.get("provider_ids") or {}).get(provider) or "")


def market_supports_live_price(symbol):
    item = get_market_definition(symbol)
    return bool(item and item.get("live_price_enabled"))


def market_supports_reference_price(symbol):
    item = get_market_definition(symbol)
    return bool(item and item.get("reference_price_enabled"))


def market_supports_btc_trade(symbol):
    item = get_market_definition(symbol)
    return bool(item and item.get("btc_trade_enabled"))


def market_sort_key(symbol):
    item = get_market_definition(symbol)
    if item:
        return (int(item.get("sort_order") or 9999), item["symbol"])
    return (9999, normalize_market_symbol(symbol))
