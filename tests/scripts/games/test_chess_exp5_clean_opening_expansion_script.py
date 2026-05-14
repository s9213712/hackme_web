import json
from pathlib import Path

import chess

from scripts.games.chess_exp5_clean_opening_expansion import (
    _build_curated_rows,
    build_clean_opening_expansion,
)


def test_exp5_clean_opening_curated_rows_are_legal_multi_good():
    rows = _build_curated_rows()

    assert len(rows) >= 30
    assert all(row["category"] == "opening" for row in rows)
    assert all(row["label_quality"] == "clean" for row in rows)
    assert all(row["multi_good"] for row in rows)
    for row in rows:
        board = chess.Board(row["fen"])
        assert row["side"] == ("white" if board.turn == chess.WHITE else "black")
        legal = {move.uci() for move in board.legal_moves}
        assert set(row["expected_uci_any"]).issubset(legal)
        assert row["teacher_move"] in row["expected_uci_any"]
        assert row["position_id"]


def test_exp5_clean_opening_expansion_outputs_artifacts_without_model_eval(tmp_path):
    output_dir = tmp_path / "out"
    train_path = tmp_path / "train.jsonl"
    benchmark_summary = tmp_path / "summary.json"
    train_path.write_text("", encoding="utf-8")
    benchmark_summary.write_text(json.dumps({"benchmark": {"rows": []}}, ensure_ascii=False), encoding="utf-8")

    result = build_clean_opening_expansion(
        train_paths=[train_path],
        benchmark_summary=benchmark_summary,
        output_dir=output_dir,
        production_model=tmp_path / "missing_production.json",
        fallback_production_model=tmp_path / "missing_fallback.json",
        baseline_model=tmp_path / "missing_baseline.json",
        search_profile="fixed_depth_fast",
        min_clean_rows=30,
    )

    assert result["pass"] is True
    assert result["clean_opening_rows"] >= 30
    assert result["true_heldout_rows"] == result["clean_opening_rows"]
    assert result["multi_good_rows"] == result["clean_opening_rows"]
    assert result["label_quality_counts"] == {"clean": result["clean_opening_rows"]}
    assert result["overlap"]["train_vs_curated_overlap_count"] == 0
    assert result["overlap"]["benchmark_vs_curated_overlap_count"] == 0
    assert Path(result["artifacts"]["clean_opening_cases_jsonl"]).exists()
    assert Path(result["artifacts"]["summary_json"]).exists()
