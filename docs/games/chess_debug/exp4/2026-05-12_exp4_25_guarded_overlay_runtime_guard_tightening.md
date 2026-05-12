# exp4_25：Guarded Overlay Runtime Guard Tightening（2026-05-12）

## 結論

promotion=false；retrain_attempted=false；runtime_mutated=false。

本輪沒有重新訓練，也沒有啟用 production overlay。只針對 exp4_24 找出的 runtime guard 過寬問題做安全收緊，並用 exp4_24 的 26 筆 unsafe rows 做 targeted replay。

結果：

- exp4_24 unsafe rows：`26`
- exp4_25 targeted replay still_unsafe：`0`
- regression_rows_after_guard：`0`
- blocked_after_guard_tightening：`26`
- guard_reason_after：全部為 `ordinary_runtime_margin_insufficient`
- deterministic actual runtime guarded score：`0.8693`
- deterministic baseline score：`0.8693`
- deterministic delta vs baseline：`0.0000`

判讀：

- 安全修正成功：已知 26 筆 unsafe override 全部被擋掉。
- 正向 overlay 訊號暫時消失：原本 exp4_20-23 的 `0.9231` 是靠 ordinary move 覆蓋得到；收緊後回到 baseline `0.8693`。
- 這輪不能 promotion，但它修掉了 guarded overlay 最危險的 broad sanity regression。

## 上一輪問題

exp4_24 audit 顯示：

- unsafe override：`26`
- regression rows：`26`
- trusted=10 unsafe：`14`
- trusted=20 unsafe：`12`
- seen unsafe：`16`
- unseen unsafe：`10`
- guard_reason 全部是 `runtime_static_and_rule_guard_passed`
- semantic 分布：
  - `e_pawn_central_break=12`
  - `d_pawn_central_break=12`
  - `flank_pawn_push=2`

這代表 guard 對 ordinary central pawn / flank move 太寬。baseline 已經正確時，final 用 0-margin 或弱 static-window ordinary move 覆蓋 baseline，造成 broad sanity regression。

## 修改項目

主要修改：

- `services/games/chess_pv_guarded_overlay.py`
  - 新增 `DEFAULT_ORDINARY_OVERRIDE_MIN_DELTA_CP = 125`
  - 新增 move family 分類：
    - `castling`
    - `en_passant`
    - `promotion`
    - `capture`
    - `ordinary`
  - 非特殊 move 若要覆蓋 baseline，必須滿足：
    - legal
    - promotion subtype guard 不反對
    - static window 不明顯反對
    - 且 `final_score_cp - baseline_score_cp >= 125`
  - 若未達門檻，回傳：
    - `ordinary_runtime_margin_insufficient`

保留：

- castling / en-passant / promotion 的 special-rule path 不受 ordinary margin rule 直接阻擋。
- non-queen promotion subtype guard 仍保留。
- runtime guard 仍不讀 expected label / pass-fail outcome。

新增：

- `scripts/games/chess_exp4_guarded_overlay_targeted_replay.py`
  - 讀 exp4_24 audit JSON。
  - 對 26 筆 unsafe rows 重新套用目前 runtime guard。
  - 輸出 unsafe 是否仍存在、哪些 row 被擋、guard reason after tightening。

新增測試：

- `tests/scripts/games/test_chess_exp4_guarded_overlay_targeted_replay_script.py`
  - 驗證 zero-margin ordinary override 會被擋。
  - 驗證 replay script 會產出 JSON / Markdown artifact。

更新測試：

- `tests/scripts/games/test_chess_live_learning_validation_script.py`
  - runtime guarded overlay 測試改成保守邏輯：
    - 0-margin opening ordinary override 不再被採用。
    - 有明確 +200cp margin 的 ordinary override 仍可通過。

## 實驗命令

```bash
python3 -m py_compile /home/s92137/hackme_web/services/games/chess_pv_guarded_overlay.py /home/s92137/hackme_web/scripts/games/chess_exp4_guarded_overlay_targeted_replay.py
```

```bash
PYTHONPATH=/home/s92137/hackme_web pytest /home/s92137/hackme_web/tests/scripts/games/test_chess_exp4_guarded_overlay_targeted_replay_script.py -q
```

```bash
PYTHONPATH=/home/s92137/hackme_web pytest /home/s92137/hackme_web/tests/scripts/games/test_chess_live_learning_validation_script.py -q
```

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_exp4_guarded_overlay_targeted_replay.py --audit-json /home/s92137/hackme_web/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full/exp4/audits/exp4_guarded_overlay_unsafe_override_audit.json --output-json /home/s92137/hackme_web/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full/exp4/audits/exp4_guarded_overlay_targeted_replay_after_tightening.json --output-md /home/s92137/hackme_web/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full/exp4/audits/exp4_guarded_overlay_targeted_replay_after_tightening.md
```

## Targeted Replay 結果

輸出：

- JSON：`/home/s92137/hackme_web/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full/exp4/audits/exp4_guarded_overlay_targeted_replay_after_tightening.json`
- Markdown：`/home/s92137/hackme_web/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full/exp4/audits/exp4_guarded_overlay_targeted_replay_after_tightening.md`

| 指標 | 數值 |
|---|---:|
| unsafe_rows_total | `26` |
| blocked_after_guard_tightening | `26` |
| still_unsafe | `0` |
| regression_rows_after_guard | `0` |
| positive_override_preserved_count | `0` |
| baseline_selected_count | `26` |
| final_selected_count | `0` |
| passed | `true` |

guard reason after tightening：

| reason | count |
|---|---:|
| `ordinary_runtime_margin_insufficient` | `26` |

## Deterministic Guarded Overlay After Tightening

使用 exp4_23 full 的 deterministic snapshot 重新計算：

| 指標 | 數值 |
|---|---:|
| baseline_score | `0.8693` |
| simulator_runtime_guarded_score | `0.8693` |
| simulator_delta_vs_baseline | `0.0000` |
| simulator_unsafe_override | `0` |
| simulator_positive_override | `0` |
| actual_runtime_guarded_score | `0.8693` |
| actual_delta_vs_baseline | `0.0000` |
| actual_unsafe_override | `0` |
| actual_positive_override | `0` |
| actual_simulator_mismatch | `0` |

判讀：

- 收緊後 deterministic 正向分數沒有保住。
- 這是預期內的保守結果，因為 exp4_24 的 regression 與 exp4_20-23 的 positive deterministic signal 都走過同一個寬鬆 ordinary guard。
- 目前應優先確保 unsafe=0；不能為了保留 `+0.0538` 放寬到再次產生 broad unsafe override。

## 結果判讀

exp4_25 是安全修正，不是棋力提升。

這輪把問題從：

> guarded overlay 太寬，會在 broad sanity 中覆蓋正確 baseline

收斂成：

> guarded overlay 現在安全，但太保守，沒有保留可觀測正向收益

因此目前不能 promotion，也不應該 full broad sanity 重跑求過。下一步應找更精細、仍不讀 label 的 runtime guard，讓它能區分：

- 真正有 runtime evidence 的正向 override
- 0-margin ordinary e/d pawn swap
- flank / capture 看似合理但 broad variant 上會 regression 的覆蓋

## 下一步

建議 exp4_26：

- 不 retrain。
- 不 promotion。
- 針對 exp4_20-23 的 deterministic positive case 與 exp4_24 unsafe cases 做 side-by-side guard feature audit。
- 找出不讀 label 也能保留正向 override、同時阻擋 26 筆 unsafe 的訊號，例如：
  - higher-confidence policy / final-decision reason
  - teacher/static top-k margin，而非 pure material score
  - special-rule 或 mistake-retention scoped guard
  - ordinary move cluster blacklist / allowlist
  - baseline/final agreement with deterministic safe cluster
- 目標是 `unsafe=0` 且 `guarded_score > baseline`；若做不到，guarded overlay 暫不具備 promotion value。
