import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


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
    assert "--allow-multi-engine" in source
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


def test_live_learning_validation_requires_individual_engine_selection():
    module = _load_validation_module()

    assert module._select_requested_engines("exp2") == [("exp2", module.EXPERIMENT_NN_DIFFICULTY)]
    try:
        module._select_requested_engines("")
    except ValueError as exc:
        assert "pass exactly one --engines alias" in str(exc)
    else:
        raise AssertionError("empty engine selection should fail")
    try:
        module._select_requested_engines("exp2,exp3")
    except ValueError as exc:
        assert "multi-engine validation is disabled" in str(exc)
    else:
        raise AssertionError("multi-engine selection should fail without override")
    assert module._select_requested_engines("exp2,exp3", allow_multi_engine=True) == [
        ("exp2", module.EXPERIMENT_NN_DIFFICULTY),
        ("exp3", module.EXPERIMENT_DL_DIFFICULTY),
    ]


def test_live_learning_validation_retrains_every_ten_valid_games_and_records_old_probe():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "BASE_VALID_GAMES = 20" in source
    assert "EXTRA_VALID_GAMES = 5" in source
    assert "AUTORUN_THRESHOLD = 10" in source
    assert "return combined + extra_valid_games" in source
    assert "_evaluate_retention_probe" in source
    assert "_evaluate_mistake_retention_probe" in source
    assert '"counted_as_game": False' in source
    assert '"source": "old_trusted_engine_move"' in source
    assert '"source": "old_trusted_engine_move_mistake"' in source
    assert '"retention_probe": retention_probe' in source
    assert '"mistake_retention_probe": mistake_retention_probe' in source


def test_mistake_retention_probe_requires_before_failure_and_after_fix(monkeypatch):
    module = _load_validation_module()
    samples = [{"fen": "fixture", "side": "white", "move_uci": "e2e4", "game_index": 1, "game_id": 7, "game_label": "old_error", "ply": 3}]
    calls = []

    def fake_choose(engine_alias, board_state, side, model_path):
        calls.append(str(model_path))
        if str(model_path) == "before":
            return {"from": "g1", "to": "f3"}
        return {"from": "e2", "to": "e4"}

    monkeypatch.setattr(module, "_choose_engine_move_for_eval", fake_choose)

    result = module._evaluate_mistake_retention_probe("exp2", Path("before"), Path("after"), samples)

    assert result["counted_as_game"] is False
    assert result["source"] == "old_trusted_engine_move_mistake"
    assert result["probe_case_id"] == "game:7:ply:3:e2e4"
    assert result["before_failed"] is True
    assert result["after_fixed"] is True
    assert result["avoided_same_error"] is True
    assert result["learning_signal"] is True
    assert "before model failed" in result["learning_signal_reason"]


def test_mistake_retention_probe_does_not_claim_learning_without_prior_mistake(monkeypatch):
    module = _load_validation_module()
    samples = [{"fen": "fixture", "side": "white", "move_uci": "e2e4"}]

    monkeypatch.setattr(module, "_choose_engine_move_for_eval", lambda *args, **kwargs: {"from": "e2", "to": "e4"})

    result = module._evaluate_mistake_retention_probe("exp2", Path("before"), Path("after"), samples)

    assert result["supported"] is False
    assert result["reason"] == "no_prior_mistake_sample"
    assert result["counted_as_game"] is False
    assert result["probe_case_id"] == "game:0:ply:0:e2e4"
    assert result["before_move"] == "e2e4"
    assert result["after_move"] == "e2e4"
    assert result["avoided_same_error"] is False
    assert result["learning_signal"] is False
    assert "目前沒有足夠證據證明 retrain 改善了該錯誤" in result["human_explanation"]


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

    assert "deterministic strength gate skipped:" in source
    assert "Stochastic Auxiliary Game Benchmark" in source
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
    assert "_evaluate_deterministic_strength_snapshot" in source
    assert "hash_changed only proves model bytes changed" in source


def test_live_learning_validation_expands_traps_and_probe_range():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "white_fried_liver_probe" in source
    assert "black_caro_kann_probe" in source
    assert "short_low_signal_trap" in source
    assert "premature_resign_trap" in source
    assert "promotion_white" in source
    assert "free_queen_white" in source


def test_prepare_formal_dataset_blocks_validation_invalid_rows(tmp_path, monkeypatch):
    module = _load_validation_module()
    engine_dir = tmp_path / "exp2"
    runtime_dir = tmp_path / "runtime"
    reports_dir = runtime_dir / "reports" / "games"
    reports_dir.mkdir(parents=True)
    module._jsonl_dump(reports_dir / "chess_replays_quarantine.jsonl", [])
    module._jsonl_dump(reports_dir / "chess_replays_rejected.jsonl", [])

    def fake_run_json_subprocess(cmd, cwd):
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        module._jsonl_dump(
            output_dir / "train.jsonl",
            [
                {"source_game_id": 1001, "engine_name": "experiment 2:nn", "move_count": 20},
                {"source_game_id": 2001, "engine_name": "experiment 2:nn", "move_count": 20},
            ],
        )
        return {"ok": True}

    monkeypatch.setattr(module, "_run_json_subprocess", fake_run_json_subprocess)

    result = module._prepare_formal_dataset(engine_dir, runtime_dir, invalid_game_ids={2001})
    train_rows = module._read_jsonl(engine_dir / "train_dataset.jsonl")
    rejected_rows = module._read_jsonl(engine_dir / "rejected_dataset.jsonl")

    assert result["contaminated_rows"] == 0
    assert result["blocked_contaminated_rows"] == 1
    assert [row["source_game_id"] for row in train_rows] == [1001]
    assert any(row["source_game_id"] == 2001 and row["reject_reason"] == "validation_invalid_game" for row in rejected_rows)


def test_checkpoint_trigger_consumes_target_and_ignores_invalid_stored_rows():
    module = _load_validation_module()
    pending = {10, 20}
    valid_game = SimpleNamespace(category="valid")
    invalid_game = SimpleNamespace(category="invalid_duplicate")

    assert module._should_launch_checkpoint(
        engine_alias="exp4",
        game=valid_game,
        stored_replay={"stored": True},
        trusted_replays=10,
        pending_checkpoint_targets=pending,
    )
    pending.discard(10)
    assert not module._should_launch_checkpoint(
        engine_alias="exp4",
        game=invalid_game,
        stored_replay={"stored": True},
        trusted_replays=10,
        pending_checkpoint_targets=pending,
    )
    assert not module._should_launch_checkpoint(
        engine_alias="exp4",
        game=valid_game,
        stored_replay={"stored": True},
        trusted_replays=10,
        pending_checkpoint_targets=pending,
    )
    assert module._should_launch_checkpoint(
        engine_alias="exp4",
        game=valid_game,
        stored_replay={"stored": True},
        trusted_replays=20,
        pending_checkpoint_targets=pending,
    )


def test_stage_game_win_rates_include_post_twenty_extra_normal_games():
    module = _load_validation_module()
    games = []
    outcomes = ["black"] * 10 + ["white"] * 5 + [None] * 5 + ["black"] * 3 + ["white"] * 2
    for index, winner_color in enumerate(outcomes, start=1):
        games.append(
            {
                "index": index,
                "category": "valid",
                "human_side": "white",
                "winner_color": winner_color,
                "stored_replay": {"collection_tier": "trusted"},
            }
        )

    rows = module._stage_game_win_rates(games, autorun_threshold=10)

    assert module.TOTAL_GAMES == 30
    assert module.VALID_GAMES == 25
    assert [row["stage"] for row in rows] == ["0-10", "10-20", "20-25"]
    assert all(row["basis"] == "trusted_valid_games_only" for row in rows)
    assert all(row["invalid_games_excluded"] is True for row in rows)
    assert rows[0]["normal_games"] == 10
    assert rows[0]["wins"] == 10
    assert rows[1]["normal_games"] == 10
    assert rows[1]["losses"] == 5
    assert rows[1]["draws"] == 5
    assert rows[1]["win_rate"] == 0.0
    assert rows[1]["win_rate_delta_from_previous_stage"] == -1.0
    assert rows[2]["normal_games"] == 5
    assert rows[2]["wins"] == 3
    assert rows[2]["win_rate"] == 0.6
    assert rows[2]["win_rate_delta_from_previous_stage"] == 0.6


def test_stage_win_rate_drop_marks_catastrophic_regression():
    module = _load_validation_module()
    summary = {
        "stage_game_win_rates": [
            {"stage": "0-10", "win_rate": 0.5},
            {"stage": "10-20", "win_rate": 0.2},
            {"stage": "20-25", "win_rate": 0.6},
        ],
        "before_after_eval": {"benchmark_before": {"skipped": True}, "benchmark_after": {"skipped": True}, "checkpoints": []},
    }

    stability = module._stability_summary(summary)

    assert stability["stage_win_rate_drop_10_20_vs_0_10"] == 0.3
    assert stability["stage_catastrophic_regression"] is True
    assert stability["catastrophic_regression"] is True


def test_deterministic_strength_gate_blocks_regression_without_using_game_benchmark():
    module = _load_validation_module()
    snapshots = [
        {"model_label": "baseline", "model_hash": "base", "aggregate": {"overall_deterministic_score": 0.8, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0, "category_score": {"mistake_retention": {"score": 1.0}}}},
        {"model_label": "checkpoint@10", "model_hash": "c10", "aggregate": {"overall_deterministic_score": 0.8, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0, "category_score": {"mistake_retention": {"score": 1.0}}}},
        {"model_label": "checkpoint@20", "model_hash": "c20", "aggregate": {"overall_deterministic_score": 0.75, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0, "category_score": {"mistake_retention": {"score": 1.0}}}},
        {"model_label": "final", "model_hash": "final", "aggregate": {"overall_deterministic_score": 0.6, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0, "category_score": {"mistake_retention": {"score": 1.0}}}},
    ]

    report = module._deterministic_strength_report(snapshots)

    assert report["passed"] is False
    assert "final deterministic score regressed below baseline" in report["reasons"]
    assert "final deterministic score regressed beyond checkpoint@20 threshold" in report["reasons"]


def test_stochastic_benchmark_hash_perft_and_runtime_do_not_release_promotion():
    module = _load_validation_module()
    summary = {
        "engine_alias": "exp2",
        "replay_summary": {"trusted_replays": module.VALID_GAMES, "quarantine_replays": module.INVALID_GAMES},
        "dataset_integrity": {"contaminated_rows": 0, "duplicate_ratio": 0.0, "invalid_fen": 0, "illegal_moves": 0, "side_mismatch": 0, "short_resign_games": 0},
        "poison_detection": {"forced_repetition_patterns": 0, "intentional_blunders": 0, "engine_copy_suspected": 0, "suspicious_resign_rate": 0.0},
        "stability": {"catastrophic_regression": False},
        "before_after_eval": {
            "benchmark_before": {"skipped": True, "reason": "stochastic_auxiliary_disabled"},
            "benchmark_after": {"skipped": True, "reason": "stochastic_auxiliary_disabled"},
            "checkpoints": [
                {
                    "trusted_count": 10,
                    "trusted_replays": 10,
                    "hash_changed": True,
                    "model_hash_changed": True,
                    "previous_model_hash": "before",
                    "new_model_hash": "after",
                    "pre_checkpoint_model_sha256": "before",
                    "post_checkpoint_model_sha256": "after",
                    "ineffective_training": False,
                    "mistake_retention_probe": {"learning_signal": True},
                }
            ],
        },
        "deterministic_strength_snapshot": {"supported": True, "skipped": False, "passed": False, "reasons": ["deterministic fixture failed"], "final": {"illegal_rate": 0.0, "blunder_avoid_rate": 1.0}},
        "stochastic_auxiliary_benchmark": {"skipped": True, "strength_evidence": False},
        "perft": {"strength_evidence": False},
        "runtime_metrics": {"train_seconds": 1.0},
        "engine_verdict": "PASS",
    }

    gate = module._promotion_gate_summary(summary)

    assert gate["passed"] is False
    assert "deterministic strength gate failed: deterministic fixture failed" in gate["reasons"]
    assert not any("stochastic_auxiliary_disabled" in reason for reason in gate["reasons"])


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
                    "trusted_count": 10,
                    "trusted_replays": 10,
                    "started_at": "2026-05-09T00:00:10+00:00",
                    "finished_at": "2026-05-09T00:00:14+00:00",
                    "duration_seconds": 4.0,
                    "dataset_hash": "sha256:datasetfixture",
                    "previous_model_hash": "before",
                    "new_model_hash": "after",
                    "hash_changed": True,
                    "pre_checkpoint_model_sha256": "before",
                    "post_checkpoint_model_sha256": "after",
                    "benchmark_skipped": True,
                    "benchmark_skip_reason": skip_reason,
                    "gate_decision": {"passed": False, "reasons": [f"benchmark skipped: {skip_reason}"]},
                    "mistake_retention_probe": {
                        "probe_case_id": "game:7:ply:3:e2e4",
                        "before_move": "g1f3",
                        "after_move": "g1f3",
                        "avoided_same_error": False,
                        "learning_signal": False,
                        "learning_signal_reason": "after model repeated the same wrong move",
                        "human_explanation": "目前沒有足夠證據證明 retrain 改善了該錯誤，因為 after model 仍重複同一錯誤。",
                    },
                }
            ],
        },
        "deterministic_strength_snapshot": {
            "supported": True,
            "skipped": False,
            "passed": False,
            "reasons": ["final deterministic score regressed below baseline"],
            "regression_vs_baseline": -0.2,
            "regression_vs_checkpoint10": -0.1,
            "regression_vs_checkpoint20": -0.1,
            "score_table": [
                {"model_label": "baseline", "model_hash": "before", "overall_deterministic_score": 0.8, "top1_correct_rate": 0.8, "top3_contains_rate": 0.8, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0},
                {"model_label": "checkpoint@10", "model_hash": "after", "overall_deterministic_score": 0.6, "top1_correct_rate": 0.6, "top3_contains_rate": 0.6, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0},
                {"model_label": "final", "model_hash": "after", "overall_deterministic_score": 0.6, "top1_correct_rate": 0.6, "top3_contains_rate": 0.6, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0},
            ],
            "final": {"overall_deterministic_score": 0.6, "top1_correct_rate": 0.6, "top3_contains_rate": 0.6, "illegal_rate": 0.0, "blunder_avoid_rate": 1.0, "category_score": {"mistake_retention": {"score": 0.5, "count": 1, "top1_correct_rate": 0.5, "top3_contains_rate": 0.5, "illegal_rate": 0.0, "blunder_rate": 0.0}}},
        },
        "stochastic_auxiliary_benchmark": {
            "purpose": "sanity signal only; not primary promotion evidence",
            "strength_evidence": False,
            "skipped": True,
            "skip_reason": skip_reason,
        },
        "perft": {"purpose": "move generation correctness only; not strength evidence", "strength_evidence": False, "skipped": True, "reason": "fixture"},
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
    assert "deterministic strength gate failed: final deterministic score regressed below baseline" in engine_json["promotion_gate"]["reasons"]
    assert any("mistake retention probe failed" in reason for reason in engine_json["promotion_gate"]["reasons"])
    assert "illegal moves detected in dataset" in engine_json["promotion_gate"]["reasons"]
    assert "forced repetition poison signal exceeded threshold" in engine_json["promotion_gate"]["reasons"]
    assert "## Can This Model Be Promoted?" in root_md
    assert "## Can This Model Be Promoted?" in engine_md
    assert "Stochastic Auxiliary Game Benchmark" in root_md
    assert "Stochastic Auxiliary Game Benchmark" in engine_md
    assert "strength_evidence: `False`" in engine_md
    assert "目前沒有足夠證據證明 retrain 改善了該錯誤" in engine_md
    assert module._report_consistency_issues(root_json, [engine_json], root_md, {"exp2": engine_md}) == []
