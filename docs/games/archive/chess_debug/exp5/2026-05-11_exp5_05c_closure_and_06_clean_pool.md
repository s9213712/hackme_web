# exp5_05c closure + exp5_06 clean-pool retrain ablation

Date: 2026-05-11
Status:
- exp5_05c → **blocked**, conclusion stable: 12-row clean+review is insufficient
- exp5_06 → **stage_candidate-level evidence** for cells B and C, blocked only by
  benchmark-report gate policy (orthogonal). First positive `score_delta` in
  any exp5 ablation under `fixed_depth_strong`.

Predecessors:
- `2026-05-11_exp5_05a_b_deterministic_gate_and_label_audit.md`
- `2026-05-11_exp5_04_learning_capacity_ablation.md`
- `2026-05-11_exp3_replay_format_lessons_for_exp5.md`
- `2026-05-11_exp3_replay_example2_5game_lessons_for_exp5.md`

## What was implemented before re-running (items 1-11 closure)

This pair of experiments only ran AFTER all 11 structural fixes from the
exp3-example1 and exp3-example2 analyses landed. The implemented set:

| # | Item | Where |
|---|---|---|
| 1 | `label_quality` → per-sample weight multiplier (clean 1.0× / review 0.4× / questionable 0.0×) | `chess_exp5_dataset_train.py` |
| 2 | `position_id` v2 (board_fen + turn + castling_xfen + ep_square + side) | `chess_exp5_teacher_distill.py:_position_id` |
| 3 | `source_category` + per-category `confidence_score_baseline` (exp3 ladder: benchmark .98 → user_games .42) | `chess_exp5_teacher_distill.py` |
| 4 | `--quarantine-jsonl` separate output for label_quality=questionable rows | same |
| 5 | Self-play outcome anchor enrichment script | `chess_exp5_self_play_anchor.py` (new) |
| 6 | Wording: stop calling depth-3 static teacher "ground truth"; docs use "label proposal" + `static_teacher_top_k=true` | `docs/games/chess_debug/exp5/README.md` |
| 7 | Game-level pattern audit (never_castled / early_king_move / rim_knight / queen_for_minor_early) | `chess_exp5_replay_audit.py` (new) |
| 8 | Eval-based resign validator (resign_questionable if eval ≥ −300cp and no mate ≤ 5) | same |
| 9 | Loser-blunder mining (drop ≥ 200cp → hard-negative candidate) | same |
| 10 | `_king_safety_score` upgrade: broader safe set + uncastled-K-after-move-12 penalty + castling move-order bonus | `services/games/chess_nnue.py` |
| 11 | Castling cluster as hard floor in strength gate | `scripts/games/chess_exp5_strength_gate.py:_evaluate_castling_floor` |

**Replay audit on the two exp3 example files**: 6/6 games flagged for
quarantine (every game has at least `pattern_never_castled_*`). Game 3 in
example2 caught as `resign_questionable_by_eval`: resigner had eval +664cp
and no mate within 5. 6 blunder moves recorded with drops of −377 to
−2357 cp. The existing exp3 `suspicious_flag` had marked all 6 games as
`False` — our audit corrects 6/6.

**Resign-policy audit on exp5 distill / training artefacts**:
`files_scanned=24, files_with_game_outcome_fields=0, resign_rows_count=0,
resign_rows_used_as_positive_target=0`. exp5 does not currently consume
any game-outcome data, so the failure mode exp3-example2 demonstrates
cannot reach exp5 through current pipelines. `resign_policy_audit_passed=True`.

**Item 10 baseline determinism**: 3 runs of the post-item10 baseline under
`fixed_depth_strong` on the 60-case exp5_02 strength set: scores
`[0.683333, 0.683333, 0.683333]`, `move_diff_count=0`, baseline_score
unchanged vs pre-item10. **Item 10 changed the eval surface without
changing the existing strength-set decisions** (the move-12 penalty
doesn't fire for early-game test FENs; the move-order castling bonus
only re-orders alpha-beta exploration, not final selection when other
factors dominate).

## exp5_05c closure — cell D rerun with post-item10 baseline + new instrumentation

| metric | exp5_05c v1 (pre-fix) | exp5_05c closure rerun |
|---|---|---|
| `mass_per_row_review_to_clean_ratio` | (not captured) | **0.4** — confirms `--label-quality-weight-review=0.4` actually scales updates |
| `review_weight_not_effective` | unknown | **False** (good) |
| `positive_updates_by_label_quality` | n/a | clean=32, review=64, questionable=0 |
| `effective_update_mass_by_label_quality` | n/a | clean=806.4, review=645.1, questionable=0 |
| `baseline_score` (60-case set) | 0.6875 | **0.7031** (item 10 net effect on broader saf-zone reward) |
| `candidate_score` | 0.6875 | 0.6875 |
| `score_delta` | -0.0156 | **-0.0156** (still negative — same magnitude, but baseline is now stronger) |
| `train_agreement_delta` | +0.0833 | +0.0833 |
| `baseline_teacher_margin` | -1419.6 cp | **-155.8 cp** (item 10's broader haven moves baseline much closer to teacher choices) |
| `candidate_teacher_margin` | -1885.8 cp | -144.4 cp |
| `margin_delta` | -466.3 cp | **+11.3 cp** (flipped POSITIVE for the first time) |
| `regression_rate` | 0.047 | 0.031 |
| `pass_count / run_count` | 0 / 3 | 0 / 3 |

**Verdict for exp5_05c**: closure-ready. The instrumentation confirms the
review weight is genuinely effective. The eval upgrade made the baseline
itself stronger, but with only 12 training rows the trainer cannot beat
the upgraded baseline. **The conclusion does not change**: clean pool
size is the limiting factor, not the training knobs.

## exp5_06 — larger clean pool retrain ablation

### Inputs

| artefact | count | hash16 |
|---|---|---|
| raw FENs (`exp5_06_raw_fens_v2.jsonl`) | 212 | — |
| distill output (`exp5_06_distill_v2.jsonl`) | 211 (1 illegal) | — |
| train bucket (after `eval_mod=5` split) | 169 | — |
| eval bucket (strength cases) | 42 | f98ac54989f393f1 |
| `exp5_06_train_clean_only.jsonl` | 60 | a8545ecf185daafc |
| `exp5_06_train_clean_plus_review.jsonl` | 67 | 431b644872f1ed3c |

### Distill label-quality summary

```
raw_rows                                                = 212
output_rows                                             = 211
clean_rows                                              = 73
review_rows                                             = 8
questionable_rows                                       = 130
clean_ratio                                             = 0.346    (vs exp5_02's 0.067)
baseline_policy_gap_avg                                 = 10568.9 cp
baseline_policy_gap_max                                 = 218408 cp
teacher_top3_does_not_contain_teacher_move_count        = 96 / 211
quarantine_jsonl rows                                   = 130
```

### Per-category clean ratio

| category | clean | review | quest | total | clean_ratio |
|---|---|---|---|---|---|
| opening | 6 | 2 | 76 | 84 | 0.07 |
| tactic | 11 | 2 | 14 | 27 | 0.41 |
| endgame | 43 | 3 | 23 | 69 | **0.62** |
| special_rule | 9 | 1 | 12 | 22 | 0.41 |
| quiet_positional | 2 | 0 | 5 | 7 | 0.29 |
| blunder_avoid | 2 | 0 | 0 | 2 | 1.00 |

Endgame positions carry the clean pool. Opening positions are
structurally hard for the depth-3 static teacher to converge with the
cheap NNUE eval; future pool expansion should prioritise
endgame/tactic/special_rule.

### Train/eval split via `position_id`

```
train_rows: 169 (60 clean / 7 review / 102 questionable)
eval_rows : 42  (13 clean / 1 review / 28 questionable)
overlap by position_id: 0  (eval_mod=5 deterministic hash split)
```

### Ablation grid (3 seeds × 4 cells, `fixed_depth_strong`)

| cell | trn rows | epochs | topK | review_w | pass | mean Δ | imp/seed | reg/seed | reg_rate | train_agr_Δ | margin_Δ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A: clean_only e=4 t=0 | 60 | 4 | 0 | — | 0/3 | **−0.0652** | 1.0 | 4.0 | 0.087 | +0.300 | −73.4 |
| **B: clean_only e=4 t=2** | 60 | 4 | 2 | — | 0/3* | **+0.0217** | 1.0 | **0.0** | **0.000** | +0.283 | −78.3 |
| **C: clean+review e=4 t=2 rw=0.4** | 67 | 4 | 2 | 0.4 | 0/3* | **+0.0217** | 1.0 | **0.0** | **0.000** | +0.284 | −53.8 |
| D: clean+review e=8 t=0 rw=0.4 | 67 | 8 | 0 | 0.4 | 0/3 | −0.0217 | 1.0 | 2.0 | 0.043 | +0.343 | −58.2 |

*Cells B and C have zero deterministic-strength failures (see "What blocked
pass_count" below). The 0/3 reads as "all 3 seeds pass strength but the
overall promotion gate is skipped due to missing benchmark report".

### What blocked `pass_count` even though candidate > baseline

For cells B and C, every per-seed run reports:

```
case_pass_rate     : 0.8043   (>= 0.70 threshold)
candidate_score    : 0.8043
baseline_score     : 0.7826
gate_pass_reasons  : ['strength_gate_skipped_no_benchmark_report']
```

The strength gate itself passes; the **outer promotion gate** appends
`strength_gate_skipped_no_benchmark_report` whenever
`--benchmark-report-path` is absent. exp5_06 ran without a benchmark
because the deterministic strength gate is supposed to BE the primary
evidence under exp5_05a's policy. The two checks should not both be
required for "stage candidate". This is gate-policy plumbing, not a
measurement problem.

### Hard-negative audit (cell B, seed 11)

```
hard_negative_injected_count                  = 47       (down from 221 in exp5_04 — top5 exclusion is biting)
hard_negative_preexisting_count               = 0
hard_negative_excluded_as_teacher_top3_count  = 140
hard_negative_excluded_as_teacher_top5_count  = 72
hard_negative_excluded_as_multi_good_count    = 69
samples_missing_teacher_top3_count            = 0        (all distill rows carry teacher_top3 now)
candidate_score_far_above_teacher_count       = ~16 / 60
```

The new distill carries `teacher_top3` / `teacher_top5` for every row,
so `top3_exclusion=140` and `top5_exclusion=72` actually trigger.
**The trainer is no longer accidentally penalising teacher's own
equivalent good moves** as it did in exp5_04 (where distill rows had
no top3/top5 and all 221 candidate-moves were treated as raw HN).

### `label_quality` weighting evidence (cell C, seed 11)

```
weight_clean                = 1.0
weight_review               = 0.4
weight_questionable         = 0.0
rows_clean                  = 60
rows_review                 = 7
rows_questionable           = 0
rows_dropped_questionable   = 0  (none in train bucket after distill filter)

positive_updates_by_label_quality:
  clean         = 240
  review        = 28
  questionable  = 0
effective_update_mass_by_label_quality:
  clean         = 6048
  review        = 282
  questionable  = 0
mass_per_row_clean / mass_per_row_review = 100.8 / 40.32  (ratio 0.4)
review_weight_not_effective = False
```

Review weight bites: each review row contributes 40% of a clean row's
total weight-mass. Without this, exp5_05c's `repeat = max(1, round(weight))`
would have collapsed review to full weight.

### Train-row learning audit (best cell D)

```
baseline_teacher_agreement_on_train  = 0.328  (22/67)
candidate_teacher_agreement_on_train = 0.672  (45/67)
train_agreement_delta                = +0.343
baseline_teacher_margin              = -38.4 cp
candidate_teacher_margin             = -96.6 cp
margin_delta                         = -58.2 cp
```

Candidate flips 23 train rows from "teacher not top-1" to "teacher top-1"
— this is real, visible learning, not metric-shaped artefacts. The margin
worsening is the same effect explained in exp5_04: once teacher is top-1
the "gap" metric measures distance to NEW non-teacher top-1.

### Per-tier `score_delta` breakdown (sum across 3 seeds, then divided by 3 to get per-seed)

| cell | clean (n=13) | review (n=1) | questionable (n=28) | unlabeled (n=4) |
|---|---|---|---|---|
| A: clean_only e=4 t=0 | **0.0** (3 imp / 3 reg) | 0 | **−3.0** (0 imp / 9 reg) | 0 |
| **B: clean_only e=4 t=2** | **+1.0** (3 imp / 0 reg) | 0 | 0 (0 imp / 0 reg) | 0 |
| **C: clean+review e=4 t=2 rw=0.4** | **+1.0** (3 imp / 0 reg) | 0 | 0 (0 imp / 0 reg) | 0 |
| D: clean+review e=8 t=0 rw=0.4 | **+1.0** (3 imp / 0 reg) | 0 | **−2.0** (0 imp / 6 reg) | 0 |

`improved` and `regressed` totals are across all 3 seeds. The 1-case-per-seed
clean improvement in B/C/D is the **same FEN improving deterministically
across seeds**:

| improved case | category | label | teacher | baseline | candidate |
|---|---|---|---|---|---|
| `exp5_06_eval_f8f2899e884a` | endgame (KP, `kp_wf2`) | clean | `e1d1` | `f2f4` (pawn push) | `e1d1` / `e1d2` (king activation) |

The candidate has learned the **fundamental KP endgame rule**: activate the
king before the pawn. Baseline pushes the pawn first (a known beginner
mistake).

### Cells A and D regression breakdown

| cell | regressed (seed 11) | tier | category |
|---|---|---|---|
| A | `exp5_06_eval_31025eb9bc43` (opening depth 8) | questionable | opening |
| A | `exp5_06_eval_ebff4e895b11` (endgame `kp_wd3`) | **clean** | endgame |
| A | `exp5_06_eval_7ac29069c628` (endgame `kr_middle`) | questionable | endgame |
| A | `exp5_06_eval_16d54cae934b` (`ep_chance_w2`) | questionable | special_rule |
| D | `exp5_06_eval_6a4c7222b99c` (opening depth 6) | questionable | opening |
| D | `exp5_06_eval_7ac29069c628` (endgame `kr_middle`) | questionable | endgame |

Cell A loses **one clean endgame case (`kp_wd3`)** alongside three questionable
cases. Cell D only loses questionable cases. **Cells B and C: zero
regressions of any kind.**

Conclusion: without HN (Cell A), training pushes weights too broadly and
can corrupt clean cases. **HN exclusion of teacher_top3 / teacher_top5 /
multi-good is what protects clean cases from regression in Cells B and C.**

### Final consolidated table

| cell | strength criteria | mean Δ | clean Δ (/seed) | quest Δ (/seed) | reg/seed | train_agr_Δ | castle_floor |
|---|---|---|---|---|---|---|---|
| A: clean_only e=4 t=0 | **FAIL** | −0.0652 | 0.0 | −3.0 | 4.0 | +0.300 | no regress |
| **B: clean_only e=4 t=2** | **PASS** | +0.0217 | **+1.0** | 0.0 | **0.0** | +0.283 | no regress |
| **C: clean+review e=4 t=2 rw=0.4** | **PASS** | +0.0217 | **+1.0** | 0.0 | **0.0** | +0.284 | no regress |
| D: clean+review e=8 t=0 rw=0.4 | FAIL | −0.0217 | +1.0 | −2.0 | 2.0 | +0.343 | no regress |

"Strength criteria" = `candidate_score > baseline_score AND case_pass_rate ≥ 0.70`.
Cells B and C pass on their own deterministic strength evidence.

### Special-rule and castling cluster check

`castling_floor_enabled=True` by default in the strength gate now. For
the exp5_06 candidates (cells B and C), the castling cluster on the 4
bundled castling cases: candidate=baseline (no castling regression).
For cells A and D, same. So **item 11's floor was satisfied across the
ablation**.

The bundled special-rule gate, run separately on the bundled baseline,
shows the cheap eval still only picks castling 1/4 cases. That is a
known limitation; promotion-ready exp5_06+ candidates should explicitly
include castling training rows (already present: 9 clean special_rule
rows in the train bucket).

## Promotion tier (current snapshot)

| tier | A | B | C | D |
|---|---|---|---|---|
| `blocked` | true | true | true | true |
| `stage_candidate` (strength-only signal) | false | **TRUE in spirit** (candidate > baseline, no regression, train-learning visible) | **TRUE in spirit** | false |
| `shadow_candidate` | false | false | false | false |
| `production_promote` | false | false | false | false |

"In spirit" because the literal `stage_candidate=false` value comes from
the `strength_gate_skipped_no_benchmark_report` outer-gate rule. The
deterministic strength evidence on its own would qualify B and C.

## What changed materially between exp5_05c and exp5_06

| dimension | exp5_05c | exp5_06 |
|---|---|---|
| clean training rows | 4 | 60 (B) / 60+7=67 (C, D) |
| total distill rows | 60 | 211 |
| clean_ratio | 0.067 | 0.346 |
| strength_cases label_quality clean | 4/60 | 13/42 |
| strength_cases label_quality questionable | 48/60 | 28/42 |
| train_vs_strength_overlap (position_id) | 4–12 / 60 | **0 / 42** (eval_mod hash split) |
| best mean Δ (3 seeds) | −0.0156 | **+0.0217** |
| best train_agreement_delta | +0.0833 | +0.343 |
| best regression_rate | 0.031 | **0.000** (cells B, C) |

## Sufficient for what

Yes for:
- "is exp5 architecturally capable of producing a positive
  `score_delta > 0` under `fixed_depth_strong` deterministic gate, with
  visible train-row learning, and zero regression?" → **Yes, cells B
  and C demonstrate this with 3/3 seeds.**

Not yet for:
- production promotion (still needs benchmark report + shadow_pass + smoke
  cases + repeatability across seeds — and the 42-case eval set is too small
  to support a 0.70 threshold with high confidence; cells flip on ≤ 1 case)
- broader category coverage (opening clean ratio 0.07 is too low; we lean
  heavily on endgame which is not where most live games are)

## Recommended next steps (exp5_07+, not executed here)

1. **Promote the strength-gate-only signal to `stage_candidate`** in the
   tier logic when the user explicitly skips benchmark. The current
   "skip → fail" coupling treats absence of benchmark as a regression
   signal, which it isn't.
2. **Expand clean pool further** by adding 200–300 more endgame /
   tactic / special_rule FENs — same yield ratios should push clean to
   200+.
3. **Build a dedicated castling-training set**: 20–40 positions where
   castling is unambiguously the only good move; distill these and
   weight them at `special_rule_weight=2.0` per the user's spec.
4. **Run the replay-level audit on any future incoming user_games** so
   exp5 doesn't import the exp3-example2 failure modes.
5. **Use the self-play outcome anchor on the train bucket** — for each
   clean row, run K=4 self-play games and either downweight or drop
   rows where the outcome diverges. This adds the
   "game-outcome anchor on every sample" item from exp3's example1.

## Files touched (this round)

- `services/games/chess_nnue.py` (item 10: `_king_safety_score` upgrade + castling move-order bonus)
- `scripts/games/chess_exp5_dataset_train.py` (label_quality → weight; positive_updates/effective_mass instrumentation; teacher_top5 exclusion; BooleanOptionalAction)
- `scripts/games/chess_exp5_teacher_distill.py` (position_id v2 with castling+ep; source_category; quarantine_jsonl; eval_mod split)
- `scripts/games/chess_exp5_repeatability_gate.py` (--label-quality-weight-* pass-through; --multi-good-margin-cp; training_config + label_quality_weighting per-run)
- `scripts/games/chess_exp5_strength_gate.py` (item 11: castling floor; `--castling-floor-enabled`)
- `scripts/games/chess_exp5_special_rule_gate.py` (NEW — bundled special-rule deterministic gate)
- `scripts/games/chess_exp5_replay_audit.py` (NEW — items 7/8/9: pattern + resign + blunder audit)
- `scripts/games/chess_exp5_self_play_anchor.py` (NEW — item 5: self-play outcome anchor)
- `docs/games/chess_debug/exp5/README.md` (item 6: terminology rules)
- `docs/games/chess_debug/exp5/2026-05-11_exp3_replay_format_lessons_for_exp5.md`
- `docs/games/chess_debug/exp5/2026-05-11_exp3_replay_example2_5game_lessons_for_exp5.md`
- `docs/games/chess_debug/exp5/2026-05-11_exp5_05c_closure_and_06_clean_pool.md` (this file)

## Artifacts

- `chess_results/exp5_05c_clean_ablation/cell_D_creview_e8_t0_v2/` — closure cell with post-item10 baseline + new instrumentation
- `chess_results/exp5_06_clean_pool/`
  - `fen_sources/exp5_06_raw_fens_v2.jsonl` — 212 raw FEN candidates
  - `distill/exp5_06_distill_v2.jsonl` — 211 distilled rows w/ label_quality
  - `distill/exp5_06_audit_v2.jsonl` — full audit
  - `distill/exp5_06_quarantine_v2.jsonl` — 130 questionable rows
  - `inputs/exp5_06_train_{clean_only, clean_plus_review}.jsonl`
  - `inputs/exp5_06_strength_cases.jsonl` — 42 eval-bucket cases
  - `ablation/cell_{A_e4_t0, B_e4_t2, C_e4_t2, D_e8_t0}/` — 4 cells × 3 seeds
- `chess_results/exp5_replay_audit/` — 6/6 example games quarantined with explicit reasons
- `chess_results/exp5_self_play_anchor_demo/` — anchor module demo on 12 rows

## Test surface

```
py_compile: 8 files OK
exp5 targeted tests: 22 passed
git diff --check: clean
```
