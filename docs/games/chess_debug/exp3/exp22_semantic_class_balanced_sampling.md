# EXP22 - Semantic Class-balanced Sampling

## 前一個實驗暴露的問題
Exp21 coverage 補齊後仍 sampling 失衡，e_pawn/flank 類別過度主導。

## 實驗目標與要求
目標要求：

- 每個 semantic class 每輪抽樣數一致，或使用 inverse-frequency loss weight。
- 報告 effective_sample_weight_by_semantic。
- checkpoint@10 / @20 分布不得偏斜，`max_class_count / min_class_count <= 2`。
- cp20 不可丟失 cp10 exact / mistake retention。

結果：

- Raw distribution 仍不均，但 effective distribution 已平衡。
- cp10 raw：e_pawn=28、d_pawn=9、flank=10、kingside=9、development=9。
- cp10 effective：約 16.7-18.0，各類 skew ratio 1.08。
- cp20 raw：e_pawn=10、d_pawn=9、flank=27、kingside=9、development=9。
- cp20 effective：約 16.4-18.5，各類 skew ratio 1.12。
- sampling gate 通過，`semantic_sampling_skew` 不再是 blocker。
- clean gate 仍失敗：kingside/development 仍 0/9，cp20 mistake retention 從 expected 走回 `f8a3`。

經驗：

- Sampling 問題已排除，剩下是模型表徵/任務設計問題。
- cp20 retention 失敗表示多任務或 checkpoint drift 仍會覆蓋已學能力。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp22_semantic_class_balanced_sampling
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root /home/s92137/chess_results/exp22_semantic_class_balanced_sampling
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp22_semantic_class_balanced_sampling | - | HIGH_RISK | - | 45.854 | - | - | 937.72 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp22_semantic_class_balanced_sampling`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
