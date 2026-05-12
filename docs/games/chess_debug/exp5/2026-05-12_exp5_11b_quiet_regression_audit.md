# exp5_11b quiet positional regression audit

Date: 2026-05-12

## Goal

Audit the single `quiet_positional_clean_regression` blocker from exp5_10 without retraining, changing the candidate, or touching runtime production.

This round only reads:

- `/home/s92137/chess_results/exp5_10_production_readiness/summary.json`
- `/home/s92137/chess_results/exp5_10_production_readiness/exp5_10_benchmark_cases.jsonl`

## Artefacts

- audit root: `/home/s92137/chess_results/exp5_11b_quiet_regression_audit/`
- rows: `/home/s92137/chess_results/exp5_11b_quiet_regression_audit/quiet_regression_rows.jsonl`
- summary: `/home/s92137/chess_results/exp5_11b_quiet_regression_audit/summary.json`
- markdown summary: `/home/s92137/chess_results/exp5_11b_quiet_regression_audit/SUMMARY.md`

## Result

| metric | value |
|---|---:|
| quiet_clean_regression_count | 1 |
| true_model_regression_count | 0 |
| multi_good_scoring_issue_count | 1 |
| fixture_issue_count | 0 |
| label_quality_issue_count | 0 |
| needs_manual_review_count | 0 |

Classification counts:

```json
{
  "multi_good_scoring_issue": 1
}
```

## Regression row

| field | value |
|---|---|
| case_id | `exp5_09_bench_d400404a65f3` |
| fen | `8/6pp/5pk1/8/8/5PK1/6PP/8 w - - 0 1` |
| side | `white` |
| subcategory | `k_and_p_symmetric` |
| label_quality | `clean` |
| teacher_move | `g3f2` |
| recorded teacher_top3 | `g3f2`, `f3f4`, `g3f4` |
| recorded teacher_top5 | `g3f2`, `f3f4`, `g3f4`, `g3g4`, `g3h4` |
| baseline_move | `f3f4` |
| candidate_move | `h2h4` |
| baseline_pass | `true` |
| candidate_pass | `false` |
| baseline_in_teacher_top3/top5 | `true` / `true` |
| candidate_in_teacher_top3/top5 | `false` / `false` |
| board status | `STATUS_VALID` |
| teacher_static_score | `44` |
| baseline_static_score | `32` |
| candidate_static_score | `28` |
| candidate_static_rank | `7` |
| static_eval_delta_candidate_vs_teacher | `-16` |
| static_eval_delta_candidate_vs_baseline | `-4` |
| classification | `multi_good_scoring_issue` |
| classification reason | `candidate_within_50cp_of_teacher_static_eval` |

## Interpretation

The regression is not a bad FEN and not an illegal-move fixture issue.

It is also not strong evidence of a true model regression:

- The candidate move is outside the recorded teacher top5, so the current gate marks it wrong.
- Under the same static teacher evaluator, the candidate move is only `16cp` below the teacher move.
- It is only `4cp` below the baseline move that passed.
- This is a quiet symmetric K+P position where several non-losing quiet moves are close.

So the blocker should be treated as a gate / label-audit problem, not as a reason to immediately train a repair candidate.

## Production implication

Current status remains:

```text
stage_candidate   = true
shadow_candidate  = true
production        = hold
```

Recommended blocker rewrite:

```text
replace quiet_positional_clean_regression
with quiet_positional_gate_label_audit_required
```

Production should still not be promoted until exp5_10 is rerun with the quiet positional gate accepting near-equivalent quiet moves or with the case re-labeled as multi-good.

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_quiet_regression_audit.py`
- `python3 scripts/games/chess_exp5_quiet_regression_audit.py`
- `git diff --check`

## Next step

Proceed to an exp5_11c gate-label fix:

- allow quiet positional cases to use a static-eval near-equivalence window, or
- explicitly mark this case as multi-good with `h2h4` included as acceptable, then
- rerun exp5_10 production-readiness validation.

Do not retrain before this gate/label issue is fixed.
