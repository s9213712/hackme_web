import hashlib
import inspect
import json
import math
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.system.notifications import create_notification_if_enabled, create_root_notification_if_enabled
from services.points_chain import (
    DISPLAY_CURRENCY,
    actor_value,
    compute_ledger_hash,
    metadata_hash,
    normalize_currency_type,
    public_account_id,
    utc_now,
    _metadata_json_checked,
)
from services.server_mode.context import SmV2Context, current_ctx
from services.server_mode.routing import resolve_table
from services.trading.accounting.core import (
    _decimal_units,
    _quantity_step_units_from_precision,
    fee_points,
    notional_points,
    quantity_to_units,
    units_to_quantity,
)
from services.trading.accounting.funding_pool import (
    funding_pool_outstanding_principal,
    funding_pool_payload,
)
from services.trading.accounting.interest import (
    margin_interest_due_micropoints,
    margin_interest_due_points,
    margin_interest_points,
    margin_interest_total_hours,
)
from services.trading.accounting.trial_credit import (
    trial_allocate_sell_result,
    trial_credit_expires_at,
    trial_credit_payload,
    trial_credit_status_after_delta,
    trial_units_for_buy,
)
from services.trading.audit import emit_trading_audit_event
from services.trading.constants import (
    APR_DAYS_PER_YEAR,
    ASSET_SCALE,
    DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT,
    DEFAULT_GRID_FEE_DISCOUNT_PERCENT,
    DEFAULT_SPOT_FEE_RATE_PERCENT,
    DEPTH_CAPABLE_PROVIDERS,
    GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT,
    OPEN_ORDER_STATUSES,
    POINT_MICRO_SCALE,
    PRICE_PROVIDER_LABELS,
    REFERENCE_PRICE_CAPABLE_PROVIDERS,
    TICKER_CAPABLE_PROVIDERS,
    TRADING_BOT_AUDIT_INTERVAL_SECONDS,
    TRADING_BOT_AUDIT_LIMIT,
    TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS,
    UNLIMITED_BOT_MAX_RUNS,
    WEIGHTED_PRICE_PROVIDERS,
    WORKFLOW_ACTION_TYPES,
    WORKFLOW_CONDITION_TYPES,
    WORKFLOW_NODE_TYPES,
    WORKFLOW_PORTS,
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
from services.trading.notifications import (
    create_trading_user_notification,
    insufficient_balance_notification_payload,
    margin_liquidated_notification_payload,
    trade_fill_notification_payload,
)
from services.trading.admin import (
    allocate_reserve as allocate_reserve_helper,
    get_backtest_capacity_measurement as get_backtest_capacity_measurement_helper,
    get_backtest_capacity_time_budget_seconds as get_backtest_capacity_time_budget_seconds_helper,
    get_max_backtest_candles as get_max_backtest_candles_helper,
    get_root_settings as get_root_settings_helper,
    record_backtest_capacity_measurement as record_backtest_capacity_measurement_helper,
    settings_payload as settings_payload_helper,
    update_market as update_market_helper,
    update_root_settings as update_root_settings_helper,
)
from services.trading.margin import (
    accrue_margin_interest as accrue_margin_interest_helper,
    add_margin_collateral as add_margin_collateral_helper,
    close_margin_position as close_margin_position_helper,
    margin_account_payload,
    margin_free_margin_points,
    margin_liquidation_order_key,
    margin_position_payload_with_risk,
    margin_risk_payload,
    margin_summary_payload,
    margin_summary_payload_legacy,
    notify_margin_risk_alerts,
    open_margin_position as open_margin_position_helper,
    scan_margin_liquidations as scan_margin_liquidations_helper,
)
from services.trading.orders import (
    cancel_order as cancel_order_helper,
    execute_order as execute_order_helper,
    match_open_limit_orders as match_open_limit_orders_helper,
    place_order as place_order_helper,
)
from services.trading.price_fusion.context import (
    price_context_confidence,
    price_context_risk_grade_usable,
    price_source_label,
    price_usage_label,
)
from services.trading.price_fusion.orderbook import (
    depth_notional_score,
    depth_notional_snapshot,
    parse_orderbook_side,
    provider_depth_request_limit,
)
from services.trading.price_fusion.weights import (
    apply_price_fusion_weight_cap,
    build_price_fusion_weight_model,
    price_fusion_effective_score,
    price_fusion_reference_score,
)
from services.trading.payloads import (
    bot_audit_eligibility_reason_label,
    bot_audit_label,
    bot_payload,
    bot_run_payload,
    fill_payload,
    futures_position_payload,
    margin_position_payload,
    market_payload,
    order_payload,
    position_payload,
)
from services.trading.price_runtime import (
    append_price_fusion_warning as append_price_fusion_warning_helper,
    build_orderbook_snapshot as build_orderbook_snapshot_helper,
    build_price_context as build_price_context_helper,
    current_market_price_points as current_market_price_points_helper,
    fetch_live_price_points as fetch_live_price_points_helper,
    fetch_weighted_fused_price_points as fetch_weighted_fused_price_points_helper,
    get_live_market_quote as get_live_market_quote_helper,
    price_fusion_warning as price_fusion_warning_helper,
    price_stream_provider_state as price_stream_provider_state_helper,
    primary_price_fusion_warning as primary_price_fusion_warning_helper,
    provider_orderbook_with_fallback as provider_orderbook_with_fallback_helper,
    provider_quantity_unit_info as provider_quantity_unit_info_helper,
    provider_ticker_with_fallback as provider_ticker_with_fallback_helper,
    provider_transport_meta as provider_transport_meta_helper,
    recent_price_window as recent_price_window_helper,
    resolve_stream_orderbook_snapshot as resolve_stream_orderbook_snapshot_helper,
    resolve_stream_ticker_snapshot as resolve_stream_ticker_snapshot_helper,
    root_price_fusion_status_on_conn as root_price_fusion_status_on_conn_helper,
    stored_market_price_contexts as stored_market_price_contexts_helper,
    transport_state_from_provider_rows as transport_state_from_provider_rows_helper,
)
from services.trading.reporting import (
    funding_payload as funding_payload_runtime_helper,
    margin_trade_records as margin_trade_records_helper,
    position_payload_with_metrics as position_payload_with_metrics_helper,
    root_report as root_report_helper,
    user_dashboard as user_dashboard_helper,
)
from services.trading.shadow import (
    ensure_shadow_wallet as ensure_shadow_wallet_helper,
    shadow_actor_user_id as shadow_actor_user_id_helper,
    shadow_existing_ledger_row as shadow_existing_ledger_row_helper,
    shadow_last_ledger_hash as shadow_last_ledger_hash_helper,
    shadow_record_transaction as shadow_record_transaction_helper,
    shadow_wallet_payload as shadow_wallet_payload_helper,
    wallet_payload as wallet_payload_helper,
    wallet_row as wallet_row_helper,
)
from services.trading.trial_credit import (
    cancel_trial_reclaim_sell_orders as cancel_trial_reclaim_sell_orders_helper,
    clear_trial_reclaim_blocked as clear_trial_reclaim_blocked_helper,
    ensure_trial_credit as ensure_trial_credit_helper,
    reclaim_trial_credit as reclaim_trial_credit_helper,
    release_trial_margin_collateral as release_trial_margin_collateral_helper,
    set_trial_reclaim_blocked as set_trial_reclaim_blocked_helper,
    trial_allocate_sell as trial_allocate_sell_helper,
    trial_credit_row as trial_credit_row_helper,
    trial_deploy as trial_deploy_helper,
    trial_delta as trial_delta_helper,
    trial_lock_for_buy as trial_lock_for_buy_helper,
    trial_mark_buy_executed as trial_mark_buy_executed_helper,
    trial_position as trial_position_helper,
    trial_spend as trial_spend_helper,
    trial_unlock as trial_unlock_helper,
)
from services.trading.grid import (
    create_grid_bot as create_grid_bot_helper,
    delete_grid_bot as delete_grid_bot_helper,
    grid_bot_payload,
    grid_fee_rate_percent,
    grid_levels,
    list_grid_bots as list_grid_bots_helper,
    grid_preview_fee_rates,
    grid_preview_risk,
    grid_preview_summary,
    grid_quantity_units,
    preview_grid_bot as preview_grid_bot_helper,
    scan_grid_bots as scan_grid_bots_helper,
    scan_one_grid_bot as scan_one_grid_bot_helper,
    toggle_grid_bot as toggle_grid_bot_helper,
)
from services.trading.bots.indicators import (
    build_workflow_indicator_series,
    workflow_indicator_context,
)
from services.trading.bots.workflow import (
    condition_label,
    validate_workflow,
    validate_workflow_graph,
    workflow_condition_hit,
    workflow_decision,
    workflow_graph_decision,
)
from services.trading.bots.service import (
    bot_audit_candidates as bot_audit_candidates_helper,
    bot_audit_dashboard_on_conn as bot_audit_dashboard_on_conn_helper,
    bot_audit_enabled_at_on_row as bot_audit_enabled_at_helper,
    bot_audit_is_eligible_on_row as bot_audit_is_eligible_helper,
    bot_audit_latest_map_on_conn as bot_audit_latest_map_helper,
    bot_audit_run_findings as bot_audit_run_findings_helper,
    bot_condition_checks as bot_condition_checks_helper,
    bot_trigger_hit as bot_trigger_hit_helper,
    delete_trading_bot as delete_trading_bot_helper,
    get_bot_audit_dashboard as get_bot_audit_dashboard_helper,
    increase_trading_bot_max_runs as increase_trading_bot_max_runs_helper,
    legacy_workflow as legacy_workflow_helper,
    list_trading_bots as list_trading_bots_helper,
    quantity_text_from_budget as quantity_text_from_budget_helper,
    record_bot_audit_run as record_bot_audit_run_helper,
    record_bot_run as record_bot_run_helper,
    run_due_bot_audits as run_due_bot_audits_helper,
    run_due_trading_bots as run_due_trading_bots_helper,
    run_trading_bot_once as run_trading_bot_once_helper,
    run_trading_bot_rows as run_trading_bot_rows_helper,
    run_trading_bots as run_trading_bots_helper,
    save_trading_bot as save_trading_bot_helper,
    validate_bot_payload as validate_bot_payload_helper,
    workflow_live_context as workflow_live_context_helper,
    workflow_order_from_decision as workflow_order_from_decision_helper,
)
from services.trading.backtest import (
    backtest_trading_bot as backtest_trading_bot_helper,
)
from services.trading.funding import (
    close_root_contract_position as close_root_contract_position_helper,
    funding_payload as funding_payload_helper,
    funding_snapshot_ctx as funding_snapshot_ctx_helper,
    get_funding_rate_snapshot as get_funding_rate_snapshot_helper,
    open_root_contract_position as open_root_contract_position_helper,
    publish_funding_rate_snapshot as publish_funding_rate_snapshot_helper,
    reset_root_simulated_balance as reset_root_simulated_balance_helper,
    root_sim_account as root_sim_account_helper,
    settle_funding_adjustment as settle_funding_adjustment_helper,
    sim_delta as sim_delta_helper,
)
from services.trading.markets import (
    create_market_provider_mapping as create_market_provider_mapping_helper,
    create_market_registry as create_market_registry_helper,
    disable_market_provider_mapping as disable_market_provider_mapping_helper,
    disable_market_registry as disable_market_registry_helper,
    fallback_market_display_symbol,
    get_market_provider_registry as get_market_provider_registry_helper,
    list_market_registry as list_market_registry_helper,
    market_display_symbol_from_registry_row,
    market_provider_mapping_payload as market_provider_mapping_payload_helper,
    market_provider_ids_from_mappings,
    market_registry_audit as market_registry_audit_helper,
    market_registry_payload as market_registry_payload_helper,
    market_seed_compare_value,
    market_supports_mapping_rows,
    normalize_market_symbol_from_rows,
    persist_market_registry_probe as persist_market_registry_probe_helper,
    probe_market_registry as probe_market_registry_helper,
    probe_market_registry_on_conn as probe_market_registry_on_conn_helper,
    provider_mapping_capabilities,
    registry_seed_status,
    update_market_provider_mapping as update_market_provider_mapping_helper,
    update_market_registry as update_market_registry_helper,
    validate_market_provider_mapping_payload as validate_market_provider_mapping_payload_helper,
    validate_market_registry_payload as validate_market_registry_payload_helper,
)
from services.trading.validators import (
    _apr_percent_from_daily,
    _billable_interest_hours_from_elapsed_seconds,
    _daily_percent_from_apr,
    _decimal_text,
    _normalize_borrow_interest_timing,
    _to_decimal,
    _to_float,
    _to_int,
    _to_price_float,
)
from services.trading.verification import (
    ledger_row as ledger_row_helper,
    replay_positions as replay_positions_helper,
    verify_fill_ledgers as verify_fill_ledgers_helper,
    verify_margin_position_locks as verify_margin_position_locks_helper,
    verify_open_order_locks as verify_open_order_locks_helper,
    verify_reserve_pool as verify_reserve_pool_helper,
    verify_sim_accounts as verify_sim_accounts_helper,
    verify_spot_realized_pnl as verify_spot_realized_pnl_helper,
    verify_state as verify_state_helper,
    verify_state_on_conn as verify_state_on_conn_helper,
)
from services.trading.mode_gate import (
    assert_same_world,
    assert_trading_allowed,
    funding_channel_key,
    liquidation_settle_table,
    liquidation_target_table,
    matching_orderbook_key,
)
from services.trading.catalog import (
    TRADING_MARKET_CATALOG_SEED_VERSION,
    list_market_definitions,
    list_live_price_markets,
    list_seed_markets,
    market_display_symbol,
    market_provider_id,
    market_sort_key,
    market_supports_btc_trade,
    market_supports_live_price,
    normalize_market_symbol,
)
from services.trading.streams import TradingPriceStreamHub, WS_CAPABLE_PRICE_PROVIDERS


USDT_TO_POINTS_RATE = 1
ROOT_SIMULATED_INITIAL_POINTS = 10_000
TRIAL_CREDIT_INITIAL_POINTS = 1_000
TRIAL_CREDIT_DAYS = 7
TRADING_FUNDING_POOL_INITIAL_POINTS = 10_000
TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER = 4.0
MARGIN_LONG_FINANCING_RATE_PERCENT = 90.0
SHORT_COLLATERAL_RATE_PERCENT = 60.0
SUPPORTED_EXECUTION_MODES = {"house_counterparty", "pvp_matching", "hybrid_liquidity"}
BACKTEST_SEGMENT_CANDLES = 10_000
# Default cap; root may override via trading_settings 'trading.backtest_max_candles'.
# Hard floor (1000) and ceiling (10_000_000) are enforced wherever the setting is consumed.
MAX_BACKTEST_CANDLES = 20_000
BACKTEST_MAX_CANDLES_FLOOR = 1_000
BACKTEST_MAX_CANDLES_CEILING = 10_000_000
# First-boot probe budget bounds (seconds). Default 60s gives a stable signal;
# floor 5s prevents nonsense projections from dust-sized probes.
BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS = 60
BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS = 5
BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS = 600
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
DEFAULT_PRICE_STREAM_WS_STALE_SECONDS = 10
DEFAULT_BORROW_APR_BTC_ETH_PERCENT = 8.0
DEFAULT_BORROW_APR_USDT_POINTS_PERCENT = 10.0
DEFAULT_BORROW_INTEREST_INTERVAL_HOURS = 1
DEFAULT_BORROW_INTEREST_MINIMUM_HOURS = 1
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


def _condition_label(cond):
    return condition_label(cond)


def _registry_display_quote_currency(definition):
    return str(definition.get("display_quote_currency") or definition.get("quote_currency") or "").strip().upper()


def _registry_display_name(definition):
    base = str(definition.get("base_asset") or "").strip().upper()
    quote = _registry_display_quote_currency(definition)
    return f"{base}/{quote}" if base and quote else str(definition.get("symbol") or "").strip().upper()


def _registry_default_market_payload(definition):
    return {
        "symbol": str(definition.get("symbol") or "").strip().upper(),
        "base_asset": str(definition.get("base_asset") or "").strip().upper(),
        "quote_asset": str(definition.get("quote_currency") or "POINTS").strip().upper() or "POINTS",
        "display_name": _registry_display_name(definition),
        "display_quote_currency": _registry_display_quote_currency(definition),
        "market_type": "spot",
        "enabled": 1,
        "allow_spot": 1,
        "allow_margin": 1,
        "allow_bots": 1,
        "allow_risk_grade_usage": 1,
        "price_precision": 8,
        "quantity_precision": 8,
        "min_order_size": 0.00000001,
        "max_order_size": 1000000.0,
        "lot_size": 0.00000001,
        "tick_size": 0.00000001,
        "sort_order": int(definition.get("sort_order") or 9999),
        "default_manual_price_points": float(definition.get("default_manual_price_points") or 1.0),
        "live_price_enabled": 1 if definition.get("live_price_enabled") else 0,
        "reference_price_enabled": 1 if definition.get("reference_price_enabled") else 0,
        "btc_trade_enabled": 1 if definition.get("btc_trade_enabled") else 0,
        "registry_source": "catalog_seed",
        "seed_version": int(TRADING_MARKET_CATALOG_SEED_VERSION),
    }


def _provider_mapping_capabilities(provider):
    return provider_mapping_capabilities(
        provider,
        ticker_capable_providers=TICKER_CAPABLE_PROVIDERS,
        depth_capable_providers=DEPTH_CAPABLE_PROVIDERS,
        reference_price_capable_providers=REFERENCE_PRICE_CAPABLE_PROVIDERS,
    )


def _market_seed_compare_value(value):
    return market_seed_compare_value(value)


def _registry_seed_status(registry_row, mappings):
    return registry_seed_status(
        registry_row,
        mappings,
        registry_default_market_payload=_registry_default_market_payload,
        provider_mapping_capabilities_func=_provider_mapping_capabilities,
    )


def _seed_market_registry_from_catalog(conn):
    now = _now()
    for definition in list_market_definitions():
        payload = _registry_default_market_payload(definition)
        conn.execute(
            """
            INSERT OR IGNORE INTO trading_markets_registry (
                symbol, base_asset, quote_asset, display_name, display_quote_currency,
                market_type, enabled, allow_spot, allow_margin, allow_bots,
                allow_risk_grade_usage, price_precision, quantity_precision,
                min_order_size, max_order_size, lot_size, tick_size, sort_order,
                default_manual_price_points, live_price_enabled, reference_price_enabled,
                btc_trade_enabled, registry_source, seed_version, probe_status, probe_summary_json,
                created_at, updated_at, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'seeded', '{}', ?, ?, NULL, NULL)
            """,
            (
                payload["symbol"],
                payload["base_asset"],
                payload["quote_asset"],
                payload["display_name"],
                payload["display_quote_currency"],
                payload["market_type"],
                payload["enabled"],
                payload["allow_spot"],
                payload["allow_margin"],
                payload["allow_bots"],
                payload["allow_risk_grade_usage"],
                payload["price_precision"],
                payload["quantity_precision"],
                payload["min_order_size"],
                payload["max_order_size"],
                payload["lot_size"],
                payload["tick_size"],
                payload["sort_order"],
                payload["default_manual_price_points"],
                payload["live_price_enabled"],
                payload["reference_price_enabled"],
                payload["btc_trade_enabled"],
                payload["registry_source"],
                payload["seed_version"],
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE trading_markets_registry
            SET seed_version=?, updated_at=CASE WHEN registry_source='catalog_seed' AND updated_by IS NULL THEN ? ELSE updated_at END
            WHERE symbol=? AND registry_source='catalog_seed'
            """,
            (int(TRADING_MARKET_CATALOG_SEED_VERSION), now, payload["symbol"]),
        )
        registry = conn.execute(
            "SELECT id FROM trading_markets_registry WHERE symbol=?",
            (payload["symbol"],),
        ).fetchone()
        if not registry:
            continue
        provider_ids = dict(definition.get("provider_ids") or {})
        priority = 1
        for provider, provider_symbol in provider_ids.items():
            capabilities = _provider_mapping_capabilities(provider)
            conn.execute(
                """
                INSERT OR IGNORE INTO trading_market_provider_mappings (
                    market_id, provider, provider_symbol,
                    supports_ticker, supports_depth, supports_candles,
                    enabled, priority, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(registry["id"]),
                    provider,
                    str(provider_symbol or "").strip(),
                    capabilities["supports_ticker"],
                    capabilities["supports_depth"],
                    capabilities["supports_candles"],
                    1 if str(provider_symbol or "").strip() else 0,
                    priority,
                    now,
                    now,
                ),
            )
            priority += 1


def _sync_registry_markets_to_runtime(conn):
    runtime_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_markets)").fetchall()}
    runtime_has_provider_ids = "provider_ids_json" in runtime_cols
    rows = conn.execute(
        """
        SELECT *
        FROM trading_markets_registry
        ORDER BY sort_order ASC, symbol ASC
        """
    ).fetchall()
    now = _now()
    for registry in rows:
        mappings = conn.execute(
            """
            SELECT *
            FROM trading_market_provider_mappings
            WHERE market_id=?
            ORDER BY enabled DESC, priority ASC, id ASC
            """,
            (int(registry["id"]),),
        ).fetchall()
        provider_ids = {
            str(row["provider"] or "").strip(): str(row["provider_symbol"] or "").strip()
            for row in mappings
            if int(row["enabled"] or 0) and str(row["provider_symbol"] or "").strip()
        }
        live_supported = bool(registry["live_price_enabled"]) and any(
            int(row["enabled"] or 0) and int(row["supports_ticker"] or 0) and str(row["provider_symbol"] or "").strip()
            for row in mappings
        )
        reference_supported = bool(registry["reference_price_enabled"]) and any(
            int(row["enabled"] or 0) and int(row["supports_candles"] or 0) and str(row["provider_symbol"] or "").strip()
            for row in mappings
        )
        existing = conn.execute(
            "SELECT * FROM trading_markets WHERE symbol=?",
            (str(registry["symbol"] or "").strip().upper(),),
        ).fetchone()
        if existing:
            assignments = [
                "base_asset=?",
                "quote_currency=?",
                "enabled=?",
                "spot_enabled=?",
                "display_quote_currency=?",
                "display_name=?",
                "market_type=?",
                "sort_order=?",
                "allow_margin=?",
                "allow_bots=?",
                "allow_risk_grade_usage=?",
                "price_precision=?",
                "quantity_precision=?",
                "min_order_size=?",
                "max_order_size=?",
                "lot_size=?",
                "tick_size=?",
                "live_price_enabled=?",
                "reference_price_enabled=?",
                "btc_trade_enabled=?",
                "updated_at=?",
                "updated_by=NULL",
            ]
            values = [
                registry["base_asset"],
                registry["quote_asset"],
                int(registry["enabled"] or 0),
                int(registry["allow_spot"] or 0),
                registry["display_quote_currency"],
                registry["display_name"],
                registry["market_type"],
                int(registry["sort_order"] or 9999),
                int(registry["allow_margin"] or 0),
                int(registry["allow_bots"] or 0),
                int(registry["allow_risk_grade_usage"] or 0),
                int(registry["price_precision"] or 8),
                int(registry["quantity_precision"] or 8),
                float(registry["min_order_size"] or 0.00000001),
                float(registry["max_order_size"] or 1000000.0),
                float(registry["lot_size"] or 0.00000001),
                float(registry["tick_size"] or 0.00000001),
                1 if live_supported else 0,
                1 if reference_supported else 0,
                int(registry["btc_trade_enabled"] or 0),
                now,
            ]
            if runtime_has_provider_ids:
                assignments.insert(-2, "provider_ids_json=?")
                values.insert(-1, _json_dumps(provider_ids))
            conn.execute(
                f"UPDATE trading_markets SET {', '.join(assignments)} WHERE symbol=?",
                [*values, registry["symbol"]],
            )
        else:
            columns = [
                "symbol",
                "base_asset",
                "quote_currency",
                "enabled",
                "spot_enabled",
                "manual_price_points",
                "fee_rate_percent",
                "updated_at",
                "price_source",
                "display_quote_currency",
                "display_name",
                "market_type",
                "sort_order",
                "allow_margin",
                "allow_bots",
                "allow_risk_grade_usage",
                "price_precision",
                "quantity_precision",
                "min_order_size",
                "max_order_size",
                "lot_size",
                "tick_size",
                "live_price_enabled",
                "reference_price_enabled",
                "btc_trade_enabled",
            ]
            values = [
                registry["symbol"],
                registry["base_asset"],
                registry["quote_asset"],
                int(registry["enabled"] or 0),
                int(registry["allow_spot"] or 0),
                registry["default_manual_price_points"] or 1,
                DEFAULT_SPOT_FEE_RATE_PERCENT,
                now,
                FUSED_PRICE_SOURCE,
                registry["display_quote_currency"],
                registry["display_name"],
                registry["market_type"],
                int(registry["sort_order"] or 9999),
                int(registry["allow_margin"] or 0),
                int(registry["allow_bots"] or 0),
                int(registry["allow_risk_grade_usage"] or 0),
                int(registry["price_precision"] or 8),
                int(registry["quantity_precision"] or 8),
                float(registry["min_order_size"] or 0.00000001),
                float(registry["max_order_size"] or 1000000.0),
                float(registry["lot_size"] or 0.00000001),
                float(registry["tick_size"] or 0.00000001),
                1 if live_supported else 0,
                1 if reference_supported else 0,
                int(registry["btc_trade_enabled"] or 0),
            ]
            if runtime_has_provider_ids:
                columns.append("provider_ids_json")
                values.append(_json_dumps(provider_ids))
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO trading_markets ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )


def ensure_trading_schema(conn):
    # Slice 4b: pure CREATE TABLE DDL strings live in schema_ddl.py so
    # this function shrinks from 740 lines to ~280. Imperative migrations
    # (PRAGMA-guarded ALTER TABLE, legacy unit renames, default settings
    # INSERT OR IGNORE, registry catalog seed) stay below because they
    # need shared `now` + helpers.
    from services.trading.schema_ddl import ALL_TABLE_DDL

    for ddl in ALL_TABLE_DDL:
        conn.execute(ddl)
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
    for column_name, ddl in (
        ("display_quote_currency", "ALTER TABLE trading_markets ADD COLUMN display_quote_currency TEXT NOT NULL DEFAULT 'USDT'"),
        ("display_name", "ALTER TABLE trading_markets ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"),
        ("market_type", "ALTER TABLE trading_markets ADD COLUMN market_type TEXT NOT NULL DEFAULT 'spot'"),
        ("sort_order", "ALTER TABLE trading_markets ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 9999"),
        ("allow_margin", "ALTER TABLE trading_markets ADD COLUMN allow_margin INTEGER NOT NULL DEFAULT 1"),
        ("allow_bots", "ALTER TABLE trading_markets ADD COLUMN allow_bots INTEGER NOT NULL DEFAULT 1"),
        ("allow_risk_grade_usage", "ALTER TABLE trading_markets ADD COLUMN allow_risk_grade_usage INTEGER NOT NULL DEFAULT 1"),
        ("price_precision", "ALTER TABLE trading_markets ADD COLUMN price_precision INTEGER NOT NULL DEFAULT 8"),
        ("quantity_precision", "ALTER TABLE trading_markets ADD COLUMN quantity_precision INTEGER NOT NULL DEFAULT 8"),
        ("min_order_size", "ALTER TABLE trading_markets ADD COLUMN min_order_size REAL NOT NULL DEFAULT 0.00000001"),
        ("max_order_size", "ALTER TABLE trading_markets ADD COLUMN max_order_size REAL NOT NULL DEFAULT 1000000"),
        ("lot_size", "ALTER TABLE trading_markets ADD COLUMN lot_size REAL NOT NULL DEFAULT 0.00000001"),
        ("tick_size", "ALTER TABLE trading_markets ADD COLUMN tick_size REAL NOT NULL DEFAULT 0.00000001"),
        ("live_price_enabled", "ALTER TABLE trading_markets ADD COLUMN live_price_enabled INTEGER NOT NULL DEFAULT 1"),
        ("reference_price_enabled", "ALTER TABLE trading_markets ADD COLUMN reference_price_enabled INTEGER NOT NULL DEFAULT 1"),
        ("btc_trade_enabled", "ALTER TABLE trading_markets ADD COLUMN btc_trade_enabled INTEGER NOT NULL DEFAULT 0"),
        ("provider_ids_json", "ALTER TABLE trading_markets ADD COLUMN provider_ids_json TEXT NOT NULL DEFAULT '{}'"),
        # Boot-ready gate (2026-05-06, warmup tightened 2026-05-07):
        # NULL until at least two consecutive live quotes have produced a
        # stable candidate for this market. Trading / liquidation / bot ops
        # refuse to act on markets where this is still NULL — protects
        # against both the seed default and the very first live quote after a
        # fresh boot or provider recovery.
        ("live_price_warmup_started_at", "ALTER TABLE trading_markets ADD COLUMN live_price_warmup_started_at TEXT"),
        ("live_price_confirmed_at", "ALTER TABLE trading_markets ADD COLUMN live_price_confirmed_at TEXT"),
    ):
        if column_name not in market_cols:
            conn.execute(ddl)
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
    registry_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_markets_registry)").fetchall()}
    if "registry_source" not in registry_cols:
        conn.execute("ALTER TABLE trading_markets_registry ADD COLUMN registry_source TEXT NOT NULL DEFAULT 'catalog_seed'")
    if "seed_version" not in registry_cols:
        conn.execute("ALTER TABLE trading_markets_registry ADD COLUMN seed_version INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        """
        UPDATE trading_markets_registry
        SET registry_source='catalog_seed'
        WHERE registry_source IS NULL OR TRIM(registry_source)=''
        """
    )
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
        ("trading.price_stream_ws_enabled", "true"),
        ("trading.price_stream_ws_stale_seconds", str(DEFAULT_PRICE_STREAM_WS_STALE_SECONDS)),
        ("trading.shadow_funding_publish_enabled", "false"),
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
    _seed_market_registry_from_catalog(conn)
    _sync_registry_markets_to_runtime(conn)
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
    trial_credit_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trading_trial_credits)").fetchall()}
    if "reclaim_blocked_reason" not in trial_credit_cols:
        conn.execute("ALTER TABLE trading_trial_credits ADD COLUMN reclaim_blocked_reason TEXT NOT NULL DEFAULT ''")
    if "reclaim_blocked_at" not in trial_credit_cols:
        conn.execute("ALTER TABLE trading_trial_credits ADD COLUMN reclaim_blocked_at TEXT")
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
    MAX_BACKTEST_CANDLES = MAX_BACKTEST_CANDLES
    BACKTEST_MAX_CANDLES_FLOOR = BACKTEST_MAX_CANDLES_FLOOR
    BACKTEST_MAX_CANDLES_CEILING = BACKTEST_MAX_CANDLES_CEILING
    BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS = BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
    BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS = BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS
    BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS = BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS
    DEFAULT_BORROW_APR_BTC_ETH_PERCENT = DEFAULT_BORROW_APR_BTC_ETH_PERCENT
    DEFAULT_BORROW_APR_USDT_POINTS_PERCENT = DEFAULT_BORROW_APR_USDT_POINTS_PERCENT
    DEFAULT_BORROW_INTEREST_INTERVAL_HOURS = DEFAULT_BORROW_INTEREST_INTERVAL_HOURS
    DEFAULT_BORROW_INTEREST_MINIMUM_HOURS = DEFAULT_BORROW_INTEREST_MINIMUM_HOURS
    TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER = TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER
    MARGIN_LONG_FINANCING_RATE_PERCENT = MARGIN_LONG_FINANCING_RATE_PERCENT
    SHORT_COLLATERAL_RATE_PERCENT = SHORT_COLLATERAL_RATE_PERCENT
    FUSED_PRICE_SOURCE = FUSED_PRICE_SOURCE
    PRICE_FUSION_MODES = PRICE_FUSION_MODES
    DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS = DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS
    DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT = DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT
    DEFAULT_PRICE_FUSION_DEPTH_LEVELS = DEFAULT_PRICE_FUSION_DEPTH_LEVELS
    MAX_PRICE_FUSION_DEPTH_LEVELS = MAX_PRICE_FUSION_DEPTH_LEVELS
    DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT = DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT
    DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT = DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT
    DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS = DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS
    DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS = DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS
    DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT = DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT
    DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO = DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO
    DEFAULT_PRICE_STREAM_WS_STALE_SECONDS = DEFAULT_PRICE_STREAM_WS_STALE_SECONDS
    TRADING_BOT_AUDIT_INTERVAL_SECONDS = TRADING_BOT_AUDIT_INTERVAL_SECONDS
    TRADING_BOT_AUDIT_LIMIT = TRADING_BOT_AUDIT_LIMIT
    TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS = TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS
    ROOT_SIMULATED_INITIAL_POINTS = ROOT_SIMULATED_INITIAL_POINTS
    TRIAL_CREDIT_INITIAL_POINTS = TRIAL_CREDIT_INITIAL_POINTS
    TRIAL_CREDIT_DAYS = TRIAL_CREDIT_DAYS

    def __init__(self, *, get_db, points_service, audit=None, live_price_provider=None, historical_candles_provider=None, stream_hub=None):
        self.get_db = get_db
        self.points_service = points_service
        self.audit = audit or (lambda *args, **kwargs: None)
        self.live_price_provider = live_price_provider
        self.historical_candles_provider = historical_candles_provider
        self.stream_hub = stream_hub
        self._matching_orderbooks = {}
        self._funding_channels = {}

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
        emit_trading_audit_event(
            conn,
            event_type=event_type,
            message=message,
            actor_id=self._actor_id(actor),
            target_user_id=target_user_id,
            order_id=order_id,
            market_symbol=market_symbol,
            severity=severity,
            metadata=metadata,
            json_dumps=_json_dumps,
            now_text=_now,
            uuid_factory=uuid.uuid4,
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

    def _matching_orderbook_namespace(self, market_symbol, *, ctx=None):
        route_ctx = self._resolve_trading_ctx(ctx, action="matching_orderbook")
        market = str(market_symbol or "").strip().upper()
        key = matching_orderbook_key(market, route_ctx)
        book = self._matching_orderbooks.setdefault(
            key,
            {
                "market_symbol": market,
                "mode": route_ctx.mode,
                "tester_id": route_ctx.tester_id,
                "buy": {},
                "sell": {},
            },
        )
        return key, book, route_ctx

    def _matching_orderbook_keys_for_ctx(self, ctx):
        route_ctx = self._resolve_trading_ctx(ctx, action="matching_orderbook")
        return [
            key
            for key, book in self._matching_orderbooks.items()
            if str(book.get("mode") or "") == route_ctx.mode
            and int(book.get("tester_id") or 0) == int(route_ctx.tester_id or 0)
        ]

    def _matching_orderbook_apply_order(self, order, *, ctx=None):
        if not order:
            return None
        if str(order["order_type"] or "").strip().lower() != "limit":
            return None
        order_uuid = str(order["order_uuid"] or "").strip()
        if not order_uuid:
            return None
        side = str(order["side"] or "").strip().lower()
        key, book, route_ctx = self._matching_orderbook_namespace(order["market_symbol"], ctx=ctx)
        for side_name in ("buy", "sell"):
            if side_name != side:
                book[side_name].pop(order_uuid, None)
        if str(order["status"] or "") in OPEN_ORDER_STATUSES:
            book[side][order_uuid] = {
                "id": int(order["id"]),
                "order_uuid": order_uuid,
                "market_symbol": str(order["market_symbol"] or "").strip().upper(),
                "side": side,
                "status": str(order["status"] or ""),
                "limit_price_points": order["limit_price_points"],
                "updated_at": order["updated_at"],
            }
        else:
            book[side].pop(order_uuid, None)
        return key, route_ctx

    def _matching_orderbook_hydrate(self, conn, *, market_symbol=None, limit=200, ctx=None):
        orders_table, route_ctx = self._resolve_table("orders", ctx, action="matching_orderbook_hydrate")
        params = []
        where = "WHERE order_type='limit' AND status IN ('open', 'partially_filled')"
        if route_ctx.mode == "internal_test":
            if route_ctx.tester_id is None:
                raise ValueError("internal_test matching orderbook hydrate requires tester_id")
            where += " AND tester_user_id=?"
            params.append(int(route_ctx.tester_id))
        market = str(market_symbol or "").strip().upper()
        if market:
            where += " AND market_symbol=?"
            params.append(market)
        rows = conn.execute(
            f"SELECT * FROM {orders_table} {where} ORDER BY id ASC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        live_by_key = {}
        for row in rows:
            applied = self._matching_orderbook_apply_order(row, ctx=route_ctx)
            if not applied:
                continue
            key, _applied_ctx = applied
            live_by_key.setdefault(key, set()).add(str(row["order_uuid"] or ""))
        if market:
            keys = [matching_orderbook_key(market, route_ctx)]
        else:
            keys = self._matching_orderbook_keys_for_ctx(route_ctx)
        for key in keys:
            book = self._matching_orderbooks.get(key)
            if not book:
                continue
            live_uuids = live_by_key.get(key, set())
            for side_name in ("buy", "sell"):
                for order_uuid in list(book[side_name].keys()):
                    if order_uuid not in live_uuids:
                        book[side_name].pop(order_uuid, None)
        return route_ctx

    def _matching_orderbook_order_uuids(self, conn, *, market_symbol=None, limit=200, ctx=None):
        route_ctx = self._matching_orderbook_hydrate(conn, market_symbol=market_symbol, limit=limit, ctx=ctx)
        market = str(market_symbol or "").strip().upper()
        if market:
            keys = [matching_orderbook_key(market, route_ctx)]
        else:
            keys = self._matching_orderbook_keys_for_ctx(route_ctx)
        items = []
        for key in keys:
            book = self._matching_orderbooks.get(key) or {}
            for side_name in ("buy", "sell"):
                items.extend((book.get(side_name) or {}).values())
        items.sort(key=lambda item: int(item.get("id") or 0))
        return [str(item.get("order_uuid") or "") for item in items[: int(limit)] if str(item.get("order_uuid") or "")]

    def _funding_snapshot_ctx(self, snapshot):
        return funding_snapshot_ctx_helper(snapshot)

    def publish_funding_rate_snapshot(
        self,
        *,
        market_symbol,
        rate_percent,
        actor=None,
        ctx=None,
        provider_count=1,
        confidence="medium",
        stale=False,
        degraded=False,
        exclusion_reason="",
    ):
        return publish_funding_rate_snapshot_helper(
            self,
            market_symbol=market_symbol,
            rate_percent=rate_percent,
            actor=actor,
            ctx=ctx,
            provider_count=provider_count,
            confidence=confidence,
            stale=stale,
            degraded=degraded,
            exclusion_reason=exclusion_reason,
        )

    def get_funding_rate_snapshot(self, *, market_symbol, ctx=None):
        return get_funding_rate_snapshot_helper(self, market_symbol=market_symbol, ctx=ctx)

    def settle_funding_adjustment(
        self,
        *,
        actor,
        user_id,
        market_symbol,
        delta_points,
        published_snapshot=None,
        ctx=None,
        idempotency_key=None,
    ):
        return settle_funding_adjustment_helper(
            self,
            actor=actor,
            user_id=user_id,
            market_symbol=market_symbol,
            delta_points=delta_points,
            published_snapshot=published_snapshot,
            ctx=ctx,
            idempotency_key=idempotency_key,
        )

    def _legacy_production_ctx(self):
        return SmV2Context(
            mode="production",
            tester_id=None,
            actor_role="system",
            request_id="legacy-trading",
        )

    def _resolve_trading_ctx(self, ctx=None, *, action="trade"):
        if ctx is None:
            try:
                ctx = current_ctx()
            except Exception:
                ctx = self._legacy_production_ctx()
        return assert_trading_allowed(ctx, action=action)

    def _ambient_trading_ctx(self):
        try:
            return current_ctx()
        except Exception:
            return self._legacy_production_ctx()

    def _routing_ctx_for_read(self, ctx=None):
        route_ctx = ctx or self._ambient_trading_ctx()
        if getattr(route_ctx, "mode", "") not in {"production", "internal_test"}:
            return self._legacy_production_ctx()
        return route_ctx

    def _resolve_table(self, logical, ctx=None, *, for_write=False, action="trade"):
        route_ctx = self._resolve_trading_ctx(ctx, action=action) if for_write else self._routing_ctx_for_read(ctx)
        return resolve_table(logical, route_ctx), route_ctx

    def _sql_tables(self, ctx=None, *, for_write=False, action="trade"):
        _orders, route_ctx = self._resolve_table("orders", ctx, for_write=for_write, action=action)
        return ({
            "orders": _orders,
            "positions": resolve_table("positions", route_ctx),
            "points_ledger": resolve_table("points_ledger", route_ctx),
            "wallets": resolve_table("wallets", route_ctx),
        }, route_ctx)

    def _format_routed_sql(self, sql, ctx=None, *, for_write=False, action="trade"):
        tables, route_ctx = self._sql_tables(ctx, for_write=for_write, action=action)
        return sql.format(**tables), route_ctx

    def _execute_routed_sql(self, conn, sql, params=(), ctx=None, *, for_write=False, action="trade"):
        formatted, route_ctx = self._format_routed_sql(sql, ctx, for_write=for_write, action=action)
        return conn.execute(formatted, params), route_ctx

    def _shadow_actor_user_id(self, ctx, user_id):
        return shadow_actor_user_id_helper(ctx, user_id)

    def _ensure_shadow_wallet(self, conn, user_id, ctx):
        return ensure_shadow_wallet_helper(self, conn, user_id, ctx)

    def _shadow_wallet_payload(self, row):
        return shadow_wallet_payload_helper(self, row)

    def _wallet_row(self, conn, user_id, ctx=None):
        return wallet_row_helper(self, conn, user_id, ctx=ctx)

    def _wallet_payload(self, conn, user_id, ctx=None):
        return wallet_payload_helper(self, conn, user_id, ctx=ctx)

    def _shadow_existing_ledger_row(self, conn, idempotency_key):
        return shadow_existing_ledger_row_helper(self, conn, idempotency_key)

    def _shadow_last_ledger_hash(self, conn):
        return shadow_last_ledger_hash_helper(self, conn)

    def _shadow_record_transaction(self, conn, *, ctx, user_id, currency_type, direction, amount, action_type, reference_type=None, reference_id=None, idempotency_key=None, reason="", public_metadata=None, private_metadata=None, sensitive_metadata_encrypted="", actor=None, risk_flag="none", risk_score=0):
        return shadow_record_transaction_helper(
            self,
            conn,
            ctx=ctx,
            user_id=user_id,
            currency_type=currency_type,
            direction=direction,
            amount=amount,
            action_type=action_type,
            reference_type=reference_type,
            reference_id=reference_id,
            idempotency_key=idempotency_key,
            reason=reason,
            public_metadata=public_metadata,
            private_metadata=private_metadata,
            sensitive_metadata_encrypted=sensitive_metadata_encrypted,
            actor=actor,
            risk_flag=risk_flag,
            risk_score=risk_score,
        )

    def _runtime_market_sort_key(self, item):
        symbol = str((item or {}).get("symbol") if isinstance(item, dict) else item or "").strip().upper()
        sort_order = (item or {}).get("sort_order") if isinstance(item, dict) else None
        try:
            return (int(sort_order or 9999), symbol)
        except Exception:
            return (9999, symbol)

    def _display_symbol_from_parts(self, *, base_asset="", quote_currency="", display_quote_currency=""):
        base = str(base_asset or "").strip().upper()
        quote = str(display_quote_currency or quote_currency or "").strip().upper()
        return f"{base}/{quote}" if base and quote else ""

    def _registry_market_row(self, conn, value, *, include_disabled=True):
        symbol = self._normalize_market_symbol_on_conn(conn, value, include_disabled=include_disabled)
        if not symbol:
            return None
        query = "SELECT * FROM trading_markets_registry WHERE symbol=?"
        params = [symbol]
        if not include_disabled:
            query += " AND enabled=1"
        return conn.execute(query, params).fetchone()

    def _normalize_market_symbol_on_conn(self, conn, value, *, include_disabled=True):
        rows = conn.execute(
            """
            SELECT symbol, base_asset, quote_asset, display_quote_currency, display_name, enabled
            FROM trading_markets_registry
            """
        ).fetchall()
        return normalize_market_symbol_from_rows(
            rows,
            value,
            include_disabled=include_disabled,
            display_symbol_from_parts=self._display_symbol_from_parts,
        )

    def normalize_market_symbol(self, value, *, include_disabled=True):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._normalize_market_symbol_on_conn(conn, value, include_disabled=include_disabled)
        finally:
            conn.close()

    def _market_provider_mappings(self, conn, symbol, *, include_disabled=False):
        market = self._registry_market_row(conn, symbol, include_disabled=True)
        if not market:
            return []
        query = """
            SELECT *
            FROM trading_market_provider_mappings
            WHERE market_id=?
        """
        params = [int(market["id"])]
        if not include_disabled:
            query += " AND enabled=1"
        query += " ORDER BY priority ASC, id ASC"
        return conn.execute(query, params).fetchall()

    def _market_provider_ids_from_mappings(self, rows, *, support_field=None):
        return market_provider_ids_from_mappings(rows, support_field=support_field)

    def _market_provider_id_on_conn(self, conn, symbol, provider):
        provider_key = str(provider or "").strip()
        if not provider_key:
            return ""
        mapping = next(
            (
                row for row in self._market_provider_mappings(conn, symbol)
                if str(row["provider"] or "").strip() == provider_key
            ),
            None,
        )
        if mapping and int(mapping["enabled"] or 0):
            return str(mapping["provider_symbol"] or "").strip()
        return ""

    def market_provider_id(self, symbol, provider, *, conn=None):
        if conn is not None:
            return self._market_provider_id_on_conn(conn, symbol, provider)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._market_provider_id_on_conn(conn, symbol, provider)
        finally:
            conn.close()

    def _market_supports_live_price_on_conn(self, conn, symbol):
        market = self._registry_market_row(conn, symbol, include_disabled=True)
        if not market or not int(market["live_price_enabled"] or 0):
            return False
        return market_supports_mapping_rows(
            self._market_provider_mappings(conn, symbol),
            support_field="supports_ticker",
        )

    def _market_supports_reference_price_on_conn(self, conn, symbol):
        market = self._registry_market_row(conn, symbol, include_disabled=True)
        if not market or not int(market["reference_price_enabled"] or 0):
            return False
        return market_supports_mapping_rows(
            self._market_provider_mappings(conn, symbol),
            support_field="supports_candles",
        )

    def _market_supports_btc_trade_on_conn(self, conn, symbol):
        market = self._registry_market_row(conn, symbol, include_disabled=True)
        return bool(market and int(market["btc_trade_enabled"] or 0))

    def market_supports_reference_price(self, symbol):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._market_supports_reference_price_on_conn(conn, symbol)
        finally:
            conn.close()

    def market_supports_btc_trade(self, symbol):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._market_supports_btc_trade_on_conn(conn, symbol)
        finally:
            conn.close()

    def _list_live_price_market_symbols(self, conn):
        rows = conn.execute("SELECT symbol FROM trading_markets_registry WHERE enabled=1 ORDER BY sort_order ASC, symbol ASC").fetchall()
        return [str(row["symbol"] or "").strip().upper() for row in rows if self._market_supports_live_price_on_conn(conn, row["symbol"])]

    def _list_reference_price_market_symbols(self, conn):
        rows = conn.execute("SELECT symbol FROM trading_markets_registry WHERE enabled=1 ORDER BY sort_order ASC, symbol ASC").fetchall()
        return [str(row["symbol"] or "").strip().upper() for row in rows if self._market_supports_reference_price_on_conn(conn, row["symbol"])]

    def _market_display_symbol_on_conn(self, conn, symbol, quote_currency=None):
        market = self._registry_market_row(conn, symbol, include_disabled=True)
        if market:
            return market_display_symbol_from_registry_row(
                market,
                display_symbol_from_parts=self._display_symbol_from_parts,
            )
        return fallback_market_display_symbol(symbol, quote_currency=quote_currency)

    def market_display_symbol(self, symbol, quote_currency=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._market_display_symbol_on_conn(conn, symbol, quote_currency=quote_currency)
        finally:
            conn.close()

    def _market(self, conn, symbol):
        row = conn.execute(
            "SELECT * FROM trading_markets WHERE symbol=?",
            (self._normalize_market_symbol_on_conn(conn, symbol),),
        ).fetchone()
        if not row:
            raise ValueError("market not found")
        if not int(row["enabled"] or 0) or not int(row["spot_enabled"] or 0):
            raise ValueError("spot trading is disabled for this market")
        if row["execution_mode"] != "house_counterparty":
            raise ValueError("only house_counterparty execution is enabled in v1")
        return dict(row)

    def _is_market_boot_ready(self, market):
        """Boot-ready gate (2026-05-06).

        ``trading_markets.live_price_confirmed_at`` is NULL until the market
        has survived warmup with at least two stable live quotes. Until that
        timestamp is set, any operation that takes price as truth (spot order,
        margin open, liquidation, bot decision) MUST refuse — otherwise we
        risk acting either on the seed default that ``manual_price_points`` was
        first inserted with, or on a single unconfirmed startup spike.
        """
        if not isinstance(market, dict) and "live_price_confirmed_at" not in (getattr(market, "keys", lambda: ())()):
            return False
        try:
            confirmed_at = market["live_price_confirmed_at"]
        except (KeyError, IndexError):
            confirmed_at = None
        return bool(str(confirmed_at or "").strip())

    def _assert_market_boot_ready(self, market, *, usage="trading"):
        if not self._is_market_boot_ready(market):
            symbol = ""
            try:
                symbol = str(market["symbol"])
            except Exception:
                pass
            raise ValueError(
                f"market {symbol or '?'} 尚未收到任何即時價格更新，{usage} 暫停以避免使用啟動時的預設參考價"
            )

    def _validate_market_quantity_constraints(self, market, quantity_units):
        quantity_units = int(quantity_units or 0)
        if quantity_units <= 0:
            raise ValueError("quantity must be positive")
        quantity_decimal = Decimal(quantity_units) / Decimal(ASSET_SCALE)
        min_order_size = Decimal(str(market["min_order_size"] if "min_order_size" in market.keys() else "0.00000001"))
        max_order_size = Decimal(str(market["max_order_size"] if "max_order_size" in market.keys() else "1000000"))
        if quantity_decimal < min_order_size:
            raise ValueError(f"quantity below minimum {_decimal_text(min_order_size)}")
        if quantity_decimal > max_order_size:
            raise ValueError(f"quantity above maximum {_decimal_text(max_order_size)}")
        quantity_precision = int(market["quantity_precision"] if "quantity_precision" in market.keys() else 8)
        precision_step_units = _quantity_step_units_from_precision(quantity_precision)
        if precision_step_units > 1 and quantity_units % precision_step_units != 0:
            raise ValueError(f"quantity exceeds quantity precision {quantity_precision}")
        lot_size = Decimal(str(market["lot_size"] if "lot_size" in market.keys() else "0.00000001"))
        lot_units = max(1, _decimal_units(lot_size))
        if lot_units > 1 and quantity_units % lot_units != 0:
            raise ValueError(f"quantity must align with lot size {units_to_quantity(lot_units)}")

    def _validate_market_limit_price(self, market, raw_price):
        price_decimal = _to_decimal(raw_price, name="limit_price_points", minimum=0.00000001)
        price_precision = int(market["price_precision"] if "price_precision" in market.keys() else 8)
        quantum = Decimal(1).scaleb(-max(0, min(price_precision, 8)))
        if price_decimal != price_decimal.quantize(quantum, rounding=ROUND_HALF_UP):
            raise ValueError(f"limit price exceeds price precision {price_precision}")
        tick_size = Decimal(str(market["tick_size"] if "tick_size" in market.keys() else "0.00000001"))
        tick_units = max(1, _decimal_units(tick_size))
        price_units = max(1, _decimal_units(price_decimal))
        if tick_units > 1 and price_units % tick_units != 0:
            raise ValueError(f"limit price must align with tick size {_decimal_text(tick_size)}")
        return float(price_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))

    def _position(self, conn, user_id, symbol, *, ctx=None):
        now = _now()
        positions_table, route_ctx = self._resolve_table("positions", ctx, action="position-read")
        if positions_table == "test_shadow_positions":
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {positions_table}
                    (tester_user_id, user_id, market_symbol, quantity_units, locked_quantity_units, avg_cost_points, updated_at)
                VALUES (?, ?, ?, 0, 0, 0, ?)
                """,
                (self._shadow_actor_user_id(route_ctx, user_id), int(user_id), symbol, now),
            )
        else:
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {positions_table}
                    (user_id, market_symbol, quantity_units, locked_quantity_units, avg_cost_points, updated_at)
                VALUES (?, ?, 0, 0, 0, ?)
                """,
                (int(user_id), symbol, now),
            )
        return conn.execute(
            f"SELECT * FROM {positions_table} WHERE user_id=? AND market_symbol=?",
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
        return funding_pool_outstanding_principal(lent=lent, repaid=repaid)

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
        return grid_fee_rate_percent(base_fee_rate_percent, settings)

    def _funding_pool_payload(self, conn, *, requested_principal=0, borrowed_asset=None):
        reserve = self._reserve(conn)
        settings = self._settings_payload(conn)
        balance = int(reserve["balance_points"] or 0)
        outstanding = self._funding_pool_outstanding_principal(conn)
        borrowed_asset = str(borrowed_asset or "POINTS").strip().upper() or "POINTS"
        base_apr = self._borrow_apr_percent_for_asset(settings, asset_symbol=borrowed_asset)
        raw_pressure = settings.get("borrow_interest_pool_pressure_multiplier")
        pressure = float(TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER if raw_pressure is None else raw_pressure)
        payload = funding_pool_payload(
            balance=balance,
            outstanding=outstanding,
            requested_principal=requested_principal,
            borrowed_asset=borrowed_asset,
            base_apr=base_apr,
            pressure=pressure,
            initial_points=TRADING_FUNDING_POOL_INITIAL_POINTS,
            daily_from_apr=_daily_percent_from_apr,
            apr_from_daily=_apr_percent_from_daily,
        )
        return payload

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

    def _ledger(self, conn, *, ctx=None, **kwargs):
        ledger_table, route_ctx = self._resolve_table("points_ledger", ctx, action="ledger-write")
        if ledger_table == "test_shadow_ledger":
            return self._shadow_record_transaction(conn, ctx=route_ctx, **kwargs)
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
        return order_payload(row, units_to_quantity=units_to_quantity)

    def _bot_payload(self, row):
        return bot_payload(
            row,
            bot_max_runs_from_storage=_bot_max_runs_from_storage,
            bot_max_runs_has_remaining=_bot_max_runs_has_remaining,
            now_text=_now,
            market_display_symbol=self.market_display_symbol,
            json_loads=_json_loads,
        )

    def _bot_run_payload(self, row):
        return bot_run_payload(row)

    def _market_payload(self, row):
        return market_payload(
            row,
            json_loads=_json_loads,
            display_symbol_from_parts=self._display_symbol_from_parts,
        )

    def _settings_payload(self, conn):
        return settings_payload_helper(self, conn)
    def get_root_settings(self):
        return get_root_settings_helper(self)
    def get_max_backtest_candles(self, conn=None):
        return get_max_backtest_candles_helper(self, conn=conn)
    def get_backtest_capacity_time_budget_seconds(self, conn=None):
        return get_backtest_capacity_time_budget_seconds_helper(self, conn=conn)
    def get_backtest_capacity_measurement(self, conn=None):
        return get_backtest_capacity_measurement_helper(self, conn=conn)
    def record_backtest_capacity_measurement(
        self,
        *,
        measured_capacity_min,
        measured_capacity_max,
        measured_at,
        bottleneck_strategy="",
        fastest_strategy="",
        actor_id="system",
        seed_default_cap=True,
    ):
        return record_backtest_capacity_measurement_helper(
            self,
            measured_capacity_min=measured_capacity_min,
            measured_capacity_max=measured_capacity_max,
            measured_at=measured_at,
            bottleneck_strategy=bottleneck_strategy,
            fastest_strategy=fastest_strategy,
            actor_id=actor_id,
            seed_default_cap=seed_default_cap,
        )
    def update_root_settings(self, *, actor, settings=None, markets=None):
        return update_root_settings_helper(self, actor=actor, settings=settings, markets=markets)
    def _market_registry_audit(self, conn, *, actor=None, action="", market_symbol="", before=None, after=None):
        return market_registry_audit_helper(
            self,
            conn,
            actor=actor,
            action=action,
            market_symbol=market_symbol,
            before=before,
            after=after,
        )

    def _market_registry_payload(self, conn, registry_row):
        return market_registry_payload_helper(
            self,
            conn,
            registry_row,
            registry_default_market_payload=_registry_default_market_payload,
        )

    def _market_provider_mapping_payload(self, row):
        return market_provider_mapping_payload_helper(row)

    def _validate_market_registry_payload(self, payload, *, existing=None):
        return validate_market_registry_payload_helper(payload, existing=existing)

    def _validate_market_provider_mapping_payload(self, payload, *, existing=None):
        return validate_market_provider_mapping_payload_helper(payload, existing=existing)

    def _probe_market_registry_on_conn(self, conn, registry_row):
        return probe_market_registry_on_conn_helper(self, conn, registry_row)

    def _persist_market_registry_probe(self, conn, registry_row):
        return persist_market_registry_probe_helper(self, conn, registry_row)

    def list_market_registry(self, *, include_disabled=True):
        return list_market_registry_helper(self, include_disabled=include_disabled)

    def get_market_provider_registry(self, *, market_id):
        return get_market_provider_registry_helper(self, market_id=market_id)

    def create_market_registry(self, *, actor, payload):
        return create_market_registry_helper(
            self,
            actor=actor,
            payload=payload,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def update_market_registry(self, *, actor, market_id, payload):
        return update_market_registry_helper(
            self,
            actor=actor,
            market_id=market_id,
            payload=payload,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def disable_market_registry(self, *, actor, market_id):
        return disable_market_registry_helper(
            self,
            actor=actor,
            market_id=market_id,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def create_market_provider_mapping(self, *, actor, market_id, payload):
        return create_market_provider_mapping_helper(
            self,
            actor=actor,
            market_id=market_id,
            payload=payload,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def update_market_provider_mapping(self, *, actor, market_id, mapping_id, payload):
        return update_market_provider_mapping_helper(
            self,
            actor=actor,
            market_id=market_id,
            mapping_id=mapping_id,
            payload=payload,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def disable_market_provider_mapping(self, *, actor, market_id, mapping_id):
        return disable_market_provider_mapping_helper(
            self,
            actor=actor,
            market_id=market_id,
            mapping_id=mapping_id,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def probe_market_registry(self, *, market_id):
        return probe_market_registry_helper(
            self,
            market_id=market_id,
            sync_runtime_markets=_sync_registry_markets_to_runtime,
        )

    def _live_price_symbol(self, market_symbol, *, conn=None):
        symbol = self._normalize_market_symbol_on_conn(conn, market_symbol) if conn is not None else self.normalize_market_symbol(market_symbol)
        if conn is not None:
            return self._market_provider_id_on_conn(conn, symbol, "binance_public_api")
        return self.market_provider_id(symbol, "binance_public_api")

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

    def _call_with_optional_conn(self, func, *args, conn=None, **kwargs):
        if conn is None:
            return func(*args, **kwargs)
        try:
            parameters = inspect.signature(func).parameters
        except Exception:
            parameters = {}
        if "conn" in parameters:
            return func(*args, conn=conn, **kwargs)
        return func(*args, **kwargs)

    def _provider_ticker_with_fallback(self, source, market_symbol, *, settings, http_fetcher, conn=None):
        return provider_ticker_with_fallback_helper(
            self,
            source,
            market_symbol,
            settings=settings,
            http_fetcher=http_fetcher,
            conn=conn,
        )

    def _provider_orderbook_with_fallback(self, source, market_symbol, *, settings, depth_levels, band_percent, request_limit, http_fetcher, book_getter, conn=None):
        return provider_orderbook_with_fallback_helper(
            self,
            source,
            market_symbol,
            settings=settings,
            depth_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            http_fetcher=http_fetcher,
            book_getter=book_getter,
            conn=conn,
        )

    def _fetch_binance_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        symbol = self.market_provider_id(market_symbol, "binance_public_api", conn=conn)
        if not symbol:
            raise ValueError("binance price is not supported for this market")
        def http_fetcher():
            payload, fetch_meta = self._fetch_json_url(
                f"{BINANCE_TICKER_URL}?{urlencode({'symbol': symbol})}",
                timeout=5,
                with_meta=True,
            )
            price = payload.get("price") if isinstance(payload, dict) else None
            return self._price_points_from_float(price, source="binance_public_api"), fetch_meta
        price_points, meta = self._provider_ticker_with_fallback("binance_public_api", market_symbol, settings=settings or {}, http_fetcher=http_fetcher, conn=conn)
        return (price_points, meta) if with_meta else price_points

    def _fetch_okx_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        instrument = self.market_provider_id(market_symbol, "okx_public_api", conn=conn)
        if not instrument:
            raise ValueError("okx price is not supported for this market")
        def http_fetcher():
            payload, fetch_meta = self._fetch_json_url(
                f"{OKX_TICKER_URL}?{urlencode({'instId': instrument})}",
                timeout=5,
                user_agent="hackme_web/1.0 trading-price okx",
                with_meta=True,
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            ticker = data[0] if isinstance(data, list) and data else None
            price = ticker.get("last") if isinstance(ticker, dict) else None
            return self._price_points_from_float(price, source="okx_public_api"), fetch_meta
        price_points, meta = self._provider_ticker_with_fallback("okx_public_api", market_symbol, settings=settings or {}, http_fetcher=http_fetcher, conn=conn)
        return (price_points, meta) if with_meta else price_points

    def _fetch_coinbase_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        product_id = self.market_provider_id(market_symbol, "coinbase_exchange", conn=conn)
        if not product_id:
            raise ValueError("coinbase price is not supported for this market")
        def http_fetcher():
            payload, fetch_meta = self._fetch_json_url(
                COINBASE_TICKER_URL_TEMPLATE.format(product_id=product_id),
                timeout=5,
                user_agent="hackme_web/1.0 trading-price coinbase",
                with_meta=True,
            )
            price = payload.get("price") if isinstance(payload, dict) else None
            return self._price_points_from_float(price, source="coinbase_exchange"), fetch_meta
        price_points, meta = self._provider_ticker_with_fallback("coinbase_exchange", market_symbol, settings=settings or {}, http_fetcher=http_fetcher, conn=conn)
        return (price_points, meta) if with_meta else price_points

    def _fetch_kraken_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        pair = self.market_provider_id(market_symbol, "kraken_public_api", conn=conn)
        if not pair:
            raise ValueError("kraken price is not supported for this market")
        def http_fetcher():
            payload, fetch_meta = self._fetch_json_url(
                f"{KRAKEN_TICKER_URL}?{urlencode({'pair': pair})}",
                timeout=5,
                user_agent="hackme_web/1.0 trading-price kraken",
                with_meta=True,
            )
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError(f"kraken ticker error: {payload.get('error') if isinstance(payload, dict) else 'invalid payload'}")
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            ticker = next(iter(result.values()), None)
            close = ticker.get("c", [None])[0] if isinstance(ticker, dict) else None
            return self._price_points_from_float(close, source="kraken_public_api"), fetch_meta
        price_points, meta = self._provider_ticker_with_fallback("kraken_public_api", market_symbol, settings=settings or {}, http_fetcher=http_fetcher, conn=conn)
        return (price_points, meta) if with_meta else price_points

    def _fetch_gemini_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        symbol = self.market_provider_id(market_symbol, "gemini_public_api", conn=conn)
        if not symbol:
            raise ValueError("gemini price is not supported for this market")
        payload, fetch_meta = self._fetch_json_url(
            GEMINI_TICKER_URL_TEMPLATE.format(symbol=symbol),
            timeout=5,
            user_agent="hackme_web/1.0 trading-price gemini",
            with_meta=True,
        )
        price = payload.get("close") or payload.get("last") if isinstance(payload, dict) else None
        price_points = self._price_points_from_float(price, source="gemini_public_api")
        meta = self._provider_transport_meta("gemini_public_api", market_symbol, settings=settings or {}, transport="http_polling", fetched_at=fetch_meta.get("fetched_at"), latency_ms=fetch_meta.get("latency_ms"), conn=conn)
        return (price_points, meta) if with_meta else price_points

    def _fetch_bitstamp_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        pair = self.market_provider_id(market_symbol, "bitstamp_public_api", conn=conn)
        if not pair:
            raise ValueError("bitstamp price is not supported for this market")
        payload, fetch_meta = self._fetch_json_url(
            BITSTAMP_TICKER_URL_TEMPLATE.format(pair=pair),
            timeout=5,
            user_agent="hackme_web/1.0 trading-price bitstamp",
            with_meta=True,
        )
        price = payload.get("last") if isinstance(payload, dict) else None
        price_points = self._price_points_from_float(price, source="bitstamp_public_api")
        meta = self._provider_transport_meta("bitstamp_public_api", market_symbol, settings=settings or {}, transport="http_polling", fetched_at=fetch_meta.get("fetched_at"), latency_ms=fetch_meta.get("latency_ms"), conn=conn)
        return (price_points, meta) if with_meta else price_points

    def _fetch_coingecko_price_points(self, market_symbol, *, settings=None, with_meta=False, conn=None):
        coin_id = self.market_provider_id(market_symbol, "coingecko_simple_price", conn=conn)
        if not coin_id:
            raise ValueError("coingecko price is not supported for this market")
        payload, fetch_meta = self._fetch_json_url(
            f"{COINGECKO_SIMPLE_PRICE_URL}?{urlencode({'ids': coin_id, 'vs_currencies': 'usd', 'include_last_updated_at': 'true'})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-price coingecko",
            with_meta=True,
        )
        coin = payload.get(coin_id) if isinstance(payload, dict) else None
        price = coin.get("usd") if isinstance(coin, dict) else None
        price_points = self._price_points_from_float(price, source="coingecko_simple_price")
        meta = self._provider_transport_meta("coingecko_simple_price", market_symbol, settings=settings or {}, transport="http_polling", fetched_at=fetch_meta.get("fetched_at"), latency_ms=fetch_meta.get("latency_ms"), conn=conn)
        return (price_points, meta) if with_meta else price_points

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

    def _price_stream_ws_enabled(self, settings):
        return bool((settings or {}).get("price_stream_ws_enabled", True))

    def _price_stream_ws_stale_seconds(self, settings):
        try:
            return int((settings or {}).get("price_stream_ws_stale_seconds") or DEFAULT_PRICE_STREAM_WS_STALE_SECONDS)
        except Exception:
            return DEFAULT_PRICE_STREAM_WS_STALE_SECONDS

    def _price_stream_provider_state(self, source, market_symbol, *, settings, conn=None):
        return price_stream_provider_state_helper(self, source, market_symbol, settings=settings, conn=conn)

    def _provider_transport_meta(self, source, market_symbol, *, settings, stream_state=None, transport="http_polling", fetched_at="", latency_ms=0.0, fallback=False, exclusion_reason="", conn=None):
        return provider_transport_meta_helper(
            self,
            source,
            market_symbol,
            settings=settings,
            stream_state=stream_state,
            transport=transport,
            fetched_at=fetched_at,
            latency_ms=latency_ms,
            fallback=fallback,
            exclusion_reason=exclusion_reason,
            conn=conn,
        )

    def _resolve_stream_ticker_snapshot(self, source, market_symbol, *, settings, conn=None):
        return resolve_stream_ticker_snapshot_helper(self, source, market_symbol, settings=settings, conn=conn)

    def _resolve_stream_orderbook_snapshot(self, source, market_symbol, *, settings, conn=None):
        return resolve_stream_orderbook_snapshot_helper(self, source, market_symbol, settings=settings, conn=conn)

    def _provider_quantity_unit_info(self, source):
        return provider_quantity_unit_info_helper(self, source)

    def _price_fusion_warning(self, code, message, *, severity="warning"):
        return price_fusion_warning_helper(code, message, severity=severity)

    def _append_price_fusion_warning(self, warnings, code, message, *, severity="warning"):
        return append_price_fusion_warning_helper(self, warnings, code, message, severity=severity)

    def _primary_price_fusion_warning(self, warnings):
        return primary_price_fusion_warning_helper(warnings)

    def _price_usage_label(self, price_type):
        return price_usage_label(price_type)

    def _price_source_label(self, source):
        return price_source_label(source, PRICE_PROVIDER_LABELS, fused_price_source=FUSED_PRICE_SOURCE)

    def _price_context_confidence(self, *, price_type, source, health, degraded, stale, provider_count, high_risk_blocked):
        return price_context_confidence(
            price_type=price_type,
            source=source,
            health=health,
            degraded=degraded,
            stale=stale,
            provider_count=provider_count,
            high_risk_blocked=high_risk_blocked,
            minimum_provider_count=DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT,
        )

    def _price_context_risk_grade_usable(
        self,
        *,
        price_type,
        source,
        health,
        degraded,
        stale,
        provider_count,
        high_risk_blocked,
        fallback,
        synthetic_test_provider=False,
    ):
        return price_context_risk_grade_usable(
            price_type=price_type,
            source=source,
            health=health,
            degraded=degraded,
            stale=stale,
            provider_count=provider_count,
            high_risk_blocked=high_risk_blocked,
            fallback=fallback,
            synthetic_test_provider=synthetic_test_provider,
        )

    def _build_price_context(self, *, market_symbol, price_type, price_points, price_source, price_meta):
        return build_price_context_helper(
            self,
            market_symbol=market_symbol,
            price_type=price_type,
            price_points=price_points,
            price_source=price_source,
            price_meta=price_meta,
        )

    def _attach_market_price_contexts(self, market, *, reference_context, risk_grade_context):
        item = dict(market or {})
        item["reference_price_points"] = reference_context.get("price_points")
        item["risk_grade_price_points"] = risk_grade_context.get("price_points")
        item["reference_price_context"] = reference_context
        item["risk_grade_price_context"] = risk_grade_context
        return item

    def _stored_market_price_contexts(self, market):
        return stored_market_price_contexts_helper(self, market)

    def _price_fusion_effective_score(self, snapshot):
        return price_fusion_effective_score(snapshot)

    def _price_fusion_reference_score(self, snapshot):
        return price_fusion_reference_score(snapshot)

    def _price_fusion_warning_is_degrading(self, warning):
        code = str((warning or {}).get("code") or "").strip()
        if not code:
            return False
        return code not in {
            "provider_coverage_partial",
            "provider_weight_cap_applied",
        }

    def _price_fusion_exclusion_is_degrading(self, exclusion):
        reason = str((exclusion or {}).get("reason") or "").strip()
        if not reason:
            return False
        return reason not in {
            "manual_weight_zero",
        }

    def _transport_state_from_provider_rows(self, provider_rows, *, warnings=None, degraded=False, conservative_mode=False, min_provider_count=0, ws_enabled=True):
        return transport_state_from_provider_rows_helper(
            self,
            provider_rows,
            warnings=warnings,
            degraded=degraded,
            conservative_mode=conservative_mode,
            min_provider_count=min_provider_count,
            ws_enabled=ws_enabled,
        )

    def _assert_price_meta_allows_high_risk_use(self, conn, *, actor=None, market_symbol="", usage="", price_meta=None):
        if market_symbol:
            market_row = conn.execute(
                "SELECT allow_risk_grade_usage FROM trading_markets WHERE symbol=?",
                (self._normalize_market_symbol_on_conn(conn, market_symbol),),
            ).fetchone()
            if market_row and not int(market_row["allow_risk_grade_usage"] or 0):
                raise ValueError(f"{usage or 'high-risk trading action'} is disabled for this market")
        meta = price_meta or {}
        if bool(meta.get("synthetic_test_provider")):
            return
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
        return provider_depth_request_limit(
            source,
            depth_levels,
            default_depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS,
        )

    def _parse_orderbook_side(self, rows, *, max_levels):
        return parse_orderbook_side(rows, max_levels=max_levels)

    def _depth_notional_snapshot(self, bids, asks, *, max_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        return depth_notional_snapshot(
            bids,
            asks,
            max_levels=max_levels,
            band_percent=band_percent,
        )

    def _depth_notional_score(self, bids, asks, *, max_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT):
        return depth_notional_score(
            bids,
            asks,
            max_levels=max_levels,
            band_percent=band_percent,
        )

    def _build_orderbook_snapshot(self, *, source, bids, asks, fetch_meta=None, max_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, request_limit=None, transport_meta=None):
        return build_orderbook_snapshot_helper(
            self,
            source=source,
            bids=bids,
            asks=asks,
            fetch_meta=fetch_meta,
            max_levels=max_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            transport_meta=transport_meta,
        )

    def _normalize_orderbook_fetch_result(self, fetch_result):
        if isinstance(fetch_result, tuple) and len(fetch_result) == 2:
            payload, fetch_meta = fetch_result
            return payload, fetch_meta if isinstance(fetch_meta, dict) else {}
        return fetch_result, {}

    def _okx_http_book_getter(self, payload):
        data = payload.get("data") if isinstance(payload, dict) else None
        book = data[0] if isinstance(data, list) and data else None
        if not isinstance(book, dict):
            raise ValueError("okx order book payload is invalid")
        return book.get("bids") or [], book.get("asks") or []

    def _kraken_http_book_getter(self, payload):
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(f"kraken depth error: {payload.get('error') if isinstance(payload, dict) else 'invalid payload'}")
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        book = next(iter(result.values()), None)
        if not isinstance(book, dict):
            raise ValueError("kraken order book payload is invalid")
        return book.get("bids") or [], book.get("asks") or []

    def _fetch_binance_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, settings=None, conn=None):
        symbol = self.market_provider_id(market_symbol, "binance_public_api", conn=conn)
        if not symbol:
            raise ValueError("binance order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("binance_public_api", depth_levels)
        return self._provider_orderbook_with_fallback(
            "binance_public_api",
            market_symbol,
            settings=settings or {},
            depth_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            http_fetcher=lambda: self._normalize_orderbook_fetch_result(self._fetch_json_url(
                f"{BINANCE_DEPTH_URL}?{urlencode({'symbol': symbol, 'limit': request_limit})}",
                timeout=5,
                with_meta=True,
            )),
            book_getter=lambda payload: ((payload or {}).get("bids") or [], (payload or {}).get("asks") or []),
            conn=conn,
        )

    def _fetch_okx_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, settings=None, conn=None):
        instrument = self.market_provider_id(market_symbol, "okx_public_api", conn=conn)
        if not instrument:
            raise ValueError("okx order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("okx_public_api", depth_levels)
        return self._provider_orderbook_with_fallback(
            "okx_public_api",
            market_symbol,
            settings=settings or {},
            depth_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            http_fetcher=lambda: self._normalize_orderbook_fetch_result(self._fetch_json_url(
                f"{OKX_BOOKS_URL}?{urlencode({'instId': instrument, 'sz': request_limit})}",
                timeout=5,
                user_agent="hackme_web/1.0 trading-depth okx",
                with_meta=True,
            )),
            book_getter=self._okx_http_book_getter,
            conn=conn,
        )

    def _fetch_coinbase_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, settings=None, conn=None):
        product_id = self.market_provider_id(market_symbol, "coinbase_exchange", conn=conn)
        if not product_id:
            raise ValueError("coinbase order book is not supported for this market")
        return self._provider_orderbook_with_fallback(
            "coinbase_exchange",
            market_symbol,
            settings=settings or {},
            depth_levels=depth_levels,
            band_percent=band_percent,
            request_limit=2,
            http_fetcher=lambda: self._normalize_orderbook_fetch_result(self._fetch_json_url(
                f"{COINBASE_BOOK_URL_TEMPLATE.format(product_id=product_id)}?{urlencode({'level': 2})}",
                timeout=5,
                user_agent="hackme_web/1.0 trading-depth coinbase",
                with_meta=True,
            )),
            book_getter=lambda payload: ((payload or {}).get("bids") or [], (payload or {}).get("asks") or []),
            conn=conn,
        )

    def _fetch_kraken_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, settings=None, conn=None):
        pair = self.market_provider_id(market_symbol, "kraken_public_api", conn=conn)
        if not pair:
            raise ValueError("kraken order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("kraken_public_api", depth_levels)
        return self._provider_orderbook_with_fallback(
            "kraken_public_api",
            market_symbol,
            settings=settings or {},
            depth_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            http_fetcher=lambda: self._normalize_orderbook_fetch_result(self._fetch_json_url(
                f"{KRAKEN_DEPTH_URL}?{urlencode({'pair': pair, 'count': request_limit})}",
                timeout=5,
                user_agent="hackme_web/1.0 trading-depth kraken",
                with_meta=True,
            )),
            book_getter=self._kraken_http_book_getter,
            conn=conn,
        )

    def _fetch_gemini_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, settings=None, conn=None):
        symbol = self.market_provider_id(market_symbol, "gemini_public_api", conn=conn)
        if not symbol:
            raise ValueError("gemini order book is not supported for this market")
        request_limit = self._provider_depth_request_limit("gemini_public_api", depth_levels)
        payload, fetch_meta = self._normalize_orderbook_fetch_result(self._fetch_json_url(
            f"{GEMINI_BOOK_URL_TEMPLATE.format(symbol=symbol)}?{urlencode({'limit_bids': request_limit, 'limit_asks': request_limit})}",
            timeout=5,
            user_agent="hackme_web/1.0 trading-depth gemini",
            with_meta=True,
        ))
        return self._build_orderbook_snapshot(
            source="gemini_public_api",
            bids=[[row.get("price"), row.get("amount")] for row in (payload.get("bids") or []) if isinstance(row, dict)],
            asks=[[row.get("price"), row.get("amount")] for row in (payload.get("asks") or []) if isinstance(row, dict)],
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            transport_meta=self._provider_transport_meta("gemini_public_api", market_symbol, settings=settings or {}, transport="http_polling", fetched_at=fetch_meta.get("fetched_at"), latency_ms=fetch_meta.get("latency_ms"), conn=conn),
        )

    def _fetch_bitstamp_orderbook_snapshot(self, market_symbol, *, depth_levels=DEFAULT_PRICE_FUSION_DEPTH_LEVELS, band_percent=DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, settings=None, conn=None):
        pair = self.market_provider_id(market_symbol, "bitstamp_public_api", conn=conn)
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
            transport_meta=self._provider_transport_meta("bitstamp_public_api", market_symbol, settings=settings or {}, transport="http_polling", fetched_at=fetch_meta.get("fetched_at"), latency_ms=fetch_meta.get("latency_ms"), conn=conn),
        )

    def _price_fusion_manual_weights(self, settings):
        return _normalize_price_fusion_manual_weights((settings or {}).get("price_fusion_manual_weights"))

    def _apply_price_fusion_weight_cap(self, weighted_rows, *, max_single_provider_weight_percent):
        return apply_price_fusion_weight_cap(
            weighted_rows,
            max_single_provider_weight_percent=max_single_provider_weight_percent,
        )

    def _build_price_fusion_weight_model(self, snapshots, *, mode, weight_map, max_single_provider_weight_percent, score_getter):
        return build_price_fusion_weight_model(
            snapshots,
            mode=mode,
            weight_map=weight_map,
            max_single_provider_weight_percent=max_single_provider_weight_percent,
            score_getter=score_getter,
        )

    def _fetch_weighted_fused_price_points(self, market_symbol, *, settings, conn=None):
        return fetch_weighted_fused_price_points_helper(
            self,
            market_symbol,
            settings=settings,
            conn=conn,
        )

    def _default_price_fusion_market_symbol(self, conn):
        rows = conn.execute("SELECT * FROM trading_markets ORDER BY sort_order ASC, symbol ASC").fetchall()
        for row in rows:
            symbol = str(row["symbol"] or "").strip().upper()
            if self._market_supports_live_price_on_conn(conn, symbol):
                return symbol
        catalog_symbols = self._list_live_price_market_symbols(conn)
        return catalog_symbols[0] if catalog_symbols else ""

    def _root_price_fusion_status_on_conn(self, conn, *, market_symbol=""):
        return root_price_fusion_status_on_conn_helper(
            self,
            conn,
            market_symbol=market_symbol,
        )

    def get_root_price_fusion_status(self, *, market_symbol=""):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._root_price_fusion_status_on_conn(conn, market_symbol=market_symbol)
        finally:
            conn.close()

    def get_live_market_quote(self, *, market_symbol=""):
        return get_live_market_quote_helper(self, market_symbol=market_symbol)

    def _fetch_live_price_points(self, market_symbol, *, with_meta=False, settings=None, conn=None):
        return fetch_live_price_points_helper(
            self,
            market_symbol,
            with_meta=with_meta,
            settings=settings,
            conn=conn,
        )

    def _fetch_indicator_candles(self, market_symbol, *, limit=240, interval="15m", conn=None):
        symbol = self._live_price_symbol(market_symbol, conn=conn)
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

    def _recent_price_window(self, market_symbol, *, lookback_seconds=60, since_time_text=None, interval="1m", conn=None):
        return recent_price_window_helper(
            self,
            market_symbol,
            lookback_seconds=lookback_seconds,
            since_time_text=since_time_text,
            interval=interval,
            conn=conn,
        )

    def _workflow_live_context(self, conn, *, market, user_id, observed_price, observed_low=None, observed_high=None):
        return workflow_live_context_helper(
            self,
            conn,
            market=market,
            user_id=user_id,
            observed_price=observed_price,
            observed_low=observed_low,
            observed_high=observed_high,
        )

    def _current_market_price_points(self, conn, market, *, with_meta=False, high_risk=False):
        return current_market_price_points_helper(
            self,
            conn,
            market,
            with_meta=with_meta,
            high_risk=high_risk,
        )

    def _root_sim_account(self, conn, user_id, *, actor=None):
        return root_sim_account_helper(
            self,
            conn,
            user_id,
            actor=actor,
            root_simulated_initial_points=ROOT_SIMULATED_INITIAL_POINTS,
        )

    def _sim_delta(self, conn, user_id, *, balance_delta=0, locked_delta=0):
        return sim_delta_helper(
            self,
            conn,
            user_id,
            balance_delta=balance_delta,
            locked_delta=locked_delta,
            root_simulated_initial_points=ROOT_SIMULATED_INITIAL_POINTS,
        )

    def _is_root_user_id(self, conn, user_id):
        row = conn.execute("SELECT username FROM users WHERE id=?", (int(user_id),)).fetchone()
        return bool(row and row["username"] == "root")

    def _system_actor(self):
        return {"username": "system", "role": "system"}

    def _trial_credit_row(self, conn, user_id):
        return trial_credit_row_helper(self, conn, user_id)
    def _ensure_trial_credit(self, conn, user_id, *, actor=None, allow_reclaim=True):
        return ensure_trial_credit_helper(self, conn, user_id, actor=actor, allow_reclaim=allow_reclaim)
    def _trial_position(self, conn, user_id, symbol):
        return trial_position_helper(self, conn, user_id, symbol)
    def _trial_delta(self, conn, user_id, *, available_delta=0, locked_delta=0, deployed_delta=0, status=None, reclaimed=False):
        return trial_delta_helper(
            self,
            conn,
            user_id,
            available_delta=available_delta,
            locked_delta=locked_delta,
            deployed_delta=deployed_delta,
            status=status,
            reclaimed=reclaimed,
        )
    def _trial_lock_for_buy(self, conn, user_id, total_points):
        return trial_lock_for_buy_helper(self, conn, user_id, total_points)
    def _trial_spend(self, conn, user_id, amount):
        return trial_spend_helper(self, conn, user_id, amount)
    def _trial_deploy(self, conn, user_id, amount):
        return trial_deploy_helper(self, conn, user_id, amount)
    def _trial_unlock(self, conn, user_id, amount):
        return trial_unlock_helper(self, conn, user_id, amount)
    def _set_trial_reclaim_blocked(self, conn, user_id, *, reason):
        return set_trial_reclaim_blocked_helper(self, conn, user_id, reason=reason)
    def _clear_trial_reclaim_blocked(self, conn, user_id):
        return clear_trial_reclaim_blocked_helper(self, conn, user_id)
    def _trial_mark_buy_executed(self, conn, *, user_id, market_symbol, quantity_units, trial_used_points, total_points):
        return trial_mark_buy_executed_helper(
            self,
            conn,
            user_id=user_id,
            market_symbol=market_symbol,
            quantity_units=quantity_units,
            trial_used_points=trial_used_points,
            total_points=total_points,
        )
    def _trial_allocate_sell(self, conn, *, user_id, market_symbol, quantity_units, net_credit_points):
        return trial_allocate_sell_helper(
            self,
            conn,
            user_id=user_id,
            market_symbol=market_symbol,
            quantity_units=quantity_units,
            net_credit_points=net_credit_points,
        )
    def _cancel_trial_reclaim_sell_orders(self, conn, user_id, *, actor, reason, ctx=None):
        return cancel_trial_reclaim_sell_orders_helper(self, conn, user_id, actor=actor, reason=reason, ctx=ctx)
    def _release_trial_margin_collateral(self, conn, user_id, *, collateral_trial, available_delta_if_active=0):
        return release_trial_margin_collateral_helper(
            self,
            conn,
            user_id,
            collateral_trial=collateral_trial,
            available_delta_if_active=available_delta_if_active,
        )
    def _reclaim_trial_credit(self, conn, user_id, *, actor=None, reason="TRIAL_CREDIT_RECLAIM", ctx=None):
        return reclaim_trial_credit_helper(self, conn, user_id, actor=actor, reason=reason, ctx=ctx)
    def _funding_payload(self, conn, user_id):
        return funding_payload_runtime_helper(self, conn, user_id)
    def _position_payload(self, row):
        return position_payload(row, units_to_quantity=units_to_quantity)

    def _position_payload_with_metrics(self, row, *, market=None, realized_points=0, total_fees=0):
        return position_payload_with_metrics_helper(
            self,
            row,
            market=market,
            realized_points=realized_points,
            total_fees=total_fees,
        )
    def _futures_position_payload(self, row):
        return futures_position_payload(row, units_to_quantity=units_to_quantity)

    def _margin_position_payload(self, row):
        return margin_position_payload(
            row,
            units_to_quantity=units_to_quantity,
            to_decimal=_to_decimal,
            apr_percent_from_daily=_apr_percent_from_daily,
            point_micro_scale=POINT_MICRO_SCALE,
            default_interest_interval_hours=DEFAULT_BORROW_INTEREST_INTERVAL_HOURS,
            default_interest_minimum_hours=DEFAULT_BORROW_INTEREST_MINIMUM_HOURS,
            now_text=_now,
            billable_interest_hours_from_elapsed_seconds=_billable_interest_hours_from_elapsed_seconds,
        )

    def _margin_trade_records(self, conn, user_id, *, limit=50):
        return margin_trade_records_helper(self, conn, user_id, limit=limit)
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
        return margin_interest_total_hours(
            row,
            now_text=now_text or _now(),
            billable_interest_hours_from_elapsed_seconds=_billable_interest_hours_from_elapsed_seconds,
            default_interval_hours=DEFAULT_BORROW_INTEREST_INTERVAL_HOURS,
            default_minimum_hours=DEFAULT_BORROW_INTEREST_MINIMUM_HOURS,
        )

    def _margin_interest_due_points(self, row, *, hours):
        return margin_interest_due_points(
            row,
            hours=hours,
            point_micro_scale=POINT_MICRO_SCALE,
            due_micropoints_func=self._margin_interest_due_micropoints,
        )

    def _margin_interest_due_micropoints(self, *, principal, rate_percent, hours):
        return margin_interest_due_micropoints(
            principal=principal,
            rate_percent=rate_percent,
            hours=hours,
            point_micro_scale=POINT_MICRO_SCALE,
        )

    def _margin_interest_points(self, row, now_text=None):
        return margin_interest_points(
            row,
            now_text=now_text or _now(),
            point_micro_scale=POINT_MICRO_SCALE,
            total_hours_func=self._margin_interest_total_hours,
            due_micropoints_func=self._margin_interest_due_micropoints,
        )

    def _accrue_margin_interest(self, conn, position, *, actor=None, now_text=None, ctx=None):
        return accrue_margin_interest_helper(self, conn, position, actor=actor, now_text=now_text, ctx=ctx)

    def _margin_risk_payload(self, conn, position, market=None, *, now_text=None, price_override_points=None, price_source_override=None):
        return margin_risk_payload(
            self,
            conn,
            position,
            market=market,
            now_text=now_text,
            price_override_points=price_override_points,
            price_source_override=price_source_override,
        )

    def _margin_position_payload_with_risk(self, conn, row, *, market=None, risk_overrides=None):
        return margin_position_payload_with_risk(
            self,
            conn,
            row,
            market=market,
            risk_overrides=risk_overrides,
        )

    def _margin_free_margin_points(self, conn, user_id):
        return margin_free_margin_points(self, conn, user_id)

    def _margin_account_payload(self, conn, user_id, rows=None):
        return margin_account_payload(self, conn, user_id, rows)

    def _margin_summary_payload(self, conn, user_id, rows):
        return margin_summary_payload(self, conn, user_id, rows)

    def _margin_liquidation_order_key(self, row):
        return margin_liquidation_order_key(row)

    def _margin_summary_payload_legacy(self, rows):
        return margin_summary_payload_legacy(rows)

    def _fill_payload(self, row, realized=None):
        return fill_payload(
            row,
            units_to_quantity=units_to_quantity,
            json_loads=_json_loads,
            realized=realized,
        )

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
            notice = trade_fill_notification_payload(
                fill,
                units_to_quantity=units_to_quantity,
                decimal_text=_decimal_text,
            )
            create_trading_user_notification(
                conn,
                user_id=fill["user_id"],
                notification_type=notice["notification_type"],
                title=notice["title"],
                body=notice["body"],
                create_notification=create_notification_if_enabled,
            )
        except Exception:
            pass

    def _is_insufficient_error(self, exc):
        lowered = str(exc or "").lower()
        return any(term in lowered for term in ("insufficient", "餘額不足", "積分不足", "資金不足", "持倉不足"))

    def _notify_insufficient_balance(self, *, user_id, market_symbol, side, order_type, quantity, error):
        conn = self.get_db()
        try:
            notice = insufficient_balance_notification_payload(
                market_symbol=market_symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                error=error,
            )
            create_trading_user_notification(
                conn,
                user_id=user_id,
                notification_type=notice["notification_type"],
                title=notice["title"],
                body=notice["body"],
                create_notification=create_notification_if_enabled,
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    def _notify_margin_liquidated(self, conn, *, user_id, position, risk):
        try:
            notice = margin_liquidated_notification_payload(
                position=position,
                risk=risk,
                decimal_text=_decimal_text,
            )
            create_trading_user_notification(
                conn,
                user_id=user_id,
                notification_type=notice["notification_type"],
                title=notice["title"],
                body=notice["body"],
                create_notification=create_notification_if_enabled,
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
        notify_margin_risk_alerts(self, conn, position=position, risk=risk, market=market)

    def list_markets(self, *, include_disabled=False):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            where = "" if include_disabled else "WHERE enabled=1 AND spot_enabled=1"
            rows = conn.execute(f"SELECT * FROM trading_markets {where} ORDER BY sort_order ASC, symbol ASC").fetchall()
            payloads = [self._market_payload(row) for row in rows]
            return sorted(payloads, key=self._runtime_market_sort_key)
        finally:
            conn.close()

    def user_dashboard(self, *, user_id):
        # source-contract breadcrumb:
        # "margin_summary": self._margin_summary_payload(conn, user_id, margin_positions)
        return user_dashboard_helper(self, user_id=user_id)
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
        return legacy_workflow_helper(
            trigger_type=trigger_type,
            trigger_price=trigger_price,
            side=side,
            quantity_text=quantity_text,
            order_type=order_type,
            limit_price=limit_price,
            max_runs=max_runs,
            cooldown_seconds=cooldown_seconds,
        )

    def _validate_workflow(self, value):
        return validate_workflow(
            value,
            validate_workflow_graph_func=self._validate_workflow_graph,
            to_int=_to_int,
            condition_types=WORKFLOW_CONDITION_TYPES,
            action_types=WORKFLOW_ACTION_TYPES,
        )

    def _validate_workflow_graph(self, workflow):
        return validate_workflow_graph(
            workflow,
            to_int=_to_int,
            condition_types=WORKFLOW_CONDITION_TYPES,
            action_types=WORKFLOW_ACTION_TYPES,
            node_types=WORKFLOW_NODE_TYPES,
            ports=WORKFLOW_PORTS,
        )

    def _validate_bot_payload(self, conn, payload):
        return validate_bot_payload_helper(self, conn, payload)

    def list_trading_bots(self, *, actor):
        return list_trading_bots_helper(self, actor=actor)

    def save_trading_bot(self, *, actor, payload, bot_uuid=None):
        return save_trading_bot_helper(self, actor=actor, payload=payload, bot_uuid=bot_uuid)

    def delete_trading_bot(self, *, actor, bot_uuid):
        return delete_trading_bot_helper(self, actor=actor, bot_uuid=bot_uuid)

    def increase_trading_bot_max_runs(self, *, actor, bot_uuid, delta):
        return increase_trading_bot_max_runs_helper(self, actor=actor, bot_uuid=bot_uuid, delta=delta)

    # ── Grid Trading Bot ────────────────────────────────────────────────────

    def _grid_levels(self, lower, upper, count, spacing_mode="arithmetic"):
        return grid_levels(lower, upper, count, spacing_mode)

    def _grid_quantity_units(self, amount_points, price_points):
        return grid_quantity_units(amount_points, price_points)

    def _grid_preview_fee_rates(self, market, settings, *, order_mode="maker"):
        return grid_preview_fee_rates(market, settings, order_mode=order_mode)

    def _grid_preview_risk(self, *, min_net_spread_percent, break_even_spread_percent, spacing_percent):
        return grid_preview_risk(
            min_net_spread_percent=min_net_spread_percent,
            break_even_spread_percent=break_even_spread_percent,
            spacing_percent=spacing_percent,
        )

    def _grid_preview_summary(self, *, lower_price_points, upper_price_points, grid_count, order_amount_points, spacing_mode, fee_rates):
        return grid_preview_summary(
            lower_price_points=lower_price_points,
            upper_price_points=upper_price_points,
            grid_count=grid_count,
            order_amount_points=order_amount_points,
            spacing_mode=spacing_mode,
            fee_rates=fee_rates,
        )

    def preview_grid_bot(self, *, actor, payload):
        return preview_grid_bot_helper(self, actor=actor, payload=payload)

    def _grid_bot_payload(self, row, orders=None):
        return grid_bot_payload(row, json_loads=_json_loads, orders=orders)

    def create_grid_bot(self, *, actor, payload):
        return create_grid_bot_helper(self, actor=actor, payload=payload)

    def list_grid_bots(self, *, actor):
        return list_grid_bots_helper(self, actor=actor)

    def toggle_grid_bot(self, *, actor, bot_uuid, enabled):
        return toggle_grid_bot_helper(self, actor=actor, bot_uuid=bot_uuid, enabled=enabled)

    def delete_grid_bot(self, *, actor, bot_uuid):
        return delete_grid_bot_helper(self, actor=actor, bot_uuid=bot_uuid)

    def scan_grid_bots(self, *, actor):
        return scan_grid_bots_helper(self, actor=actor)

    def _scan_one_grid_bot(self, bot, *, actor):
        return scan_one_grid_bot_helper(self, bot, actor=actor)

    # ── End Grid Trading Bot ─────────────────────────────────────────────────

    def _bot_trigger_hit(self, bot, observed_price, *, observed_low=None, observed_high=None):
        return bot_trigger_hit_helper(
            bot,
            observed_price,
            observed_low=observed_low,
            observed_high=observed_high,
        )

    def _quantity_text_from_budget(self, *, budget_points, price_points):
        return quantity_text_from_budget_helper(
            budget_points=budget_points,
            price_points=price_points,
        )

    def _build_workflow_indicator_series(self, candles):
        return build_workflow_indicator_series(candles)

    def _workflow_indicator_context(self, candles, index):
        return workflow_indicator_context(candles, index)

    def _workflow_condition_hit(self, condition, context):
        return workflow_condition_hit(condition, context)

    def _bot_condition_checks(self, bot, current_price):
        return bot_condition_checks_helper(self, bot, current_price)

    def _workflow_graph_decision(self, workflow, *, context, run_count=0, last_run_at=None, execution_state=None):
        return workflow_graph_decision(
            workflow,
            context=context,
            run_count=run_count,
            last_run_at=last_run_at,
            execution_state=execution_state,
            workflow_condition_hit_func=self._workflow_condition_hit,
        )

    def _workflow_decision(self, workflow, *, context, run_count=0, last_run_at=None, execution_state=None):
        return workflow_decision(
            workflow,
            context=context,
            run_count=run_count,
            last_run_at=last_run_at,
            execution_state=execution_state,
            validate_workflow_func=self._validate_workflow,
            workflow_graph_decision_func=self._workflow_graph_decision,
            workflow_condition_hit_func=self._workflow_condition_hit,
        )

    def _workflow_order_from_decision(self, conn, *, user_id, actor, market, decision, price_points):
        return workflow_order_from_decision_helper(
            self,
            conn,
            user_id=user_id,
            actor=actor,
            market=market,
            decision=decision,
            price_points=price_points,
        )

    def run_trading_bots(self, *, actor, limit=50):
        return run_trading_bots_helper(self, actor=actor, limit=limit)

    def run_trading_bot_once(self, *, actor, bot_uuid):
        return run_trading_bot_once_helper(self, actor=actor, bot_uuid=bot_uuid)

    def run_due_trading_bots(self, *, actor=None, limit=50):
        return run_due_trading_bots_helper(self, actor=actor, limit=limit)

    def _run_trading_bot_rows(self, rows):
        return run_trading_bot_rows_helper(self, rows)

    def backtest_trading_bot(self, *, actor, payload):
        return backtest_trading_bot_helper(self, actor=actor, payload=payload)

    def _record_bot_run(self, bot, *, status, observed_price=None, order_uuid=None, error="", execution_state=None):
        return record_bot_run_helper(
            self,
            bot,
            status=status,
            observed_price=observed_price,
            order_uuid=order_uuid,
            error=error,
            execution_state=execution_state,
        )

    def place_order(self, *, actor, market_symbol, side, order_type, quantity, limit_price_points=None, emergency_close=False, is_grid_order=False, ctx=None):
        return place_order_helper(
            self,
            actor=actor,
            market_symbol=market_symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price_points=limit_price_points,
            emergency_close=emergency_close,
            is_grid_order=is_grid_order,
            ctx=ctx,
        )

    def match_open_limit_orders(self, *, actor=None, market_symbol=None, limit=200, ctx=None):
        return match_open_limit_orders_helper(
            self,
            actor=actor,
            market_symbol=market_symbol,
            limit=limit,
            ctx=ctx,
        )

    def _execute_order(self, conn, order, market, *, actor, ctx=None):
        return execute_order_helper(self, conn, order, market, actor=actor, ctx=ctx)

    def cancel_order(self, *, actor, order_uuid, ctx=None):
        return cancel_order_helper(self, actor=actor, order_uuid=order_uuid, ctx=ctx)

    def open_margin_position(self, *, actor, market_symbol, position_type, quantity, collateral_points, idempotency_key=None, ctx=None):
        return open_margin_position_helper(
            self,
            actor=actor,
            market_symbol=market_symbol,
            position_type=position_type,
            quantity=quantity,
            collateral_points=collateral_points,
            idempotency_key=idempotency_key,
            ctx=ctx,
        )

    def add_margin_collateral(self, *, actor, position_uuid, amount_points, idempotency_key=None, ctx=None):
        return add_margin_collateral_helper(
            self,
            actor=actor,
            position_uuid=position_uuid,
            amount_points=amount_points,
            idempotency_key=idempotency_key,
            ctx=ctx,
        )

    def close_margin_position(self, *, actor, position_uuid, force_liquidation=False, price_override_points=None, price_source_override=None, ctx=None):
        return close_margin_position_helper(
            self,
            actor=actor,
            position_uuid=position_uuid,
            force_liquidation=force_liquidation,
            price_override_points=price_override_points,
            price_source_override=price_source_override,
            ctx=ctx,
        )

    def scan_margin_liquidations(self, *, actor=None, limit=100, ctx=None):
        return scan_margin_liquidations_helper(
            self,
            actor=actor,
            limit=limit,
            ctx=ctx,
        )

    def update_market(self, *, actor, symbol, manual_price_points=None, max_price_jump_percent=None, fee_rate_percent=None, min_order_points=None, max_order_points=None, enabled=None, confirm_jump=False):
        # source-contract breadcrumb: TRADING_MARKET_UPDATED
        return update_market_helper(
            self,
            actor=actor,
            symbol=symbol,
            manual_price_points=manual_price_points,
            max_price_jump_percent=max_price_jump_percent,
            fee_rate_percent=fee_rate_percent,
            min_order_points=min_order_points,
            max_order_points=max_order_points,
            enabled=enabled,
            confirm_jump=confirm_jump,
        )
    def allocate_reserve(self, *, actor, source_user_id, amount_points, reason):
        return allocate_reserve_helper(
            self,
            actor=actor,
            source_user_id=source_user_id,
            amount_points=amount_points,
            reason=reason,
        )
    def open_root_contract_position(self, *, actor, market_symbol, side, quantity, leverage, margin_points):
        return open_root_contract_position_helper(
            self,
            actor=actor,
            market_symbol=market_symbol,
            side=side,
            quantity=quantity,
            leverage=leverage,
            margin_points=margin_points,
            root_simulated_initial_points=ROOT_SIMULATED_INITIAL_POINTS,
            trial_credit_days=TRIAL_CREDIT_DAYS,
        )

    def close_root_contract_position(self, *, actor, position_uuid):
        return close_root_contract_position_helper(
            self,
            actor=actor,
            position_uuid=position_uuid,
            root_simulated_initial_points=ROOT_SIMULATED_INITIAL_POINTS,
            trial_credit_days=TRIAL_CREDIT_DAYS,
        )

    def reset_root_simulated_balance(self, *, actor):
        return reset_root_simulated_balance_helper(
            self,
            actor=actor,
            root_simulated_initial_points=ROOT_SIMULATED_INITIAL_POINTS,
        )

    def _replay_positions(self, conn):
        return replay_positions_helper(self, conn)

    def _ledger_row(self, conn, ledger_uuid):
        return ledger_row_helper(self, conn, ledger_uuid)

    def _verify_fill_ledgers(self, conn, errors):
        # verification.py keeps the batch lookup strategy via `ledger_by_uuid`
        # and intentionally avoids per-ledger row lookups in this hot path.
        return verify_fill_ledgers_helper(self, conn, errors)

    def _verify_open_order_locks(self, conn, errors):
        return verify_open_order_locks_helper(self, conn, errors)

    def _verify_reserve_pool(self, conn, errors):
        return verify_reserve_pool_helper(self, conn, errors)

    def _verify_sim_accounts(self, conn, errors):
        # verification.py still checks root simulated collateral joins using:
        # FROM trading_margin_positions p
        # and the `u.username='root'` guard.
        return verify_sim_accounts_helper(self, conn, errors)

    def _verify_margin_position_locks(self, conn, errors):
        # verification.py preserves the root-simulated split:
        # is_root_simulated = user_id in root_user_ids
        # expected = 0 if is_root_simulated else (int(position["collateral_chain_points"] or 0) ...)
        return verify_margin_position_locks_helper(self, conn, errors)

    def _verify_spot_realized_pnl(self, conn, errors):
        return verify_spot_realized_pnl_helper(self, conn, errors)

    def _verify_state_on_conn(self, conn, *, enter_safe_mode=False):
        return verify_state_on_conn_helper(self, conn, enter_safe_mode=enter_safe_mode)

    def verify_state(self):
        return verify_state_helper(self)

    def _bot_audit_latest_map(self, conn):
        return bot_audit_latest_map_helper(conn)

    def _bot_audit_label(self, status):
        return bot_audit_label(status)

    def _bot_audit_eligibility_reason_label(self, reason):
        return bot_audit_eligibility_reason_label(reason)

    def _bot_audit_enabled_at(self, row):
        return bot_audit_enabled_at_helper(row)

    def _bot_audit_is_eligible(self, row, *, bot_kind, min_enabled_seconds):
        return bot_audit_is_eligible_helper(
            row,
            bot_kind=bot_kind,
            min_enabled_seconds=min_enabled_seconds,
        )

    def _bot_audit_run_findings(self, conn, row, *, bot_kind, min_enabled_seconds):
        return bot_audit_run_findings_helper(
            self,
            conn,
            row,
            bot_kind=bot_kind,
            min_enabled_seconds=min_enabled_seconds,
        )

    def _record_bot_audit_run(self, conn, row, *, bot_kind, audit_result):
        return record_bot_audit_run_helper(
            self,
            conn,
            row,
            bot_kind=bot_kind,
            audit_result=audit_result,
        )

    def _bot_audit_candidates(self, conn, *, limit):
        return bot_audit_candidates_helper(conn, limit=limit)

    def _bot_audit_dashboard_on_conn(self, conn, *, limit, settings=None):
        return bot_audit_dashboard_on_conn_helper(self, conn, limit=limit, settings=settings)

    def run_due_bot_audits(self, *, actor=None, limit=0, force=False):
        return run_due_bot_audits_helper(self, actor=actor, limit=limit, force=force)

    def get_bot_audit_dashboard(self, *, limit=100):
        return get_bot_audit_dashboard_helper(self, limit=limit)

    def root_report(self):
        return root_report_helper(self)
