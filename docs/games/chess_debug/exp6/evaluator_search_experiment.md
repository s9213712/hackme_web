# Exp6 Evaluator/Search Experiment

Date: 2026-05-18
Repo commit: `681317d2f15562f4bd35013f90adac31ec748dab`

## Policy

- Champion modified: `false`
- Champion path: `runtime/games/models/chess_experiment_6_neural.npz`
- Champion md5 before: `1c27627adb3c4597561bc7509438e25c`
- Champion md5 after: `1c27627adb3c4597561bc7509438e25c`
- Champion permissions after: `444`
- Root policy bonus used: `false`
- Staged moves/FENs persisted: `false`
- Promotion gate function: `chess_exp6_curriculum.play_staged_test()`
- `chess_exp6_search_ablation.py` status: diagnostic only, not a gate.

## Candidate: `exp6_halfkp_v1`

Files:

- Script: `scripts/games/chess_exp6_halfkp_value_candidate.py`
- Model artifact: `/tmp/exp6_halfkp_v1_600.pt`
- JSON report: `/tmp/exp6_halfkp_v1_600_report.json`

Design:

- Lightweight HalfKP/HalfKAv2-style sparse value evaluator.
- Features are king-square-conditioned piece-square accumulators from white
  and black perspectives.
- Output is a learned residual on top of Exp6 static material + PST baseline.
- Target is compressed Stockfish centipawn value:
  `tanh(clipped_cp_white / 600)`, with a small raw cp residual term.
- Supports after-board evaluation because the search evaluator accepts any
  `chess.Board` after `push()`.
- No policy head and no root rerank path.

Training run:

```bash
python3 -u scripts/games/chess_exp6_halfkp_value_candidate.py \
  --train-limit 600 --dev-size 120 --epochs 4 --hidden 64 --batch-size 256 \
  --model-out /tmp/exp6_halfkp_v1_600.pt \
  --report-json /tmp/exp6_halfkp_v1_600_report.json
```

Final dev metrics:

- smooth L1 on compressed value: `0.022455`
- cp correlation: `0.4474`
- sign accuracy: `0.7417`
- average absolute cp error: `99.94`

## Verification

`py_compile` passed for:

- `services/games/chess_exp6.py`
- `scripts/games/chess_exp6_curriculum.py`
- `scripts/games/chess_exp6_halfkp_value_candidate.py`

Deterministic evaluator sanity:

- Passed.
- Evaluating the same board and one after-board twice produced identical
  values across the fixed suite.

Fixed FEN tactical suite:

- Passed.
- White mate-in-one: passed.
- Black mate-in-one: passed.
- Promotion legality case: passed.

Blunder avoidance suite:

- Passed.
- No tested fixed-FEN choice was illegal or allowed immediate opponent
  mate-in-one.

Fixed-FEN search ablation:

- Baseline current evaluator + current search: legal on all cases.
- New evaluator + same search: legal on all cases.
- New evaluator + depth-2 narrow search: legal on all cases.
- New evaluator + depth-3 narrow search: legal on all cases.
- New evaluator + quiescence off: legal on all cases.
- New evaluator + move ordering off: legal on all cases.

Depth-3 narrow was materially slower on fixed FENs, roughly `0.28s` to `1.10s`
on the sampled positions.

## Staged Result

4-game early gate with `same_search`:

- Result: `0W/2D/2L = -10/16`
- Stop condition: below `-4/16`
- Full 10-game gate: skipped because the candidate failed the required early
  stop condition.

This is a fail. It is not eligible for promotion or wider gate work.

## Interpretation

The HalfKP-style value path is technically wired correctly: it is
deterministic, supports after-board evaluation, passes the generic tactical and
blunder sanity checks, and can be swapped into the existing Exp6 search without
illegal moves in fixed-FEN ablations.

It still breaks staged defence quickly. The failure is not a policy-rerank
failure; it means the small HalfKP residual trained on 600 generic labels is
not yet a stronger consequence evaluator than the locked v6.2 S2 value stack.

Next recommendation:

- Do not promote `exp6_halfkp_v1`.
- Do not add policy workarounds.
- If continuing HalfKP, first improve value training scale/objective and add a
  stronger pre-staged after-board regression suite before spending staged games.
- Alternatively wire a faster incremental evaluator into search so depth-3 can
  be tested under the official gate without exceeding runtime budgets.
