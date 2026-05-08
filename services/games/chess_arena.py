"""Helpers for reading chess arena / benchmark artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path

from services.server.runtime import default_runtime_root_path


def default_chess_reports_dir() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip() or str(default_runtime_root_path())
    reports_root = os.environ.get("HTML_LEARNING_REPORTS_DIR", "").strip() or os.path.join(runtime_dir, "reports")
    return Path(reports_root) / "games"


def _latest_matching_json(pattern: str, *, report_dir: Path | None = None) -> Path | None:
    root = Path(report_dir or default_chess_reports_dir())
    candidates = sorted(root.glob(pattern))
    return candidates[-1] if candidates else None


def _load_json(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_training_report(*, report_dir: Path | None = None) -> dict:
    path = _latest_matching_json("chess_self_play_train_*.json", report_dir=report_dir)
    payload = _load_json(path)
    return {
        "path": str(path) if path else "",
        "exists": bool(path and path.exists()),
        "summary": payload or {},
    }


def latest_seed_training_report(*, report_dir: Path | None = None) -> dict:
    path = _latest_matching_json("chess_seed_train_*.json", report_dir=report_dir)
    payload = _load_json(path)
    return {
        "path": str(path) if path else "",
        "exists": bool(path and path.exists()),
        "summary": payload or {},
    }


def latest_replay_prepare_report(*, report_dir: Path | None = None) -> dict:
    path = _latest_matching_json("chess_replay_prepare_*.json", report_dir=report_dir)
    payload = _load_json(path)
    return {
        "path": str(path) if path else "",
        "exists": bool(path and path.exists()),
        "summary": payload or {},
    }


def latest_benchmark_report(*, report_dir: Path | None = None) -> dict:
    training = latest_training_report(report_dir=report_dir)
    payload = training.get("summary") or {}
    benchmark = payload.get("benchmark") if isinstance(payload, dict) else None
    smoke = payload.get("smoke_evaluation") if isinstance(payload, dict) else None
    return {
        "training_report_path": training.get("path") or "",
        "benchmark": benchmark or {},
        "smoke_evaluation": smoke or {},
    }


def latest_pipeline_report(*, report_dir: Path | None = None) -> dict:
    path = _latest_matching_json("chess_train_pipeline_*.json", report_dir=report_dir)
    payload = _load_json(path)
    return {
        "path": str(path) if path else "",
        "exists": bool(path and path.exists()),
        "summary": payload or {},
    }
