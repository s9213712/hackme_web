import json
from pathlib import Path

from scripts.games.chess_exp5_opening_label_audit import run_audit


def _write_summary(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"benchmark": {"rows": rows}}, ensure_ascii=False), encoding="utf-8")


def test_exp5_opening_label_audit_separates_questionable_from_clean_regression(tmp_path):
    summary_path = tmp_path / "summary.json"
    output_dir = tmp_path / "audit"
    rows = [
        {
            "id": "questionable_opening_fail",
            "category": "opening",
            "subcategory": "toy",
            "label_quality": "questionable",
            "fen": "4k3/8/8/8/8/8/4q3/4K3 w - - 0 1",
            "side": "white",
            "teacher_move": "e1e2",
            "expected_uci_any": ["e1e2"],
            "baseline_move": "e1e2",
            "candidate_move": "e1d1",
            "baseline_pass": True,
            "candidate_pass": False,
            "candidate_regressed": True,
            "candidate_reasons": ["unexpected_move"],
        },
        {
            "id": "clean_opening_regression",
            "category": "opening",
            "subcategory": "toy",
            "label_quality": "clean",
            "fen": "4k3/8/8/8/8/8/4q3/4K3 w - - 0 1",
            "side": "white",
            "teacher_move": "e1e2",
            "expected_uci_any": ["e1e2"],
            "baseline_move": "e1e2",
            "candidate_move": "e1d1",
            "baseline_pass": True,
            "candidate_pass": False,
            "candidate_regressed": True,
            "candidate_reasons": ["unexpected_move"],
        },
    ]
    _write_summary(summary_path, rows)

    result = run_audit(summary_path, output_dir)

    assert result["opening_rows"] == 2
    assert result["questionable_rows"] == 1
    assert result["questionable_rows_block_production"] is False
    assert result["clean_true_opening_regressions"] == 1
    assert result["production_blocker"] is True
    audited_rows = [
        json.loads(line)
        for line in Path(result["artifacts"]["opening_label_audit_jsonl"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["case_id"]: row for row in audited_rows}
    assert by_id["questionable_opening_fail"]["classification"] == "questionable_label_do_not_gate"
    assert by_id["clean_opening_regression"]["classification"] == "true_opening_regression"
