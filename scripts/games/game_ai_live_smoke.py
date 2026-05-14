#!/usr/bin/env python3
"""Run only the live game API smoke checks for the game AI audit."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.games.game_ai_strength_eval import run_live_api_smoke  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run hackme_web game AI live API smoke checks.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", default="test")
    parser.add_argument("--password", default="TestGameQa123!")
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_game_ai_live_smoke.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "base_url": args.base_url,
        "result": run_live_api_smoke(args.base_url, args.username, args.password),
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
