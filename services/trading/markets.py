"""Pure market registry and provider mapping helpers.

These helpers normalize market aliases and provider mapping metadata without
performing any DB access or remote fetches. The legacy trading engine remains
responsible for orchestration and persistence.
"""

from services.trading_markets import (
    TRADING_MARKET_CATALOG_SEED_VERSION,
    get_market_definition,
    normalize_market_symbol,
)


def provider_mapping_capabilities(
    provider,
    *,
    ticker_capable_providers,
    depth_capable_providers,
    reference_price_capable_providers,
):
    return {
        "supports_ticker": 1 if provider in ticker_capable_providers else 0,
        "supports_depth": 1 if provider in depth_capable_providers else 0,
        "supports_candles": 1 if provider in reference_price_capable_providers else 0,
    }


def market_seed_compare_value(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return round(float(value), 8)
    if value is None:
        return None
    return value


def registry_seed_status(
    registry_row,
    mappings,
    *,
    registry_default_market_payload,
    provider_mapping_capabilities_func,
):
    source = str(registry_row.get("registry_source") or "catalog_seed").strip().lower() or "catalog_seed"
    catalog_definition = get_market_definition(registry_row.get("symbol"))
    catalog_seed_version = int(TRADING_MARKET_CATALOG_SEED_VERSION)
    applied_seed_version = int(registry_row.get("seed_version") or 0)
    if source == "custom":
        return {
            "registry_source": "custom",
            "seed_version": applied_seed_version,
            "catalog_seed_version": catalog_seed_version,
            "seed_sync_status": "custom",
            "seed_sync_reasons": [],
            "seed_sync_message": "此市場由 root 在資料庫中建立，DB 是唯一 source of truth。",
        }
    if not catalog_definition:
        return {
            "registry_source": source,
            "seed_version": applied_seed_version,
            "catalog_seed_version": catalog_seed_version,
            "seed_sync_status": "orphaned_seed",
            "seed_sync_reasons": ["catalog_definition_missing"],
            "seed_sync_message": "catalog 已不再定義此市場；目前以 DB registry 為唯一 source of truth。",
        }
    expected = registry_default_market_payload(catalog_definition)
    reasons = []
    compare_fields = (
        "base_asset",
        "quote_asset",
        "display_name",
        "display_quote_currency",
        "market_type",
        "enabled",
        "allow_spot",
        "allow_margin",
        "allow_bots",
        "allow_risk_grade_usage",
        "price_precision",
        "quantity_precision",
        "min_order_size",
        "max_order_size",
        "lot_size",
        "tick_size",
        "sort_order",
        "default_manual_price_points",
        "live_price_enabled",
        "reference_price_enabled",
        "btc_trade_enabled",
    )
    for field in compare_fields:
        if market_seed_compare_value(registry_row.get(field)) != market_seed_compare_value(expected.get(field)):
            reasons.append(field)
    expected_mappings = {}
    for provider, provider_symbol in dict(catalog_definition.get("provider_ids") or {}).items():
        capabilities = provider_mapping_capabilities_func(provider)
        expected_mappings[provider] = {
            "provider_symbol": str(provider_symbol or "").strip(),
            "supports_ticker": int(capabilities["supports_ticker"]),
            "supports_depth": int(capabilities["supports_depth"]),
            "supports_candles": int(capabilities["supports_candles"]),
            "enabled": 1 if str(provider_symbol or "").strip() else 0,
        }
    actual_mappings = {
        str(row["provider"] or "").strip(): {
            "provider_symbol": str(row["provider_symbol"] or "").strip(),
            "supports_ticker": int(row["supports_ticker"] or 0),
            "supports_depth": int(row["supports_depth"] or 0),
            "supports_candles": int(row["supports_candles"] or 0),
            "enabled": int(row["enabled"] or 0),
        }
        for row in mappings
    }
    if expected_mappings != actual_mappings:
        reasons.append("provider_mappings")
    status = "current" if not reasons else "drifted"
    message = (
        "此 seeded 市場仍與目前 catalog 定義一致。"
        if status == "current"
        else "此 seeded 市場已偏離目前 catalog 定義；DB registry 仍是執行期 source of truth。"
    )
    return {
        "registry_source": source,
        "seed_version": applied_seed_version,
        "catalog_seed_version": catalog_seed_version,
        "seed_sync_status": status,
        "seed_sync_reasons": reasons,
        "seed_sync_message": message,
    }


def build_market_alias_map(rows, *, include_disabled=True, display_symbol_from_parts):
    alias_map = {}
    for row in rows:
        if not include_disabled and not int(row["enabled"] or 0):
            continue
        symbol = str(row["symbol"] or "").strip().upper()
        if not symbol:
            continue
        alias_map[symbol] = symbol
        display_symbol = display_symbol_from_parts(
            base_asset=row["base_asset"],
            quote_currency=row["quote_asset"],
            display_quote_currency=row["display_quote_currency"],
        )
        if display_symbol:
            alias_map[display_symbol] = symbol
        display_name = str(row["display_name"] or "").strip().upper()
        if display_name:
            alias_map[display_name] = symbol
    return alias_map


def normalize_market_symbol_from_rows(rows, value, *, include_disabled=True, display_symbol_from_parts):
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    alias_map = build_market_alias_map(
        rows,
        include_disabled=include_disabled,
        display_symbol_from_parts=display_symbol_from_parts,
    )
    return alias_map.get(raw, normalize_market_symbol(raw))


def market_provider_ids_from_mappings(rows, *, support_field=None):
    provider_ids = {}
    for row in rows or []:
        provider = str(row["provider"] or "").strip()
        provider_symbol = str(row["provider_symbol"] or "").strip()
        if not provider or not provider_symbol or not int(row["enabled"] or 0):
            continue
        if support_field and not int(row[support_field] or 0):
            continue
        provider_ids[provider] = provider_symbol
    return provider_ids


def market_supports_mapping_rows(rows, *, support_field):
    return any(
        int(row["enabled"] or 0) and int(row[support_field] or 0) and str(row["provider_symbol"] or "").strip()
        for row in rows
    )


def market_display_symbol_from_registry_row(row, *, display_symbol_from_parts):
    if not row:
        return ""
    return display_symbol_from_parts(
        base_asset=row["base_asset"],
        quote_currency=row["quote_asset"],
        display_quote_currency=row["display_quote_currency"],
    ) or str(row["symbol"] or "").strip().upper()


def fallback_market_display_symbol(symbol, *, quote_currency=None):
    normalized = normalize_market_symbol(symbol)
    quote = str(quote_currency or "").strip().upper()
    if normalized.endswith("/POINTS"):
        return normalized[:-7] + "/USDT"
    if quote == "POINTS" and "/" in normalized:
        base, _sep, _tail = normalized.partition("/")
        return f"{base}/USDT"
    return normalized
