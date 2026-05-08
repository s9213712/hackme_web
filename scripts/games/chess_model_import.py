#!/usr/bin/env python3
"""Validate and install external chess model weights into runtime.

Supported inputs:

- app-compatible `.json`
- `.npz` archives produced by NumPy / PyTorch export steps
- `.pt` / `.pth` state-dicts when `torch` is installed

The importer fills missing metadata from the app's canonical template, then
validates shapes against the exact schema expected by the runtime loader.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_dl import (  # noqa: E402
    EXPERIMENT_DL_DIFFICULTY,
    default_chess_dl_model_path,
    experiment_dl_model_template,
    normalize_experiment_dl_model_payload,
)
from services.games.chess_pv import (  # noqa: E402
    EXPERIMENT_PV_DIFFICULTY,
    default_chess_pv_model_path,
    experiment_pv_model_template,
    normalize_experiment_pv_model_payload,
)
from services.games.chess_nn import (  # noqa: E402
    EXPERIMENT_NN_DIFFICULTY,
    default_chess_nn_model_path,
    experiment_nn_model_template,
    normalize_experiment_nn_model_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and install external chess experiment models.")
    parser.add_argument("--engine", required=True, choices=[EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY, "exp2", "exp3", "exp4"])
    parser.add_argument("--input", required=True, help="Input model file (.json, .npz, .pt, .pth)")
    parser.add_argument("--output", default="", help="Destination runtime model path. Defaults to engine runtime path.")
    parser.add_argument("--validate-only", action="store_true", help="Validate input without writing runtime model.")
    return parser.parse_args()


def _normalized_engine(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "exp2":
        return EXPERIMENT_NN_DIFFICULTY
    if normalized == "exp3":
        return EXPERIMENT_DL_DIFFICULTY
    if normalized == "exp4":
        return EXPERIMENT_PV_DIFFICULTY
    return normalized


def _ensure_datetime_text() -> str:
    return datetime.now().isoformat()


def _plain_python(value):
    if isinstance(value, dict):
        return {str(key): _plain_python(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_python(item) for item in value]
    if hasattr(value, "detach") and hasattr(value, "cpu") and hasattr(value, "tolist"):
        try:
            return value.detach().cpu().tolist()
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _strip_state_prefix(mapping: dict) -> dict:
    cleaned = {}
    for key, value in mapping.items():
        normalized = str(key)
        if normalized.startswith("module."):
            normalized = normalized[len("module."):]
        cleaned[normalized] = value
    return cleaned


def _extract_mapping(payload) -> dict:
    raw = _plain_python(payload)
    if not isinstance(raw, dict):
        raise ValueError("input payload must decode to a mapping")
    if isinstance(raw.get("state_dict"), dict):
        raw = raw["state_dict"]
    elif isinstance(raw.get("model"), dict):
        raw = raw["model"]
    return _strip_state_prefix({str(key): _plain_python(value) for key, value in raw.items()})


def _load_json(path: Path) -> dict:
    return _extract_mapping(json.loads(path.read_text(encoding="utf-8")))


def _load_npz(path: Path) -> dict:
    try:
        import numpy as np
    except Exception as exc:
        raise ValueError("NumPy is required to import .npz model files") from exc
    with np.load(path, allow_pickle=True) as archive:
        return _extract_mapping({str(key): archive[key] for key in archive.files})


def _load_torch(path: Path) -> dict:
    try:
        import torch
    except Exception as exc:
        raise ValueError("PyTorch is required to import .pt/.pth model files") from exc
    payload = torch.load(path, map_location="cpu")
    return _extract_mapping(payload)


def _load_input(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".npz":
        return _load_npz(path)
    if suffix in {".pt", ".pth"}:
        return _load_torch(path)
    raise ValueError(f"unsupported input format: {suffix or '<no suffix>'}")


def _merge_into_template(template: dict, raw: dict) -> dict:
    merged = dict(template)
    for key, value in raw.items():
        merged[key] = _plain_python(value)
    merged["updated_at"] = str(raw.get("updated_at") or merged.get("updated_at") or _ensure_datetime_text())
    if "sample_count" in merged:
        try:
            merged["sample_count"] = max(0, int(merged.get("sample_count") or 0))
        except Exception:
            merged["sample_count"] = 0
    if "replay_size" in merged:
        try:
            merged["replay_size"] = max(0, int(merged.get("replay_size") or 0))
        except Exception:
            merged["replay_size"] = 0
    return merged


def _validate_for_engine(engine: str, raw: dict) -> dict:
    if engine == EXPERIMENT_NN_DIFFICULTY:
        candidate = _merge_into_template(experiment_nn_model_template(), raw)
        normalized = normalize_experiment_nn_model_payload(candidate)
        if normalized is None:
            raise ValueError("exp2 model validation failed: schema/shape mismatch")
        return normalized
    if engine == EXPERIMENT_DL_DIFFICULTY:
        candidate = _merge_into_template(experiment_dl_model_template(), raw)
        normalized = normalize_experiment_dl_model_payload(candidate)
        if normalized is None:
            raise ValueError("exp3 model validation failed: schema/shape mismatch")
        return normalized
    if engine == EXPERIMENT_PV_DIFFICULTY:
        candidate = _merge_into_template(experiment_pv_model_template(), raw)
        normalized = normalize_experiment_pv_model_payload(candidate)
        if normalized is None:
            raise ValueError("exp4 model validation failed: schema/shape mismatch")
        return normalized
    raise ValueError(f"unsupported engine: {engine}")


def _default_output_for_engine(engine: str) -> Path:
    if engine == EXPERIMENT_NN_DIFFICULTY:
        return default_chess_nn_model_path()
    if engine == EXPERIMENT_DL_DIFFICULTY:
        return default_chess_dl_model_path()
    if engine == EXPERIMENT_PV_DIFFICULTY:
        return default_chess_pv_model_path()
    raise ValueError(f"unsupported engine: {engine}")


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _summary(engine: str, output_path: Path | None, payload: dict, *, validate_only: bool) -> dict:
    summary = {
        "ok": True,
        "engine": engine,
        "validate_only": bool(validate_only),
        "architecture": str(payload.get("architecture") or ""),
        "version": int(payload.get("version") or 0),
        "sample_count": int(payload.get("sample_count") or 0),
    }
    if engine == EXPERIMENT_NN_DIFFICULTY:
        summary["input_size"] = int(payload.get("input_size") or 0)
        summary["hidden_size"] = int(payload.get("hidden_size") or 0)
    elif engine == EXPERIMENT_DL_DIFFICULTY:
        summary["input_size"] = int(payload.get("input_size") or 0)
        summary["hidden1_size"] = int(payload.get("hidden1_size") or 0)
        summary["hidden2_size"] = int(payload.get("hidden2_size") or 0)
        summary["replay_size"] = int(payload.get("replay_size") or 0)
    else:
        summary["board_input_size"] = int(payload.get("board_input_size") or 0)
        summary["move_input_size"] = int(payload.get("move_input_size") or 0)
        summary["shared_hidden_size"] = int(payload.get("shared_hidden_size") or 0)
    if output_path is not None:
        summary["output_path"] = str(output_path)
    return summary


def main() -> int:
    args = parse_args()
    engine = _normalized_engine(args.engine)
    input_path = Path(args.input).expanduser().resolve()
    raw = _load_input(input_path)
    payload = _validate_for_engine(engine, raw)
    output_path = None if args.validate_only else Path(args.output).expanduser().resolve() if args.output else _default_output_for_engine(engine)
    if output_path is not None:
        _save_json(output_path, payload)
    print(json.dumps(_summary(engine, output_path, payload, validate_only=args.validate_only), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
