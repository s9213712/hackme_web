# exp4_17：special-rule subtype + choose/explain consistency

## 上一輪問題

exp4_16 已修掉「raw policy 學會 special move，但 final decision 不採用」的 blocker：

- short castle：final 從 `d2d4` 改成 `e1g1`
- en-passant：final 穩定採用 `d5e6`
- special-rule deterministic gate：`6/7`

但 exp4_16 仍暴露兩個問題：

1. special-rule family 會對，但 subtype 不穩。
   - castling 可能把 expected `e1g1` / `e8g8` 選成 queenside castling。
   - promotion 可能把 expected queen / knight / rook subtype 混掉。
2. sparring artifact 出現 choose / explain 不一致風險。
   - 同一 FEN + model + profile 下，實際 move 和 audit row 可能不同。
   - 這會讓 sparring audit 無法解釋實際對局。

## 本輪指令與目標

先專注 exp4 學習力，不把 sparring 勝負當棋力結論。

本輪目標：

- 處理已知問題後再測本次試驗。
- 修 special-rule subtype selection。
- 新增 exp4 fixed-depth profile，降低 time-budget variance。
- 補 choose/explain consistency tests。
- 不降低 promotion gate。
- 不把 diagnostic quick gate 當正式 promotion evidence。

## 修改項目

### 1. special-rule subtype

`services/games/chess_pv.py` 的 `_special_rule_type()` 從 family-level 改成 subtype-level：

- `castling_short`
- `castling_long`
- `en_passant`
- `promotion_queen`
- `promotion_knight_mate`
- `underpromotion_knight`
- `underpromotion_bishop`
- `underpromotion_rook`
- `underpromotion_rook_avoid_stalemate`

同時新增：

- `rule_family`
- `rule_subtype`
- subtype-specific bonus table

### 2. subtype selection priority

rule-aware final fusion 在 guard 通過後，排序改成優先尊重 raw policy rank，再看 subtype bonus / adjusted score。

原因：

- exp4_16 中 `e7e8n` raw rank=1，但 generic underpromotion bonus + opening score 讓 `e7e8r` 被選上。
- 這不是「不會 promotion」，而是 family-level scoring 蓋掉 subtype。

修正後：

- `promotion_white_knight_mate` 會選 `e7e8n`
- `promotion_white_queen` 仍選 `e7e8q`

### 3. deterministic fixed-depth profile

新增 exp4 search profiles：

- `fixed_depth_fast`
- `fixed_depth_balanced`
- `fixed_depth_strong`

這些 profile 的 `time_budget_ms=None`。

目的不是提升棋力，而是讓 diagnostic / sparring / choose-explain audit 更可重現。

### 4. choose/explain consistency

新增 tests：

- rule-aware fusion 保留 special-rule subtype。
- choose path 與 explain path 在 special-rule cases 上必須選同一手。
- rule-aware final fusion 成功後，ordinary policy override 不可覆蓋 final move。
- raw rank > 3 或 search guard 明確反對時不可套 rule bonus。

## 實跑命令

```bash
python3 -m py_compile /home/s92137/hackme_web/services/games/chess_pv.py /home/s92137/hackme_web/tests/games/test_games.py
PYTHONPATH=/home/s92137/hackme_web pytest /home/s92137/hackme_web/tests/games/test_games.py -q -k 'rule_aware or special_rule_consistency'
PYTHONPATH=/home/s92137/hackme_web pytest /home/s92137/hackme_web/tests/scripts/games/test_chess_live_learning_validation_script.py -q
PYTHONPATH=/home/s92137/hackme_web pytest /home/s92137/hackme_web/tests/games/test_games.py -q
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp4 --quick-retrain-gate --quick-retrain-max-samples 64 --quick-retrain-max-seconds 90 --quick-retrain-skip-heavy-sanity --output-root /home/s92137/chess_results/exp4_17_special_rule_subtype_consistency
```

## 測試結果

- `py_compile`：pass
- targeted rule-aware tests：5 passed
- validation script tests：pass
- games tests：63 passed
- diagnostic quick gate：完成，verdict=`PARTIAL`

結果目錄：

- `/home/s92137/chess_results/exp4_17_special_rule_subtype_consistency`

## 量化結果

### Timing

- total_wall_seconds：`316.629`
- total_checkpoint_seconds：`171.633`
- retrain_seconds：`88.36`
- deterministic_eval_seconds：`57.615`
- skipped_eval_seconds_estimate：`156.626`

本輪用了 `--quick-retrain-skip-heavy-sanity`，所以不能作 promotion evidence。

### Deterministic snapshot

| model | overall | top1 | top3 | mistake_retention_score |
|---|---:|---:|---:|---:|
| baseline | 0.8693 | 0.8462 | 0.9231 | 0.4333 |
| checkpoint@10 | 0.8693 | 0.8462 | 0.9231 | 0.6667 |
| checkpoint@20 | 0.8693 | 0.8462 | 0.9231 | 0.6667 |
| final | 0.8693 | 0.8462 | 0.9231 | 0.6667 |

判讀：

- deterministic score 沒退步，但也沒有高於 baseline。
- mistake retention category 有改善。
- 不能宣稱 broad strength improvement。

### Special-rule deterministic gate

`7/7 = 1.0`

| case | expected | chosen | result |
|---|---|---|---|
| castle_short_white | `e1g1` | `e1g1` | pass |
| castle_long_white | `e1c1` | `e1c1` | pass |
| en_passant_white_take | `d5e6` | `d5e6` | pass |
| promotion_white_queen | `e7e8q` | `e7e8q` | pass |
| promotion_white_knight_mate | `e7e8n` | `e7e8n` | pass |
| underpromotion_rook_avoid_stalemate | `g7g8r` / `g7g8q` | `g7g8r` | pass |
| en_passant_not_available | legal non-e.p. move | `e2e4` | pass |

這是本輪主要正向結果：exp4_16 的 `6/7` 已修成 `7/7`。

### Rule-aware final fusion targeted cases

- targeted cases：2
- passes_after：2
- guard_passed：2
- opening_push_suppressed：2
- final_move_changed：1

逐案：

- `targeted_castle_short_white_italian`
  - before final：`d2d4`
  - after final：`e1g1`
  - raw top1：`e1g1`
  - rule bonus：420
  - guard：pass

- `targeted_en_passant_white_take`
  - before final：`d5e6`
  - after final：`d5e6`
  - raw top1：`d5e6`
  - rule bonus：420
  - guard：pass

### Mistake retention

- checkpoint@10：`matched_expected`
  - before：`e7e5`
  - after：`d7d5`
  - expected：`d7d5`

- checkpoint@20：`retained_expected`
  - before：`e7e5`
  - after：`e7e5`
  - expected：`e7e5`

判讀：

- old mistake correction / retention 本輪正常。
- 沒有 cp20 repeated old mistake。

## Gate 結果

- overall verdict：`PARTIAL`
- promotion_gate：false
- opening_specialist_gate：false
- general_model_promotion_gate：false

主要 blockers：

- heavy sanity skipped，不能證明 broad learning。
- deterministic final 沒高於 baseline。
- opening final decision alignment 仍 unresolved。
- low-margin override 仍不可算 learning success。
- balanced_fusion final decision generalization below threshold。
- hard flank capability gap remains unresolved。

## Gate Accounting Cleanup

修完 subtype 後又補了一個 evidence accounting cleanup，避免已知 diagnostic 被錯誤列為 opening blocker。

結果目錄：

- `/home/s92137/chess_results/exp4_17_gate_accounting_cleanup`

修正內容：

1. low-margin override 只要 `low_margin_override_counted_success_count=0`，就只列為 non-blocking note。
   - 它可以用於 move ordering。
   - 但不可算 learning success。
   - 之前「有被 applied」就列入 blocker，屬於過度阻擋。

2. opening final decision alignment 排除 `mistake_retention` rows。
   - mistake retention 由 retention probe / deterministic category 管。
   - 不應把 `mistake_retention_game_900001_ply_3` 的 raw_policy_fail 算成 opening alignment 失敗。

重跑結果：

- result dir：`/home/s92137/chess_results/exp4_17_gate_accounting_cleanup`
- verdict：`PARTIAL`
- promotion：`false`
- special-rule：`7/7`
- opening_final_decision_alignment_passed：`true`
- opening_alignment_case_count：`3`
- opening_alignment_failure_type_counts：`{passed: 2, multi_good_tie_not_failure: 1}`
- mistake_retention_rows_excluded_from_opening_alignment：`3`
- low_margin_override_applied_count：`4`
- low_margin_override_counted_success_count：`0`

被移除的錯誤 blockers：

- `exp4 opening low-margin policy override was applied; cannot count as learning success`
- `exp4 opening final decision alignment failed or remains unresolved`

仍保留的真 blockers：

- targeted mistake retention 不能單獨證明 broad deterministic strength improvement。
- deterministic final 沒高於 baseline。
- heavy sanity diagnostics skipped。
- balanced_fusion final decision generalization below threshold。
- hard flank capability gap remains unresolved。

## 結果判讀

本輪成功處理的是 special-rule subtype / audit consistency 層問題：

- promotion subtype 從 `e7e8r` 修到 `e7e8n`。
- special-rule gate 從 `6/7` 變 `7/7`。
- fixed-depth profile 與 choose/explain consistency tests 已補上。
- low-margin override 與 opening alignment 的 gate accounting 已修正。

但本輪沒有證明 exp4 broad learning：

- deterministic final 與 baseline 持平。
- heavy sanity 被跳過。
- opening / generalization blockers 仍在。

因此本輪是「special-rule subtype 修正成功」而不是「promotion-ready」。

## 下一步方向

1. 不要再泛化加 special-rule anchors。
   - 目前 special-rule 7/7，先保留。

2. 下一步回到 exp4 學習力主線：
   - opening final decision alignment。
   - low-margin override evidence cleanup。
   - broad generalization / unseen variants。

3. 若要繼續 sparring：
   - exp4 必須使用 `fixed_depth_*` profile。
   - smoke seed 要標 `diagnostic_only`，不能作 strength evidence。

4. 若要正式驗收：
   - 必須跑不跳 heavy sanity 的 full gate。
   - 目前這輪 skip-heavy 只能作 targeted diagnostic。
