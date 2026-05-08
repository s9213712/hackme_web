"""Bundled seed models and runtime model path helpers for chess engines."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from services.server.runtime import default_runtime_root_path


GAMES_DIR = Path(__file__).resolve().parent
BUNDLED_MODELS_DIR = GAMES_DIR / "models"
RUNTIME_GAMES_SUBDIR = ("games", "models")


def bundled_chess_models_dir() -> Path:
    return BUNDLED_MODELS_DIR


def runtime_chess_models_dir() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        runtime_dir = str(default_runtime_root_path())
    explicit = os.environ.get("HTML_LEARNING_CHESS_MODEL_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return Path(runtime_dir).joinpath(*RUNTIME_GAMES_SUBDIR)


def bundled_seed_model_path(filename: str) -> Path:
    return bundled_chess_models_dir() / filename


def bundled_seed_database_path(filename: str) -> Path:
    return bundled_chess_models_dir() / filename


def runtime_model_path(filename: str, *, env_var: str = "") -> Path:
    override = os.environ.get(env_var, "").strip() if env_var else ""
    return Path(override) if override else runtime_chess_models_dir() / filename


def ensure_runtime_model_from_bundle(runtime_path: Path, bundled_path: Path) -> dict:
    runtime_path = Path(runtime_path)
    bundled_path = Path(bundled_path)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    if runtime_path.exists():
        return {
            "ok": True,
            "created": False,
            "copied": False,
            "runtime_path": str(runtime_path),
            "bundle_path": str(bundled_path),
            "source": "runtime_existing",
        }
    if bundled_path.exists():
        shutil.copyfile(bundled_path, runtime_path)
        return {
            "ok": True,
            "created": True,
            "copied": True,
            "runtime_path": str(runtime_path),
            "bundle_path": str(bundled_path),
            "source": "bundled_seed",
        }
    return {
        "ok": False,
        "created": False,
        "copied": False,
        "runtime_path": str(runtime_path),
        "bundle_path": str(bundled_path),
        "source": "missing_bundle",
    }
