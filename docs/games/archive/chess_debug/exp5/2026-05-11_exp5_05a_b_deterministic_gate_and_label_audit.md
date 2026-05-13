# exp5_05a + exp5_05b — deterministic gate & teacher-label audit

Date: 2026-05-11
Status: `blocked`. `stage_candidate = shadow_candidate = production_promote = false`.
Predecessors: `2026-05-11_exp5_04_learning_capacity_ablation.md`,
`2026-05-11_exp5_next_learning_strength_plan.md`.

## Why exp5_05 was needed

`exp5_04` showed:
- `train_agreement_delta = 0.0` for HN-only cells, `+0.0833` for epochs-only / both.
- `score_delta` of +0.05 ~ +0.08 across cells, never clearing the 0.70 gate.
- `baseline_score` *drifted across seeds within the same cell* (e.g. `[0.594, 0.641, 0.641]`),
  even though the baseline model is identical across seeds.

That gave two hypotheses to test before any further training-knob tuning:

1. Is the strength gate itself a deterministic measurement instrument?
2. Is the teacher distill set a clean training signal?

This document answers both.

## exp5_05a — fixed-depth deterministic gate

### What changed

`services/games/chess_nnue.py:29-39` — added three new search profiles that
share each timed profile's depth + quiescence but drop `time_budget_ms`:

```python
"fixed_depth_fast":     {"depth": 1, "quiescence_depth": 1, "time_budget_ms": None}
"fixed_depth_balanced": {"depth": 2, "quiescence_depth": 2, "time_budget_ms": None}
"fixed_depth_strong":   {"depth": 3, "quiescence_depth": 4, "time_budget_ms": None}
```

`search_best_move` already honours `time_budget_ms=None` by setting `deadline=None`
and skipping the `_check_deadline` raise (see `chess_search.py:435-442`). The existing
iterative-deepening loop completes to `max_depth` and returns. No code change to the
search itself was needed.

### Determinism check (5× same-model repeats, 60-case strength set)

| profile | model | 5-run scores | std | per-run move-diff count |
|---|---|---|---|---|
| `fixed_depth_strong` | baseline | 0.683 / 0.683 / 0.683 / 0.683 / 0.683 | **0.0** | **0** |
| `fixed_depth_strong` | candidate `e1_t4` | 0.667 / 0.667 / 0.667 / 0.667 / 0.667 | **0.0** | **0** |
| `strong` (timed, 1100 ms) | baseline | 0.633 / 0.583 / 0.617 / 0.617 / 0.600 | 0.017 | **4** |
| `strong` (timed, 1100 ms) | candidate `e1_t4` | 0.667 / 0.667 / 0.667 / 0.667 / 0.667 | 0.0 | 0 |

`fixed_depth_strong` is **bit-for-bit reproducible** on both models. Timed
`strong` has a ±1.5-case noise floor on the baseline. Importantly: **the
candidate happens to be stable under timed strong (no time pressure with its
weights), but the baseline gets penalised**, so `score_delta` looks inflated.

### `repeated_case_differences` (which cases drift under timed `strong`)

5-run side-by-side, only listing cases where the chosen move was not unanimous:

| case_id | baseline 5 runs | candidate (e1_t4) 5 runs |
|---|---|---|
| `exp5_02_case_022` | `a5a4 f8a3 a5a4 a5a4 a5a4` | `a5a4 f8a3 a5a4 a5a4 a5a4` |
| `exp5_02_case_033` | `a7a5 a7a6 a7a5 a7a5 a7a6` | `a7a5 a7a6 a7a5 a7a5 a7a5` |
| `exp5_02_case_036` | `a7a5 a7a6 a7a5 a7a5 a7a5` | (stable) |
| `exp5_02_case_042` | `a5a4 d5c4 d5c4 d5c4 d5c4` | `d5c4 d5c4 a5a4 a5a4 a5a4` |
| `exp5_02_case_058` | `b2b3 b2b3 f1e2 b2b3 f1e2` | `b2b3 b2b3 f1e2 b2b3 b2b3` |
| `exp5_02_case_059` | (stable) | `f1e2 b2b3 f1e2 f1e2 f1e2` |

All drifting moves are near-equivalent quiet positional choices (alternative
a-pawn pushes, alternative bishop developments, etc.) where the iterative
deepening loop reaches a different completed depth depending on whether the
1100 ms deadline fires. Under `fixed_depth_strong` the search always completes
to depth 3 + 4-ply quiescence and the chosen move is unanimous across all 5
runs (move_diff_count = 0 for both baseline and candidate).

### What the deterministic gate actually says

| measurement | timed `strong` (exp5_04 v2, mean) | `fixed_depth_strong` (exp5_05a) |
|---|---|---|
| baseline_score | ~0.625 (range 0.583–0.641) | **0.683** |
| candidate_score (e1_t4) | ~0.6875 | **0.667** |
| score_delta | **+0.0625** (apparent improvement) | **−0.0167** (real regression) |

**The exp5_04 gate gain was largely an artifact of timed-strong noise pulling baseline_score down.**
Under a deterministic gate, the best exp5_04 candidate is **slightly weaker** than
baseline (40/60 vs 41/60).

This does not mean training did nothing — `train_agreement_delta` rose in
`e8_t0` and `e8_t4` — but it does mean we cannot claim a gate improvement.

### Recommendation

Switch the repeatability gate's default `--search-profile` to `fixed_depth_strong`
for any future promotion attempt. Keep `strong` available for benchmarking, but
flag any conclusion based on a timed profile as **auxiliary, not primary
evidence**.

This recommendation has NOT yet been wired into
`scripts/games/chess_exp5_repeatability_gate.py` — the script still defaults to
`strong`. Leaving that change for exp5_05c so it lands together with the clean
distill set.

## exp5_05b — teacher distill label audit

### What changed

`scripts/games/chess_exp5_teacher_distill.py` — every accepted row now also
emits:

- `teacher_top3`, `teacher_top5` (1-ply static-eval ranking; **NOT** a deep
  alpha-beta teacher ranking)
- `teacher_top_k_method = "one_ply_static_eval"`, `static_teacher_top_k = true`
  (so consumers don't mistake this for search-strength evidence)
- `teacher_eval_cp`
- `baseline_top1`, `baseline_top1_score`, `baseline_teacher_score`,
  `baseline_teacher_rank` (from `rank_experiment_nnue_policy_moves` —
  pure static enumerate-and-score, no search)
- `baseline_policy_gap_cp` = `baseline_top1_score − baseline_teacher_score`
- `label_quality` ∈ {`clean`, `review`, `questionable`}
- `label_quality_reason` (one of:
  `baseline_top1_matches_teacher`,
  `questionable_by_baseline_policy_gap`,
  `baseline_policy_gap_in_review_window`,
  `baseline_policy_gap_within_clean_window`)
- `questionable_by_baseline_policy_gap` (boolean)

New CLI knobs:

| flag | default | purpose |
|---|---|---|
| `--baseline-model-path` | bundled exp5 baseline | Model used for `baseline_top1/score` probe |
| `--baseline-probe-profile` | `fixed_depth_fast` | Forced to a fixed-depth profile so label-quality audit cannot inherit time-budget noise |
| `--label-quality-far-above-cp` | 250.0 | `>=` this → `questionable` |
| `--label-quality-review-cp` | 80.0 | `>=` this and `<` far-above → `review` |
| `--teacher-top-k` | 5 | K for `teacher_top3`/`teacher_top5` |
| `--drop-questionable` | off | When set, `questionable` rows are excluded from the output JSONL but **still recorded in the audit JSONL** with `included_in_output=false` and `drop_reason="questionable_by_baseline_policy_gap"` |
| `--audit-jsonl` | (off) | Per-row audit destination |

The script avoids strong claims about the *teacher* — the gap is named
`baseline_policy_gap_cp` (NOT "teacher wrong"), and the label is
`questionable_by_baseline_policy_gap` (NOT "label_wrong"). A large gap means the
cheap NNUE eval cannot justify the teacher's choice, not that the teacher
itself is incorrect.

### Dry-run on the existing 60-row exp5_02 distill (no_drop variant)

```
raw_rows                                                = 60
output_rows                                             = 60
clean_rows                                              = 4
review_rows                                             = 8
questionable_rows                                       = 48
clean_ratio                                             = 0.067
questionable_by_baseline_policy_gap_count               = 48
teacher_top3_does_not_contain_teacher_move_count        = 40   <-- 67% of rows
missing_teacher_top3_count                              = 40
baseline_policy_gap_avg                                 = 1419.55 cp
baseline_policy_gap_max                                 = 20624.0 cp
far_above_threshold_cp                                  = 250.0
review_threshold_cp                                     = 80.0
teacher_top_k_method                                    = one_ply_static_eval
baseline_probe_profile                                  = fixed_depth_fast
```

### Drop variant (`--drop-questionable`)

```
accepted_samples       = 12   (4 clean + 8 review)
skipped_rows           = 48
rejected_reasons       = {'label_questionable_dropped': 48}
clean_distill_sha256   = 562616b68822e529affe93397415147715fdd6befd7693e5b418107dac14ae14
audit_jsonl rows       = 60  (all 60 still recorded; 48 with included_in_output=false)
```

A sample dropped row's audit entry (excerpt):

```json
{
  "fen": "rnbqkbnr/pppp1ppp/8/4p3/8/PP6/2PPPPPP/RNBQKBNR b KQkq - 0 2",
  "move_uci": "a7a5",
  "baseline_top1": "f8a3",
  "baseline_top1_score": 1307.0,
  "baseline_teacher_score": 42.0,
  "baseline_teacher_rank": 20,
  "baseline_policy_gap_cp": 1265.0,
  "label_quality": "questionable",
  "label_quality_reason": "questionable_by_baseline_policy_gap",
  "questionable_by_baseline_policy_gap": true,
  "included_in_output": false,
  "drop_reason": "questionable_by_baseline_policy_gap"
}
```

### What this tells us about the exp5_02 distill set

- Only **4 / 60 rows** have `baseline_top1 == teacher_move`. The cheap NNUE eval and
  the teacher agree on a single best move in 6.7% of positions.
- **40 / 60 rows** have a teacher move that the teacher's *own* 1-ply static eval
  doesn't even rank in its top-3. This is a strong indicator that the
  teacher's choices in this dataset are **not justified by static positional
  evaluation** — they may depend on deeper tactics, or they may be
  artifacts of the `exp18_train` source from a prior experiment.
- `baseline_policy_gap_avg = 1419 cp` per row, max = 20624 cp. The teacher and
  the baseline disagree at scales far beyond what 60 single-pass weight
  updates can move.

The exp5_04 finding `candidate_score_far_above_teacher_count = 48/60` (with
threshold 250 cp) is **exactly reproduced** here as
`questionable_by_baseline_policy_gap_count = 48`. The two audits agree.

### Why this matters for promotion

If 80% of the training rows are positions where the cheap eval cannot follow
the teacher, then pushing the candidate harder (more epochs, more HN) is
training the model to *override its own evaluator on label noise*. That is
why `e8_t4` (the most aggressive cell in exp5_04) had the worst gate Δ even
though its `train_agreement_delta` was best — it was learning to satisfy
arbitrary labels at the expense of the cases the gate actually scores.

## Combined verdict

| tier | result | reason |
|---|---|---|
| `blocked` | **true** | label-quality audit shows ≤ 7% clean rows in the exp5_02 distill set |
| `stage_candidate` | **false** | deterministic gate shows `score_delta = -0.0167`, i.e. candidate is slightly worse than baseline |
| `shadow_candidate` | **false** | repeatability_pass requires `pass_count == run_count` |
| `production_promote` | **false** | requires clean labels + shadow_pass + train-learning visible + smoke + held-out |

The exp5_04 "improvement" reading was a measurement artefact. Real
`score_delta` under a deterministic gate is **slightly negative**. The
candidate is not safe to stage.

## Files touched (this round)

- `services/games/chess_nnue.py` (new fixed_depth_* profiles)
- `scripts/games/chess_exp5_teacher_distill.py` (label-quality audit, drop filter)
- `docs/games/chess_debug/exp5/2026-05-11_exp5_05a_b_deterministic_gate_and_label_audit.md` (this file)

## Artifacts

- `chess_results/exp5_05a_fixed_depth_gate/`
  - `baseline_fdstrong/`, `baseline_strong_timed/`,
    `candidate_e1_t4_fdstrong/`, `candidate_e1_t4_timed/` — each with 5 strength-gate runs
- `chess_results/exp5_05b_label_cleanup/`
  - `inputs/fens_exp5_02.jsonl` — the 60 FENs extracted from exp5_04 distill input
  - `dry_run_no_drop/{stdout.json, audit.jsonl, distill.jsonl, stderr.log}`
  - `dry_run_drop/{stdout.json, audit.jsonl, distill_clean.jsonl, stderr.log}`
  - `dry_run_drop/distill_clean.jsonl` — the 12-row label-cleaned distill set
    (sha256 `562616b6…`)

## Next step: exp5_05c

With (a) gate now deterministic and (b) label-cleanup tools in place, the
remaining open question is whether *any* learning capacity setting on a
cleaned distill set produces a visible, real gate gain — not a timed-noise
artefact. exp5_05c proposes:

1. Wire `chess_exp5_repeatability_gate.py` to default to `fixed_depth_strong`
   so any further comparison is noise-free.
2. Re-distill using the (4 + 8 = 12 row) clean+review subset, weighting clean
   higher than review.
3. Re-run the same four-cell `epochs ∈ {1,8} × topK ∈ {0,4}` grid plus the
   middle point `epochs=4, topK=2`. With only 12 training rows the runs will
   be much faster.
4. The promotion bar is now **score_delta > 0 under fixed_depth_strong**, not
   under timed strong. We additionally require `train_agreement_delta > 0`,
   `regression_rate ≤ 0.10`, and `smoke_score = 1.0`.

exp5_05c has NOT been executed in this commit — only exp5_05a and exp5_05b.
