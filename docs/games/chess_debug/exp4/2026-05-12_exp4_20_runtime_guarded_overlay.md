# exp4_20：Runtime Guarded Overlay Simulator（2026-05-12）

## 上一輪問題

exp4_19 的 label-based attribution 顯示：

- full replacement：`0.8693 -> 0.8693`
- guarded overlay attribution：`0.8693 -> 0.9231`

但 exp4_19 還不能作 production evidence，因為它知道 deterministic label / expected move 後才分類：

- final 哪些 case 是 positive override
- final 哪些 case 是 regression，需要 fallback baseline

production runtime 不能偷看 label。因此 exp4_20 目標是把 attribution 轉成 no-label runtime guard simulator。

## 實驗命令

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --quick-retrain-skip-heavy-sanity \
  --output-root /home/s92137/chess_results/exp4_20_runtime_guarded_overlay
```

結果目錄：

- `/home/s92137/chess_results/exp4_20_runtime_guarded_overlay`
- engine summary：`/home/s92137/chess_results/exp4_20_runtime_guarded_overlay/exp4/summary.json`
- no-label guard cases：`/home/s92137/chess_results/exp4_20_runtime_guarded_overlay/exp4/audits/exp4_runtime_guarded_overlay.jsonl`

## 修改項目

新增 no-label runtime overlay simulator：

- `_exp4_runtime_guarded_overlay_report(...)`
- `_exp4_runtime_overlay_allows_final(...)`
- `_exp4_runtime_promotion_subtype_guard(...)`

Guard 決策時**不可用**：

- expected label
- top1_correct
- positive_override / prevented_regression 這類事後分類

Guard 可用：

- final move 是否合法
- final 是否等於 baseline
- `score_cp` / static-like delta window
- promotion subtype oracle
- 非 queen promotion 只有在以下 runtime 可驗證理由才允許：
  - underpromotion 立即將死
  - queen promotion 會 stalemate，而 underpromotion 不 stalemate

這個 guard 仍是 simulator，尚未接到 production choose path。

## 實跑結果

| 指標 | 數值 |
|---|---:|
| engine_verdict | `PARTIAL` |
| promotion_gate.passed | `false` |
| baseline_score | `0.8693` |
| final_score | `0.8693` |
| runtime_guarded_score | `0.9231` |
| delta_vs_baseline | `+0.0538` |
| delta_vs_final | `+0.0538` |
| unsafe_override_count | `0` |
| candidate_worth_runtime_overlay | `true` |
| diagnostic_uses_expected_labels_for_decision | `false` |

Runtime decision counts：

| decision | count |
|---|---:|
| same_move | 10 |
| runtime_guard_allowed | 2 |
| runtime_guard_fallback | 1 |
| positive_override_after_scoring | 1 |
| prevented_regression_after_scoring | 1 |
| unsafe_override_after_scoring | 0 |

Fallback reason：

| reason | count |
|---|---:|
| nonqueen_promotion_downgrade_without_runtime_tactical_reason | 1 |

關鍵 case：

- `mistake_retention_game_900002_ply_1`
  - baseline：`e7e5`
  - final：`d7d5`
  - guard：allowed
  - reason：`runtime_static_and_rule_guard_passed`
  - scoring 後確認是 positive override

- `promotion_white`
  - baseline：`e7e8q`
  - final：`e7e8n`
  - guard：fallback baseline
  - reason：`nonqueen_promotion_downgrade_without_runtime_tactical_reason`
  - scoring 後確認 prevented regression

- `opening_develop_white`
  - baseline：`e2e4`
  - final：`g1f3`
  - guard：allowed
  - 兩者都是 opening multi-good；不算 broad learning evidence。

## 結果判讀

exp4_20 比 exp4_19 更進一步：

- exp4_19：label-based attribution 上界可到 `0.9231`
- exp4_20：no-label runtime simulator 也可到 `0.9231`

這表示目前最快可信路線不是 full model replacement，而是：

> baseline default + runtime guarded positive overlay

目前仍不能 promotion，原因：

- 本輪仍是 `--quick-retrain-skip-heavy-sanity`。
- simulator 尚未接入 production choose path。
- broad unseen generalization 仍未證明。
- hard flank / historical exp31 仍是 general-model blocker。

但 exp4_20 已經證明 guard 的核心規則有效：它能在不偷看 label 的情況下採用局部正向修正，並擋住 promotion subtype regression。

## 下一步

exp4_21 應該做 production integration draft：

1. 在 exp4 runtime choose path 加 guarded overlay mode，但預設仍關閉。
2. baseline model 仍為 default。
3. overlay candidate 只在 guard 通過時覆蓋 baseline。
4. guard 必須保留：
   - legal move check
   - static/search delta window
   - promotion subtype oracle
   - special-rule subtype guard
   - unsafe override audit
5. 實跑 quick targeted + full broad diagnostic，確認：
   - runtime guarded score > baseline
   - unsafe_override_count = 0
   - special_rule = 7/7
   - promotion_white fallback 生效
   - mistake_retention positive override 保留

一句話：exp4_20 已把「guarded overlay 有機會」從 label-based attribution 推進到 no-label runtime simulator；下一步才是把 guard 接到 production choose path。
