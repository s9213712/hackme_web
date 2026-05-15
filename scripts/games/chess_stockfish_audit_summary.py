#!/usr/bin/env python3
"""Aggregate Stockfish audit ledgers without exposing positions or moves."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _bucket(value: int, limits: list[tuple[int, str]], fallback: str) -> str:
    for upper, name in limits:
        if value <= upper:
            return name
    return fallback


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def summarize(path: Path) -> dict[str, Any]:
    rows = _read_rows(path)
    by_status = Counter(str(row.get("played_status") or "unknown") for row in rows)
    by_category = Counter(str(row.get("category") or "unknown") for row in rows)
    by_ply_bucket = Counter(
        _bucket(int(row.get("source_ply") or 0), [(12, "opening"), (32, "early_midgame"), (60, "midgame"), (100, "late")], "very_late")
        for row in rows
    )
    by_cp_loss = Counter(
        _bucket(int(row.get("cp_loss") or 0), [(0, "zero"), (60, "clean"), (160, "review"), (300, "bad"), (700, "severe")], "critical")
        for row in rows
    )
    category_status: dict[str, Counter[str]] = defaultdict(Counter)
    ply_status: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        status = str(row.get("played_status") or "unknown")
        category_status[str(row.get("category") or "unknown")][status] += 1
        ply_bucket = _bucket(
            int(row.get("source_ply") or 0),
            [(12, "opening"), (32, "early_midgame"), (60, "midgame"), (100, "late")],
            "very_late",
        )
        ply_status[ply_bucket][status] += 1
    cp_losses = [int(row.get("cp_loss") or 0) for row in rows]
    rejected = [int(row.get("cp_loss") or 0) for row in rows if str(row.get("played_status") or "") == "rejected"]
    return {
        "source": str(path),
        "rows": len(rows),
        "counts": {
            "by_status": dict(by_status),
            "by_category": dict(by_category),
            "by_ply_bucket": dict(by_ply_bucket),
            "by_cp_loss_bucket": dict(by_cp_loss),
            "category_status": {key: dict(value) for key, value in sorted(category_status.items())},
            "ply_status": {key: dict(value) for key, value in sorted(ply_status.items())},
        },
        "averages": {
            "avg_cp_loss": round(sum(cp_losses) / len(cp_losses), 2) if cp_losses else 0.0,
            "avg_rejected_cp_loss": round(sum(rejected) / len(rejected), 2) if rejected else 0.0,
            "max_cp_loss": max(cp_losses or [0]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    payload = summarize(args.input)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
