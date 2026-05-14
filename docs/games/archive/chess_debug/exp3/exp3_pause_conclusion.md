# Exp3 暫停開發結論

日期：2026-05-11

## 結論

exp3 目前暫停開發。

這不是因為 exp3 沒有價值，而是因為它的主要價值已經完成：exp3 成功把西洋棋 live-learning validation、deterministic promotion gate、artifact consistency、dataset integrity、poison/leakage guard、mistake retention、semantic held-out、smoke gate、safe checkpoint selection 等治理流程跑通。

但是，exp3 不適合作為後續主要棋力模型繼續硬修。它的核心架構仍是 lightweight MLP evaluator + alpha-beta search。exp1-34 的結果顯示，這條路線在語義泛化與 retention 上已經接近實用上限。

## 暫停原因

主要原因：

- exp3 已證明 governance pipeline 可行，但沒有證明小型 MLP 能穩定學出棋理泛化。
- exp34 後仍存在 flank contextual learning 不穩、hard semantic generalization 不足、mixed scheduler 只能局部修復 e-pawn、hard flank label/context 仍需 quarantine。
- exp3 需要大量 semantic memory、hard-negative、rehearsal、scheduler、rollback、smoke gate 校準才能維持局部能力，複雜度已經不符合 lightweight baseline 的定位。
- 繼續在 exp3 上堆補丁，會把模型能力問題偽裝成 gate/report 問題，反而降低後續判斷清晰度。
- 後續應把棋力提升轉向更合理的架構：exp4 的 Policy/Value + MCTS，與 exp5 的 NNUE + alpha-beta/PVS。

## 最後狀態

exp34 的重要結論：

- cp20 mistake retention 已修正，safe checkpoint 可選 cp20。
- development scoring 問題已透過 multi-good credit 解決。
- central anchor 有局部改善。
- flank specialist / contextual flank 仍未穩定。
- hard flank 被標記為 `questionable_hard_flank_label`，不可作 promotion hard evidence。
- hard e-pawn 在 mixed checkpoint 中 raw policy 仍未穩定把 expected move 排上來，不應用 fusion threshold 硬放行。
- promotion gate 維持 false 是正確結果。

最後判讀：

- exp3 不是完全學不會，而是無法穩定滿足「可 promotion 的泛化與 retention 證據」。
- exp3 已足夠作為 baseline 與 governance regression test。
- exp3 不應再承擔最終棋力突破。

## 保留價值

exp3 仍應保留：

- 作為 deterministic promotion gate 的測試平台。
- 作為 dataset integrity / leakage guard / report consistency 的回歸樣板。
- 作為 exp4 / exp5 報告格式與 artifact evidence 的參考。
- 作為 lightweight baseline，檢查新架構是否真的比小模型路線更好。

## 不再做的事

暫停後不再優先投入：

- 不再繼續調 exp3 semantic sampling / hard-negative weight。
- 不再繼續調 exp3 flank-specific memory 補丁。
- 不再為 exp3 降低 promotion gate。
- 不再用 exp3 的 train/seen improvement 宣稱棋力成功。
- 不再把 exp3 的小型 MLP failure 當作 exp4/exp5 的結論。

## 後續方向

exp4：

- 走 Policy/Value + MCTS。
- 建立 MCTS root visit / policy / value breakdown。
- 用 deterministic strength snapshot 驗證，不靠 20-30 盤實戰勝率。

exp5：

- 走 NNUE-like evaluator + alpha-beta/PVS。
- 補真正 feature accumulator 與傳統搜尋優化。
- 建立 exp5 專用 deterministic gate。

governance：

- exp3 的 gate/report structure 可繼續沿用。
- 但 exp4/exp5 的 learning success 定義必須按各自架構重建，不可直接套用 exp3 的 semantic replay assumptions。

## 文件位置

- 主 ledger：[`chess_debug.md`](chess_debug.md)
- exp3 報告索引：[`INDEX.md`](INDEX.md)
- 架構分流報告：[`architecture_exp3_exp4_exp5_route_split.md`](architecture_exp3_exp4_exp5_route_split.md)
