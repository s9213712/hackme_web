# Architecture：exp3 / exp4 / exp5 路線分流

## 上一階段問題

exp1-34 已經把西洋棋 debug pipeline 做到可審計，但也暴露一個更根本的問題：目前 exp3/exp4 的小型神經網路與語義 replay 修補，不能直接等同於現代主流西洋棋神經網路架構。

主要問題：

- exp3 是 lightweight MLP + alpha-beta，適合快速 gate 與 replay governance，不適合作為最終棋力架構。
- exp4 已有 policy/value prototype，但仍主要靠 alpha-beta 搜尋，還不是清楚的 Policy/Value + MCTS 路線。
- 沒有 NNUE + alpha-beta/PVS 路線，導致「傳統高效搜尋 + 神經評估」這條更接近 Stockfish 現代架構的方向缺席。

## 本輪指令全文

使用者確認方向：

> 那就照你的說法進行

當時建議方向：

- 保留 exp3 作 lightweight baseline。
- 將 exp4 往 Policy/Value network + MCTS 推進。
- 另外新增 exp5：NNUE + alpha-beta/PVS search。
- 不要把新架構直接混進現有 exp3/4 retrain promotion gate。

## 分析

這輪不應繼續硬修 exp34 的 flank / retention 問題，因為那是在小型 MLP 路線裡追局部修補。更合理的做法是先把架構角色分清楚：

- exp3：快速、便宜、可審計 baseline。
- exp4：Policy/Value + MCTS 路線，用於後續類 AlphaZero/Leela 方向實驗。
- exp5：NNUE-like evaluator + alpha-beta/PVS 路線，用於後續類 Stockfish 方向實驗。

這樣可以避免把 exp3 的 learning failure 錯誤外推到所有架構，也避免把 exp4/exp5 的新特性污染既有 deterministic promotion evidence chain。

## 修改項目

- 新增 `services/games/chess_nnue.py`。
- exp5 difficulty：`experiment 5:nnue`。
- exp5 model file：`chess_experiment_5_nnue.json`。
- exp5 architecture：`nnue-like-sparse-accumulator-v1`。
- exp5 搜尋：沿用 shared alpha-beta stack，搭配 sparse evaluator。
- exp4 `choose_experiment_pv_move(...)` 新增 `decision_mode="mcts"`。
- exp4 新增 deterministic root MCTS/PUCT decision mode。
- routes catalog/schema/practice 加入 exp5。
- 前台 practice/root candidate engine 選單加入 exp5。
- exp4 label 改成 `實驗 4：Policy/Value + MCTS`。
- exp5 label 使用 `實驗 5：NNUE + AlphaBeta/PVS`。
- warm-start / production inventory / candidate staging 加入 exp5。
- 測試更新 catalog、frontend label、practice 建局與 warm-start inventory。
- 主 ledger `docs/games/chess_debug/chess_debug.md` 追加本輪架構分流紀錄。

## 實際結果

已驗證：

- `python3 -m py_compile services/games/chess_nnue.py services/games/chess_pv.py routes/games.py services/games/chess_promotion.py` 通過。
- exp4 MCTS smoke move 可產生合法 move。
- exp5 NNUE-like smoke move 可產生合法 move。
- exp5 已出現在前台、catalog、warm-start inventory 與 candidate staging 支援範圍。

尚未宣稱：

- exp4 尚未完成成熟 MCTS tree search。
- exp5 尚未是 Stockfish 相容 NNUE。
- exp5 尚未接入 quick deterministic promotion gate。
- 本輪不宣稱 promotion gate 通過。

## 結果判讀

這輪是架構治理修正，不是棋力 promotion 修正。

有效成果是：

- exp3 不再被誤當作現代最終棋力模型。
- exp4 開始明確承擔 Policy/Value + MCTS 方向。
- exp5 開始明確承擔 NNUE + alpha-beta/PVS 方向。
- 前台與後端都能選到 exp5，warm-start 也能建立 exp5 artifact。

風險：

- exp4 的 MCTS 目前是 deterministic root-level PUCT 模式，還需要後續補完整 tree/visit statistics/debug。
- exp5 目前是 NNUE-like skeleton，需要後續補真正 accumulator、feature transformer、PVS 與傳統搜尋優化。
- 如果未來直接把 exp5 放進 exp3/4 的 replay gate，會造成 evidence 語義混亂；需要 exp5 專用 gate。

## 未來修正方向

- exp4：
  - 補 MCTS visit statistics、root policy/value breakdown。
  - 把 deterministic strength snapshot 接到 `decision_mode="mcts"`。
  - 確認 tactic/blunder 不因 policy prior 退步。
- exp5：
  - 補真正 NNUE accumulator。
  - 補 PVS、LMR、null-move pruning、killer/history/countermove ordering。
  - 建立 exp5 專用 deterministic strength gate。
- governance：
  - 報告必須列出 engine architecture。
  - exp3/exp4/exp5 不可共用不相容的 training success 語義。
  - promotion gate 仍只看 deterministic held-out evidence，不看架構名。

## 適用 exp3/4

- exp3：保留為 baseline，這輪不改 retrain gate。
- exp4：已新增 MCTS decision entry，後續需要正式 gate 實跑。
- exp5：新路線，不屬於 exp3/4，但可共用 report consistency、artifact evidence、promotion gate 原則。
