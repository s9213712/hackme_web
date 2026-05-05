"""Pure weighting helpers for trading price fusion."""


def price_fusion_effective_score(snapshot):
    try:
        return max(float(snapshot.get("effective_depth_score")), 0.0)
    except Exception:
        try:
            return max(float(snapshot.get("depth_score") or 0.0), 0.0)
        except Exception:
            return 0.0


def price_fusion_reference_score(snapshot):
    try:
        density_score = max(float(snapshot.get("depth_density_score") or 0.0), 0.0)
        if density_score > 0:
            return density_score
    except Exception:
        pass
    try:
        return max(float(snapshot.get("depth_score") or 0.0), 0.0)
    except Exception:
        return 0.0


def apply_price_fusion_weight_cap(weighted_rows, *, max_single_provider_weight_percent):
    total_raw = sum(max(float(weight), 0.0) for _snap, weight in weighted_rows)
    if total_raw <= 0:
        raise ValueError("weighted fused price has no positive provider weight")
    normalized = {
        snap["source"]: max(float(weight), 0.0) / total_raw
        for snap, weight in weighted_rows
    }
    cap_fraction = max(0.0, min(float(max_single_provider_weight_percent or 0.0), 100.0)) / 100.0
    if cap_fraction <= 0 or cap_fraction >= 1.0:
        return normalized, False, False
    if len(weighted_rows) * cap_fraction < 1.0 - 1e-9:
        return normalized, False, True
    remaining = {snap["source"]: max(float(weight), 0.0) for snap, weight in weighted_rows}
    capped = {}
    remaining_fraction = 1.0
    while remaining:
        raw_sum = sum(remaining.values())
        if raw_sum <= 0 or remaining_fraction <= 1e-9:
            break
        over = [
            source
            for source, value in remaining.items()
            if (value / raw_sum) * remaining_fraction > cap_fraction + 1e-12
        ]
        if not over:
            for source, value in remaining.items():
                capped[source] = (value / raw_sum) * remaining_fraction
            remaining = {}
            break
        for source in over:
            capped[source] = cap_fraction
            del remaining[source]
            remaining_fraction -= cap_fraction
            if remaining_fraction <= 1e-9:
                remaining_fraction = 0.0
                break
    if remaining:
        raw_sum = sum(remaining.values())
        if raw_sum > 0 and remaining_fraction > 0:
            for source, value in remaining.items():
                capped[source] = (value / raw_sum) * remaining_fraction
    cap_applied = any(abs(capped.get(source, 0.0) - normalized.get(source, 0.0)) > 1e-12 for source in normalized)
    return capped or normalized, cap_applied, False


def build_price_fusion_weight_model(snapshots, *, mode, weight_map, max_single_provider_weight_percent, score_getter):
    rows = []
    resolved_mode = mode
    if mode == "manual_weights":
        manual_positive_total = 0.0
        for snap in snapshots:
            weight = float(weight_map.get(snap["source"], 0.0))
            if weight > 0:
                rows.append((snap, weight))
                manual_positive_total += weight
        if manual_positive_total <= 0:
            resolved_mode = "auto_depth_fallback"
            rows = []
    if not rows:
        rows = [(snap, float(score_getter(snap))) for snap in snapshots]
    total_raw_weight = sum(max(float(weight), 0.0) for _snap, weight in rows)
    if total_raw_weight <= 0:
        equal_weight = 1.0 / len(snapshots)
        resolved_mode = "equal_weight_fallback"
        rows = [(snap, equal_weight) for snap in snapshots]
        total_raw_weight = sum(weight for _snap, weight in rows)
    normalized_weights, cap_applied, cap_unenforceable = apply_price_fusion_weight_cap(
        rows,
        max_single_provider_weight_percent=max_single_provider_weight_percent,
    )
    return {
        "rows": rows,
        "resolved_mode": resolved_mode,
        "total_raw_weight": total_raw_weight,
        "normalized_weights": normalized_weights,
        "cap_applied": cap_applied,
        "cap_unenforceable": cap_unenforceable,
    }
