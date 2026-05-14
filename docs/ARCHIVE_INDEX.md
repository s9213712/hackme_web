# Documentation Archive Index

本索引記錄 `docs/` 內不再作為第一入口、但仍需保留追溯價值的資料。歸檔原則是不刪證據、不覆蓋歷史，只把一次性報告與實驗輸出移出日常入口。

## 目前歸檔

| 路徑 | 內容 | 狀態 |
|---|---|---|
| `archive/competition_2026-05-06/` | Workflow Template Competition 回測競賽報告、方法、資料腳本 | 歷史證據包；若要重跑，先檢查內部硬編碼輸出路徑 |
| `archive/agent_qa_reports/` | 2026-05-11 至 2026-05-13 的舊 AGENTS QA 報告 | 歷史 QA 證據；新報告仍寫回 `AGENTS/reports/` |
| `archive/history/VERSION_STORY.md` | 專案歷史、舊分支故事與已放棄方向 | 歷史脈絡；不是現行操作指南 |
| `games/archive/` | 西洋棋 debug、exp3/exp4/exp5 歷史 ledger、舊 replay 證據 | 遊戲 AI 歷史紀錄；主入口見 `games/ARCHIVE_INDEX.md` |

## 維護規則

- 日常操作文件留在 `docs/` 根層或各 domain 目錄。
- 一次性 benchmark、競賽、過期 QA 報告放 `archive/`。
- 大型可機讀證據依 domain 留在該 domain 的 `evidence/` 或 `experiments/`。
- 若搬移會破壞常用入口，保留相容 README 指到新位置。
