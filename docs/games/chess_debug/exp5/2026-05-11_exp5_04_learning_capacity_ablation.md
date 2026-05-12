# exp5_04 — learning capacity ablation

Date: 2026-05-11
Status: stage_candidate = false, shadow = false, production_promote = false (all four ablation cells)
Predecessor: `2026-05-11_exp5_next_learning_strength_plan.md`

## Why exp5_04 was needed

`exp5_03_repeatability_fix3` cleared the gate's safety floor but stalled at
`case_pass_rate = 0.6875 < 0.70` and — more importantly — `train_agreement_delta = 0.0`,
`margin_delta = -35.3 cp`, `retrain_effect_not_visible = true`. We could not say the
candidate had learned anything from the 60 distill rows; the small gate gain
(+0.046875) might have come from incidental mobility/material side-effects.

Diagnosis (see `services/games/chess_nnue.py:444-573`):

1. The trainer ran a **single pass** over the 60 replay rows. Each row only nudged the
   destination-square piece-square weight by ~25 cp. Sixty single updates were too weak
   to shift PVS top-1 decisions on the 64-case strength set.
2. Distill rows carried **no hard_negatives** (`[]`). The candidate's currently-preferred
   moves (b8c6, c8f5, b1c3, …) were never penalised, so their evaluator scores stayed
   well above the teacher's even after training.

## What changed

| File | Change |
|---|---|
| `services/games/chess_nnue.py:502-591` | `train_experiment_nnue_from_replay_samples` now accepts `epochs` (default 1, backwards-compatible). |
| `scripts/games/chess_exp5_dataset_train.py` | Adds `--epochs`, `--auto-hard-negative-topk`, `--hard-negative-source-model-path`, `--multi-good-margin-cp`, `--hard-negative-audit-path`. Auto-HN excludes `teacher_top3` and multi-good ties (`abs(candidate - teacher) ≤ margin`). Reports `hard_negative_injected_count` (newly added only), `hard_negative_preexisting_count`, `hard_negative_excluded_as_teacher_top3_count`, `hard_negative_excluded_as_multi_good_count`, `samples_missing_teacher_top3_count`, `candidate_score_far_above_teacher_count`. |
| `scripts/games/chess_exp5_repeatability_gate.py` | Forwards `--epochs`, `--auto-hard-negative-topk`, `--multi-good-margin-cp`; writes per-run `training_config` and `hard_negative_audit_summary` into the payload. |

Existing exp5 / training tests all still pass (22 passed).

## Ablation grid

Inputs (held constant across cells, 3 seeds 11/12/13 per cell):
- baseline model: `services/games/models/chess_experiment_5_nnue.json`
- distill / train rows: 60 (same shuffled file as exp5_03 fix3)
- strength cases: 60 cases + 4 auto-derived smoke rows = 64
- held-out: 24 (side-flipped from the strength cases, leakage-clean)
- gate threshold: `case_pass_rate ≥ 0.70`, `regression_rate ≤ 0.10`
- search_profile: `strong`

| cell | epochs | topK | pass | mean Δ | min Δ | max Δ | mean agreement_Δ | mean margin_Δ (cp) | improved/seed | regressed/seed | clean_only | smoke |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `e1_t0` (≈exp5_02) | 1 | 0 | 0/3 | +0.0625 | +0.0625 | +0.0625 | 0.0000 | −68.23 | 6.3 | 2.3 | 0.619 | 1.00 |
| `e8_t0` (epochs only) | 8 | 0 | 0/3 | +0.0573 | +0.0469 | +0.0625 | **+0.0667** | −112.92 | 6.7 | 3.0 | 0.643 | 0.75 |
| `e1_t4` (HN only) | 1 | 4 | 0/3 | **+0.0833** | +0.0781 | +0.0938 | 0.0000 | −323.98 | 7.3 | 2.0 | 0.643 | 1.00 |
| `e8_t4` (both) | 8 | 4 | 0/3 | +0.0469 | +0.0469 | +0.0469 | **+0.0833** | −467.88 | 6.0 | 3.0 | 0.619 | 1.00 |

(`e1_t4` and `e8_t4` were re-run as `*_v2` with the latest audit code; results stayed
within noise. The v2 means came in slightly lower because baseline_score itself drifts
between seeds — see "Noise" below — but the directional verdict is unchanged.)

### What the four cells say

- **epochs alone (e8_t0)** is what makes train-row learning *visible*:
  `candidate_teacher_agreement_on_train` lifts from 4/60 to 8/60
  (+0.0667 agreement_Δ). But gate Δ is flat-to-slightly-worse than the e1_t0
  baseline and smoke regresses to 0.75 — multi-epoch on 60 narrow rows
  starts to overfit and corrupts opening-style decisions.
- **HN alone (e1_t4)** is what flips top-1 on the gate cases best:
  `mean Δ = +0.0833`, `improved/seed = 7.3`, `regressed/seed = 2.0`. But
  train-row agreement stays at 0.0 — HN moves the **gate** without making the
  per-row teacher truly top-1 in training set.
- **Both (e8_t4)** shows the best `agreement_Δ` (+0.0833 = 9/60 train rows
  flip to teacher-top-1), but gate Δ shrinks to +0.0469 — the multi-epoch
  + HN combination over-pressures the model, eating clean gains while
  finally producing visible train-row learning.
- **Nothing clears the 0.70 gate** (best is 0.6875 = 44/64).

### Hard-negative audit (latest v2 runs, identical across both v2 cells)

```
auto_hard_negative_topk                       = 4
multi_good_margin_cp                          = 30.0
multi_good_margin_units                       = raw_policy_score (centipawn-scaled w/ move-order bonus)
raw_policy_score_scale                        = centipawn-ish
hard_negative_injected_count                  = 221     (newly added; preexisting NOT counted)
hard_negative_preexisting_count               = 0
hard_negative_excluded_as_multi_good_count    = 18
hard_negative_excluded_as_teacher_top3_count  = 0
hard_negative_overlap_with_teacher_top3_count = 0
samples_missing_teacher_top3_count            = 60     <-- ALL distill rows lack teacher_top3
samples_with_injection                        = 59 / 60
candidate_score_far_above_teacher_count       = 48     <-- 48/60 train rows have baseline top1 ≥ +250 cp above teacher
candidate_score_far_above_teacher_threshold_cp= 250.0
hard_negative_source_model_path               = baseline (services/games/models/chess_experiment_5_nnue.json)
```

### Training config evidence (cell_e8_t4_v2, seed 11)

```
epochs = 8 (epochs_actual=8)
auto_hard_negative_topk = 4
multi_good_margin_cp = 30.0
positive_updates       = 480   (=60 rows × 8 epochs)
hard_negative_updates  = 1768  (=221 HN × 8 epochs)
```

vs `cell_e1_t4_v2`: `positive_updates=60`, `hard_negative_updates=221`. The
multipliers prove epochs and HN both took effect.

### Train-row learning (cell_e8_t4_v2, seed 11)

```
baseline_teacher_agreement_on_train  = 0.0667 (4/60)
candidate_teacher_agreement_on_train = 0.1500 (9/60)
train_agreement_delta                = +0.0833
baseline_teacher_margin              = -1419.6 cp
candidate_teacher_margin             = -1885.8 cp
margin_delta                         = -466.3 cp  (more negative — see "Margin caveat" below)
retrain_effect_not_visible           = False (agreement_delta > 0)
```

### Margin caveat

`margin_delta` is **not** "teacher score got worse"; it is `top1_gap_after - top1_gap_before`
where `top1_gap = teacher_score - top1_score`. Once HN pushes baseline's old top-1 down
and a *new* alternative becomes top-1 with a fresh huge score, the gap widens even though
the teacher's score may have *also* moved up. For the 9 rows where the teacher actually
reached rank-1, the gap necessarily *did* close. So the negative aggregate `margin_delta`
co-exists with real positive learning on a minority of rows — which is exactly what
`train_agreement_delta` captures.

### Teacher-label sanity flag

`candidate_score_far_above_teacher_count = 48 / 60` means the baseline-rated top-1
move scores ≥ 250 cp above the teacher's move in 80% of the distill rows. With these
distill rows being side-flipped opening positions where the teacher consistently
suggests a-file pawn pushes (`a7a5`, `a5a4`, `f8a3`, `c8f5`, …), the cheap NNUE eval
genuinely disagrees with the teacher on most rows. This is **not** a bug in the
trainer — it is a signal that the **teacher distill set is unusual** (likely
`exp18_train` artifacts of a previous experiment) and that pushing the candidate to
fully obey it would be label-quality-driven, not strength-driven.

Recommendation: a future round should re-distill with a stronger / less-quirky
teacher and use `candidate_score_far_above_teacher_count` as a label-quality gate.

## Noise observation

Baseline scores **drift across seeds** within the same cell:
`e1_t4_v2` baselines = [0.594, 0.641, 0.641]; `e8_t4_v2` = [0.609, 0.641, 0.641].
Because the baseline model is identical across seeds, the variation has to come
from the strength gate's search itself — `search_profile=strong` uses
`time_budget_ms=1100`, and time-bound PVS can choose different moves on
near-ties between runs. This is ±1-2 cases of noise per seed; with deltas of
+2 to +4 cases, the gate threshold is easily inside the noise envelope.

Until we make the gate fully deterministic (e.g. node-budget instead of time-budget,
or `depth=4` fixed without time guard), single-cell variance will keep eating the
learning signal at the threshold boundary.

## Promotion tier

| tier | result | reason |
|---|---|---|
| blocked | **true** | every cell has `not_all_runs_passed` and `all_runs_failed` |
| stage_candidate | **false** | no cell reaches `case_pass_rate ≥ 0.70`; best is 0.6875 |
| shadow_candidate | **false** | repeatability_pass requires `pass_count == run_count` |
| production_promote | **false** | requires shadow + train-learning visible + smoke + held-out |

`e8_t4` is the **only configuration that produces visible train-row learning**
(`train_agreement_delta=+0.0833`, `agreement_4/60→9/60`). `e1_t4` is the **only
configuration that produces the largest gate gain** (+0.0833 mean). Neither is
enough to stage.

## What was actually fixed

- `train_agreement_delta` is finally positive (0.0 → +0.0833 with epochs=8).
  The retrain is no longer invisible in the train-row teacher agreement metric.
- Hard-negative injection works as intended and emits an auditable per-sample
  trail (`hard_negative_audit.jsonl` per run).
- Per-sample audit confirms multi-good and teacher_top3 protection is in place
  (18 multi-good exclusions, 0 teacher_top3 exclusions because distill rows
  carry no `teacher_top3` field — flagged via `samples_missing_teacher_top3_count`).
- The `--multi-good-margin-cp` knob propagates through the repeatability gate
  and is recorded in every run's `training_config`.

## What is still blocking promotion

1. Best `case_pass_rate = 0.6875 < 0.70`.
2. `candidate_score_far_above_teacher_count = 48/60` — the teacher distill set
   may be too quirky for the cheap NNUE eval to follow without label cleanup.
3. Strength-gate time-budget noise inflates baseline variance (~±1 case),
   which sits on top of a 1-2-case improvement signal.

## Next steps (exp5_05 candidate plan, not yet executed)

1. Re-distill with a stronger / cleaner teacher and use
   `candidate_score_far_above_teacher_count` as a label-quality filter
   (drop rows where the cheap eval can't justify the teacher's choice).
2. Switch the gate to a deterministic search budget (fixed depth + node cap,
   not time-budget) to remove the ±1-case noise floor.
3. Try `epochs=4, topK=2` — somewhere between the e1_t4 (best gate) and
   e8_t4 (best learning visibility) configurations.
4. Optional: dynamic HN mining — re-mine top-K from the **candidate** every
   2 epochs instead of statically from the baseline.
5. Expand the strength set beyond exp5_02's 60 cases so the threshold has more
   resolution than 1/64 = 0.0156.

## Files touched (this round)

- `services/games/chess_nnue.py`
- `scripts/games/chess_exp5_dataset_train.py`
- `scripts/games/chess_exp5_repeatability_gate.py`
- `docs/games/chess_debug/exp5/2026-05-11_exp5_04_learning_capacity_ablation.md` (this file)

## Artifacts

- `chess_results/exp5_04_learning_capacity/cell_e1_t0/`
- `chess_results/exp5_04_learning_capacity/cell_e8_t0/`
- `chess_results/exp5_04_learning_capacity/cell_e1_t4/` + `cell_e1_t4_v2/`
- `chess_results/exp5_04_learning_capacity/cell_e8_t4/` + `cell_e8_t4_v2/`

Each cell directory contains `stdout.json` (the repeatability payload), `stderr.log`,
`heldout_rows_exp5_03.jsonl`, `smoke_rows_exp5_03.jsonl`, and per-seed
`run_X_seed_Y/{candidate model, distill_shuffled, hard_negative_audit (when topK>0)}`.
