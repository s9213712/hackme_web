# AGENTS Docs

這裡收斂所有 agent 協作規則、QA runbook、交易系統 QA 任務書，以及各 agent
產出的 QA 報告。

## 先讀哪份

- 要看 agent 共通交付規則：
  [RULES_FOR_AGENTS.md](RULES_FOR_AGENTS.md)
- 要跑整站 QA：
  [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)
- 要跑交易系統深度 QA：
  [TRADING_SYSTEM_QA_FOR_AGENTS.md](TRADING_SYSTEM_QA_FOR_AGENTS.md)
- 要先套用交易系統固定回歸矩陣：
  [TRADING_QA_REGRESSION_MATRIX.md](TRADING_QA_REGRESSION_MATRIX.md)
- 要看各 agent 的歷史報告與跨 agent issue 收斂表：
  請到 `docs/AGENTS/reports/` 目錄查閱

## 目錄

- `RULES_FOR_AGENTS.md`
  - 全專案工作原則與完成定義
- `QA_MISSION_FOR_AGENTS.md`
  - 整站 QA / 手動驗證 / pentest runbook
- `TRADING_SYSTEM_QA_FOR_AGENTS.md`
  - 交易系統專用深度 QA 任務書
- `TRADING_QA_REGRESSION_MATRIX.md`
  - 交易系統固定必跑的 reject-path / adversarial / accounting 回歸矩陣
- `reports/`
  - 各 agent 的 QA 歸檔與測試證據

## 維護原則

- `docs/AGENTS` 是 agent 文件與 QA 歸檔的正式入口。
- 新報告優先放在 `docs/AGENTS/reports/<agent>/...`。
- 不要再新增第二套平行目錄，例如 `docs/codex/...` 或 repo 根層 `reports/...` 的新副本。
