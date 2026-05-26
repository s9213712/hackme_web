from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import copy
import math
import os
import time


@lru_cache(maxsize=1)
def _engine_module():
    from services.trading import trading_engine as engine

    return engine


def _warning_language_from(value):
    if isinstance(value, dict):
        text = str(
            value.get("warning_language")
            or value.get("trading.warning_language")
            or value.get("language")
            or ""
        ).strip().lower()
    else:
        text = str(value or "").strip().lower()
    return "en" if text.startswith("en") else "zh-TW"


def _warning_text(value, key, **kwargs):
    language = _warning_language_from(value)
    if language == "en":
        messages = {
            "manual_price_short": "Manual root price is active",
            "cached_price_short": "Using the last healthy cache",
            "manual_price_detail": "Manual root price is active; do not treat it as normal live market depth.",
            "cached_price_detail": "Using the last healthy cache; the price may already be stale.",
            "test_provider_detail": "Using an injected test live-price provider; suitable for testing and reference display only, not for production risk pricing.",
            "manual_root_block_reason": "Root manual price is active; manual prices are reference-only and must not be used for automatic execution or settlement.",
            "cached_high_risk_block_reason": "The last healthy cache is active and cannot be used as a risk-grade price.",
            "provider_coverage_partial": "Some provider snapshots are truncated. This does not prove real market depth is insufficient; reference price remains available, but the data is excluded from high-risk weighting.",
            "provider_coverage_partial_provider": "Snapshot coverage is truncated. This does not prove the venue lacks real depth; it is kept for reference pricing only and excluded from high-risk weighting.",
            "provider_count_low": f"Only {kwargs.get('provider_count', 0)} risk-grade order-book providers remain, below the recommended minimum of {kwargs.get('minimum_provider_count', 0)}.",
            "conservative_reference_only": "Not enough risk-grade providers are available; reference price only.",
            "conservative_status_message": "Price source degraded: the system has fallen back to a reduced provider set. High-risk trading should be paused.",
            "excluded_sources_reweighted": "Some venues were excluded, and the system redistributed weights across the remaining healthy sources.",
        }
        return messages.get(key, key)
    messages = {
        "manual_price_short": "目前使用手動價格",
        "cached_price_short": "目前使用最後健康快取",
        "manual_price_detail": "目前使用手動價格，請勿將此價格視為正常即時市場深度。",
        "cached_price_detail": "目前使用最後健康快取，請留意價格可能已過時。",
        "test_provider_detail": "目前使用測試注入 live price provider；此來源只適合測試與 reference 顯示，不可視為 production 風控價格。",
        "manual_root_block_reason": "目前使用 root 手動價格；手動價格只能做 reference 顯示，不可用於自動成交或結算。",
        "cached_high_risk_block_reason": "目前使用最後健康快取，不能作為風控級價格。",
        "provider_coverage_partial": "部分來源資料截斷，不代表該交易所真實深度不足；reference price 仍會納入，但不作為高風險風控權重。",
        "provider_coverage_partial_provider": "資料截斷，不代表該交易所真實深度不足；目前僅納入 reference price，不納入高風險風控權重。",
        "provider_count_low": f"風控級可用 order book 來源只剩 {kwargs.get('provider_count', 0)} 家，低於建議下限 {kwargs.get('minimum_provider_count', 0)} 家",
        "conservative_reference_only": "目前風控級可用來源數不足，只能提供 reference price",
        "conservative_status_message": "價格來源降級：目前已退回單一 ticker，建議暫停高風險交易。",
        "excluded_sources_reweighted": "部分交易所來源已被排除，系統已用剩餘健康來源重新分配權重。",
    }
    return messages.get(key, key)


def build_price_context(service, *, market_symbol, price_type, price_points, price_source, price_meta):
    engine = _engine_module()
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
    warning_message = ""
    if source == "manual_root":
        warning_message = _warning_text(meta, "manual_price_short")
    elif source.endswith("_cached"):
        warning_message = _warning_text(meta, "cached_price_short")
    if not warning_message:
        warning_message = str(meta.get("high_risk_block_reason") or meta.get("fallback_reason") or "").strip()
    if not warning_message:
        warning_message = str(service._primary_price_fusion_warning(warnings).get("message") or "").strip()
    if not warning_message and source == "manual_root":
        warning_message = _warning_text(meta, "manual_price_detail")
    if not warning_message and stale:
        warning_message = _warning_text(meta, "cached_price_detail")
    if not warning_message and synthetic_test_provider:
        warning_message = _warning_text(meta, "test_provider_detail")
    confidence = service._price_context_confidence(
        price_type=normalized_type,
        source=source,
        health=health,
        degraded=degraded,
        stale=stale,
        provider_count=provider_count,
        high_risk_blocked=high_risk_blocked,
    )
    risk_grade_usable = service._price_context_risk_grade_usable(
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
        "price_points": None if price_points in (None, "") else float(engine._to_decimal(price_points, name="price_points", minimum=0)),
        "source": source,
        "source_label": service._price_source_label(source),
        "confidence": confidence,
        "stale": stale,
        "degraded": degraded,
        "provider_count": provider_count,
        "connected": bool(meta.get("connected")),
        "fallback": bool(meta.get("fallback")),
        "last_update_at": str(meta.get("last_update_at") or ""),
        "exclusion_reason": str(meta.get("exclusion_reason") or ""),
        "health": health,
        "purpose": service._price_usage_label(normalized_type),
        "warning_message": warning_message,
        "high_risk_blocked": high_risk_blocked,
        "risk_grade_usable": risk_grade_usable,
        "synthetic_test_provider": synthetic_test_provider,
        "warning_only": warning_only,
        "excluded_sources": list(meta.get("excluded_sources") or []),
        "warnings": warnings,
    }


def stored_market_price_contexts(service, market):
    source = str((market or {}).get("price_source") or "manual_root").strip() or "manual_root"
    price_value = (market or {}).get("manual_price_points") or 0
    price_meta = {
        "price_health": "healthy",
        "fallback_reason": "",
        "excluded_sources": [],
        "warnings": [],
        "high_risk_blocked": source == "manual_root" or source.endswith("_cached"),
        "high_risk_block_reason": "",
        "requested_price_mode": "reference",
        "reference_price_points": price_value,
        "risk_grade_price_points": None if source == "manual_root" or source.endswith("_cached") else price_value,
        "resolved_source": source,
        "reference_provider_count": 1 if source and source != "manual_root" else 0,
        "risk_grade_provider_count": 0 if source == "manual_root" or source.endswith("_cached") else 1,
        "stale": source.endswith("_cached"),
        "degraded": source == "manual_root" or source.endswith("_cached"),
        "connected": False,
        "fallback": source.endswith("_cached"),
        "last_update_at": str((market or {}).get("updated_at") or ""),
        "exclusion_reason": "manual_root_active" if source == "manual_root" else ("cached_price_active" if source.endswith("_cached") else ""),
        "confidence": "manual" if source == "manual_root" else ("low" if source.endswith("_cached") else "medium"),
    }
    if source == "manual_root":
        price_meta["price_health"] = "warning"
        price_meta["high_risk_block_reason"] = _warning_text(price_meta, "manual_root_block_reason")
        price_meta["warnings"] = service._append_price_fusion_warning(
            [],
            "manual_price_active",
            _warning_text(price_meta, "manual_price_detail"),
            severity="warning",
        )
        price_meta["fallback_reason"] = "manual_root_not_allowed_for_high_risk"
    elif source.endswith("_cached"):
        price_meta["price_health"] = "fallback"
        price_meta["high_risk_block_reason"] = _warning_text(price_meta, "cached_high_risk_block_reason")
        price_meta["warnings"] = service._append_price_fusion_warning(
            [],
            "cached_price_active",
            _warning_text(price_meta, "cached_price_detail"),
            severity="warning",
        )
        price_meta["fallback_reason"] = _warning_text(price_meta, "cached_price_short")
    reference_context = service._build_price_context(
        market_symbol=(market or {}).get("symbol"),
        price_type="reference",
        price_points=price_value,
        price_source=source,
        price_meta=price_meta,
    )
    risk_context = service._build_price_context(
        market_symbol=(market or {}).get("symbol"),
        price_type="risk_grade",
        price_points=price_value,
        price_source=source,
        price_meta=price_meta,
    )
    return reference_context, risk_context


def provider_ticker_with_fallback(service, source, market_symbol, *, settings, http_fetcher, conn=None):
    ws_snapshot, stream_state = service._resolve_stream_ticker_snapshot(source, market_symbol, settings=settings, conn=conn)
    if ws_snapshot:
        return (
            float(_engine_module()._to_decimal(ws_snapshot.get("price_points"), name=f"{source} websocket price_points", minimum=0.00000001)),
            service._provider_transport_meta(
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
        service._provider_transport_meta(
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


def provider_orderbook_with_fallback(
    service,
    source,
    market_symbol,
    *,
    settings,
    depth_levels,
    band_percent,
    request_limit,
    http_fetcher,
    book_getter,
    conn=None,
):
    ws_snapshot, stream_state = service._resolve_stream_orderbook_snapshot(source, market_symbol, settings=settings, conn=conn)
    if ws_snapshot:
        return service._build_orderbook_snapshot(
            source=source,
            bids=ws_snapshot.get("bids") or [],
            asks=ws_snapshot.get("asks") or [],
            fetch_meta={
                "fetched_at": ws_snapshot.get("fetched_at") or ws_snapshot.get("last_update_at") or _engine_module()._now(),
                "latency_ms": ws_snapshot.get("latency_ms") or 0.0,
            },
            max_levels=depth_levels,
            band_percent=band_percent,
            request_limit=request_limit,
            transport_meta=service._provider_transport_meta(
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
    return service._build_orderbook_snapshot(
        source=source,
        bids=bids,
        asks=asks,
        fetch_meta=fetch_meta,
        max_levels=depth_levels,
        band_percent=band_percent,
        request_limit=request_limit,
        transport_meta=service._provider_transport_meta(
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


def price_stream_provider_state(service, source, market_symbol, *, settings, conn=None):
    provider_id = service.market_provider_id(market_symbol, source, conn=conn)
    if not service.stream_hub or not service._price_stream_ws_enabled(settings):
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
    return service.stream_hub.get_provider_state(
        source,
        market_symbol,
        provider_id=provider_id,
        stale_after_seconds=service._price_stream_ws_stale_seconds(settings),
    )


def provider_transport_meta(
    service,
    source,
    market_symbol,
    *,
    settings,
    stream_state=None,
    transport="http_polling",
    fetched_at="",
    latency_ms=0.0,
    fallback=False,
    exclusion_reason="",
    conn=None,
):
    state = dict(stream_state or service._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn) or {})
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


def resolve_stream_ticker_snapshot(service, source, market_symbol, *, settings, conn=None):
    state = service._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn)
    if not service.stream_hub or not state.get("ws_supported"):
        return None, state
    snapshot = service.stream_hub.get_ticker_snapshot(
        source,
        market_symbol,
        provider_id=service.market_provider_id(market_symbol, source, conn=conn),
        stale_after_seconds=service._price_stream_ws_stale_seconds(settings),
    )
    if not snapshot or snapshot.get("stale") or snapshot.get("degraded") or snapshot.get("price_points") in (None, ""):
        return None, state
    return snapshot, state


def resolve_stream_orderbook_snapshot(service, source, market_symbol, *, settings, conn=None):
    state = service._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn)
    if not service.stream_hub or not state.get("ws_supported"):
        return None, state
    snapshot = service.stream_hub.get_orderbook_snapshot(
        source,
        market_symbol,
        provider_id=service.market_provider_id(market_symbol, source, conn=conn),
        stale_after_seconds=service._price_stream_ws_stale_seconds(settings),
    )
    if not snapshot or snapshot.get("stale") or snapshot.get("degraded"):
        return None, state
    return snapshot, state


def provider_quantity_unit_info(service, source):
    engine = _engine_module()
    return {
        "quantity_unit": "base_asset",
        "quantity_unit_label": "base asset",
        "quantity_unit_confirmed": True,
        "quantity_unit_note": f"{engine.PRICE_PROVIDER_LABELS.get(source, source)} spot order book quantity is parsed as base asset size.",
        "contract_size_adjusted": False,
    }


def price_fusion_warning(code, message, *, severity="warning"):
    return {
        "code": str(code or "").strip(),
        "message": str(message or "").strip(),
        "severity": str(severity or "warning").strip() or "warning",
    }


def append_price_fusion_warning(service, warnings, code, message, *, severity="warning"):
    warning = service._price_fusion_warning(code, message, severity=severity)
    if not warning["code"]:
        return warnings
    existing = list(warnings or [])
    if not any(str(item.get("code") or "") == warning["code"] for item in existing if isinstance(item, dict)):
        existing.append(warning)
    return existing


def primary_price_fusion_warning(warnings):
    for warning in warnings or []:
        if isinstance(warning, dict) and str(warning.get("code") or "").strip():
            return warning
    return {}


def transport_state_from_provider_rows(
    service,
    provider_rows,
    *,
    warnings=None,
    degraded=False,
    conservative_mode=False,
    min_provider_count=0,
    ws_enabled=True,
):
    engine = _engine_module()
    rows = [row for row in (provider_rows or []) if isinstance(row, dict)]
    ws_rows = [row for row in rows if row.get("source") in engine.WS_CAPABLE_PRICE_PROVIDERS]
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
        primary_warning = service._primary_price_fusion_warning(warnings or [])
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


def build_orderbook_snapshot(
    service,
    *,
    source,
    bids,
    asks,
    fetch_meta=None,
    max_levels,
    band_percent,
    request_limit=None,
    transport_meta=None,
):
    engine = _engine_module()
    stats = service._depth_notional_snapshot(bids, asks, max_levels=max_levels, band_percent=band_percent)
    fetched_at = str((fetch_meta or {}).get("fetched_at") or engine._now())
    latency_ms = round(float((fetch_meta or {}).get("latency_ms") or 0.0), 2)
    try:
        age_seconds = max(0.0, round((datetime.now() - datetime.fromisoformat(fetched_at)).total_seconds(), 3))
    except Exception:
        age_seconds = 0.0
    snapshot = {
        "source": source,
        "price_points": service._price_points_from_float(stats["midpoint"], source=source),
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
        "provider_depth_request_limit": int(request_limit or max_levels or engine.DEFAULT_PRICE_FUSION_DEPTH_LEVELS),
        "provider_depth_limit_reached": bool(request_limit and (
            int(stats["raw_bid_levels_count"]) >= int(request_limit)
            or int(stats["raw_ask_levels_count"]) >= int(request_limit)
        )),
        "depth_band_percent": round(float(stats["band_percent"]), 4),
        "fetched_at": fetched_at,
        "age_seconds": age_seconds,
        "latency_ms": latency_ms,
    }
    snapshot.update(service._provider_quantity_unit_info(source))
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


def fetch_weighted_fused_price_points(service, market_symbol, *, settings, conn=None):
    engine = _engine_module()
    market_symbol = str(market_symbol or "").strip().upper()
    snapshots = []
    errors = []
    provider_failures = {}
    warnings = []
    depth_levels = service._price_fusion_depth_levels(settings)
    depth_band_percent = service._price_fusion_depth_band_percent(settings)
    min_orderbook_coverage_percent = service._price_fusion_min_orderbook_coverage_percent(settings)
    max_single_provider_weight_percent = service._price_fusion_provider_weight_cap_percent(settings)
    min_provider_count = service._price_fusion_min_provider_count(settings)
    mode = str((settings or {}).get("price_fusion_mode") or "auto_depth").strip()
    weight_map = service._price_fusion_manual_weights(settings)
    fetchers = (
        ("binance_public_api", service._fetch_binance_orderbook_snapshot),
        ("okx_public_api", service._fetch_okx_orderbook_snapshot),
        ("coinbase_exchange", service._fetch_coinbase_orderbook_snapshot),
        ("kraken_public_api", service._fetch_kraken_orderbook_snapshot),
        ("gemini_public_api", service._fetch_gemini_orderbook_snapshot),
        ("bitstamp_public_api", service._fetch_bitstamp_orderbook_snapshot),
    )
    fetchers_to_query = fetchers
    if mode == "manual_weights":
        weighted_fetchers = tuple(
            (source, fetcher)
            for source, fetcher in fetchers
            if max(float(weight_map.get(source, 0.0)), 0.0) > 0
        )
        if weighted_fetchers:
            fetchers_to_query = weighted_fetchers
    for source, fetcher in fetchers_to_query:
        try:
            try:
                snapshots.append(
                    service._call_with_optional_conn(
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
                        service._call_with_optional_conn(
                            fetcher,
                            market_symbol,
                            depth_levels=depth_levels,
                            settings=settings,
                            conn=conn,
                        )
                    )
                except TypeError:
                    snapshots.append(service._call_with_optional_conn(fetcher, market_symbol, conn=conn))
        except Exception as exc:
            short_error = str(exc)[:120]
            errors.append(f"{source}: {short_error}")
            provider_failures[source] = short_error
    if not snapshots:
        try:
            fallback_price, fallback_source, fallback_meta = service._call_with_optional_conn(
                service._fetch_live_price_points,
                market_symbol,
                with_meta=True,
                settings=settings,
                conn=conn,
            )
            synthetic_test_provider = str(fallback_source or "") == "test_live_price_provider"
            if not synthetic_test_provider:
                warnings = service._append_price_fusion_warning(
                    warnings,
                    "orderbook_unavailable",
                    (
                        f"All multi-venue order books failed; degraded to single-ticker source {engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source)}"
                        if _warning_language_from(settings) == "en"
                        else f"多交易所 order book 全部失敗，已降級為單一 ticker 價格來源 {engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source)}"
                    ),
                    severity="critical",
                )
                warnings = service._append_price_fusion_warning(
                    warnings,
                    "provider_count_low",
                    _warning_text(settings, "provider_count_low", provider_count=1, minimum_provider_count=min_provider_count),
                    severity="critical",
                )
            primary_warning = service._primary_price_fusion_warning(warnings)
            excluded = [
                {
                    "source": source,
                    "label": engine.PRICE_PROVIDER_LABELS.get(source, source),
                    "reason": "fetch_failed",
                    "error": provider_failures.get(source, ""),
                }
                for source, _fetcher in fetchers
            ]
            fallback_value = float(engine._to_decimal(fallback_price, name="fallback_price", minimum=0.00000001))
            providers_used = [{
                "source": fallback_source,
                "label": engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
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
                "coverage_warning_message": "" if synthetic_test_provider else _warning_text(settings, "provider_coverage_partial_provider"),
                "quantity_unit": "n/a",
                "quantity_unit_label": "n/a",
                "quantity_unit_confirmed": False,
                "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                "best_bid_points": None,
                "best_ask_points": None,
                "spread_percent": None,
                "bid_notional_points": None,
                "ask_notional_points": None,
                "fetched_at": str(fallback_meta.get("last_update_at") or engine._now()),
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
                "last_update_at": str(fallback_meta.get("last_update_at") or engine._now()),
                "exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                "provider_last_update_at": str(fallback_meta.get("last_update_at") or engine._now()),
                "provider_exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
            }]
            providers_used = [{
                "source": fallback_source,
                "label": engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
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
                "coverage_warning_message": _warning_text(settings, "provider_coverage_partial_provider"),
                "quantity_unit": "n/a",
                "quantity_unit_label": "n/a",
                "quantity_unit_confirmed": False,
                "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                "best_bid_points": None,
                "best_ask_points": None,
                "spread_percent": None,
                "bid_notional_points": None,
                "ask_notional_points": None,
                "fetched_at": str(fallback_meta.get("last_update_at") or engine._now()),
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
                "last_update_at": str(fallback_meta.get("last_update_at") or engine._now()),
                "exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                "provider_last_update_at": str(fallback_meta.get("last_update_at") or engine._now()),
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
                "transport_state": service._transport_state_from_provider_rows(
                    providers_used,
                    warnings=warnings,
                    degraded=not bool(synthetic_test_provider),
                    conservative_mode=not bool(synthetic_test_provider),
                    min_provider_count=min_provider_count,
                    ws_enabled=service._price_stream_ws_enabled(settings),
                ),
            }
        except Exception as fallback_exc:
            errors.append(f"single_source_fallback: {str(fallback_exc)[:120]}")
            raise ValueError("; ".join(errors) or "all fused price providers failed") from fallback_exc

    median_midpoint = engine._median_float([snap.get("midpoint_points") or snap.get("price_points") or 0.0 for snap in snapshots])
    excluded_providers = [
        {
            "source": source,
            "label": engine.PRICE_PROVIDER_LABELS.get(source, source),
            "reason": "fetch_failed",
            "error": provider_failures.get(source, ""),
            "manual_weight": round(float(weight_map.get(source, 0.0)), 8),
            **service._price_stream_provider_state(source, market_symbol, settings=settings, conn=conn),
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
            _warning_text(settings, "provider_coverage_partial_provider")
            if coverage_insufficient or bool(snap.get("orderbook_truncated"))
            else ""
        )
        reason = ""
        message = ""
        if age_seconds is not None and float(age_seconds or 0.0) > engine.DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS:
            reason = "stale_orderbook"
            message = f"order book age {snap.get('age_seconds')}s exceeds {engine.DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS}s"
        elif latency_ms is not None and float(latency_ms or 0.0) > engine.DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS:
            reason = "latency_too_high"
            message = f"order book latency {snap.get('latency_ms')}ms exceeds {engine.DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS}ms"
        elif side_balance_ratio_percent is not None and float(side_balance_ratio_percent or 0.0) < engine.DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0:
            reason = "one_sided_depth"
            message = f"single-sided depth ratio {snap.get('side_balance_ratio_percent')}% is below {round(engine.DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2)}%"
        elif deviation_percent > engine.DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT:
            reason = "midpoint_deviation_exceeded"
            message = f"midpoint deviates {round(deviation_percent, 4)}% from median"
        if reason:
            excluded_providers.append({
                "source": snap["source"],
                "label": engine.PRICE_PROVIDER_LABELS.get(snap["source"], snap["source"]),
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
            fallback_price, fallback_source, fallback_meta = service._call_with_optional_conn(
                service._fetch_live_price_points,
                market_symbol,
                with_meta=True,
                settings=settings,
                conn=conn,
            )
            synthetic_test_provider = str(fallback_source or "") == "test_live_price_provider"
            if not synthetic_test_provider:
                warnings = service._append_price_fusion_warning(
                    warnings,
                    "orderbook_quality_rejected",
                    (
                        f"Multi-venue order books were fetched, but all were excluded by quality rules; degraded to single-ticker source {engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source)}"
                        if _warning_language_from(settings) == "en"
                        else f"多交易所 order book 已抓到，但全部被品質規則排除，已降級為單一 ticker 價格來源 {engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source)}"
                    ),
                    severity="critical",
                )
                warnings = service._append_price_fusion_warning(
                    warnings,
                    "provider_count_low",
                    _warning_text(settings, "provider_count_low", provider_count=1, minimum_provider_count=min_provider_count),
                    severity="critical",
                )
            primary_warning = service._primary_price_fusion_warning(warnings)
            fallback_value = float(engine._to_decimal(fallback_price, name="fallback_price", minimum=0.00000001))
            fallback_used = [{
                "source": fallback_source,
                "label": engine.PRICE_PROVIDER_LABELS.get(fallback_source, fallback_source),
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
                "coverage_warning_message": "" if synthetic_test_provider else _warning_text(settings, "provider_coverage_partial_provider"),
                "quantity_unit": "n/a",
                "quantity_unit_label": "n/a",
                "quantity_unit_confirmed": False,
                "quantity_unit_note": "ticker fallback has no order book depth snapshot",
                "best_bid_points": None,
                "best_ask_points": None,
                "spread_percent": None,
                "bid_notional_points": None,
                "ask_notional_points": None,
                "fetched_at": str(fallback_meta.get("last_update_at") or engine._now()),
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
                "last_update_at": str(fallback_meta.get("last_update_at") or engine._now()),
                "exclusion_reason": str(fallback_meta.get("exclusion_reason") or ""),
                "provider_last_update_at": str(fallback_meta.get("last_update_at") or engine._now()),
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
                "transport_state": service._transport_state_from_provider_rows(
                    fallback_used,
                    warnings=warnings,
                    degraded=not bool(synthetic_test_provider),
                    conservative_mode=not bool(synthetic_test_provider),
                    min_provider_count=min_provider_count,
                    ws_enabled=service._price_stream_ws_enabled(settings),
                ),
            }
        except Exception as fallback_exc:
            errors.append(f"quality_filtered_single_source: {str(fallback_exc)[:120]}")
            raise ValueError("; ".join(errors) or "all fused price providers failed quality checks") from fallback_exc

    manual_positive_reference = sum(max(float(weight_map.get(snap["source"], 0.0)), 0.0) for snap in snapshots)
    if mode == "manual_weights" and manual_positive_reference > 0:
        weighted_reference_snapshots = []
        for snap in snapshots:
            if max(float(weight_map.get(snap["source"], 0.0)), 0.0) > 0:
                weighted_reference_snapshots.append(snap)
                continue
            excluded_providers.append({
                "source": snap["source"],
                "label": engine.PRICE_PROVIDER_LABELS.get(snap["source"], snap["source"]),
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
        warnings = service._append_price_fusion_warning(
            warnings,
            "manual_weights_invalid",
            "root 手動權重全部為 0，已改用自動深度權重",
        )
    reference_model = service._build_price_fusion_weight_model(
        snapshots,
        mode=reference_mode_input,
        weight_map=weight_map,
        max_single_provider_weight_percent=max_single_provider_weight_percent,
        score_getter=service._price_fusion_reference_score,
    )
    if mode == "manual_weights" and manual_positive_reference <= 0:
        warnings = service._append_price_fusion_warning(
            warnings,
            "manual_weights_unusable",
            "root 手動權重目前沒有可用來源，已改用自動深度權重",
        )
    if reference_model["resolved_mode"] == "equal_weight_fallback":
        warnings = service._append_price_fusion_warning(
            warnings,
            "depth_score_invalid",
            "所有來源 reference price 分數都無效，已改用等權平均",
        )
    if reference_model["cap_unenforceable"]:
        warnings = service._append_price_fusion_warning(
            warnings,
            "provider_weight_cap_unenforceable",
            f"目前 reference price 可用來源太少，無法滿足單一來源權重上限 {max_single_provider_weight_percent:.2f}%",
        )
    elif reference_model["cap_applied"]:
        warnings = service._append_price_fusion_warning(
            warnings,
            "provider_weight_cap_applied",
            f"已套用單一來源權重上限 {max_single_provider_weight_percent:.2f}%",
        )

    risk_snapshots = [snap for snap in snapshots if bool(snap.get("risk_grade_eligible"))]
    risk_model = None
    if risk_snapshots:
        risk_model = service._build_price_fusion_weight_model(
            risk_snapshots,
            mode=mode,
            weight_map=weight_map,
            max_single_provider_weight_percent=max_single_provider_weight_percent,
            score_getter=service._price_fusion_effective_score,
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
        float(engine._to_decimal(snap["price_points"], name="price_points", minimum=0.00000001)) * float(reference_weights.get(snap["source"], 0.0))
        for snap in snapshots
    )
    risk_grade_price = None
    if risk_rows:
        risk_grade_price = sum(
            float(engine._to_decimal(snap["price_points"], name="price_points", minimum=0.00000001)) * float(risk_weights.get(snap["source"], 0.0))
            for snap in risk_snapshots
        )

    if any(bool(snap.get("orderbook_truncated")) or bool(snap.get("coverage_insufficient")) for snap in snapshots):
        warnings = service._append_price_fusion_warning(
            warnings,
            "provider_coverage_partial",
            _warning_text(settings, "provider_coverage_partial"),
        )
    reference_sources = {snap["source"] for snap in snapshots}
    risk_sources = {snap["source"] for snap in risk_snapshots}
    conservative_mode = len(risk_sources) < min_provider_count
    if conservative_mode:
        warnings = service._append_price_fusion_warning(
            warnings,
            "provider_count_low",
            _warning_text(
                settings,
                "provider_count_low",
                provider_count=len(risk_sources),
                minimum_provider_count=min_provider_count,
            ),
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
                "label": engine.PRICE_PROVIDER_LABELS.get(source, source),
                "reason": "manual_weight_zero",
                "error": "",
                "manual_weight": round(float(weight_map.get(source, 0.0)), 8),
            })

    primary_warning = service._primary_price_fusion_warning(warnings)
    warning_message = "；".join(
        warning.get("message") or ""
        for warning in warnings
        if isinstance(warning, dict) and str(warning.get("message") or "").strip()
    )
    degrading_warning_present = any(service._price_fusion_warning_is_degrading(item) for item in warnings)
    degrading_exclusion_present = any(service._price_fusion_exclusion_is_degrading(item) for item in excluded_providers)
    fallback_active = reference_model["resolved_mode"] in {"auto_depth_fallback", "equal_weight_fallback"}
    degraded = bool(degrading_exclusion_present or degrading_warning_present or fallback_active or conservative_mode)
    warning_only = bool((warnings or excluded_providers)) and not degraded
    reference_value = float(Decimal(str(reference_price)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))
    transport_state = service._transport_state_from_provider_rows(
        snapshots,
        warnings=warnings,
        degraded=degraded,
        conservative_mode=conservative_mode,
        min_provider_count=min_provider_count,
        ws_enabled=service._price_stream_ws_enabled(settings),
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
        "high_risk_block_reason": _warning_text(settings, "conservative_reference_only") if conservative_mode else "",
        "reference_price_points": reference_value,
        "risk_grade_price_points": risk_value,
        "reference_provider_count": len(reference_sources),
        "risk_grade_provider_count": len(risk_sources),
        "providers_used": [
            {
                "source": snap["source"],
                "label": engine.PRICE_PROVIDER_LABELS.get(snap["source"], snap["source"]),
                "price_points": float(engine._to_decimal(snap["price_points"], name="price_points", minimum=0.00000001)),
                "midpoint_points": round(float(snap.get("midpoint_points") or snap["price_points"]), 8),
                "best_bid_points": round(float(snap.get("best_bid_points") or 0.0), 8),
                "best_ask_points": round(float(snap.get("best_ask_points") or 0.0), 8),
                "spread_points": round(float(snap.get("spread_points") or 0.0), 8),
                "spread_percent": round(float(snap.get("spread_percent") or 0.0), 8),
                "bid_notional_points": round(float(snap.get("bid_notional_points") or 0.0), 8),
                "ask_notional_points": round(float(snap.get("ask_notional_points") or 0.0), 8),
                "depth_score": round(float(snap.get("depth_score") or 0.0), 8),
                "effective_depth_score": round(float(service._price_fusion_effective_score(snap)), 8),
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
                "depth_band_percent": round(float(snap.get("depth_band_percent") or engine.DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT), 4),
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
        "resolved_source": engine.FUSED_PRICE_SOURCE,
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


def root_price_fusion_status_on_conn(service, conn, *, market_symbol=""):
    engine = _engine_module()
    settings = service._settings_payload(conn)
    configured_source = str(settings.get("price_source") or engine.FUSED_PRICE_SOURCE)
    requested_mode = str(settings.get("price_fusion_mode") or "auto_depth")
    requested_symbol = str(market_symbol or "").strip().upper()
    resolved_symbol = service._normalize_market_symbol_on_conn(conn, requested_symbol) if requested_symbol else ""
    symbol = resolved_symbol or service._default_price_fusion_market_symbol(conn)
    display_symbol = service._market_display_symbol_on_conn(conn, symbol)
    live_supported = bool(symbol and service._market_supports_live_price_on_conn(conn, symbol))
    payload = {
        "configured_source": configured_source,
        "configured_source_label": engine.PRICE_PROVIDER_LABELS.get(configured_source, configured_source),
        "requested_mode": requested_mode,
        "market_symbol": symbol,
        "requested_market_symbol": requested_symbol,
        "resolved_market_symbol": symbol,
        "display_market_symbol": display_symbol,
        "live_supported": live_supported,
        "providers_configured": list(engine.WEIGHTED_PRICE_PROVIDERS),
        "manual_weights": service._price_fusion_manual_weights(settings),
        "depth_levels": service._price_fusion_depth_levels(settings),
        "depth_band_percent": float(settings.get("price_fusion_depth_band_percent") or engine.DEFAULT_PRICE_FUSION_DEPTH_BAND_PERCENT),
        "max_single_provider_weight_percent": float(settings.get("price_fusion_max_single_provider_weight_percent") or engine.DEFAULT_PRICE_FUSION_MAX_SINGLE_PROVIDER_WEIGHT_PERCENT),
        "max_provider_age_seconds": int(settings.get("price_fusion_max_provider_age_seconds") or engine.DEFAULT_PRICE_FUSION_MAX_PROVIDER_AGE_SECONDS),
        "max_provider_latency_ms": int(settings.get("price_fusion_max_provider_latency_ms") or engine.DEFAULT_PRICE_FUSION_MAX_PROVIDER_LATENCY_MS),
        "max_midpoint_deviation_percent": float(settings.get("price_fusion_max_midpoint_deviation_percent") or engine.DEFAULT_PRICE_FUSION_MAX_MIDPOINT_DEVIATION_PERCENT),
        "min_side_balance_ratio_percent": float(settings.get("price_fusion_min_side_balance_ratio_percent") or round(engine.DEFAULT_PRICE_FUSION_MIN_SIDE_BALANCE_RATIO * 100.0, 2)),
        "min_provider_count": int(settings.get("price_fusion_min_provider_count") or engine.DEFAULT_PRICE_FUSION_MIN_PROVIDER_COUNT),
    }
    if configured_source != engine.FUSED_PRICE_SOURCE:
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
            "resolved_source": engine.FUSED_PRICE_SOURCE,
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
    price_points, details = service._fetch_weighted_fused_price_points(symbol, settings=settings, conn=conn)
    providers_used = list((details or {}).get("providers_used") or [])
    weights_sum_percent = round(sum(float(row.get("normalized_weight_percent") or 0.0) for row in providers_used), 4)
    degraded = bool((details or {}).get("degraded"))
    conservative_mode = bool((details or {}).get("conservative_mode"))
    high_risk_blocked = bool((details or {}).get("high_risk_blocked"))
    high_risk_block_reason = str((details or {}).get("high_risk_block_reason") or "").strip()
    warnings = list((details or {}).get("warnings") or [])
    warning_message = str((details or {}).get("warning_message") or "").strip()
    if conservative_mode and not warning_message:
        warning_message = _warning_text(settings, "conservative_status_message")
    elif degraded and not warning_message and (details or {}).get("excluded_providers"):
        warning_message = _warning_text(settings, "excluded_sources_reweighted")
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
        "resolved_source": str((details or {}).get("resolved_source") or engine.FUSED_PRICE_SOURCE),
        "price_points": float(engine._to_decimal(price_points, name="price_points", minimum=0.00000001)),
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


def _live_quote_cache_seconds():
    try:
        return max(0.0, min(float(os.environ.get("HACKME_TRADING_LIVE_QUOTE_CACHE_SECONDS", "2.0")), 30.0))
    except Exception:
        return 2.0


def _live_quote_stale_seconds():
    try:
        return max(0.0, min(float(os.environ.get("HACKME_TRADING_LIVE_QUOTE_STALE_SECONDS", "15.0")), 120.0))
    except Exception:
        return 15.0


def _clone_quote(payload, *, cache_status=None):
    cloned = copy.deepcopy(payload)
    if cache_status:
        cloned["price_cache_status"] = cache_status
    return cloned


def _live_quote_cacheable(payload):
    if not isinstance(payload, dict):
        return False
    return str(payload.get("price_health") or "").strip().lower() != "boot_pending"


def _configured_provider_fetcher(service, source):
    return {
        "binance_public_api": service._fetch_binance_price_points,
        "okx_public_api": service._fetch_okx_price_points,
        "coinbase_exchange": service._fetch_coinbase_price_points,
        "kraken_public_api": service._fetch_kraken_price_points,
        "gemini_public_api": service._fetch_gemini_price_points,
        "bitstamp_public_api": service._fetch_bitstamp_price_points,
        "coingecko_simple_price": service._fetch_coingecko_price_points,
    }.get(str(source or "").strip())


def get_live_market_quote(service, *, market_symbol="", force_refresh=False):
    requested_symbol = str(market_symbol or "").strip().upper()
    cache_key = requested_symbol or "__default__"
    now = time.monotonic()
    ttl = _live_quote_cache_seconds()
    stale_ttl = _live_quote_stale_seconds()
    if not force_refresh and ttl > 0:
        with service._live_quote_cache_lock:
            entry = service._live_quote_cache.get(cache_key)
            cached_payload = (entry or {}).get("payload")
            if cached_payload and not _live_quote_cacheable(cached_payload):
                cached_payload = None
            if cached_payload and float(entry.get("expires_at") or 0.0) > now:
                return _clone_quote(cached_payload, cache_status="hit")
            if cached_payload and entry and entry.get("refreshing") and float(entry.get("stale_until") or 0.0) > now:
                return _clone_quote(cached_payload, cache_status="stale_while_refresh")
            service._live_quote_cache[cache_key] = {
                "payload": cached_payload,
                "expires_at": float((entry or {}).get("expires_at") or 0.0),
                "stale_until": float((entry or {}).get("stale_until") or 0.0),
                "refreshing": True,
            }
    try:
        payload = _refresh_live_market_quote(service, market_symbol=market_symbol)
    except Exception:
        if not force_refresh and stale_ttl > 0:
            with service._live_quote_cache_lock:
                entry = service._live_quote_cache.get(cache_key) or {}
                cached_payload = entry.get("payload")
                if cached_payload and _live_quote_cacheable(cached_payload) and float(entry.get("stale_until") or 0.0) > now:
                    entry["refreshing"] = False
                    return _clone_quote(cached_payload, cache_status="stale_after_refresh_error")
                if entry:
                    entry["refreshing"] = False
        raise
    if not force_refresh and ttl > 0:
        if not _live_quote_cacheable(payload):
            with service._live_quote_cache_lock:
                service._live_quote_cache.pop(cache_key, None)
            return _clone_quote(payload, cache_status="refresh_uncached")
        refreshed_at = time.monotonic()
        with service._live_quote_cache_lock:
            service._live_quote_cache[cache_key] = {
                "payload": copy.deepcopy(payload),
                "expires_at": refreshed_at + ttl,
                "stale_until": refreshed_at + max(ttl, stale_ttl),
                "refreshing": False,
            }
        return _clone_quote(payload, cache_status="refresh")
    return payload


def _refresh_live_market_quote(service, *, market_symbol=""):
    engine = _engine_module()
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        requested_symbol = str(market_symbol or "").strip().upper()
        symbol = service._normalize_market_symbol_on_conn(conn, requested_symbol)
        defaulted_market = not bool(symbol)
        if symbol:
            market_row = service._market(conn, symbol)
        else:
            market_row = conn.execute(
                "SELECT * FROM trading_markets WHERE enabled=1 AND spot_enabled=1 ORDER BY sort_order ASC, symbol ASC"
            ).fetchall()
            market_row = next(iter(market_row), None)
            if not market_row:
                raise ValueError("market not found")
        settings = service._settings_payload(conn)
        market = service._market_payload(market_row)
        current_price, price_source, price_meta = service._current_market_price_points(conn, market, with_meta=True)
        price_meta = dict(price_meta or {})
        price_meta.setdefault("warning_language", settings.get("warning_language", "zh-TW"))
        updated_row = conn.execute("SELECT * FROM trading_markets WHERE symbol=?", (market["symbol"],)).fetchone()
        conn.commit()
        payload = service._market_payload(updated_row or market_row)
        payload["manual_price_points"] = current_price
        payload["price_source"] = str(price_source or payload.get("price_source") or "manual_root")
        resolved_symbol = str(payload.get("symbol") or "").strip().upper()
        reference_context = service._build_price_context(
            market_symbol=resolved_symbol,
            price_type="reference",
            price_points=(price_meta or {}).get("reference_price_points") if price_meta else current_price,
            price_source=payload["price_source"],
            price_meta=price_meta,
        )
        risk_grade_context = service._build_price_context(
            market_symbol=resolved_symbol,
            price_type="risk_grade",
            price_points=(price_meta or {}).get("risk_grade_price_points") if price_meta else current_price,
            price_source=payload["price_source"],
            price_meta=price_meta,
        )
        payload = service._attach_market_price_contexts(
            payload,
            reference_context=reference_context,
            risk_grade_context=risk_grade_context,
        )
        return {
            "market": payload,
            "requested_market_symbol": requested_symbol,
            "resolved_market_symbol": resolved_symbol,
            "display_market_symbol": service._market_display_symbol_on_conn(conn, resolved_symbol),
            "refresh_interval_ms": 2000,
            "server_time": engine._now(),
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
            "conservative_mode": bool((price_meta or {}).get("conservative_mode")),
            "minimum_provider_count": int((price_meta or {}).get("minimum_provider_count") or 0),
            "risk_grade_usable": bool((risk_grade_context or {}).get("risk_grade_usable")),
            "defaulted_market": defaulted_market,
            "reference_price_context": reference_context,
            "risk_grade_price_context": risk_grade_context,
            "transport_state": dict((price_meta or {}).get("transport_state") or {}),
            "warning_language": str(settings.get("warning_language") or "zh-TW"),
        }
    finally:
        conn.close()


def fetch_live_price_points(service, market_symbol, *, with_meta=False, settings=None, conn=None):
    engine = _engine_module()
    market_symbol = service._normalize_market_symbol_on_conn(conn, market_symbol) if conn is not None else service.normalize_market_symbol(market_symbol)
    if not service._live_price_symbol(market_symbol, conn=conn):
        raise ValueError("live price is not supported for this market")
    settings = settings or {}
    raw_settings = settings.get("raw") if isinstance(settings.get("raw"), dict) else {}
    qa_live_price_enabled = str(
        settings.get("qa_live_price_provider_enabled")
        or settings.get("trading.qa_live_price_provider_enabled")
        or raw_settings.get("trading.qa_live_price_provider_enabled")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on", "enabled"}
    qa_live_price_allowed = str(os.environ.get("HACKME_DEV_TRADING_ALLOW_QA_LIVE_PRICE_PROVIDER") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
    if qa_live_price_allowed and qa_live_price_enabled and conn is not None:
        market = service._market(conn, market_symbol)
        price = service._price_points_from_float(market["manual_price_points"], source="test_live_price_provider")
        meta = {
            "ws_supported": False,
            "transport": "qa_db_provider",
            "connected": True,
            "fallback": False,
            "stale": False,
            "degraded": False,
            "confidence": "low",
            "provider_count": 1,
            "last_update_at": engine._now(),
            "exclusion_reason": "",
            "latency_ms": 0.0,
            "synthetic_test_provider": True,
        }
        return (price, "test_live_price_provider", meta) if with_meta else (price, "test_live_price_provider")
    if service.live_price_provider:
        price = service.live_price_provider(market_symbol)
        price_points = service._price_points_from_float(price, source="test_live_price_provider")
        meta = {
            "ws_supported": False,
            "transport": "test_provider",
            "connected": False,
            "fallback": False,
            "stale": False,
            "degraded": False,
            "confidence": "low",
            "provider_count": 1,
            "last_update_at": engine._now(),
            "exclusion_reason": "",
            "latency_ms": 0.0,
            "synthetic_test_provider": True,
        }
        return (price_points, "test_live_price_provider", meta) if with_meta else (price_points, "test_live_price_provider")
    errors = []
    providers = (
        ("binance_public_api", service._fetch_binance_price_points),
        ("okx_public_api", service._fetch_okx_price_points),
        ("coinbase_exchange", service._fetch_coinbase_price_points),
        ("kraken_public_api", service._fetch_kraken_price_points),
        ("gemini_public_api", service._fetch_gemini_price_points),
        ("bitstamp_public_api", service._fetch_bitstamp_price_points),
        ("coingecko_simple_price", service._fetch_coingecko_price_points),
    )
    for source, fetcher in providers:
        try:
            price_points, provider_meta = service._call_with_optional_conn(
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


def recent_price_window(service, market_symbol, *, lookback_seconds=60, since_time_text=None, interval="1m", conn=None):
    engine = _engine_module()
    lookback = max(60, int(lookback_seconds or 60))
    settings = service._settings_payload(conn) if conn is not None else {}
    raw_settings = settings.get("raw") if isinstance(settings.get("raw"), dict) else {}
    configured_source = str(settings.get("price_source") or engine.DEFAULT_TRADING_PRICE_SOURCE).strip()
    qa_live_price_enabled = str(
        settings.get("qa_live_price_provider_enabled")
        or settings.get("trading.qa_live_price_provider_enabled")
        or raw_settings.get("trading.qa_live_price_provider_enabled")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on", "enabled"}
    qa_live_price_allowed = str(os.environ.get("HACKME_DEV_TRADING_ALLOW_QA_LIVE_PRICE_PROVIDER") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
    if conn is not None and configured_source == "test_live_price_provider" and qa_live_price_enabled and qa_live_price_allowed:
        market = service._market(conn, market_symbol)
        price = service._price_points_from_float(market["manual_price_points"], source="test_live_price_provider")
        if price and float(price) > 0:
            return {
                "interval": interval,
                "lookback_seconds": lookback,
                "candle_count": 1,
                "low_points": float(price),
                "high_points": float(price),
                "source": "test_live_price_provider",
            }
    interval_seconds = 60 if interval == "1m" else 900
    limit = max(2, min(int(math.ceil(lookback / interval_seconds)) + 2, 240))
    candles = service._fetch_indicator_candles(market_symbol, limit=limit, interval=interval, conn=conn)
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
        start_ms = service._parse_candle_time_ms(candle, interval_seconds=interval_seconds)
        if since_ms is not None and start_ms is not None and (start_ms + interval_seconds * 1000) <= since_ms:
            continue
        try:
            low_value = engine._to_decimal(candle.get("low_points") or candle.get("low_usdt") or 0, name="low_points", minimum=0)
            high_value = engine._to_decimal(candle.get("high_points") or candle.get("high_usdt") or 0, name="high_points", minimum=0)
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


def current_market_price_points(service, conn, market, *, with_meta=False, high_risk=False):
    engine = _engine_module()
    symbol = market["symbol"]
    settings = service._settings_payload(conn)
    configured_source = settings.get("price_source") or engine.DEFAULT_TRADING_PRICE_SOURCE
    confirmed_at_text = str(market.get("live_price_confirmed_at") or "").strip()
    warmup_started_at_text = str(market.get("live_price_warmup_started_at") or "").strip()
    price_meta = {
        "price_health": "healthy",
        "fallback_reason": "",
        "excluded_sources": [],
        "warnings": [],
        "high_risk_blocked": False,
        "high_risk_block_reason": "",
        "conservative_mode": False,
        "minimum_provider_count": 0,
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
    if configured_source == "manual_root" or not service._live_price_symbol(symbol, conn=conn):
        price = market["manual_price_points"]
        if not price or float(price) <= 0:
            raise ValueError(
                f"market {symbol} 沒有可用的手動價格（manual_price_points <= 0）；"
                "請等待 live provider 寫入第一筆即時價，或由 root 主動設定"
            )
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
        price_meta["risk_grade_price_points"] = None
        price_meta["resolved_source"] = source
        price_meta["price_health"] = "warning"
        price_meta["degraded"] = True
        price_meta["high_risk_blocked"] = True
        price_meta["high_risk_block_reason"] = (
            f"market {symbol} 目前使用 root 手動價格；"
            "手動價格只能做 reference 顯示，不可用於自動成交或結算。"
        )
        price_meta["connected"] = False
        price_meta["fallback"] = False
        price_meta["last_update_at"] = transport_state["last_update_at"]
        price_meta["exclusion_reason"] = transport_state["exclusion_reason"]
        price_meta["confidence"] = "manual"
        price_meta["transport_state"] = transport_state
        price_meta["risk_grade_usable"] = False
        price_meta["warnings"] = service._append_price_fusion_warning(
            price_meta.get("warnings"),
            "manual_price_active",
            "目前使用手動價格，請勿將此價格視為正常即時市場深度。",
            severity="warning",
        )
        price_meta["fallback_reason"] = "manual_root_not_allowed_for_high_risk"
        return (price, source, price_meta) if with_meta else (price, source)
    old_price_decimal = Decimal(str(market["manual_price_points"] or "0"))
    old_price = float(old_price_decimal)
    old_source = str(market["price_source"] or "")
    fusion_details = None
    try:
        if configured_source == engine.FUSED_PRICE_SOURCE:
            price, fusion_details = service._call_with_optional_conn(
                service._fetch_weighted_fused_price_points,
                symbol,
                settings=settings,
                conn=conn,
            )
            live_source = engine.FUSED_PRICE_SOURCE
            live_transport_meta = dict((fusion_details or {}).get("transport_state") or {})
        elif service.live_price_provider:
            price, live_source, live_transport_meta = service._fetch_live_price_points(symbol, with_meta=True, settings=settings, conn=conn)
        else:
            configured_fetcher = _configured_provider_fetcher(service, configured_source)
            if configured_fetcher:
                try:
                    price, live_transport_meta = service._call_with_optional_conn(
                        configured_fetcher,
                        symbol,
                        settings=settings,
                        with_meta=True,
                        conn=conn,
                    )
                    live_source = configured_source
                except Exception as primary_exc:
                    price, fusion_details = service._call_with_optional_conn(
                        service._fetch_weighted_fused_price_points,
                        symbol,
                        settings=settings,
                        conn=conn,
                    )
                    fusion_details = dict(fusion_details or {})
                    fusion_details["primary_price_source"] = configured_source
                    fusion_details["primary_price_error"] = str(primary_exc)[:300]
                    fusion_details["warning_only"] = True
                    fusion_details["warnings"] = service._append_price_fusion_warning(
                        fusion_details.get("warnings"),
                        "primary_price_source_failed_fused_fallback",
                        f"{configured_source} 報價失敗，已改用融合價格 fallback。",
                        severity="warning",
                    )
                    live_source = engine.FUSED_PRICE_SOURCE
                    live_transport_meta = dict((fusion_details or {}).get("transport_state") or {})
            else:
                price, live_source, live_transport_meta = service._fetch_live_price_points(symbol, with_meta=True, settings=settings, conn=conn)
    except Exception as exc:
        max_stale = int(settings.get("max_price_staleness_seconds") or 0)
        try:
            updated_at = datetime.fromisoformat(str(market["updated_at"]))
            stale_seconds = int((datetime.now() - updated_at).total_seconds())
        except Exception:
            stale_seconds = max_stale + 1
        cached_source = old_source[:-7] if old_source.endswith("_cached") else old_source
        if old_price_decimal > 0 and max_stale > 0 and stale_seconds <= max_stale and cached_source in engine.LIVE_PRICE_SOURCE_NAMES:
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
            service._audit_event(
                conn,
                "TRADING_PRICE_FALLBACK_USED",
                "live trading price unavailable; using cached last-good price",
                market_symbol=symbol,
                severity="warning",
                metadata={"error": str(exc), "cached_price_points": old_price, "stale_seconds": stale_seconds, "max_stale_seconds": max_stale},
            )
            return (old_price, source, price_meta) if with_meta else (old_price, source)
        raise ValueError(f"live trading price unavailable for {symbol}: {exc}") from exc
    history_sql, _history_ctx = service._format_routed_sql(
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
    if old_price_decimal > 0 and old_source in engine.LIVE_PRICE_SOURCE_NAMES and has_live_history:
        jump_percent = float((abs(Decimal(str(price)) - old_price_decimal) * Decimal("100")) / old_price_decimal)
        allowed_percent = float(market["max_price_jump_percent"] or 0)
        if allowed_percent and jump_percent > allowed_percent:
            service._audit_event(
                conn,
                "TRADING_PRICE_CIRCUIT_BREAKER",
                "live trading price jump exceeded market threshold",
                market_symbol=symbol,
                severity="critical",
                metadata={"old_price_points": old_price, "new_price_points": price, "jump_percent": jump_percent, "allowed_percent": allowed_percent},
            )
            raise ValueError(f"live trading price jump {jump_percent:.2f}% exceeds max {allowed_percent:.2f}% for {symbol}")
    fusion_active = bool(fusion_details and live_source == engine.FUSED_PRICE_SOURCE)
    if fusion_active and (
        fusion_details.get("conservative_mode")
        or fusion_details.get("fallback_active")
        or fusion_details.get("degraded")
    ):
        warnings = list(fusion_details.get("warnings") or [])
        primary_warning = service._primary_price_fusion_warning(warnings)
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
            "conservative_mode": bool(fusion_details.get("conservative_mode")),
            "minimum_provider_count": int(fusion_details.get("min_provider_count") or 0),
            "reference_price_points": fusion_details.get("reference_price_points"),
            "risk_grade_price_points": fusion_details.get("risk_grade_price_points"),
            "resolved_source": str(fusion_details.get("resolved_source") or live_source or engine.FUSED_PRICE_SOURCE),
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
        service._audit_event(
            conn,
            "TRADING_PRICE_FUSION_DEGRADED",
            "fused trading price degraded or partially excluded providers",
            market_symbol=symbol,
            severity="critical" if fusion_details.get("conservative_mode") else "warning",
            metadata={
                "resolved_source": str(fusion_details.get("resolved_source") or live_source or engine.FUSED_PRICE_SOURCE),
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
    elif fusion_active:
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
            "resolved_source": str(fusion_details.get("resolved_source") or live_source or engine.FUSED_PRICE_SOURCE),
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
            "conservative_mode": bool(fusion_details.get("conservative_mode")),
            "minimum_provider_count": int(fusion_details.get("min_provider_count") or 0),
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
        live_price = float(engine._to_decimal(price, name="live_price_points", minimum=0.00000001))
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
        price_meta["conservative_mode"] = False
        price_meta["minimum_provider_count"] = 1
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
    if fusion_active and high_risk and fusion_details.get("risk_grade_price_points") is not None:
        price = float(engine._to_decimal(fusion_details.get("risk_grade_price_points"), name="risk_grade_price_points", minimum=0.00000001))
    now = engine._now()
    next_confirmed_at = confirmed_at_text or None
    next_warmup_started_at = warmup_started_at_text or None
    warmup_pending_reason = ""
    warmup_jump_percent = None
    if live_source in engine.LIVE_PRICE_SOURCE_NAMES and not confirmed_at_text:
        allowed_percent = float(market["max_price_jump_percent"] or 0)
        if not warmup_started_at_text:
            warmup_pending_reason = (
                f"market {symbol} 已收到第一筆即時價格；"
                "仍需再確認一筆穩定報價後才允許 bot / 撮合 / 風控。"
            )
            next_confirmed_at = None
            next_warmup_started_at = now
        elif old_price_decimal > 0:
            warmup_jump_percent = float((abs(Decimal(str(price)) - old_price_decimal) * Decimal("100")) / old_price_decimal)
            if allowed_percent and warmup_jump_percent > allowed_percent:
                warmup_pending_reason = (
                    f"market {symbol} 即時價格暖機期間跳動 {warmup_jump_percent:.2f}% 超過 "
                    f"{allowed_percent:.2f}%；仍需等待下一筆穩定報價。"
                )
                next_confirmed_at = None
                next_warmup_started_at = now
            else:
                next_confirmed_at = now
                next_warmup_started_at = None
        else:
            warmup_pending_reason = (
                f"market {symbol} 已收到第一筆即時價格；"
                "仍需再確認一筆穩定報價後才允許 bot / 撮合 / 風控。"
            )
            next_confirmed_at = None
            next_warmup_started_at = now
    if warmup_pending_reason:
        price_meta["price_health"] = "boot_pending"
        price_meta["high_risk_blocked"] = True
        price_meta["high_risk_block_reason"] = warmup_pending_reason
        price_meta["risk_grade_usable"] = False
        price_meta["fallback_reason"] = warmup_pending_reason
        price_meta["warnings"] = service._append_price_fusion_warning(
            price_meta.get("warnings"),
            "boot_warmup_pending",
            warmup_pending_reason,
            severity="warning",
        )
        transport_state = dict(price_meta.get("transport_state") or {})
        if transport_state and not str(transport_state.get("message") or "").strip():
            transport_state["message"] = warmup_pending_reason
            price_meta["transport_state"] = transport_state
        service._audit_event(
            conn,
            "TRADING_PRICE_BOOT_WARMUP_PENDING",
            "live trading price captured but market is still warming up",
            market_symbol=symbol,
            severity="warning",
            metadata={
                "resolved_source": str(live_source or configured_source or ""),
                "price_points": float(engine._to_decimal(price, name="warmup_price_points", minimum=0.00000001)),
                "previous_price_points": float(old_price_decimal) if old_price_decimal > 0 else None,
                "jump_percent": warmup_jump_percent,
                "allowed_percent": float(market["max_price_jump_percent"] or 0),
                "warmup_started_at": next_warmup_started_at,
                "reason": warmup_pending_reason,
            },
        )
    if live_source in engine.LIVE_PRICE_SOURCE_NAMES:
        conn.execute(
            "UPDATE trading_markets SET manual_price_points=?, price_source=?, updated_at=?, "
            "live_price_warmup_started_at=?, live_price_confirmed_at=? WHERE symbol=?",
            (price, live_source, now, next_warmup_started_at, next_confirmed_at, symbol),
        )
    else:
        conn.execute(
            "UPDATE trading_markets SET manual_price_points=?, price_source=?, updated_at=? WHERE symbol=?",
            (price, live_source, now, symbol),
        )
    return (price, live_source, price_meta) if with_meta else (price, live_source)
