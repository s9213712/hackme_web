from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "games" / "chess_live_learning_validation.py"


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


def test_live_learning_validation_expands_traps_and_probe_range():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "white_fried_liver_probe" in source
    assert "black_caro_kann_probe" in source
    assert "short_low_signal_trap" in source
    assert "premature_resign_trap" in source
    assert "promotion_white" in source
    assert "free_queen_white" in source
