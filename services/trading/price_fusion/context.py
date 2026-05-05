"""Pure display and confidence helpers for trading price fusion contexts."""


def price_usage_label(price_type):
    normalized = str(price_type or "reference").strip().lower()
    if normalized == "risk_grade":
        return "融資 / 強平 / 保證金 / PnL / bot 風控 / 交易限制"
    return "展示 / 一般估值 / K 線 / 非風控參考"


def price_source_label(source, provider_labels, *, fused_price_source):
    normalized = str(source or "").strip()
    if not normalized:
        return "未知價格來源"
    if normalized == "manual_root":
        return "root 手動價格"
    if normalized.endswith("_cached"):
        base = normalized[:-7]
        return f"{price_source_label(base, provider_labels, fused_price_source=fused_price_source)}（最後健康快取）"
    if normalized == fused_price_source:
        return "融合價格"
    if normalized == "ticker_fallback":
        return "單一 ticker 降級價格"
    if normalized == "scan_window_replay":
        return "掃描視窗回放價格"
    if normalized == "reference_price":
        return "參考價格"
    if normalized == "test_live_price_provider":
        return "測試 live price provider"
    return provider_labels.get(normalized, normalized)


def price_context_confidence(
    *,
    price_type,
    source,
    health,
    degraded,
    stale,
    provider_count,
    high_risk_blocked,
    minimum_provider_count,
):
    normalized_source = str(source or "").strip()
    normalized_health = str(health or "healthy").strip().lower()
    normalized_type = str(price_type or "reference").strip().lower()
    providers = max(0, int(provider_count or 0))
    if normalized_source == "manual_root":
        return "manual"
    if normalized_source == "test_live_price_provider":
        return "low"
    if stale or high_risk_blocked or normalized_health in {"conservative", "fallback"}:
        return "low"
    if degraded:
        return "medium"
    if normalized_type == "risk_grade" and providers < max(1, minimum_provider_count):
        return "medium"
    return "high"


def price_context_risk_grade_usable(
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
    normalized_type = str(price_type or "reference").strip().lower() or "reference"
    normalized_source = str(source or "").strip()
    normalized_health = str(health or "healthy").strip().lower()
    providers = max(0, int(provider_count or 0))
    if normalized_type != "risk_grade":
        return False
    if synthetic_test_provider or normalized_source == "test_live_price_provider":
        return False
    if normalized_source == "manual_root" or normalized_source.endswith("_cached"):
        return False
    if high_risk_blocked or stale or degraded or fallback:
        return False
    if normalized_health in {"fallback", "conservative", "degraded"}:
        return False
    return providers > 0
