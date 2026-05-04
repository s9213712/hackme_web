from services.trading_markets import (
    get_market_definition,
    list_live_price_markets,
    list_seed_markets,
    market_display_symbol,
    market_provider_id,
    market_supports_btc_trade,
    market_supports_reference_price,
    normalize_market_symbol,
)


def test_trading_market_catalog_normalizes_internal_and_display_symbols():
    assert normalize_market_symbol("btc/points") == "BTC/POINTS"
    assert normalize_market_symbol("BTC/USDT") == "BTC/POINTS"
    assert normalize_market_symbol("eth/usdt") == "ETH/POINTS"

    btc = get_market_definition("BTC/USDT")
    eth = get_market_definition("ETH/POINTS")

    assert btc["symbol"] == "BTC/POINTS"
    assert btc["display_symbol"] == "BTC/USDT"
    assert eth["symbol"] == "ETH/POINTS"
    assert eth["display_symbol"] == "ETH/USDT"
    assert market_display_symbol("BTC/POINTS") == "BTC/USDT"
    assert market_display_symbol("ETH/USDT") == "ETH/USDT"


def test_trading_market_catalog_exposes_provider_ids_and_feature_flags():
    assert list_live_price_markets() == ["BTC/POINTS", "ETH/POINTS"]
    assert [row["symbol"] for row in list_seed_markets()] == ["BTC/POINTS", "ETH/POINTS"]

    assert market_provider_id("BTC/POINTS", "binance_public_api") == "BTCUSDT"
    assert market_provider_id("ETH/USDT", "coinbase_exchange") == "ETH-USD"
    assert market_provider_id("ETH/POINTS", "coingecko_simple_price") == "ethereum"

    assert market_supports_reference_price("BTC/USDT") is True
    assert market_supports_reference_price("ETH/POINTS") is True
    assert market_supports_btc_trade("BTC/USDT") is True
    assert market_supports_btc_trade("ETH/USDT") is False
