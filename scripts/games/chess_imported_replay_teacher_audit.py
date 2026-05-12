#!/usr/bin/env python3
"""Teacher-audit imported per-ply replay JSONL — W8 commit 1.

Reads one or more canonical per-ply replay JSONL files (typically produced
by the W7 PGN input stage in ``chess_pipeline_dryrun``) and classifies each
row into ``accepted`` / ``review`` / ``rejected`` based on:

  * legal-move + valid-FEN reconstruction (objective rule oracle);
  * teacher agreement: exp4 PV ranker and/or exp5 NNUE ranker, depending
    on the audit profile and which model paths were given;
  * dedupe by (fen, side, move_uci) within the run.

Only ``accepted`` rows are stamped with
``trusted_source='imported_dataset_teacher_audited'`` (which the W8
seed_train whitelist accepts at cap 200) plus
``label_quality='clean'`` and ``training_eligible=True``. Raw / review /
rejected rows never get the audited trusted_source, so an accidental
inclusion of the wrong JSONL into ``seed_train --include-replay-jsonl``
fails at the validator gate.

Diagnostic-only. Never writes any model, never opens a non-dry-run
training step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import chess

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.games.chess_pv import rank_experiment_pv_policy_moves  # noqa: E402
from services.games.chess_nnue import rank_experiment_nnue_policy_moves  # noqa: E402
from services.games.external_replay_safety import serialize_json_payload  # noqa: E402


AUDIT_PROFILES = ("strict", "very_strict", "diagnostic")
AUDITED_TRUSTED_SOURCE = "imported_dataset_teacher_audited"
ACCEPTED_WEIGHT_CAP = 0.5
DEFAULT_TOP_K = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_dirname() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _rank_top_k(
    ranker: Callable[..., list[dict]] | None,
    *,
    fen: str,
    side: str,
    model_path: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[str] | None:
    """Run a ranker helper and return top-K UCIs, or None if not configured."""
    if ranker is None or not model_path:
        return None
    try:
        rows = ranker({"__fen__": fen}, side, model_path=model_path)
    except Exception:
        return None
    out: list[str] = []
    for row in rows or []:
        move = str((row or {}).get("move") or "").strip().lower()
        if move:
            out.append(move)
        if len(out) >= top_k:
            break
    return out


def classify_row(
    row: dict,
    *,
    exp4_top: list[str] | None,
    exp5_top: list[str] | None,
    profile: str = "strict",
) -> tuple[str, list[str], dict]:
    """Return ``(status, reasons, teacher_detail)`` for one replay row.

    ``status`` ∈ {accepted, review, rejected}. ``reasons`` lists the
    contributing rules (objective rule oracle codes only — never
    'ground_truth'). ``teacher_detail`` records both rankers' top-3 and
    candidate-in-top-3 booleans for downstream review.
    """
    reasons: list[str] = []
    teacher_detail = {
        "exp4": {"supported": False, "top_k": [], "candidate_in_top_k": False},
        "exp5": {"supported": False, "top_k": [], "candidate_in_top_k": False},
    }

    fen = str(row.get("fen") or "").strip()
    move_uci = str(row.get("move_uci") or "").strip().lower()
    side = str(row.get("side") or "").strip().lower()
    if not fen or not move_uci or not side:
        return "rejected", ["missing_required_field"], teacher_detail
    try:
        board = chess.Board(fen)
    except Exception:
        return "rejected", ["invalid_fen"], teacher_detail
    # Move.from_uci only parses; board.legal_moves does the legality check.
    # Splitting them lets us distinguish 'invalid_uci' (garbage string) from
    # 'illegal_move' (well-formed UCI that doesn't fit the position).
    try:
        mv = chess.Move.from_uci(move_uci)
    except Exception:
        return "rejected", ["invalid_uci"], teacher_detail
    if mv not in board.legal_moves:
        return "rejected", ["illegal_move"], teacher_detail

    in_exp4 = False
    if exp4_top is not None:
        teacher_detail["exp4"]["supported"] = True
        teacher_detail["exp4"]["top_k"] = list(exp4_top)
        in_exp4 = move_uci in exp4_top
        teacher_detail["exp4"]["candidate_in_top_k"] = in_exp4
    in_exp5 = False
    if exp5_top is not None:
        teacher_detail["exp5"]["supported"] = True
        teacher_detail["exp5"]["top_k"] = list(exp5_top)
        in_exp5 = move_uci in exp5_top
        teacher_detail["exp5"]["candidate_in_top_k"] = in_exp5

    profile = (profile or "strict").lower()
    if profile == "diagnostic":
        return "review", ["legal_move", "diagnostic_only_profile"], teacher_detail

    if exp4_top is None and exp5_top is None:
        return "review", ["legal_move", "no_teacher_configured"], teacher_detail

    if profile == "very_strict":
        if in_exp4 and in_exp5:
            return (
                "accepted",
                ["legal_move", "teacher_top_k_agreement_both_engines"],
                teacher_detail,
            )
        if in_exp4 or in_exp5:
            return (
                "review",
                ["legal_move", "teacher_top_k_partial_agreement_only"],
                teacher_detail,
            )
        return "rejected", ["legal_move", "teacher_top_k_disagreement_both"], teacher_detail

    # default: strict
    if in_exp4 or in_exp5:
        return (
            "accepted",
            ["legal_move", "teacher_top_k_agreement"],
            teacher_detail,
        )
    return "review", ["legal_move", "teacher_no_top_k_agreement"], teacher_detail


def stamp_accepted(row: dict, *, weight_cap: float = ACCEPTED_WEIGHT_CAP) -> dict:
    """Return a copy of ``row`` stamped with the audited trusted source.

    Caller is responsible for ensuring the row passed actually classified
    as 'accepted'. The function pins down trusted_source / label_quality /
    training_eligible / teacher_audit_status so downstream consumers cannot
    accidentally trust an unaudited row that happens to have the same
    ``fen / move_uci`` triple.
    """
    out = dict(row)
    out["trusted_source"] = AUDITED_TRUSTED_SOURCE
    out["source"] = AUDITED_TRUSTED_SOURCE
    out["label_quality"] = "clean"
    out["training_eligible"] = True
    out["teacher_audit_status"] = "passed"
    raw_weight = row.get("weight")
    try:
        weight = float(raw_weight) if raw_weight is not None else weight_cap
    except Exception:
        weight = weight_cap
    out["weight"] = min(max(weight, 0.0), float(weight_cap))
    return out


def _stamp_unaccepted(row: dict, *, status: str, reasons: list[str]) -> dict:
    out = dict(row)
    out["audit_status"] = status
    out["audit_reasons"] = list(reasons)
    out["training_eligible"] = False
    out["teacher_audit_status"] = "review" if status == "review" else "rejected"
    return out


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("fen") or "").strip(),
        str(row.get("side") or "").strip().lower(),
        str(row.get("move_uci") or "").strip().lower(),
    )


def _input_hash(paths: list[Path]) -> str:
    payload = json.dumps({"inputs": [str(p) for p in paths]}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_audit(
    *,
    input_jsonls: list[Path],
    output_dir: Path,
    exp4_model_path: str = "",
    exp5_model_path: str = "",
    profile: str = "strict",
    top_k: int = DEFAULT_TOP_K,
    weight_cap: float = ACCEPTED_WEIGHT_CAP,
) -> dict:
    """Audit every row across every input JSONL. Returns the summary dict."""
    if profile not in AUDIT_PROFILES:
        raise SystemExit(
            f"error: --audit-profile must be one of {AUDIT_PROFILES}; got {profile!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = output_dir / "accepted_replay.jsonl"
    review_path = output_dir / "review_replay.jsonl"
    rejected_path = output_dir / "rejected_replay.jsonl"
    detail_path = output_dir / "audit_detail.jsonl"
    summary_path = output_dir / "summary.json"

    counts: dict = {
        "input_rows": 0,
        "accepted_rows": 0,
        "review_rows": 0,
        "rejected_rows": 0,
        "duplicates_dropped": 0,
        "missing_files": 0,
        "by_reason_rejected": {},
        "by_reason_review": {},
    }
    seen_keys: set[tuple[str, str, str]] = set()

    paths_used: list[Path] = []
    with (
        accepted_path.open("w", encoding="utf-8") as fh_a,
        review_path.open("w", encoding="utf-8") as fh_r,
        rejected_path.open("w", encoding="utf-8") as fh_x,
        detail_path.open("w", encoding="utf-8") as fh_d,
    ):
        for raw_path in input_jsonls:
            path = Path(raw_path).expanduser().resolve()
            if not path.exists():
                counts["missing_files"] += 1
                continue
            paths_used.append(path)
            for row in _read_jsonl(path):
                counts["input_rows"] += 1
                key = _row_key(row)
                if key in seen_keys:
                    counts["duplicates_dropped"] += 1
                    rejected = _stamp_unaccepted(row, status="rejected", reasons=["duplicate_fen_side_move"])
                    fh_x.write(json.dumps(rejected, sort_keys=True) + "\n")
                    fh_d.write(
                        json.dumps(
                            {
                                "source_id": row.get("source_id"),
                                "audit_status": "rejected",
                                "audit_reasons": ["duplicate_fen_side_move"],
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    counts["rejected_rows"] += 1
                    counts["by_reason_rejected"]["duplicate_fen_side_move"] = (
                        counts["by_reason_rejected"].get("duplicate_fen_side_move", 0) + 1
                    )
                    continue
                seen_keys.add(key)

                fen = str(row.get("fen") or "")
                side = str(row.get("side") or "white")
                exp4_top = _rank_top_k(
                    rank_experiment_pv_policy_moves,
                    fen=fen,
                    side=side,
                    model_path=exp4_model_path,
                    top_k=top_k,
                )
                exp5_top = _rank_top_k(
                    rank_experiment_nnue_policy_moves,
                    fen=fen,
                    side=side,
                    model_path=exp5_model_path,
                    top_k=top_k,
                )
                status, reasons, teacher = classify_row(
                    row, exp4_top=exp4_top, exp5_top=exp5_top, profile=profile
                )

                detail = {
                    "source_id": row.get("source_id"),
                    "fen": fen,
                    "side": side,
                    "move_uci": row.get("move_uci"),
                    "winner_color": row.get("winner_color"),
                    "audit_status": status,
                    "audit_reasons": reasons,
                    "teacher": teacher,
                }
                fh_d.write(json.dumps(detail, sort_keys=True) + "\n")

                if status == "accepted":
                    counts["accepted_rows"] += 1
                    fh_a.write(
                        json.dumps(
                            stamp_accepted(row, weight_cap=weight_cap),
                            sort_keys=True,
                        )
                        + "\n"
                    )
                elif status == "review":
                    counts["review_rows"] += 1
                    fh_r.write(
                        json.dumps(_stamp_unaccepted(row, status="review", reasons=reasons), sort_keys=True)
                        + "\n"
                    )
                    for r in reasons:
                        counts["by_reason_review"][r] = counts["by_reason_review"].get(r, 0) + 1
                else:
                    counts["rejected_rows"] += 1
                    fh_x.write(
                        json.dumps(_stamp_unaccepted(row, status="rejected", reasons=reasons), sort_keys=True)
                        + "\n"
                    )
                    for r in reasons:
                        counts["by_reason_rejected"][r] = counts["by_reason_rejected"].get(r, 0) + 1

    summary = {
        "stage": "pgn_teacher_audit",
        "timestamp": _now_iso(),
        "output_dir": str(output_dir),
        "input_jsonls": [str(p) for p in paths_used],
        "input_hash": _input_hash(paths_used),
        "audit_profile": profile,
        "top_k": top_k,
        "weight_cap": weight_cap,
        "exp4_model_path": exp4_model_path,
        "exp5_model_path": exp5_model_path,
        "exp4_teacher_used": bool(exp4_model_path),
        "exp5_teacher_used": bool(exp5_model_path),
        "counts": counts,
        "accepted_jsonl": str(accepted_path),
        "review_jsonl": str(review_path),
        "rejected_jsonl": str(rejected_path),
        "audit_detail_jsonl": str(detail_path),
        "policy": {
            "diagnostic_only": True,
            "production_runtime_mutation": False,
            "raw_internet_download": False,
            "audited_trusted_source": AUDITED_TRUSTED_SOURCE,
        },
    }
    summary_path.write_text(serialize_json_payload(summary), encoding="utf-8")

    md_lines = [
        "# Imported replay teacher audit (W8 commit 1, diagnostic only)",
        "",
        f"- timestamp: {summary['timestamp']}",
        f"- output_dir: {output_dir}",
        f"- audit_profile: {profile}",
        f"- top_k: {top_k}",
        f"- weight_cap: {weight_cap}",
        f"- exp4_teacher_used: {summary['exp4_teacher_used']}",
        f"- exp5_teacher_used: {summary['exp5_teacher_used']}",
        "",
        "## Counts",
        f"- input_rows: {counts['input_rows']}",
        f"- accepted_rows: {counts['accepted_rows']}",
        f"- review_rows: {counts['review_rows']}",
        f"- rejected_rows: {counts['rejected_rows']}",
        f"- duplicates_dropped: {counts['duplicates_dropped']}",
        f"- missing_files: {counts['missing_files']}",
        "",
        "## Policy (hard-coded)",
        "- diagnostic_only = True",
        "- production_runtime_mutation = False",
        "- raw_internet_download = False",
        f"- audited_trusted_source = {AUDITED_TRUSTED_SOURCE}",
        "",
        "Feed `accepted_replay.jsonl` to `chess_seed_train.py` via",
        "`--include-replay-jsonl`. Raw imported_dataset rows that did NOT",
        "pass this audit must not be fed to seed_train; the orchestrator",
        "swaps include_jsonls accordingly.",
    ]
    (output_dir / "SUMMARY.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Teacher-audit imported replay JSONL. Accepted rows are stamped "
            "trusted_source='imported_dataset_teacher_audited'; review and "
            "rejected rows are never training_eligible."
        )
    )
    p.add_argument(
        "--input-jsonl",
        action="append",
        default=[],
        help="Input replay JSONL (canonical per-ply). Repeatable.",
    )
    p.add_argument("--output-dir", required=True)
    p.add_argument(
        "--exp4-model-path",
        default="",
        help="Optional exp4 PV model path for top-k teacher signal.",
    )
    p.add_argument(
        "--exp5-model-path",
        default="",
        help="Optional exp5 NNUE model path for top-k teacher signal.",
    )
    p.add_argument(
        "--audit-profile",
        default="strict",
        choices=list(AUDIT_PROFILES),
        help="strict: top-K of either engine; very_strict: top-K of both; diagnostic: classify only.",
    )
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--weight-cap", type=float, default=ACCEPTED_WEIGHT_CAP)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    inputs = [Path(p) for p in args.input_jsonl]
    if not inputs:
        raise SystemExit("error: at least one --input-jsonl is required")
    output_dir = Path(args.output_dir).expanduser().resolve()
    summary = run_audit(
        input_jsonls=inputs,
        output_dir=output_dir,
        exp4_model_path=str(args.exp4_model_path or ""),
        exp5_model_path=str(args.exp5_model_path or ""),
        profile=str(args.audit_profile or "strict"),
        top_k=int(args.top_k or DEFAULT_TOP_K),
        weight_cap=float(args.weight_cap or ACCEPTED_WEIGHT_CAP),
    )
    counts = summary["counts"]
    print("=== chess_imported_replay_teacher_audit (W8 commit 1) ===")
    print(f"output_dir   : {summary['output_dir']}")
    print(f"profile      : {summary['audit_profile']}  top_k={summary['top_k']}")
    print(f"input_rows   : {counts['input_rows']}")
    print(f"accepted     : {counts['accepted_rows']}")
    print(f"review       : {counts['review_rows']}")
    print(f"rejected     : {counts['rejected_rows']}")
    print(f"duplicates   : {counts['duplicates_dropped']}")
    print(f"accepted JSONL: {summary['accepted_jsonl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
