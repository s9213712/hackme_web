# EXP3 - Quick Retrain Gate

## 前一個實驗暴露的問題
Exp2 暴露 30-game/full-game benchmark 太慢、波動大，不能當日常 promotion gate。

## 實驗目標與要求
目標要求：

- 不再每次跑完整 30-game generation。
- 使用固定 trusted replay fixture、固定 seed、固定 retrain steps/epochs/max seconds。
- 產出 baseline、checkpoint@10、checkpoint@20、final。
- deterministic strength snapshot 成為正式 gate 主體。

結果：

- Quick gate 大幅縮短日常驗收時間。
- 報告開始包含 timing breakdown：replay generation、retrain、deterministic eval、report write、total wall time。
- 仍發現 loss 下降但 deterministic score 不提升。

經驗：

- 快速不等於可信；quick gate 必須保留 deterministic promotion gate。
- replay_loss 下降只能代表 trainer fit 了資料，不能代表 final decision 改善。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp3_quick_gate_20260510_083200
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp3_quick_gate_20260510_083200
```
### exp3_quick_gate_20260510_083500
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp3_quick_gate_20260510_083500
```
### exp3_quick_gate_20260510_083900
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp3_quick_gate_20260510_083900
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp3_quick_gate_20260510_083200 | - | PARTIAL | - | 1.601 | - | - | 74.672 | true | - | - | - |
| exp3_quick_gate_20260510_083500 | - | PARTIAL | - | 1.806 | - | - | 11.442 | true | - | - | - |
| exp3_quick_gate_20260510_083900 | - | PARTIAL | - | 1.623 | - | - | 10.841 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp3_quick_gate_20260510_083900`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
直接適用該實驗線；exp3 是主要 quick deterministic gate，exp4 共用 replay/probe/gate surface。
