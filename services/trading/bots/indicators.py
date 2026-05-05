"""Pure workflow indicator helpers."""

import math


def build_workflow_indicator_series(candles):
    candles = candles or []
    contexts = [{} for _ in candles]
    closes = []
    highs = []
    lows = []
    prev_close = None
    gain_count = 0
    avg_gain = None
    avg_loss = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            continue
        try:
            close = float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt") or 0)
            high = float(candle.get("high_points") or candle.get("high_usdt") or close)
            low = float(candle.get("low_points") or candle.get("low_usdt") or close)
        except Exception:
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        if not math.isfinite(high) or high <= 0:
            high = close
        if not math.isfinite(low) or low <= 0:
            low = close
        closes.append(close)
        highs.append(high)
        lows.append(low)
        if prev_close is not None:
            delta = close - prev_close
            gain = max(delta, 0.0)
            loss = abs(min(delta, 0.0))
            gain_count += 1
            if gain_count == 14:
                recent_closes = closes[-13:] + [close]
                deltas = [recent_closes[i] - recent_closes[i - 1] for i in range(1, len(recent_closes))]
                gains = [max(value, 0.0) for value in deltas]
                losses = [abs(min(value, 0.0)) for value in deltas]
                avg_gain = sum(gains) / 14.0
                avg_loss = sum(losses) / 14.0
            elif gain_count > 14 and avg_gain is not None and avg_loss is not None:
                avg_gain = ((avg_gain * 13.0) + gain) / 14.0
                avg_loss = ((avg_loss * 13.0) + loss) / 14.0
        prev_close = close
        ma20 = sum(closes[-20:]) / 20.0 if len(closes) >= 20 else None
        ma50 = sum(closes[-50:]) / 50.0 if len(closes) >= 50 else None
        ma200 = sum(closes[-200:]) / 200.0 if len(closes) >= 200 else None
        bb_mid = ma20
        bb_upper = None
        bb_lower = None
        bb_std = None
        if ma20 is not None:
            window20 = closes[-20:]
            variance = sum((value - ma20) ** 2 for value in window20) / 20.0
            bb_std = math.sqrt(variance)
            if bb_std > 0:
                bb_upper = ma20 + 2 * bb_std
                bb_lower = ma20 - 2 * bb_std
        kd_k = None
        if len(closes) >= 9:
            high9 = max(highs[-9:])
            low9 = min(lows[-9:])
            kd_k = 50.0 if high9 == low9 else ((close - low9) * 100.0 / (high9 - low9))
        rsi_value = None
        if gain_count >= 14 and avg_gain is not None and avg_loss is not None:
            if avg_loss == 0:
                rsi_value = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_value = 100.0 - (100.0 / (1.0 + rs))
        contexts[index] = {
            "price": close,
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "bb_mid": bb_mid,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_std": bb_std,
            "rsi": rsi_value,
            "kd": kd_k,
        }
    return contexts


def workflow_indicator_context(candles, index):
    candles = candles or []
    index = max(0, min(int(index or 0), len(candles) - 1)) if candles else 0
    closes = []
    highs = []
    lows = []
    for candle in candles[: index + 1]:
        try:
            closes.append(float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt") or 0))
            highs.append(float(candle.get("high_points") or candle.get("high_usdt") or closes[-1]))
            lows.append(float(candle.get("low_points") or candle.get("low_usdt") or closes[-1]))
        except Exception:
            continue
    if not closes:
        return {}

    def sma(period):
        period = int(period)
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def rsi(period=14):
        if len(closes) <= period:
            return None
        gains = []
        losses = []
        for offset in range(1, len(closes)):
            delta = closes[offset] - closes[offset - 1]
            gains.append(max(delta, 0))
            losses.append(abs(min(delta, 0)))
        if len(gains) < period:
            return None
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for offset in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[offset]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[offset]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    ma20 = sma(20)
    ma50 = sma(50)
    bb_mid = ma20
    bb_upper = None
    bb_lower = None
    bb_std = None
    if ma20 is not None and len(closes) >= 20:
        variance = sum((value - ma20) ** 2 for value in closes[-20:]) / 20
        bb_std = math.sqrt(variance)
        if bb_std > 0:
            bb_upper = ma20 + 2 * bb_std
            bb_lower = ma20 - 2 * bb_std
    kd_k = None
    if len(closes) >= 9 and highs and lows:
        high9 = max(highs[-9:])
        low9 = min(lows[-9:])
        kd_k = 50.0 if high9 == low9 else ((closes[-1] - low9) * 100 / (high9 - low9))
    return {
        "price": closes[-1],
        "ma20": ma20,
        "ma50": ma50,
        "ma200": sma(200),
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_std": bb_std,
        "rsi": rsi(14),
        "kd": kd_k,
    }
