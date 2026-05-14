# EXP33 - Failed Smoke Anchor Microdiagnosis + Safe Checkpoint Retention

## 前一個實驗暴露的問題

Exp32 修正了 development smoke scoring 的假失敗，development 從 strict `0/2` 變成 multi-good credit 後 `2/2`。剩下的 blocker 已經不是 gate scoring，而是三個真問題：

- `e_pawn_central_break=0/2`。
- `flank_pawn_push=0/2`，且 smoke anchors 已分層，不是全部 hard case。
- checkpoint@20 mistake retention repeated old mistake；exp32 rehearsal 有跑但 `repair_success=false`。

## 實驗目標與要求

目標不是讓 promotion 通過，而是把 smoke failure 與 retention failure 變成可定位、可修復、可 fallback 的流程。

要求：

- 保留 exp30a leakage guard、evaluation cache、smoke early stop。
- 保留 exp31 semantic loss budget scheduler。
- 保留 exp32 development multi-good credit 與 flank stratified smoke anchors。
- 不降低 gate、不把 `kingside_aggression` 放回 balanced hard gate。
- 不用 train/seen performance、`hash_changed` 或 replay loss 當 learning success。
- 對 8 個 smoke anchors 輸出 microdiagnosis。
- 對 e_pawn/flank failed anchors 做 isolated overfit probe。
- cp20 retention fail 時不可繼續選 cp20 當 final candidate。

## 實驗命令完整全文

```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root <chess_results>/exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention
```

## 分析及修改項目

- 新增 smoke anchor microdiagnosis 欄位：
  - `expected_raw_score`。
  - `expected_final_score`。
  - `search_best_move`。
  - `decision_path_reason`。
  - `failure_type`。
- 新增 `e_pawn` dampening audit：
  - `e_pawn_update_count`。
  - `e_pawn_consumed_budget`。
  - `e_pawn_effective_gradient_norm`。
  - `e_pawn_margin_before_after`。
  - `dampening_trigger_reason`。
  - `dampening_applied_steps`。
  - `possibly_overapplied`。
- 新增 failed anchor isolated overfit probe：
  - 針對失敗的 e_pawn/flank smoke anchors。
  - 使用 exact FEN + 4 個近似 variants。
  - expected move 作 positive，top competing moves 作 hard negatives。
  - 輸出 raw/final top1 before/after、expected rank before/after、variant pass rate。
- 強化 mistake retention repair：
  - rehearsal rows 從 8 增為 12。
  - anchor weight 從 3.0 增為 5.0。
  - max samples 從 16 增為 24。
- 新增 `safe_checkpoint_selection`：
  - cp20 retention pass 才能選 cp20。
  - cp20 fail 但 cp10 pass 時，final fallback 到 cp10。
  - cp10/cp20 都 fail 時，`selected_safe_checkpoint=none`。
- final model selection 改用 safe checkpoint，不再讓 known failed-retention cp20 直接當 final。

## 修改後實際結果

結果目錄：

`<chess_results>/exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention`

總體：

| 指標 | 結果 |
| --- | --- |
| verdict | `HIGH_RISK` |
| promotion_gate.passed | `false` |
| total_wall_seconds | `211.779` |
| total_checkpoint_seconds | `149.043` |
| retrain_seconds | `47.683` |
| deterministic_eval_seconds | `55.186` |
| specialist_probe_seconds | `0.0` |
| skipped_eval_seconds_estimate | `125.68` |

Smoke gate：

| Checkpoint | Smoke pass | e_pawn | d_pawn | flank | development |
| --- | ---: | ---: | ---: | ---: | ---: |
| cp10 | `0.375` | `0/2` | `1/2` | `0/2` | `2/2` |
| cp20 | `0.25` | `0/2` | `0/2` | `0/2` | `2/2` |

e_pawn dampening audit：

| Checkpoint | update_count | consumed_budget | gradient_norm | margin_delta | dampened | possibly_overapplied |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| cp10 | `720` | `432.0` | `281.34` | `29.2218` | `e_pawn_central_break` | `false` |
| cp20 | `720` | `432.0` | `281.34` | `11.6758` | `e_pawn_central_break` | `false` |

Isolated overfit probe：

| Case | Semantic | cp10 isolated exact | cp10 variants | cp20 isolated exact | cp20 variants | 判讀 |
| --- | --- | --- | ---: | --- | ---: | --- |
| `gate_e_pawn_easy_001` | e_pawn | `true` | `1.0` | `true` | `1.0` | isolated 可學，mixed fail 偏 scheduler/interference |
| `gate_e_pawn_hard_001` | e_pawn | `false` | `1.0` | `false` | `1.0` | raw policy 會到 rank1，但 final decision 仍擋住 |
| `gate_flank_easy_001` | flank | `true` | `0.75` | `true` | `0.75` | isolated 可學，mixed fail 偏 scheduler/interference |
| `gate_flank_hard_001` | flank | `false` | `0.25` | `false` | `0.25` | isolated 也失敗，偏 label/feature/decision path 問題 |

cp20 mistake retention stronger repair：

| Checkpoint | before | after | expected | stronger_repair_applied | after_repair | repair_success |
| --- | --- | --- | --- | --- | --- | --- |
| cp10 | `b8a6` | `e7e5` | `e7e5` | `false` | `null` | `false` |
| cp20 | `f8a3` | `f8a3` | `a7a5` | `true` | `f8a3` | `false` |

Safe checkpoint selection：

| Checkpoint | retention_pass | result_kind | selected |
| --- | --- | --- | --- |
| cp10 | `true` | `matched_expected` | `cp10_fallback` |
| cp20 | `false` | `repeated_old_mistake` | rejected |

Final model hash 改為 cp10 fallback hash：

`795597604ad8cabce2777b2c6c57c093860643f853717b8b8a35259710a2f46b`

## 結果判讀

Exp33 有效，因為它把三個 blocker 分清楚了：

- easy e_pawn 與 easy flank 單獨訓練能學會，mixed gate 失敗不是 label 完全錯，而是 scheduler / multi-task interference / budget allocation 問題。
- hard e_pawn raw policy 可被推到 rank1，但 final decision 仍選原本 move，這是 final decision path 或 static/search blocker。
- hard flank isolated 也無法修正，代表該類 case 可能需要重新 label audit 或更強 context feature，不該只加 rehearsal。
- cp20 stronger repair 仍失敗，所以 safe checkpoint 正確 fallback 到 cp10；promotion 仍 false 合理。

這輪也暴露新事實：cp20 不只 retention fail，還讓 smoke gate 從 cp10 `0.375` 退到 cp20 `0.25`，d_pawn 從 `1/2` 掉到 `0/2`，因此 cp20 不能作為 final candidate。

## 未來修正方向

- 對 easy e_pawn/easy flank：修 mixed scheduler 或 per-semantic rehearsal，因為 isolated 已證明可學。
- 對 hard e_pawn：檢查 final decision path，raw policy rank1 仍不被採納，重點是 search/static/fusion blocker。
- 對 hard flank：回到 label/context audit，確認該 hard flank 是否真應作 balanced hard target。
- 對 cp20 retention：不要再只加同型 rehearsal；需要針對 `a7a5` vs `f8a3` 的 decision breakdown 或 checkpoint rollback policy。

## 適用 exp3 / exp4

本輪實跑是 exp3。`safe_checkpoint_selection`、smoke microdiagnosis、development multi-good smoke scoring 屬於 validation/report layer，概念上適用 exp4；isolated overfit probe 對 exp4 已有 `train_experiment_pv_from_replay_samples` path，但本輪沒有 exp4 實跑數據。
