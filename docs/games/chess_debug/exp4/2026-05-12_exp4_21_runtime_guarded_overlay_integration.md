# exp4_21：Runtime Guarded Overlay Integration Draft（2026-05-12）

## 上一輪問題

exp4_20 證明 no-label runtime simulator 能重現 exp4_19 的 guarded overlay 分數：

- baseline：`0.8693`
- full final replacement：`0.8693`
- runtime guarded simulator：`0.9231`
- unsafe override：`0`

但 exp4_20 仍只是 validation simulator，沒有接到真正前台 / production choose path。

## 本輪目標

exp4_21 只做 integration draft，不做 promotion：

1. 把 guard 抽成 runtime 與 validation 共用 helper。
2. guard input 只包含 runtime-feasible sanitized 欄位。
3. 前台 exp4 choose path 可透過 env flag 啟用 guarded overlay。
4. 預設仍關閉，不改 production 行為。

## 修改項目

新增：

- `services/games/chess_pv_guarded_overlay.py`

核心 API：

- `exp4_runtime_overlay_allows_final(...)`
- `exp4_promotion_subtype_guard(...)`
- `choose_experiment_pv_guarded_overlay_move(...)`
- `guarded_overlay_enabled()`

Runtime flag：

```bash
HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY=1
HTML_LEARNING_CHESS_EXP4_OVERLAY_CANDIDATE_MODEL_PATH=/path/to/exp4_candidate.json
```

預設：

- `HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY` 未設定時，前台 exp4 仍走原本 `choose_experiment_pv_move(...)`。
- 只有明確設定 flag 時才進 guarded overlay path。

## Guard 輸入限制

Guard 不接受完整 deterministic row，不可讀：

- `expected_best_moves`
- `top1_correct`
- `candidate_pass`
- `positive_override_after_scoring`
- `prevented_regression_after_scoring`
- benchmark labels

Guard 只接受：

- `fen`
- `side`
- `baseline_move_uci`
- `final_move_uci`
- `baseline_score_cp`
- `final_score_cp`
- `final_illegal`

若 runtime 沒有提供 score，helper 會用共用 deterministic material/static scoring 補上；若仍無法取得 score，預設 fallback，不放行。

## 前台串接

`routes/games.py::choose_computer_move(...)`：

- exp4 difficulty 預設仍呼叫 `choose_experiment_pv_move(...)`
- 若 `guarded_overlay_enabled()` 為 true，改呼叫 `choose_experiment_pv_guarded_overlay_move(...)`
- overlay helper 會：
  - 用 baseline model 產生 baseline move
  - 用 candidate model 產生 final move
  - 用 shared no-label guard 決定是否採用 final
  - guard fail 時 fallback baseline

## 實跑結果

結果目錄：

```text
/home/s92137/chess_results/exp4_21_runtime_guarded_overlay_integration
```

驗證模式：

- `validation_mode=quick_retrain_gate`
- 使用 `--quick-retrain-skip-heavy-sanity`
- `overall_verdict=PARTIAL`
- `promotion_gate.passed=false`

時間：

| 指標 | 數值 |
| --- | ---: |
| `total_wall_seconds` | `329.788` |
| `total_checkpoint_seconds` | `178.993` |
| `retrain_seconds` | `92.089` |
| `deterministic_eval_seconds` | `60.061` |

Runtime guarded overlay：

| 指標 | 數值 |
| --- | ---: |
| baseline score | `0.8693` |
| full final replacement score | `0.8693` |
| runtime guarded score | `0.9231` |
| delta vs baseline | `+0.0538` |
| `same_move` | `10` |
| `runtime_guard_allowed` | `2` |
| `runtime_guard_fallback` | `1` |
| `positive_override_after_scoring` | `1` |
| `prevented_regression_after_scoring` | `1` |
| `unsafe_override_after_scoring` | `0` |
| `candidate_worth_runtime_overlay` | `true` |
| `diagnostic_uses_expected_labels_for_decision` | `false` |

關鍵 case：

- `mistake_retention_game_900002_ply_1`：baseline `e7e5`，candidate `d7d5`，guard 採用 final，原因 `runtime_static_and_rule_guard_passed`。
- `promotion_white`：baseline `e7e8q`，candidate `e7e8n`，guard fallback baseline，原因 `nonqueen_promotion_downgrade_without_runtime_tactical_reason`。

Runtime helper direct smoke：

- `mistake_retention_d7d5`：`d7d5`
- `promotion_white_fallback`：`e7e8q`

Special-rule gate：

- `special_rule=7/7`
- `unsafe_override_count=0`

## 目前狀態

這是 integration draft：

- production 預設不啟用。
- quick targeted gate 已確認 shared no-label guard 仍重現 exp4_20 的 `0.9231`。
- 尚未跑 full broad diagnostic。
- 仍不可 promotion。

下一輪要跑：

1. route-level / service-level test，確認 flag off 不改行為，flag on 才走 overlay。
2. full broad diagnostic，確認 guarded actual path 不引入 unseen regression。
3. 若 full diagnostic 維持 `runtime_guarded_score > baseline` 且 `unsafe_override=0`，再討論 guarded overlay promotion。

## 判讀

exp4_21 的意義不是證明棋力已可上線，而是把 exp4_20 的 no-label simulator 轉成可驗證的 runtime draft。這輪 quick targeted gate 已經維持：

- runtime guarded score `0.9231`
- delta vs baseline `+0.0538`
- unsafe override `0`
- special-rule `7/7`

但因為 heavy sanity 仍 skipped，promotion 仍必須是 false。下一步如果 full diagnostic 也能維持：

- runtime guarded score > baseline
- unsafe_override_count = 0
- special_rule = 7/7
- promotion subtype regression 被 fallback
- mistake retention positive override 保留

才可以討論 guarded overlay promotion。
