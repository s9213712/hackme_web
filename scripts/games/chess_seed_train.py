#!/usr/bin/env python3
"""Offline seed trainer for directly usable chess experiment models.

This script is the pragmatic answer to the current engine state:

- exp3 / exp4 are weak when cold-started
- startup-time warm-up is too slow for production use

So this tool trains seed artifacts offline under ``runtime/`` (or explicit
paths), then prints a compact JSON summary with model paths you can install
directly.
"""

from __future__ import annotations

import argparse
import json
import random
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_dl import bundled_chess_dl_model_path  # noqa: E402
from services.games.chess_engine import bundled_chess_engine_db_path  # noqa: E402
from services.games.chess_nn import bundled_chess_nn_model_path  # noqa: E402
from services.games.chess_nnue import (  # noqa: E402
    bundled_chess_nnue_model_path,
    default_chess_nnue_model_path,
)
from services.games.chess_pv import (  # noqa: E402
    bundled_chess_pv_model_path,
    default_chess_pv_model_path,
)
from services.games.self_play_training import (  # noqa: E402
    DEFAULT_MAX_PLIES,
    DEFAULT_STUDENT_EXPLORATION_RATE,
    DEFAULT_TEACHER_DEPTH,
    ChessExperimentStore,
    default_training_report_dir,
    run_post_training_smoke_evaluation,
    run_round_robin_benchmark,
    run_training_session,
    write_training_report,
)
import services.games.chess_dl as chess_dl_service  # noqa: E402
import services.games.chess_pv as chess_pv_service  # noqa: E402
from services.games.chess_pv import (  # noqa: E402
    normalize_experiment_pv_replay_sample,
    train_experiment_pv_from_replay_samples,
)
from services.games.chess_nnue import (  # noqa: E402
    normalize_experiment_nnue_replay_sample,
    train_experiment_nnue_from_replay_samples,
)


# v1 external replay policy (see [[feedback-pvp-replay-discipline]]). Absolute
# per-source caps; v2 should switch to fraction-of-self-play once
# run_training_session exposes a sample count. Trusted-source whitelist
# rejects rows whose trusted_source is not in this set.
TRUSTED_SOURCE_WHITELIST = frozenset(
    {
        "imported_dataset",
        "teacher_guidance",
        "benchmark",
        "external",
        "pvp_filtered",
        "human_beat_engine",
        "sparring_objective_hit",
    }
)

DEFAULT_EXTERNAL_CAPS = {
    "imported_dataset": 200,
    "teacher_guidance": 200,
    "benchmark": 100,
    "external": 100,
    "pvp_filtered": 100,
    "human_beat_engine": 100,
    "sparring_objective_hit": 50,
}
DEFAULT_EXTERNAL_TOTAL_CAP = 300


PRESETS = {
    "micro": {
        "exp2_teacher_games": 0,
        "exp3_teacher_games": 1,
        "exp4_teacher_games": 1,
        "hard_exp2_games": 0,
        "hard_exp3_games": 1,
        "hard_exp4_games": 1,
        "cross_games": 0,
        "cross_exp1_exp3_games": 0,
        "cross_exp2_exp3_games": 0,
        "cross_exp1_exp4_games": 0,
        "cross_exp2_exp4_games": 0,
        "cross_exp3_exp4_games": 1,
        "teacher_depth": 1,
        "max_plies": 12,
        "student_exploration_rate": 0.12,
    },
    "quick": {
        "exp2_teacher_games": 4,
        "exp3_teacher_games": 6,
        "exp4_teacher_games": 6,
        "hard_exp2_games": 2,
        "hard_exp3_games": 4,
        "hard_exp4_games": 4,
        "cross_games": 0,
        "cross_exp1_exp3_games": 3,
        "cross_exp2_exp3_games": 2,
        "cross_exp1_exp4_games": 3,
        "cross_exp2_exp4_games": 2,
        "cross_exp3_exp4_games": 3,
        "teacher_depth": 1,
        "max_plies": 18,
        "student_exploration_rate": 0.1,
    },
    "standard": {
        "exp2_teacher_games": 8,
        "exp3_teacher_games": 16,
        "exp4_teacher_games": 16,
        "hard_exp2_games": 4,
        "hard_exp3_games": 10,
        "hard_exp4_games": 10,
        "cross_games": 0,
        "cross_exp1_exp3_games": 8,
        "cross_exp2_exp3_games": 6,
        "cross_exp1_exp4_games": 8,
        "cross_exp2_exp4_games": 6,
        "cross_exp3_exp4_games": 8,
        "teacher_depth": 2,
        "max_plies": 28,
        "student_exploration_rate": 0.08,
    },
    "warmup10": {
        "exp2_teacher_games": 12,
        "exp3_teacher_games": 24,
        "exp4_teacher_games": 24,
        "hard_exp2_games": 6,
        "hard_exp3_games": 12,
        "hard_exp4_games": 12,
        "cross_games": 0,
        "cross_exp1_exp3_games": 10,
        "cross_exp2_exp3_games": 8,
        "cross_exp1_exp4_games": 10,
        "cross_exp2_exp4_games": 8,
        "cross_exp3_exp4_games": 10,
        "teacher_depth": 2,
        "max_plies": 24,
        "student_exploration_rate": 0.05,
    },
    "strong": {
        "exp2_teacher_games": 16,
        "exp3_teacher_games": 32,
        "exp4_teacher_games": 32,
        "hard_exp2_games": 8,
        "hard_exp3_games": 20,
        "hard_exp4_games": 20,
        "cross_games": 0,
        "cross_exp1_exp3_games": 14,
        "cross_exp2_exp3_games": 10,
        "cross_exp1_exp4_games": 14,
        "cross_exp2_exp4_games": 10,
        "cross_exp3_exp4_games": 14,
        "teacher_depth": 2,
        "max_plies": 36,
        "student_exploration_rate": 0.06,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline seed trainer for directly usable chess exp2/exp3/exp4 models.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    parser.add_argument("--include-exp2", action="store_true", help="Also train exp2 during seed generation.")
    parser.add_argument("--skip-exp3", action="store_true", help="Skip exp3 training.")
    parser.add_argument("--skip-exp4", action="store_true", help="Skip exp4 training.")
    parser.add_argument(
        "--skip-exp5",
        action="store_true",
        help=(
            "Skip exp5 NNUE training during external replay step. "
            "run_training_session has no exp5 schedule today so this only "
            "gates the --include-replay-jsonl trainer for the NNUE side."
        ),
    )
    parser.add_argument("--teacher-depth", type=int, default=-1)
    parser.add_argument("--max-plies", type=int, default=-1)
    parser.add_argument("--student-exploration-rate", type=float, default=-1.0)
    parser.add_argument("--seed", type=int, default=20260508)
    parser.add_argument("--dl-search-depth", type=int, default=1)
    parser.add_argument("--dl-quiescence-depth", type=int, default=1)
    parser.add_argument("--pv-search-depth", type=int, default=1)
    parser.add_argument("--pv-quiescence-depth", type=int, default=1)
    parser.add_argument("--with-smoke", action="store_true")
    parser.add_argument("--with-benchmark", action="store_true")
    parser.add_argument("--smoke-games-per-pair", type=int, default=1)
    parser.add_argument("--benchmark-rounds", type=int, default=1)
    parser.add_argument("--report-dir", default=str(default_training_report_dir()))
    parser.add_argument("--experiment-db-path", default="")
    parser.add_argument("--experiment-2-model-path", default="")
    parser.add_argument("--experiment-3-model-path", default="")
    parser.add_argument("--experiment-4-model-path", default="")
    parser.add_argument("--experiment-5-model-path", default="")
    parser.add_argument(
        "--include-replay-jsonl",
        action="append",
        default=[],
        help=(
            "External replay JSONL path (repeatable). Rows must carry trusted_source "
            "in the whitelist (pvp_filtered / human_beat_engine / imported_dataset / "
            "teacher_guidance / benchmark / external / sparring_objective_hit). "
            "Per-source absolute caps apply; see chess_seed_train.DEFAULT_EXTERNAL_CAPS."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Skip ALL training: run_training_session, smoke, benchmark, "
            "write_training_report, and the external replay trainer. "
            "Still loads and validates --include-replay-jsonl rows so "
            "you can verify schema + normalize + caps before a real run."
        ),
    )
    parser.add_argument(
        "--allow-default-model-paths",
        action="store_true",
        help=(
            "Opt-in: allow non-dry-run --include-replay-jsonl to write to "
            "the default exp4 / exp5 model paths. Without this flag the "
            "script refuses to train external replay into the bundled / "
            "runtime defaults — you must pass --experiment-4-model-path "
            "(or --skip-exp4) and --experiment-5-model-path (or "
            "--skip-exp5) so external replay only lands in explicit "
            "staging / candidate artifacts."
        ),
    )
    return parser.parse_args()


def _is_default_model_path(
    explicit_path: str,
    *,
    bundled_resolver: Callable[[], Path],
    default_resolver: Callable[[], Path],
) -> tuple[bool, str]:
    """Return (is_default, reason).

    Treats an explicit `--experiment-X-model-path` as "default" if it resolves
    to the bundled artifact, the runtime default artifact, or any file under
    `services/games/models/`. Blocks the W4.1d escape "user explicitly typed
    the bundled path so the guard let it through".
    """
    if not explicit_path:
        return False, ""
    try:
        explicit = Path(explicit_path).expanduser().resolve()
    except Exception:
        return False, ""
    try:
        bundled = bundled_resolver().resolve()
    except Exception:
        bundled = None
    try:
        runtime_default = default_resolver().resolve()
    except Exception:
        runtime_default = None
    if bundled is not None and explicit == bundled:
        return True, f"resolves to bundled path {bundled}"
    if runtime_default is not None and explicit == runtime_default:
        return True, f"resolves to runtime default {runtime_default}"
    bundled_models_dir = (ROOT / "services" / "games" / "models").resolve()
    try:
        explicit.relative_to(bundled_models_dir)
    except ValueError:
        return False, ""
    return True, f"resides under bundled-models dir {bundled_models_dir}"


def _assert_external_replay_safety(args: argparse.Namespace) -> None:
    """Block non-dry-run external replay from silently writing default models.

    Self-play warm-up (no --include-replay-jsonl) keeps its pre-existing
    behaviour of writing to bundled paths; this guard only fires for the
    new external-replay code path. Pass --allow-default-model-paths to
    override (useful for one-off recovery runs, not the default flow).
    """
    if not args.include_replay_jsonl:
        return
    if args.dry_run:
        return
    if args.allow_default_model_paths:
        return
    problems: list[str] = []
    if not args.skip_exp4:
        if not args.experiment_4_model_path:
            problems.append(
                "exp4 PV: pass --experiment-4-model-path <staging/candidate.json> "
                "or --skip-exp4 to gate exp4 out of this run."
            )
        else:
            is_default, reason = _is_default_model_path(
                args.experiment_4_model_path,
                bundled_resolver=bundled_chess_pv_model_path,
                default_resolver=default_chess_pv_model_path,
            )
            if is_default:
                problems.append(f"exp4 PV: --experiment-4-model-path {reason}")
    if not args.skip_exp5:
        if not args.experiment_5_model_path:
            problems.append(
                "exp5 NNUE: pass --experiment-5-model-path <staging/candidate.json> "
                "or --skip-exp5 to gate exp5 out of this run."
            )
        else:
            is_default, reason = _is_default_model_path(
                args.experiment_5_model_path,
                bundled_resolver=bundled_chess_nnue_model_path,
                default_resolver=default_chess_nnue_model_path,
            )
            if is_default:
                problems.append(f"exp5 NNUE: --experiment-5-model-path {reason}")
    if not problems:
        return
    msg_lines = [
        "error: refusing to train --include-replay-jsonl into default model paths.",
        "Real (non-dry-run) external-replay warm-up must target explicit "
        "candidate / staging artifacts, not bundled or runtime defaults:",
    ]
    msg_lines.extend(f"  - {p}" for p in problems)
    msg_lines.append(
        "Pass --allow-default-model-paths if you really intend to write defaults."
    )
    raise SystemExit("\n".join(msg_lines))


def _load_external_replay(paths: list[str]) -> tuple[list[dict], dict]:
    """Load + validate external replay JSONL rows.

    Returns (samples, stats). Rejected reasons:
      - invalid_json (per line)
      - invalid_trusted_source (not in whitelist)
      - missing_required_fields (fen / move_uci / side)
    """
    samples: list[dict] = []
    stats: dict = {
        "files_read": 0,
        "files_missing": [],
        "rows_total": 0,
        "rows_kept": 0,
        "rejected_invalid_json": 0,
        "rejected_invalid_trusted_source": 0,
        "rejected_missing_fields": 0,
        "source_breakdown_raw": {},
    }
    for raw_path in paths or []:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            stats["files_missing"].append(str(path))
            continue
        stats["files_read"] += 1
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                stats["rows_total"] += 1
                try:
                    row = json.loads(line)
                except Exception:
                    stats["rejected_invalid_json"] += 1
                    continue
                trusted = str(row.get("trusted_source") or "")
                if trusted not in TRUSTED_SOURCE_WHITELIST:
                    stats["rejected_invalid_trusted_source"] += 1
                    continue
                if not row.get("fen") or not row.get("move_uci") or not row.get("side"):
                    stats["rejected_missing_fields"] += 1
                    continue
                samples.append(row)
                stats["source_breakdown_raw"][trusted] = (
                    stats["source_breakdown_raw"].get(trusted, 0) + 1
                )
    stats["rows_kept"] = len(samples)
    return samples, stats


def _apply_external_caps(
    samples: list[dict],
    *,
    caps: dict[str, int] | None = None,
    total_cap: int = DEFAULT_EXTERNAL_TOTAL_CAP,
    seed: int = 0,
) -> tuple[list[dict], dict]:
    """Group by trusted_source, downsample to per-source cap, then enforce total."""
    caps = dict(caps if caps is not None else DEFAULT_EXTERNAL_CAPS)
    rng = random.Random(seed)
    by_source: dict[str, list[dict]] = {}
    for s in samples:
        by_source.setdefault(str(s.get("trusted_source") or ""), []).append(s)
    per_source: dict[str, dict] = {}
    capped: list[dict] = []
    for source in sorted(by_source):
        items = list(by_source[source])
        cap = int(caps.get(source, 100))
        if len(items) > cap:
            rng.shuffle(items)
            kept = items[:cap]
        else:
            kept = items
        per_source[source] = {
            "raw": len(by_source[source]),
            "cap": cap,
            "kept_after_per_source_cap": len(kept),
        }
        capped.extend(kept)
    pre_total = len(capped)
    if pre_total > total_cap:
        rng.shuffle(capped)
        capped = capped[:total_cap]
    final = {}
    for s in capped:
        ts = str(s.get("trusted_source") or "")
        final[ts] = final.get(ts, 0) + 1
    return capped, {
        "per_source": per_source,
        "after_total_cap": final,
        "total_cap": int(total_cap),
        "pre_total_cap_count": pre_total,
        "total_kept": len(capped),
    }


def _dryrun_artifact_path(report_dir: Path) -> Path:
    """Compute the timestamped dry-run artifact path without writing it yet.

    Split from the writer so callers can inject the planned path into
    `payload['dry_run_artifact']` BEFORE serialisation, ensuring the on-disk
    JSON and the stdout JSON are byte-identical.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return report_dir / f"chess_seed_train_dryrun_{ts}.json"


def _write_dryrun_payload_artifact(payload: dict, artifact_path: Path) -> Path:
    """Persist the final payload to disk when dry-run skips write_training_report.

    Dry-run is supposed to give the operator a tangible inspection target for
    load_stats / cap_stats / normalize_validation / train_result.skipped_reason
    — stdout alone is too easy to lose. Caller is expected to set
    `payload['dry_run_artifact']` to `artifact_path` before invocation so the
    saved file self-references its own location.
    """
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return artifact_path


def _validate_normalize(samples: list[dict]) -> dict:
    """Run each capped sample through the exp4 PV + exp5 NNUE normalizers.

    A pure-validation step (no model write, no replay buffer write) that
    proves a sample is acceptable to both trainers before the first real
    training run. Records up to 5 failing source_ids per engine to make
    debugging schema problems easy without dumping the entire JSONL.
    """
    stats: dict = {
        "exp4_ok": 0,
        "exp4_failed": 0,
        "exp5_ok": 0,
        "exp5_failed": 0,
        "exp4_failed_samples": [],
        "exp5_failed_samples": [],
    }
    for s in samples:
        sid = str(s.get("source_id") or "")
        try:
            n4 = normalize_experiment_pv_replay_sample(s)
        except Exception as exc:
            n4 = None
            sid_label = f"{sid}:{exc!r}" if sid else repr(exc)
            if len(stats["exp4_failed_samples"]) < 5:
                stats["exp4_failed_samples"].append(sid_label)
        if n4 is not None:
            stats["exp4_ok"] += 1
        else:
            stats["exp4_failed"] += 1
            if sid and len(stats["exp4_failed_samples"]) < 5 and sid not in stats["exp4_failed_samples"]:
                stats["exp4_failed_samples"].append(sid)
        try:
            n5 = normalize_experiment_nnue_replay_sample(s)
        except Exception as exc:
            n5 = None
            sid_label = f"{sid}:{exc!r}" if sid else repr(exc)
            if len(stats["exp5_failed_samples"]) < 5:
                stats["exp5_failed_samples"].append(sid_label)
        if n5 is not None:
            stats["exp5_ok"] += 1
        else:
            stats["exp5_failed"] += 1
            if sid and len(stats["exp5_failed_samples"]) < 5 and sid not in stats["exp5_failed_samples"]:
                stats["exp5_failed_samples"].append(sid)
    return stats


def _train_with_external_replay(
    samples: list[dict],
    *,
    pv_model_path: Path,
    nnue_model_path: Path,
    dry_run: bool,
    skip_exp4: bool,
    skip_exp5: bool = False,
) -> dict:
    """Train exp4 PV and exp5 NNUE with external replay samples.

    No-ops on empty sample list or dry_run.
    """
    result: dict = {"trained_exp4": False, "trained_exp5": False, "sample_count": len(samples)}
    if not samples:
        result["skipped_reason"] = "no_samples"
        return result
    if dry_run:
        result["skipped_reason"] = "dry_run"
        return result
    if not skip_exp4:
        result["exp4_train_report"] = train_experiment_pv_from_replay_samples(
            samples, model_path=pv_model_path
        )
        result["trained_exp4"] = True
    if not skip_exp5:
        result["exp5_train_report"] = train_experiment_nnue_from_replay_samples(
            samples, model_path=nnue_model_path
        )
        result["trained_exp5"] = True
    return result


def _model_stats(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "sample_count": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "sample_count": int(payload.get("sample_count") or 0),
        "architecture": str(payload.get("architecture") or ""),
        "version": int(payload.get("version") or 0),
    }


@contextmanager
def _temporary_search_depths(args: argparse.Namespace):
    old_dl_depth = chess_dl_service._SEARCH_DEPTH
    old_dl_qdepth = chess_dl_service._SEARCH_QUIESCENCE_DEPTH
    old_pv_depth = chess_pv_service._SEARCH_DEPTH
    old_pv_qdepth = chess_pv_service._SEARCH_QUIESCENCE_DEPTH
    chess_dl_service._SEARCH_DEPTH = max(1, int(args.dl_search_depth or 1))
    chess_dl_service._SEARCH_QUIESCENCE_DEPTH = max(0, int(args.dl_quiescence_depth or 0))
    chess_pv_service._SEARCH_DEPTH = max(1, int(args.pv_search_depth or 1))
    chess_pv_service._SEARCH_QUIESCENCE_DEPTH = max(0, int(args.pv_quiescence_depth or 0))
    try:
        yield
    finally:
        chess_dl_service._SEARCH_DEPTH = old_dl_depth
        chess_dl_service._SEARCH_QUIESCENCE_DEPTH = old_dl_qdepth
        chess_pv_service._SEARCH_DEPTH = old_pv_depth
        chess_pv_service._SEARCH_QUIESCENCE_DEPTH = old_pv_qdepth


def _resolved_schedule(args: argparse.Namespace) -> dict:
    schedule = dict(PRESETS[args.preset])
    if int(args.teacher_depth) > 0:
        schedule["teacher_depth"] = int(args.teacher_depth)
    if int(args.max_plies) > 0:
        schedule["max_plies"] = int(args.max_plies)
    if float(args.student_exploration_rate) >= 0:
        schedule["student_exploration_rate"] = float(args.student_exploration_rate)
    if not args.include_exp2:
        schedule["exp2_teacher_games"] = 0
        schedule["hard_exp2_games"] = 0
        schedule["cross_exp2_exp3_games"] = 0
        schedule["cross_exp2_exp4_games"] = 0
    if args.skip_exp3:
        schedule["exp3_teacher_games"] = 0
        schedule["hard_exp3_games"] = 0
        schedule["cross_exp1_exp3_games"] = 0
        schedule["cross_exp2_exp3_games"] = 0
        schedule["cross_exp3_exp4_games"] = 0
    if args.skip_exp4:
        schedule["exp4_teacher_games"] = 0
        schedule["hard_exp4_games"] = 0
        schedule["cross_exp1_exp4_games"] = 0
        schedule["cross_exp2_exp4_games"] = 0
        schedule["cross_exp3_exp4_games"] = 0
    return schedule


def _progress_log(event: dict) -> None:
    phase = str(event.get("phase") or "")
    if phase == "training_started":
        sys.stderr.write(f"[chess-seed-train] training 0/{event.get('total', 0)}\n")
    elif phase == "training_match_completed":
        sys.stderr.write(
            "[chess-seed-train] "
            f"{event.get('completed', 0)}/{event.get('total', 0)} "
            f"{event.get('white_engine')} vs {event.get('black_engine')} "
            f"winner={event.get('winner_color') or 'draw'} "
            f"plies={event.get('plies', 0)} reason={event.get('reason')}\n"
        )
    elif phase == "training_finished":
        sys.stderr.write(
            f"[chess-seed-train] training finished {event.get('completed', 0)}/{event.get('total', 0)} "
            f"games={event.get('games_played', 0)}\n"
        )
    sys.stderr.flush()


def _progress(message: str) -> None:
    sys.stderr.write(f"[chess-seed-train] {message}\n")
    sys.stderr.flush()


def main() -> int:
    args = parse_args()
    _assert_external_replay_safety(args)
    schedule = _resolved_schedule(args)
    store = ChessExperimentStore(args.experiment_db_path or bundled_chess_engine_db_path())
    nn_model_path = Path(args.experiment_2_model_path or bundled_chess_nn_model_path())
    dl_model_path = Path(args.experiment_3_model_path or bundled_chess_dl_model_path())
    pv_model_path = Path(args.experiment_4_model_path or bundled_chess_pv_model_path())
    nnue_model_path = Path(args.experiment_5_model_path or bundled_chess_nnue_model_path())
    _progress(f"preset: {args.preset} seed={int(args.seed)}")
    _progress(f"target exp1 db: {Path(args.experiment_db_path or bundled_chess_engine_db_path())}")
    _progress(f"target exp2 model: {nn_model_path}")
    _progress(f"target exp3 model: {dl_model_path}")
    _progress(f"target exp4 model: {pv_model_path}")
    _progress(f"target exp5 model: {nnue_model_path}")
    _progress(f"report dir: {Path(args.report_dir)}")
    if args.dry_run:
        _progress(
            "DRY RUN: skipping run_training_session, smoke, benchmark, "
            "write_training_report, and external-replay trainer"
        )
        summary: dict = {
            "dry_run_only": True,
            "games_played": 0,
            "teacher_depth": int(schedule.get("teacher_depth") or DEFAULT_TEACHER_DEPTH),
            "max_plies": int(schedule.get("max_plies") or DEFAULT_MAX_PLIES),
            "student_exploration_rate": float(
                schedule.get("student_exploration_rate") or DEFAULT_STUDENT_EXPLORATION_RATE
            ),
            "requested_games": {},
            "updates": {},
        }
        reports: dict = {}
    else:
        _progress("phase seed training started")
        with _temporary_search_depths(args):
            summary = run_training_session(
                exp1_teacher_games=0,
                exp2_teacher_games=int(schedule["exp2_teacher_games"]),
                exp3_teacher_games=int(schedule["exp3_teacher_games"]),
                exp4_teacher_games=int(schedule["exp4_teacher_games"]),
                hard_exp1_games=0,
                hard_exp2_games=int(schedule["hard_exp2_games"]),
                hard_exp3_games=int(schedule["hard_exp3_games"]),
                hard_exp4_games=int(schedule["hard_exp4_games"]),
                cross_games=int(schedule["cross_games"]),
                cross_exp1_exp3_games=int(schedule["cross_exp1_exp3_games"]),
                cross_exp2_exp3_games=int(schedule["cross_exp2_exp3_games"]),
                cross_exp1_exp4_games=int(schedule["cross_exp1_exp4_games"]),
                cross_exp2_exp4_games=int(schedule["cross_exp2_exp4_games"]),
                cross_exp3_exp4_games=int(schedule["cross_exp3_exp4_games"]),
                teacher_depth=int(schedule["teacher_depth"] or DEFAULT_TEACHER_DEPTH),
                max_plies=int(schedule["max_plies"] or DEFAULT_MAX_PLIES),
                student_exploration_rate=float(schedule["student_exploration_rate"] or DEFAULT_STUDENT_EXPLORATION_RATE),
                seed=int(args.seed),
                store=store,
                nn_model_path=nn_model_path,
                dl_model_path=dl_model_path,
                pv_model_path=pv_model_path,
                nnue_model_path=nnue_model_path,
                progress_hook=_progress_log,
            )
            if args.with_smoke:
                sys.stderr.write("[chess-seed-train] smoke evaluation started\n")
                sys.stderr.flush()
                summary["smoke_evaluation"] = run_post_training_smoke_evaluation(
                    store=store,
                    nn_model_path=nn_model_path,
                    dl_model_path=dl_model_path,
                    pv_model_path=pv_model_path,
                    nnue_model_path=nnue_model_path,
                    teacher_depth=int(schedule["teacher_depth"] or DEFAULT_TEACHER_DEPTH),
                    max_plies=int(schedule["max_plies"] or DEFAULT_MAX_PLIES),
                    games_per_pair=max(0, int(args.smoke_games_per_pair or 0)),
                    seed=int(args.seed) + 101,
                )
                sys.stderr.write("[chess-seed-train] smoke evaluation finished\n")
                sys.stderr.flush()
            if args.with_benchmark:
                sys.stderr.write("[chess-seed-train] benchmark started\n")
                sys.stderr.flush()
                summary["benchmark"] = run_round_robin_benchmark(
                    store=store,
                    nn_model_path=nn_model_path,
                    dl_model_path=dl_model_path,
                    pv_model_path=pv_model_path,
                    nnue_model_path=nnue_model_path,
                    teacher_depth=int(schedule["teacher_depth"] or DEFAULT_TEACHER_DEPTH),
                    max_plies=int(schedule["max_plies"] or DEFAULT_MAX_PLIES),
                    rounds=max(0, int(args.benchmark_rounds or 0)),
                    seed=int(args.seed) + 202,
                )
                sys.stderr.write("[chess-seed-train] benchmark finished\n")
                sys.stderr.flush()

        reports = write_training_report(summary, report_dir=Path(args.report_dir), basename="chess_seed_train")
        _progress(f"phase result report: json={reports.get('json_report')} md={reports.get('md_report')}")

    external_block: dict = {"enabled": False}
    if args.include_replay_jsonl:
        external_block["enabled"] = True
        external_block["paths"] = list(args.include_replay_jsonl)
        loaded_samples, load_stats = _load_external_replay(args.include_replay_jsonl)
        capped_samples, cap_stats = _apply_external_caps(
            loaded_samples, seed=int(args.seed)
        )
        external_block["load_stats"] = load_stats
        external_block["cap_stats"] = cap_stats
        external_block["normalize_validation"] = _validate_normalize(capped_samples)
        external_block["dry_run"] = bool(args.dry_run)
        external_block["skip_exp4"] = bool(args.skip_exp4)
        external_block["skip_exp5"] = bool(args.skip_exp5)
        train_result = _train_with_external_replay(
            capped_samples,
            pv_model_path=pv_model_path,
            nnue_model_path=nnue_model_path,
            dry_run=bool(args.dry_run),
            skip_exp4=bool(args.skip_exp4),
            skip_exp5=bool(args.skip_exp5),
        )
        external_block["train_result"] = train_result
        nv = external_block["normalize_validation"]
        _progress(
            "external replay: "
            f"files={load_stats['files_read']} "
            f"raw_rows={load_stats['rows_total']} "
            f"kept={load_stats['rows_kept']} "
            f"after_caps={cap_stats['total_kept']} "
            f"normalize_exp4={nv['exp4_ok']}/{nv['exp4_ok'] + nv['exp4_failed']} "
            f"normalize_exp5={nv['exp5_ok']}/{nv['exp5_ok'] + nv['exp5_failed']} "
            f"trained_exp4={train_result['trained_exp4']} "
            f"trained_exp5={train_result['trained_exp5']}"
        )
    payload = {
        "ok": True,
        "preset": args.preset,
        "seed": int(args.seed),
        "experiment_db_path": str(Path(args.experiment_db_path or bundled_chess_engine_db_path())),
        "games_played": int(summary.get("games_played") or 0),
        "teacher_depth": int(summary.get("teacher_depth") or 0),
        "max_plies": int(summary.get("max_plies") or 0),
        "student_exploration_rate": float(summary.get("student_exploration_rate") or 0.0),
        "schedule": summary.get("requested_games") or {},
        "updates": summary.get("updates") or {},
        "reports": reports,
        "models": {
            "exp2": _model_stats(nn_model_path),
            "exp3": _model_stats(dl_model_path),
            "exp4": _model_stats(pv_model_path),
            "exp5": _model_stats(nnue_model_path),
        },
        "with_smoke": bool(args.with_smoke),
        "with_benchmark": bool(args.with_benchmark),
        "external_replay": external_block,
        "dry_run": bool(args.dry_run),
        "search_depth_overrides": {
            "exp3_depth": max(1, int(args.dl_search_depth or 1)),
            "exp3_qdepth": max(0, int(args.dl_quiescence_depth or 0)),
            "exp4_depth": max(1, int(args.pv_search_depth or 1)),
            "exp4_qdepth": max(0, int(args.pv_quiescence_depth or 0)),
        },
    }
    if args.dry_run and args.include_replay_jsonl:
        artifact_path = _dryrun_artifact_path(Path(args.report_dir))
        payload["dry_run_artifact"] = str(artifact_path)
        _write_dryrun_payload_artifact(payload, artifact_path)
        _progress(f"dry-run JSON artifact written: {artifact_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    _progress("phase result seed training: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check model target paths, report dir permissions, and lower --preset for a smaller repro")
        raise
