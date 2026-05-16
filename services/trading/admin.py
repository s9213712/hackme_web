"""Trading admin/settings helpers extracted from the engine facade."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime

from services.trading.accounting.funding_pool import funding_pool_payload
from services.trading.constants import (
    DEFAULT_GRID_FEE_DISCOUNT_PERCENT,
    DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT,
    DEFAULT_PRICE_FUSION_TRADE_MIN_PROVIDER_COUNT,
    DEFAULT_TRADING_PRICE_SOURCE,
    PRICE_PROVIDER_LABELS,
    WEIGHTED_PRICE_PROVIDERS,
)
from services.trading.settings_schema import (
    TRADING_ROOT_BOOL_SETTING_KEYS,
    apr_pair_from_raw,
    bool_input_text,
    choice_input_value,
    daily_from_apr,
    float_input_text,
    int_input_text,
    interval_pair_from_raw,
    raw_bool_setting,
    raw_choice_setting,
    raw_float_setting,
    raw_int_setting,
    text_input_value,
    write_apr_from_daily,
)
from services.trading.validators import _to_decimal, _to_float, _to_int, _to_price_float


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


def _normalize_price_fusion_manual_weights(service, raw):
    out = {}
    source = raw if isinstance(raw, dict) else {}
    for provider in WEIGHTED_PRICE_PROVIDERS:
        value = source.get(provider, service.DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS.get(provider, 1.0))
        try:
            number = float(value)
        except Exception:
            number = service.DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS.get(provider, 1.0)
        if not math.isfinite(number):
            number = service.DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS.get(provider, 1.0)
        out[provider] = max(0.0, min(number, 1000.0))
    return out


def settings_payload(service, conn):
    rows = conn.execute("SELECT key, value, updated_at, updated_by FROM trading_settings ORDER BY key").fetchall()
    raw = {row["key"]: row["value"] for row in rows}
    borrow_apr_btc_eth, borrow_apr_usdt_points = apr_pair_from_raw(
        raw,
        btc_eth_default=service.DEFAULT_BORROW_APR_BTC_ETH_PERCENT,
        usdt_points_default=service.DEFAULT_BORROW_APR_USDT_POINTS_PERCENT,
    )
    borrow_interest_interval_hours, borrow_interest_minimum_hours = interval_pair_from_raw(
        raw,
        interval_default=service.DEFAULT_BORROW_INTEREST_INTERVAL_HOURS,
        minimum_default=service.DEFAULT_BORROW_INTEREST_MINIMUM_HOURS,
    )
    return {
        "enabled": raw_bool_setting(raw, "trading.enabled", default=True),
        "futures_enabled": raw_bool_setting(raw, "trading.futures_enabled", default=False),
        "pvp_matching_enabled": raw_bool_setting(raw, "trading.pvp_matching_enabled", default=False),
        "borrowing_enabled": raw_bool_setting(raw, "trading.borrowing_enabled", default=True),
        "borrow_apr_btc_eth_percent": borrow_apr_btc_eth,
        "borrow_apr_usdt_points_percent": borrow_apr_usdt_points,
        "borrow_interest_percent_daily": daily_from_apr(borrow_apr_usdt_points),
        "borrow_interest_pool_pressure_multiplier": raw_float_setting(
            raw,
            "trading.borrow_interest_pool_pressure_multiplier",
            service.TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER,
            name="borrow_interest_pool_pressure_multiplier",
            minimum=0,
            maximum=100,
        ),
        "borrow_interest_interval_hours": borrow_interest_interval_hours,
        "borrow_interest_minimum_hours": borrow_interest_minimum_hours,
        "margin_long_financing_percent": raw_float_setting(
            raw,
            "trading.margin_long_financing_percent",
            service.MARGIN_LONG_FINANCING_RATE_PERCENT,
            name="margin_long_financing_percent",
            minimum=0,
            maximum=100,
        ),
        "short_collateral_percent": raw_float_setting(
            raw,
            "trading.short_collateral_percent",
            service.SHORT_COLLATERAL_RATE_PERCENT,
            name="short_collateral_percent",
            minimum=0,
            maximum=100,
        ),
        "margin_liquidation_enabled": raw_bool_setting(raw, "trading.margin_liquidation_enabled", default=True),
        "shadow_funding_publish_enabled": raw_bool_setting(raw, "trading.shadow_funding_publish_enabled", default=False),
        "margin_maintenance_percent": raw_float_setting(raw, "trading.margin_maintenance_percent", "15", name="margin_maintenance_percent", minimum=0, maximum=100),
        "grid_fee_discount_percent": raw_float_setting(raw, "trading.grid_fee_discount_percent", DEFAULT_GRID_FEE_DISCOUNT_PERCENT, name="grid_fee_discount_percent", minimum=0, maximum=100),
        "max_price_staleness_seconds": raw_int_setting(raw, "trading.max_price_staleness_seconds", "900", name="max_price_staleness_seconds", minimum=0, maximum=86400),
        "price_source": raw.get("trading.price_source", DEFAULT_TRADING_PRICE_SOURCE),
        "price_fusion_mode": raw_choice_setting(raw, "trading.price_fusion_mode", "auto_depth", allowed=service.PRICE_FUSION_MODES),
        "price_fusion_manual_weights": _normalize_price_fusion_manual_weights(
            service,
            _json_loads(raw.get("trading.price_fusion_manual_weights_json"), service.DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS),
        ),
        "price_fusion_provider_labels": dict(PRICE_PROVIDER_LABELS),
        "price_fusion_providers": list(WEIGHTED_PRICE_PROVIDERS),
        "price_fusion_live_markets": service._list_live_price_market_symbols(conn),
        "price_fusion_depth_band_percent": raw_float_setting(raw, "trading.price_fusion_depth_band_percent", service.DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, name="price_fusion_depth_band_percent", minimum=0.1, maximum=10),
        "price_fusion_depth_levels": raw_int_setting(raw, "trading.price_fusion_depth_levels", service.DEFAULT_PRICE_FUSION_DEPTH_LEVELS, name="price_fusion_depth_levels", minimum=10, maximum=service.MAX_PRICE_FUSION_DEPTH_LEVELS),
        "price_fusion_min_orderbook_coverage_percent": raw_float_setting(raw, "trading.price_fusion_min_orderbook_coverage_percent", service.DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT, name="price_fusion_min_orderbook_coverage_percent", minimum=0.1, maximum=10),
        "price_fusion_max_single_provider_weight_percent": raw_float_setting(raw, "trading.price_fusion_max_single_provider_weight_percent", service.DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT, name="price_fusion_max_single_provider_weight_percent", minimum=0, maximum=100),
        "price_fusion_max_provider_age_seconds": service.DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS,
        "price_fusion_max_provider_latency_ms": service.DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS,
        "price_fusion_max_midpoint_deviation_percent": service.DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT,
        "price_fusion_min_side_balance_ratio_percent": round(service.DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2),
        "price_fusion_min_provider_count": raw_int_setting(raw, "trading.price_fusion_min_provider_count", DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT, name="price_fusion_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS)),
        "price_fusion_trade_min_provider_count": raw_int_setting(
            raw,
            "trading.price_fusion_trade_min_provider_count",
            DEFAULT_PRICE_FUSION_TRADE_MIN_PROVIDER_COUNT,
            name="price_fusion_trade_min_provider_count",
            minimum=1,
            maximum=len(WEIGHTED_PRICE_PROVIDERS),
        ),
        "warning_language": raw_choice_setting(
            raw,
            "trading.warning_language",
            "zh-TW",
            allowed={"zh-TW", "en"},
        ),
        "price_degrade_pause_market_orders": raw_bool_setting(raw, "trading.price_degrade_pause_market_orders", default=False),
        "price_degrade_pause_bots": raw_bool_setting(raw, "trading.price_degrade_pause_bots", default=False),
        "price_degrade_pause_borrowing": raw_bool_setting(raw, "trading.price_degrade_pause_borrowing", default=False),
        "allow_unready_markets": raw_bool_setting(raw, "trading.allow_unready_markets", default=True),
        "disable_price_confidence_gates": raw_bool_setting(raw, "trading.disable_price_confidence_gates", default=True),
        "dev_allow_conservative_market_orders": raw_bool_setting(raw, "trading.dev_allow_conservative_market_orders", default=False),
        "dev_allow_unready_markets": raw_bool_setting(raw, "trading.dev_allow_unready_markets", default=False),
        "dev_disable_price_confidence_gates": raw_bool_setting(raw, "trading.dev_disable_price_confidence_gates", default=False),
        "simulated_slippage_enabled": raw_bool_setting(raw, "trading.simulated_slippage_enabled", default=False),
        "simulated_slippage_base_basis_points": raw_float_setting(
            raw,
            "trading.simulated_slippage_base_basis_points",
            0,
            name="simulated_slippage_base_basis_points",
            minimum=0,
            maximum=10000,
            legacy_storage_key="trading.simulated_slippage_base_" + "bp" + "s",
        ),
        "simulated_slippage_size_basis_points_per_10k_notional": raw_float_setting(
            raw,
            "trading.simulated_slippage_size_basis_points_per_10k_notional",
            0,
            name="simulated_slippage_size_basis_points_per_10k_notional",
            minimum=0,
            maximum=10000,
            legacy_storage_key="trading.simulated_slippage_size_" + "bp" + "s_per_10k_notional",
        ),
        "simulated_slippage_max_basis_points": raw_float_setting(
            raw,
            "trading.simulated_slippage_max_basis_points",
            0,
            name="simulated_slippage_max_basis_points",
            minimum=0,
            maximum=10000,
            legacy_storage_key="trading.simulated_slippage_max_" + "bp" + "s",
        ),
        "price_stream_ws_enabled": raw_bool_setting(raw, "trading.price_stream_ws_enabled", default=True),
        "price_stream_ws_stale_seconds": raw_int_setting(raw, "trading.price_stream_ws_stale_seconds", service.DEFAULT_PRICE_STREAM_WS_STALE_SECONDS, name="price_stream_ws_stale_seconds", minimum=1, maximum=120),
        "qa_live_price_provider_enabled": raw_bool_setting(
            raw,
            "trading.qa_live_price_provider_enabled",
            default=False,
        ),
        "btc_trade_enabled": raw_bool_setting(raw, "trading.btc_trade_enabled", default=False),
        "btc_trade_project_dir": raw.get("trading.btc_trade_project_dir", ""),
        "btc_trade_repo_url": raw.get("trading.btc_trade_repo_url", "https://github.com/s9213712/BTC_trade.git"),
        "btc_trade_branch": raw.get("trading.btc_trade_branch", "strategy/v15b-plus"),
        "bot_auto_scan_enabled": raw_bool_setting(raw, "trading.bot_auto_scan_enabled", default=True),
        "background_worker_dev_ready_enabled": raw_bool_setting(
            raw,
            "trading.background_worker_dev_ready_enabled",
            default=False,
        ),
        "bot_auto_scan_interval_seconds": raw_int_setting(raw, "trading.bot_auto_scan_interval_seconds", "30", name="bot_auto_scan_interval_seconds", minimum=10, maximum=3600),
        "bot_auto_scan_limit": raw_int_setting(raw, "trading.bot_auto_scan_limit", "50", name="bot_auto_scan_limit", minimum=1, maximum=200),
        "bot_competition_enabled": raw_bool_setting(raw, "trading.bot_competition_enabled", default=True),
        "bot_competition_weekly_reward_points": raw_int_setting(raw, "trading.bot_competition_weekly_reward_points", "100", name="bot_competition_weekly_reward_points", minimum=0, maximum=1_000_000),
        "bot_audit_enabled": raw_bool_setting(raw, "trading.bot_audit_enabled", default=True),
        "bot_audit_interval_seconds": raw_int_setting(raw, "trading.bot_audit_interval_seconds", service.TRADING_BOT_AUDIT_INTERVAL_SECONDS, name="bot_audit_interval_seconds", minimum=60, maximum=86400),
        "bot_audit_limit": raw_int_setting(raw, "trading.bot_audit_limit", service.TRADING_BOT_AUDIT_LIMIT, name="bot_audit_limit", minimum=1, maximum=200),
        "bot_audit_min_enabled_seconds": raw_int_setting(raw, "trading.bot_audit_min_enabled_seconds", service.TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS, name="bot_audit_min_enabled_seconds", minimum=3600, maximum=604800),
        "backtest_max_candles": raw_int_setting(raw, "trading.backtest_max_candles", str(service.MAX_BACKTEST_CANDLES), name="backtest_max_candles", minimum=service.BACKTEST_MAX_CANDLES_FLOOR, maximum=service.BACKTEST_MAX_CANDLES_CEILING),
        "backtest_measured_capacity": raw_int_setting(raw, "trading.backtest_measured_capacity", "0", name="backtest_measured_capacity", minimum=0, maximum=service.BACKTEST_MAX_CANDLES_CEILING),
        "backtest_measured_capacity_max": raw_int_setting(raw, "trading.backtest_measured_capacity_max", "0", name="backtest_measured_capacity_max", minimum=0, maximum=service.BACKTEST_MAX_CANDLES_CEILING),
        "backtest_capacity_measured_at": raw.get("trading.backtest_capacity_measured_at", ""),
        "backtest_capacity_bottleneck": raw.get("trading.backtest_capacity_bottleneck", ""),
        "backtest_capacity_fastest": raw.get("trading.backtest_capacity_fastest", ""),
        "backtest_capacity_time_budget_seconds": raw_int_setting(raw, "trading.backtest_capacity_time_budget_seconds", str(service.BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS), name="backtest_capacity_time_budget_seconds", minimum=service.BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS, maximum=service.BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS),
        "raw": raw,
    }


def get_root_settings(service):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        return {
            "settings": service._settings_payload(conn),
            "markets": [
                service._market_payload(row)
                for row in conn.execute("SELECT * FROM trading_markets ORDER BY sort_order ASC, symbol ASC").fetchall()
            ],
            "reserve_pool": dict(service._reserve(conn)),
            "funding_pool": service._funding_pool_payload(conn),
        }
    finally:
        conn.close()


def get_max_backtest_candles(service, conn=None):
    close_conn = False
    if conn is None:
        conn = service.get_db()
        close_conn = True
    try:
        try:
            service.ensure_schema(conn)
            row = conn.execute("SELECT value FROM trading_settings WHERE key = ?", ("trading.backtest_max_candles",)).fetchone()
        except Exception:
            return service.MAX_BACKTEST_CANDLES
        if not row:
            return service.MAX_BACKTEST_CANDLES
        try:
            value = int(str(row["value"]).strip())
        except Exception:
            return service.MAX_BACKTEST_CANDLES
        if value < service.BACKTEST_MAX_CANDLES_FLOOR:
            return service.MAX_BACKTEST_CANDLES
        if value > service.BACKTEST_MAX_CANDLES_CEILING:
            return service.BACKTEST_MAX_CANDLES_CEILING
        return value
    finally:
        if close_conn:
            conn.close()


def get_backtest_capacity_time_budget_seconds(service, conn=None):
    close_conn = False
    if conn is None:
        conn = service.get_db()
        close_conn = True
    try:
        try:
            service.ensure_schema(conn)
            row = conn.execute(
                "SELECT value FROM trading_settings WHERE key = ?",
                ("trading.backtest_capacity_time_budget_seconds",),
            ).fetchone()
        except Exception:
            return service.BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
        if not row:
            return service.BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
        try:
            value = int(str(row["value"]).strip())
        except Exception:
            return service.BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
        if value < service.BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS:
            return service.BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS
        if value > service.BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS:
            return service.BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS
        return value
    finally:
        if close_conn:
            conn.close()


def get_backtest_capacity_measurement(service, conn=None):
    close_conn = False
    if conn is None:
        conn = service.get_db()
        close_conn = True
    try:
        try:
            service.ensure_schema(conn)
            rows = conn.execute(
                "SELECT key, value FROM trading_settings WHERE key IN (?, ?, ?, ?, ?)",
                (
                    "trading.backtest_measured_capacity",
                    "trading.backtest_measured_capacity_max",
                    "trading.backtest_capacity_measured_at",
                    "trading.backtest_capacity_bottleneck",
                    "trading.backtest_capacity_fastest",
                ),
            ).fetchall()
        except Exception:
            return {"measured_capacity": 0, "measured_capacity_max": 0, "measured_at": "", "bottleneck_strategy": "", "fastest_strategy": ""}
        raw = {row["key"]: row["value"] for row in rows}
        try:
            measured_capacity = int(str(raw.get("trading.backtest_measured_capacity", "0")).strip() or 0)
        except Exception:
            measured_capacity = 0
        try:
            measured_capacity_max = int(str(raw.get("trading.backtest_measured_capacity_max", "0")).strip() or 0)
        except Exception:
            measured_capacity_max = 0
        return {
            "measured_capacity": max(0, measured_capacity),
            "measured_capacity_max": max(0, measured_capacity_max),
            "measured_at": raw.get("trading.backtest_capacity_measured_at", "") or "",
            "bottleneck_strategy": raw.get("trading.backtest_capacity_bottleneck", "") or "",
            "fastest_strategy": raw.get("trading.backtest_capacity_fastest", "") or "",
        }
    finally:
        if close_conn:
            conn.close()


def record_backtest_capacity_measurement(
    service,
    *,
    measured_capacity_min,
    measured_capacity_max,
    measured_at,
    bottleneck_strategy="",
    fastest_strategy="",
    actor_id="system",
    seed_default_cap=True,
):
    try:
        measured_capacity_min = int(measured_capacity_min)
    except Exception:
        measured_capacity_min = 0
    try:
        measured_capacity_max = int(measured_capacity_max)
    except Exception:
        measured_capacity_max = 0
    measured_capacity_min = max(0, min(service.BACKTEST_MAX_CANDLES_CEILING, measured_capacity_min))
    measured_capacity_max = max(measured_capacity_min, min(service.BACKTEST_MAX_CANDLES_CEILING, measured_capacity_max))
    if not measured_at:
        measured_at = _now()
    bottleneck_strategy = str(bottleneck_strategy or "")[:100]
    fastest_strategy = str(fastest_strategy or "")[:100]
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.backtest_measured_capacity", str(measured_capacity_min), measured_at, actor_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.backtest_measured_capacity_max", str(measured_capacity_max), measured_at, actor_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.backtest_capacity_measured_at", measured_at, measured_at, actor_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.backtest_capacity_bottleneck", bottleneck_strategy, measured_at, actor_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.backtest_capacity_fastest", fastest_strategy, measured_at, actor_id),
        )
        if seed_default_cap and measured_capacity_min >= service.BACKTEST_MAX_CANDLES_FLOOR:
            row = conn.execute(
                "SELECT 1 FROM trading_settings WHERE key = ?",
                ("trading.backtest_max_candles",),
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.backtest_max_candles", str(measured_capacity_min), measured_at, actor_id),
                )
        conn.commit()
    finally:
        conn.close()


def update_root_settings(service, *, actor, settings=None, markets=None):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        now = _now()
        settings = settings if isinstance(settings, dict) else {}
        market_updates = markets if isinstance(markets, list) else []
        setting_changes = {}
        for input_key, storage_key in TRADING_ROOT_BOOL_SETTING_KEYS.items():
            if input_key in settings:
                value = bool_input_text(settings, input_key)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (storage_key, value, now, service._actor_id(actor)),
                )
                setting_changes[storage_key] = value
        for input_key, storage_key, default_value in (
            ("borrow_apr_btc_eth_percent", "trading.borrow_apr_btc_eth_percent", service.DEFAULT_BORROW_APR_BTC_ETH_PERCENT),
            ("borrow_apr_usdt_points_percent", "trading.borrow_apr_usdt_points_percent", service.DEFAULT_BORROW_APR_USDT_POINTS_PERCENT),
        ):
            if input_key in settings:
                numeric = _to_float(settings.get(input_key), name=input_key, minimum=0, maximum=100)
                value = float_input_text(settings, input_key, minimum=0, maximum=100)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (storage_key, value, now, service._actor_id(actor)),
                )
                setting_changes[storage_key] = value
                if input_key == "borrow_apr_usdt_points_percent":
                    legacy_daily = str(daily_from_apr(numeric))
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        ("trading.borrow_interest_percent_daily", legacy_daily, now, service._actor_id(actor)),
                    )
                    setting_changes["trading.borrow_interest_percent_daily"] = legacy_daily
        if "borrow_interest_percent_daily" in settings and "borrow_apr_usdt_points_percent" not in settings:
            _to_float(settings.get("borrow_interest_percent_daily"), name="borrow_interest_percent_daily", minimum=0, maximum=100)
            apr_payload = write_apr_from_daily(settings, now=now, actor_id=service._actor_id(actor))
            apr_value = apr_payload["trading.borrow_apr_usdt_points_percent"]
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.borrow_apr_usdt_points_percent", apr_value, now, service._actor_id(actor)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.borrow_interest_percent_daily", apr_payload["trading.borrow_interest_percent_daily"], now, service._actor_id(actor)),
            )
            setting_changes["trading.borrow_apr_usdt_points_percent"] = apr_value
            setting_changes["trading.borrow_interest_percent_daily"] = apr_payload["trading.borrow_interest_percent_daily"]
        if "borrow_interest_pool_pressure_multiplier" in settings:
            value = float_input_text(settings, "borrow_interest_pool_pressure_multiplier", minimum=0, maximum=100)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.borrow_interest_pool_pressure_multiplier", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.borrow_interest_pool_pressure_multiplier"] = value
        for input_key, storage_key in (
            ("borrow_interest_interval_hours", "trading.borrow_interest_interval_hours"),
            ("borrow_interest_minimum_hours", "trading.borrow_interest_minimum_hours"),
        ):
            if input_key in settings:
                value = int_input_text(settings, input_key, minimum=1, maximum=168)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (storage_key, value, now, service._actor_id(actor)),
                )
                setting_changes[storage_key] = value
        for input_key, storage_key in (
            ("margin_long_financing_percent", "trading.margin_long_financing_percent"),
            ("short_collateral_percent", "trading.short_collateral_percent"),
        ):
            if input_key in settings:
                value = float_input_text(settings, input_key, minimum=0, maximum=100)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (storage_key, value, now, service._actor_id(actor)),
                )
                setting_changes[storage_key] = value
        if "margin_maintenance_percent" in settings:
            value = float_input_text(settings, "margin_maintenance_percent", minimum=0, maximum=100)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.margin_maintenance_percent", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.margin_maintenance_percent"] = value
        if "grid_fee_discount_percent" in settings:
            value = float_input_text(settings, "grid_fee_discount_percent", minimum=0, maximum=100)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.grid_fee_discount_percent", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.grid_fee_discount_percent"] = value
        if "max_price_staleness_seconds" in settings:
            value = int_input_text(settings, "max_price_staleness_seconds", minimum=0, maximum=86400)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.max_price_staleness_seconds", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.max_price_staleness_seconds"] = value
        if "bot_auto_scan_interval_seconds" in settings:
            value = int_input_text(settings, "bot_auto_scan_interval_seconds", minimum=10, maximum=3600)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.bot_auto_scan_interval_seconds", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.bot_auto_scan_interval_seconds"] = value
        if "bot_auto_scan_limit" in settings:
            value = int_input_text(settings, "bot_auto_scan_limit", minimum=1, maximum=200)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.bot_auto_scan_limit", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.bot_auto_scan_limit"] = value
        if "bot_competition_weekly_reward_points" in settings:
            value = int_input_text(settings, "bot_competition_weekly_reward_points", minimum=0, maximum=1_000_000)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.bot_competition_weekly_reward_points", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.bot_competition_weekly_reward_points"] = value
        if "backtest_max_candles" in settings:
            value = int_input_text(settings, "backtest_max_candles", minimum=service.BACKTEST_MAX_CANDLES_FLOOR, maximum=service.BACKTEST_MAX_CANDLES_CEILING)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.backtest_max_candles", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.backtest_max_candles"] = value
        if "backtest_capacity_time_budget_seconds" in settings:
            value = int_input_text(settings, "backtest_capacity_time_budget_seconds", minimum=service.BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS, maximum=service.BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.backtest_capacity_time_budget_seconds", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.backtest_capacity_time_budget_seconds"] = value
        if "bot_audit_interval_seconds" in settings:
            value = int_input_text(settings, "bot_audit_interval_seconds", minimum=60, maximum=86400)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.bot_audit_interval_seconds", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.bot_audit_interval_seconds"] = value
        if "bot_audit_limit" in settings:
            value = int_input_text(settings, "bot_audit_limit", minimum=1, maximum=200)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.bot_audit_limit", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.bot_audit_limit"] = value
        if "bot_audit_min_enabled_seconds" in settings:
            value = int_input_text(settings, "bot_audit_min_enabled_seconds", minimum=3600, maximum=604800)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.bot_audit_min_enabled_seconds", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.bot_audit_min_enabled_seconds"] = value
        if "price_source" in settings:
            value = choice_input_value(
                settings,
                "price_source",
                allowed={service.FUSED_PRICE_SOURCE, "binance_public_api", "manual_root"},
                error_message="price_source must be fused_weighted, binance_public_api, or manual_root",
            )
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_source", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_source"] = value
        if "price_fusion_mode" in settings:
            value = choice_input_value(
                settings,
                "price_fusion_mode",
                allowed=service.PRICE_FUSION_MODES,
                error_message="price_fusion_mode must be auto_depth or manual_weights",
            )
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_mode", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_mode"] = value
        if "price_fusion_manual_weights" in settings:
            value = _normalize_price_fusion_manual_weights(service, settings.get("price_fusion_manual_weights"))
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_manual_weights_json", _json_dumps(value), now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_manual_weights_json"] = value
        if "price_fusion_depth_levels" in settings:
            value = int_input_text(settings, "price_fusion_depth_levels", minimum=10, maximum=service.MAX_PRICE_FUSION_DEPTH_LEVELS)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_depth_levels", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_depth_levels"] = value
        if "price_fusion_depth_band_percent" in settings:
            value = float_input_text(settings, "price_fusion_depth_band_percent", minimum=0.1, maximum=10)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_depth_band_percent", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_depth_band_percent"] = value
        if "price_fusion_min_orderbook_coverage_percent" in settings:
            value = float_input_text(settings, "price_fusion_min_orderbook_coverage_percent", minimum=0.1, maximum=10)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_min_orderbook_coverage_percent", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_min_orderbook_coverage_percent"] = value
        if "price_fusion_max_single_provider_weight_percent" in settings:
            value = float_input_text(settings, "price_fusion_max_single_provider_weight_percent", minimum=0, maximum=100)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_max_single_provider_weight_percent", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_max_single_provider_weight_percent"] = value
        if "price_fusion_min_provider_count" in settings:
            value = int_input_text(settings, "price_fusion_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS))
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_min_provider_count", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_min_provider_count"] = value
        if "price_fusion_trade_min_provider_count" in settings:
            value = int_input_text(settings, "price_fusion_trade_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS))
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_fusion_trade_min_provider_count", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_fusion_trade_min_provider_count"] = value
        if "warning_language" in settings:
            value = choice_input_value(
                settings,
                "warning_language",
                allowed={"zh-TW", "en"},
                error_message="warning_language must be zh-TW or en",
            )
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.warning_language", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.warning_language"] = value
        if "simulated_slippage_base_basis_points" in settings:
            value = float_input_text(settings, "simulated_slippage_base_basis_points", minimum=0, maximum=10000)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.simulated_slippage_base_basis_points", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.simulated_slippage_base_basis_points"] = value
        if "simulated_slippage_size_basis_points_per_10k_notional" in settings:
            value = float_input_text(settings, "simulated_slippage_size_basis_points_per_10k_notional", minimum=0, maximum=10000)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.simulated_slippage_size_basis_points_per_10k_notional", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.simulated_slippage_size_basis_points_per_10k_notional"] = value
        if "simulated_slippage_max_basis_points" in settings:
            value = float_input_text(settings, "simulated_slippage_max_basis_points", minimum=0, maximum=10000)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.simulated_slippage_max_basis_points", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.simulated_slippage_max_basis_points"] = value
        if "price_stream_ws_stale_seconds" in settings:
            value = int_input_text(settings, "price_stream_ws_stale_seconds", minimum=1, maximum=120)
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.price_stream_ws_stale_seconds", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.price_stream_ws_stale_seconds"] = value
        if "btc_trade_project_dir" in settings:
            value = text_input_value(settings, "btc_trade_project_dir")
            conn.execute(
                "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("trading.btc_trade_project_dir", value, now, service._actor_id(actor)),
            )
            setting_changes["trading.btc_trade_project_dir"] = value
        for input_key, storage_key in (
            ("btc_trade_repo_url", "trading.btc_trade_repo_url"),
            ("btc_trade_branch", "trading.btc_trade_branch"),
        ):
            if input_key in settings:
                value = text_input_value(settings, input_key)
                if input_key == "btc_trade_repo_url" and not value:
                    value = "https://github.com/s9213712/BTC_trade.git"
                if input_key == "btc_trade_branch" and not value:
                    value = "strategy/v15b-plus"
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (storage_key, value, now, service._actor_id(actor)),
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
            updates["updated_by"] = service._actor_id(actor)
            assignments = ", ".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE trading_markets SET {assignments} WHERE symbol=?", [*updates.values(), symbol])
            changed_markets.append({"symbol": symbol, **updates})
        if setting_changes:
            service._audit_event(conn, "TRADING_SETTINGS_UPDATED", "root updated trading settings", actor=actor, metadata=setting_changes)
        if changed_markets:
            service._audit_event(conn, "TRADING_MARKET_BILLING_UPDATED", "root updated trading billing parameters", actor=actor, metadata={"markets": changed_markets})
        if not setting_changes and not changed_markets:
            raise ValueError("no trading settings changes")
        conn.commit()
        return {"ok": True, **service.get_root_settings()}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_market(service, *, actor, symbol, manual_price_points=None, max_price_jump_percent=None, fee_rate_percent=None, min_order_points=None, max_order_points=None, enabled=None, confirm_jump=False):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
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
        updates["updated_by"] = service._actor_id(actor)
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE trading_markets SET {assignments} WHERE symbol=?", [*updates.values(), market["symbol"]])
        service._audit_event(conn, "TRADING_MARKET_UPDATED", "root updated manual market settings", actor=actor, market_symbol=market["symbol"], metadata=updates)
        conn.commit()
        updated = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (market["symbol"],)).fetchone()
        return {"ok": True, "market": service._market_payload(updated)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def allocate_reserve(service, *, actor, source_user_id, amount_points, reason):
    amount = _to_int(amount_points, name="amount_points", minimum=1)
    if str(reason or "").strip() != "ROOT_RESERVE_ALLOCATION":
        raise ValueError("reason must be ROOT_RESERVE_ALLOCATION")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        ledger = service._ledger(
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
            public_metadata={"reason": "ROOT_RESERVE_ALLOCATION", "allocated_by": service._actor_id(actor)},
            actor=actor,
            risk_flag="admin_action",
            risk_score=80,
        )
        balance = service._reserve_delta(
            conn,
            delta=amount,
            event_type="root_reserve_allocation",
            reason="ROOT_RESERVE_ALLOCATION",
            actor=actor,
            source_user_id=source_user_id,
            points_ledger_uuid=ledger["ledger_uuid"],
        )
        service._audit_event(conn, "TRADING_RESERVE_ALLOCATED", "root allocated points to trading reserve", actor=actor, target_user_id=source_user_id, severity="warning", metadata={"amount_points": amount, "reason": "ROOT_RESERVE_ALLOCATION", "ledger_uuid": ledger["ledger_uuid"]})
        conn.commit()
        return {"ok": True, "balance_points": balance, "ledger_uuid": ledger["ledger_uuid"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
