import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "games" / "chess_exp4_guarded_overlay_targeted_replay.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("exp4_guarded_overlay_targeted_replay_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exp4_guarded_overlay_targeted_replay_blocks_zero_margin_ordinary_override(tmp_path):
    module = _load_module()
    audit_json = tmp_path / "audit.json"
    audit_json.write_text(
        json.dumps(
            {
                "unsafe_rows": [
                    {
                        "trusted_count": 10,
                        "split": "unseen",
                        "case_id": "unsafe_e_pawn",
                        "fen": "rnbqkbnr/1ppppppp/p7/8/8/N4N2/PPPPPPPP/R1BQKB1R b KQkq - 1 2",
                        "side": "black",
                        "expected_move": "e7e5",
                        "baseline_move": "e7e5",
                        "final_move": "d7d5",
                        "baseline_correct": True,
                        "final_correct": False,
                        "unsafe_override": True,
                        "semantic_class": "e_pawn_central_break",
                        "difficulty": "easy",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = module.replay_unsafe_rows(audit_json)

    assert report["unsafe_rows_total"] == 1
    assert report["blocked_after_guard_tightening"] == 1
    assert report["still_unsafe"] == 0
    assert report["regression_rows_after_guard"] == 0
    assert report["baseline_selected_count"] == 1
    assert report["final_selected_count"] == 0
    assert report["guard_reason_after_counts"] == {"ordinary_runtime_margin_insufficient": 1}
    assert report["passed"] is True


def test_exp4_guarded_overlay_targeted_replay_writes_artifacts(tmp_path):
    module = _load_module()
    audit_json = tmp_path / "audit.json"
    audit_json.write_text(json.dumps({"unsafe_rows": []}), encoding="utf-8")
    output_json = tmp_path / "replay.json"
    output_md = tmp_path / "replay.md"

    assert module.main(["--audit-json", str(audit_json), "--output-json", str(output_json), "--output-md", str(output_md)]) == 0

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    md = output_md.read_text(encoding="utf-8")
    assert payload["source"] == "exp4_25_guarded_overlay_targeted_replay"
    assert payload["promotion"] is False
    assert "unsafe_rows_total" in md


def test_exp4_guarded_overlay_parking_status_is_explicit(monkeypatch):
    from services.games.chess_pv_guarded_overlay import exp4_guarded_overlay_parking_status

    monkeypatch.delenv("HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY", raising=False)

    status = exp4_guarded_overlay_parking_status()

    assert status["exp4_guarded_overlay_status"] == "parked_not_promotion_ready"
    assert status["promotion"] is False
    assert status["runtime_mutated"] is False
    assert status["retrain_attempted"] is False
    assert status["broad_sanity_unsafe_override_count"] == 26
    assert status["unsafe_guard_reason"] == "runtime_static_and_rule_guard_passed"
    assert status["production_default"] == "disabled"
    assert status["enabled_now"] is False
