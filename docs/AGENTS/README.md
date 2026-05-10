# AGENTS Docs

這裡收斂所有 agent 協作規則、QA runbook、交易系統 QA 任務書。

## 先讀哪份

- 要看 agent 共通交付規則：
  [RULES_FOR_AGENTS.md](RULES_FOR_AGENTS.md)
- 要跑整站 QA：
  [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)
- 要跑交易系統深度 QA：
  [TRADING_SYSTEM_QA_FOR_AGENTS.md](TRADING_SYSTEM_QA_FOR_AGENTS.md)
- 要先套用交易系統固定回歸矩陣：
  [TRADING_QA_REGRESSION_MATRIX.md](TRADING_QA_REGRESSION_MATRIX.md)

## 目錄

- `RULES_FOR_AGENTS.md`
  - 全專案工作原則與完成定義
- `QA_MISSION_FOR_AGENTS.md`
  - 整站 QA / 手動驗證 / pentest runbook
- `TRADING_SYSTEM_QA_FOR_AGENTS.md`
  - 交易系統專用深度 QA 任務書
- `TRADING_QA_REGRESSION_MATRIX.md`
  - 交易系統固定必跑的 reject-path / adversarial / accounting 回歸矩陣
- `research/`
  - agent-facing long-form research and future-work specs, including PointsChain v2, LLM WebChat / Agent platform control, Discord sync, and semi-autonomous AI-managed web

## 維護原則

- `docs/AGENTS` 是 agent 工作規則與 QA 任務書的正式入口。
- `docs/AGENTS/research` 是仍會影響未來動工的研究規格；不是 runtime evidence 或一次性 QA 報告。
- 歷史 QA 報告已移出 tracked docs；需要追溯時使用 Git history 或外部工作紀錄。
- 不要再新增第二套平行目錄，例如 `docs/codex/...` 或 repo 根層 `reports/...` 的新副本。
