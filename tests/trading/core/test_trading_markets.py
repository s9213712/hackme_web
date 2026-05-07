from services.trading.catalog import (
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
    assert normalize_market_symbol("xrp/usdt") == "XRP/POINTS"
    assert normalize_market_symbol("BNB/USDT") == "BNB/POINTS"
    assert normalize_market_symbol("paxg/usdt") == "PAXG/POINTS"

    btc = get_market_definition("BTC/USDT")
    eth = get_market_definition("ETH/POINTS")
    xrp = get_market_definition("XRP/USDT")
    bnb = get_market_definition("BNB/POINTS")
    paxg = get_market_definition("PAXG/USDT")

    assert btc["symbol"] == "BTC/POINTS"
    assert btc["display_symbol"] == "BTC/USDT"
    assert eth["symbol"] == "ETH/POINTS"
    assert eth["display_symbol"] == "ETH/USDT"
    assert xrp["symbol"] == "XRP/POINTS"
    assert xrp["display_symbol"] == "XRP/USDT"
    assert bnb["symbol"] == "BNB/POINTS"
    assert bnb["display_symbol"] == "BNB/USDT"
    assert paxg["symbol"] == "PAXG/POINTS"
    assert paxg["display_symbol"] == "PAXG/USDT"
    assert market_display_symbol("BTC/POINTS") == "BTC/USDT"
    assert market_display_symbol("ETH/USDT") == "ETH/USDT"
    assert market_display_symbol("XRP/POINTS") == "XRP/USDT"
    assert market_display_symbol("BNB/POINTS") == "BNB/USDT"
    assert market_display_symbol("PAXG/USDT") == "PAXG/USDT"


def test_trading_market_catalog_exposes_provider_ids_and_feature_flags():
    assert list_live_price_markets() == ["BTC/POINTS", "ETH/POINTS", "XRP/POINTS", "BNB/POINTS", "PAXG/POINTS"]
    assert [row["symbol"] for row in list_seed_markets()] == ["BTC/POINTS", "ETH/POINTS", "XRP/POINTS", "BNB/POINTS", "PAXG/POINTS"]

    assert market_provider_id("BTC/POINTS", "binance_public_api") == "BTCUSDT"
    assert market_provider_id("ETH/USDT", "coinbase_exchange") == "ETH-USD"
    assert market_provider_id("XRP/USDT", "kraken_public_api") == "XRPUSD"
    assert market_provider_id("BNB/POINTS", "binance_public_api") == "BNBUSDT"
    assert market_provider_id("PAXG/USDT", "coingecko_simple_price") == "pax-gold"
    assert market_provider_id("ETH/POINTS", "coingecko_simple_price") == "ethereum"

    assert market_supports_reference_price("BTC/USDT") is True
    assert market_supports_reference_price("ETH/POINTS") is True
    assert market_supports_reference_price("XRP/USDT") is True
    assert market_supports_reference_price("BNB/USDT") is True
    assert market_supports_reference_price("PAXG/POINTS") is True
    assert market_supports_btc_trade("BTC/USDT") is True
    assert market_supports_btc_trade("ETH/USDT") is False
    assert market_supports_btc_trade("XRP/USDT") is False
