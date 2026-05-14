# exp4_23：Guarded Overlay Broad Sanity Gate（2026-05-12）

## 上一輪問題

exp4_22 已證明 `actual runtime guarded overlay` 與 simulator 沒有 drift：

- baseline / full replacement score：`0.8693`
- actual runtime guarded score：`0.9231`
- unsafe override：`0`
- simulator mismatch：`0`

但 exp4_22 的 broad sanity 判讀仍主要看 full final replacement，不是 guarded overlay 這種 promotion shape。因此 exp4_23 要補一個專門的 guarded overlay broad sanity gate：runtime 仍以 baseline 為預設，只在 no-label guard 放行時採用 final candidate，並檢查 seen/unseen variants 是否不退步。

## 本輪目標

- 新增 `guarded_overlay_broad_sanity_gate`，放在 `promotion_gate` 與 root engine row 內。
- gate 不可讀 label 作 runtime 決策，只能用已存在的 guarded overlay decision，再用 label 做離線評分。
- gate 必須同時檢查 actual runtime guarded deterministic gain、unsafe override、simulator mismatch、special-rule、seen/unseen sanity non-regression。
- quick mode 若跳過 heavy sanity，必須明確回報 sanity missing，不可假通過。
- full mode 必須輸出每個 checkpoint 的 guarded seen/unseen pass rate 與 baseline 對照。

## 修改項目

`scripts/games/chess_live_learning_validation.py`

- `_exp4_guarded_overlay_sanity_from_rows(...)` 新增 `baseline_pass_rate` / `final_pass_rate`，讓 guarded overlay broad sanity 能比較 baseline、final、guarded 三者。
- `_evaluate_sanity_learning_probe(...)` 新增：
  - `guarded_overlay_seen_baseline_pass_rate`
  - `guarded_overlay_unseen_baseline_pass_rate`
  - `guarded_overlay_seen_final_pass_rate`
  - `guarded_overlay_unseen_final_pass_rate`
- 新增 `_guarded_overlay_broad_sanity_gate(summary)`：
  - 檢查 actual runtime guarded overlay 是否安全提升 deterministic score。
  - 檢查 seen/unseen guarded overlay pass rate 是否低於 baseline。
  - 檢查 guarded sanity unsafe override count 是否為 0。
  - 檢查 special-rule gate 是否維持 `1.0`。
  - `production_enablement_required=true`，即使通過也只是 guarded overlay promotion request 的候選，不會自動 production enable。
- `_promotion_gate_summary(...)` 與 `_root_engine_row(...)` 輸出 `guarded_overlay_broad_sanity_gate`。
- `_compact_sanity_probe_for_summary(...)` 修正 compact 後 baseline/final guarded rate 被丟掉的顯示問題。

`tests/scripts/games/test_chess_live_learning_validation_script.py`

- 新增通過案例：no-label runtime overlay shape 安全提升、seen/unseen 不退步時，nested guarded gate 可通過。
- 新增阻擋案例：runtime regression、unsafe override、simulator mismatch、seen/unseen regression、special-rule 退步都會擋下。
- 新增 compact 測試，避免報告把 guarded baseline/final pass rate 顯示成 `0`。

## 實驗命令

Quick targeted gate（驗證欄位與 skip-heavy 行為）：

```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --quick-retrain-skip-heavy-sanity \
  --output-root <repo>/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_quick
```

Full diagnostic（正式檢查 guarded overlay broad sanity）：

```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --output-root <repo>/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full
```

驗證：

```bash
python3 -m py_compile <repo>/scripts/games/chess_live_learning_validation.py
PYTHONPATH=<repo> pytest <repo>/tests/scripts/games/test_chess_live_learning_validation_script.py -q
PYTHONPATH=<repo> pytest <repo>/tests/games/test_games.py -q
PYTHONPATH=<repo> pytest <repo>/tests/games -q
git -C <repo> diff --check
```

## Quick 結果

結果目錄：

```text
<repo>/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_quick
```

核心數據：

| 指標 | 數值 |
| --- | ---: |
| engine verdict | `PARTIAL` |
| promotion | `false` |
| baseline score | `0.8693` |
| full final replacement score | `0.8693` |
| actual runtime guarded score | `0.9231` |
| delta vs baseline | `+0.0538` |
| unsafe override | `0` |
| simulator mismatch | `0` |
| total wall seconds | `715.377` |
| checkpoint seconds | `178.133` |

`guarded_overlay_broad_sanity_gate`：

- `passed=false`
- reasons:
  - `guarded overlay sanity missing at trusted=10`
  - `guarded overlay sanity missing at trusted=20`

判讀：

- quick mode 正確沒有假通過，因為 `--quick-retrain-skip-heavy-sanity` 沒有 seen/unseen guarded sanity rows。
- deterministic 13 題仍顯示 guarded overlay 有 `+0.0538`，但 quick 結果不能作 broad promotion evidence。

## Full Diagnostic 結果

結果目錄：

```text
<repo>/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full
```

核心數據：

| 指標 | 數值 |
| --- | ---: |
| engine verdict | `HIGH_RISK` |
| promotion | `false` |
| baseline score | `0.8693` |
| full final replacement score | `0.8693` |
| actual runtime guarded score | `0.9231` |
| delta vs baseline | `+0.0538` |
| deterministic unsafe override | `0` |
| simulator mismatch | `0` |
| special-rule | `7/7` |
| total wall seconds | `2709.435` |
| checkpoint seconds | `2414.420` |
| retrain seconds | `101.763` |
| deterministic eval seconds | `91.524` |
| report write seconds | `60.601` |

`guarded_overlay_broad_sanity_gate`：

- `passed=false`
- reasons:
  - `guarded overlay sanity unsafe override at trusted=10`
  - `guarded overlay unseen variant pass rate regressed at trusted=20`
  - `guarded overlay sanity unsafe override at trusted=20`

Guarded overlay broad sanity table：

| checkpoint | seen baseline | seen guarded | seen non-regression | unseen baseline | unseen guarded | unseen non-regression | unsafe overrides |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| trusted=10 | `0.4028` | `0.4653` | `true` | `0.3571` | `0.3889` | `true` | `14` |
| trusted=20 | `0.4681` | `0.4823` | `true` | `0.3968` | `0.3889` | `false` | `12` |

Sanity learning 仍是 `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY`：

| checkpoint | exact | seen | unseen | final decision generalization | guarded generalization | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| trusted=10 | `true` | `0.4653` | `0.3968` | `0.4333` | `0.4296` | `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY` |
| trusted=20 | `true` | `0.4823` | `0.3889` | `0.4382` | `0.4382` | `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY` |

## 結果判讀

exp4_23 是必要的阻擋實驗。

exp4_20 到 exp4_22 的 deterministic overlay 結果看起來很好：

- baseline `0.8693`
- actual runtime guarded `0.9231`
- unsafe override `0`
- simulator mismatch `0`

但 exp4_23 把同一個 guarded overlay 放到 broad sanity variants 後，發現：

- deterministic 小題庫沒有 unsafe override，不代表 broad variants 沒有 unsafe override。
- trusted=10/20 的 guarded sanity 分別出現 `14` / `12` 個 unsafe overrides。
- trusted=20 的 unseen guarded pass rate `0.3889` 低於 baseline `0.3968`。

因此目前不能做 guarded overlay promotion。這不是 full replacement 的老問題，而是 guarded overlay 自己在 broad sanity 上也還不夠安全。

## 本輪發現的新問題

1. `actual_runtime_guarded_overlay` deterministic gate 太小，只能證明 13 題上的安全性。
2. broad sanity variants 暴露 guarded overlay guard 過寬，會採用事後 label 看來是 regression 的 final move。
3. trusted=20 unseen variants 出現實際低於 baseline，代表 overlay 不是單純「baseline + 正向修正」。
4. full diagnostic 仍太慢，`total_wall_seconds=2709.435`，主要耗在 final decision variants；後續需要 cache / high-risk-row replay，而不是每輪全量重跑。

## 後續方向

下一輪不應 retrain。應先做 `exp4_24_guarded_overlay_unsafe_override_audit`：

- 列出 trusted=10/20 的 unsafe override rows。
- 對每個 unsafe row 輸出 `case_id / fen / baseline_move / final_move / selected_move / guard_reason / guard_detail / expected_move / semantic_class / difficulty / category`。
- 分群：promotion subtype、opening multi-good false negative、score window 太寬、rule subtype guard 不足、static score 誤判。
- 收緊 runtime guard：
  - 缺 score 不可放行，除非 special-rule subtype oracle 強支持。
  - 對 non-special ordinary opening move 加更嚴格的 top-k / static window。
  - 對 broad sanity 曾出現 unsafe 的 guard reason 加 blacklist 或二階檢查。
- 只跑 targeted unsafe-row replay，確認 unsafe override count 降到 0，再跑 full broad sanity。

## 結論

exp4_23 把 guarded overlay 從 deterministic 小題庫推進到 broad sanity gate，並正確擋下 promotion。

目前狀態：

- runtime guarded overlay deterministic score 仍有正向訊號。
- broad sanity unsafe override 非 0。
- trusted=20 unseen guarded rate 低於 baseline。
- promotion 仍必須是 `false`。

下一步重點不是再訓練，而是修 runtime guard 的 broad-sanity unsafe override。
