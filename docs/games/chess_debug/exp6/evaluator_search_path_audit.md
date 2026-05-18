# Exp6 Evaluator/Search Path Audit

Date: 2026-05-18
Repo commit inspected: `681317d2f15562f4bd35013f90adac31ec748dab`

## Gate Rule

Promotion decisions must use `scripts/games/chess_exp6_curriculum.py::play_staged_test()`.
`scripts/games/chess_exp6_search_ablation.py` is diagnostic only: its
`principles` clone does not exactly reproduce the runtime champion gate.

Current locked champion:

- Path: `runtime/games/models/chess_experiment_6_neural.npz`
- Expected md5: `1c27627adb3c4597561bc7509438e25c`
- Expected permissions: `444`
- Must not be modified by experiments.

## Official Staged Gate Path

`chess_exp6_curriculum.play_staged_test(weights_path)` builds the staged
schedule from:

- `STAGED_DEPTHS = [1, 2, 3, 4, 5]`
- `STAGED_GAMES_PER_DEPTH = 2`
- `STAGED_OPENINGS = start, open_game, queen_pawn, sicilian, english`

For each game it calls:

1. `chess_exp6_curriculum.play_one_game(...)`
2. `services.games.chess_exp6.choose_experiment_neural_move(...)`
3. `services.games.chess_exp6._to_neural_board(...)`
4. forced mate-in-one short-circuit
5. `services.games.chess_exp6._ensure_default_weights()` or the
   `EXP6_NEURAL_WEIGHTS_PATH` set by the gate
6. `services.games.chess_neural.load_weights(...)`
7. `services.games.chess_neural.NeuralEvaluator(...)`
8. `services.games.chess_exp6._resolve_search_profile("balanced", board=board)`
9. `services.games.chess_search.search_best_move(...)`
10. `services.games.chess_search.opening_sanity_filter(...)`
11. `services.games.chess_exp6._opening_principle_filter(...)`
12. optional conversion filters only if `EXP6_CONVERSION_FILTERS` is enabled;
    current default is off.

The gate report redacts moves/FENs by default and stores only summaries and a
final-FEN digest.

## Runtime Search Profile

The runtime default profile is `balanced`:

- depth: `2`
- quiescence depth: `2`
- time budget: `600 ms`
- PVS: enabled
- LMR: enabled
- null move: disabled
- futility pruning: enabled

Depth-3 exists as `strong` / `fixed_depth_d3`, but is not the default because
previous testing showed it is too slow and not reliably stronger.

## Evaluator Path

`NeuralEvaluator.__call__(board)` delegates to:

1. `chess_neural.evaluate_board(board, weights)`
2. `chess_neural.board_to_features(board)`
3. `chess_neural.evaluate_features(...)`

The current value is:

`static_baseline_cp_white(board) + neural_residual_cp_white`

Then it is returned from `board.turn`'s perspective for negamax.

`static_baseline_cp_white` is:

- material balance
- piece-square table contribution

The neural residual uses the `774 -> 256 -> 32 -> 1` network stored in the
champion `.npz`.

## Move Ordering

Runtime move ordering is not policy-based. It is:

- `_move_order_score`: captures, promotions, checks
- plus `_opening_principle_score` when `EXP6_OPENING_PRINCIPLES` is enabled
  (default on)
- plus search-internal TT move, killers, history, captures, promotions, checks
  inside `chess_search._ordered_moves(...)`

There is no root policy bonus in the approved runtime path.

## Quiescence And TT

`search_best_move(...)` uses:

- iterative deepening
- aspiration windows
- `TranspositionTable`
- `ZobristHasher(seed=20260601)` from Exp6 runtime
- killer/history move ordering
- quiescence search over captures/promotions by default
- optional PVS/LMR/futility according to profile

Quiescence calls the same evaluator on after-boards, so a candidate evaluator
must be stable for `eval(s after move)`, not only the current root board.

## Current Architecture Diagnosis

Exp6 is not primarily blocked by candidate root move sorting. Multiple
policy-rerank probes produced good offline top-N sanity and still broke staged
defence. The next useful work should make evaluator/search consequences more
reliable, especially for after-board evaluation inside depth-2/depth-3 search.
