"""Pure trading settings parsing helpers.

The trading engine still owns database access and update orchestration.
This module centralizes byte-for-byte-equivalent normalization so the
engine no longer embeds long stretches of repeated parsing code.
"""

from services.trading.validators import _apr_percent_from_daily, _daily_percent_from_apr, _to_float, _to_int


TRUE_VALUES = {"true", "1", "yes"}


TRADING_ROOT_BOOL_SETTING_KEYS = {
    "enabled": "trading.enabled",
    "futures_enabled": "trading.futures_enabled",
    "pvp_matching_enabled": "trading.pvp_matching_enabled",
    "borrowing_enabled": "trading.borrowing_enabled",
    "margin_liquidation_enabled": "trading.margin_liquidation_enabled",
    "shadow_funding_publish_enabled": "trading.shadow_funding_publish_enabled",
    "bot_auto_scan_enabled": "trading.bot_auto_scan_enabled",
    "bot_audit_enabled": "trading.bot_audit_enabled",
    "btc_trade_enabled": "trading.btc_trade_enabled",
    "price_stream_ws_enabled": "trading.price_stream_ws_enabled",
    "price_degrade_pause_market_orders": "trading.price_degrade_pause_market_orders",
    "price_degrade_pause_bots": "trading.price_degrade_pause_bots",
    "price_degrade_pause_borrowing": "trading.price_degrade_pause_borrowing",
    "simulated_slippage_enabled": "trading.simulated_slippage_enabled",
}


def raw_bool_setting(raw, storage_key, default=False):
    fallback = "true" if default else "false"
    return str(raw.get(storage_key, fallback)).lower() in TRUE_VALUES


def raw_float_setting(raw, storage_key, default_value, *, name, minimum=0.0, maximum=10**12, legacy_storage_key=None):
    raw_value = raw.get(storage_key)
    if raw_value in (None, "") and legacy_storage_key:
        raw_value = raw.get(legacy_storage_key, str(default_value))
    elif raw_value in (None, ""):
        raw_value = str(default_value)
    return _to_float(raw_value, name=name, minimum=minimum, maximum=maximum)


def raw_int_setting(raw, storage_key, default_value, *, name, minimum=0, maximum=10**12):
    return _to_int(raw.get(storage_key, str(default_value)), name=name, minimum=minimum, maximum=maximum)


def raw_choice_setting(raw, storage_key, default_value, *, allowed):
    value = raw.get(storage_key, default_value)
    return value if value in allowed else default_value


def bool_input_text(settings, input_key):
    return "true" if bool(settings.get(input_key)) else "false"


def float_input_text(settings, input_key, *, name=None, minimum=0.0, maximum=10**12):
    return str(
        _to_float(
            settings.get(input_key),
            name=name or input_key,
            minimum=minimum,
            maximum=maximum,
        )
    )


def int_input_text(settings, input_key, *, name=None, minimum=0, maximum=10**12):
    return str(
        _to_int(
            settings.get(input_key),
            name=name or input_key,
            minimum=minimum,
            maximum=maximum,
        )
    )


def text_input_value(settings, input_key, *, default="", max_length=500):
    value = str(settings.get(input_key) or default).strip()
    if len(value) > max_length:
        raise ValueError(f"{input_key} too long")
    return value


def choice_input_value(settings, input_key, *, allowed, error_message):
    value = str(settings.get(input_key) or "").strip()
    if value not in allowed:
        raise ValueError(error_message)
    return value


def apr_pair_from_raw(raw, *, btc_eth_default, usdt_points_default):
    borrow_apr_btc_eth = raw_float_setting(
        raw,
        "trading.borrow_apr_btc_eth_percent",
        btc_eth_default,
        name="borrow_apr_btc_eth_percent",
        minimum=0,
        maximum=100000,
    )
    borrow_apr_usdt_points = raw_float_setting(
        raw,
        "trading.borrow_apr_usdt_points_percent",
        usdt_points_default,
        name="borrow_apr_usdt_points_percent",
        minimum=0,
        maximum=100000,
    )
    return borrow_apr_btc_eth, borrow_apr_usdt_points


def interval_pair_from_raw(raw, *, interval_default, minimum_default):
    return (
        raw_int_setting(
            raw,
            "trading.borrow_interest_interval_hours",
            interval_default,
            name="borrow_interest_interval_hours",
            minimum=1,
            maximum=168,
        ),
        raw_int_setting(
            raw,
            "trading.borrow_interest_minimum_hours",
            minimum_default,
            name="borrow_interest_minimum_hours",
            minimum=1,
            maximum=168,
        ),
    )


def write_apr_from_daily(settings, *, now, actor_id):
    legacy_daily = _to_float(
        settings.get("borrow_interest_percent_daily"),
        name="borrow_interest_percent_daily",
        minimum=0,
        maximum=100,
    )
    return {
        "trading.borrow_apr_usdt_points_percent": str(_apr_percent_from_daily(legacy_daily)),
        "trading.borrow_interest_percent_daily": str(legacy_daily),
        "__meta__": {"now": now, "actor_id": actor_id},
    }


def daily_from_apr(apr_percent):
    return _daily_percent_from_apr(apr_percent)
