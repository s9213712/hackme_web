# exp4_18：full broad learning diagnostic + e_pawn gate accounting fix

## 上一輪問題

exp4_17 已把 special-rule subtype 與 choose/explain consistency 清乾淨：

- special-rule deterministic gate：`7/7`
- castling short/long、en-passant、promotion subtype 都能被 final path 採用
- low-margin override 不再被計入 learning success

但 exp4_17 使用 `--quick-retrain-skip-heavy-sanity`，只能證明「已知 gate accounting 問題修掉」，不能證明 broad learning / generalization。

## 本輪目標

本輪不再追 special-rule，而是跑一輪不跳過 heavy sanity 的 exp4 診斷，確認真正 blocker 是哪一層：

- raw policy 是否真的泛化
- final decision 是否擋住已學會的 policy
- e_pawn / flank blocker 是否為真模型問題或 gate label 問題
- checkpoint retention 是否穩定
- full sanity 實際成本是否可接受

## 實驗命令

Full diagnostic：

```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --output-root <chess_results>/exp4_18_full_broad_learning_diagnostic
```

修正 e_pawn gate accounting 後的 quick confirmation：

```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --quick-retrain-skip-heavy-sanity \
  --output-root <chess_results>/exp4_18_e_pawn_gate_accounting_fix
```

## 實際結果

### Full diagnostic

結果目錄：

- `<chess_results>/exp4_18_full_broad_learning_diagnostic`

結果：

- verdict：`HIGH_RISK`
- promotion_gate：false
- checkpoint@10 / checkpoint@20 都完成 full sanity
- selected_safe_checkpoint：`cp20`
- mistake retention：通過
- special-rule gate：`7/7`

Timing：

| metric | seconds |
|---|---:|
| total_wall_seconds | 2438.614 |
| total_checkpoint_seconds | 2264.592 |
| retrain_seconds | 92.685 |
| deterministic_eval_seconds | 75.923 |

判讀：

- retrain 不是主要瓶頸。
- full sanity 的 final decision seen/unseen before/after 評估才是最大成本。
- raw policy batch 很快，final decision path 因融合/search 成本高。

### Deterministic snapshot

| model | score | top1 | top3 | mistake_retention | endgame |
|---|---:|---:|---:|---:|---:|
| baseline | 0.8693 | 0.8462 | 0.9231 | 0.4333 | 1.0 |
| checkpoint@10 | 0.8693 | 0.8462 | 0.9231 | 0.6667 | 0.65 |
| checkpoint@20 | 0.8693 | 0.8462 | 0.9231 | 0.6667 | 0.65 |
| final | 0.8693 | 0.8462 | 0.9231 | 0.6667 | 0.65 |

判讀：

- mistake retention category 變好。
- endgame category 退步。
- 總分打平 baseline，不能證明 broad strength improvement。

### Sanity learning

| checkpoint | exact | seen | unseen | raw generalization | final generalization |
|---|---:|---:|---:|---:|---:|
| trusted=10 | pass | 0.4653 | 0.3968 | 0.4667 | 0.4333 |
| trusted=20 | pass | 0.4823 | 0.3889 | 0.4195 | 0.4382 |

判讀：

- exact FEN 會。
- seen/unseen variants 都未達泛化門檻。
- cp20 沒有比 cp10 穩定變好。
- learning_signal=false 合理。

### Mistake retention

| checkpoint | before | after | expected | result |
|---|---|---|---|---|
| trusted=10 | `e7e5` | `d7d5` | `d7d5` | matched_expected |
| trusted=20 | `e7e5` | `e7e5` | `e7e5` | retained_expected |

判讀：

- targeted correction / retention 是正向訊號。
- 但它仍只是局部證據，不能覆蓋 broad generalization failure。

### e_pawn 診斷

full diagnostic 原本列出：

- `true_e_pawn_final_decision_blocked_count_nonzero (4)`

逐案檢查後發現 4 筆都來自兩個 easy opening cases，在 cp10/cp20 各出現一次：

- `gate_e_pawn_easy_002`：`1.Nf3` 後要求黑走 `e7e5`，模型走 `d7d5`
- `gate_e_pawn_easy_003`：`1.c3` 後要求黑走 `e7e5`，模型走 `d7d5`

判讀：

- 這不是明確壞棋。
- 在 quiet opening 後 `d7d5` 是合理中央回應。
- 這應列為 opening multi-good / gate label accounting，不應作為 e_pawn learning failure。

## 修改項目

### e_pawn opening-book equivalence

修改 `scripts/games/chess_live_learning_validation.py`：

- 對正式 gate template 的 `easy` black opening e-pawn case，若 expected=`e7e5`，但模型選擇 `d7d5` / `c7c5` / `g8f6` 等 `OPENING_BLACK_CANDIDATES`，可列為 `opening_multi_good_tie`。
- 條件收窄為必須是正式 template easy case，避免 synthetic/no-template case 被誤放行。
- `opening_label_audit` 同步加入 `opening_book_shadow`，避免 clean true failure 被 quiet-opening 多好棋污染。

驗證後，用 exp4_18 full summary 重新套新 classifier：

| item | before | after |
|---|---:|---:|
| true_e_pawn_raw_policy_fail | 0 | 0 |
| true_e_pawn_final_decision_blocked | 4 | 0 |
| opening_multi_good_tie | 0 | 4 |
| e_pawn_equivalent_credit_pass_rate | 0.7778 | 1.0 |

### Quick confirmation

結果目錄：

- `<chess_results>/exp4_18_e_pawn_gate_accounting_fix`

結果：

- verdict：`PARTIAL`
- promotion_gate：false
- `true_e_pawn_final_decision_blocked_count_nonzero` 已不再出現在 gate reasons
- special-rule 仍為 `7/7`
- deterministic final 仍為 `0.8693`
- heavy sanity skipped，所以不可 promotion

Timing：

| metric | seconds |
|---|---:|
| total_wall_seconds | 323.552 |
| total_checkpoint_seconds | 176.387 |
| retrain_seconds | 91.235 |
| deterministic_eval_seconds | 58.771 |

## 結果判讀

本輪修掉的是一個假 blocker，不是棋力提升：

- e_pawn easy opening 多好棋不該被當成 failure。
- special-rule 已經穩定，不應再投入下一輪主修。
- exp4 目前仍沒有 broad learning evidence。

真正 blocker：

- deterministic final 沒超 baseline。
- full sanity unseen 仍只有約 `0.39`。
- cp20 沒有穩定優於 cp10。
- hard flank 仍是 general-model blocker，但已排除出 opening-specialist gate。
- full sanity 成本太高，不適合每次小修都跑。

## 下一步方向

下一輪不應再調 special-rule 或 e_pawn accounting。

建議聚焦：

1. broad learning / generalization：找出為什麼 exact FEN 會、seen/unseen 不會。
2. endgame retention：deterministic total 打平 baseline 的主因之一是 endgame score 從 `1.0` 掉到 `0.65`。
3. final sanity cost：full sanity 應改成分層，cheap gate 過後才跑全量 seen/unseen；否則單輪 40 分鐘不利迭代。
4. hard flank：只在 general-model 路線繼續處理，opening-specialist 不應被它阻擋。
