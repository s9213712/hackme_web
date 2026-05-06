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

from services.notifications import create_notification_if_enabled, create_root_notification_if_enabled
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
from services.server_mode_context import SmV2Context, current_ctx
from services.server_mode_routing import resolve_table
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
from services.trading.margin import (
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
    backtest_anchor_price,
    backtest_equity_value,
    backtest_segment_count,
    build_backtest_equity_point,
    build_backtest_initial_state,
    build_backtest_outlier_warning,
    build_backtest_range_warnings,
    build_backtest_result_payload,
    filter_backtest_candles_by_range,
    iter_backtest_segments,
    push_recent_valid_price,
    update_backtest_drawdown,
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
from services.trading_mode_gate import (
    assert_same_world,
    assert_trading_allowed,
    funding_channel_key,
    liquidation_settle_table,
    liquidation_target_table,
    matching_orderbook_key,
)
from services.trading_markets import (
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
from services.trading_price_streams import TradingPriceStreamHub, WS_CAPABLE_PRICE_PROVIDERS


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
        CREATE TABLE IF NOT EXISTS trading_markets_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            base_asset TEXT NOT NULL,
            quote_asset TEXT NOT NULL DEFAULT 'POINTS',
            display_name TEXT NOT NULL,
            display_quote_currency TEXT NOT NULL DEFAULT 'USDT',
            market_type TEXT NOT NULL DEFAULT 'spot',
            enabled INTEGER NOT NULL DEFAULT 1,
            allow_spot INTEGER NOT NULL DEFAULT 1,
            allow_margin INTEGER NOT NULL DEFAULT 1,
            allow_bots INTEGER NOT NULL DEFAULT 1,
            allow_risk_grade_usage INTEGER NOT NULL DEFAULT 1,
            price_precision INTEGER NOT NULL DEFAULT 8,
            quantity_precision INTEGER NOT NULL DEFAULT 8,
            min_order_size REAL NOT NULL DEFAULT 0.00000001,
            max_order_size REAL NOT NULL DEFAULT 1000000,
            lot_size REAL NOT NULL DEFAULT 0.00000001,
            tick_size REAL NOT NULL DEFAULT 0.00000001,
            sort_order INTEGER NOT NULL DEFAULT 9999,
            default_manual_price_points REAL NOT NULL DEFAULT 1,
            live_price_enabled INTEGER NOT NULL DEFAULT 1,
            reference_price_enabled INTEGER NOT NULL DEFAULT 1,
            btc_trade_enabled INTEGER NOT NULL DEFAULT 0,
            registry_source TEXT NOT NULL DEFAULT 'catalog_seed',
            seed_version INTEGER NOT NULL DEFAULT 1,
            probe_status TEXT NOT NULL DEFAULT 'pending',
            probe_summary_json TEXT NOT NULL DEFAULT '{}',
            probe_checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by INTEGER,
            updated_by INTEGER,
            CHECK (market_type IN ('spot', 'synthetic', 'reference_only')),
            CHECK (enabled IN (0, 1)),
            CHECK (allow_spot IN (0, 1)),
            CHECK (allow_margin IN (0, 1)),
            CHECK (allow_bots IN (0, 1)),
            CHECK (allow_risk_grade_usage IN (0, 1)),
            CHECK (live_price_enabled IN (0, 1)),
            CHECK (reference_price_enabled IN (0, 1)),
            CHECK (btc_trade_enabled IN (0, 1)),
            CHECK (registry_source IN ('catalog_seed', 'custom'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_market_provider_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id INTEGER NOT NULL REFERENCES trading_markets_registry(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            provider_symbol TEXT NOT NULL DEFAULT '',
            supports_ticker INTEGER NOT NULL DEFAULT 0,
            supports_depth INTEGER NOT NULL DEFAULT 0,
            supports_candles INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 100,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (market_id, provider)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_market_registry_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            action TEXT NOT NULL,
            market_symbol TEXT NOT NULL,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
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
        try:
            tester_id = int(getattr(ctx, "tester_id", None) or 0)
        except Exception:
            tester_id = 0
        return tester_id if tester_id > 0 else int(user_id)

    def _ensure_shadow_wallet(self, conn, user_id, ctx):
        now = utc_now()
        actor_user_id = self._shadow_actor_user_id(ctx, user_id)
        conn.execute(
            """
            INSERT OR IGNORE INTO test_shadow_wallets (
                tester_user_id, user_id, balance_points, frozen_points,
                total_points_earned, total_points_spent, wallet_status, risk_level,
                created_at, updated_at
            ) VALUES (?, ?, 0, 0, 0, 0, 'active', 'normal', ?, ?)
            """,
            (actor_user_id, int(user_id), now, now),
        )
        row = conn.execute("SELECT * FROM test_shadow_wallets WHERE user_id=?", (int(user_id),)).fetchone()
        if row is None:
            raise ValueError("shadow wallet not found")
        return row

    def _shadow_wallet_payload(self, row):
        if not row:
            return None
        points_balance = int(row["balance_points"] or 0)
        points_frozen = int(row["frozen_points"] or 0)
        total_points_earned = int(row["total_points_earned"] or 0)
        total_points_spent = int(row["total_points_spent"] or 0)
        return {
            "user_id": int(row["user_id"]),
            "public_account_id": public_account_id(self.points_service.chain_secret, int(row["user_id"])),
            "currency_type": DISPLAY_CURRENCY,
            "points_balance": points_balance,
            "points_frozen": points_frozen,
            "total_points_earned": total_points_earned,
            "total_points_spent": total_points_spent,
            "soft_balance": points_balance,
            "hard_balance": 0,
            "soft_frozen": points_frozen,
            "hard_frozen": 0,
            "wallet_status": row["wallet_status"],
            "risk_level": row["risk_level"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _wallet_row(self, conn, user_id, ctx=None):
        wallet_table, route_ctx = self._resolve_table("wallets", ctx, action="wallet-read")
        if wallet_table == "wallets":
            return self.points_service.ensure_wallet(conn, user_id)
        return self._ensure_shadow_wallet(conn, user_id, route_ctx)

    def _wallet_payload(self, conn, user_id, ctx=None):
        wallet_table, route_ctx = self._resolve_table("wallets", ctx, action="wallet-read")
        if wallet_table == "wallets":
            return self.points_service.serialize_wallet(self.points_service.ensure_wallet(conn, user_id))
        return self._shadow_wallet_payload(self._ensure_shadow_wallet(conn, user_id, route_ctx))

    def _shadow_existing_ledger_row(self, conn, idempotency_key):
        if not idempotency_key:
            return None
        return conn.execute("SELECT * FROM test_shadow_ledger WHERE idempotency_key=?", (str(idempotency_key),)).fetchone()

    def _shadow_last_ledger_hash(self, conn):
        row = conn.execute("SELECT ledger_hash FROM test_shadow_ledger ORDER BY id DESC LIMIT 1").fetchone()
        return str(row["ledger_hash"] or "") if row else None

    def _shadow_record_transaction(self, conn, *, ctx, user_id, currency_type, direction, amount, action_type, reference_type=None, reference_id=None, idempotency_key=None, reason="", public_metadata=None, private_metadata=None, sensitive_metadata_encrypted="", actor=None, risk_flag="none", risk_score=0):
        if direction not in {"credit", "debit", "freeze", "unfreeze", "reverse", "transfer_in", "transfer_out"}:
            raise ValueError("unsupported ledger direction")
        amount = int(amount or 0)
        if amount <= 0:
            raise ValueError("amount must be positive")
        existing = self._shadow_existing_ledger_row(conn, idempotency_key)
        if existing:
            return existing

        wallet = self._ensure_shadow_wallet(conn, user_id, ctx)
        if str(wallet["wallet_status"] or "active") == "closed":
            raise ValueError("wallet is closed")
        currency = normalize_currency_type(currency_type)
        balance_col = "balance_points"
        frozen_col = "frozen_points"
        earned_col = "total_points_earned"
        spent_col = "total_points_spent"
        balance_before = int(wallet[balance_col] or 0)
        frozen_before = int(wallet[frozen_col] or 0)
        balance_after = balance_before
        frozen_after = frozen_before
        earned_delta = 0
        spent_delta = 0
        if direction in {"credit", "transfer_in"}:
            balance_after += amount
            earned_delta = amount
        elif direction in {"debit", "transfer_out", "reverse"}:
            if balance_before < amount:
                raise ValueError("insufficient balance")
            balance_after -= amount
            spent_delta = amount
        elif direction == "freeze":
            if balance_before < amount:
                raise ValueError("insufficient balance")
            balance_after -= amount
            frozen_after += amount
        elif direction == "unfreeze":
            if frozen_before < amount:
                raise ValueError("insufficient frozen balance")
            balance_after += amount
            frozen_after -= amount

        public_json = _metadata_json_checked(public_metadata or {}, label="public_metadata")
        private_json = _metadata_json_checked(private_metadata or {}, label="private_metadata")
        meta_hash = metadata_hash(public_metadata or {}, private_metadata or {}, sensitive_metadata_encrypted or "")
        now = utc_now()
        ledger_uuid = str(uuid.uuid4())
        previous_ledger_hash = self._shadow_last_ledger_hash(conn)
        ledger_data = {
            "ledger_uuid": ledger_uuid,
            "public_account_id": public_account_id(self.points_service.chain_secret, int(user_id)),
            "currency_type": currency,
            "direction": direction,
            "amount": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "action_type": action_type,
            "reference_type": reference_type,
            "reference_id": str(reference_id) if reference_id is not None else None,
            "metadata_hash": meta_hash,
            "previous_ledger_hash": previous_ledger_hash,
            "created_at": now,
        }
        ledger_hash = compute_ledger_hash(ledger_data)
        actor_user_id = self._shadow_actor_user_id(ctx, user_id)
        cur = conn.execute(
            """
            INSERT INTO test_shadow_ledger (
                ledger_uuid, tester_user_id, user_id, public_account_id, currency_type, direction,
                amount, balance_before, balance_after, action_type, reference_type, reference_id,
                idempotency_key, reason, public_metadata_json, private_metadata_json,
                sensitive_metadata_encrypted, metadata_hash, previous_ledger_hash, ledger_hash,
                risk_flag, risk_score, created_by, created_by_role, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (
                ledger_uuid,
                actor_user_id,
                int(user_id),
                ledger_data["public_account_id"],
                currency,
                direction,
                amount,
                balance_before,
                balance_after,
                action_type,
                reference_type,
                ledger_data["reference_id"],
                idempotency_key,
                reason or "",
                public_json,
                private_json,
                sensitive_metadata_encrypted or "",
                meta_hash,
                previous_ledger_hash,
                ledger_hash,
                risk_flag,
                int(risk_score or 0),
                int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                actor_value(actor, "role"),
                now,
            ),
        )
        conn.execute(
            f"""
            UPDATE test_shadow_wallets
            SET {balance_col}=?, {frozen_col}=?, {earned_col}={earned_col}+?, {spent_col}={spent_col}+?,
                balance_points=?, updated_at=?
            WHERE user_id=?
            """,
            (balance_after, frozen_after, earned_delta, spent_delta, balance_after, now, int(user_id)),
        )
        return conn.execute("SELECT * FROM test_shadow_ledger WHERE id=?", (cur.lastrowid,)).fetchone()

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
        rows = conn.execute("SELECT key, value, updated_at, updated_by FROM trading_settings ORDER BY key").fetchall()
        raw = {row["key"]: row["value"] for row in rows}
        borrow_apr_btc_eth, borrow_apr_usdt_points = apr_pair_from_raw(
            raw,
            btc_eth_default=DEFAULT_BORROW_APR_BTC_ETH_PERCENT,
            usdt_points_default=DEFAULT_BORROW_APR_USDT_POINTS_PERCENT,
        )
        borrow_interest_interval_hours, borrow_interest_minimum_hours = interval_pair_from_raw(
            raw,
            interval_default=DEFAULT_BORROW_INTEREST_INTERVAL_HOURS,
            minimum_default=DEFAULT_BORROW_INTEREST_MINIMUM_HOURS,
        )
        return {
            "enabled": raw_bool_setting(raw, "trading.enabled", default=True),
            "futures_enabled": raw_bool_setting(raw, "trading.futures_enabled", default=False),
            "pvp_matching_enabled": raw_bool_setting(raw, "trading.pvp_matching_enabled", default=False),
            "borrowing_enabled": raw_bool_setting(raw, "trading.borrowing_enabled", default=True),
            "borrow_apr_btc_eth_percent": borrow_apr_btc_eth,
            "borrow_apr_usdt_points_percent": borrow_apr_usdt_points,
            "borrow_interest_percent_daily": daily_from_apr(borrow_apr_usdt_points),
            "borrow_interest_pool_pressure_multiplier": raw_float_setting(raw, "trading.borrow_interest_pool_pressure_multiplier", TRADING_FUNDING_POOL_PRESSURE_MULTIPLIER, name="borrow_interest_pool_pressure_multiplier", minimum=0, maximum=100),
            "borrow_interest_interval_hours": borrow_interest_interval_hours,
            "borrow_interest_minimum_hours": borrow_interest_minimum_hours,
            "margin_long_financing_percent": raw_float_setting(raw, "trading.margin_long_financing_percent", MARGIN_LONG_FINANCING_RATE_PERCENT, name="margin_long_financing_percent", minimum=0, maximum=100),
            "short_collateral_percent": raw_float_setting(raw, "trading.short_collateral_percent", SHORT_COLLATERAL_RATE_PERCENT, name="short_collateral_percent", minimum=0, maximum=100),
            "margin_liquidation_enabled": raw_bool_setting(raw, "trading.margin_liquidation_enabled", default=True),
            "shadow_funding_publish_enabled": raw_bool_setting(raw, "trading.shadow_funding_publish_enabled", default=False),
            "margin_maintenance_percent": raw_float_setting(raw, "trading.margin_maintenance_percent", "15", name="margin_maintenance_percent", minimum=0, maximum=100),
            "grid_fee_discount_percent": raw_float_setting(raw, "trading.grid_fee_discount_percent", DEFAULT_GRID_FEE_DISCOUNT_PERCENT, name="grid_fee_discount_percent", minimum=0, maximum=100),
            "max_price_staleness_seconds": raw_int_setting(raw, "trading.max_price_staleness_seconds", "900", name="max_price_staleness_seconds", minimum=0, maximum=86400),
            "price_source": raw.get("trading.price_source", FUSED_PRICE_SOURCE),
            "price_fusion_mode": raw_choice_setting(raw, "trading.price_fusion_mode", "auto_depth", allowed=PRICE_FUSION_MODES),
            "price_fusion_manual_weights": _normalize_price_fusion_manual_weights(_json_loads(raw.get("trading.price_fusion_manual_weights_json"), DEFAULT_PRICE_FUSION_MANUAL_WEIGHTS)),
            "price_fusion_provider_labels": dict(PRICE_PROVIDER_LABELS),
            "price_fusion_providers": list(WEIGHTED_PRICE_PROVIDERS),
            "price_fusion_live_markets": self._list_live_price_market_symbols(conn),
            "price_fusion_depth_band_percent": raw_float_setting(raw, "trading.price_fusion_depth_band_percent", DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT, name="price_fusion_depth_band_percent", minimum=0.1, maximum=10),
            "price_fusion_depth_levels": raw_int_setting(raw, "trading.price_fusion_depth_levels", DEFAULT_PRICE_FUSION_DEPTH_LEVELS, name="price_fusion_depth_levels", minimum=10, maximum=MAX_PRICE_FUSION_DEPTH_LEVELS),
            "price_fusion_min_orderbook_coverage_percent": raw_float_setting(raw, "trading.price_fusion_min_orderbook_coverage_percent", DEFAULT_PRICE_FUSION_MIN_ORDERBOOK_COVERAGE_PERCENT, name="price_fusion_min_orderbook_coverage_percent", minimum=0.1, maximum=10),
            "price_fusion_max_single_provider_weight_percent": raw_float_setting(raw, "trading.price_fusion_max_single_provider_weight_percent", DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT, name="price_fusion_max_single_provider_weight_percent", minimum=0, maximum=100),
            "price_fusion_max_provider_age_seconds": DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS,
            "price_fusion_max_provider_latency_ms": DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS,
            "price_fusion_max_midpoint_deviation_percent": DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT,
            "price_fusion_min_side_balance_ratio_percent": round(DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2),
            "price_fusion_min_provider_count": raw_int_setting(raw, "trading.price_fusion_min_provider_count", DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT, name="price_fusion_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS)),
            "price_stream_ws_enabled": raw_bool_setting(raw, "trading.price_stream_ws_enabled", default=True),
            "price_stream_ws_stale_seconds": raw_int_setting(raw, "trading.price_stream_ws_stale_seconds", DEFAULT_PRICE_STREAM_WS_STALE_SECONDS, name="price_stream_ws_stale_seconds", minimum=1, maximum=120),
            "btc_trade_enabled": raw_bool_setting(raw, "trading.btc_trade_enabled", default=False),
            "btc_trade_project_dir": raw.get("trading.btc_trade_project_dir", ""),
            "btc_trade_repo_url": raw.get("trading.btc_trade_repo_url", "https://github.com/s9213712/BTC_trade.git"),
            "btc_trade_branch": raw.get("trading.btc_trade_branch", "strategy/v15b-plus"),
            "bot_auto_scan_enabled": raw_bool_setting(raw, "trading.bot_auto_scan_enabled", default=True),
            "bot_auto_scan_interval_seconds": raw_int_setting(raw, "trading.bot_auto_scan_interval_seconds", "30", name="bot_auto_scan_interval_seconds", minimum=10, maximum=3600),
            "bot_auto_scan_limit": raw_int_setting(raw, "trading.bot_auto_scan_limit", "50", name="bot_auto_scan_limit", minimum=1, maximum=200),
            "bot_audit_enabled": raw_bool_setting(raw, "trading.bot_audit_enabled", default=True),
            "bot_audit_interval_seconds": raw_int_setting(raw, "trading.bot_audit_interval_seconds", TRADING_BOT_AUDIT_INTERVAL_SECONDS, name="bot_audit_interval_seconds", minimum=60, maximum=86400),
            "bot_audit_limit": raw_int_setting(raw, "trading.bot_audit_limit", TRADING_BOT_AUDIT_LIMIT, name="bot_audit_limit", minimum=1, maximum=200),
            "bot_audit_min_enabled_seconds": raw_int_setting(raw, "trading.bot_audit_min_enabled_seconds", TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS, name="bot_audit_min_enabled_seconds", minimum=3600, maximum=604800),
            "backtest_max_candles": raw_int_setting(raw, "trading.backtest_max_candles", str(MAX_BACKTEST_CANDLES), name="backtest_max_candles", minimum=BACKTEST_MAX_CANDLES_FLOOR, maximum=BACKTEST_MAX_CANDLES_CEILING),
            "backtest_measured_capacity": raw_int_setting(raw, "trading.backtest_measured_capacity", "0", name="backtest_measured_capacity", minimum=0, maximum=BACKTEST_MAX_CANDLES_CEILING),
            "backtest_measured_capacity_max": raw_int_setting(raw, "trading.backtest_measured_capacity_max", "0", name="backtest_measured_capacity_max", minimum=0, maximum=BACKTEST_MAX_CANDLES_CEILING),
            "backtest_capacity_measured_at": raw.get("trading.backtest_capacity_measured_at", ""),
            "backtest_capacity_bottleneck": raw.get("trading.backtest_capacity_bottleneck", ""),
            "backtest_capacity_fastest": raw.get("trading.backtest_capacity_fastest", ""),
            "backtest_capacity_time_budget_seconds": raw_int_setting(raw, "trading.backtest_capacity_time_budget_seconds", str(BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS), name="backtest_capacity_time_budget_seconds", minimum=BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS, maximum=BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS),
            "raw": raw,
        }

    def get_root_settings(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return {
                "settings": self._settings_payload(conn),
                "markets": [
                    self._market_payload(row)
                    for row in conn.execute("SELECT * FROM trading_markets ORDER BY sort_order ASC, symbol ASC").fetchall()
                ],
                "reserve_pool": dict(self._reserve(conn)),
                "funding_pool": self._funding_pool_payload(conn),
            }
        finally:
            conn.close()

    def get_max_backtest_candles(self, conn=None):
        """Resolve the runtime backtest cap (root-configured) with safe fallback to MAX_BACKTEST_CANDLES."""
        close_conn = False
        if conn is None:
            conn = self.get_db()
            close_conn = True
        try:
            try:
                self.ensure_schema(conn)
                row = conn.execute("SELECT value FROM trading_settings WHERE key = ?", ("trading.backtest_max_candles",)).fetchone()
            except Exception:
                return MAX_BACKTEST_CANDLES
            if not row:
                return MAX_BACKTEST_CANDLES
            try:
                value = int(str(row["value"]).strip())
            except Exception:
                return MAX_BACKTEST_CANDLES
            if value < BACKTEST_MAX_CANDLES_FLOOR:
                return MAX_BACKTEST_CANDLES
            if value > BACKTEST_MAX_CANDLES_CEILING:
                return BACKTEST_MAX_CANDLES_CEILING
            return value
        finally:
            if close_conn:
                conn.close()

    def get_backtest_capacity_time_budget_seconds(self, conn=None):
        """Resolve the root-configured probe time budget (seconds), default 60."""
        close_conn = False
        if conn is None:
            conn = self.get_db()
            close_conn = True
        try:
            try:
                self.ensure_schema(conn)
                row = conn.execute(
                    "SELECT value FROM trading_settings WHERE key = ?",
                    ("trading.backtest_capacity_time_budget_seconds",),
                ).fetchone()
            except Exception:
                return BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
            if not row:
                return BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
            try:
                value = int(str(row["value"]).strip())
            except Exception:
                return BACKTEST_CAPACITY_TIME_BUDGET_DEFAULT_SECONDS
            if value < BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS:
                return BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS
            if value > BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS:
                return BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS
            return value
        finally:
            if close_conn:
                conn.close()

    def get_backtest_capacity_measurement(self, conn=None):
        """Return measurement payload (min/max capacity + bottleneck/fastest strategy)."""
        close_conn = False
        if conn is None:
            conn = self.get_db()
            close_conn = True
        try:
            try:
                self.ensure_schema(conn)
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
        """Persist probe results.

        If ``seed_default_cap`` and the cap setting is still at its first-boot default
        (i.e., never set by root), auto-seed ``trading.backtest_max_candles`` with the
        worst-case capacity so root sees a host-realistic default in the UI.
        """
        try:
            measured_capacity_min = int(measured_capacity_min)
        except Exception:
            measured_capacity_min = 0
        try:
            measured_capacity_max = int(measured_capacity_max)
        except Exception:
            measured_capacity_max = 0
        measured_capacity_min = max(0, min(BACKTEST_MAX_CANDLES_CEILING, measured_capacity_min))
        measured_capacity_max = max(measured_capacity_min, min(BACKTEST_MAX_CANDLES_CEILING, measured_capacity_max))
        if not measured_at:
            measured_at = _now()
        bottleneck_strategy = str(bottleneck_strategy or "")[:100]
        fastest_strategy = str(fastest_strategy or "")[:100]
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
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
            if seed_default_cap and measured_capacity_min >= BACKTEST_MAX_CANDLES_FLOOR:
                # Only seed if cap is still unset — preserve any explicit root override.
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
            for input_key, storage_key in TRADING_ROOT_BOOL_SETTING_KEYS.items():
                if input_key in settings:
                    value = bool_input_text(settings, input_key)
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
                    value = float_input_text(settings, input_key, minimum=0, maximum=100)
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
                    if input_key == "borrow_apr_usdt_points_percent":
                        legacy_daily = str(daily_from_apr(numeric))
                        conn.execute(
                            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                            ("trading.borrow_interest_percent_daily", legacy_daily, now, self._actor_id(actor)),
                        )
                        setting_changes["trading.borrow_interest_percent_daily"] = legacy_daily
            if "borrow_interest_percent_daily" in settings and "borrow_apr_usdt_points_percent" not in settings:
                legacy_daily = _to_float(settings.get("borrow_interest_percent_daily"), name="borrow_interest_percent_daily", minimum=0, maximum=100)
                apr_payload = write_apr_from_daily(settings, now=now, actor_id=self._actor_id(actor))
                apr_value = apr_payload["trading.borrow_apr_usdt_points_percent"]
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_apr_usdt_points_percent", apr_value, now, self._actor_id(actor)),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.borrow_interest_percent_daily", apr_payload["trading.borrow_interest_percent_daily"], now, self._actor_id(actor)),
                )
                setting_changes["trading.borrow_apr_usdt_points_percent"] = apr_value
                setting_changes["trading.borrow_interest_percent_daily"] = apr_payload["trading.borrow_interest_percent_daily"]
            if "borrow_interest_pool_pressure_multiplier" in settings:
                value = float_input_text(settings, "borrow_interest_pool_pressure_multiplier", minimum=0, maximum=100)
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
                    value = int_input_text(settings, input_key, minimum=1, maximum=168)
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
                    value = float_input_text(settings, input_key, minimum=0, maximum=100)
                    conn.execute(
                        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (storage_key, value, now, self._actor_id(actor)),
                    )
                    setting_changes[storage_key] = value
            if "margin_maintenance_percent" in settings:
                value = float_input_text(settings, "margin_maintenance_percent", minimum=0, maximum=100)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.margin_maintenance_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.margin_maintenance_percent"] = value
            if "grid_fee_discount_percent" in settings:
                value = float_input_text(settings, "grid_fee_discount_percent", minimum=0, maximum=100)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.grid_fee_discount_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.grid_fee_discount_percent"] = value
            if "max_price_staleness_seconds" in settings:
                value = int_input_text(settings, "max_price_staleness_seconds", minimum=0, maximum=86400)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.max_price_staleness_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.max_price_staleness_seconds"] = value
            if "bot_auto_scan_interval_seconds" in settings:
                value = int_input_text(settings, "bot_auto_scan_interval_seconds", minimum=10, maximum=3600)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_auto_scan_interval_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_auto_scan_interval_seconds"] = value
            if "bot_auto_scan_limit" in settings:
                value = int_input_text(settings, "bot_auto_scan_limit", minimum=1, maximum=200)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_auto_scan_limit", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_auto_scan_limit"] = value
            if "backtest_max_candles" in settings:
                value = int_input_text(settings, "backtest_max_candles", minimum=BACKTEST_MAX_CANDLES_FLOOR, maximum=BACKTEST_MAX_CANDLES_CEILING)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.backtest_max_candles", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.backtest_max_candles"] = value
            if "backtest_capacity_time_budget_seconds" in settings:
                value = int_input_text(settings, "backtest_capacity_time_budget_seconds", minimum=BACKTEST_CAPACITY_TIME_BUDGET_MIN_SECONDS, maximum=BACKTEST_CAPACITY_TIME_BUDGET_MAX_SECONDS)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.backtest_capacity_time_budget_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.backtest_capacity_time_budget_seconds"] = value
            if "bot_audit_interval_seconds" in settings:
                value = int_input_text(settings, "bot_audit_interval_seconds", minimum=60, maximum=86400)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_audit_interval_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_audit_interval_seconds"] = value
            if "bot_audit_limit" in settings:
                value = int_input_text(settings, "bot_audit_limit", minimum=1, maximum=200)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_audit_limit", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_audit_limit"] = value
            if "bot_audit_min_enabled_seconds" in settings:
                value = int_input_text(settings, "bot_audit_min_enabled_seconds", minimum=3600, maximum=604800)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.bot_audit_min_enabled_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.bot_audit_min_enabled_seconds"] = value
            if "price_source" in settings:
                value = choice_input_value(
                    settings,
                    "price_source",
                    allowed={FUSED_PRICE_SOURCE, "binance_public_api", "manual_root"},
                    error_message="price_source must be fused_weighted, binance_public_api, or manual_root",
                )
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_source", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_source"] = value
            if "price_fusion_mode" in settings:
                value = choice_input_value(
                    settings,
                    "price_fusion_mode",
                    allowed=PRICE_FUSION_MODES,
                    error_message="price_fusion_mode must be auto_depth or manual_weights",
                )
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
                value = int_input_text(settings, "price_fusion_depth_levels", minimum=10, maximum=MAX_PRICE_FUSION_DEPTH_LEVELS)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_depth_levels", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_depth_levels"] = value
            if "price_fusion_depth_band_percent" in settings:
                value = float_input_text(settings, "price_fusion_depth_band_percent", minimum=0.1, maximum=10)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_depth_band_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_depth_band_percent"] = value
            if "price_fusion_min_orderbook_coverage_percent" in settings:
                value = float_input_text(settings, "price_fusion_min_orderbook_coverage_percent", minimum=0.1, maximum=10)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_min_orderbook_coverage_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_min_orderbook_coverage_percent"] = value
            if "price_fusion_max_single_provider_weight_percent" in settings:
                value = float_input_text(settings, "price_fusion_max_single_provider_weight_percent", minimum=0, maximum=100)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_max_single_provider_weight_percent", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_max_single_provider_weight_percent"] = value
            if "price_fusion_min_provider_count" in settings:
                value = int_input_text(settings, "price_fusion_min_provider_count", minimum=1, maximum=len(WEIGHTED_PRICE_PROVIDERS))
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_fusion_min_provider_count", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_fusion_min_provider_count"] = value
            if "price_stream_ws_stale_seconds" in settings:
                value = int_input_text(settings, "price_stream_ws_stale_seconds", minimum=1, maximum=120)
                conn.execute(
                    "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    ("trading.price_stream_ws_stale_seconds", value, now, self._actor_id(actor)),
                )
                setting_changes["trading.price_stream_ws_stale_seconds"] = value
            if "btc_trade_project_dir" in settings:
                value = text_input_value(settings, "btc_trade_project_dir")
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
                    value = text_input_value(settings, input_key)
                    if input_key == "btc_trade_repo_url" and not value:
                        value = "https://github.com/s9213712/BTC_trade.git"
                    if input_key == "btc_trade_branch" and not value:
                        value = "strategy/v15b-plus"
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
        ws_snapshot, stream_state = self._resolve_stream_ticker_snapshot(source, market_symbol, settings=settings, conn=conn)
        if ws_snapshot:
            return (
                float(_to_decimal(ws_snapshot.get("price_points"), name=f"{source} websocket price_points", minimum=0.00000001)),
                self._provider_transport_meta(
                    source,
                    market_symbol,
                    settings=settings,
                    stream_state=stream_state,
                    transport="websocket",
                    fetched_at=ws_snapshot.get("fetched_at"),
                    latency_ms=ws_snapshot.get("latency_ms"),
                    conn=conn,
                ),
            )
        price_points, fetch_meta = http_fetcher()
        return (
            price_points,
            self._provider_transport_meta(
                source,
                market_symbol,
                settings=settings,
                stream_state=stream_state,
                transport="http_polling",
                fetched_at=(fetch_meta or {}).get("fetched_at"),
                latency_ms=(fetch_meta or {}).get("latency_ms"),
                fallback=bool(stream_state.get("ws_supported")),
                exclusion_reason=str(stream_state.get("exclusion_reason") or ""),
                conn=conn,
            ),
        )

    def _provider_orderbook_with_fallback(self, source, market_symbol, *, settings, depth_levels, band_percent, request_limit, http_fetcher, book_getter, conn=None):
        ws_snapshot, stream_state = self._resolve_stream_orderbook_snapshot(source, market_symbol, settings=settings, conn=conn)
        if ws_snapshot:
            return self._build_orderbook_snapshot(
                source=source,
                bids=ws_snapshot.get("bids") or [],
                asks=ws_snapshot.get("asks") or [],
                fetch_meta={
                    "fetched_at": ws_snapshot.get("fetched_at") or ws_snapshot.get("last_update_at") or _now(),
                    "latency_ms": ws_snapshot.get("latency_ms") or 0.0,
                },
                max_levels=depth_levels,
                band_percent=band_percent,
                request_limit=request_limit,
                transport_meta=self._provider_transport_meta(
                    source,
                    market_symbol,
                    settings=settings,
                    stream_state=stream_state,
                    transport="websocket",
                    fetched_at=ws_snapshot.get("fetched_at") or ws_snapshot.get("last_update_at"),
                    latency_ms=ws_snapshot.get("latency_ms"),
                    conn=conn,
                ),
            )
        payload, fetch_meta = http_fetcher()
        bids, asks = book_getter(payload)
        return self._build_orderbook_snapshot(
            source=source,
            bids=bids,
            asks=asks,
            fetch_meta=fetch_meta,
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            transport_meta=self._provider_transport_meta(
                source,
                market_symbol,
                settings=settings,
                stream_state=stream_state,
                transport="http_polling",
                fetched_at=(fetch_meta or {}).get("fetched_at"),
                latency_ms=(fetch_meta or {}).get("latency_ms"),
                fallback=bool(stream_state.get("ws_supported")),
                exclusion_reason=str(stream_state.get("exclusion_reason") or ""),
                conn=conn,
            ),
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
        provider_id = self.market_provider_id(market_symbol, source, conn=conn)
        if not self.stream_hub or not self._price_stream_ws_enabled(settings):
            return {
                "provider": source,
                "market_symbol": str(market_symbol or "").strip().upper(),
                "ws_supported": False,
                "transport": "http_polling",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": False,
                "confidence": "medium",
                "provider_count": 1,
                "last_update_at": "",
                "exclusion_reason": "" if provider_id else "provider_not_supported",
            }
        return self.stream_hub.get_provider_state(
            source,
            market_symbol,
            provider_id=provider_id,
            stale_after_seconds=self._price_stream_ws_stale_seconds(settings),
        )

    def _provider_transport_meta(self, source, market_symbol, *, settings, stream_state=None, transport="http_polling", fetched_at="", latency_ms=0.0, fallback=False, exclusion_reason="", conn=None):
        state = dict(stream_state or self._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn) or {})
        connected = bool(state.get("connected")) if transport == "websocket" else False
        stale = bool(state.get("stale")) if transport == "websocket" else False
        degraded = stale or (transport == "http_polling" and bool(state.get("ws_supported")) and fallback)
        confidence = "high" if transport == "websocket" and connected and not stale else ("medium" if transport == "http_polling" else str(state.get("confidence") or "low"))
        last_update_at = str(fetched_at or state.get("last_update_at") or "")
        reason = str(exclusion_reason or state.get("exclusion_reason") or "")
        return {
            "ws_supported": bool(state.get("ws_supported")),
            "transport": transport,
            "connected": connected,
            "fallback": bool(fallback),
            "stale": stale,
            "degraded": degraded,
            "confidence": confidence,
            "provider_count": 1,
            "last_update_at": last_update_at,
            "exclusion_reason": reason,
            "latency_ms": round(float(latency_ms or 0.0), 2),
        }

    def _resolve_stream_ticker_snapshot(self, source, market_symbol, *, settings, conn=None):
        state = self._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn)
        if not self.stream_hub or not state.get("ws_supported"):
            return None, state
        snapshot = self.stream_hub.get_ticker_snapshot(
            source,
            market_symbol,
            provider_id=self.market_provider_id(market_symbol, source, conn=conn),
            stale_after_seconds=self._price_stream_ws_stale_seconds(settings),
        )
        if not snapshot or snapshot.get("stale") or snapshot.get("degraded") or snapshot.get("price_points") in (None, ""):
            return None, state
        return snapshot, state

    def _resolve_stream_orderbook_snapshot(self, source, market_symbol, *, settings, conn=None):
        state = self._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn)
        if not self.stream_hub or not state.get("ws_supported"):
            return None, state
        snapshot = self.stream_hub.get_orderbook_snapshot(
            source,
            market_symbol,
            provider_id=self.market_provider_id(market_symbol, source, conn=conn),
            stale_after_seconds=self._price_stream_ws_stale_seconds(settings),
        )
        if not snapshot or snapshot.get("stale") or snapshot.get("degraded"):
            return None, state
        return snapshot, state

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
        meta = price_meta or {}
        normalized_type = str(price_type or "reference").strip().lower() or "reference"
        health = str(meta.get("price_health") or "healthy").strip() or "healthy"
        warnings = list(meta.get("warnings") or [])
        source = str(meta.get("resolved_source") or price_source or "manual_root").strip() or "manual_root"
        stale = bool(meta.get("stale"))
        degraded = bool(meta.get("degraded")) or health in {"fallback", "degraded", "conservative"}
        provider_key = "risk_grade_provider_count" if normalized_type == "risk_grade" else "reference_provider_count"
        provider_count = max(0, int(meta.get(provider_key) or 0))
        high_risk_blocked = bool(meta.get("high_risk_blocked")) if normalized_type == "risk_grade" else False
        synthetic_test_provider = bool(meta.get("synthetic_test_provider"))
        warning_only = bool(meta.get("warning_only")) or ((bool(warnings) or bool(meta.get("excluded_sources"))) and not degraded)
        warning_message = str(meta.get("high_risk_block_reason") or meta.get("fallback_reason") or "").strip()
        if not warning_message:
            warning_message = str(self._primary_price_fusion_warning(warnings).get("message") or "").strip()
        if not warning_message and source == "manual_root":
            warning_message = "目前使用手動價格，請勿將此價格視為正常即時市場深度。"
        if not warning_message and stale:
            warning_message = "目前使用最後健康快取，請留意價格可能已過時。"
        if not warning_message and synthetic_test_provider:
            warning_message = "目前使用測試注入 live price provider；此來源只適合測試與 reference 顯示，不可視為 production 風控價格。"
        confidence = self._price_context_confidence(
            price_type=normalized_type,
            source=source,
            health=health,
            degraded=degraded,
            stale=stale,
            provider_count=provider_count,
            high_risk_blocked=high_risk_blocked,
        )
        risk_grade_usable = self._price_context_risk_grade_usable(
            price_type=normalized_type,
            source=source,
            health=health,
            degraded=degraded,
            stale=stale,
            provider_count=provider_count,
            high_risk_blocked=high_risk_blocked,
            fallback=bool(meta.get("fallback")),
            synthetic_test_provider=synthetic_test_provider,
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
            "connected": bool(meta.get("connected")),
            "fallback": bool(meta.get("fallback")),
            "last_update_at": str(meta.get("last_update_at") or ""),
            "exclusion_reason": str(meta.get("exclusion_reason") or ""),
            "health": health,
            "purpose": self._price_usage_label(normalized_type),
            "warning_message": warning_message,
            "high_risk_blocked": high_risk_blocked,
            "risk_grade_usable": risk_grade_usable,
            "synthetic_test_provider": synthetic_test_provider,
            "warning_only": warning_only,
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
            "high_risk_blocked": source.endswith("_cached"),
            "high_risk_block_reason": "",
            "requested_price_mode": "reference",
            "reference_price_points": price_value,
            "risk_grade_price_points": price_value,
            "resolved_source": source,
            "reference_provider_count": 1 if source and source != "manual_root" else 0,
            "risk_grade_provider_count": 1 if source and source != "manual_root" else 0,
            "stale": source.endswith("_cached"),
            "degraded": source == "manual_root" or source.endswith("_cached"),
            "connected": False,
            "fallback": source.endswith("_cached"),
            "last_update_at": str((market or {}).get("updated_at") or ""),
            "exclusion_reason": "manual_root_active" if source == "manual_root" else ("cached_price_active" if source.endswith("_cached") else ""),
            "confidence": "manual" if source == "manual_root" else ("low" if source.endswith("_cached") else "medium"),
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
            price_meta["high_risk_block_reason"] = "目前使用最後健康快取，不能作為風控級價格。"
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
        rows = [row for row in (provider_rows or []) if isinstance(row, dict)]
        ws_rows = [row for row in rows if row.get("source") in WS_CAPABLE_PRICE_PROVIDERS]
        connected_count = sum(1 for row in ws_rows if bool(row.get("connected")))
        fallback_count = sum(1 for row in ws_rows if bool(row.get("fallback")))
        stale_count = sum(1 for row in ws_rows if bool(row.get("stream_stale") or row.get("stale")))
        last_update_at = ""
        last_candidates = [
            str(row.get("provider_last_update_at") or row.get("last_update_at") or row.get("fetched_at") or "").strip()
            for row in rows
            if str(row.get("provider_last_update_at") or row.get("last_update_at") or row.get("fetched_at") or "").strip()
        ]
        if last_candidates:
            last_update_at = sorted(last_candidates)[-1]
        warning_rows = [row for row in rows if str(row.get("provider_exclusion_reason") or "").strip()]
        primary_exclusion = str(warning_rows[0].get("provider_exclusion_reason") or "").strip() if warning_rows else ""
        if not primary_exclusion:
            primary_warning = self._primary_price_fusion_warning(warnings or [])
            primary_exclusion = str(primary_warning.get("message") or primary_warning.get("code") or "").strip()
        if not ws_enabled:
            return {
                "mode": "http_polling_only",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": bool(degraded),
                "confidence": "medium",
                "provider_count": len(rows),
                "last_update_at": last_update_at,
                "exclusion_reason": primary_exclusion,
                "message": "WebSocket 未啟用，使用 HTTP polling 作為 provider input。",
            }
        if not ws_rows:
            return {
                "mode": "http_only_providers",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": bool(degraded),
                "confidence": "medium",
                "provider_count": len(rows),
                "last_update_at": last_update_at,
                "exclusion_reason": primary_exclusion,
                "message": "目前市場沒有支援 WebSocket 的 provider input，使用 HTTP polling。",
            }
        transport_degraded = bool(degraded or conservative_mode or fallback_count or stale_count or connected_count <= 0)
        confidence = "high"
        if conservative_mode or connected_count <= 0:
            confidence = "low"
        elif transport_degraded:
            confidence = "medium"
        return {
            "mode": "mixed" if fallback_count else "websocket",
            "connected": connected_count > 0,
            "fallback": fallback_count > 0,
            "stale": stale_count > 0,
            "degraded": transport_degraded,
            "confidence": confidence,
            "provider_count": connected_count,
            "last_update_at": last_update_at,
            "exclusion_reason": primary_exclusion,
            "message": (
                "部分 provider 已切回 HTTP polling，請視為可審計降級狀態。"
                if fallback_count
                else (
                    "WebSocket provider input 正常運作。"
                    if connected_count >= max(1, min_provider_count)
                    else "WebSocket provider input 不足，請視為降級狀態。"
                )
            ),
        }

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
        if isinstance(transport_meta, dict):
            snapshot.update({
                "ws_supported": bool(transport_meta.get("ws_supported")),
                "transport": str(transport_meta.get("transport") or "http_polling"),
                "connected": bool(transport_meta.get("connected")),
                "fallback": bool(transport_meta.get("fallback")),
                "stream_stale": bool(transport_meta.get("stale")),
                "stream_degraded": bool(transport_meta.get("degraded")),
                "stream_confidence": str(transport_meta.get("confidence") or "medium"),
                "provider_last_update_at": str(transport_meta.get("last_update_at") or fetched_at),
                "provider_exclusion_reason": str(transport_meta.get("exclusion_reason") or ""),
            })
        return snapshot

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
                    snapshots.append(
                        self._call_with_optional_conn(
                            fetcher,
                            market_symbol,
                            depth_levels=depth_levels,
                            band_percent=depth_band_percent,
                            settings=settings,
                            conn=conn,
                        )
                    )
                except TypeError:
                    try:
                        snapshots.append(
                            self._call_with_optional_conn(
                                fetcher,
                                market_symbol,
                                depth_levels=depth_levels,
                                settings=settings,
                                conn=conn,
                            )
                        )
                    except TypeError:
                        snapshots.append(self._call_with_optional_conn(fetcher, market_symbol, conn=conn))
            except Exception as exc:
                short_error = str(exc)[:120]
                errors.append(f"{source}: {short_error}")
                provider_failures[source] = short_error
        if not snapshots:
            try:
                fallback_price, fallback_source, fallback_meta = self._call_with_optional_conn(
                    self._fetch_live_price_points,
                    market_symbol,
                    with_meta=True,
                    settings=settings,
                    conn=conn,
                )
                synthetic_test_provider = str(fallback_source or "") == "test_live_price_provider"
                if not synthetic_test_provider:
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
                providers_used = [{
                    "source": fallback_source,
                    "label": PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
                    "price_points": fallback_value,
                    "midpoint_points": fallback_value,
                    "depth_score": 0.0,
                    "effective_depth_score": 0.0,
                    "depth_density_score": 0.0,
                    "reference_weight_percent": 100.0,
                    "risk_grade_weight_percent": 100.0 if synthetic_test_provider else 0.0,
                    "normalized_weight_percent": 100.0,
                    "raw_normalized_weight_percent": 100.0,
                    "risk_grade_eligible": bool(synthetic_test_provider),
                    "coverage_insufficient": not bool(synthetic_test_provider),
                    "coverage_warning_message": "" if synthetic_test_provider else "資料截斷，不代表該交易所真實深度不足；目前僅納入 reference price，不納入高風險風控權重。",
                    "quantity_unit": "n/a",
                    "quantity_unit_label": "n/a",
                    "quantity_unit_confirmed": False,
                    "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                    "best_bid_points": None,
                    "best_ask_points": None,
                    "spread_percent": None,
                    "bid_notional_points": None,
                    "ask_notional_points": None,
                    "fetched_at": str(fallback_meta.get("last_update_at") or _now()),
                    "age_seconds": 0.0,
                    "latency_ms": round(float(fallback_meta.get("latency_ms") or 0.0), 2),
                    "midpoint_deviation_percent": 0.0,
                    "raw_bid_levels_count": 0,
                    "raw_ask_levels_count": 0,
                    "used_bid_levels_count": 0,
                    "used_ask_levels_count": 0,
                    "bid_coverage_percent": 0.0,
                    "ask_coverage_percent": 0.0,
                    "bid_reached_lower_bound": False,
                    "ask_reached_upper_bound": False,
                    "orderbook_truncated": not bool(synthetic_test_provider),
                    "coverage_ratio_percent": 0.0,
                    "depth_levels_requested": depth_levels,
                    "provider_depth_request_limit": 0,
                    "provider_depth_limit_reached": False,
                    "transport": str(fallback_meta.get("transport") or "http_polling"),
                    "connected": bool(fallback_meta.get("connected")),
                    "fallback": bool(fallback_meta.get("fallback")),
                    "stale": bool(fallback_meta.get("stale")),
                    "degraded": bool(fallback_meta.get("degraded")),
                    "confidence": str(fallback_meta.get("confidence") or "low"),
                    "last_update_at": str(fallback_meta.get("last_update_at") or _now()),
                    "exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                    "provider_last_update_at": str(fallback_meta.get("last_update_at") or _now()),
                    "provider_exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                }]
                providers_used = [{
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
                    "fetched_at": str(fallback_meta.get("last_update_at") or _now()),
                    "age_seconds": 0.0,
                    "latency_ms": round(float(fallback_meta.get("latency_ms") or 0.0), 2),
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
                    "transport": str(fallback_meta.get("transport") or "http_polling"),
                    "connected": bool(fallback_meta.get("connected")),
                    "fallback": bool(fallback_meta.get("fallback")),
                    "stale": bool(fallback_meta.get("stale")),
                    "degraded": bool(fallback_meta.get("degraded")),
                    "confidence": str(fallback_meta.get("confidence") or "low"),
                    "last_update_at": str(fallback_meta.get("last_update_at") or _now()),
                    "exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                    "provider_last_update_at": str(fallback_meta.get("last_update_at") or _now()),
                    "provider_exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                }]
                return fallback_price, {
                    "requested_mode": str((settings or {}).get("price_fusion_mode") or "auto_depth").strip(),
                    "mode": "test_provider_fallback" if synthetic_test_provider else "emergency_single_source",
                    "reference_mode": "test_provider" if synthetic_test_provider else "ticker_fallback",
                    "risk_grade_mode": "test_provider" if synthetic_test_provider else "unavailable",
                    "synthetic_test_provider": bool(synthetic_test_provider),
                    "warnings": warnings,
                    "warning_code": str(primary_warning.get("code") or ""),
                    "warning_message": "；".join(
                        warning.get("message") or ""
                        for warning in warnings
                        if isinstance(warning, dict) and str(warning.get("message") or "").strip()
                    ),
                    "degraded": not bool(synthetic_test_provider),
                    "fallback_active": not bool(synthetic_test_provider),
                    "conservative_mode": not bool(synthetic_test_provider),
                    "high_risk_blocked": not bool(synthetic_test_provider),
                    "high_risk_block_reason": "" if synthetic_test_provider else "目前可用 order book 來源不足，只能提供 degraded reference price",
                    "providers_used": providers_used,
                    "excluded_providers": excluded,
                    "provider_errors": errors,
                    "resolved_source": fallback_source,
                    "reference_price_points": fallback_value,
                    "risk_grade_price_points": fallback_value if synthetic_test_provider else None,
                    "reference_provider_count": 1,
                    "risk_grade_provider_count": 1 if synthetic_test_provider else 0,
                    "reference_weights_sum_percent": 100.0,
                    "risk_grade_weights_sum_percent": 100.0 if synthetic_test_provider else 0.0,
                    "depth_levels": depth_levels,
                    "depth_band_percent": depth_band_percent,
                    "min_orderbook_coverage_percent": min_orderbook_coverage_percent,
                    "max_single_provider_weight_percent": max_single_provider_weight_percent,
                    "min_provider_count": min_provider_count,
                    "median_midpoint_points": fallback_value,
                    "transport_state": self._transport_state_from_provider_rows(
                        providers_used,
                        warnings=warnings,
                        degraded=not bool(synthetic_test_provider),
                        conservative_mode=not bool(synthetic_test_provider),
                        min_provider_count=min_provider_count,
                        ws_enabled=self._price_stream_ws_enabled(settings),
                    ),
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
                **self._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn),
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
                    "transport": str(snap.get("transport") or "http_polling"),
                    "connected": bool(snap.get("connected")),
                    "fallback": bool(snap.get("fallback")),
                    "stale": bool(snap.get("stream_stale")),
                    "degraded": bool(snap.get("stream_degraded")),
                    "confidence": str(snap.get("stream_confidence") or "medium"),
                    "last_update_at": str(snap.get("provider_last_update_at") or snap.get("fetched_at") or ""),
                    "exclusion_reason": str(snap.get("provider_exclusion_reason") or message or reason),
                })
                continue
            reference_snapshots.append(snap)

        snapshots = reference_snapshots
        if not snapshots:
            try:
                fallback_price, fallback_source, fallback_meta = self._call_with_optional_conn(
                    self._fetch_live_price_points,
                    market_symbol,
                    with_meta=True,
                    settings=settings,
                    conn=conn,
                )
                synthetic_test_provider = str(fallback_source or "") == "test_live_price_provider"
                if not synthetic_test_provider:
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
                fallback_used = [{
                    "source": fallback_source,
                    "label": PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
                    "price_points": fallback_value,
                    "midpoint_points": fallback_value,
                    "depth_score": 0.0,
                    "effective_depth_score": 0.0,
                    "depth_density_score": 0.0,
                    "reference_weight_percent": 100.0,
                    "risk_grade_weight_percent": 100.0 if synthetic_test_provider else 0.0,
                    "normalized_weight_percent": 100.0,
                    "raw_normalized_weight_percent": 100.0,
                    "risk_grade_eligible": bool(synthetic_test_provider),
                    "coverage_insufficient": not bool(synthetic_test_provider),
                    "coverage_warning_message": "" if synthetic_test_provider else "資料截斷，不代表該交易所真實深度不足；目前僅納入 reference price，不納入高風險風控權重。",
                    "quantity_unit": "n/a",
                    "quantity_unit_label": "n/a",
                    "quantity_unit_confirmed": False,
                    "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                    "best_bid_points": None,
                    "best_ask_points": None,
                    "spread_percent": None,
                    "bid_notional_points": None,
                    "ask_notional_points": None,
                    "fetched_at": str(fallback_meta.get("last_update_at") or _now()),
                    "age_seconds": 0.0,
                    "latency_ms": round(float(fallback_meta.get("latency_ms") or 0.0), 2),
                    "midpoint_deviation_percent": 0.0,
                    "raw_bid_levels_count": 0,
                    "raw_ask_levels_count": 0,
                    "used_bid_levels_count": 0,
                    "used_ask_levels_count": 0,
                    "bid_coverage_percent": 0.0,
                    "ask_coverage_percent": 0.0,
                    "bid_reached_lower_bound": False,
                    "ask_reached_upper_bound": False,
                    "orderbook_truncated": not bool(synthetic_test_provider),
                    "coverage_ratio_percent": 0.0,
                    "depth_levels_requested": depth_levels,
                    "provider_depth_request_limit": 0,
                    "provider_depth_limit_reached": False,
                    "transport": str(fallback_meta.get("transport") or "http_polling"),
                    "connected": bool(fallback_meta.get("connected")),
                    "fallback": bool(fallback_meta.get("fallback")),
                    "stale": bool(fallback_meta.get("stale")),
                    "degraded": bool(fallback_meta.get("degraded")),
                    "confidence": str(fallback_meta.get("confidence") or "low"),
                    "last_update_at": str(fallback_meta.get("last_update_at") or _now()),
                    "exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                    "provider_last_update_at": str(fallback_meta.get("last_update_at") or _now()),
                    "provider_exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                }]
                return fallback_price, {
                    "requested_mode": str((settings or {}).get("price_fusion_mode") or "auto_depth").strip(),
                    "mode": "test_provider_fallback" if synthetic_test_provider else "quality_filtered_single_source",
                    "reference_mode": "test_provider" if synthetic_test_provider else "ticker_fallback",
                    "risk_grade_mode": "test_provider" if synthetic_test_provider else "unavailable",
                    "synthetic_test_provider": bool(synthetic_test_provider),
                    "warnings": warnings,
                    "warning_code": str(primary_warning.get("code") or ""),
                    "warning_message": "；".join(
                        warning.get("message") or ""
                        for warning in warnings
                        if isinstance(warning, dict) and str(warning.get("message") or "").strip()
                    ),
                    "degraded": not bool(synthetic_test_provider),
                    "fallback_active": not bool(synthetic_test_provider),
                    "conservative_mode": not bool(synthetic_test_provider),
                    "high_risk_blocked": not bool(synthetic_test_provider),
                    "high_risk_block_reason": "" if synthetic_test_provider else "目前可用 order book 來源不足，只能提供 degraded reference price",
                    "providers_used": fallback_used,
                    "excluded_providers": excluded_providers,
                    "provider_errors": errors,
                    "resolved_source": fallback_source,
                    "reference_price_points": fallback_value,
                    "risk_grade_price_points": fallback_value if synthetic_test_provider else None,
                    "reference_provider_count": 1,
                    "risk_grade_provider_count": 1 if synthetic_test_provider else 0,
                    "reference_weights_sum_percent": 100.0,
                    "risk_grade_weights_sum_percent": 100.0 if synthetic_test_provider else 0.0,
                    "depth_levels": depth_levels,
                    "depth_band_percent": depth_band_percent,
                    "min_orderbook_coverage_percent": min_orderbook_coverage_percent,
                    "max_single_provider_weight_percent": max_single_provider_weight_percent,
                    "min_provider_count": min_provider_count,
                    "median_midpoint_points": median_midpoint,
                    "transport_state": self._transport_state_from_provider_rows(
                        fallback_used,
                        warnings=warnings,
                        degraded=not bool(synthetic_test_provider),
                        conservative_mode=not bool(synthetic_test_provider),
                        min_provider_count=min_provider_count,
                        ws_enabled=self._price_stream_ws_enabled(settings),
                    ),
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
        degrading_warning_present = any(self._price_fusion_warning_is_degrading(item) for item in warnings)
        degrading_exclusion_present = any(self._price_fusion_exclusion_is_degrading(item) for item in excluded_providers)
        fallback_active = reference_model["resolved_mode"] in {"auto_depth_fallback", "equal_weight_fallback"}
        degraded = bool(degrading_exclusion_present or degrading_warning_present or fallback_active or conservative_mode)
        warning_only = bool((warnings or excluded_providers)) and not degraded
        reference_value = float(Decimal(str(reference_price)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))
        transport_state = self._transport_state_from_provider_rows(
            snapshots,
            warnings=warnings,
            degraded=degraded,
            conservative_mode=conservative_mode,
            min_provider_count=min_provider_count,
            ws_enabled=self._price_stream_ws_enabled(settings),
        )
        degraded = bool(degraded or transport_state.get("degraded"))
        if degraded:
            warning_only = False
        if not warning_message and str(transport_state.get("message") or "").strip():
            warning_message = str(transport_state.get("message") or "").strip()
        risk_value = (
            float(Decimal(str(risk_grade_price)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))
            if risk_grade_price is not None and not conservative_mode
            else None
        )
        return reference_value, {
            "requested_mode": mode,
            "mode": reference_model["resolved_mode"],
            "reference_mode": "reference_price",
            "risk_grade_mode": risk_model["resolved_mode"] if risk_model else "unavailable",
            "synthetic_test_provider": False,
            "warnings": warnings,
            "warning_code": str(primary_warning.get("code") or ""),
            "warning_message": warning_message,
            "degraded": degraded,
            "warning_only": warning_only,
            "fallback_active": fallback_active,
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
                    "transport": str(snap.get("transport") or "http_polling"),
                    "connected": bool(snap.get("connected")),
                    "fallback": bool(snap.get("fallback")),
                    "stale": bool(snap.get("stream_stale")),
                    "degraded": bool(snap.get("stream_degraded")),
                    "confidence": str(snap.get("stream_confidence") or "medium"),
                    "last_update_at": str(snap.get("provider_last_update_at") or snap.get("fetched_at") or ""),
                    "exclusion_reason": str(snap.get("provider_exclusion_reason") or ""),
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
            "transport_state": transport_state,
        }

    def _default_price_fusion_market_symbol(self, conn):
        rows = conn.execute("SELECT * FROM trading_markets ORDER BY sort_order ASC, symbol ASC").fetchall()
        for row in rows:
            symbol = str(row["symbol"] or "").strip().upper()
            if self._market_supports_live_price_on_conn(conn, symbol):
                return symbol
        catalog_symbols = self._list_live_price_market_symbols(conn)
        return catalog_symbols[0] if catalog_symbols else ""

    def _root_price_fusion_status_on_conn(self, conn, *, market_symbol=""):
        settings = self._settings_payload(conn)
        configured_source = str(settings.get("price_source") or FUSED_PRICE_SOURCE)
        requested_mode = str(settings.get("price_fusion_mode") or "auto_depth")
        requested_symbol = str(market_symbol or "").strip().upper()
        resolved_symbol = self._normalize_market_symbol_on_conn(conn, requested_symbol) if requested_symbol else ""
        symbol = resolved_symbol or self._default_price_fusion_market_symbol(conn)
        display_symbol = self._market_display_symbol_on_conn(conn, symbol)
        live_supported = bool(symbol and self._market_supports_live_price_on_conn(conn, symbol))
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
            transport_state = {
                "mode": "inactive",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": False,
                "confidence": "manual",
                "provider_count": 0,
                "last_update_at": "",
                "exclusion_reason": "",
                "message": "目前價格來源不是融合價格；只有切回融合價格後才會計算各 API 即時占比。",
            }
            payload.update({
                "state": "inactive",
                "message": transport_state["message"],
                "degraded": False,
                "fallback_active": False,
                "conservative_mode": False,
                "weights_sum_percent": 0.0,
                "providers_used": [],
                "excluded_providers": [],
                "resolved_mode": requested_mode,
                "resolved_source": configured_source,
                "price_points": None,
                "transport_state": transport_state,
                "connected": False,
                "fallback": False,
                "stale": False,
                "confidence": "manual",
                "provider_count": 0,
                "last_update_at": "",
                "exclusion_reason": "",
            })
            return payload
        if not live_supported:
            transport_state = {
                "mode": "unsupported",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": True,
                "confidence": "low",
                "provider_count": 0,
                "last_update_at": "",
                "exclusion_reason": "market_not_supported",
                "message": "這個市場目前沒有支援即時融合價格來源。",
            }
            payload.update({
                "state": "unsupported",
                "message": transport_state["message"],
                "degraded": True,
                "fallback_active": False,
                "conservative_mode": False,
                "weights_sum_percent": 0.0,
                "providers_used": [],
                "excluded_providers": [],
                "resolved_mode": requested_mode,
                "resolved_source": FUSED_PRICE_SOURCE,
                "price_points": None,
                "transport_state": transport_state,
                "connected": False,
                "fallback": False,
                "stale": False,
                "confidence": "low",
                "provider_count": 0,
                "last_update_at": "",
                "exclusion_reason": "market_not_supported",
            })
            return payload
        price_points, details = self._fetch_weighted_fused_price_points(symbol, settings=settings, conn=conn)
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
            "transport_state": dict((details or {}).get("transport_state") or {}),
            "connected": bool(((details or {}).get("transport_state") or {}).get("connected")),
            "fallback": bool(((details or {}).get("transport_state") or {}).get("fallback")),
            "stale": bool(((details or {}).get("transport_state") or {}).get("stale")),
            "confidence": str((((details or {}).get("transport_state") or {}).get("confidence") or "medium")),
            "provider_count": int((((details or {}).get("transport_state") or {}).get("provider_count") or 0)),
            "last_update_at": str((((details or {}).get("transport_state") or {}).get("last_update_at") or "")),
            "exclusion_reason": str((((details or {}).get("transport_state") or {}).get("exclusion_reason") or "")),
            "risk_grade_usable": not high_risk_blocked and int((details or {}).get("risk_grade_provider_count") or 0) > 0,
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
            symbol = self._normalize_market_symbol_on_conn(conn, requested_symbol)
            defaulted_market = not bool(symbol)
            if symbol:
                market_row = self._market(conn, symbol)
            else:
                market_row = conn.execute(
                    "SELECT * FROM trading_markets WHERE enabled=1 AND spot_enabled=1 ORDER BY sort_order ASC, symbol ASC"
                ).fetchall()
                market_row = next(iter(market_row), None)
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
                "display_market_symbol": self._market_display_symbol_on_conn(conn, resolved_symbol),
                "refresh_interval_ms": 2000,
                "server_time": _now(),
                "price_type": reference_context["price_type"],
                "source": reference_context["source"],
                "confidence": reference_context["confidence"],
                "stale": reference_context["stale"],
                "degraded": reference_context["degraded"],
                "provider_count": reference_context["provider_count"],
                "connected": bool((price_meta or {}).get("connected")),
                "fallback": bool((price_meta or {}).get("fallback")),
                "last_update_at": str((price_meta or {}).get("last_update_at") or ""),
                "exclusion_reason": str((price_meta or {}).get("exclusion_reason") or ""),
                "price_health": str((price_meta or {}).get("price_health") or "healthy"),
                "fallback_reason": str((price_meta or {}).get("fallback_reason") or ""),
                "excluded_sources": list((price_meta or {}).get("excluded_sources") or []),
                "warnings": list((price_meta or {}).get("warnings") or []),
                "high_risk_blocked": bool((price_meta or {}).get("high_risk_blocked")),
                "high_risk_block_reason": str((price_meta or {}).get("high_risk_block_reason") or ""),
                "risk_grade_usable": bool((risk_grade_context or {}).get("risk_grade_usable")),
                "defaulted_market": defaulted_market,
                "reference_price_context": reference_context,
                "risk_grade_price_context": risk_grade_context,
                "transport_state": dict((price_meta or {}).get("transport_state") or {}),
            }
        finally:
            conn.close()

    def _fetch_live_price_points(self, market_symbol, *, with_meta=False, settings=None, conn=None):
        market_symbol = self._normalize_market_symbol_on_conn(conn, market_symbol) if conn is not None else self.normalize_market_symbol(market_symbol)
        if not self._live_price_symbol(market_symbol, conn=conn):
            raise ValueError("live price is not supported for this market")
        settings = settings or {}
        if self.live_price_provider:
            price = self.live_price_provider(market_symbol)
            price_points = self._price_points_from_float(price, source="test_live_price_provider")
            meta = {
                "ws_supported": False,
                "transport": "test_provider",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": False,
                "confidence": "low",
                "provider_count": 1,
                "last_update_at": _now(),
                "exclusion_reason": "",
                "latency_ms": 0.0,
                "synthetic_test_provider": True,
            }
            return (price_points, "test_live_price_provider", meta) if with_meta else (price_points, "test_live_price_provider")
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
                price_points, provider_meta = self._call_with_optional_conn(
                    fetcher,
                    market_symbol,
                    settings=settings,
                    with_meta=True,
                    conn=conn,
                )
                return (price_points, source, provider_meta) if with_meta else (price_points, source)
            except Exception as exc:
                errors.append(f"{source}: {str(exc)[:120]}")
        raise ValueError("; ".join(errors) or "all live price providers failed")

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
        lookback = max(60, int(lookback_seconds or 60))
        interval_seconds = 60 if interval == "1m" else 900
        limit = max(2, min(int(math.ceil(lookback / interval_seconds)) + 2, 240))
        candles = self._fetch_indicator_candles(market_symbol, limit=limit, interval=interval, conn=conn)
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
            "connected": False,
            "fallback": False,
            "last_update_at": "",
            "exclusion_reason": "",
            "confidence": "low",
            "synthetic_test_provider": False,
        }
        if configured_source == "manual_root" or not self._live_price_symbol(symbol, conn=conn):
            price = market["manual_price_points"]
            source = "manual_root" if configured_source == "manual_root" else str(market["price_source"] or "manual_root")
            transport_state = {
                "mode": "manual_root",
                "connected": False,
                "fallback": False,
                "stale": False,
                "degraded": True,
                "confidence": "manual",
                "provider_count": 0,
                "last_update_at": str(market["updated_at"] or ""),
                "exclusion_reason": "manual_root_active",
                "message": "目前使用手動價格，不是即時市場 provider input。",
            }
            price_meta["reference_price_points"] = float(Decimal(str(price or "0")))
            price_meta["risk_grade_price_points"] = float(Decimal(str(price or "0")))
            price_meta["resolved_source"] = source
            price_meta["degraded"] = True
            price_meta["connected"] = False
            price_meta["fallback"] = False
            price_meta["last_update_at"] = transport_state["last_update_at"]
            price_meta["exclusion_reason"] = transport_state["exclusion_reason"]
            price_meta["confidence"] = "manual"
            price_meta["transport_state"] = transport_state
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
            if configured_source == FUSED_PRICE_SOURCE:
                price, fusion_details = self._call_with_optional_conn(
                    self._fetch_weighted_fused_price_points,
                    symbol,
                    settings=settings,
                    conn=conn,
                )
                live_source = FUSED_PRICE_SOURCE
                live_transport_meta = dict((fusion_details or {}).get("transport_state") or {})
            elif self.live_price_provider:
                price, live_source, live_transport_meta = self._fetch_live_price_points(symbol, with_meta=True, settings=settings, conn=conn)
            else:
                price, live_source, live_transport_meta = self._fetch_live_price_points(symbol, with_meta=True, settings=settings, conn=conn)
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
                transport_state = {
                    "mode": "cached_fallback",
                    "connected": False,
                    "fallback": True,
                    "stale": True,
                    "degraded": True,
                    "confidence": "low",
                    "provider_count": 1,
                    "last_update_at": "",
                    "exclusion_reason": str(exc),
                    "message": "即時價格失敗，已退回最後健康快取。",
                }
                price_meta.update({
                    "price_health": "fallback",
                    "fallback_reason": str(exc),
                    "excluded_sources": [],
                    "reference_price_points": old_price,
                    "risk_grade_price_points": None,
                    "resolved_source": source,
                    "reference_provider_count": 1,
                    "risk_grade_provider_count": 0,
                    "high_risk_blocked": True,
                    "high_risk_block_reason": "目前使用最後健康快取，不能作為風控級價格。",
                    "stale": bool(transport_state["stale"]),
                    "degraded": bool(transport_state["degraded"]),
                    "connected": bool(transport_state["connected"]),
                    "fallback": bool(transport_state["fallback"]),
                    "last_update_at": str(transport_state["last_update_at"]),
                    "exclusion_reason": str(transport_state["exclusion_reason"]),
                    "confidence": str(transport_state["confidence"]),
                    "risk_grade_usable": False,
                    "transport_state": transport_state,
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
        history_sql, _history_ctx = self._format_routed_sql(
            """
            SELECT 1
            FROM {orders}
            WHERE market_symbol=?
            UNION ALL
            SELECT 1 FROM trading_margin_positions WHERE market_symbol=?
            UNION ALL
            SELECT 1 FROM trading_futures_positions WHERE market_symbol=?
            LIMIT 1
            """
        )
        has_live_history = bool(conn.execute(history_sql, (symbol, symbol, symbol)).fetchone())
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
            fusion_details.get("conservative_mode")
            or fusion_details.get("fallback_active")
            or fusion_details.get("degraded")
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
                "degraded": True,
                "risk_grade_usable": False,
                "connected": bool((fusion_details.get("transport_state") or {}).get("connected")),
                "fallback": bool((fusion_details.get("transport_state") or {}).get("fallback")),
                "stale": bool((fusion_details.get("transport_state") or {}).get("stale")),
                "last_update_at": str((fusion_details.get("transport_state") or {}).get("last_update_at") or ""),
                "exclusion_reason": str((fusion_details.get("transport_state") or {}).get("exclusion_reason") or reason_text),
                "confidence": str((fusion_details.get("transport_state") or {}).get("confidence") or "low"),
                "synthetic_test_provider": bool(fusion_details.get("synthetic_test_provider")),
                "warning_only": False,
                "transport_state": dict((fusion_details.get("transport_state") or {})),
            })
            self._audit_event(
                conn,
                "TRADING_PRICE_FUSION_DEGRADED",
                "fused trading price degraded or partially excluded providers",
                market_symbol=symbol,
                severity="critical" if fusion_details.get("conservative_mode") else "warning",
                metadata={
                    "resolved_source": str(fusion_details.get("resolved_source") or live_source or FUSED_PRICE_SOURCE),
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
            transport_state = dict((fusion_details.get("transport_state") or {}))
            risk_grade_usable = bool(
                (fusion_details.get("risk_grade_provider_count") or 0)
                and not bool(transport_state.get("stale"))
                and not bool(transport_state.get("degraded"))
                and not bool(transport_state.get("fallback"))
                and not bool(fusion_details.get("conservative_mode"))
            )
            price_meta.update({
                "reference_price_points": fusion_details.get("reference_price_points"),
                "risk_grade_price_points": fusion_details.get("risk_grade_price_points"),
                "resolved_source": str(fusion_details.get("resolved_source") or live_source or FUSED_PRICE_SOURCE),
                "reference_provider_count": int(fusion_details.get("reference_provider_count") or 0),
                "risk_grade_provider_count": int(fusion_details.get("risk_grade_provider_count") or 0),
                "warnings": list(fusion_details.get("warnings") or []),
                "excluded_sources": [
                    str(item.get("source") or "")
                    for item in (fusion_details.get("excluded_providers") or [])
                    if str(item.get("source") or "").strip()
                ],
                "risk_grade_usable": risk_grade_usable,
                "high_risk_blocked": False,
                "high_risk_block_reason": "",
                "stale": bool(transport_state.get("stale")),
                "degraded": bool(transport_state.get("degraded")),
                "connected": bool(transport_state.get("connected")),
                "fallback": bool(transport_state.get("fallback")),
                "last_update_at": str(transport_state.get("last_update_at") or ""),
                "exclusion_reason": str(transport_state.get("exclusion_reason") or ""),
                "confidence": str(transport_state.get("confidence") or "high"),
                "synthetic_test_provider": bool(fusion_details.get("synthetic_test_provider")),
                "warning_only": bool(fusion_details.get("warning_only")),
                "transport_state": transport_state,
            })
        else:
            live_price = float(_to_decimal(price, name="live_price_points", minimum=0.00000001))
            transport_state = {
                "mode": str((live_transport_meta or {}).get("transport") or "http_polling"),
                "connected": bool((live_transport_meta or {}).get("connected")),
                "fallback": bool((live_transport_meta or {}).get("fallback")),
                "stale": bool((live_transport_meta or {}).get("stale")),
                "degraded": bool((live_transport_meta or {}).get("degraded")),
                "confidence": str((live_transport_meta or {}).get("confidence") or "medium"),
                "provider_count": int((live_transport_meta or {}).get("provider_count") or 1),
                "last_update_at": str((live_transport_meta or {}).get("last_update_at") or ""),
                "exclusion_reason": str((live_transport_meta or {}).get("exclusion_reason") or ""),
                "message": "",
            }
            synthetic_test_provider = str(live_source or "") == "test_live_price_provider" or bool((live_transport_meta or {}).get("synthetic_test_provider"))
            risk_grade_unusable = bool(
                synthetic_test_provider
                or transport_state["fallback"]
                or transport_state["stale"]
                or transport_state["degraded"]
            )
            price_meta["reference_price_points"] = live_price
            price_meta["risk_grade_price_points"] = None if risk_grade_unusable else live_price
            price_meta["resolved_source"] = str(live_source or configured_source or "manual_root")
            price_meta["reference_provider_count"] = 1
            price_meta["risk_grade_provider_count"] = 0 if risk_grade_unusable else 1
            price_meta["high_risk_blocked"] = bool(risk_grade_unusable and not synthetic_test_provider)
            if risk_grade_unusable and not synthetic_test_provider:
                price_meta["high_risk_block_reason"] = "目前 provider input 已降級 / stale / fallback，不能作為風控級價格。"
            price_meta["stale"] = bool(transport_state["stale"])
            price_meta["degraded"] = bool(transport_state["degraded"])
            price_meta["connected"] = bool(transport_state["connected"])
            price_meta["fallback"] = bool(transport_state["fallback"])
            price_meta["last_update_at"] = str(transport_state["last_update_at"])
            price_meta["exclusion_reason"] = str(transport_state["exclusion_reason"])
            price_meta["confidence"] = str(transport_state["confidence"])
            price_meta["risk_grade_usable"] = not bool(risk_grade_unusable)
            price_meta["transport_state"] = transport_state
            price_meta["synthetic_test_provider"] = bool(synthetic_test_provider)
            if transport_state["fallback"] and not price_meta["fallback_reason"]:
                price_meta["fallback_reason"] = "WebSocket provider input 已斷線，已自動切回 HTTP polling。"
            elif transport_state["stale"] and not price_meta["fallback_reason"]:
                price_meta["fallback_reason"] = "WebSocket provider input 已過時，已改用 HTTP polling。"
        active_transport_state = dict(price_meta.get("transport_state") or {})
        if active_transport_state and not price_meta.get("fallback_reason") and (
            bool(active_transport_state.get("fallback"))
            or bool(active_transport_state.get("stale"))
            or bool(active_transport_state.get("degraded"))
        ):
            price_meta["fallback_reason"] = str(active_transport_state.get("message") or active_transport_state.get("exclusion_reason") or "").strip()
        if configured_source == FUSED_PRICE_SOURCE and fusion_details and high_risk and fusion_details.get("risk_grade_price_points") is not None:
            price = float(_to_decimal(fusion_details.get("risk_grade_price_points"), name="risk_grade_price_points", minimum=0.00000001))
        now = _now()
        conn.execute(
            "UPDATE trading_markets SET manual_price_points=?, price_source=?, updated_at=? WHERE symbol=?",
            (price, live_source, now, symbol),
        )
        return (price, live_source, price_meta) if with_meta else (price, live_source)

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
        return conn.execute("SELECT * FROM trading_trial_credits WHERE user_id=?", (int(user_id),)).fetchone()

    def _ensure_trial_credit(self, conn, user_id, *, actor=None, allow_reclaim=True):
        user_id = int(user_id)
        if self._is_root_user_id(conn, user_id):
            return None
        row = self._trial_credit_row(conn, user_id)
        now = _now()
        if not row:
            expires_at = trial_credit_expires_at(now, days_valid=TRIAL_CREDIT_DAYS)
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
        next_status = trial_credit_status_after_delta(
            status or row["status"],
            next_available=next_available,
            next_locked=next_locked,
            next_deployed=next_deployed,
        )
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
        trial_units = trial_units_for_buy(
            quantity_units=quantity_units,
            trial_used_points=trial_used_points,
            total_points=total_points,
        )
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
        allocation = trial_allocate_sell_result(
            available_trial_units=int(trial_pos["quantity_units"] or 0),
            trial_cost_total=int(trial_pos["trial_cost_points"] or 0),
            quantity_units=quantity_units,
            net_credit_points=net_credit_points,
        )
        conn.execute(
            """
            UPDATE trading_trial_position_costs
            SET quantity_units=?, trial_cost_points=?, updated_at=?
            WHERE user_id=? AND market_symbol=?
            """,
            (allocation["remaining_units"], allocation["remaining_cost"], _now(), int(user_id), market_symbol),
        )
        self._trial_delta(
            conn,
            user_id,
            available_delta=allocation["trial_repaid_points"],
            deployed_delta=-allocation["trial_cost_points"],
        )
        return {
            "trial_units": allocation["trial_units"],
            "trial_cost_points": allocation["trial_cost_points"],
            "trial_repaid_points": allocation["trial_repaid_points"],
            "trial_profit_points": allocation["trial_profit_points"],
            "wallet_credit_points": allocation["wallet_credit_points"],
        }

    def _cancel_trial_reclaim_sell_orders(self, conn, user_id, *, actor, reason, ctx=None):
        route_ctx = self._routing_ctx_for_read(ctx)
        orders_table = resolve_table("orders", route_ctx)
        positions_table = resolve_table("positions", route_ctx)
        orders = conn.execute(
            f"""
            SELECT o.*
            FROM {orders_table} o
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
                    f"""
                    UPDATE {positions_table}
                    SET quantity_units=quantity_units+?,
                        locked_quantity_units=MAX(locked_quantity_units-?, 0),
                        updated_at=?
                    WHERE user_id=? AND market_symbol=?
                    """,
                    (remaining_units, remaining_units, _now(), int(user_id), order["market_symbol"]),
                )
            conn.execute(
                f"""
                UPDATE {orders_table}
                SET status='cancelled', reason=?, updated_at=?
                WHERE id=?
                """,
                (f"{reason}: trial credit reclaim unlocked sell order", _now(), order["id"]),
            )
            updated_order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone()
            self._matching_orderbook_apply_order(updated_order, ctx=route_ctx)
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

    def _reclaim_trial_credit(self, conn, user_id, *, actor=None, reason="TRIAL_CREDIT_RECLAIM", ctx=None):
        row = self._trial_credit_row(conn, user_id)
        if not row or row["status"] != "active":
            return row
        actor = actor or self._system_actor()
        reclaimed_before_sell = int(row["available_points"] or 0)
        route_ctx = self._routing_ctx_for_read(ctx)
        orders_table = resolve_table("orders", route_ctx)
        positions_table = resolve_table("positions", route_ctx)
        for order in conn.execute(
            f"""
            SELECT * FROM {orders_table}
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
                    ctx=route_ctx,
                )
            conn.execute(
                f"""
                UPDATE {orders_table}
                SET status='cancelled', frozen_points=0, trial_frozen_points=0, chain_frozen_points=0,
                    reason=?, updated_at=?
                WHERE id=?
                """,
                (f"{reason}: trial credit reclaimed", _now(), order["id"]),
            )
            updated_order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone()
            self._matching_orderbook_apply_order(updated_order, ctx=route_ctx)
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
        self._cancel_trial_reclaim_sell_orders(conn, user_id, actor=actor, reason=reason, ctx=route_ctx)
        for trial_pos in conn.execute(
            "SELECT * FROM trading_trial_position_costs WHERE user_id=? AND quantity_units>0 ORDER BY market_symbol",
            (int(user_id),),
        ).fetchall():
            position = self._position(conn, user_id, trial_pos["market_symbol"], ctx=route_ctx)
            sell_units = min(int(position["quantity_units"] or 0), int(trial_pos["quantity_units"] or 0))
            if sell_units <= 0:
                continue
            market = self._market(conn, trial_pos["market_symbol"])
            current_price, price_source = self._current_market_price_points(conn, market)
            order_uuid = str(uuid.uuid4())
            now = _now()
            conn.execute(
                f"""
                UPDATE {positions_table}
                SET quantity_units=quantity_units-?, locked_quantity_units=locked_quantity_units+?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (sell_units, sell_units, now, int(user_id), trial_pos["market_symbol"]),
            )
            cur = conn.execute(
                f"""
                INSERT INTO {orders_table} (
                    order_uuid, user_id, market_symbol, side, order_type, funding_mode, execution_mode,
                    quantity_units, limit_price_points, execution_price_points, status,
                    frozen_points, trial_frozen_points, chain_frozen_points, fee_points,
                    filled_quantity_units, reason, created_at, updated_at
                ) VALUES (?, ?, ?, 'sell', 'market', 'trial_mixed', 'house_counterparty',
                    ?, NULL, ?, 'open', 0, 0, 0, 0, 0, ?, ?, ?)
                """,
                (order_uuid, int(user_id), trial_pos["market_symbol"], sell_units, current_price, reason, now, now),
            )
            order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (cur.lastrowid,)).fetchone()
            fill = self._execute_order(conn, order, market, actor=actor, ctx=route_ctx)
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
        return funding_payload_helper(
            self,
            conn,
            user_id,
            root_simulated_initial_points=ROOT_SIMULATED_INITIAL_POINTS,
            trial_credit_days=TRIAL_CREDIT_DAYS,
        )

    def _position_payload(self, row):
        return position_payload(row, units_to_quantity=units_to_quantity)

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
        if not position or position["status"] != "open":
            return position
        if self._is_root_user_id(conn, int(position["user_id"])):
            return position
        margin_positions_table, route_ctx = self._resolve_table("margin_positions", ctx, action="margin_interest")
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
                f"UPDATE {margin_positions_table} SET interest_accrued_hours=?, interest_carry_micropoints=?, updated_at=? WHERE id=?",
                (total_hours, next_carry, _now(), position["id"]),
            )
            return conn.execute(f"SELECT * FROM {margin_positions_table} WHERE id=?", (position["id"],)).fetchone()

        user_id = int(position["user_id"])
        wallet_payload = self._wallet_payload(conn, user_id, ctx=route_ctx)
        available = int(wallet_payload.get("points_balance") or 0)
        paid = min(due_points, available)
        capitalized = due_points - paid
        ledger_uuid = None
        if paid:
            ledger_uuid = self._ledger(
                conn,
                ctx=route_ctx,
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
            f"""
            UPDATE {margin_positions_table}
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
        return conn.execute(f"SELECT * FROM {margin_positions_table} WHERE id=?", (position["id"],)).fetchone()

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
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._ensure_trial_credit(conn, user_id)
            conn.commit()
            tables, route_ctx = self._sql_tables()
            positions_table = tables["positions"]
            orders_table = tables["orders"]
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
            markets = sorted(markets, key=self._runtime_market_sort_key)
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
                for row in conn.execute(
                    f"SELECT * FROM {positions_table} WHERE user_id=? ORDER BY market_symbol",
                    (int(user_id),),
                ).fetchall()
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
            raw_orders = conn.execute(
                f"SELECT * FROM {orders_table} WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (int(user_id),),
            ).fetchall()
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
                    f"SELECT f.id, o.order_uuid FROM trading_fills f JOIN {orders_table} o ON o.id=f.order_id WHERE f.user_id=? ORDER BY f.id DESC LIMIT 50",
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
        if not self._actor_id(actor):
            raise ValueError("login required")
        payload = payload or {}
        bot_config = payload.get("bot_config") if isinstance(payload.get("bot_config"), dict) else {}
        if bot_config:
            payload = {**bot_config, **payload}
        candles = payload.get("candles") or []
        if not isinstance(candles, list) or len(candles) < 2:
            raise ValueError("candles are required for backtest")
        active_max_candles = self.get_max_backtest_candles()
        if len(candles) > active_max_candles:
            raise ValueError(f"candles length must be <= {active_max_candles}")
        start_time = str(payload.get("start_time") or "").strip()
        end_time = str(payload.get("end_time") or "").strip()
        if start_time or end_time:
            candles = filter_backtest_candles_by_range(
                candles,
                start_time=start_time,
                end_time=end_time,
            )
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
        state = build_backtest_initial_state(
            cash=cash,
            initial_units=payload.get("initial_units") or 0,
            initial_avg_cost=payload.get("initial_avg_cost") or 0,
            initial_trade_count=payload.get("initial_trade_count") or 0,
            initial_candle_offset=payload.get("initial_candle_offset") or 0,
            initial_workflow_state=initial_workflow_state,
            grid_fee_rate=grid_fee_rate_percent,
        )
        workflow_indicator_series = self._build_workflow_indicator_series(candles) if strategy == "workflow" else []

        def _record_equity(global_index, candle, price):
            equity = backtest_equity_value(cash=state["cash"], units=state["units"], price=price)
            state["peak_value"], state["max_drawdown_percent"] = update_backtest_drawdown(
                peak_value=state["peak_value"],
                max_drawdown_percent=state["max_drawdown_percent"],
                equity=equity,
            )
            state["equity_curve"].append(
                build_backtest_equity_point(
                    global_index=global_index,
                    candle=candle,
                    price=price,
                    equity=equity,
                )
            )

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
                anchor_price = backtest_anchor_price(
                    recent_valid_prices=state.get("recent_valid_prices"),
                    last_valid_price=state.get("last_valid_price"),
                )
                if anchor_price > 0 and max_price_jump_percent > 0:
                    jump_percent = abs(price - anchor_price) * 100.0 / anchor_price
                    if jump_percent > max_price_jump_percent:
                        state["outlier_skipped_count"] += 1
                        if state["outlier_skipped_count"] <= 5:
                            range_warnings.append(
                                build_backtest_outlier_warning(
                                    global_index=global_index,
                                    candle=candle,
                                    price=price,
                                    anchor_price=anchor_price,
                                    max_price_jump_percent=max_price_jump_percent,
                                )
                            )
                        continue
                state["last_valid_price"] = price
                state["recent_valid_prices"] = push_recent_valid_price(
                    state["recent_valid_prices"],
                    price,
                    limit=5,
                )

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

        segment_count = backtest_segment_count(len(candles), BACKTEST_SEGMENT_CANDLES)
        for chunk in iter_backtest_segments(candles, BACKTEST_SEGMENT_CANDLES):
            _run_chunk(chunk)
        all_candles_raw = payload.get("candles") or []
        range_warnings = build_backtest_range_warnings(
            existing_warnings=range_warnings,
            start_time=start_time,
            end_time=end_time,
            all_candles_raw=all_candles_raw,
            candle_count=len(candles),
            max_backtest_candles=active_max_candles,
            segment_count=segment_count,
            max_backtest_candles_per_batch=BACKTEST_SEGMENT_CANDLES,
            outlier_skipped_count=state["outlier_skipped_count"],
            max_price_jump_percent=max_price_jump_percent,
        )
        return build_backtest_result_payload(
            state=state,
            candles=candles,
            strategy=strategy,
            market_symbol=market["symbol"],
            initial_cash=initial_cash,
            start_time=start_time,
            end_time=end_time,
            range_warnings=range_warnings,
            max_backtest_candles=active_max_candles,
            max_backtest_candles_per_batch=BACKTEST_SEGMENT_CANDLES,
            requested_candle_limit=payload.get("requested_candle_limit") or payload.get("candle_limit") or payload.get("limit") or len(candles),
            data_source=str(payload.get("data_source") or ("provided_candles" if payload.get("candles") else "")),
            provider_symbol=str(payload.get("provider_symbol") or ""),
            max_price_jump_percent=max_price_jump_percent,
            segment_count=segment_count,
        )

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
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            state = self._state(conn)
            reserve = self._reserve(conn)
            markets = [
                self._market_payload(row)
                for row in conn.execute("SELECT * FROM trading_markets ORDER BY sort_order ASC, symbol ASC").fetchall()
            ]
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
