# exp4_19：Guarded Overlay Attribution（2026-05-12）

## 上一輪問題

exp4_18 把 special-rule、e_pawn gate accounting 等假 blocker 清掉後，真正問題變成：

- full final replacement 的 deterministic score 仍等於 baseline：`0.8693 -> 0.8693`。
- special-rule 已是 `7/7`，但 broad learning / final-decision generalization 沒有可觀測提升。
- full heavy sanity 成本太高：`total_wall_seconds=2438.614`，每輪 40 分鐘不利於快速定位。

所以 exp4_19 不再盲目加資料或加權重，而是問一個更實際的問題：

> 如果 runtime 仍以 baseline 為預設，只在「final 明確優於或不劣於 baseline」的安全範圍採用 exp4 candidate，能不能讓 deterministic score 上升？

## 實驗命令

本輪先跑 quick targeted gate，不跑 full heavy sanity：

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --quick-retrain-max-seconds 90 \
  --quick-retrain-skip-heavy-sanity \
  --output-root /home/s92137/chess_results/exp4_19_guarded_overlay_attribution
```

結果目錄：

- `/home/s92137/chess_results/exp4_19_guarded_overlay_attribution`
- engine summary：`/home/s92137/chess_results/exp4_19_guarded_overlay_attribution/exp4/summary.json`
- overlay detail：`/home/s92137/chess_results/exp4_19_guarded_overlay_attribution/exp4/audits/exp4_guarded_overlay_attribution.jsonl`

## 修改項目

新增 `_exp4_guarded_overlay_attribution(deterministic_report)`：

- baseline 仍是 default。
- final-model move 只在 deterministic label 顯示「正向修正」或「等價不退步」時採用。
- final 比 baseline 差時，回退 baseline。
- 這是 attribution / upper-bound，不是 production runtime guard，因為目前使用 deterministic expected labels。

新增 artifact：

- `exp4_guarded_overlay_attribution.json`
- `audits/exp4_guarded_overlay_attribution.jsonl`

promotion gate 只把 overlay 結果放進 `non_blocking_notes`，不會因此放行。

## 實跑結果

核心結果：

| 指標 | 數值 |
|---|---:|
| engine_verdict | `PARTIAL` |
| promotion_gate.passed | `false` |
| baseline_score | `0.8693` |
| final_score | `0.8693` |
| guarded_overlay_score | `0.9231` |
| delta_vs_baseline | `+0.0538` |
| delta_vs_final | `+0.0538` |
| candidate_worth_runtime_overlay | `true` |
| unsafe_override_count | `0` |
| adoption_rate | `0.1538` |

Overlay decision counts：

| decision | count | 判讀 |
|---|---:|---|
| same_move | 10 | baseline / final 相同，維持 baseline |
| positive_override | 1 | final 修正 baseline 錯誤 |
| neutral_equivalent_override | 1 | final 與 baseline 都是可接受好棋 |
| prevented_regression | 1 | final 退步，回退 baseline |
| unresolved_no_gain | 0 | 沒有新增未解收益 |
| fallback_to_baseline | 1 | 回退 baseline 防止退步 |

實際關鍵 case：

- `mistake_retention_game_900002_ply_1`：baseline `e7e5` 錯，final `d7d5` 對，overlay 採用 final。
- `promotion_white`：baseline `e7e8q` 對，final `e7e8n` 錯，overlay 回退 baseline。
- `opening_develop_white`：baseline `e2e4` 與 final `g1f3` 都是 opening multi-good，overlay 可採用 final 但不算 broad learning evidence。

## 結果判讀

這輪最重要的發現是：

- full model replacement 沒有超過 baseline。
- 但 baseline-default guarded overlay 在 deterministic attribution 上可達 `0.9231`，比 baseline / final replacement 高 `+0.0538`。

這表示 exp4 目前不是「完全沒有可用學習訊號」，而是：

- final candidate 有局部正向修正。
- final candidate 也有局部 regression。
- 全盤替換會讓正負抵消。
- 以 baseline 為底、只接受安全正向覆蓋，才是目前最合理的 production 方向。

但這仍不能 promotion，原因：

- 本輪用了 `--quick-retrain-skip-heavy-sanity`。
- overlay attribution 使用 deterministic expected labels，runtime 不能直接取得這些 labels。
- 尚未實作 production-safe runtime guard。
- broad unseen generalization 仍未證明。

## 下一步

exp4_20 應該把這個 label-based upper-bound 轉成可上線的 runtime guarded overlay：

1. baseline 仍為 default。
2. runtime guard 只能使用可取得訊號：
   - special-rule oracle / subtype validation
   - static/search score delta
   - teacher top-k 或 deterministic case manifest
   - move legality / blunder guard
   - opening multi-good equivalence
3. final candidate 只有在 guard 通過時覆蓋 baseline。
4. 所有不確定 broad case fallback baseline。
5. 驗收條件：
   - guarded_runtime_score > baseline
   - unsafe_override_count = 0
   - special_rule 維持 7/7
   - mistake_retention 不退步
   - promotion_white 這類 regression 必須被 baseline fallback 擋住

一句話：exp4_19 證明「全盤替換」不是最快路線；「baseline + guarded positive override」才是目前最可能安全提升 deterministic score 的方向。
