# Exp5 v17 vs Stockfish Gap Analysis

Date: 2026-05-14

## Status

Exp5 v18 is abandoned as a strength direction. The evidence is retained as a negative experiment, but production analysis should use v17 as the best current baseline.

Current best Exp5 baseline:

| Version | Advanced score | Grade | Gauntlet | Threefold | Avg ms/game |
|---|---:|---|---:|---:|---:|
| v15 | 80.5769 | strong_club_candidate | 14W/16D/0L | 0.5333 | 9516.767 |
| v16 | 84.8551 | strong_club_candidate | 18W/12D/0L | 0.4000 | 15317.006 |
| v17 | 90.9949 | advanced_engine_candidate | 24W/6D/0L | 0.2000 | 14024.485 |
| v18 home-filter | 81.7892 | strong_club_candidate | 16W/12D/2L | 0.4000 | 13075.207 |

Evidence:

- `docs/games/evidence/exp5/v17/2026-05-14_exp5_advanced_score_v17_trap_prior2_30s_runtime_fullrerun.json`
- `docs/games/evidence/exp5/v17/2026-05-14_exp5_gauntlet_v17_full_trap_prior2.json`
- `docs/games/evidence/exp5/v18/advanced_score_home_filter_30s_runtime.json`
- `docs/games/evidence/exp5/v18/gauntlet_30_fixed_depth_balanced_home_filter.json`

Interpretation: v18 fixed a narrow early-queen probe but damaged broad complete-game performance. Treat v18 as a rejected patch family.

## What v17 Is

Exp5 v17 is a Python chess engine built around:

- fixed-depth production profile: `fixed_depth_balanced`, depth 2, quiescence depth 2.
- source-embedded static base model with `sample_count = 1837`.
- hand-written evaluation: material, sparse PST/center weights, simple mobility, king-safety, tempo, and endgame conversion.
- hand-written post-search filters for opening sanity, tactical safety, repetition avoidance, endgame progress, promotion defense, and stalemate avoidance.
- small opening/trap priors embedded in source.

Important local references:

- `services/games/chess_nnue.py`
- `services/games/chess_search.py`
- `services/games/chess_exp5_base_model.py`

## What Stockfish Has That v17 Does Not

### 1. Search architecture

Stockfish is not just alpha-beta plus a few heuristics. Its current search uses mature layers including transposition table use, iterative deepening, aspiration windows, razoring, futility pruning, null-move search with verification, internal iterative reductions, ProbCut, staged move picking, quiescence search, tablebase probing, repetition handling, and many tuned conditions.

Exp5 v17 has a much smaller Python search loop. It has iterative deepening, aspiration windows, a transposition table, killer/history-style ordering, quiescence, and shallow extensions, but production depth is still only 2. The v18 attempt to add Stockfish-like NMP/LMR/PVS/futility did not help because the surrounding evaluator and move picker are not strong enough to support aggressive pruning safely.

Conclusion: copying pruning rules alone is not enough. Stockfish's pruning works because it is supported by high-quality move ordering, strong eval, tested thresholds, and massive regression testing.

### 2. Move ordering

Stockfish uses a staged MovePicker: TT move first, good captures, quiets scored by history/continuation history, bad captures, bad quiets, with SEE gates and partial sorting.

Exp5 v17 scores all legal moves with a hand score and python-chess operations, then sorts. This is simpler but expensive and less selective. It cannot safely push depth unless move ordering becomes more reliable.

Conclusion: Exp5 should not add more post-search filters first. If we optimize search, the next structural item should be staged move picking and better node accounting.

### 3. Evaluation

Stockfish uses a true NNUE with sparse features, accumulators, quantized CPU inference, and trained networks. Current Stockfish NNUE families use large king-relative feature spaces and learned positional evaluation.

Exp5 v17's "NNUE-like" model is not a real NNUE accumulator. It is a compact source-embedded parameter table plus hand-written eval terms. It sees some chess concepts, but not with Stockfish's learned coverage of king-relative piece placement, threats, quiet positional structure, and phase-specific evaluation.

Conclusion: Exp5 v17's evaluator is the largest strength ceiling. Hand-tuned additions can easily regress because they are not trained or statistically gated.

### 4. Training and validation

Stockfish development relies on Fishtest-style statistical testing: pentanomial result modeling, GSPRT, SPSA parameter tuning, large distributed runs, and explicit quality control.

Exp5 currently uses local probes, tactical suites, and a 30-game gauntlet. That is useful for local regression, but too small to validate broad changes like pruning, eval terms, or training changes.

Conclusion: v17 can be improved, but only if each candidate is gated against v17 with stronger measurement. The existing advanced score is now mostly saturated except complete-game gauntlet, repetition rate, and external-engine comparison.

## Can Stockfish Filter Valuable Games?

Yes. This is the best next use of Stockfish.

Stockfish should be used as an offline teacher and replay auditor, not as a direct replacement for Exp5 during normal play.

Recommended pipeline:

1. Keep v17 as immutable production baseline.
2. For every replay, sample positions from the full game.
3. Ask Stockfish for MultiPV labels at fixed depth or fixed movetime.
4. For the move actually played, compute:
   - legality and terminal state correctness.
   - Stockfish rank of played move.
   - centipawn loss against Stockfish best move.
   - mate swing or missed forced mate.
   - whether top-3/top-5 alternatives are close.
   - category: tactic, endgame, opening, quiet positional, repetition/draw, special rule.
5. Accept only high-signal positions:
   - hard negative: Exp5 move loses >= 150-300 cp and Stockfish best move is stable.
   - soft positive: Exp5 move is Stockfish top-3/top-5 and score gap is small.
   - tactical label: missed mate, missed winning capture, allowed mate, promotion race.
   - endgame label: missed tablebase-like conversion or allowed draw.
6. Reject noisy positions:
   - Stockfish top moves are all nearly equal and no useful training signal exists.
   - opening positions where many book moves are equivalent unless building a book.
   - positions where low-depth and higher-depth Stockfish disagree.
   - positions generated by v18 regressions unless explicitly used as hard-negative examples.
7. Train only a small experience adapter/model from accepted labels.
8. Promote only if candidate beats v17 under deterministic gates and complete-game gauntlets.

This follows the "寧缺勿濫" rule: most replay positions are not valuable training data. Stockfish's value is to reject low-signal or misleading rows.

## Practical Stockfish Settings

For filtering, prefer stronger Stockfish settings:

- `MultiPV = 5` or `MultiPV = 8`.
- fixed `depth` for determinism, or fixed `movetime` for speed.
- use `position ... moves ...` rather than FEN-only when repetition context matters.
- use `UCI_ShowWDL = true` when WDL confidence is needed.
- use `SyzygyPath` if tablebases are installed, especially for KPK/KRK/KQK and low-piece endings.

For sparring, use `UCI_LimitStrength` or `Skill Level`. For filtering, do not weaken Stockfish.

Local blocker: `stockfish` is currently not available in PATH on this machine. A future script should accept `--stockfish-path` and/or `STOCKFISH_PATH`.

## Proposed Next Worklist

1. Add a dedicated Stockfish replay audit script under `scripts/games/`.
2. Emit JSONL rows with full audit evidence: fen, move, topK, cp loss, mate flags, category, accept/reject reason.
3. Add a summary report generator under `docs/games/evidence/exp5/stockfish_audit/`.
4. Use the audit output to build small experience adapters only, not to overwrite the source base model.
5. Add a v17-vs-candidate gate:
   - legacy probes must stay saturated.
   - tactical suite must not regress.
   - complete-game gauntlet must improve v17's 24W/6D/0L or reduce threefold without losses.
   - Stockfish cp-loss distribution must improve on held-out positions.

## Recommendation

Do not continue v18-style filter stacking.

The next credible path is:

1. Stockfish as strict replay auditor and teacher.
2. High-signal small adapter training.
3. Held-out Stockfish-audited validation.
4. Only then attempt deeper search or true NNUE-style accumulator work.

This keeps v17 stable while converting replay experience from "self-imitation" into externally judged training data.

## External References

- Stockfish search source: https://github.com/official-stockfish/Stockfish/blob/master/src/search.cpp
- Stockfish move picker source: https://github.com/official-stockfish/Stockfish/blob/master/src/movepick.cpp
- Stockfish NNUE documentation: https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html
- Stockfish UCI commands: https://official-stockfish.github.io/docs/stockfish-wiki/UCI-%26-Commands.html
- Fishtest statistical methods: https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html
