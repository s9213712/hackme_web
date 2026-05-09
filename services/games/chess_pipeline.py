"""Status and path helpers for the offline chess training pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from services.games.chess_arena import default_chess_reports_dir
from services.games.chess_engine import default_chess_engine_db_path
from services.games.chess_promotion import default_chess_candidate_dir
from services.games.chess_replay_buffer import replay_buffer_summary
from services.server.runtime import default_runtime_root_path


DEFAULT_RETRAIN_MIN_USABLE_REPLAYS = 25
DEFAULT_RETRAIN_MAX_AGE_HOURS = 24 * 7
_PIPELINE_AUTORUN_LOCK = threading.Lock()


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
        "experiment": default_chess_engine_db_path(),
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


def default_chess_pipeline_autorun_status_path() -> Path:
    return default_chess_reports_dir() / "chess_pipeline_autorun_status.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _pid_running(pid: int) -> bool:
    if int(pid or 0) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def latest_pipeline_autorun_status(*, path: Path | None = None) -> dict:
    status_path = Path(path or default_chess_pipeline_autorun_status_path())
    payload = _load_json(status_path)
    if not isinstance(payload, dict):
        payload = {}
    pid = int(payload.get("pid") or 0)
    running = str(payload.get("status") or "").strip().lower() == "running" and _pid_running(pid)
    if str(payload.get("status") or "").strip().lower() == "running" and not running:
        payload["status"] = "stale"
    payload["pid"] = pid
    payload["is_running"] = running
    payload["path"] = str(status_path)
    payload["exists"] = status_path.exists()
    return payload


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
        "--preset standard --include-exp2 "
        "--promote-engines 'experiment 2:nn,experiment 3:dl,experiment 4:pv' "
        f"--min-usable-replays {thresholds['min_usable_replays']}"
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


def maybe_launch_chess_train_pipeline(
    *,
    replay: dict | None = None,
    trigger: str = "live_replay",
    actor_username: str | None = None,
) -> dict:
    replay = replay if isinstance(replay, dict) else replay_buffer_summary()
    recommendation = pipeline_recommendation(replay=replay)
    status_path = default_chess_pipeline_autorun_status_path()
    if not recommendation["ready"]:
        return {
            "ok": True,
            "launched": False,
            "reason": "not_ready",
            "recommendation": recommendation,
            "status": latest_pipeline_autorun_status(path=status_path),
        }
    with _PIPELINE_AUTORUN_LOCK:
        current = latest_pipeline_autorun_status(path=status_path)
        if current.get("is_running"):
            return {
                "ok": True,
                "launched": False,
                "reason": "already_running",
                "recommendation": recommendation,
                "status": current,
            }
        root = _repo_root()
        min_usable = int(recommendation["thresholds"]["min_usable_replays"])
        report_dir = default_chess_reports_dir()
        report_dir.mkdir(parents=True, exist_ok=True)
        run_id = build_pipeline_run_id("autorun")
        log_path = report_dir / f"chess_train_pipeline_autorun_{run_id}.log"
        cmd = [
            sys.executable,
            str(root / "scripts" / "games" / "chess_train_pipeline.py"),
            "--preset",
            "standard",
            "--include-exp2",
            "--promote-engines",
            "experiment 2:nn,experiment 3:dl,experiment 4:pv",
            "--min-usable-replays",
            str(max(1, min_usable)),
        ]
        env = os.environ.copy()
        current_pythonpath = str(env.get("PYTHONPATH") or "").strip()
        root_text = str(root)
        if current_pythonpath:
            paths = current_pythonpath.split(os.pathsep)
            if root_text not in paths:
                env["PYTHONPATH"] = os.pathsep.join([root_text, current_pythonpath])
        else:
            env["PYTHONPATH"] = root_text
        log_handle = log_path.open("w", encoding="utf-8")
        log_handle.write(f"$ {' '.join(cmd)}\n\n")
        log_handle.flush()
        started_at = datetime.utcnow().isoformat() + "Z"
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(root),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except Exception:
            log_handle.close()
            raise
        status = {
            "status": "running",
            "trigger": str(trigger or "live_replay"),
            "actor_username": str(actor_username or "").strip(),
            "pid": int(proc.pid or 0),
            "started_at": started_at,
            "finished_at": "",
            "returncode": None,
            "log_path": str(log_path),
            "command": cmd,
            "run_id": run_id,
            "recommendation": recommendation,
            "replay_snapshot": replay,
        }
        _save_json(status_path, status)

        def _monitor() -> None:
            try:
                returncode = proc.wait()
            finally:
                log_handle.close()
            latest_report = latest_pipeline_report()
            finished = dict(status)
            finished.update(
                {
                    "status": "passed" if returncode == 0 else "failed",
                    "finished_at": datetime.utcnow().isoformat() + "Z",
                    "returncode": int(returncode),
                    "latest_pipeline_report_path": str(latest_report.get("path") or ""),
                }
            )
            _save_json(status_path, finished)

        threading.Thread(target=_monitor, name="chess-pipeline-autorun", daemon=True).start()
        return {
            "ok": True,
            "launched": True,
            "reason": "started",
            "recommendation": recommendation,
            "status": latest_pipeline_autorun_status(path=status_path),
        }
