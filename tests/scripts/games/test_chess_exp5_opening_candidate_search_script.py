from pathlib import Path

from scripts.games.chess_exp5_opening_candidate_search import (
    opening_rows_to_samples,
    resolve_current_production_model,
    retention_rows_to_samples,
)


def test_exp5_opening_rows_to_samples_preserves_multigood_expected_moves():
    rows = [
        {
            "id": "case1",
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "side": "white",
            "expected_uci_any": ["e2e4", "d2d4", "g1f3", "c2c4"],
        }
    ]

    samples = opening_rows_to_samples(rows, weight=2.0)

    assert len(samples) == 4
    assert {sample["move_uci"] for sample in samples} == {"e2e4", "d2d4", "g1f3", "c2c4"}
    assert all(sample["label_quality"] == "clean" for sample in samples)
    assert all(sample["category"] == "opening" for sample in samples)
    assert all(sample["teacher_top5"] == ["e2e4", "d2d4", "g1f3", "c2c4"] for sample in samples)
    assert sum(sample["weight"] for sample in samples) == 2.0


def test_exp5_retention_rows_are_limited_to_endgame_like_clean_rows():
    rows = [
        {
            "fen": "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1",
            "side": "white",
            "move_uci": "e2e4",
            "label_quality": "clean",
        },
        {
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "side": "white",
            "move_uci": "e2e4",
            "label_quality": "clean",
        },
        {
            "fen": "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1",
            "side": "white",
            "move_uci": "e2e4",
            "label_quality": "questionable",
        },
    ]

    samples = retention_rows_to_samples(rows, max_rows=10)

    assert len(samples) == 1
    assert samples[0]["source"] == "exp5_15_endgame_retention"
    assert samples[0]["move_uci"] == "e2e4"


def test_exp5_current_model_resolution_uses_fallback_when_runtime_absent(tmp_path):
    runtime = tmp_path / "missing_runtime.json"
    fallback = tmp_path / "fallback.json"
    fallback.write_text("{}", encoding="utf-8")

    resolved, source = resolve_current_production_model(runtime, fallback)

    assert resolved == fallback
    assert source == "promoted_stage_candidate_fallback"
