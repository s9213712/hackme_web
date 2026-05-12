"""Tests for W4 external-replay helpers in scripts/games/chess_seed_train.py.

Covers _load_external_replay (validation + whitelist), _apply_external_caps
(per-source + total cap, deterministic via seed), and _train_with_external_replay
(dry_run / empty short-circuits).
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.games.chess_seed_train import (
    DEFAULT_EXTERNAL_TOTAL_CAP,
    TRUSTED_SOURCE_WHITELIST,
    _apply_external_caps,
    _load_external_replay,
    _train_with_external_replay,
    _validate_normalize,
)


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


# ---- _load_external_replay --------------------------------------------


def _row(**kwargs) -> dict:
    base = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "move_uci": "e7e5",
        "side": "black",
        "target": 1.0,
        "weight": 0.15,
        "source": "pvp",
        "trusted_source": "pvp_filtered",
        "label_quality": "review",
    }
    base.update(kwargs)
    return base


def test_load_external_replay_keeps_whitelisted_rows(tmp_path):
    path = _write_jsonl(
        tmp_path / "a.jsonl",
        [
            _row(trusted_source="pvp_filtered"),
            _row(trusted_source="human_beat_engine", weight=0.20, label_quality="clean"),
            _row(trusted_source="imported_dataset"),
        ],
    )
    samples, stats = _load_external_replay([str(path)])
    assert stats["files_read"] == 1
    assert stats["rows_total"] == 3
    assert stats["rows_kept"] == 3
    assert stats["rejected_invalid_trusted_source"] == 0
    assert stats["source_breakdown_raw"]["pvp_filtered"] == 1
    assert stats["source_breakdown_raw"]["human_beat_engine"] == 1
    assert stats["source_breakdown_raw"]["imported_dataset"] == 1
    assert len(samples) == 3


def test_load_external_replay_rejects_non_whitelisted_source(tmp_path):
    path = _write_jsonl(
        tmp_path / "b.jsonl",
        [
            _row(trusted_source="random_internet"),
            _row(trusted_source=""),
            _row(trusted_source="pvp_filtered"),
        ],
    )
    samples, stats = _load_external_replay([str(path)])
    assert stats["rows_total"] == 3
    assert stats["rejected_invalid_trusted_source"] == 2
    assert stats["rows_kept"] == 1
    assert samples[0]["trusted_source"] == "pvp_filtered"


def test_load_external_replay_rejects_missing_required_fields(tmp_path):
    path = _write_jsonl(
        tmp_path / "c.jsonl",
        [
            _row(fen=""),
            _row(move_uci=""),
            _row(side=""),
            _row(),
        ],
    )
    samples, stats = _load_external_replay([str(path)])
    assert stats["rejected_missing_fields"] == 3
    assert stats["rows_kept"] == 1
    assert len(samples) == 1


def test_load_external_replay_skips_blank_and_invalid_json(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(_row()),
                "",
                "not-json-at-all",
                json.dumps(_row(trusted_source="human_beat_engine")),
            ]
        ),
        encoding="utf-8",
    )
    samples, stats = _load_external_replay([str(path)])
    # Blank line skipped before counting, invalid_json counted but rejected.
    assert stats["rows_total"] == 3
    assert stats["rejected_invalid_json"] == 1
    assert stats["rows_kept"] == 2


def test_load_external_replay_handles_missing_file(tmp_path):
    samples, stats = _load_external_replay([str(tmp_path / "does_not_exist.jsonl")])
    assert stats["files_read"] == 0
    assert stats["files_missing"] != []
    assert samples == []


# ---- _apply_external_caps ---------------------------------------------


def test_apply_caps_downsamples_per_source(tmp_path):
    samples = (
        [_row(trusted_source="pvp_filtered") for _ in range(150)]
        + [_row(trusted_source="human_beat_engine") for _ in range(150)]
        + [_row(trusted_source="sparring_objective_hit") for _ in range(80)]
    )
    capped, stats = _apply_external_caps(samples, seed=42)
    # pvp_filtered cap = 100, hve cap = 100, sparring cap = 50
    assert stats["per_source"]["pvp_filtered"]["kept_after_per_source_cap"] == 100
    assert stats["per_source"]["human_beat_engine"]["kept_after_per_source_cap"] == 100
    assert stats["per_source"]["sparring_objective_hit"]["kept_after_per_source_cap"] == 50
    # pre-total = 250; total cap default 300 → all kept after total cap
    assert stats["pre_total_cap_count"] == 250
    assert stats["total_kept"] == 250


def test_apply_caps_enforces_total_cap(tmp_path):
    samples = (
        [_row(trusted_source="pvp_filtered") for _ in range(100)]
        + [_row(trusted_source="human_beat_engine") for _ in range(100)]
        + [_row(trusted_source="imported_dataset") for _ in range(200)]
    )
    capped, stats = _apply_external_caps(samples, seed=42)
    # pvp+hve = 100+100, imported_dataset cap=200 → pre_total=400, total_cap=300
    assert stats["pre_total_cap_count"] == 400
    assert stats["total_kept"] == DEFAULT_EXTERNAL_TOTAL_CAP == 300


def test_apply_caps_deterministic_with_same_seed(tmp_path):
    samples = [_row(trusted_source="pvp_filtered", source_id=f"id-{i}") for i in range(150)]
    a, _ = _apply_external_caps(samples, seed=99)
    b, _ = _apply_external_caps(samples, seed=99)
    assert [s.get("source_id") for s in a] == [s.get("source_id") for s in b]


# ---- _train_with_external_replay --------------------------------------


def test_train_with_external_replay_short_circuits_when_dry_run(tmp_path):
    samples = [_row()]
    result = _train_with_external_replay(
        samples,
        pv_model_path=tmp_path / "pv.json",
        nnue_model_path=tmp_path / "nnue.json",
        dry_run=True,
        skip_exp4=False,
    )
    assert result["trained_exp4"] is False
    assert result["trained_exp5"] is False
    assert result["skipped_reason"] == "dry_run"
    assert result["sample_count"] == 1


def test_train_with_external_replay_short_circuits_when_empty(tmp_path):
    result = _train_with_external_replay(
        [],
        pv_model_path=tmp_path / "pv.json",
        nnue_model_path=tmp_path / "nnue.json",
        dry_run=False,
        skip_exp4=False,
    )
    assert result["skipped_reason"] == "no_samples"
    assert result["trained_exp4"] is False
    assert result["trained_exp5"] is False


def test_trusted_source_whitelist_includes_new_sources():
    # Regression guard: future commits must not silently drop these names.
    for name in ("pvp_filtered", "human_beat_engine", "sparring_objective_hit"):
        assert name in TRUSTED_SOURCE_WHITELIST


# ---- _validate_normalize -----------------------------------------------


def test_validate_normalize_accepts_typical_pvp_sample():
    samples = [
        _row(source_id=f"id-{i}", trusted_source="pvp_filtered")
        for i in range(5)
    ]
    stats = _validate_normalize(samples)
    assert stats["exp4_ok"] == 5
    assert stats["exp4_failed"] == 0
    assert stats["exp5_ok"] == 5
    assert stats["exp5_failed"] == 0
    assert stats["exp4_failed_samples"] == []
    assert stats["exp5_failed_samples"] == []


def test_validate_normalize_counts_failures_and_records_ids():
    # Empty fen / move_uci / side break both normalizers (they require those).
    bad = [
        _row(source_id="bad-fen", fen=""),
        _row(source_id="bad-move", move_uci=""),
    ]
    good = [_row(source_id="good-1")]
    stats = _validate_normalize(bad + good)
    # exp4 PV falls back to build_experiment_pv_sample_from_position when
    # board_features / move_features are absent; that path requires
    # non-empty fen + move_uci. Both bad rows should fail; the good one
    # succeeds.
    assert stats["exp4_failed"] == 2
    assert stats["exp4_ok"] == 1
    assert stats["exp5_failed"] == 2
    assert stats["exp5_ok"] == 1
    assert "bad-fen" in stats["exp4_failed_samples"]
    assert "bad-move" in stats["exp4_failed_samples"]


# ---- _train_with_external_replay skip flags ---------------------------


def test_train_with_external_replay_skip_exp5_blocks_nnue_training(monkeypatch, tmp_path):
    """skip_exp5 must skip the NNUE trainer even when dry_run is False."""
    pv_calls: list = []
    nnue_calls: list = []

    def fake_pv(samples, *, model_path):
        pv_calls.append((len(samples), str(model_path)))
        return {"trained_samples": len(samples)}

    def fake_nnue(samples, *, model_path):
        nnue_calls.append((len(samples), str(model_path)))
        return {"trained_samples": len(samples)}

    monkeypatch.setattr(
        "scripts.games.chess_seed_train.train_experiment_pv_from_replay_samples", fake_pv
    )
    monkeypatch.setattr(
        "scripts.games.chess_seed_train.train_experiment_nnue_from_replay_samples", fake_nnue
    )

    result = _train_with_external_replay(
        [_row()],
        pv_model_path=tmp_path / "pv.json",
        nnue_model_path=tmp_path / "nnue.json",
        dry_run=False,
        skip_exp4=False,
        skip_exp5=True,
    )
    assert result["trained_exp4"] is True
    assert result["trained_exp5"] is False
    assert len(pv_calls) == 1
    assert nnue_calls == []


def test_train_with_external_replay_skip_exp4_blocks_pv_training(monkeypatch, tmp_path):
    pv_calls: list = []
    nnue_calls: list = []
    monkeypatch.setattr(
        "scripts.games.chess_seed_train.train_experiment_pv_from_replay_samples",
        lambda samples, *, model_path: pv_calls.append(samples) or {},
    )
    monkeypatch.setattr(
        "scripts.games.chess_seed_train.train_experiment_nnue_from_replay_samples",
        lambda samples, *, model_path: nnue_calls.append(samples) or {},
    )

    result = _train_with_external_replay(
        [_row()],
        pv_model_path=tmp_path / "pv.json",
        nnue_model_path=tmp_path / "nnue.json",
        dry_run=False,
        skip_exp4=True,
        skip_exp5=False,
    )
    assert result["trained_exp4"] is False
    assert result["trained_exp5"] is True
    assert pv_calls == []
    assert len(nnue_calls) == 1
