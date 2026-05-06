#!/usr/bin/env python3
"""Stage 1 of the workflow-template competition benchmark.

Downloads 1h candles for the 5 traded assets (BTC, ETH, XRP, BNB, PAXG)
against USDT from Binance public klines, runs OHLC + continuity quality
checks, and writes:

- ``docs/COMPETITION/data/candles_<asset>.json``  raw candles per asset
- ``docs/COMPETITION/data/data_quality.json``     machine-readable summary
- ``docs/COMPETITION/DATA_QUALITY.md``              human-readable report

Stops with non-zero exit and a clear error if any asset fails the
quality gates so downstream stages don't run on bad data.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "COMPETITION" / "data"
DOCS_DIR = REPO_ROOT / "docs" / "COMPETITION"
OUT_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# (display, binance_symbol, target_5y_candles)
ASSETS = [
    ("BTC",  "BTCUSDT",  5 * 365 * 24),
    ("ETH",  "ETHUSDT",  5 * 365 * 24),
    ("XRP",  "XRPUSDT",  5 * 365 * 24),
    ("BNB",  "BNBUSDT",  5 * 365 * 24),
    ("PAXG", "PAXGUSDT", 5 * 365 * 24),  # PAXG/USDT listed mid-2020; will return less
]

INTERVAL = "1h"
INTERVAL_MS = 60 * 60 * 1000
OUTLIER_PCT_THRESHOLD = 50.0  # candle-to-candle close swings beyond ±50% are outliers


def http_get_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "competition-bench/1.0"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_candles(symbol: str, total: int) -> list:
    """Fetch up to ``total`` 1h candles in ascending order, walking backwards."""
    rows = []
    end_ms = int(time.time() * 1000)
    fetched = 0
    while fetched < total:
        chunk = min(1000, total - fetched)
        params = {"symbol": symbol, "interval": INTERVAL, "limit": chunk, "endTime": end_ms}
        url = "https://api.binance.com/api/v3/klines?" + urlencode(params)
        try:
            page = http_get_json(url)
        except Exception as exc:
            print(f"  [warn] fetch error for {symbol}: {exc}", file=sys.stderr)
            break
        if not isinstance(page, list) or not page:
            break
        rows = page + rows
        end_ms = page[0][0] - 1
        fetched += len(page)
        time.sleep(0.15)
    rows.sort(key=lambda r: r[0])
    return [
        {
            "ts": int(row[0] // 1000),
            "iso": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).isoformat(),
            "open":  float(row[1]),
            "high":  float(row[2]),
            "low":   float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
    ]


def quality_check(asset: str, candles: list) -> dict:
    n = len(candles)
    issues = {
        "ohlc_invalid": [],
        "timestamp_dup": [],
        "timestamp_gap": [],
        "outlier_jump": [],
        "zero_volume": 0,
    }
    if n < 2:
        return {
            "asset": asset,
            "candle_count": n,
            "first_iso": candles[0]["iso"] if n else "",
            "last_iso": candles[-1]["iso"] if n else "",
            "issues": issues,
            "verdict": "FAIL",
            "verdict_reason": "candle count below minimum",
        }

    seen_ts = set()
    prev_close = None
    for i, c in enumerate(candles):
        if not (c["high"] >= max(c["open"], c["close"]) and c["low"] <= min(c["open"], c["close"])):
            issues["ohlc_invalid"].append({"index": i, "iso": c["iso"]})
        if c["ts"] in seen_ts:
            issues["timestamp_dup"].append({"index": i, "iso": c["iso"]})
        seen_ts.add(c["ts"])
        if i > 0 and c["ts"] - candles[i - 1]["ts"] != INTERVAL_MS // 1000:
            gap_seconds = c["ts"] - candles[i - 1]["ts"]
            issues["timestamp_gap"].append({"index": i, "iso": c["iso"], "gap_seconds": gap_seconds})
        if prev_close and prev_close > 0:
            jump_pct = abs(c["close"] - prev_close) / prev_close * 100.0
            if jump_pct > OUTLIER_PCT_THRESHOLD:
                issues["outlier_jump"].append({"index": i, "iso": c["iso"], "jump_pct": round(jump_pct, 2)})
        if (c["volume"] or 0) == 0:
            issues["zero_volume"] += 1
        prev_close = c["close"]

    fatal = (
        bool(issues["ohlc_invalid"])
        or bool(issues["timestamp_dup"])
        or bool(issues["outlier_jump"])
    )
    warning = bool(issues["timestamp_gap"]) or issues["zero_volume"] > n * 0.05
    return {
        "asset": asset,
        "candle_count": n,
        "first_iso": candles[0]["iso"],
        "last_iso": candles[-1]["iso"],
        "issues": issues,
        "verdict": "FAIL" if fatal else ("WARNING" if warning else "PASS"),
        "verdict_reason": (
            "OHLC invalid / timestamp dup / outlier jump" if fatal
            else ("timestamp gaps or zero-volume rate >5%" if warning else "ok")
        ),
    }


def main() -> int:
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "interval": INTERVAL,
        "outlier_pct_threshold": OUTLIER_PCT_THRESHOLD,
        "assets": [],
    }
    overall_fatal = False
    for asset, symbol, target in ASSETS:
        print(f"[stage1] fetching {asset} ({symbol}, target {target})...", file=sys.stderr)
        t0 = time.perf_counter()
        candles = fetch_candles(symbol, target)
        elapsed = time.perf_counter() - t0
        print(f"  got {len(candles)} candles in {elapsed:.1f}s", file=sys.stderr)

        # Persist raw candles (gitignored under public/data/*.json wildcard).
        out_path = OUT_DIR / f"candles_{asset}.json"
        out_path.write_text(json.dumps({
            "asset": asset, "symbol": symbol, "interval": INTERVAL,
            "candle_count": len(candles), "candles": candles,
        }))

        report = quality_check(asset, candles)
        report["fetch_seconds"] = round(elapsed, 2)
        report["symbol"] = symbol
        if report["verdict"] == "FAIL":
            overall_fatal = True
        summary["assets"].append(report)
        v = report["verdict"]
        print(f"  → {v}: {report['verdict_reason']}", file=sys.stderr)

    summary["overall_verdict"] = "FAIL" if overall_fatal else (
        "WARNING" if any(a["verdict"] == "WARNING" for a in summary["assets"]) else "PASS"
    )
    (OUT_DIR / "data_quality.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    # Markdown report
    lines = [
        "# 競賽資料品質報告（Stage 1）",
        "",
        f"產生時間：{summary['generated_at']}",
        f"K 線間隔：{summary['interval']}",
        f"離群跳幅門檻：±{summary['outlier_pct_threshold']}%（candle-to-candle close）",
        "",
        f"**整體判定：{summary['overall_verdict']}**",
        "",
        "## 各資產摘要",
        "",
        "| Asset | Symbol | Candles | 區間 | OHLC 違法 | TS 重複 | TS 缺口 | 離群跳幅 | 零成交 | 判定 |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for a in summary["assets"]:
        iss = a["issues"]
        lines.append(
            f"| {a['asset']} | {a['symbol']} | {a['candle_count']:,} | "
            f"{a['first_iso'][:10]} → {a['last_iso'][:10]} | "
            f"{len(iss['ohlc_invalid'])} | {len(iss['timestamp_dup'])} | "
            f"{len(iss['timestamp_gap'])} | {len(iss['outlier_jump'])} | "
            f"{iss['zero_volume']} | **{a['verdict']}** |"
        )
    lines.extend([
        "",
        "## 判定規則",
        "- **FAIL**：OHLC 違法 / timestamp 重複 / 離群跳幅 > 50%（任一）",
        "- **WARNING**：timestamp 缺口存在 或 零成交 > 5%",
        "- **PASS**：以上皆無",
        "",
        "## 注意",
        "- PAXG/USDT 在 Binance 上市較晚（2020 年中），實際資料區間可能短於 5 年；",
        "  其 candle 數會少於其他資產，**不會** 用外插或硬補的方式延長。",
        "- 離群跳幅 > 50% 通常代表 split / delisting / Binance 資料異常，",
        "  本競賽偵測到即標 FAIL 並停止下游 stages，不容忍硬塞。",
        "",
    ])
    (DOCS_DIR / "DATA_QUALITY.md").write_text("\n".join(lines))
    print(f"[stage1] wrote {DOCS_DIR / 'DATA_QUALITY.md'}", file=sys.stderr)
    print(f"[stage1] overall verdict: {summary['overall_verdict']}", file=sys.stderr)
    return 0 if not overall_fatal else 2


if __name__ == "__main__":
    sys.exit(main())
