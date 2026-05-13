# Chess pipeline — 進度小結 (2026-05-12)

> 對應使用者原始需求：
> 「自動下載範例棋局、訓練 exp4/5 warm-up、自動進行雙方對戰（多種模式）、retrain、最終輸出報告的整套流程，這整段有接起來嗎？」

## TL;DR

**架構接好了，但故意停在 dry-run。** 現在能一鍵跑「下載 → audit → 評估 → 報告」的 safe 半閉環，**不 mutate 任何 model / db**。要 full-auto retrain loop 還缺兩塊：sparring stage 串進 orchestrator、staging-train 解鎖機制。

## 你原本要的整套流程 vs 現況

| 階段 | 狀態 | 備註 |
|---|---|---|
| 1. 自動下載範例棋局 | ✅ 已接 | W9 `--pgn-source-url` lane，記入 `any_network_pgn_download` invariant |
| 2. PGN → per-ply replay | ✅ 已接 | stage 00（W7） |
| 3. Teacher audit gate | ✅ 已接 | stage 00b（W8）exp4+exp5 top-k 共識，accepted / review / rejected 分流 |
| 4. exp4/5 warm-up 訓練 | 🟡 **故意停在 dry-run** | stage 04 hard-coded `--dry-run`（早期定的安全約束）；只印建議指令給人工複核 |
| 5. 自動雙方對戰（多模式） | 🟡 **元件齊但未串進 orchestrator** | sparring smoke + `chess_sparring_to_replay.py` 都在，但 `chess_pipeline_dryrun.py` 還沒把 sparring 當一個 stage 串進去 |
| 6. retrain 後再對戰 | ❌ 無 closed-loop | 因 (4) 不執行，沒有 retrain → 下一輪對戰 |
| 7. 最終聚合報告 | ✅ 已接 | stage 06 PIPELINE_SUMMARY.md，5 個 cross-stage invariants |

## 現在能跑的指令

```
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path /tmp/sample.pgn \
  --pgn-audit-exp4-model-path services/games/models/chess_experiment_4_pv.json \
  --pgn-audit-exp5-model-path services/games/models/chess_experiment_5_nnue.json \
  --output-root /tmp/pipeline_demo
```

或用 `--pgn-source-url <URL>` 取代 `--pgn-path`（會走 W9 的 network download lane，audit gate 仍強制 required）。

最後產出 `06_aggregate/PIPELINE_SUMMARY.md`，含 5 個 cross-stage invariants：

```
- all_stages_diagnostic_only: True
- any_production_runtime_mutation: False
- any_model_mutation: False
- unaudited_imported_dataset_used_for_seed_train: False
- any_network_pgn_download: False / True
```

教學文件：`docs/games/chess_debug/2026-05-12_pipeline_operator_tutorial.md`

## 還沒做的（要 full auto 閉環的話）

1. **把 sparring 接進 orchestrator** — exp4 vs exp5 多模式對戰當 stage 02/03，輸出 replay
2. **解鎖 stage 4 staged training** — 需要新 flag `--execute-staging-train`，之前明令禁止；要做須先設 guardrails：staging model path、artifact diff、人工 ack
3. **retrain → 第二輪 sparring → 對比報告** — diff candidate vs baseline 勝率 / illegal_rate

## 下一步排序建議

| 優先 | 工作 | 風險 |
|---|---|---|
| A | push W9 兩個 commits（穩定當前 milestone） | 低 |
| B | **W10：sparring 接進 orchestrator**（仍 dry-run，只生 replay + report，不 retrain） | 低 |
| C | exp5_18 promotion review / exp4_25 overlay guard | 中（之前候選） |
| D | W11：staging-train 解鎖（需設計人工 ack 機制） | **高，需明確設計討論** |

## 安全契約現況（不變）

- `aggregator_writes_no_models = True`
- `aggregator_writes_no_db = True`
- `aggregator_executes_no_stage = True`
- stage 4 hard-coded `--dry-run`，無法從 CLI 解鎖
- 任何 PGN-derived row 必須先過 teacher audit 才能進 seed_train
- network download 進 local cache，audit gate required = True
