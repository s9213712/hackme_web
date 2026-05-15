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
import re
import shutil
import subprocess
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
RUNTIME_ROOT = Path(__file__).resolve().parents[2]
REQUIRE_TAG_CHOICES = {
    "club",
    "strong_club",
    "master",
    "elite",
    "rapid",
    "classical",
    "decisive",
    "draw_or_unknown",
    "short_game",
    "medium_game",
    "long_game",
    "full_material",
    "reduced_material",
    "endgame_material",
    "contains_capture",
    "contains_check",
    "contains_castling",
    "contains_promotion",
    "contains_en_passant",
    "checkmate",
    "short_decisive",
}
INTERACTIVE_PRESETS = {
    "1": ("master_decisive", {"min_elo": 2200, "result": "decisive", "require_tag": []}),
    "2": ("elite_any", {"min_elo": 2500, "result": "any", "require_tag": []}),
    "3": ("rapid_or_classical", {"min_elo": 1800, "result": "any", "require_tag": []}),
    "4": ("endgame_material", {"min_elo": 0, "result": "any", "require_tag": ["endgame_material"]}),
    "5": ("special_rules", {"min_elo": 0, "result": "any", "require_tag": []}),
    "6": ("custom", {"min_elo": 0, "result": "any", "require_tag": []}),
}


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
    parser.add_argument("--interactive", action="store_true", help="Prompt for source, filters, output path, and options.")
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
    parser.add_argument("--require-tag", action="append", default=[], choices=sorted(REQUIRE_TAG_CHOICES))
    parser.add_argument("--position-scope", choices=["any", "complete", "fragment"], default="any")
    parser.add_argument("--valid-games-only", action="store_true", help="Shortcut for --valid-game-filter basic.")
    parser.add_argument("--valid-game-filter", choices=["off", "basic", "strict", "elite"], default="off")
    parser.add_argument("--skip-nonstandard-start", action="store_true")
    parser.add_argument("--output-format", choices=["replay-jsonl", "prepared-dataset"], default="replay-jsonl")
    parser.add_argument("--prepared-output-dir", default="")
    parser.add_argument("--distill-manifest", default="", help="Write a manifest for a later teacher-distill run.")
    parser.add_argument(
        "--stockfish-filter",
        action="store_true",
        help=(
            "After writing replay JSONL, run the local external Stockfish teacher audit/filter. "
            "Requires a local Stockfish binary; no binary is downloaded or bundled."
        ),
    )
    parser.add_argument("--stockfish-output-dir", default="", help="Output directory for --stockfish-filter artifacts.")
    parser.add_argument("--stockfish-path", default="", help="Local Stockfish-compatible UCI binary for --stockfish-filter.")
    parser.add_argument("--stockfish-depth", type=int, default=8, help="Stockfish depth for --stockfish-filter.")
    parser.add_argument("--stockfish-movetime-ms", type=int, default=0, help="Optional Stockfish movetime for --stockfish-filter.")
    parser.add_argument("--stockfish-multipv", type=int, default=5, help="Stockfish MultiPV count for --stockfish-filter.")
    parser.add_argument("--stockfish-max-positions", type=int, default=0, help="Maximum positions to audit after PGN conversion.")
    parser.add_argument(
        "--stockfish-eval-mod",
        type=int,
        default=10,
        help="Deterministic Stockfish split modulus for --stockfish-filter: bucket 0 => eval, others => train.",
    )
    parser.add_argument("--allow-empty-output", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--source", choices=sorted(TRUSTED_SOURCES), default="imported_dataset")
    parser.add_argument("--collection-tier", choices=["trusted", "quarantine"], default="trusted")
    parser.add_argument("--computer-difficulty", default="imported_pgn")
    parser.add_argument("--source-label", default="", help="Optional dataset label stored in pgn_labels.source_label.")
    return parser.parse_args()


def _prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    print(f"{message}{suffix}: ", file=sys.stderr, end="", flush=True)
    value = input().strip()
    return value or default


def _prompt_bool(message: str, default: bool = False) -> bool:
    default_label = "Y/n" if default else "y/N"
    value = _prompt(f"{message} ({default_label})", "y" if default else "n").strip().lower()
    return value in {"y", "yes", "1", "true", "t", "是", "好"}


def _prompt_choice(message: str, choices: dict[str, str], default: str) -> str:
    print(message, file=sys.stderr)
    for key, label in choices.items():
        print(f"  {key}. {label}", file=sys.stderr)
    while True:
        value = _prompt("選項", default)
        if value in choices:
            return value
        print(f"無效選項：{value}", file=sys.stderr)


def _default_output_for_source(source_value: str, *, output_format: str) -> str:
    safe = Path(urlparse(source_value).path).name if source_value.startswith(("http://", "https://")) else Path(source_value).stem
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (safe or "imported"))
    suffix = "prepared" if output_format == "prepared-dataset" else "replay"
    return str(Path.home() / "chess_results" / f"{safe}_{suffix}.jsonl")


def _run_interactive(args: argparse.Namespace) -> argparse.Namespace:
    print("Chess PGN import interactive mode", file=sys.stderr)
    source_kind = _prompt_choice(
        "選來源",
        {"1": "本地 PGN/ZIP/GZ/BZ2/ZST", "2": "下載 URL"},
        "1",
    )
    if source_kind == "1":
        args.input_pgn = [_prompt("本地檔案路徑")]
        args.source_url = []
    else:
        args.source_url = [_prompt("PGN/ZIP/GZ/BZ2/ZST URL")]
        args.input_pgn = []

    preset_key = _prompt_choice(
        "選分類/篩選類型",
        {
            "1": "Master decisive: Elo >= 2200 且決勝局",
            "2": "Elite: Elo >= 2500",
            "3": "Strong rapid/classical candidate: Elo >= 1800",
            "4": "Endgame material: 殘局材料標籤",
            "5": "Special rules: 王車易位/升變/吃過路兵",
            "6": "自訂",
        },
        "1",
    )
    preset_name, preset = INTERACTIVE_PRESETS[preset_key]
    args.min_elo = int(_prompt("最低平均 Elo", str(preset["min_elo"])))
    args.result = _prompt_choice("結果", {"1": "any", "2": "decisive", "3": "draw"}, "2" if preset["result"] == "decisive" else "1")
    args.result = {"1": "any", "2": "decisive", "3": "draw"}[args.result]
    args.require_tag = list(preset["require_tag"])
    valid_key = _prompt_choice(
        "有效棋局篩選強度",
        {"1": "off", "2": "basic", "3": "strict", "4": "elite"},
        "2",
    )
    args.valid_game_filter = {"1": "off", "2": "basic", "3": "strict", "4": "elite"}[valid_key]
    args.valid_games_only = args.valid_game_filter != "off"
    if preset_name == "special_rules":
        tag_key = _prompt_choice(
            "特殊規則標籤",
            {"1": "contains_castling", "2": "contains_promotion", "3": "contains_en_passant"},
            "1",
        )
        args.require_tag = [{"1": "contains_castling", "2": "contains_promotion", "3": "contains_en_passant"}[tag_key]]
    elif preset_name == "custom":
        tag = _prompt("必要 training tag，留空表示不限制", "")
        args.require_tag = [tag] if tag else []

    count = int(_prompt("隨機抽樣數量，0 表示不抽樣", "20"))
    args.sample_size = max(0, count)
    args.max_games = int(_prompt("最多輸出幾局，0 表示不限", str(count or 100)))
    args.scan_limit = int(_prompt("最多掃描幾局，0 表示不限", "0"))
    args.seed = int(_prompt("隨機 seed", str(args.seed)))
    args.min_ply = int(_prompt("最少 ply 數", str(args.min_ply)))

    scope_key = _prompt_choice(
        "選完整棋局或殘局/FEN fragment",
        {"1": "any", "2": "complete", "3": "fragment"},
        "2",
    )
    args.position_scope = {"1": "any", "2": "complete", "3": "fragment"}[scope_key]
    args.skip_nonstandard_start = args.position_scope == "complete"

    format_key = _prompt_choice(
        "選輸出格式",
        {"1": "replay-jsonl", "2": "prepared-dataset"},
        "1",
    )
    args.output_format = {"1": "replay-jsonl", "2": "prepared-dataset"}[format_key]
    default_output = _default_output_for_source((args.source_url or args.input_pgn or ["imported"])[0], output_format=args.output_format)
    args.output_jsonl = _prompt("replay JSONL 儲存位置/檔名", default_output)
    args.replace_output = _prompt_bool("覆蓋輸出檔", True)
    if args.output_format == "prepared-dataset":
        args.prepared_output_dir = _prompt(
            "prepared dataset 輸出資料夾",
            str(Path(args.output_jsonl).expanduser().with_suffix("").parent / (Path(args.output_jsonl).stem + "_dataset")),
        )
    if _prompt_bool("是否建立蒸餾 manifest", False):
        args.distill_manifest = _prompt(
            "distill manifest 儲存位置",
            str(Path(args.output_jsonl).expanduser().with_suffix(".distill_manifest.json")),
        )
    args.source_label = _prompt("來源標籤", args.source_label or preset_name)
    args.no_progress = False
    return args


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
    minute_match = re.search(r"(\d+)\s*minutes?", value, re.IGNORECASE)
    if minute_match:
        first_seconds = int(minute_match.group(1)) * 60
        if first_seconds < 180:
            return "bullet"
        if first_seconds < 600:
            return "blitz"
        if first_seconds < 1800:
            return "rapid"
        return "classical"
    hour_match = re.search(r"(\d+)\s*hours?", value, re.IGNORECASE)
    if hour_match:
        return "classical"
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


def _valid_game_rejection(record: dict, strength: str) -> str | None:
    strength = str(strength or "off").strip().lower()
    if strength in {"", "off", "false", "none"}:
        return None
    headers = record.get("pgn_headers") or {}
    labels = record.get("pgn_labels") or {}
    variant = str(headers.get("Variant") or "Standard").strip().lower()
    if variant not in {"", "standard"}:
        return "invalid_variant"
    if str(headers.get("Result") or "").strip() not in {"1-0", "0-1", "1/2-1/2"}:
        return "invalid_result"
    if str(labels.get("termination") or "").strip().lower() in {"abandoned", "unterminated", "time forfeit", "rules infraction"}:
        return "invalid_termination"
    if record.get("rating_estimate") is None:
        return "missing_rating"
    if float(record.get("confidence_score") or 0.0) < 0.75:
        return "low_confidence"
    if record.get("suspicious_flag") or record.get("resign_abuse_flag"):
        return "suspicious_or_abuse"
    if int(record.get("move_count") or 0) < 12:
        return "invalid_too_short"
    if strength in {"strict", "elite"}:
        if str(labels.get("termination") or "").strip().lower() not in {"normal", ""}:
            return "non_normal_termination"
        if str(record.get("opening_seed") or "") != "standard_start":
            return "nonstandard_start"
        if float(record.get("confidence_score") or 0.0) < 0.85:
            return "strict_low_confidence"
        if int(record.get("move_count") or 0) < 20:
            return "strict_too_short"
        if str(labels.get("time_control_class") or "") in {"bullet", "unknown_time_control"}:
            return "strict_time_control"
    if strength == "elite":
        if int(record.get("rating_estimate") or 0) < 2500:
            return "elite_rating_below_min"
        if str(labels.get("time_control_class") or "") not in {"rapid", "classical"}:
            return "elite_time_control"
    return None


def _eligible_record(
    record: dict,
    *,
    min_elo: int,
    min_ply: int,
    result: str,
    skip_nonstandard_start: bool,
    position_scope: str,
    require_tags: list[str],
    valid_game_filter: str,
) -> str | None:
    if valid_game_filter and valid_game_filter != "off":
        invalid_reason = _valid_game_rejection(record, valid_game_filter)
        if invalid_reason:
            return invalid_reason
    if int(record.get("move_count") or 0) < min_ply:
        return "too_short"
    if skip_nonstandard_start and str(record.get("opening_seed") or "") != "standard_start":
        return "nonstandard_start"
    if position_scope == "complete" and str(record.get("opening_seed") or "") != "standard_start":
        return "nonstandard_start"
    if position_scope == "fragment" and str(record.get("opening_seed") or "") == "standard_start":
        return "not_fragment"
    if min_elo and int(record.get("rating_estimate") or 0) < min_elo:
        return "elo_below_min"
    pgn_result = str((record.get("pgn_headers") or {}).get("Result") or "")
    if not _result_filter_ok(pgn_result, result):
        return "result_filter"
    tags = set(record.get("training_tags") or [])
    missing_tags = [tag for tag in require_tags if tag and tag not in tags]
    if missing_tags:
        return "missing_required_tag:" + ",".join(missing_tags)
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


def _progress(scanned: int, eligible: int, selected_count: int, *, limit: int, enabled: bool, final: bool = False) -> None:
    if not enabled:
        return
    if limit > 0:
        ratio = min(1.0, scanned / max(1, limit))
        width = 24
        filled = int(width * ratio)
        bar = "#" * filled + "-" * (width - filled)
        text = f"\r[pgn-import] [{bar}] {ratio:6.1%} scanned={scanned} eligible={eligible} selected={selected_count}"
    else:
        text = f"\r[pgn-import] scanned={scanned} eligible={eligible} selected={selected_count}"
    print(text, file=sys.stderr, end="\n" if final else "", flush=True)


def _write_distill_manifest(path: Path, *, replay_path: Path, records: list[dict], summary: dict) -> dict:
    manifest = {
        "generated_at": _now(),
        "replay_jsonl": str(replay_path),
        "record_count": len(records),
        "replay_ids": [str(record.get("replay_id") or "") for record in records],
        "recommended_next_step": "Run the exp5 teacher distill pipeline against this replay JSONL before retraining.",
        "import_summary": summary,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"distill_manifest": str(path), "distill_requested": True}


def _prepare_dataset(replay_path: Path, output_dir: Path) -> dict:
    command = [
        sys.executable,
        str(RUNTIME_ROOT / "scripts" / "games" / "chess_replay_prepare.py"),
        "--trusted-replay-path",
        str(replay_path),
        "--output-dir",
        str(output_dir),
        "--replace-output",
    ]
    proc = subprocess.run(
        command,
        cwd=str(RUNTIME_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except Exception:
            payload = {"raw_stdout": proc.stdout}
    return {
        "ok": proc.returncode == 0 and bool(payload.get("ok", proc.returncode == 0)),
        "returncode": proc.returncode,
        "command": command,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "summary": payload,
    }


def _run_stockfish_filter(replay_path: Path, args: argparse.Namespace) -> dict:
    if not replay_path.exists():
        return {
            "ok": False,
            "skipped": False,
            "reason": "replay_jsonl_missing",
            "replay_jsonl": str(replay_path),
        }
    output_dir = (
        Path(args.stockfish_output_dir).expanduser().resolve()
        if args.stockfish_output_dir
        else replay_path.with_suffix("").parent / f"{replay_path.stem}_stockfish_filter"
    )
    command = [
        sys.executable,
        str(RUNTIME_ROOT / "scripts" / "games" / "chess_stockfish_teacher_audit.py"),
        "--input-jsonl",
        str(replay_path),
        "--output-dir",
        str(output_dir),
        "--depth",
        str(max(0, int(args.stockfish_depth or 0))),
        "--movetime-ms",
        str(max(0, int(args.stockfish_movetime_ms or 0))),
        "--multipv",
        str(max(1, int(args.stockfish_multipv or 1))),
        "--replace-output",
    ]
    if args.stockfish_path:
        command.extend(["--stockfish-path", str(args.stockfish_path)])
    if int(args.stockfish_max_positions or 0) > 0:
        command.extend(["--max-positions", str(int(args.stockfish_max_positions))])
    if int(args.stockfish_eval_mod or 0) >= 0:
        command.extend(["--eval-mod", str(max(0, int(args.stockfish_eval_mod or 0)))])
    proc = subprocess.run(
        command,
        cwd=str(RUNTIME_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except Exception:
            payload = {"raw_stdout": proc.stdout[-4000:]}
    return {
        "ok": proc.returncode == 0 and str(payload.get("stage") or "") == "stockfish_teacher_audit",
        "returncode": proc.returncode,
        "command": command,
        "output_dir": str(output_dir),
        "summary_path": str(output_dir / "summary.json"),
        "teacher_train_jsonl": str(output_dir / "stockfish_teacher_train_rows.jsonl"),
        "teacher_eval_jsonl": str(output_dir / "stockfish_teacher_eval_rows.jsonl"),
        "played_clean_jsonl": str(output_dir / "stockfish_played_clean_rows.jsonl"),
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "summary": payload,
    }


def main() -> int:
    args = parse_args()
    if args.interactive:
        args = _run_interactive(args)
    input_paths = [Path(path).expanduser().resolve() for path in args.input_pgn]
    errors: list[dict] = []
    for url in args.source_url:
        try:
            input_paths.append(
                _download_url(
                    url,
                    Path(args.download_dir).expanduser().resolve(),
                    refresh=bool(args.refresh_downloads),
                ).resolve()
            )
        except Exception as exc:
            errors.append({"stage": "download", "source": url, "error": str(exc)})
    if not input_paths:
        summary = {
            "ok": False,
            "generated_at": _now(),
            "input_paths": [],
            "output_jsonl": str(Path(args.output_jsonl).expanduser()),
            "errors": errors or [{"stage": "input", "error": "At least one --input-pgn or --source-url is required."}],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    output_path = Path(args.output_jsonl).expanduser().resolve()
    existing_ids, existing_signatures = (set(), set()) if args.replace_output else _existing_ids_and_signatures(output_path)
    rng = random.Random(int(args.seed))
    selected: list[dict] = []
    skipped = Counter()
    scanned = 0
    eligible_seen = 0
    emitted_cap = int(args.sample_size or args.max_games or 0)
    progress_enabled = not bool(args.no_progress)
    progress_limit = int(args.scan_limit or args.max_games or args.sample_size or 0)

    for input_path in input_paths:
        if not input_path.exists():
            skipped["missing_input"] += 1
            errors.append({"stage": "read", "source": str(input_path), "error": "missing_input"})
            continue
        try:
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
                    reason = error or "parse_error"
                    skipped[reason] += 1
                    errors.append({"stage": "parse", "source": str(input_path), "game_index": index, "error": reason})
                    _progress(scanned, eligible_seen, len(selected), limit=progress_limit, enabled=progress_enabled)
                    continue
                ineligible = _eligible_record(
                    record,
                    min_elo=int(args.min_elo or 0),
                    min_ply=int(args.min_ply or 0),
                    result=str(args.result),
                    skip_nonstandard_start=bool(args.skip_nonstandard_start),
                    position_scope=str(args.position_scope or "any"),
                    require_tags=[str(tag) for tag in (args.require_tag or []) if str(tag).strip()],
                    valid_game_filter="basic" if bool(args.valid_games_only) and str(args.valid_game_filter) == "off" else str(args.valid_game_filter),
                )
                if ineligible:
                    skipped[ineligible] += 1
                    _progress(scanned, eligible_seen, len(selected), limit=progress_limit, enabled=progress_enabled)
                    continue
                if not args.allow_duplicates and (
                    str(record.get("replay_id") or "") in existing_ids
                    or str(record.get("duplicate_signature") or "") in existing_signatures
                ):
                    skipped["duplicate"] += 1
                    _progress(scanned, eligible_seen, len(selected), limit=progress_limit, enabled=progress_enabled)
                    continue
                eligible_seen += 1
                _reservoir_insert(selected, record, seen=eligible_seen, sample_size=int(args.sample_size or 0), rng=rng)
                _progress(scanned, eligible_seen, len(selected), limit=progress_limit, enabled=progress_enabled)
                if not args.sample_size and args.max_games and len(selected) >= int(args.max_games):
                    break
        except Exception as exc:
            skipped["read_error"] += 1
            errors.append({"stage": "read", "source": str(input_path), "error": str(exc)})
        if args.scan_limit and scanned >= int(args.scan_limit):
            break
        if not args.sample_size and args.max_games and len(selected) >= int(args.max_games):
                break
    _progress(scanned, eligible_seen, len(selected), limit=progress_limit, enabled=progress_enabled, final=True)

    if args.sample_size and args.max_games and len(selected) > int(args.max_games):
        selected = selected[: int(args.max_games)]
    if emitted_cap and len(selected) > emitted_cap:
        selected = selected[:emitted_cap]

    for record in selected:
        existing_ids.add(str(record.get("replay_id") or ""))
        existing_signatures.add(str(record.get("duplicate_signature") or ""))

    if selected or args.allow_empty_output:
        _write_jsonl(output_path, selected, replace_output=bool(args.replace_output))
    category_counts = Counter()
    special_counts = Counter()
    for record in selected:
        labels = record.get("pgn_labels") or {}
        category_counts.update(labels.get("categories") or [])
        special_counts.update(labels.get("special_rules") or [])
    summary = {
        "ok": bool(selected) or bool(args.allow_empty_output),
        "generated_at": _now(),
        "input_paths": [str(path) for path in input_paths],
        "output_jsonl": str(output_path),
        "output_format": str(args.output_format),
        "replace_output": bool(args.replace_output),
        "scanned_games": scanned,
        "eligible_games": eligible_seen,
        "written_records": len(selected),
        "sample_size": int(args.sample_size or 0),
        "seed": int(args.seed),
        "filters": {
            "min_elo": int(args.min_elo or 0),
            "min_ply": int(args.min_ply or 0),
            "result": str(args.result),
            "position_scope": str(args.position_scope or "any"),
            "require_tag": list(args.require_tag or []),
            "valid_game_filter": "basic" if bool(args.valid_games_only) and str(args.valid_game_filter) == "off" else str(args.valid_game_filter),
            "skip_nonstandard_start": bool(args.skip_nonstandard_start),
        },
        "skipped": dict(sorted(skipped.items())),
        "errors": errors,
        "category_counts": dict(sorted(category_counts.items())),
        "special_rule_counts": dict(sorted(special_counts.items())),
    }
    if selected and args.output_format == "prepared-dataset":
        prepared_dir = Path(args.prepared_output_dir).expanduser().resolve() if args.prepared_output_dir else output_path.with_suffix("").parent / (output_path.stem + "_dataset")
        summary["prepared_dataset"] = _prepare_dataset(output_path, prepared_dir)
        if not summary["prepared_dataset"]["ok"]:
            summary["ok"] = False
            errors.append({"stage": "prepare_dataset", "error": "chess_replay_prepare failed"})
    if selected and args.stockfish_filter:
        summary["stockfish_filter"] = _run_stockfish_filter(output_path, args)
        if not summary["stockfish_filter"]["ok"]:
            summary["ok"] = False
            errors.append({"stage": "stockfish_filter", "error": "chess_stockfish_teacher_audit failed"})
    elif args.stockfish_filter:
        summary["stockfish_filter"] = {
            "ok": False,
            "skipped": True,
            "reason": "no_selected_games",
        }
    if selected and args.distill_manifest:
        try:
            summary.update(_write_distill_manifest(Path(args.distill_manifest).expanduser().resolve(), replay_path=output_path, records=selected, summary=summary))
        except Exception as exc:
            summary["ok"] = False
            errors.append({"stage": "distill_manifest", "error": str(exc)})
    if not selected and not args.allow_empty_output:
        errors.append({"stage": "selection", "error": "No games were written. Check filters, source path, parse errors, or duplicate filtering."})
        summary["errors"] = errors
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
