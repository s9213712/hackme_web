# exp5_11a suspicious-rate audit

Date: 2026-05-12

## Goal

Audit `exp5_10` suspicious rows without retraining, changing the candidate, or touching runtime production.

Question:

- Is `suspicious_rate_nonzero` a true model risk?
- Or is it a fixture / audit false positive?
- Or is it label-quality noise?

## Inputs

- source summary: `<chess_results>/exp5_10_production_readiness/summary.json`
- source cases: `<chess_results>/exp5_10_production_readiness/exp5_10_benchmark_cases.jsonl`
- candidate: `<chess_results>/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- baseline: `<repo>/services/games/models/chess_experiment_5_nnue.json`

## Artefacts

- audit root: `<chess_results>/exp5_11a_suspicious_audit/`
- audit rows: `<chess_results>/exp5_11a_suspicious_audit/suspicious_rows.jsonl`
- summary json: `<chess_results>/exp5_11a_suspicious_audit/summary.json`
- summary md: `<chess_results>/exp5_11a_suspicious_audit/SUMMARY.md`

## Result

After fixing the two invalid rook mate smoke fixtures and rerunning exp5_10, the current suspicious audit is clean:

| metric | value |
|---|---:|
| suspicious_row_count | 0 |
| true_model_risk_count | 0 |
| fixture_or_audit_false_positive_count | 0 |
| label_quality_issue_count | 0 |
| needs_manual_review_count | 0 |

Classification counts:

```json
{}
```

Reason counts:

```json
{}
```

## Pre-fix suspicious rows

| case | class | category | label | baseline | candidate | initial status | after status |
|---|---|---|---|---|---|---|---|
| `exp5_10_smoke_mate_in_1_rook_white` | fixture/audit false positive | smoke / mate_in_1 | clean | `g7g8` | `g7g8` | `STATUS_OPPOSITE_CHECK` | `STATUS_NO_BLACK_KING` |
| `exp5_10_smoke_mate_in_1_rook_black` | fixture/audit false positive | smoke / mate_in_1 | clean | `g2g1` | `g2g1` | `STATUS_OPPOSITE_CHECK` | `STATUS_NO_WHITE_KING` |

## Interpretation

The original suspicious rows were invalid smoke fixtures:

- The initial FEN already has the opposite side in check while it is not that side's turn.
- Python-chess therefore allows a pseudo-legal king-capture-like move in an invalid board state.
- After the candidate move, the board has `STATUS_NO_BLACK_KING` or `STATUS_NO_WHITE_KING`.
- The stalemate flag is a consequence of the invalid post-move board, not a clean model decision in a valid chess position.

The runner now uses valid K+R mate-in-1 fixtures:

- white: `7k/8/6K1/8/8/8/8/R7 w - - 0 1`, expected mate move `a1a8`
- black: `r7/8/8/8/8/6k1/8/7K b - - 0 1`, expected mate move `a8a1`

The corrected exp5_10 rerun has `suspicious_rate=0.0` and `suspicious_matches=[]`.

## Production implication

This audit removes `suspicious_rate_nonzero` as a current production blocker, but it does not make the candidate production-ready.

Production is still blocked by:

- `quiet_positional_clean_regression`
- thin expanded overall delta (`+0.007407`)

Status remains:

```text
stage_candidate   = true
shadow_candidate  = true
production        = hold
```

## Next step

Proceed to `exp5_11b` quiet positional regression isolation. The invalid rook mate smoke FENs have already been replaced and retested.
