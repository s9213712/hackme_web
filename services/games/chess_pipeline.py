"""Status and path helpers for the offline chess training pipeline."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from services.games.chess_arena import default_chess_reports_dir
from services.games.chess_promotion import default_chess_candidate_dir
from services.games.chess_replay_buffer import replay_buffer_summary
from services.server.runtime import default_runtime_root_path


DEFAULT_RETRAIN_MIN_USABLE_REPLAYS = 25
DEFAULT_RETRAIN_MAX_AGE_HOURS = 24 * 7


def _runtime_root() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip() or str(default_runtime_root_path())
    return Path(runtime_dir)


def retrain_min_usable_replays() -> int:
    raw = str(os.environ.get("HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS", "")).strip()
    try:
        value = int(raw)
    except Exception:
        value = DEFAULT_RETRAIN_MIN_USABLE_REPLAYS
    return max(1, value)


def retrain_max_age_hours() -> int:
    raw = str(os.environ.get("HTML_LEARNING_CHESS_RETRAIN_MAX_AGE_HOURS", "")).strip()
    try:
        value = int(raw)
    except Exception:
        value = DEFAULT_RETRAIN_MAX_AGE_HOURS
    return max(1, value)


def default_chess_pipeline_dataset_root() -> Path:
    return default_chess_reports_dir() / "chess_datasets"


def default_chess_pipeline_candidate_root() -> Path:
    return default_chess_candidate_dir() / "runs"


def build_pipeline_run_id(prefix: str = "pipeline") -> str:
    return f"{prefix}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"


def candidate_paths_for_run(run_id: str, *, include_exp2: bool = False) -> dict[str, Path]:
    root = default_chess_pipeline_candidate_root() / str(run_id)
    paths = {
        "experiment": _runtime_root() / "database" / "chess_experiment.db",
        "experiment 3:dl": root / "chess_experiment_3_dl.json",
        "experiment 3:dl replay": root / "chess_experiment_3_dl_replay.jsonl",
        "experiment 4:pv": root / "chess_experiment_4_pv.json",
    }
    if include_exp2:
        paths["experiment 2:nn"] = root / "chess_experiment_2_nn.json"
    return paths


def dataset_paths_for_run(run_id: str) -> dict[str, Path]:
    root = default_chess_pipeline_dataset_root() / str(run_id)
    return {
        "root": root,
        "train": root / "train.jsonl",
        "eval": root / "eval.jsonl",
    }


def _load_json(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_pipeline_report(*, report_dir: Path | None = None) -> dict:
    root = Path(report_dir or default_chess_reports_dir())
    candidates = sorted(root.glob("chess_train_pipeline_*.json"))
    path = candidates[-1] if candidates else None
    payload = _load_json(path)
    return {
        "path": str(path) if path else "",
        "exists": bool(path and path.exists()),
        "summary": payload or {},
    }


def _parse_iso_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _latest_train_timestamp(*, pipeline_report: dict | None = None, seed_report: dict | None = None) -> datetime | None:
    for report in (pipeline_report or {}, seed_report or {}):
        summary = report.get("summary") if isinstance(report, dict) else {}
        if not isinstance(summary, dict):
            continue
        for key in ("finished_at", "generated_at", "timestamp"):
            parsed = _parse_iso_utc(summary.get(key))
            if parsed is not None:
                return parsed
    return None


def pipeline_recommendation(*, replay: dict | None = None, pipeline_report: dict | None = None, seed_report: dict | None = None) -> dict:
    replay = replay if isinstance(replay, dict) else replay_buffer_summary()
    pipeline_report = pipeline_report if isinstance(pipeline_report, dict) else latest_pipeline_report()
    thresholds = {
        "min_usable_replays": retrain_min_usable_replays(),
        "max_age_hours": retrain_max_age_hours(),
    }
    usable_replays = int(replay.get("usable_replays") or 0)
    ready_reasons: list[str] = []
    blocked_reasons: list[str] = []
    if usable_replays < thresholds["min_usable_replays"]:
        blocked_reasons.append(
            f"usable_replays {usable_replays} < min_usable_replays {thresholds['min_usable_replays']}"
        )
    last_train_at = _latest_train_timestamp(pipeline_report=pipeline_report, seed_report=seed_report)
    replay_last = _parse_iso_utc(replay.get("last_timestamp") or "")
    if last_train_at is None and usable_replays > 0:
        ready_reasons.append("no prior pipeline run")
    elif last_train_at is not None:
        age_hours = (datetime.utcnow() - last_train_at) / timedelta(hours=1)
        if age_hours >= thresholds["max_age_hours"]:
            ready_reasons.append(f"last training older than {thresholds['max_age_hours']}h")
        if replay_last is not None and replay_last > last_train_at:
            ready_reasons.append("new replay data arrived after last training")
    else:
        age_hours = None
    if usable_replays == 0:
        blocked_reasons.append("no usable replays yet")
    if not ready_reasons and not blocked_reasons and usable_replays >= thresholds["min_usable_replays"]:
        ready_reasons.append("replay threshold reached")
    command = (
        "python3 scripts/games/chess_train_pipeline.py "
        f"--preset standard --include-quarantine --min-usable-replays {thresholds['min_usable_replays']}"
    )
    return {
        "ready": bool(ready_reasons) and not blocked_reasons,
        "ready_reasons": ready_reasons,
        "blocked_reasons": blocked_reasons,
        "thresholds": thresholds,
        "usable_replays": usable_replays,
        "last_train_at": last_train_at.isoformat() + "Z" if last_train_at else "",
        "recommended_command": command,
    }

