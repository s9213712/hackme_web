# 2026-05-11 Exp4 對齊 Exp3 Exp34 驗收鏈

## 背景

本輪目標是先把 exp4 拉到 exp3 exp34 等級的驗收能力，而不是直接追求 promotion 通過。

前一階段的主要問題：

- exp4 的前台定位是 Policy/Value + MCTS，但 validation 部分仍有路徑會使用一般 fusion / alpha-beta 行為，前台與測試語義不一致。
- quick fixture 產生的後續 filler moves 被誤當成 mistake retention 樣本，導致 retrain 後 probe 可能拿到 `a7a5`、`a5a4` 這類非目標錯題。
- mistake retention probe 會 fallback 到一般樣本，這會污染「模型是否修正舊錯」的證據。
- opening 題型中存在多個合理好棋，例如 `e2e4`、`d2d4`、`c2c4`、`g1f3`，不能把所有非 expected top1 都當成硬失敗。

## 實驗命令

本輪主要實跑命令：

```bash
python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp4 --quick-retrain-gate --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp4_02_mcts_opening_multigood
```

```bash
python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp4 --quick-retrain-gate --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp4_03_retention_fixture_clean
```

```bash
python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp4 --quick-retrain-gate --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp4_04_probe_policy_fixed
```

## 修改項目

### MCTS 決策路徑對齊

`services/games/chess_pv.py` 新增 deterministic root MCTS/PUCT 決策入口：

- `choose_experiment_pv_move(..., decision_mode="mcts")`
- `explain_experiment_pv_decision(..., decision_mode="mcts")`
- 報告輸出 `decision_mode`
- per-move breakdown 輸出 `opening_principle_score`

`scripts/games/chess_live_learning_validation.py` 中 exp4 評估路徑改用 MCTS：

- `_evaluate_move_agreement`
- `_choose_engine_move_for_eval`
- `_engine_decision_breakdown`

這避免前台走 exp4 MCTS，但 validation 走另一套決策語義。

### Opening multi-good credit

新增 opening principle scoring / fallback，並讓 exp4 的 smoke / deterministic top3 對 opening 多好棋有合理 credit。

這個修正的目的不是放寬 promotion gate，而是避免在開局第一步把多個合理候選互相誤判為錯誤。

### Quick fixture 污染修正

`_extract_engine_move_samples_from_records(...)` 現在只把 quick fixture 的第一個 engine move 標成實際 category / expected target。

後續 filler moves 改成：

- `category="fixture_continuation"`
- `quick_expected_move`
- `quick_engine_move_index`
- `is_quick_expected_move`

`_distill_quick_replay_rows(...)` 會排除 quick fixture continuation rows，並輸出：

- `quick_fixture_continuation_rows_excluded`

這修掉了 `a7a5` / `a5a4` 類 continuation move 進入 mistake retention 的問題。

### Mistake retention probe 選樣修正

`_select_mistake_probe_sample(...)` 現在只允許 `category == "mistake_retention"` 的樣本，不再 fallback 到任意樣本。

`_evaluate_mistake_retention_probe(...)` 現在會檢查所有 mistake retention samples：

- 若找到 retrain 後修正舊錯，回傳 `matched_expected`。
- 若沒有新修正，但已學會的舊題仍維持正解，回傳 `retained_expected` 並視為 `learning_signal=true`。
- 未修正的新錯會列在 `unfixed_new_mistakes`，作為診斷資料，不再污染 hard evidence。

## 實跑結果

### exp4_02_mcts_opening_multigood

結果目錄：

```text
/home/s92137/chess_results/exp4_02_mcts_opening_multigood
```

重點結果：

- verdict: `HIGH_RISK`
- deterministic snapshot 可跑，MCTS decision path 已接入。
- opening multi-good 題型明顯改善。
- 仍發現 mistake retention 會選到 fixture continuation，例如 `a7a5`，因此不能作為可信學習證據。

判讀：

exp4 的 MCTS 測試路徑已可運作，但 replay / probe evidence 還被 fixture continuation 污染。

### exp4_03_retention_fixture_clean

結果目錄：

```text
/home/s92137/chess_results/exp4_03_retention_fixture_clean
```

重點結果：

- verdict: `HIGH_RISK`
- total_retrain_seconds: `159.431`
- total_checkpoint_seconds: `472.23`
- total_wall_seconds: `498.734`
- agreement_before: `0.125`
- agreement_after: `0.25`
- checkpoint@10 可修正 `d7d5` 題：
  - probe: `game:900002:ply:1:d7d5`
  - before: `e7e5`
  - after: `d7d5`
  - expected: `d7d5`
- distillation 已排除 continuation rows：
  - checkpoint@10: original_rows `32`, distilled_rows `7`, continuation excluded `24`
  - checkpoint@20: original_rows `68`, distilled_rows `15`, continuation excluded `51`

仍有問題：

- cp20 probe 仍可能選到非 mistake_retention 的 filler target。
- 根因是 probe selector 仍保留 fallback 到一般樣本的邏輯。

判讀：

fixture continuation 已從 distilled replay 排除，但 mistake probe selector 本身仍需要禁止 fallback。

### exp4_04_probe_policy_fixed

結果目錄：

```text
/home/s92137/chess_results/exp4_04_probe_policy_fixed
```

主要報告：

```text
/home/s92137/chess_results/exp4_04_probe_policy_fixed/summary.json
/home/s92137/chess_results/exp4_04_probe_policy_fixed/SUMMARY.md
/home/s92137/chess_results/exp4_04_probe_policy_fixed/exp4/summary.json
/home/s92137/chess_results/exp4_04_probe_policy_fixed/exp4/SUMMARY.md
```

整體結果：

- engine verdict: `HIGH_RISK`
- promotion_gate.passed: `false`
- suitable_for_production_self_learning: `false`
- quick_retrain_gate: enabled
- stochastic auxiliary benchmark: skipped，原因為 `stochastic_auxiliary_disabled_by_quick_retrain_gate`
- held_out_in_training: `false`
- leakage_detected: `false`

時間：

- total_wall_seconds: `722.618`
- total_checkpoint_seconds: `696.397`
- total_retrain_seconds: `153.599`
- avg_retrain_seconds: `76.799`
- deterministic_eval_seconds: `7.01`
- report_write_seconds: `13.252`

Checkpoint evidence：

| checkpoint | duration_seconds | previous_model_hash | new_model_hash | hash_changed |
| --- | ---: | --- | --- | --- |
| trusted=10 | 75.308 | `e2f8530683629e0b20e0e172a55065a41b4dbc2d345b73ebf812da319f8f04f6` | `9f25c4473292788d717d0f6c034b3c91bbd0713b868cf757be49e03deda2d5ef` | true |
| trusted=20 | 78.291 | `9f25c4473292788d717d0f6c034b3c91bbd0713b868cf757be49e03deda2d5ef` | `eab2c328239b98c5258bbc4629d1d47679860bfb4fedf28d7ef00c0ca1163841` | true |

Deterministic strength snapshot：

| model | score | top1 | top3 |
| --- | ---: | ---: | ---: |
| baseline | 0.8693 | 0.8462 | 0.9231 |
| checkpoint@10 | 0.8693 | 0.8462 | 0.9231 |
| checkpoint@20 | 0.8693 | 0.8462 | 0.9231 |
| final | 0.8693 | 0.8462 | 0.9231 |

Mistake retention evidence：

| checkpoint | probe_case_id | before | after | expected | result | learning_signal |
| --- | --- | --- | --- | --- | --- | --- |
| trusted=10 | `game:900001:ply:1:e7e5` | `e7e5` | `e7e5` | `e7e5` | `retained_expected` | true |
| trusted=20 | `game:900002:ply:1:d7d5` | `e7e5` | `d7d5` | `d7d5` | `matched_expected` | true |

這代表本輪至少已證明：

- probe 不再被 fixture continuation 污染。
- exp4 retrain 後模型檔確實改變。
- cp20 對 `d7d5` 舊錯題有直接修正證據。
- cp10 可保留已學過的 `e7e5` 題。

但這仍不足以 promotion，因為 hash change 與單題修正不能代表整體棋力通過。

## 失敗原因

exp4_04 仍為 `HIGH_RISK`，主要原因：

- deterministic score 沒有高於 baseline。
- sanity exact FEN / seen variants / clean held-out variants 仍低於 gate 門檻。
- trusted=10 與 trusted=20 都出現 `sanity final decision learning failed`。
- hard flank capability gap 仍未解。
- report 標記 catastrophic regression，原因來自 checkpoint instability / sanity learning failure，而不是非法步或 tactic/blunder 退步。

具體觀察：

- exp4 現在可以學到部分 opening target，但對 `c7c5`、`d7d5`、`e7e5` 這類相近 opening candidate 的 margin 還不夠穩。
- 多好棋 credit 對 smoke / balanced gate 是合理的，但 sanity learning 若是明確錯題修正，仍應要求 expected target，而不能只靠 top3 合理候選放行。
- hard flank 題雖然 raw policy 可把 `c7c5` 排上來，但 final decision 仍會選 `d7d5`，代表 flank contextual decision 還沒穩定。

## 結果判讀

本輪達成的是「exp4 驗收鏈對齊 exp3 exp34」，不是「exp4 棋力 promotion」。

已達成：

- exp4 前台與 validation 都可走 MCTS decision mode。
- quick retrain gate 可產生 checkpoint@10 / checkpoint@20。
- deterministic snapshot、smoke gate、mistake retention、safe checkpoint、semantic audit 均可產出 artifact。
- fixture continuation 不再污染 distilled replay 或 mistake retention。
- report 能區分 `retained_expected` 與 `matched_expected`。

尚未達成：

- final decision learning 還不穩。
- exact target learning 與 opening multi-good credit 還需要分清楚使用場景。
- hard flank contextual learning 還沒達到 promotion hard evidence。
- deterministic score 沒有實質提升。

## 未來修正方向

下一步不要再先擴大 self-play，也不要降低 gate。

建議優先修：

1. exp4 policy override margin
   - high-confidence policy override 不應在 margin 為 0 或 opening 多好棋分數打平時覆蓋 final decision。
   - 明確錯題修正應要求 expected move margin 轉正。

2. opening target 分離
   - smoke / balanced gate 可接受多好棋 top3。
   - mistake retention / sanity learning 必須檢查指定 expected move 是否真的變成 top1 或至少 margin 明確提升。

3. c/d/e pawn semantic tie-break
   - 對 `c7c5`、`d7d5`、`e7e5` 建立 exp4 專用 opening target anchors。
   - 報告 raw policy margin、MCTS visit/value、final chosen reason。

4. hard flank contextual audit
   - 區分 raw policy 已學但 MCTS 不採納，或 raw policy 本身未學。
   - 若 static/search 認為 hard flank 不優，該 case 應進 audit，而不是直接當 promotion hard blocker。

5. 時間優化
   - retrain 約 154 秒，不是唯一瓶頸。
   - checkpoint evaluation 約 696 秒，後續應優先做 exp4 evaluation cache / smoke early stop 分級。

## 適用範圍

本輪修改主要適用 exp4。

同步影響：

- validation script 的 fixture / mistake probe 修正對 exp3 也有正面效果，因為它避免 quick fixture continuation 污染 retention evidence。
- exp4 的 MCTS decision mode、opening principle score、MCTS explain breakdown 是 exp4 專屬，不應直接套到 exp3。

## 結論

exp4 已經接到與 exp3 exp34 同等級的可審計驗收流程，但目前不應 promotion。

目前可信結論是：

- 模型檔會變。
- retrain 後能修正至少一個明確舊錯。
- fixture / probe evidence 已比前一版乾淨。
- 但整體 deterministic learning、sanity generalization、hard flank contextual decision 尚未通過。

因此 exp4 下一輪應專注於「指定錯題 target margin 與 MCTS final decision 對齊」，而不是擴大資料或放寬 gate。
