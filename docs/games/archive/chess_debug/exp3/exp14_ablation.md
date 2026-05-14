# EXP14 - Ablation 找出泛化失敗主因

## 前一個實驗暴露的問題
Exp13 繼續調權重收益有限，需要 ablation 判斷真正主因。

## 實驗目標與要求
目標要求：

- 固定跑 5 組 ablation：no_invariance_memory、invariance_memory_only、hard_negative_only、invariance+hard_negative、stronger_hard_negative_margin。
- 每組報告 cp10/cp20 final unseen、hard-held-out、min hard-negative margin、embedding delta、deterministic score、tactic/blunder regression、failed top3。
- 額外檢查 held-out labels 是否合理。

結果：

- 最佳組合是 invariance_plus_hard_negative，但仍遠低於 gate。
- stronger margin 反而更差。
- 發現 8 個 label quality warning，部分 expected move 在 static check 下落後 -330cp 到 -900cp。

經驗：

- 不能繼續調權重，必須先清理 held-out 題庫。
- 錯標或 questionable labels 會讓 promotion gate 懲罰模型走較合理的棋。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp14_hard_negative_only
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp14_hard_negative_only
```
### exp14_invariance_memory_only
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp14_invariance_memory_only
```
### exp14_invariance_plus_hard_negative
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp14_invariance_plus_hard_negative
```
### exp14_no_invariance_memory
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp14_no_invariance_memory
```
### exp14_stronger_hard_negative_margin
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp14_stronger_hard_negative_margin
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp14_hard_negative_only | - | HIGH_RISK | - | 31.99 | - | - | 149.384 | true | - | - | - |
| exp14_invariance_memory_only | - | HIGH_RISK | - | 31.628 | - | - | 141.99 | true | - | - | - |
| exp14_invariance_plus_hard_negative | - | HIGH_RISK | - | 32.21 | - | - | 140.636 | true | - | - | - |
| exp14_no_invariance_memory | - | HIGH_RISK | - | 32.812 | - | - | 146.815 | true | - | - | - |
| exp14_stronger_hard_negative_margin | - | HIGH_RISK | - | 32.949 | - | - | 143.923 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp14_stronger_hard_negative_margin`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
