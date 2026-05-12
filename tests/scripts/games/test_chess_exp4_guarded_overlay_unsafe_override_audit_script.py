import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "games" / "chess_exp4_guarded_overlay_unsafe_override_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("exp4_guarded_overlay_audit_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(case_id, fen, expected, top1, *, side="black", semantic="e_pawn_central_break"):
    return {
        "case_id": case_id,
        "fen": fen,
        "side": side,
        "expected_move": expected,
        "expected_is_top1": top1 == expected,
        "expected_in_top3": expected in [top1],
        "top1": top1,
        "top3": [top1],
        "expected_semantic": semantic,
    }


def _case(case_id, fen, expected, *, split="validation", semantic="e_pawn_central_break"):
    return {
        "case_id": case_id,
        "fen": fen,
        "side": "black" if " b " in fen else "white",
        "expected_move": expected,
        "expected_semantic": semantic,
        "semantic_class": semantic,
        "variant_difficulty": "easy",
        "variant_split": split,
        "flank_reason_tag": "bad_random_flank_push",
        "normalized_fen_hash": f"hash-{case_id}",
    }


def test_exp4_guarded_overlay_audit_extracts_unsafe_rows_and_clusters(tmp_path):
    module = _load_module()
    result_dir = tmp_path / "result"
    checkpoint_dir = result_dir / "exp4" / "checkpoints" / "10"
    checkpoint_dir.mkdir(parents=True)
    engine_dir = result_dir / "exp4"
    summary = {
        "promotion_gate": {
            "guarded_overlay_broad_sanity_gate": {
                "passed": False,
                "reasons": ["guarded overlay sanity unsafe override at trusted=10"],
            }
        },
        "exp4_actual_runtime_guarded_overlay": {
            "baseline_score": 0.8693,
            "final_score": 0.8693,
            "actual_runtime_guarded_score": 0.9231,
            "delta_vs_baseline": 0.0538,
            "unsafe_override_count": 0,
            "simulator_selected_mismatch_count": 0,
        },
    }
    (engine_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    unsafe_fen = "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq - 0 1"
    safe_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1"
    checkpoint = {
        "trusted_count": 10,
        "sanity_learning_probe": {
            "seen_variants": {"before": [], "after": [], "cases": [], "raw_policy_after": []},
            "unseen_variants": {
                "before": [
                    _row("unsafe_case", unsafe_fen, "e7e5", "e7e5"),
                    _row("positive_case", safe_fen, "d7d5", "e7e5"),
                ],
                "after": [
                    _row("unsafe_case", unsafe_fen, "e7e5", "d7d5"),
                    _row("positive_case", safe_fen, "d7d5", "d7d5"),
                ],
                "cases": [
                    _case("unsafe_case", unsafe_fen, "e7e5"),
                    _case("positive_case", safe_fen, "d7d5"),
                ],
                "raw_policy_after": [
                    {"case_id": "unsafe_case", "raw_policy_top1": "d7d5", "expected_rank": 2},
                    {"case_id": "positive_case", "raw_policy_top1": "d7d5", "expected_rank": 1},
                ],
            },
        },
    }
    (checkpoint_dir / "before_after_eval.json").write_text(json.dumps(checkpoint), encoding="utf-8")

    audit = module.build_audit(result_dir)

    assert audit["promotion"] is False
    assert audit["retrain_attempted"] is False
    assert audit["runtime_mutated"] is False
    assert audit["unsafe_override_count"] == 1
    assert audit["regression_row_count"] == 1
    assert audit["unsafe_by_split"] == {"unseen": 1}
    assert audit["checkpoint_summary"][0]["trusted_count"] == 10
    assert audit["unsafe_rows"][0]["case_id"] == "unsafe_case"
    assert audit["unsafe_rows"][0]["split"] == "unseen"
    assert "baseline_already_correct_but_overlay_replaced_it" in audit["unsafe_rows"][0]["root_causes"]
    assert audit["root_cause_counts"]["baseline_already_correct_but_overlay_replaced_it"] == 1


def test_exp4_guarded_overlay_audit_writes_json_and_markdown(tmp_path):
    module = _load_module()
    result_dir = tmp_path / "result"
    checkpoint_dir = result_dir / "exp4" / "checkpoints" / "10"
    checkpoint_dir.mkdir(parents=True)
    (result_dir / "exp4" / "summary.json").write_text(
        json.dumps({"promotion_gate": {}, "exp4_actual_runtime_guarded_overlay": {}}),
        encoding="utf-8",
    )
    (checkpoint_dir / "before_after_eval.json").write_text(
        json.dumps({"trusted_count": 10, "sanity_learning_probe": {"seen_variants": {}, "unseen_variants": {}}}),
        encoding="utf-8",
    )
    output_json = tmp_path / "audit.json"
    output_md = tmp_path / "audit.md"

    assert module.main(["--result-dir", str(result_dir), "--output-json", str(output_json), "--output-md", str(output_md)]) == 0

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    md = output_md.read_text(encoding="utf-8")
    assert payload["source"] == "exp4_24_guarded_overlay_unsafe_override_audit"
    assert "promotion=false" in md
    assert "retrain_attempted=false" in md
