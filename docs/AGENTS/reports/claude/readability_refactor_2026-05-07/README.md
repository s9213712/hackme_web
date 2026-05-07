# Readability / Refactor Slice 2 — Inventory + Plan

- Agent: claude (Opus 4.7)
- Date: 2026-05-07
- Branch: `03.Points`
- 執行階段：**inventory + plan only**（Phase 0 仍有 10 個 HIGH issues open，依專案規則
  禁止 source code change）

## 文件

| 檔 | 內容 |
|----|------|
| [INVENTORY.md](INVENTORY.md) | 巨大檔案 / 巨大函式 / 重複邏輯 / magic number / silent fallback / 註解覆蓋率 |
| [REFACTOR_PLAN.md](REFACTOR_PLAN.md) | Slice 2–8 順序、commit 規範、rollback 策略 |
| [STYLE_GUIDE.md](STYLE_GUIDE.md) | 註解策略、命名、validation 集中化、fallback 顯性化 |
| [MODULE_SPLIT_PROPOSAL.md](MODULE_SPLIT_PROPOSAL.md) | engine.py / price_runtime.py / route 大檔的具體拆檔方案 |

## 重點 takeaway（給 root 決策用）

1. **本輪不動 source code** — 嚴格遵守 “Phase 0 blocker 全 close 才動工” 規則。
2. **Slice 1（codex 2026-05-06）已抽出**：constants、validators、accounting/、price_fusion/。
   本報告**不重複**已搬內容，只列剩下的問題。
3. **下一個高 leverage 動作**是 Slice 2（strict parser alias + `_now_text` 抽 helper），
   風險低、無行為變化、解 INVENTORY §4.1+§4.3+§4.4 三大重複源頭。
4. **最高風險**是 Slice 5（reference vs risk-grade price 拆模組），但**最有架構性價值**
   — 強制 type system 區分「UI degraded ok」vs「liquidation fail closed」。
5. **Phase 0 10 個 HIGH issues 全列在 INVENTORY §10**；其中 #156（workflow bot step
   counter）與 #181（margin freeze leak）的結構性根因分析在 INVENTORY §9。

## 不在本輪做的事（避免混入）

- 任何 source code change
- 任何 bug fix
- 任何測試新增（前一輪 share-test 補強留在 working tree，未 commit；待 Phase 0 處理完
  後再決定是接續 commit 或 stash 起來等到 Slice 2）
- 任何 schema 動作

## Verdict

**PASS** — 本 slice 目標是 inventory + plan + style guide + module split proposal，
四份文件已完成且互相 cross-reference。Phase 0 完成後可直接接 Slice 2 動工。
