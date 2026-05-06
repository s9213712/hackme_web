#!/usr/bin/env python3
"""Backfill timestamps + ISO into Stage 2 equity CSVs.

Stage 2 originally wrote candle_time / candle_iso as empty strings because
of a wrong field-name lookup. Re-running Stage 2 takes ~19 minutes; this
script re-uses the existing equity_points / price values (still correct)
and just rebuilds the time + iso columns from candles_<asset>.json by
bar_index.

Effective fix; no backtest re-run required. Stage 2 source has been
patched separately so future runs produce correct CSVs end-to-end.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
EQUITY_DIR = OUT_DIR / "equity"
CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
ASSETS = [a["display"] for a in CONFIG["assets"]]


def load_candle_ts(asset: str) -> list:
    p = OUT_DIR / f"candles_{asset}.json"
    data = json.loads(p.read_text())
    return [(int(c["ts"]), c["iso"]) for c in data["candles"]]


def main() -> int:
    ts_by_asset = {a: load_candle_ts(a) for a in ASSETS}
    files = sorted(EQUITY_DIR.glob("*.csv"))
    fixed = 0
    skipped = 0
    for path in files:
        # Filename: <template>__<asset>.csv
        name = path.stem
        try:
            template, asset = name.rsplit("__", 1)
        except ValueError:
            print(f"[skip] cannot parse {name}", file=sys.stderr)
            skipped += 1
            continue
        if asset not in ts_by_asset:
            skipped += 1
            continue
        ts_list = ts_by_asset[asset]

        # Read existing rows.
        with path.open() as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = [r for r in reader]

        # Verify expected schema.
        if header != ["bar_index", "candle_time", "candle_iso", "price", "equity_points"]:
            print(f"[skip] unexpected header in {path}: {header}", file=sys.stderr)
            skipped += 1
            continue

        rewritten = []
        for row in rows:
            try:
                idx = int(row[0])
            except Exception:
                rewritten.append(row)
                continue
            if 0 <= idx < len(ts_list):
                ts, iso = ts_list[idx]
                rewritten.append([str(idx), str(ts), iso, row[3], row[4]])
            else:
                rewritten.append(row)

        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rewritten)
        fixed += 1
        if fixed % 20 == 0:
            print(f"  fixed {fixed} files...", file=sys.stderr)
    print(f"[done] fixed {fixed} files, skipped {skipped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
