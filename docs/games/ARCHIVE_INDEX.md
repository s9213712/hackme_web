# Games Archive Index

本索引記錄 2026-05-13 遊戲 AI 評測、Exp5 西洋棋優化與文件整理後的歸檔位置。歷史報告內若仍提到整理前的平面路徑，以本索引為準。

## 主要入口

| 類別 | 路徑 | 內容 |
|---|---|---|
| 總報告 | `reports/` | 棋力評測、Exp5 優化結論、retrain/adapters 比較、清理紀錄 |
| 技術參考 | `references/` | 三棋 benchmark、Exp5 模型檔、訓練 pipeline、NNUE/conversion/engine plan |
| 評測證據 | `evidence/` | JSON/JSONL replay、score probe、gauntlet、tactical suite |
| 完整實驗 | `experiments/exp5/` | adapter mode、baseline context、normal retrain smoke 的完整輸出資料夾 |
| 模型快照 | `model_snapshots/` | 預設模型替換前保留的模型快照；此目錄不搬移 |
| 歷史除錯 | `archive/` | 舊 `chess_debug` 內容與不再作為主入口的歷史文件 |

## Exp5 證據分層

| 子目錄 | 內容 | 使用方式 |
|---|---|---|
| `evidence/exp5/v7/` | v7 promotion guard 與目前預設模型等價的 rerun 結果 | 用來回查「模型檔最佳快照」與基準強度 |
| `evidence/exp5/v10/` | repetition progress v10 的 advanced score、gauntlet、tactical suite | 用來回查目前最高量測分數與 code-path 強化效果 |
| `evidence/exp5/rejected/` | v1-v9 未採用或未勝出的探索紀錄 | 用來檢討失敗假設，避免重複走同一路線 |
| `evidence/exp5/replay_sources/` | 下載腳本 probe replay | 用來追溯外部棋局下載腳本是否被納入評測 |

## 報告索引

| 報告 | 重點 |
|---|---|
| `reports/2026-05-13_game_ai_strength_report.md` | 黑白棋、圍棋、五子棋、西洋棋 AI 棋力總評 |
| `reports/2026-05-13_game_ai_current_technology_score_comparison.md` | 各棋類各 AI 技術與分數比較 |
| `reports/2026-05-13_game_ai_eval_run_log.md` | 評測過程與使用腳本紀錄 |
| `reports/2026-05-13_exp5_advanced_score_optimization.md` | Exp5 進階評分優化紀錄 |
| `reports/2026-05-13_exp5_retrain_adapter_comparison.md` | 舊 retrain 與 adapter/notes-only 架構比較 |
| `reports/2026-05-13_exp5_90_plus_research_plan.md` | 往 90+ 分與高階引擎方向的研究計畫 |
| `reports/2026-05-13_docs_games_cleanup.md` | 本輪 `docs/games` 清理與歸檔紀錄 |

## 保留原則

- `model_snapshots/` 保持在 `docs/games/model_snapshots/`，避免破壞既有引用。
- JSON/JSONL 證據不刪除，只依用途分層。
- 被淘汰的實驗放入 `evidence/exp5/rejected/` 或 `archive/`，仍保留檢討價值。
- 新增報告優先放 `reports/`；新增長期操作文件優先放 `references/`；新增可機讀證據優先放 `evidence/`。
