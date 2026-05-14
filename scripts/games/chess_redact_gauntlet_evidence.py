#!/usr/bin/env python3
"""Redact gauntlet replay evidence while preserving private raw copies."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON: {path}")
    return payload


def _copy_raw(path: Path, private_dir: Path) -> Path:
    private_dir.mkdir(parents=True, exist_ok=True)
    destination = private_dir / path.name
    shutil.copy2(path, destination)
    return destination


def _redacted_game(game: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "game_index": index,
        "result": game.get("result"),
        "reason": game.get("reason"),
        "complete_game": bool(game.get("complete_game")),
        "codex_color": game.get("codex_color"),
        "plies": game.get("plies"),
        "elapsed_ms": game.get("elapsed_ms"),
        "codex_material_cp": game.get("codex_material_cp"),
        "invalid_count": len(game.get("invalid") or []),
    }


def _redacted_json(payload: dict[str, Any], *, private_json: Path | None, private_jsonl: Path | None) -> dict[str, Any]:
    summary = dict(payload.get("summary") or {})
    method = dict(payload.get("method") or {})
    redacted = {
        "engine": payload.get("engine"),
        "generated_at": payload.get("generated_at"),
        "method": method,
        "summary": summary,
        "redaction": {
            "policy": "raw gauntlet replays are sensitive; public evidence keeps aggregate summaries only",
            "removed_fields": ["games[].moves", "games[].fen", "games[].opening_line", "final_fen"],
            "private_raw_json": str(private_json) if private_json else "",
            "private_raw_jsonl": str(private_jsonl) if private_jsonl else "",
        },
    }
    games = payload.get("games")
    if isinstance(games, list):
        redacted["games"] = [_redacted_game(game, index) for index, game in enumerate(games, start=1) if isinstance(game, dict)]
    return redacted


def _redact_jsonl(input_path: Path, output_path: Path) -> int:
    count = 0
    redacted_rows: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8", errors="replace") as source:
        for index, line in enumerate(source, start=1):
            line = line.strip()
            if not line:
                continue
            game = json.loads(line)
            if not isinstance(game, dict):
                continue
            redacted_rows.append(_redacted_game(game, index))
    with output_path.open("w", encoding="utf-8") as target:
        for row in redacted_rows:
            target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--copy-raw", action="store_true", help="Copy raw inputs to --private-dir before redacting outputs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_json = args.input_json.expanduser().resolve()
    input_jsonl = args.input_jsonl.expanduser().resolve()
    output_json = args.output_json.expanduser().resolve()
    output_jsonl = args.output_jsonl.expanduser().resolve()
    private_dir = args.private_dir.expanduser()

    private_json = _copy_raw(input_json, private_dir) if args.copy_raw else None
    private_jsonl = _copy_raw(input_jsonl, private_dir) if args.copy_raw else None

    payload = _load_json(input_json)
    redacted = _redacted_json(payload, private_json=private_json, private_jsonl=private_jsonl)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    rows = _redact_jsonl(input_jsonl, output_jsonl)
    print(
        json.dumps(
            {
                "ok": True,
                "output_json": str(output_json),
                "output_jsonl": str(output_jsonl),
                "private_json": str(private_json) if private_json else "",
                "private_jsonl": str(private_jsonl) if private_jsonl else "",
                "redacted_jsonl_rows": rows,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
