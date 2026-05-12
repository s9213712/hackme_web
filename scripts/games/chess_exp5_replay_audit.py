#!/usr/bin/env python3
"""Game-level replay audit for chess training data.

Implements items 7, 8, 9 from the example2 exp3 analysis:

- **item 7** — Pattern-level suspicious flags missed by the existing
  `_suspicious_flag` heuristic in `chess_replay_buffer.py`:
  - `pattern_never_castled`
  - `pattern_early_king_move` (king moved from starting square ≤ ply N
    without castling)
  - `pattern_rim_knight_early` (knight to a3/h3/a6/h6 within first M plies)
  - `pattern_queen_for_minor_early` (queen captures non-queen ≤ ply Q)

- **item 8** — Eval-based resign validator:
  - When `result_reason == "resign"`, re-evaluate the position just before
    the resign with the **deterministic** `fixed_depth_strong` NNUE
    profile. If the resigning side's eval ≥ -300cp AND there is no mate
    against the resigning side within 5 plies, flag
    `resign_questionable`.

- **item 9** — Loser-side blunder mining:
  - Replay each loser-side move with a fixed-depth eval before and after.
  - If `eval_after - eval_before <= -200cp` (from the loser's
    perspective), record that move as a hard-negative candidate to
    feed back into distill / training as a NEGATIVE sample.

Reads JSONL replay files in the same format as
`chess_replays_exp3_example*.jsonl`. Writes:

- per-row audit JSONL (`included_in_pool`, `quarantine_reasons`, all
  pattern flags, resign_questionable, blunder_moves[])
- per-pool summary JSON

Designed to run against existing replay ledgers BEFORE they're used as
training data — mirroring how exp3's `chess_replay_buffer` adds tier
classification at ingest time.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import (  # noqa: E402
    default_chess_nnue_model_path,
    rank_experiment_nnue_policy_moves,
)


def _progress(msg: str) -> None:
    print(f"[chess-exp5-replay-audit] {msg}", file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Game-level audit for chess replay JSONL files.")
    parser.add_argument("--replay-jsonl", action="append", required=True, help="Replay ledger JSONL(s) to audit.")
    parser.add_argument("--audit-output-jsonl", required=True, help="Per-row audit JSONL output path.")
    parser.add_argument("--summary-output-json", required=True, help="Per-pool summary JSON output path.")
    parser.add_argument("--quarantine-output-jsonl", default="", help="Optional: write rows flagged for quarantine to this file.")
    parser.add_argument("--blunder-output-jsonl", default="", help="Optional: write loser-side blunder moves as hard-negative candidates.")
    parser.add_argument("--baseline-model-path", default="", help="NNUE model used for eval-based resign + blunder check.")
    parser.add_argument("--search-profile", default="fixed_depth_strong", help="Search profile used for eval probes (must be deterministic).")
    parser.add_argument("--early-king-move-max-ply", type=int, default=20, help="Plies after which a non-castling king move from e1/e8 is no longer flagged.")
    parser.add_argument("--rim-knight-max-ply", type=int, default=10, help="Plies after which a knight to a3/h3/a6/h6 is no longer flagged.")
    parser.add_argument("--queen-trade-max-ply", type=int, default=8, help="Plies within which a queen capturing a non-queen is flagged.")
    parser.add_argument("--never-castle-min-plies-with-rights", type=int, default=10, help="If castling rights existed for this many plies and the side never castled, flag never_castled.")
    parser.add_argument("--resign-eval-floor-cp", type=float, default=-300.0, help="Resigning side's eval must be <= this to justify resign.")
    parser.add_argument("--blunder-drop-cp", type=float, default=-200.0, help="A move whose eval-after - eval-before from the moving side's perspective drops by at least this magnitude is flagged.")
    return parser.parse_args()


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            yield (line_no, payload)


def _piece_value(p: chess.PieceType) -> int:
    return {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 335, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000}.get(p, 0)


def _nnue_top1_score(model_path: Path, fen: str, side: str, *, search_profile: str) -> float:
    """Return the raw_policy_score of the top-1 move from the given side's perspective.

    Higher = better for `side` (the policy ranker already side-adjusts).
    """
    rows = rank_experiment_nnue_policy_moves({"__fen__": fen}, side, model_path=model_path, search_profile=search_profile)
    if not rows:
        return 0.0
    return float(rows[0].get("raw_policy_score") or 0.0)


def _mate_within(board: chess.Board, plies: int, *, against: chess.Color) -> bool:
    """Cheap mate-in-K detector: try moves up to K plies; if `against` is mated, return True."""
    if plies <= 0:
        return board.is_checkmate() and board.turn == against
    if board.is_checkmate():
        return board.turn == against
    if board.is_game_over():
        return False
    for mv in board.legal_moves:
        board.push(mv)
        ok = _mate_within(board, plies - 1, against=against)
        board.pop()
        if board.turn == against:
            # we wanted to find mate against `against`; opponent moves, look for OUR mate
            if ok:
                return True
        else:
            # `against` to move: if every reply still ends in mate it's mate-in
            # (light approximation: any move leads to mate -> mate)
            if not ok:
                return False
    return board.turn != against


def _audit_record(rec: dict, args: argparse.Namespace, model_path: Path) -> dict:
    history = rec.get("move_history") or []
    if not isinstance(history, list):
        history = []
    side_white = rec.get("white_engine")
    side_black = rec.get("black_engine")
    move_count = len(history)
    result_reason = str(rec.get("result_reason") or "").lower()
    winner_color = str(rec.get("winner_color") or "").lower()

    flags: list[str] = []
    notes: dict = {}

    board = chess.Board()
    seen_castled = {"white": False, "black": False}
    first_king_move_ply = {"white": None, "black": None}
    rim_knight_ply = {"white": None, "black": None}
    queen_for_minor_ply = {"white": None, "black": None}
    castling_rights_plies = {"white": 0, "black": 0}
    blunder_moves: list[dict] = []

    for ply_idx, m in enumerate(history, start=1):
        if not isinstance(m, dict):
            break
        from_sq = str(m.get("from") or "").strip().lower()
        to_sq = str(m.get("to") or "").strip().lower()
        promotion = str(m.get("promotion") or "").strip().lower()
        side = str(m.get("by") or "").strip().lower()
        if not from_sq or not to_sq:
            break
        try:
            mv = board.parse_uci(f"{from_sq}{to_sq}{promotion}")
        except Exception:
            break
        if mv not in board.legal_moves:
            break

        piece = board.piece_at(mv.from_square)
        is_castle = board.is_castling(mv)
        if is_castle and side in seen_castled:
            seen_castled[side] = True
        # castling rights tracking
        for s_name, color in (("white", chess.WHITE), ("black", chess.BLACK)):
            if board.has_kingside_castling_rights(color) or board.has_queenside_castling_rights(color):
                castling_rights_plies[s_name] += 1

        if piece is not None and piece.piece_type == chess.KING and from_sq in ("e1", "e8") and not is_castle:
            if first_king_move_ply.get(side) is None:
                first_king_move_ply[side] = ply_idx

        if piece is not None and piece.piece_type == chess.KNIGHT and to_sq in ("a3", "h3", "a6", "h6"):
            if rim_knight_ply.get(side) is None and ply_idx <= int(args.rim_knight_max_ply):
                rim_knight_ply[side] = ply_idx

        # queen-for-minor: queen captures non-queen
        if piece is not None and piece.piece_type == chess.QUEEN and board.is_capture(mv):
            captured = board.piece_at(mv.to_square)
            if board.is_en_passant(mv):
                cap_sq = chess.square(chess.square_file(mv.to_square), chess.square_rank(mv.from_square))
                captured = board.piece_at(cap_sq)
            if captured is not None and captured.piece_type != chess.QUEEN and ply_idx <= int(args.queen_trade_max_ply):
                if queen_for_minor_ply.get(side) is None:
                    queen_for_minor_ply[side] = ply_idx

        # eval drop check for loser-side blunders (item 9):
        # we score from the moving side's perspective before and after.
        # Skip if model_path missing.
        if model_path and result_reason in {"checkmate", "resign", "stalemate", "draw"}:
            try:
                fen_before = board.fen()
                eval_before = _nnue_top1_score(model_path, fen_before, side, search_profile=args.search_profile)
                board.push(mv)
                # after the move, it's the opponent's turn; we still want the
                # eval from `side`'s perspective. Easiest: re-score using
                # `side` argument so the ranker side-adjusts.
                fen_after = board.fen()
                eval_after_other = _nnue_top1_score(model_path, fen_after, side, search_profile=args.search_profile)
                board.pop()
                # eval_top1_for_side = best move for `side` evaluated under `side`.
                # When we ask the same after the move, the policy returns the
                # best move available now to `side` again, which is comparable.
                drop = eval_after_other - eval_before
                # consider blunder only if this is a loser-side move
                if winner_color and winner_color != side and drop <= float(args.blunder_drop_cp):
                    blunder_moves.append({
                        "ply": ply_idx,
                        "side": side,
                        "fen_before": fen_before,
                        "move_uci": mv.uci(),
                        "eval_before_cp": round(eval_before, 2),
                        "eval_after_cp": round(eval_after_other, 2),
                        "eval_drop_cp": round(drop, 2),
                    })
            except Exception:
                pass

        board.push(mv)

    # patterns
    pattern_flags = []
    for sn in ("white", "black"):
        if not seen_castled[sn] and castling_rights_plies[sn] >= int(args.never_castle_min_plies_with_rights):
            pattern_flags.append(f"pattern_never_castled_{sn}")
        fkm = first_king_move_ply[sn]
        if fkm is not None and fkm <= int(args.early_king_move_max_ply):
            pattern_flags.append(f"pattern_early_king_move_{sn}_ply{fkm}")
        rkp = rim_knight_ply[sn]
        if rkp is not None:
            pattern_flags.append(f"pattern_rim_knight_early_{sn}_ply{rkp}")
        qfp = queen_for_minor_ply[sn]
        if qfp is not None:
            pattern_flags.append(f"pattern_queen_for_minor_early_{sn}_ply{qfp}")

    flags.extend(pattern_flags)
    notes["seen_castled"] = seen_castled
    notes["first_king_move_ply"] = first_king_move_ply
    notes["rim_knight_ply"] = rim_knight_ply
    notes["queen_for_minor_ply"] = queen_for_minor_ply
    notes["castling_rights_plies"] = castling_rights_plies

    # item 8: resign validator
    resign_questionable = False
    resign_eval_cp = None
    resign_mate_distance = None
    if result_reason == "resign" and model_path:
        # The board now has all moves applied; the resigning side is the
        # loser (the side that is NOT winner_color).
        resigner = "white" if winner_color == "black" else "black"
        # Eval from resigner's side. We use board.turn at end of game.
        try:
            resign_eval_cp = _nnue_top1_score(model_path, board.fen(), resigner, search_profile=args.search_profile)
            # cheap mate-in-≤5 search against resigner
            if board.turn == chess.WHITE and resigner == "white":
                # resigner is to move; check if they're mated soon
                resign_mate_distance = _mate_within(board, 5, against=(chess.WHITE if resigner == "white" else chess.BLACK))
            else:
                resign_mate_distance = _mate_within(board, 5, against=(chess.WHITE if resigner == "white" else chess.BLACK))
            if resign_eval_cp >= float(args.resign_eval_floor_cp) and not resign_mate_distance:
                resign_questionable = True
                flags.append("resign_questionable_by_eval")
        except Exception:
            pass

    audit_row = {
        "match_id": rec.get("match_id"),
        "replay_id": rec.get("replay_id"),
        "white_engine": side_white,
        "black_engine": side_black,
        "move_count": move_count,
        "result_reason": result_reason,
        "winner_color": winner_color,
        "source": rec.get("source"),
        "collection_tier_input": rec.get("collection_tier"),
        "suspicious_flag_input": bool(rec.get("suspicious_flag")),
        "pattern_flags": flags,
        "resign_questionable": resign_questionable,
        "resign_eval_cp": resign_eval_cp,
        "resign_mate_within_5": bool(resign_mate_distance) if resign_mate_distance is not None else None,
        "blunder_move_count": len(blunder_moves),
        "blunder_moves": blunder_moves,
        "notes": notes,
        "quarantine_recommendation": "quarantine" if (flags or resign_questionable) else "keep",
    }
    return audit_row


def main() -> int:
    args = parse_args()
    model_path = (
        Path(args.baseline_model_path).expanduser().resolve()
        if args.baseline_model_path
        else default_chess_nnue_model_path()
    )

    rows_in = 0
    audits: list[dict] = []
    for replay_path_str in args.replay_jsonl:
        replay_path = Path(replay_path_str).expanduser().resolve()
        _progress(f"phase read replay: {replay_path}")
        for line_no, rec in _iter_jsonl(replay_path):
            rows_in += 1
            audit = _audit_record(rec, args, model_path)
            audit["_source_path"] = str(replay_path)
            audit["_source_line"] = line_no
            audits.append(audit)

    audit_out = Path(args.audit_output_jsonl).expanduser().resolve()
    audit_out.parent.mkdir(parents=True, exist_ok=True)
    with audit_out.open("w", encoding="utf-8") as handle:
        for a in audits:
            handle.write(json.dumps(a, ensure_ascii=False, sort_keys=True) + "\n")

    quarantine_out_count = 0
    if args.quarantine_output_jsonl:
        qpath = Path(args.quarantine_output_jsonl).expanduser().resolve()
        qpath.parent.mkdir(parents=True, exist_ok=True)
        with qpath.open("w", encoding="utf-8") as handle:
            for a in audits:
                if a["quarantine_recommendation"] == "quarantine":
                    handle.write(json.dumps(a, ensure_ascii=False, sort_keys=True) + "\n")
                    quarantine_out_count += 1

    blunder_total = 0
    if args.blunder_output_jsonl:
        bpath = Path(args.blunder_output_jsonl).expanduser().resolve()
        bpath.parent.mkdir(parents=True, exist_ok=True)
        with bpath.open("w", encoding="utf-8") as handle:
            for a in audits:
                for bm in a["blunder_moves"]:
                    handle.write(
                        json.dumps(
                            {
                                "match_id": a["match_id"],
                                "replay_id": a["replay_id"],
                                **bm,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    blunder_total += 1

    # summary
    flagged = [a for a in audits if a["pattern_flags"] or a["resign_questionable"]]
    pattern_counts: dict[str, int] = {}
    for a in audits:
        for f in a["pattern_flags"]:
            # strip per-side suffix for aggregation
            base = f.split("_ply")[0]
            pattern_counts[base] = pattern_counts.get(base, 0) + 1
    summary = {
        "ok": True,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "replay_paths": [str(Path(p).expanduser().resolve()) for p in args.replay_jsonl],
        "audit_output": str(audit_out),
        "quarantine_output": args.quarantine_output_jsonl or "",
        "blunder_output": args.blunder_output_jsonl or "",
        "search_profile": args.search_profile,
        "thresholds": {
            "early_king_move_max_ply": args.early_king_move_max_ply,
            "rim_knight_max_ply": args.rim_knight_max_ply,
            "queen_trade_max_ply": args.queen_trade_max_ply,
            "never_castle_min_plies_with_rights": args.never_castle_min_plies_with_rights,
            "resign_eval_floor_cp": args.resign_eval_floor_cp,
            "blunder_drop_cp": args.blunder_drop_cp,
        },
        "rows_seen": rows_in,
        "rows_audited": len(audits),
        "rows_flagged_total": len(flagged),
        "rows_recommended_quarantine": sum(1 for a in audits if a["quarantine_recommendation"] == "quarantine"),
        "rows_resign_questionable": sum(1 for a in audits if a["resign_questionable"]),
        "rows_with_blunder_moves": sum(1 for a in audits if a["blunder_move_count"] > 0),
        "blunder_moves_total": blunder_total,
        "pattern_counts": pattern_counts,
        "quarantine_rows_written": quarantine_out_count,
    }
    spath = Path(args.summary_output_json).expanduser().resolve()
    spath.parent.mkdir(parents=True, exist_ok=True)
    spath.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        raise
