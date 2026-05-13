# exp5_08 — larger clean pool + special-rule curriculum + smoke-default fix

Date: 2026-05-12
Status:
- **`candidate_can_be_staged = True`** on Cell B (clean_only e=4 topK=2)
  AND Cell C (clean+review e=4 topK=2 rw=0.4), each across 3/3 seeds
  under `fixed_depth_strong`.
- `candidate_can_be_shadowed = False` and `candidate_can_be_production_promoted = False`
  on every cell (`benchmark_report_missing_for_shadow_or_production`).
- exp5_08 **confirms** the exp5_07 stage signal at ~2× larger training
  pool (60 → 116 clean rows) and ~1.5× larger eval set (42 → 64 cases).

Predecessor: `2026-05-12_exp5_07_stage_gate_plumbing.md`

## What changed for exp5_08

### Data — larger raw pool with special-rule curriculum

| layer | raw rows | category |
|---|---|---|
| `chess_results/exp5_08_clean_pool/fen_sources/exp5_08_raw_fens.jsonl` | 344 | endgame 146 / opening 84 / special_rule 50 / tactic 46 / quiet_positional 16 / blunder_avoid 2 |

The pool is built from `gen_exp5_06_fens_v2.jsonl` (212 rows) + 132 new
positions targeted at endgame (KP / KR / KQ / KB+N / 2P), special-rule
curriculum (castling / EP / promotion / underpromotion / stalemate-avoid),
tactic (mate-in-1 / forks / pins / back-rank), and a handful of quiet
positional rows.

### Distill yields

```
raw_rows                                          = 344
distilled (legal teacher move found)              = 341
clean_rows                                        = 141   (3.4× exp5_06's 73)
review_rows                                       = 12
questionable_rows                                 = 188
clean_ratio                                       = 0.413  (vs exp5_06 0.346, exp5_02 0.067)
baseline_policy_gap_avg                           = 20264.7 cp
baseline_policy_gap_max                           = 227233 cp
teacher_top3_does_not_contain_teacher_move_count  = 219 / 341
```

Per-category clean ratio:

| category | clean | review | quest | total | ratio |
|---|---|---|---|---|---|
| endgame | **96** | 3 | 47 | 146 | **0.66** |
| tactic | 18 | 2 | 23 | 43 | 0.42 |
| special_rule | 16 | 2 | 32 | 50 | 0.32 |
| opening | 6 | 2 | 76 | 84 | 0.07 |
| quiet_positional | 3 | 3 | 10 | 16 | 0.19 |
| blunder_avoid | 2 | 0 | 0 | 2 | 1.00 |

Endgame remains the most teacher-aligned category. Opening unchanged
at 0.07: the 1-ply static teacher and the cheap NNUE eval disagree on
opening move selection regardless of pool size. **This is a pipeline
limit, not a label-noise issue** — depth-3 alpha-beta with the
`_teacher_static_eval` is structurally too shallow to converge with
the cheap eval on positional opening choices.

### Train/eval split (`eval_mod=5` deterministic position_id hash)

```
train_bucket = 277 rows  (116 clean / 11 review / 150 quest)
eval_bucket  =  64 cases (25 clean /  1 review /  38 quest)
overlap_by_position_id = 0
```

### Smoke-default fix (`chess_exp5_strength_gate.py`)

exp5_08 surfaced a latent bug in `_case_category()`: when a user-supplied
strength case carries an unrecognised `category` string (e.g.
`"exp5_08_eval"`), the function silently defaulted to `"smoke"`. That
routed every case through `_smoke_audit`, so any regression of the
candidate vs baseline on any case triggered `smoke_candidate_failures`
in `stage_reasons` — **double-counting** the explicit regression budget
and blocking otherwise-stage-eligible cells.

Fix: default is now `"unlabeled"`. `_smoke_audit` only fires on cases
that explicitly carry `category="smoke"`. The bundled `EXP5_STRENGTH_CASES`
are unaffected (every bundled case has an explicit category or
`must_checkmate`/`must_promote`/etc. flags that map to tactic/endgame).

## Ablation results (3 seeds × 4 cells, `fixed_depth_strong`, smoke fix in)

| cell | trn rows | tier_stage | mean Δ | imp/seed | reg/seed | reg_rate | train_agr_Δ | margin_Δ |
|---|---|---|---|---|---|---|---|---|
| A: clean_only e=4 t=0 | 116 | **False** | −0.0294 | 3.0 | 5.0 | 0.074 | +0.129 | −90.5 |
| **B: clean_only e=4 t=2** | 116 | **True** ✓ | **+0.0294** | 4.0 | **2.0** | 0.029 | +0.095 | −190.8 |
| **C: clean+review e=4 t=2 rw=0.4** | 127 | **True** ✓ | **+0.0294** | 4.0 | **2.0** | 0.029 | +0.118 | −166.5 |
| D: clean+review e=8 t=0 rw=0.4 | 127 | False | 0.0000 | 3.0 | 3.0 | 0.044 | +0.016 | −83.6 |

`tier_stage`: `stage_candidate=True` requires `candidate_score > baseline_score`,
`case_pass_rate ≥ 0.70`, `regression_rate ≤ 0.10`, `castling_floor` no
regress, no `held_out_in_training`, no smoke-candidate-fail (after the
smoke-default fix).

### Per-tier breakdown (sum across 3 seeds / 3 = per-seed contribution)

**Cell B (the staged candidate):**

| tier | n | sum_delta/seed | improved (×3 seeds) | regressed (×3 seeds) |
|---|---|---|---|---|
| clean | 25 | **+1.0** | 6 | 3 |
| review | 1 | 0 | 0 | 0 |
| questionable | 38 | **+1.0** | 6 | 3 |
| unlabeled | 4 | 0 | 0 | 0 |

**Cell B by category:**

| category | n | sum_delta/seed | improved | regressed |
|---|---|---|---|---|
| **endgame** | 35 | **+4.0** | **12** | **0** |
| opening | 17 | −1.0 | 0 | 3 |
| quiet_positional | 2 | −1.0 | 0 | 3 |
| special_rule | 4 | 0 | 0 | 0 |
| tactic | 6 | 0 | 0 | 0 |

**The candidate's improvement is concentrated in the endgame category: 12 cases
across 3 seeds (4 per seed) improving without a single regression.** The
opening + quiet_positional drift (−3 cases each total, i.e. 1 each per
seed) is the price.

**Cell C (clean+review):** identical to Cell B (1 review row contributes
nothing measurable; same per-cell delta and per-category split).

**Cell A (no HN):** loses 12 questionable cases per 3 seeds — the same
"weights drift broadly without HN" failure mode seen in exp5_06.

**Cell D (e=8, no HN):** +2 clean cases per seed but −9 questionable
across 3 seeds, net zero score_delta. Multi-epoch without HN still
breaks rows.

### What cells B and C actually learned

Same as exp5_06: **king-activation in K+P endgames**. Cell B improves
12 endgame cases (4 per seed × 3 seeds, all same deterministic
candidate) where the baseline plays a pawn move first and the
candidate correctly moves the king. This is the textbook
"keep the king in the corner of the pawn" rule.

## Selected candidate

| field | value |
|---|---|
| selected_candidate_cell | **B (smokefix)** |
| selection_reason | clean_only + same Δ as C but does not rely on review labels |
| training data | `exp5_08_train_clean_only.jsonl` (116 rows, all label_quality=clean) |
| epochs | 4 |
| auto-hard-negative-topk | 2 |
| review_weight | n/a (clean_only) |
| search_profile | fixed_depth_strong |
| dataset_hash16 | `9accbee6b540be89` |
| candidate sha256 | `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc` |
| baseline sha256 | `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec` |
| staged_model_path | `<chess_results>/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json` |
| baseline_model_path | `<repo>/services/games/models/chess_experiment_5_nnue.json` |

## exp5_07 vs exp5_08 progression

| | exp5_06 | exp5_07 (Cell B rerun, smaller pool) | exp5_08 (Cell B smokefix) |
|---|---|---|---|
| clean training rows | 60 | 60 | **116** |
| eval cases | 42 | 42 | **64** |
| baseline_score | 0.7826 | 0.7826 | 0.7647 |
| candidate_score | 0.8043 | 0.8043 | 0.7941 |
| **mean Δ** | +0.0217 | +0.0217 | **+0.0294** |
| train_agreement_delta | +0.283 | +0.283 | +0.095 |
| reg/seed | 0 | 0 | 2 |
| tier_stage | n/a (plumbing) | **True** | **True** |

The exp5_08 candidate has a **bigger absolute score_delta** but a
**smaller train_agreement_delta**, because:

- the larger eval bucket (64 vs 42) gives more headroom for absolute
  improvements; +0.0294 × 64 = ~+1.88 cases.
- train_agreement_delta normalises by training rows. With 4× more train
  rows, each row contributes proportionally less to agreement_delta
  (though absolute count of "newly aligned with teacher" went UP).
- regression count went from 0 to 2 — because the eval bucket now
  contains 17 opening cases the candidate sometimes breaks. The
  regression budget (≤0.10) is still met (0.029).

## What's still blocking shadow/production

```
shadow_reasons     = ["benchmark_report_missing_for_shadow_or_production"]
production_reasons = ["benchmark_report_missing_for_shadow_or_production"]
```

No model-quality issues at stage. The only blocker is **policy** —
shadow/production require external benchmark evidence (a `--benchmark-report-path`
of a focused exp5-vs-baseline benchmark with score_rate and game count).
That's a follow-up workflow, not a model-training task.

## Files touched (exp5_08)

- `scripts/games/chess_exp5_strength_gate.py` — `_case_category` default
  changed from `"smoke"` to `"unlabeled"` (smoke-default fix)
- `docs/games/chess_debug/exp5/2026-05-12_exp5_08_clean_pool_expansion.md`
  (this file)

## Artifacts

- `chess_results/exp5_08_clean_pool/`
  - `fen_sources/exp5_08_raw_fens.jsonl` — 344 raw FENs
  - `distill/exp5_08_distill.jsonl` — 341 distilled rows
  - `distill/exp5_08_audit.jsonl` — per-row audit
  - `distill/exp5_08_quarantine.jsonl` — 188 questionable rows
  - `inputs/exp5_08_train_clean_only.jsonl` — 116 rows
  - `inputs/exp5_08_train_clean_plus_review.jsonl` — 127 rows
  - `inputs/exp5_08_strength_cases.jsonl` — 64 eval-bucket cases
  - `ablation/cell_*_smokefix/` — 4 cells × 3 seeds with smoke fix
- `chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
  — staged model artifact (sha256 `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`)

## Tests

```
py_compile: 8 files OK
exp5 targeted + train pipeline + self-play tests: 22 passed
git diff --check: clean
```

## Next-step candidates

1. **Build benchmark report for shadow** — `chess_focused_benchmark_run.py`
   (or equivalent) on exp5_08 stage candidate vs baseline. With benchmark
   present, the gate would auto-promote stage → shadow (3 seeds pass
   benchmark_gate score_rate ≥ 0.45, games ≥ 2).
2. **Opening clean signal** — at 7% the opening category currently is
   noise. Either use a stronger teacher than depth-3 static (PR
   would be to plug Stockfish at appropriate depth into
   `choose_teacher_move`), OR drop opening from the distill pool
   and accept the candidate as "endgame-trained NNUE refinement".
3. **Special-rule training**: only 16 special_rule clean rows after
   filter. The user mentioned `special_rule_weight=2.0` — could be
   piloted by adding a `--label-special-rule-weight` flag in the
   trainer and weighting those 16 rows higher.
4. **Self-play outcome anchor (item 5 from exp3 lessons)** — run
   `chess_exp5_self_play_anchor.py` on the 116 clean train rows;
   downweight or drop rows where self-play disagrees with the teacher.
