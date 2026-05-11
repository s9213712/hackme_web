#!/usr/bin/env python3
"""Convert PGN games into the chess replay JSONL format.

The output is intentionally compatible with the replay buffer consumed by
scripts/games/chess_replay_prepare.py. By default it writes under
~/chess_results so imported external data does not silently poison the active
runtime replay buffer.
"""

from __future__ import annotations

import argparse
import bz2
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
from typing import Iterable
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
import zipfile

import chess
import chess.pgn


DEFAULT_OUTPUT_PATH = Path.home() / "chess_results" / "chess_replays_imported.jsonl"
DEFAULT_DOWNLOAD_DIR = Path.home() / "chess_results" / "pgn_sources"
TRUSTED_SOURCES = {"imported_dataset", "teacher_guidance", "benchmark", "external"}


class _ZipPgnText:
    def __init__(self, path: Path):
        self.path = path
        self.archive: zipfile.ZipFile | None = None
        self.raw = None
        self.text = None

    def __enter__(self):
        self.archive = zipfile.ZipFile(self.path)
        names = [name for name in self.archive.namelist() if name.lower().endswith(".pgn")]
        if not names:
            raise RuntimeError(f"No .pgn file found inside zip archive: {self.path}")
        self.raw = self.archive.open(names[0], "r")
        self.text = io.TextIOWrapper(self.raw, encoding="utf-8", errors="replace")
        return self.text

    def __exit__(self, exc_type, exc, tb):
        if self.text is not None:
            self.text.close()
        elif self.raw is not None:
            self.raw.close()
        if self.archive is not None:
            self.archive.close()
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert local or downloaded PGN games into chess replay JSONL records."
    )
    parser.add_argument("--input-pgn", action="append", default=[], help="Local PGN path. Can be used more than once.")
    parser.add_argument("--source-url", action="append", default=[], help="Download a PGN/ZIP/GZ/BZ2/ZST URL first.")
    parser.add_argument("--download-dir", default=str(DEFAULT_DOWNLOAD_DIR))
    parser.add_argument("--refresh-downloads", action="store_true")
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--replace-output", action="store_true", help="Replace the output file instead of appending.")
    parser.add_argument("--allow-duplicates", action="store_true", help="Do not skip existing replay ids/signatures.")
    parser.add_argument("--max-games", type=int, default=100, help="Maximum games to emit. Use 0 for no cap.")
    parser.add_argument("--sample-size", type=int, default=0, help="Randomly sample this many eligible games.")
    parser.add_argument("--seed", type=int, default=20260511)
    parser.add_argument("--scan-limit", type=int, default=0, help="Stop after scanning this many PGN games. Use 0 for no cap.")
    parser.add_argument("--min-elo", type=int, default=0)
    parser.add_argument("--min-ply", type=int, default=8)
    parser.add_argument("--result", choices=["any", "decisive", "draw"], default="any")
    parser.add_argument("--skip-nonstandard-start", action="store_true")
    parser.add_argument("--source", choices=sorted(TRUSTED_SOURCES), default="imported_dataset")
    parser.add_argument("--collection-tier", choices=["trusted", "quarantine"], default="trusted")
    parser.add_argument("--computer-difficulty", default="imported_pgn")
    parser.add_argument("--source-label", default="", help="Optional dataset label stored in pgn_labels.source_label.")
    return parser.parse_args()


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _sha256_json(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _download_url(url: str, download_dir: Path, *, refresh: bool) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name or hashlib.sha256(url.encode("utf-8")).hexdigest() + ".pgn"
    target = download_dir / name
    if target.exists() and not refresh:
        return target
    request = Request(url, headers={"User-Agent": "hackme-web-chess-pgn-import/1.0"})
    with urlopen(request, timeout=45) as response:
        with tempfile.NamedTemporaryFile(delete=False, dir=str(download_dir)) as tmp:
            shutil.copyfileobj(response, tmp)
            tmp_path = Path(tmp.name)
    tmp_path.replace(target)
    return target


def _open_text(path: Path):
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes[-1:] == [".gz"]:
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if suffixes[-1:] == [".bz2"]:
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    if suffixes[-1:] == [".zip"]:
        return _ZipPgnText(path)
    if suffixes[-1:] == [".zst"]:
        try:
            import zstandard as zstd  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional package.
            raise RuntimeError(
                "Reading .zst PGN files requires the optional Python package 'zstandard'. "
                "Install it or decompress the file first with zstd -dc."
            ) from exc
        raw = path.open("rb")
        reader = zstd.ZstdDecompressor().stream_reader(raw)
        return io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


def _int_header(headers: chess.pgn.Headers, key: str) -> int | None:
    value = str(headers.get(key, "") or "").strip()
    if not value or value == "?":
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _avg_elo(headers: chess.pgn.Headers) -> int | None:
    ratings = [rating for rating in (_int_header(headers, "WhiteElo"), _int_header(headers, "BlackElo")) if rating]
    if not ratings:
        return None
    return int(round(sum(ratings) / len(ratings)))


def _rating_band(avg_elo: int | None) -> str:
    if avg_elo is None:
        return "unknown_rating"
    if avg_elo >= 2500:
        return "elite"
    if avg_elo >= 2200:
        return "master"
    if avg_elo >= 1800:
        return "strong_club"
    if avg_elo >= 1200:
        return "club"
    return "low_or_unknown_quality"


def _time_control_class(value: str) -> str:
    value = str(value or "").strip()
    if not value or value == "?":
        return "unknown_time_control"
    first = value.split("+", 1)[0]
    if not first.isdigit():
        return "unknown_time_control"
    seconds = int(first)
    if seconds < 180:
        return "bullet"
    if seconds < 600:
        return "blitz"
    if seconds < 1800:
        return "rapid"
    return "classical"


def _winner_from_result(result: str) -> str | None:
    normalized = str(result or "").strip()
    if normalized == "1-0":
        return "white"
    if normalized == "0-1":
        return "black"
    return None


def _result_filter_ok(result: str, wanted: str) -> bool:
    if wanted == "any":
        return True
    if wanted == "decisive":
        return result in {"1-0", "0-1"}
    return result in {"1/2-1/2", "1/2"}


def _result_reason(board: chess.Board, result: str) -> str:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient_material"
    if board.is_seventyfive_moves():
        return "seventyfive_moves"
    if board.is_fivefold_repetition():
        return "fivefold_repetition"
    termination = str(result or "").strip()
    if termination in {"1-0", "0-1", "1/2-1/2"}:
        return "pgn_result"
    return "unknown"


def _natural_or_unknown(reason: str) -> str:
    return "natural" if reason in {"checkmate", "stalemate", "insufficient_material"} else "unknown"


def _captured_piece(board: chess.Board, move: chess.Move) -> chess.Piece | None:
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board.piece_at(capture_square)
    return captured


def _material_bucket(board: chess.Board) -> str:
    non_king_piece_count = 0
    non_pawn_piece_count = 0
    for piece in board.piece_map().values():
        if piece.piece_type == chess.KING:
            continue
        non_king_piece_count += 1
        if piece.piece_type != chess.PAWN:
            non_pawn_piece_count += 1
    if non_king_piece_count <= 8 or non_pawn_piece_count <= 4:
        return "endgame_material"
    if non_king_piece_count <= 18:
        return "reduced_material"
    return "full_material"


def _game_length_bucket(ply_count: int) -> str:
    if ply_count < 30:
        return "short_game"
    if ply_count < 80:
        return "medium_game"
    return "long_game"


def _confidence_score(source: str, avg_elo: int | None, ply_count: int, *, has_illegal: bool) -> float:
    base = {
        "benchmark": 0.98,
        "teacher_guidance": 0.95,
        "imported_dataset": 0.88,
        "external": 0.75,
    }.get(source, 0.7)
    if avg_elo is not None and avg_elo >= 2200:
        base += 0.06
    elif avg_elo is not None and avg_elo < 1200:
        base -= 0.12
    if ply_count < 8:
        base -= 0.2
    if has_illegal:
        base -= 0.5
    return max(0.0, min(1.0, round(base, 4)))


def _duplicate_signature(opening_seed: str, result_reason: str, move_history: list[dict], engine_name: str) -> str:
    return _sha256_json(
        {
            "opening_seed": opening_seed,
            "result_reason": result_reason,
            "engine_name": engine_name,
            "moves": [str(entry.get("uci") or "") for entry in move_history],
        }
    )


def _existing_ids_and_signatures(path: Path) -> tuple[set[str], set[str]]:
    replay_ids: set[str] = set()
    signatures: set[str] = set()
    if not path.exists():
        return replay_ids, signatures
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            if payload.get("replay_id"):
                replay_ids.add(str(payload["replay_id"]))
            if payload.get("duplicate_signature"):
                signatures.add(str(payload["duplicate_signature"]))
    return replay_ids, signatures


def _record_from_game(
    game: chess.pgn.Game,
    *,
    input_label: str,
    input_index: int,
    source: str,
    collection_tier: str,
    computer_difficulty: str,
    source_label: str,
) -> tuple[dict | None, str | None]:
    headers = game.headers
    board = game.board()
    initial_fen = board.fen()
    opening_seed = "standard_start" if initial_fen == chess.STARTING_FEN else initial_fen
    result = str(headers.get("Result", "*") or "*").strip()
    move_history: list[dict] = []
    has_castling = False
    has_promotion = False
    has_en_passant = False
    has_capture = False
    has_check = False
    illegal_reason = None
    for ply_index, move in enumerate(game.mainline_moves(), start=1):
        if move not in board.legal_moves:
            illegal_reason = f"illegal_move:{move.uci()}:ply_{ply_index}"
            break
        piece = board.piece_at(move.from_square)
        captured = _captured_piece(board, move)
        san = board.san(move)
        castle = board.is_castling(move)
        en_passant = board.is_en_passant(move)
        board_before = board.fen()
        by = "white" if board.turn == chess.WHITE else "black"
        board.push(move)
        has_castling = has_castling or castle
        has_promotion = has_promotion or bool(move.promotion)
        has_en_passant = has_en_passant or en_passant
        has_capture = has_capture or bool(captured)
        has_check = has_check or board.is_check()
        move_history.append(
            {
                "by": by,
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
                "uci": move.uci(),
                "san": san,
                "piece": piece.symbol() if piece else "",
                "captured": captured.symbol() if captured else None,
                "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
                "castle": bool(castle),
                "en_passant": bool(en_passant),
                "check_after": bool(board.is_check()),
                "fen_before": board_before,
                "fen_after": board.fen(),
            }
        )
    if illegal_reason:
        return None, illegal_reason
    winner_color = _winner_from_result(result)
    result_reason = _result_reason(board, result)
    avg_elo = _avg_elo(headers)
    rating_band = _rating_band(avg_elo)
    time_class = _time_control_class(str(headers.get("TimeControl", "") or ""))
    ply_count = len(move_history)
    length_bucket = _game_length_bucket(ply_count)
    material_bucket = _material_bucket(board)
    special_rules = []
    if has_castling:
        special_rules.append("castling")
    if has_promotion:
        special_rules.append("promotion")
    if has_en_passant:
        special_rules.append("en_passant")
    categories = {
        length_bucket,
        material_bucket,
        rating_band,
        time_class,
        "decisive" if winner_color else "draw_or_unknown",
    }
    if board.is_checkmate():
        categories.add("checkmate")
    if has_capture:
        categories.add("contains_capture")
    if has_check:
        categories.add("contains_check")
    for special in special_rules:
        categories.add(f"contains_{special}")
    if result_reason == "pgn_result" and winner_color and ply_count < 45:
        categories.add("short_decisive")
    replay_fingerprint = {
        "input_label": input_label,
        "input_index": input_index,
        "headers": dict(headers),
        "moves": [entry["uci"] for entry in move_history],
        "initial_fen": initial_fen,
    }
    replay_id = _sha256_json(replay_fingerprint)
    duplicate_signature = _duplicate_signature(opening_seed, result_reason, move_history, computer_difficulty)
    record = {
        "match_id": int(replay_id[:12], 16) % 2147483647,
        "game_key": "chess",
        "mode": "external",
        "engine_name": computer_difficulty,
        "engine_version": "pgn_import",
        "white_engine": str(headers.get("White", "") or "pgn_white"),
        "black_engine": str(headers.get("Black", "") or "pgn_black"),
        "opening_seed": opening_seed,
        "result": winner_color or "draw",
        "winner_color": winner_color,
        "adjudicated_or_natural": _natural_or_unknown(result_reason),
        "move_count": ply_count,
        "timestamp": _now(),
        "source": source,
        "rating_estimate": avg_elo,
        "suspicious_flag": False,
        "duplicate_flag": False,
        "resign_abuse_flag": False,
        "confidence_score": _confidence_score(source, avg_elo, ply_count, has_illegal=False),
        "collection_tier": collection_tier,
        "quarantine_reasons": [],
        "actor_username": None,
        "human_side": "white",
        "computer_difficulty": computer_difficulty,
        "result_reason": result_reason,
        "updated_at": _now(),
        "move_history": move_history,
        "replay_id": replay_id,
        "duplicate_signature": duplicate_signature,
        "pgn_headers": dict(headers),
        "pgn_source": input_label,
        "pgn_source_index": input_index,
        "pgn_labels": {
            "source_label": source_label or None,
            "event": str(headers.get("Event", "") or ""),
            "site": str(headers.get("Site", "") or ""),
            "date": str(headers.get("Date", "") or ""),
            "eco": str(headers.get("ECO", "") or ""),
            "opening": str(headers.get("Opening", "") or ""),
            "termination": str(headers.get("Termination", "") or ""),
            "time_control": str(headers.get("TimeControl", "") or ""),
            "time_control_class": time_class,
            "white_elo": _int_header(headers, "WhiteElo"),
            "black_elo": _int_header(headers, "BlackElo"),
            "avg_elo": avg_elo,
            "rating_band": rating_band,
            "game_length": length_bucket,
            "material_bucket": material_bucket,
            "special_rules": special_rules,
            "categories": sorted(categories),
        },
        "training_tags": sorted(categories),
    }
    return record, None


def _iter_games(path: Path) -> Iterable[chess.pgn.Game]:
    with _open_text(path) as handle:
        while True:
            game = chess.pgn.read_game(handle)
            if game is None:
                break
            yield game


def _eligible_record(record: dict, *, min_elo: int, min_ply: int, result: str, skip_nonstandard_start: bool) -> str | None:
    if int(record.get("move_count") or 0) < min_ply:
        return "too_short"
    if skip_nonstandard_start and str(record.get("opening_seed") or "") != "standard_start":
        return "nonstandard_start"
    if min_elo and int(record.get("rating_estimate") or 0) < min_elo:
        return "elo_below_min"
    pgn_result = str((record.get("pgn_headers") or {}).get("Result") or "")
    if not _result_filter_ok(pgn_result, result):
        return "result_filter"
    return None


def _reservoir_insert(selected: list[dict], record: dict, *, seen: int, sample_size: int, rng: random.Random) -> None:
    if sample_size <= 0:
        selected.append(record)
        return
    if len(selected) < sample_size:
        selected.append(record)
        return
    index = rng.randint(0, seen - 1)
    if index < sample_size:
        selected[index] = record


def _write_jsonl(path: Path, records: list[dict], *, replace_output: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if replace_output else "a"
    with path.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    input_paths = [Path(path).expanduser().resolve() for path in args.input_pgn]
    for url in args.source_url:
        input_paths.append(
            _download_url(
                url,
                Path(args.download_dir).expanduser().resolve(),
                refresh=bool(args.refresh_downloads),
            ).resolve()
        )
    if not input_paths:
        print("At least one --input-pgn or --source-url is required.", file=sys.stderr)
        return 2

    output_path = Path(args.output_jsonl).expanduser().resolve()
    existing_ids, existing_signatures = (set(), set()) if args.replace_output else _existing_ids_and_signatures(output_path)
    rng = random.Random(int(args.seed))
    selected: list[dict] = []
    skipped = Counter()
    scanned = 0
    eligible_seen = 0
    emitted_cap = int(args.sample_size or args.max_games or 0)

    for input_path in input_paths:
        if not input_path.exists():
            skipped["missing_input"] += 1
            continue
        for index, game in enumerate(_iter_games(input_path), start=1):
            scanned += 1
            if args.scan_limit and scanned > int(args.scan_limit):
                break
            record, error = _record_from_game(
                game,
                input_label=str(input_path),
                input_index=index,
                source=str(args.source),
                collection_tier=str(args.collection_tier),
                computer_difficulty=str(args.computer_difficulty),
                source_label=str(args.source_label or ""),
            )
            if error or record is None:
                skipped[error or "parse_error"] += 1
                continue
            ineligible = _eligible_record(
                record,
                min_elo=int(args.min_elo or 0),
                min_ply=int(args.min_ply or 0),
                result=str(args.result),
                skip_nonstandard_start=bool(args.skip_nonstandard_start),
            )
            if ineligible:
                skipped[ineligible] += 1
                continue
            if not args.allow_duplicates and (
                str(record.get("replay_id") or "") in existing_ids
                or str(record.get("duplicate_signature") or "") in existing_signatures
            ):
                skipped["duplicate"] += 1
                continue
            eligible_seen += 1
            _reservoir_insert(selected, record, seen=eligible_seen, sample_size=int(args.sample_size or 0), rng=rng)
            if not args.sample_size and args.max_games and len(selected) >= int(args.max_games):
                break
        if args.scan_limit and scanned >= int(args.scan_limit):
            break
        if not args.sample_size and args.max_games and len(selected) >= int(args.max_games):
            break

    if args.sample_size and args.max_games and len(selected) > int(args.max_games):
        selected = selected[: int(args.max_games)]
    if emitted_cap and len(selected) > emitted_cap:
        selected = selected[:emitted_cap]

    for record in selected:
        existing_ids.add(str(record.get("replay_id") or ""))
        existing_signatures.add(str(record.get("duplicate_signature") or ""))

    _write_jsonl(output_path, selected, replace_output=bool(args.replace_output))
    category_counts = Counter()
    special_counts = Counter()
    for record in selected:
        labels = record.get("pgn_labels") or {}
        category_counts.update(labels.get("categories") or [])
        special_counts.update(labels.get("special_rules") or [])
    summary = {
        "ok": True,
        "generated_at": _now(),
        "input_paths": [str(path) for path in input_paths],
        "output_jsonl": str(output_path),
        "replace_output": bool(args.replace_output),
        "scanned_games": scanned,
        "eligible_games": eligible_seen,
        "written_records": len(selected),
        "sample_size": int(args.sample_size or 0),
        "seed": int(args.seed),
        "skipped": dict(sorted(skipped.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "special_rule_counts": dict(sorted(special_counts.items())),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
