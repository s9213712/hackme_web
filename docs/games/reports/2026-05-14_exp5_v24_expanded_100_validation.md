# Exp5 V24 Expanded 100 Validation

## Scope

本次固定測試 `experiment 5:nnue` 的 V24 生產 profile：
`fixed_depth_fianchetto_tail_castle_guard`。

測驗目標是建立一組新的私有 100-scenario 題庫，避免沿用既有固定題造成過擬合。題庫分四類，各 25 題：

| Section | Questions | Evaluated positions | Purpose |
|---|---:|---:|---|
| `tail10` | 25 | 250 | 結尾 10 步殘局/轉換能力 |
| `tail20` | 25 | 500 | 結尾 20 步長尾轉換能力 |
| `human_probe_trap` | 25 | 25 | human probes / trap / special-rule 類關鍵單點 |
| `complete_game` | 25 | 2,884 | 完整棋局逐 ply 泛化能力 |

總計：100 scenarios、3,659 evaluated positions。

## Leak Policy

不公開題目。公開 docs 只保留 aggregate/redacted evidence，不包含 FEN、走法、teacher PV、teacher best move、source game id、逐題答案或完整 replay。

Raw question set 與逐局面 detail 只保留在 repo 外的 private runtime：

- `$HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/v24_expanded_100_questions.json`
- `$HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/v24_expanded_100_eval_detail.jsonl`

## Stage 1: Multi-Source Download

使用既有下載腳本 `scripts/games/chess_pgn_to_replay.py`，來源為 Lichess 公開 PGN API。不是單一來源：

1. 第一輪多來源下載：3 個有效來源，另 2 個 requested source 回 404，未納入題庫。
2. 題庫不足後，透過 Lichess public top-player API 取得更多有效高分來源。
3. 第二輪補充下載：6 個有效 top-player source。

下載端 PGN filter：

- `valid_game_filter=strict`
- `position_scope=complete`
- `skip_nonstandard_start=true`
- `min_elo` 第一輪 2400+，補充輪 2500+
- `min_ply=30`

Stage output 私有路徑：

- `$HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/imported_replay_multi.jsonl`
- `$HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/imported_replay_top_supplement.jsonl`

## Stage 2: Blockfish/Stockfish Source Audit

本機 Stockfish UCI teacher 作為本批次的 `blockfish teacher`。Stockfish binary 不進 repo，只以 local external teacher 使用。

Source audit smoke 結果：

| Batch | Eligible games | Teacher sample positions | Clean | Review | Rejected |
|---|---:|---:|---:|---:|---:|
| Initial multi-source | 49 | 120 | 110 | 8 | 2 |
| Top-player supplement | 140 | 100 | 92 | 8 | 0 |

Final question-set builder 使用更嚴格的 depth-6 MultiPV-5 teacher 重新審核實際入題 segment，不直接信任下載樣本。

## Stage 3: Question Set Build

Builder: `scripts/games/chess_exp5_expanded_validation.py build`

Teacher settings:

- backend: local Stockfish UCI
- alias: `blockfish_teacher`
- depth: 6
- MultiPV: 5
- accepted source move: top-3 或 cp loss <= 60
- review source move: cp loss <= 160

Build summary:

| Section | Questions | Positions | Source clean | Source review | Source rejected |
|---|---:|---:|---:|---:|---:|
| `tail10` | 25 | 250 | 227 | 23 | 0 |
| `tail20` | 25 | 500 | 465 | 35 | 0 |
| `human_probe_trap` | 25 | 25 | 25 | 0 | 0 |
| `complete_game` | 25 | 2,884 | 586 audited samples | 39 audited samples | 0 |

Note: complete-game source audit samples representative positions from each full game during acceptance, then preserves the full game for V24 evaluation.

Redacted evidence:

- `docs/games/evidence/exp5/v24_expanded_100_question_set_summary.json`

## Stage 4: V24 Evaluation

Evaluator: `scripts/games/chess_exp5_expanded_validation.py evaluate`

Candidate:

- `fixed_depth_fianchetto_tail_castle_guard`

Teacher settings:

- backend: local Stockfish UCI
- depth: 6
- MultiPV: 5
- clean: teacher top-3 or cp loss <= 60
- review: cp loss <= 160

Aggregate result:

| Section | Questions | Positions | Clean | Review | Rejected | Clean rate | Review+ rate | Top-1 | Top-3 | Top-5 | Avg cp loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `tail10` | 25 | 250 | 186 | 28 | 36 | 0.7440 | 0.8560 | 0.3240 | 0.5680 | 0.6680 | 471.792 |
| `tail20` | 25 | 500 | 317 | 74 | 109 | 0.6340 | 0.7820 | 0.2440 | 0.4540 | 0.6080 | 902.864 |
| `human_probe_trap` | 25 | 25 | 25 | 0 | 0 | 1.0000 | 1.0000 | 0.6800 | 0.8400 | 0.8800 | 7.440 |
| `complete_game` | 25 | 2,884 | 1,854 | 502 | 528 | 0.6429 | 0.8169 | 0.2021 | 0.4137 | 0.5465 | 300.950 |
| **Total** | **100** | **3,659** | **2,382** | **604** | **673** | **0.6510** | **0.8161** | **0.2195** | **0.4326** | **0.5655** | n/a |

Redacted evidence:

- `docs/games/evidence/exp5/v24_expanded_100_evaluation.json`
- `docs/games/evidence/exp5/v24_expanded_100_evaluation.jsonl`

## Interpretation

V24 在短 tactical/special-rule probe 上表現穩定，`human_probe_trap` 達到 25/25 clean。這表示 V24 的明確規則、升變、直接威脅與人類常見陷阱防守已經可用。

弱點集中在長尾殘局與完整棋局泛化：

- `tail20` clean rate 只有 0.6340，avg cp loss 高，代表長尾收束與連續轉換仍不穩。
- `complete_game` top-3 只有 0.4137，說明它常能保持不爆炸，但和 teacher 的候選排序差距仍大。
- `review_or_better_rate` 總體 0.8161，表示多數決策不是立即壞棋，但離高階 teacher-like engine 還有明顯距離。

這批數據支持先前判斷：V24 是目前 default 的穩定版本，但不是高階引擎。下一步若要提升，優先處理 long-horizon conversion、endgame planning、quiet positional move ordering，而不是再新增單點 trap prior。

## Script Map

```text
chess_pgn_to_replay.py --source-url ... --stockfish-filter
  -> $HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/imported_replay_*.jsonl
  -> $HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/imported_*_stockfish_probe/

chess_exp5_expanded_validation.py build
  -> $HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/v24_expanded_100_questions.json
  -> docs/games/evidence/exp5/v24_expanded_100_question_set_summary.json

chess_exp5_expanded_validation.py evaluate
  -> $HACKME_WEB_PRIVATE_ROOT/games/exp5/v24_expanded_100/v24_expanded_100_eval_detail.jsonl
  -> docs/games/evidence/exp5/v24_expanded_100_evaluation.json
  -> docs/games/evidence/exp5/v24_expanded_100_evaluation.jsonl
```
