import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "games" / "chess_live_learning_validation.py"


def _load_validation_module():
    spec = importlib.util.spec_from_file_location("chess_live_learning_validation_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_learning_validation_fast_retrain_flags_are_wired():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "--fast-retrain" in source
    assert "--skip-autorun-benchmark" in source
    assert "--skip-autorun-promote" in source
    assert "--skip-retrain-benchmark-snapshots" in source
    assert "HTML_LEARNING_CHESS_AUTORUN_SKIP_BENCHMARK" in source
    assert "HTML_LEARNING_CHESS_AUTORUN_SKIP_PROMOTE" in source
    assert "skip_autorun_benchmark=skip_autorun_benchmark" in source
    assert "skip_autorun_promote=skip_autorun_promote" in source
    assert "skip_retrain_benchmark_snapshots=skip_retrain_benchmark_snapshots" in source
    assert "_skipped_benchmark_snapshot" in source
    assert '"autorun_skip_benchmark"' in source
    assert '"autorun_skip_promote"' in source
    assert '"retrain_benchmark_snapshots_skipped"' in source


def test_live_learning_validation_retrains_every_ten_valid_games_and_records_old_probe():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "AUTORUN_THRESHOLD = 10" in source
    assert "_evaluate_retention_probe" in source
    assert '"counted_as_game": False' in source
    assert '"source": "old_trusted_engine_move"' in source
    assert '"retention_probe": retention_probe' in source


def test_live_learning_validation_reports_retrain_and_step_timing():
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"retrain_duration_seconds"' in source
    assert '"checkpoint_duration_seconds"' in source
    assert '"avg_think_ms_per_step"' in source
    assert '"think_steps_measured"' in source
    assert "_flow_timing_summary" in source
    assert "_checkpoint_timing_summary" in source


def test_live_learning_validation_reports_audit_gate_and_failure_context():
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"dataset_integrity"' in source
    assert '"stability"' in source
    assert '"promotion_gate"' in source
    assert '"poison_detection"' in source
    assert '"replay_sources"' in source
    assert '"runtime_metrics"' in source
    assert '"reproducibility"' in source
    assert "## Why This Run Failed" in source
    assert "_failure_explanations" in source


def test_live_learning_validation_gate_is_decision_evidence_not_dashboard_only():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "benchmark skipped:" in source
    assert "catastrophic_regression" in source
    assert 'overall_verdict = "HIGH_RISK"' in source
    assert "forced repetition poison signal exceeded threshold" in source
    assert "illegal moves detected in dataset" in source
    assert '"gate_decision": checkpoint_gate' in source
    assert '"dataset_hash"' in source
    assert '"benchmark_skip_reason"' in source
    assert "## Can This Model Be Promoted?" in source
    assert "_promotion_explanation" in source
    assert "_report_consistency_issues" in source


def test_live_learning_validation_expands_traps_and_probe_range():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "white_fried_liver_probe" in source
    assert "black_caro_kann_probe" in source
    assert "short_low_signal_trap" in source
    assert "premature_resign_trap" in source
    assert "promotion_white" in source
    assert "free_queen_white" in source


def test_live_learning_validation_minimal_gate_failure_fixture_writes_consistent_reports(tmp_path):
    module = _load_validation_module()
    module._environment_summary = lambda: {"python_version": "test", "platform": "test", "cpu": "test", "gpu": "", "torch_version": ""}
    skip_reason = "disabled_by_fast_retrain"
    summary = {
        "engine_alias": "exp2",
        "difficulty": "experiment 2:nn",
        "seed": 7,
        "started_at": "2026-05-09T00:00:00+00:00",
        "finished_at": "2026-05-09T00:01:00+00:00",
        "commit": "fixture",
        "total_games": module.TOTAL_GAMES,
        "games": [],
        "invalid_case_audit": [],
        "replay_summary": {"trusted_replays": module.VALID_GAMES, "quarantine_replays": module.INVALID_GAMES, "rejected_replays": 0},
        "retrain_result": {"retrain_supported": True, "trainer_probe": {"validation": {"accepted_samples_gt_zero": True, "rejected_samples_match": True}}},
        "autorun": {"launched": True},
        "autorun_status": {"status": "completed"},
        "dataset_result": {"accepted_rows": 3, "rejected_rows": 2, "dataset_sha256": "datasetfixture"},
        "dataset_integrity": {
            "total_rows": 3,
            "unique_positions": 1,
            "duplicate_positions": 2,
            "duplicate_ratio": 0.667,
            "invalid_fen": 1,
            "illegal_moves": 1,
            "side_mismatch": 0,
            "mate_positions": 0,
            "terminal_positions": 0,
            "avg_game_length": 3.0,
            "short_resign_games": 0,
            "contaminated_rows": 0,
        },
        "poison_detection": {
            "forced_repetition_patterns": 1,
            "intentional_blunders": 1,
            "engine_copy_suspected": 1,
            "suspicious_resign_rate": 0.2,
            "suspicious_resigns": 1,
        },
        "evaluation_before": {"agreement": 0.5, "avg_think_ms": 1.0, "total_think_ms": 2.0},
        "evaluation_after": {"agreement": 0.5, "avg_think_ms": 1.1, "total_think_ms": 2.2},
        "game_timing": {"avg_think_ms_per_step": 3.0, "steps_measured": 2, "total_think_ms": 6.0},
        "retrain_timing": {"checkpoint_count": 1, "total_retrain_seconds": 4.0, "avg_retrain_seconds": 4.0, "total_checkpoint_seconds": 5.0},
        "model_before": {"sha256": "before"},
        "model_after": {"sha256": "after"},
        "before_after_eval": {
            "benchmark_before": {"skipped": True, "reason": skip_reason},
            "benchmark_after": {"skipped": True, "reason": skip_reason},
            "checkpoints": [
                {
                    "dataset_hash": "sha256:datasetfixture",
                    "pre_checkpoint_model_sha256": "before",
                    "post_checkpoint_model_sha256": "after",
                    "benchmark_skipped": True,
                    "benchmark_skip_reason": skip_reason,
                    "gate_decision": {"passed": False, "reasons": [f"benchmark skipped: {skip_reason}"]},
                }
            ],
        },
        "stability": {
            "catastrophic_regression": True,
            "opening_regression": 0.0,
            "tactical_regression": 0.0,
            "endgame_regression": 0.0,
            "illegal_move_delta": None,
            "blunder_rate_before": None,
            "blunder_rate_after": None,
        },
        "exp1_live_learning": {},
        "runtime_metrics": {},
        "reproducibility": {},
    }
    summary["engine_verdict"] = module._engine_verdict(summary)
    summary["promotion_gate"] = module._promotion_gate_summary(summary)
    summary["suitable_for_production_self_learning"] = summary["engine_verdict"] == "PASS" and summary["promotion_gate"]["passed"]

    engine_dir = tmp_path / "exp2"
    engine_dir.mkdir()
    module._json_dump(engine_dir / "summary.json", summary)
    module._write_engine_report(engine_dir, summary)
    root_summary = module._build_root_summary(
        output_root=tmp_path,
        summaries=[summary],
        skip_autorun_benchmark=True,
        skip_autorun_promote=True,
        skip_retrain_benchmark_snapshots=True,
    )
    module._write_root_report(tmp_path, root_summary, [summary])

    root_json = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    engine_json = json.loads((engine_dir / "summary.json").read_text(encoding="utf-8"))
    root_md = (tmp_path / "SUMMARY.md").read_text(encoding="utf-8")
    engine_md = (engine_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert root_json["overall_verdict"] == "HIGH_RISK"
    assert root_json["engines"][0]["promotion_gate_passed"] is False
    assert engine_json["promotion_gate"]["passed"] is False
    assert f"benchmark skipped: {skip_reason}" in engine_json["promotion_gate"]["reasons"]
    assert "illegal moves detected in dataset" in engine_json["promotion_gate"]["reasons"]
    assert "forced repetition poison signal exceeded threshold" in engine_json["promotion_gate"]["reasons"]
    assert "## Can This Model Be Promoted?" in root_md
    assert "## Can This Model Be Promoted?" in engine_md
    assert f"benchmark skipped: {skip_reason}" in root_md
    assert f"benchmark skipped: {skip_reason}" in engine_md
    assert module._report_consistency_issues(root_json, [engine_json], root_md, {"exp2": engine_md}) == []
