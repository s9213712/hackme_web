# Exp5 Latest Independent Strength Eval

- Date: 2026-05-13
- Target model: `services/games/models/chess_experiment_5_nnue.json`
- SHA256: `88464dba7e3497e7be7474e0aae4272801fb2e98838985740e530f592f2ff992`
- Architecture: `nnue-like-sparse-accumulator-v1`
- Sample count: `1837`
- Updated at: `2026-05-13T14:23:10.607868`

## Command Map

1. Isolated no-training benchmark.
   - Script: `scripts/games/chess_self_play_train.py`
   - Runtime: `<chess-results>/exp5_latest_independent_eval_20260513T080000Z/runtime`
   - Key args: `--exp*-games 0`, `--hard-exp*-games 0`, `--cross* 0`, `--smoke-games-per-pair 1`, `--benchmark-rounds 2`, `--seed 20260518`
   - Model args pointed to copied service models under the isolated runtime.

2. Exp5 deterministic strength gate.
   - Script: `scripts/games/chess_exp5_strength_gate.py`
   - Candidate: `services/games/models/chess_experiment_5_nnue.json`
   - Benchmark report: `<chess-results>/exp5_latest_independent_eval_20260513T080000Z/runtime/reports/games/chess_self_play_train_20260513T094613Z.json`
   - Output: `runtime/reports/games/exp5_latest_strength_gate_20260513/`

3. Codex-vs-exp5 full games.
   - Script: `scripts/games/game_ai_codex_play_eval.py`
   - Critical env: `HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH=services/games/models/chess_experiment_5_nnue.json`
   - Args: `--games-per-ai 5 --chess-only --chess-complete-games --chess-deadloop-guard-plies 2000 --chess-difficulties 'experiment 5:nnue' --seed 20260519`
   - JSON: `runtime/reports/games/exp5_latest_services_model_codex_full_games_20260513.json`
   - JSONL replay: `runtime/reports/games/exp5_latest_services_model_codex_full_games_20260513.jsonl`

## Benchmark Result

The benchmark is independent from retraining: no self-play/replay training games were run in this pass, and all models were copied into an isolated runtime before evaluation.

- Benchmark pass: true
- Games: 84
- Suspicious matches: 0
- Exp5 standing: 24 games, 10 wins, 14 draws, 0 losses, 17.0 points
- Exp5 score rate: 0.7083
- Exp5 win rate: 0.4167
- Internal relative Elo: 1577.62

Benchmark ranking:

| Rank | Engine | Games | W-D-L | Score rate | Internal Elo |
| --- | --- | ---: | --- | ---: | ---: |
| 1 | experiment 5:nnue | 24 | 10-14-0 | 0.7083 | 1577.62 |
| 2 | experiment 2:nn | 24 | 6-18-0 | 0.6250 | 1556.52 |
| 3 | experiment 3:dl | 24 | 11-10-3 | 0.6667 | 1552.70 |
| 4 | experiment 4:pv | 24 | 3-19-2 | 0.5208 | 1513.25 |
| 5 | teacher | 24 | 3-14-7 | 0.4167 | 1454.34 |
| 6 | experiment | 24 | 0-15-9 | 0.3125 | 1439.30 |
| 7 | hard | 24 | 1-10-13 | 0.2500 | 1406.26 |

Exp5 head-to-head:

| Opponent | Exp5 result | Score rate |
| --- | --- | ---: |
| hard | 3-1-0 | 0.875 |
| teacher | 2-2-0 | 0.750 |
| experiment | 2-2-0 | 0.750 |
| experiment 3:dl | 2-2-0 | 0.750 |
| experiment 4:pv | 1-3-0 | 0.625 |
| experiment 2:nn | 0-4-0 | 0.500 |

Smoke eval: exp5 scored 2.5/4, 1 win, 3 draws, 0 losses, score rate 0.625, internal Elo 1506.42.

Endgame suite: exp5 passed 6/6, score rate 1.0. The suite overall still reported false because other engines failed cases.

## Strength Gate Result

The exp5 deterministic gate did not pass, even though the benchmark sub-gate passed.

- Gate pass: false
- Reasons: `deterministic_case_pass_rate_too_low`, `candidate_score_not_above_baseline`
- Case pass rate: 4/7 = 0.5714, below required 0.7
- Legal rate: 1.0
- Suspicious rate: 0.0
- Teacher agreement: 0.571429
- Tactic score: 0.4
- Endgame score: 1.0
- Benchmark sub-gate: passed with exp5 score rate 0.7083 over 24 games

Failed deterministic cases:

| Case | Chosen | Expected/teacher | Note |
| --- | --- | --- | --- |
| `baseline_castling_awareness` | `a8a1` | `e8c8` | Chose material capture over castling awareness. |
| `mate_in_one_white` | `f7g7` | `f7e8` | Missed immediate mate label. |
| `mate_in_one_black` | `f2g2` | `f2e1` | Missed immediate mate label. |

Castling floor: no regression against baseline, but still only 2/4. It failed kingside castling preference for both white and black in the bundled castling floor.

## Codex Full Games

This pass used the requested services model explicitly through `HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH`.

- Games: 5
- Exp5 score: 3.0/5
- Codex score: 2.0/5
- Exp5 wins: 1
- Draws: 4
- Codex wins: 0
- Average plies: 87.2
- Average elapsed: 10.749 s/game
- Invalid moves: 0
- Incomplete games: 0

Per game:

| Game | Codex color | Result | Reason | Plies | Codex material cp |
| --- | --- | --- | --- | ---: | ---: |
| 1 | white | draw | threefold repetition | 72 | -200 |
| 2 | black | draw | threefold repetition | 131 | -300 |
| 3 | white | draw | threefold repetition | 72 | -200 |
| 4 | black | exp5 win | checkmate | 89 | -1460 |
| 5 | white | draw | threefold repetition | 72 | -200 |

Subjective read:

- Exp5 is no longer obviously donating pieces in this sample. It kept at least a small material edge in every Codex full game and converted one game to checkmate.
- The main weakness is conversion, not basic legality or immediate self-destruction. Three games repeated the same rook shuffle (`Ra5/Ra4` against `Rd4/Rf4`) instead of finding a plan to improve a better endgame.
- Tactical sharpness remains incomplete. The deterministic gate shows missed mate-in-one cases, and that is too severe for a model that should understand traps and forcing lines.
- Opening and midgame coherence improved versus the earlier "promotion obsession" report, but the model still overvalues local forcing/material opportunities compared with king safety, mate nets, and non-repeating progress.

## Invalidated Reference Run

An earlier Codex full-game run in this session accidentally used `runtime/games/models/chess_experiment_5_nnue.json`, whose SHA/sample count did not match the requested services model. That run is retained only as a reference artifact:

- JSON: `runtime/reports/games/exp5_latest_codex_full_games_20260513.json`
- JSONL: `runtime/reports/games/exp5_latest_codex_full_games_20260513.jsonl`

It should not be used as the latest-model strength number.

## Verdict

Latest exp5 is the strongest model in the current internal benchmark and looks materially safer than the earlier exp4/exp5 behavior, but it is not promotion-quality under the deterministic gate. Treat it as a stronger sparring model with unresolved tactical reliability issues, especially mate recognition and converting better endgames without repetition.
