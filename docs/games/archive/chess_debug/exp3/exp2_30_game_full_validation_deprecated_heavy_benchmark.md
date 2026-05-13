# EXP2 - 30-game Full Validation 與 Deprecated Heavy Benchmark

## 前一個實驗暴露的問題
Exp1 只證明能產 artifact，但無法判斷 retrain 後模型是否真的可 promotion。

## 實驗目標與要求
目標要求：

- 使用 30-game 結構檢查 exp2。
- `trusted_valid=25`，`quarantine_invalid=5`。
- 每 10 盤 retrain，並補足 20-30 區段讓三個 stage win rate 可比較。
- 報告 stage win rate、retrain timing、mistake retention、benchmark。

結果：

- 30-game 實跑太慢，retrain 接近十分鐘。
- 20-25 stage 曾出現 `0.0` win rate，且 deterministic score 沒提升，mistake retention 下降。
- 判定疑似 catastrophic regression，而不是單純 stochastic noise。
- exp2 後續被刪除為正式 selectable engine，改以 exp3 優化版承接。

經驗：

- 小樣本實盤勝率不可復現，不能作為每次 promotion 的主要依據。
- Full-game benchmark 應改為 nightly/expensive validation 或 SPRT 大量對局，不應放在日常 retrain gate。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp2_30game_20260510_065446
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --total-games 30 --fast-retrain --output-root <chess_results>/exp2_30game_20260510_065446
```
### exp2_30game_fast_gate_20260510_071408
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --total-games 30 --quick-retrain-gate --output-root <chess_results>/exp2_30game_fast_gate_20260510_071408
```
### exp2_deterministic_gate_20260510_075410
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --quick-retrain-gate --output-root <chess_results>/exp2_deterministic_gate_20260510_075410
```
### exp2_mistake_probe_20260510_064146
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp2_mistake_probe_20260510_064146
```
### exp2_single_20260510_063310
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp2_single_20260510_063310
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp2_30game_20260510_065446 | - | PARTIAL | - | 85.068 | - | - | 109.922 | - | - | - | - |
| exp2_30game_fast_gate_20260510_071408 | - | PARTIAL | - | 85.07 | - | - | 114.253 | - | - | - | - |
| exp2_deterministic_gate_20260510_075410 | - | PARTIAL | - | 80.062 | - | - | 101.769 | true | - | - | - |
| exp2_mistake_probe_20260510_064146 | - | PARTIAL | - | 85.072 | - | - | 105.96 | - | - | - | - |
| exp2_single_20260510_063310 | - | PARTIAL | - | 80.073 | - | - | 101.163 | - | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp2_single_20260510_063310`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
Exp2 已 deprecated，不再作 selectable engine；只保留歷史 evidence。
