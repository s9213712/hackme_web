# exp4_22：Actual Runtime Guarded Overlay Full Diagnostic（2026-05-12）

## 上一輪問題

exp4_21 已把 guarded overlay 接到前台 runtime choose path，但仍有兩個缺口：

1. validation 主要仍是 simulator report，沒有逐 case 呼叫 actual runtime helper。
2. full sanity 尚未跑，因此 broad generalization 是否仍擋住 guarded overlay promotion 不清楚。

## 本輪目標

exp4_22 不做 retrain 架構大改，先修 evidence path：

- 讓 validation 產出 `exp4_actual_runtime_guarded_overlay`，直接呼叫 `choose/explain_experiment_pv_guarded_overlay_decision(...)`。
- 比對 actual runtime helper 與 simulator 選擇是否一致。
- 跑 quick targeted gate 與不跳 heavy sanity 的 full diagnostic。
- 釐清目前 blocker 是 runtime overlay 本身、full final replacement、還是 gate 評估對象不一致。

## 修改項目

新增 / 修改：

- `services/games/chess_pv_guarded_overlay.py`
  - 新增 `explain_experiment_pv_guarded_overlay_decision(...)`，回傳 selected move、baseline/final move、guard reason、guard detail。
  - `choose_experiment_pv_guarded_overlay_move(...)` 改用 explain helper，避免 choose path 與 audit path 分叉。
- `scripts/games/chess_live_learning_validation.py`
  - 新增 `exp4_actual_runtime_guarded_overlay` report。
  - actual report 會逐 deterministic case 呼叫 runtime helper，並記錄 `simulator_selected_mismatch_count`。
  - 新增 `guarded_overlay_sanity` 派生欄位：用已算好的 before/after sanity variants 套 no-label guard，避免再跑一次昂貴 search。
- `tests/scripts/games/test_chess_live_learning_validation_script.py`
  - 新增 runtime helper 測試，確認 helper 使用真實 board state，而不是只依賴 `__fen__` 或起始局面。

## 實驗命令

Quick targeted gate：

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --quick-retrain-skip-heavy-sanity \
  --output-root /home/s92137/chess_results/exp4_22_actual_runtime_guarded_overlay_quick
```

Full diagnostic：

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --output-root /home/s92137/chess_results/exp4_22_actual_runtime_guarded_overlay_full
```

## Quick 結果

結果目錄：

```text
/home/s92137/chess_results/exp4_22_actual_runtime_guarded_overlay_quick
```

核心數據：

| 指標 | 數值 |
| --- | ---: |
| engine verdict | `PARTIAL` |
| promotion | `false` |
| baseline score | `0.8693` |
| full final replacement score | `0.8693` |
| simulator guarded score | `0.9231` |
| actual runtime guarded score | `0.9231` |
| delta vs baseline | `+0.0538` |
| unsafe override | `0` |
| simulator selected mismatch | `0` |
| special-rule | `7/7` |
| total wall seconds | `333.077` |

關鍵 case：

- `mistake_retention_game_900002_ply_1`：baseline `e7e5`，final `d7d5`，actual runtime guard 採用 final。
- `promotion_white`：baseline `e7e8q`，final `e7e8n`，actual runtime guard fallback baseline。

判讀：

- actual runtime helper 與 simulator 完全一致。
- 這證明 exp4_21 的 runtime integration 沒有產生 choose-path drift。
- 但 quick 使用 `--quick-retrain-skip-heavy-sanity`，仍不能 promotion。

## Full Diagnostic 結果

結果目錄：

```text
/home/s92137/chess_results/exp4_22_actual_runtime_guarded_overlay_full
```

核心數據：

| 指標 | 數值 |
| --- | ---: |
| engine verdict | `HIGH_RISK` |
| promotion | `false` |
| baseline score | `0.8693` |
| full final replacement score | `0.8693` |
| simulator guarded score | `0.9231` |
| actual runtime guarded score | `0.9231` |
| delta vs baseline | `+0.0538` |
| unsafe override | `0` |
| simulator selected mismatch | `0` |
| total wall seconds | `2515.596` |
| total checkpoint seconds | `2243.453` |
| retrain seconds | `88.536` |
| deterministic eval seconds | `97.024` |
| report write seconds | `65.623` |

Sanity learning：

| checkpoint | exact | seen | unseen | raw unseen | final unseen | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| trusted=10 | `true` | `0.4653` | `0.3968` | `0.3968` | `0.3968` | `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY` |
| trusted=20 | `true` | `0.4823` | `0.3889` | `0.3651` | `0.3889` | `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY` |

Full blocker：

- deterministic final 沒高於 baseline：`0.8693 -> 0.8693`
- seen / clean held-out retention 仍不足
- contextual flank hard clean pass rate 仍為 0
- hard-negative / semantic margin 仍為負
- broad sanity 仍只證明 exact FEN，不足以證明泛化

## 重要判讀

這輪把問題分成兩層：

1. Runtime guarded overlay 本身是有效的：
   - actual runtime guarded score `0.9231`
   - unsafe override `0`
   - simulator mismatch `0`
   - special-rule `7/7`

2. 現有 broad sanity gate 評估的是 full final replacement，不是 guarded overlay：
   - full final replacement 仍等於 baseline
   - sanity learning 仍是 `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY`
   - 因此不能用 full final broad failure 直接推翻 guarded overlay，但也不能因此直接 promotion

本輪後新增的 `guarded_overlay_sanity` 會在後續 full diagnostic 中輸出：

- guarded seen variant pass rate
- guarded unseen variant pass rate
- guarded generalization rate
- guarded unsafe override count

這是下一輪判斷 guarded overlay promotion 的必要 evidence。

## 結論

exp4_22 修掉了 evidence path 的關鍵缺口：

- actual runtime helper 已經被 validation 逐 case 驗證。
- simulator 與 actual runtime path 沒有 drift。
- guarded overlay 在 deterministic gate 上仍維持 `0.9231`。

但 promotion 仍是 false，因為 full broad sanity 顯示 full replacement 仍不會泛化，而 guarded overlay 的 broad sanity 需要用新 `guarded_overlay_sanity` 欄位重新跑一次 full diagnostic 才能定案。

下一步：

1. 跑 exp4_23 guarded-overlay broad sanity full diagnostic。
2. 若 guarded overlay unseen 不退步且 unsafe override 為 0，再建立 guarded overlay promotion gate。
3. 同時要處理成本：full diagnostic 仍約 42 分鐘，瓶頸是 sanity final decision variants。
