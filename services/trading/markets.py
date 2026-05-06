"""Trading market registry and provider mapping helpers.

This module owns market-alias normalization plus market-registry/provider-
mapping validation and orchestration. The legacy trading engine remains the
stable façade and delegates into this module.
"""

import json

from services.trading.constants import (
    DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT,
    DEPTH_CAPABLE_PROVIDERS,
    PRICE_PROVIDER_LABELS,
    REFERENCE_PRICE_CAPABLE_PROVIDERS,
    TICKER_CAPABLE_PROVIDERS,
)
from services.trading.catalog import (
    TRADING_MARKET_CATALOG_SEED_VERSION,
    get_market_definition,
    normalize_market_symbol,
)
from services.trading.validators import _to_float, _to_int, _to_price_float


def _now_text():
    from datetime import datetime

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


def provider_mapping_capabilities(
    provider,
    *,
    ticker_capable_providers=None,
    depth_capable_providers=None,
    reference_price_capable_providers=None,
):
    ticker_capable_providers = ticker_capable_providers or TICKER_CAPABLE_PROVIDERS
    depth_capable_providers = depth_capable_providers or DEPTH_CAPABLE_PROVIDERS
    reference_price_capable_providers = reference_price_capable_providers or REFERENCE_PRICE_CAPABLE_PROVIDERS
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
    provider_mapping_capabilities_func=None,
):
    provider_mapping_capabilities_func = provider_mapping_capabilities_func or provider_mapping_capabilities
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


def market_registry_audit(service, conn, *, actor=None, action="", market_symbol="", before=None, after=None):
    conn.execute(
        """
        INSERT INTO trading_market_registry_audit (
            actor_id, action, market_symbol, before_json, after_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            service._actor_id(actor),
            str(action or "").strip() or "market_registry_update",
            str(market_symbol or "").strip().upper(),
            _json_dumps(before or {}),
            _json_dumps(after or {}),
            _now_text(),
        ),
    )


def market_provider_mapping_payload(row, *, provider_labels=None):
    provider_labels = provider_labels or PRICE_PROVIDER_LABELS
    item = dict(row)
    for key in ("supports_ticker", "supports_depth", "supports_candles", "enabled"):
        item[key] = bool(item.get(key))
    item["provider_label"] = provider_labels.get(item.get("provider"), item.get("provider"))
    return item


def market_registry_payload(service, conn, registry_row, *, registry_default_market_payload):
    item = dict(registry_row)
    for key in (
        "enabled",
        "allow_spot",
        "allow_margin",
        "allow_bots",
        "allow_risk_grade_usage",
        "live_price_enabled",
        "reference_price_enabled",
        "btc_trade_enabled",
    ):
        item[key] = bool(item.get(key))
    mappings = service._market_provider_mappings(conn, item["symbol"], include_disabled=True)
    seed_state = registry_seed_status(
        item,
        mappings,
        registry_default_market_payload=registry_default_market_payload,
        provider_mapping_capabilities_func=provider_mapping_capabilities,
    )
    item.update(seed_state)
    runtime_row = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (item["symbol"],)).fetchone()
    if runtime_row:
        runtime_market = service._market_payload(runtime_row)
        reference_context, risk_grade_context = service._stored_market_price_contexts(runtime_market)
        item["runtime_market"] = service._attach_market_price_contexts(
            runtime_market,
            reference_context=reference_context,
            risk_grade_context=risk_grade_context,
        )
        item["reference_price_context"] = reference_context
        item["risk_grade_price_context"] = risk_grade_context
        item["reference_price_status"] = {
            "source": reference_context.get("source"),
            "confidence": reference_context.get("confidence"),
            "stale": reference_context.get("stale"),
            "degraded": reference_context.get("degraded"),
            "provider_count": reference_context.get("provider_count"),
        }
        item["risk_grade_price_status"] = {
            "source": risk_grade_context.get("source"),
            "confidence": risk_grade_context.get("confidence"),
            "stale": risk_grade_context.get("stale"),
            "degraded": risk_grade_context.get("degraded"),
            "provider_count": risk_grade_context.get("provider_count"),
            "high_risk_blocked": risk_grade_context.get("high_risk_blocked"),
        }
    else:
        item["runtime_market"] = None
        item["reference_price_context"] = {}
        item["risk_grade_price_context"] = {}
        item["reference_price_status"] = {}
        item["risk_grade_price_status"] = {}
    summary = _json_loads(item.get("probe_summary_json"), {})
    item["probe_status"] = str(item.get("probe_status") or "pending")
    item["probe_summary"] = summary
    item["provider_count"] = int(summary.get("enabled_provider_count") or 0)
    item["reference_provider_count"] = int(summary.get("reference_provider_count") or 0)
    item["risk_grade_provider_count"] = int(summary.get("depth_provider_count") or 0)
    return item


def validate_market_registry_payload(payload, *, existing=None):
    payload = payload if isinstance(payload, dict) else {}
    symbol = str(payload.get("symbol") or "").strip().upper()
    base_asset = str(payload.get("base_asset") or "").strip().upper()
    quote_asset = str(payload.get("quote_asset") or payload.get("quote_currency") or "").strip().upper()
    if not symbol and base_asset and quote_asset:
        symbol = f"{base_asset}/{quote_asset}"
    if "/" not in symbol or symbol.count("/") != 1:
        raise ValueError("market symbol must look like BASE/QUOTE")
    if not base_asset or not quote_asset:
        base_asset, quote_asset = symbol.split("/", 1)
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if not base_asset or not quote_asset or any(ch not in allowed for ch in base_asset) or any(ch not in allowed for ch in quote_asset):
        raise ValueError("market symbol only supports A-Z / 0-9 / . _ -")
    if symbol != f"{base_asset}/{quote_asset}":
        raise ValueError("market symbol must match base/quote fields")
    display_quote_currency = str(payload.get("display_quote_currency") or (existing["display_quote_currency"] if existing else "USDT")).strip().upper() or quote_asset
    if any(ch not in allowed for ch in display_quote_currency):
        raise ValueError("display quote currency only supports A-Z / 0-9 / . _ -")
    display_name = str(payload.get("display_name") or "").strip() or f"{base_asset}/{display_quote_currency}"
    market_type = str(payload.get("market_type") or (existing["market_type"] if existing else "spot")).strip().lower() or "spot"
    if market_type not in {"spot", "synthetic", "reference_only"}:
        raise ValueError("market_type must be spot, synthetic, or reference_only")
    return {
        "symbol": symbol,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "display_name": display_name[:120],
        "display_quote_currency": display_quote_currency,
        "market_type": market_type,
        "enabled": 1 if bool(payload.get("enabled", existing["enabled"] if existing else True)) else 0,
        "allow_spot": 1 if bool(payload.get("allow_spot", existing["allow_spot"] if existing else True)) else 0,
        "allow_margin": 1 if bool(payload.get("allow_margin", existing["allow_margin"] if existing else True)) else 0,
        "allow_bots": 1 if bool(payload.get("allow_bots", existing["allow_bots"] if existing else True)) else 0,
        "allow_risk_grade_usage": 1 if bool(payload.get("allow_risk_grade_usage", existing["allow_risk_grade_usage"] if existing else False)) else 0,
        "price_precision": _to_int(payload.get("price_precision", existing["price_precision"] if existing else 8), name="price_precision", minimum=0, maximum=12),
        "quantity_precision": _to_int(payload.get("quantity_precision", existing["quantity_precision"] if existing else 8), name="quantity_precision", minimum=0, maximum=12),
        "min_order_size": _to_float(payload.get("min_order_size", existing["min_order_size"] if existing else 0.00000001), name="min_order_size", minimum=0.00000001, maximum=10**12),
        "max_order_size": _to_float(payload.get("max_order_size", existing["max_order_size"] if existing else 1000000), name="max_order_size", minimum=0.00000001, maximum=10**12),
        "lot_size": _to_float(payload.get("lot_size", existing["lot_size"] if existing else 0.00000001), name="lot_size", minimum=0.00000001, maximum=10**12),
        "tick_size": _to_float(payload.get("tick_size", existing["tick_size"] if existing else 0.00000001), name="tick_size", minimum=0.00000001, maximum=10**12),
        "sort_order": _to_int(payload.get("sort_order", existing["sort_order"] if existing else 9999), name="sort_order", minimum=1, maximum=100000),
        "default_manual_price_points": _to_price_float(payload.get("default_manual_price_points", existing["default_manual_price_points"] if existing else 1), name="default_manual_price_points", minimum=0.00000001),
        "live_price_enabled": 1 if bool(payload.get("live_price_enabled", existing["live_price_enabled"] if existing else True)) else 0,
        "reference_price_enabled": 1 if bool(payload.get("reference_price_enabled", existing["reference_price_enabled"] if existing else True)) else 0,
        "btc_trade_enabled": 1 if bool(payload.get("btc_trade_enabled", existing["btc_trade_enabled"] if existing else False)) else 0,
    }


def validate_market_provider_mapping_payload(payload, *, existing=None):
    payload = payload if isinstance(payload, dict) else {}
    provider = str(payload.get("provider") or (existing["provider"] if existing else "")).strip()
    if provider not in PRICE_PROVIDER_LABELS:
        raise ValueError("unsupported provider")
    provider_symbol = str(payload.get("provider_symbol") or (existing["provider_symbol"] if existing else "")).strip()
    supports_ticker = 1 if bool(payload.get("supports_ticker", existing["supports_ticker"] if existing else provider in TICKER_CAPABLE_PROVIDERS)) else 0
    supports_depth = 1 if bool(payload.get("supports_depth", existing["supports_depth"] if existing else provider in DEPTH_CAPABLE_PROVIDERS)) else 0
    supports_candles = 1 if bool(payload.get("supports_candles", existing["supports_candles"] if existing else provider in REFERENCE_PRICE_CAPABLE_PROVIDERS)) else 0
    if supports_depth and provider not in DEPTH_CAPABLE_PROVIDERS:
        raise ValueError(f"{PRICE_PROVIDER_LABELS.get(provider, provider)} 不支援 depth provider input")
    if supports_candles and provider not in REFERENCE_PRICE_CAPABLE_PROVIDERS:
        raise ValueError(f"{PRICE_PROVIDER_LABELS.get(provider, provider)} 不支援 candles reference price")
    if supports_ticker and provider not in TICKER_CAPABLE_PROVIDERS:
        raise ValueError(f"{PRICE_PROVIDER_LABELS.get(provider, provider)} 不支援 ticker input")
    return {
        "provider": provider,
        "provider_symbol": provider_symbol[:120],
        "supports_ticker": supports_ticker,
        "supports_depth": supports_depth,
        "supports_candles": supports_candles,
        "enabled": 1 if bool(payload.get("enabled", existing["enabled"] if existing else bool(provider_symbol))) else 0,
        "priority": _to_int(payload.get("priority", existing["priority"] if existing else 100), name="priority", minimum=1, maximum=1000),
    }


def probe_market_registry_on_conn(service, conn, registry_row):
    settings = service._settings_payload(conn)
    min_provider_count = max(2, int(settings.get("price_fusion_min_provider_count") or DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT))
    mappings = [
        market_provider_mapping_payload(row)
        for row in service._market_provider_mappings(conn, registry_row["symbol"], include_disabled=True)
    ]
    enabled_rows = [row for row in mappings if row["enabled"] and row["provider_symbol"]]
    ticker_rows = [row for row in enabled_rows if row["supports_ticker"]]
    depth_rows = [row for row in enabled_rows if row["supports_depth"]]
    candle_rows = [row for row in enabled_rows if row["supports_candles"]]
    issues = []
    if registry_row["live_price_enabled"] and not ticker_rows:
        issues.append({"code": "ticker_provider_missing", "message": "缺少可用 ticker provider mapping"})
    if registry_row["reference_price_enabled"] and not candle_rows:
        issues.append({"code": "reference_provider_missing", "message": "缺少可用 candles provider mapping"})
    if registry_row["allow_risk_grade_usage"] and len(depth_rows) < min_provider_count:
        issues.append({"code": "risk_grade_provider_count_low", "message": f"risk-grade 至少需要 {min_provider_count} 家 depth provider"})
    if registry_row["btc_trade_enabled"] and str(registry_row["base_asset"] or "").strip().upper() != "BTC":
        issues.append({"code": "btc_trade_market_invalid", "message": "只有 BTC 市場可啟用 BTC_trade 信號"})
    status = "ok" if not issues else ("warning" if enabled_rows else "failed")
    message = "Provider probe 通過"
    if issues:
        message = "；".join(str(item["message"]) for item in issues)
    return {
        "status": status,
        "message": message,
        "enabled_provider_count": len(enabled_rows),
        "ticker_provider_count": len(ticker_rows),
        "depth_provider_count": len(depth_rows),
        "reference_provider_count": len(candle_rows),
        "risk_grade_ready": len(depth_rows) >= min_provider_count,
        "issues": issues,
        "providers": mappings,
        "min_provider_count": min_provider_count,
    }


def persist_market_registry_probe(service, conn, registry_row):
    summary = probe_market_registry_on_conn(service, conn, registry_row)
    now = _now_text()
    conn.execute(
        "UPDATE trading_markets_registry SET probe_status=?, probe_summary_json=?, probe_checked_at=?, updated_at=? WHERE id=?",
        (
            str(summary["status"]),
            _json_dumps(summary),
            now,
            now,
            int(registry_row["id"]),
        ),
    )
    return summary


def list_market_registry(service, *, include_disabled=True):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        query = "SELECT * FROM trading_markets_registry"
        if not include_disabled:
            query += " WHERE enabled=1"
        query += " ORDER BY sort_order ASC, symbol ASC"
        rows = conn.execute(query).fetchall()
        return {
            "markets": [service._market_registry_payload(conn, row) for row in rows],
            "audit": [dict(row) for row in conn.execute("SELECT * FROM trading_market_registry_audit ORDER BY id DESC LIMIT 100").fetchall()],
        }
    finally:
        conn.close()


def get_market_provider_registry(service, *, market_id):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not market:
            raise ValueError("market not found")
        return {
            "market": service._market_registry_payload(conn, market),
            "providers": [
                service._market_provider_mapping_payload(row)
                for row in service._market_provider_mappings(conn, market["symbol"], include_disabled=True)
            ],
        }
    finally:
        conn.close()


def create_market_registry(service, *, actor, payload, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        values = service._validate_market_registry_payload(payload, existing=None)
        if conn.execute("SELECT 1 FROM trading_markets_registry WHERE symbol=?", (values["symbol"],)).fetchone():
            raise ValueError("market already exists")
        now = _now_text()
        columns = list(values.keys()) + ["registry_source", "seed_version", "probe_status", "probe_summary_json", "created_at", "updated_at", "created_by", "updated_by"]
        row_values = [values[key] for key in values] + ["custom", 0, "pending", "{}", now, now, service._actor_id(actor), service._actor_id(actor)]
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(f"INSERT INTO trading_markets_registry ({', '.join(columns)}) VALUES ({placeholders})", row_values)
        registry = conn.execute("SELECT * FROM trading_markets_registry WHERE symbol=?", (values["symbol"],)).fetchone()
        summary = service._persist_market_registry_probe(conn, registry)
        if values["allow_risk_grade_usage"] and not summary["risk_grade_ready"]:
            raise ValueError(summary["message"] or "provider probe failed")
        sync_runtime_markets(conn)
        service._market_registry_audit(conn, actor=actor, action="create_market", market_symbol=values["symbol"], before={}, after=values)
        service._audit_event(conn, "TRADING_MARKET_REGISTRY_CREATED", "root created trading market registry", actor=actor, market_symbol=values["symbol"], metadata={"market_id": registry["id"]})
        conn.commit()
        refreshed = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(registry["id"]),)).fetchone()
        return {"ok": True, "market": service._market_registry_payload(conn, refreshed)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_market_registry(service, *, actor, market_id, payload, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not existing:
            raise ValueError("market not found")
        values = service._validate_market_registry_payload(payload, existing=existing)
        if values["symbol"] != str(existing["symbol"] or "").strip().upper():
            raise ValueError("changing market symbol is not supported; disable and recreate the market instead")
        conflict = conn.execute("SELECT id FROM trading_markets_registry WHERE symbol=? AND id<>?", (values["symbol"], int(market_id))).fetchone()
        if conflict:
            raise ValueError("market symbol already exists")
        assignments = ", ".join(f"{key}=?" for key in values)
        conn.execute(
            f"UPDATE trading_markets_registry SET {assignments}, updated_at=?, updated_by=? WHERE id=?",
            [*values.values(), _now_text(), service._actor_id(actor), int(market_id)],
        )
        registry = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        summary = service._persist_market_registry_probe(conn, registry)
        if values["allow_risk_grade_usage"] and not summary["risk_grade_ready"]:
            raise ValueError(summary["message"] or "provider probe failed")
        sync_runtime_markets(conn)
        service._market_registry_audit(conn, actor=actor, action="update_market", market_symbol=registry["symbol"], before=dict(existing), after=values)
        service._audit_event(conn, "TRADING_MARKET_REGISTRY_UPDATED", "root updated trading market registry", actor=actor, market_symbol=registry["symbol"], metadata={"market_id": market_id})
        conn.commit()
        refreshed = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        return {"ok": True, "market": service._market_registry_payload(conn, refreshed)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def disable_market_registry(service, *, actor, market_id, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not existing:
            raise ValueError("market not found")
        after = dict(existing)
        after.update({
            "enabled": 0,
            "allow_spot": 0,
            "allow_margin": 0,
            "allow_bots": 0,
            "allow_risk_grade_usage": 0,
        })
        conn.execute(
            """
            UPDATE trading_markets_registry
            SET enabled=0, allow_spot=0, allow_margin=0, allow_bots=0, allow_risk_grade_usage=0,
                probe_status='disabled', updated_at=?, updated_by=?
            WHERE id=?
            """,
            (_now_text(), service._actor_id(actor), int(market_id)),
        )
        registry = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        service._persist_market_registry_probe(conn, registry)
        sync_runtime_markets(conn)
        service._market_registry_audit(conn, actor=actor, action="disable_market", market_symbol=existing["symbol"], before=dict(existing), after=after)
        service._audit_event(conn, "TRADING_MARKET_REGISTRY_DISABLED", "root disabled trading market registry", actor=actor, market_symbol=existing["symbol"], metadata={"market_id": market_id})
        conn.commit()
        refreshed = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        return {"ok": True, "market": service._market_registry_payload(conn, refreshed)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_market_provider_mapping(service, *, actor, market_id, payload, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        market = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not market:
            raise ValueError("market not found")
        values = service._validate_market_provider_mapping_payload(payload, existing=None)
        if conn.execute("SELECT 1 FROM trading_market_provider_mappings WHERE market_id=? AND provider=?", (int(market_id), values["provider"])).fetchone():
            raise ValueError("provider mapping already exists")
        now = _now_text()
        conn.execute(
            """
            INSERT INTO trading_market_provider_mappings (
                market_id, provider, provider_symbol, supports_ticker, supports_depth,
                supports_candles, enabled, priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(market_id),
                values["provider"],
                values["provider_symbol"],
                values["supports_ticker"],
                values["supports_depth"],
                values["supports_candles"],
                values["enabled"],
                values["priority"],
                now,
                now,
            ),
        )
        registry = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        service._persist_market_registry_probe(conn, registry)
        sync_runtime_markets(conn)
        service._market_registry_audit(conn, actor=actor, action="create_provider_mapping", market_symbol=market["symbol"], before={}, after=values)
        service._audit_event(conn, "TRADING_MARKET_PROVIDER_CREATED", "root created market provider mapping", actor=actor, market_symbol=market["symbol"], metadata={"provider": values["provider"]})
        conn.commit()
        return service.get_market_provider_registry(market_id=market_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_market_provider_mapping(service, *, actor, market_id, mapping_id, payload, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        market = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not market:
            raise ValueError("market not found")
        existing = conn.execute("SELECT * FROM trading_market_provider_mappings WHERE id=? AND market_id=?", (int(mapping_id), int(market_id))).fetchone()
        if not existing:
            raise ValueError("provider mapping not found")
        values = service._validate_market_provider_mapping_payload(payload, existing=existing)
        conn.execute(
            """
            UPDATE trading_market_provider_mappings
            SET provider_symbol=?, supports_ticker=?, supports_depth=?, supports_candles=?,
                enabled=?, priority=?, updated_at=?
            WHERE id=? AND market_id=?
            """,
            (
                values["provider_symbol"],
                values["supports_ticker"],
                values["supports_depth"],
                values["supports_candles"],
                values["enabled"],
                values["priority"],
                _now_text(),
                int(mapping_id),
                int(market_id),
            ),
        )
        registry = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        summary = service._persist_market_registry_probe(conn, registry)
        if int(registry["allow_risk_grade_usage"] or 0) and not summary["risk_grade_ready"]:
            raise ValueError(summary["message"] or "provider probe failed")
        sync_runtime_markets(conn)
        service._market_registry_audit(conn, actor=actor, action="update_provider_mapping", market_symbol=market["symbol"], before=dict(existing), after=values)
        service._audit_event(conn, "TRADING_MARKET_PROVIDER_UPDATED", "root updated market provider mapping", actor=actor, market_symbol=market["symbol"], metadata={"provider": existing["provider"]})
        conn.commit()
        return service.get_market_provider_registry(market_id=market_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def disable_market_provider_mapping(service, *, actor, market_id, mapping_id, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        market = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not market:
            raise ValueError("market not found")
        existing = conn.execute("SELECT * FROM trading_market_provider_mappings WHERE id=? AND market_id=?", (int(mapping_id), int(market_id))).fetchone()
        if not existing:
            raise ValueError("provider mapping not found")
        conn.execute(
            "UPDATE trading_market_provider_mappings SET enabled=0, updated_at=? WHERE id=? AND market_id=?",
            (_now_text(), int(mapping_id), int(market_id)),
        )
        registry = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        service._persist_market_registry_probe(conn, registry)
        sync_runtime_markets(conn)
        after = dict(existing)
        after["enabled"] = 0
        service._market_registry_audit(conn, actor=actor, action="disable_provider_mapping", market_symbol=market["symbol"], before=dict(existing), after=after)
        service._audit_event(conn, "TRADING_MARKET_PROVIDER_DISABLED", "root disabled market provider mapping", actor=actor, market_symbol=market["symbol"], metadata={"provider": existing["provider"]})
        conn.commit()
        return service.get_market_provider_registry(market_id=market_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def probe_market_registry(service, *, market_id, sync_runtime_markets):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        market = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        if not market:
            raise ValueError("market not found")
        summary = service._persist_market_registry_probe(conn, market)
        sync_runtime_markets(conn)
        conn.commit()
        refreshed = conn.execute("SELECT * FROM trading_markets_registry WHERE id=?", (int(market_id),)).fetchone()
        return {"ok": True, "market": service._market_registry_payload(conn, refreshed), "probe": summary}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
