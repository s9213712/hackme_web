# AGENTS Docs

這裡收斂所有 agent 協作規則、QA runbook、交易系統 QA 任務書。

## 先讀哪份

- 要看 agent 共通交付規則：
  [RULES_FOR_AGENTS.md](RULES_FOR_AGENTS.md)
- 要跑整站 QA：
  [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)
- 每次新功能完成後的針對性壓測、性能、滲透、找碴、提權、違規與例外行為 gate：
  [FEATURE_COMPLETION_QA_GATE.md](FEATURE_COMPLETION_QA_GATE.md)
- 要跑交易系統深度 QA：
  [TRADING_SYSTEM_QA_FOR_AGENTS.md](TRADING_SYSTEM_QA_FOR_AGENTS.md)
- 要先套用交易系統固定回歸矩陣：
  [TRADING_QA_REGRESSION_MATRIX.md](TRADING_QA_REGRESSION_MATRIX.md)

## 目錄

- `RULES_FOR_AGENTS.md`
  - 全專案工作原則與完成定義
- `QA_MISSION_FOR_AGENTS.md`
  - 整站 QA / 手動驗證 / pentest runbook
- `FEATURE_COMPLETION_QA_GATE.md`
  - 每次新功能完成後必跑的 targeted QA gate；未跑不得宣稱功能完整完成
- `TRADING_SYSTEM_QA_FOR_AGENTS.md`
  - 交易系統專用深度 QA 任務書
- `TRADING_QA_REGRESSION_MATRIX.md`
  - 交易系統固定必跑的 reject-path / adversarial / accounting 回歸矩陣
- [research/](research/README.md)
  - agent-facing long-form research and future-work specs, including PointsChain v2, LLM WebChat / Agent platform control, Discord sync, and semi-autonomous AI-managed web
- [skills/hackme-web-qa/SKILL.md](skills/hackme-web-qa/SKILL.md)
  - project mirror of the QA skill used by agents; keep it synchronized with the Codex skill copy when changing QA workflow rules

## 維護原則

- `docs/AGENTS` 是 agent 工作規則與 QA 任務書的正式入口。
- `docs/AGENTS/research` 是仍會影響未來動工的研究規格；不是 runtime evidence 或一次性 QA 報告。
- 歷史 QA 報告已移到 [../archive/agent_qa_reports/](../archive/agent_qa_reports/)；新報告仍寫在 `docs/AGENTS/reports/`。
- 不要再新增第二套平行目錄，例如 `docs/codex/...` 或 repo 根層 `reports/...` 的新副本。
