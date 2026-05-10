# PointsChain v2 Implementation Guide for Agents

> 給「下一個動工的 agent」看。
> 不是給 user / admin 看（user-facing 是 [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md)）。
> 不是工程設計書（看 [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md)）。
> **這份是「動工流程約束 + 建議書 + 紅線提醒」。**

---

## ⚠ 0. 動工前的強制條件（絕對不可忽略）

> **任何 agent 在動 PointsChain v2 / Phase 7 任何源碼前，必須完成下列三步。違反此節即構成 release blocker，直接拒收 PR。**

### 0.1 第一步：把當前狀態先推上去

執行動工前的 working tree 必須是「乾淨的、可被別人接手的」。

1. 檢視 `git status`，把目前所有與**區塊鏈計畫無關**的變更整理好：
   - `services/` / `routes/` / `public/` / `server.py` / `tests/` 的既有 fix（例如 codex follow-up 對 #129 / #130 / #131 / PB-1 的修補與 bot audit dashboard）必須先 **commit + push** 到目前分支（`03b.strategy_workflow` 或當下的開發分支）
   - `docs/` 內**非 BLOCKCHAIN/** 的變更（README、03_ADMIN_GUIDE、08_TRADING_ENGINE、TRADING_BOT_AUDIT、09_SNAPSHOT_RESET_RESTORE、SECURITY_MODES、RUNTIME_RESET_AND_RECOVERY 中本次只是補連結的部分）也必須先 push
2. **`docs/archive/research/BLOCKCHAIN/`** 是 PointsChain v2 規格的 canonical 位置，可以**一起或分批** push，但要在 commit message 註明「設計拍板，尚未實作」狀態。
3. CI / pytest / pre-push 必須綠燈。若後續又出現新的 blocker / high issue，必須先在主線收斂，不可直接帶進 `04.blockchain`。

> **不允許帶著未 push 的中間狀態直接開鏈化分支。**
> 否則 review 時你的鏈化變更會跟其他人的小修補糾纏不清，rollback 成本爆炸。

### 0.2 第二步：開新分支 `04.blockchain`

```bash
# 假設你目前在 03b.strategy_workflow 或主開發分支
git checkout -b 04.blockchain
```

從此以後，**所有 PointsChain v2 與 Phase 7 QA Mining 相關的源碼變更只進這個分支**。

- 分支命名固定為 `04.blockchain`，不可任意改名
- 鏈化期間若主線（03b 或之後）有 bug fix，需要 cherry-pick 到 `04.blockchain` 才用，不允許 fast-forward 整個 trunk 進來
- 鏈化分支合併回主線必須一次完成一個 phase（不要 1/3 個 phase 合）
- 每個 phase 完成後必須打 tag：`04.blockchain.phase{N}.YYYYMMDD`，方便回溯

### 0.3 第三步：歡迎建議但執行前必須獲得 root 准駁

> **歡迎你提出**：
> - 新增功能（例如 Phase 8 / 9 的 Content Mining / Validator Reward 提早設計）
> - 修正設計（例如發現 schema 缺欄、API 命名不一致、ledger event_type 漏項）
> - 替換技術選型（例如 ed25519 改 secp256k1、base58check 改 bech32）
> - QA gate 補強（例如某 invariant 沒涵蓋）
>
> **但是**：
> - 提出 → 等 root 拍板 → 才能寫進 `docs/archive/research/BLOCKCHAIN/` 與動工
> - **不可** 自行修改 `docs/archive/research/BLOCKCHAIN/` 既有取捨（除非是純補強而非取代）
> - **不可** 在分支裡先寫一版「等之後再說」，導致設計文件與實作偏離
> - 在 `docs/AGENTS/reports/<agent>/blockchain_proposal_<date>/` 下寫提案，直接 ping root，不要自己決定

提案模板：

```markdown
# 提案：<簡短標題>

## 問題 / 動機

## 我建議的設計

## 對既有 BLOCKCHAIN/ 文件的影響
- 修改 §X：...
- 新增 §Y：...

## 需要 root 拍板的點
1.
2.

## 風險 / 替代方案
```

root 拍板後，先改 `docs/archive/research/BLOCKCHAIN/`、把 status 加上「root approved YYYY-MM-DD」，再動源碼。

### 0.4 第四步：Phase 0 Cleanup Gate（進 Phase 1 前必過清單）

> **完整版本見 [PHASE_0_CLEANUP_GATE.md](PHASE_0_CLEANUP_GATE.md)** — 本節為精簡入口，內容以該檔為 canonical。

Phase 0 = PointsChain v2 鏈化前的清債項目；總計 **19 項**。
Phase 0 cleanup 本身也是源碼變更，**動工前同樣需要 root 個別授權**（即 §0.3 的提案流程）。

#### 結論（2026-05-04 final review）

> **✅ Phase 0 cleanup completed**
>
> 原先的 blocker / recommend / low issues（#122, #135–#142）已完成修復、補 regression、
> isolated live API 驗證與 full pytest。當前狀態是 **ALLOW PHASE 1 CANDIDATE**。
>
> 這不代表可以自動開工。進 Phase 1 仍需要：
> - root 對 `04.blockchain` 的明確批准
> - 使用本文件與 `docs/archive/research/BLOCKCHAIN/` 正式規格作為 canonical source
> - 保持主線工作樹乾淨、test 全綠

#### 19 項整體狀態

| 維度 | 數量 | 詳情 |
|---|---|---|
| ✅ CLOSED / RESOLVED | 18 | #122 / #129 / #130 / #131 / #135 / #136 / #137 / #138 / #139 / #140 / #141 / #142 / **#143**（補登：13.a Trading avg_cost 子項）/ PB-1 / Wallet replay / Trading fee+PnL / Restore v1 機制 / Docs+Tests sync |
| 🟡 PARTIAL / follow-up architecture work | 2 | incident_lockdown 跨路徑 coverage / silent fallback 全站 audit |

#### 系統性反 Pattern（4 條）

完整描述與修法見 [PHASE_0_CLEANUP_GATE.md §1](PHASE_0_CLEANUP_GATE.md#1-系統性反-pattern)：

1. **Silent Fallback** — 上游髒資料、下游 default 消化、API 回 200。命中 #136 / #137 / #139 / #142 / #129。
2. **宣告但未強制（schema declared, never enforced）** — `FEATURE_DEPENDENCY_RULES` / `DEFAULT_SETTINGS` 缺中央 validator。命中 #136 / #137 / #140。
3. **Self-Action Guard 不對齊** — `block` 漏 `actor.id == user_id` 比對。命中 #135。
4. **Settings 缺中央 Schema Validator** — `/api/admin/settings` PUT 用 hand-pick if-block。命中 #136 / #137。

> **必修**：[PHASE_0_CLEANUP_GATE.md §1.4](PHASE_0_CLEANUP_GATE.md#14-settings-缺中央-schema-validator) 提出的中央 `SETTING_SCHEMA` 是 #136 / #137 / #140 三件的共同根治路徑，動工時應同步落地，避免逐 key 補修。

#### 19 項 cleanup 詳情

每項 issue 的 **risk / affected module / required fix / verification command / expected result / release gate status / evidence path** 全部寫在 [PHASE_0_CLEANUP_GATE.md §2 Cleanup Items](PHASE_0_CLEANUP_GATE.md#2-cleanup-items19-項) ，動工 agent 必須讀過該章節對應條目並 verify 通過。

簡表（severity 排序）：

| # | Issue | Severity | 一句話 | 對應 Item |
|---|---|---|---|---|
| 1 | [#122](https://github.com/s9213712/hackme_web/issues/122) | ✅ CLOSED | 30s polling 漏觸發 stop-loss / liquidation | [Block-1](PHASE_0_CLEANUP_GATE.md#block-1-github-122--30s-polling-漏觸發-stop-loss--liquidation-) |
| 2 | [#135](https://github.com/s9213712/hackme_web/issues/135) | ✅ CLOSED | Admin self-block：root 可自我封鎖 | [Block-2](PHASE_0_CLEANUP_GATE.md#block-2-github-135--admin-self-block-) |
| 3 | [#136](https://github.com/s9213712/hackme_web/issues/136) | ✅ CLOSED | settings silent boolean coerce | [Block-3](PHASE_0_CLEANUP_GATE.md#block-3-github-136--settings-silent-boolean-coerce-) |
| 4 | [#137](https://github.com/s9213712/hackme_web/issues/137) | ✅ CLOSED | settings range / format validation gap | [Block-4](PHASE_0_CLEANUP_GATE.md#block-4-github-137--settings-range--format-validation-gap-) |
| 5 | [#138](https://github.com/s9213712/hackme_web/issues/138) | ✅ CLOSED | wallets/<id> 500 + traceback leak | [Recommend-5](PHASE_0_CLEANUP_GATE.md#recommend-5-github-138--walletsid-500--traceback-leak-) |
| 6 | [#139](https://github.com/s9213712/hackme_web/issues/139) | ✅ CLOSED | IP whitelist accepts non-IP | [Recommend-6](PHASE_0_CLEANUP_GATE.md#recommend-6-github-139--ip-whitelist-accepts-non-ip-silent-skip-) |
| 7 | [#140](https://github.com/s9213712/hackme_web/issues/140) | ✅ CLOSED | FEATURE_DEPENDENCY_RULES not enforced | [Recommend-7](PHASE_0_CLEANUP_GATE.md#recommend-7-github-140--feature_dependency_rules-not-enforced-) |
| 8 | [#129](https://github.com/s9213712/hackme_web/issues/129) | ✅ RESOLVED | backtest API candles<2 silent fetch | [Resolved-8](PHASE_0_CLEANUP_GATE.md#resolved-8-github-129--backtest-api-candles2-silent-fetch-) |
| 9 | [#130](https://github.com/s9213712/hackme_web/issues/130) | ✅ RESOLVED | backtest engine no outlier filter | [Resolved-9](PHASE_0_CLEANUP_GATE.md#resolved-9-github-130--backtest-engine-no-outlier-filter-) |
| 10 | [#131](https://github.com/s9213712/hackme_web/issues/131) | ✅ RESOLVED | Bollinger Band false trigger flat seq | [Resolved-10](PHASE_0_CLEANUP_GATE.md#resolved-10-github-131--bollinger-band-false-trigger-on-flat-sequence-) |
| 11 | PB-1 | ✅ RESOLVED | NaN exception leak | [Resolved-11](PHASE_0_CLEANUP_GATE.md#resolved-11-pb-1--nan--invalid-numeric-input-exception-leak-) |
| 12 | — | ✅ RESOLVED | Wallet / Ledger Replay 一致性 | [Resolved-12](PHASE_0_CLEANUP_GATE.md#resolved-12-wallet--ledger-replay-一致性-) |
| 13 | — | ✅ RESOLVED | Trading Fee / PnL Correctness | [Resolved-13](PHASE_0_CLEANUP_GATE.md#resolved-13-trading-fee--pnl-correctness-) |
| 13.a | [#143](https://github.com/s9213712/hackme_web/issues/143) | ✅ CLOSED | Incremental spot buys corrupt avg_cost_points (子項，補登) | [Resolved-13 子項 13.a](PHASE_0_CLEANUP_GATE.md#子項-13a--github-143-incremental-spot-buys-corrupt-avg_cost_points-) |
| 14 | — | ✅ RESOLVED | Restore / Snapshot Correctness（v1） | [Resolved-14](PHASE_0_CLEANUP_GATE.md#resolved-14-restore--snapshot-correctness-) |
| 15 | — | 🟡 PARTIAL | Incident Lockdown 跨路徑 Coverage | [Partial-15](PHASE_0_CLEANUP_GATE.md#partial-15-incident-lockdown-跨路徑-coverage-) |
| 16 | — | 🟡 PARTIAL | Silent Fallback Audit（全站） | [Partial-16](PHASE_0_CLEANUP_GATE.md#partial-16-silent-fallback-audit全站-) |
| 17 | PB-2/PB-3 | ✅ RESOLVED | Docs / Tests Sync | [Resolved-17](PHASE_0_CLEANUP_GATE.md#resolved-17-docs--tests-sync-) |
| 18 | [#141](https://github.com/s9213712/hackme_web/issues/141) | ✅ CLOSED | test scans .venv site-packages | [Low-18](PHASE_0_CLEANUP_GATE.md#low-18-github-141--test-scans-venv-site-packages-) |
| 19 | [#142](https://github.com/s9213712/hackme_web/issues/142) | ✅ CLOSED | prompt_password stdout pollution | [Low-19](PHASE_0_CLEANUP_GATE.md#low-19-github-142--prompt_password-stdout-pollution-) |

#### Phase 0 完成出口（root 授權實作後）

完整 checklist 見 [PHASE_0_CLEANUP_GATE.md §3](PHASE_0_CLEANUP_GATE.md#3-phase-0-完成出口root-授權實作後)，動工 agent 必須逐項勾完才算 Phase 0 完成；下列為摘要：

- [x] **必修四件**：#122 / #135 / #136 / #137 全部 close + verification PASS
- [x] **強烈建議併修**：#138 / #139 / #140（避免 Phase 1+ 重做）
- [ ] **既有持續項目**：#129 / #130 / #131 / PB-1 持續綠；silent fallback 全站 audit；incident_lockdown 跨路徑 hook
- [x] **Low cleanup**：#141 / #142
- [x] **Docs / 簽核**：ENGINEERING/QA/README 狀態同步；報告歸檔；等待 root 是否批准 Phase 1

#### 動工選項（root 三選一）

> **目前狀態：✅ ALLOW PHASE 1 CANDIDATE**
>
> root 現在要決定的是是否批准正式動工，而不是是否還要先解 blocker：
>
> - **選項 A**（建議）：批准開 `04.blockchain`，按本文件順序開始 Phase 1
> - **選項 B**：暫不開工，只維持設計文件與 final review 結論，待後續產品時程再啟動

---

## 1. 你必須先讀完的 docs（依順序）

| 順序 | 文件 | 為什麼 |
|---|---|---|
| 1 | [README.md](README.md)（本資料夾） | 知道整個 BLOCKCHAIN/ 的位置與彼此關係 |
| 2 | [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md) | 知道對 user 我們承諾了什麼 |
| 3 | [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) | 知道 8 個 phase / schema / API / 對既有系統影響 |
| 4 | [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) | 知道每個 phase 的出口 gate 與紅線 |
| 5 | [../AGENTS/RULES_FOR_AGENTS.md](../AGENTS/RULES_FOR_AGENTS.md) | 知道全專案工作原則（文件 / 測試 / 手機版 / 伺服器端運算） |
| 6 | [../AGENTS/QA_MISSION_FOR_AGENTS.md](../AGENTS/QA_MISSION_FOR_AGENTS.md) | 知道隔離測試流程 |
| 7 | `docs/AGENTS/reports/*` 下的 prechain / final review 報告 | 歷史 evidence 與測試歸檔；不是 current spec |
| 8 | 對應你動的 phase 文件 | 詳細規格 |

對應 phase 的 detail 文件：

| Phase | 主文件 | 補充 |
|---|---|---|
| 1 | [POINTS_WALLET_ADDRESSING.md](POINTS_WALLET_ADDRESSING.md) | ENGINEERING §3 |
| 2 | [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) §4 | QA §4 |
| 3 | [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md) | ENGINEERING §5 |
| 4 | [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) | ENGINEERING §6 |
| 5 | [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) §7 | QA §7 |
| 6 | [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) §8 | QA §8 |
| 7 | [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md) | ENGINEERING §8a / QA §8a |

---

## 2. 動工順序（不可亂跳）

```
Phase 0 ✅ (cleanup / runtime cleanup / isolated live validation / full pytest 已完成)
   │
Phase 1  ← 從這裡開始
   │
Phase 2  ← 必須 Phase 1 出口 gate 全綠才能開
   │
Phase 3
   │
Phase 4  ← Phase 7 多簽路徑依賴此
   │
Phase 5
   │
Phase 6  ← Phase 7 explorer 依賴此
   │
Phase 7 (QA Mining)  ← Phase 0 cleanup closed; implementation
                       blocked until Phase 1 / 2 / 4 / 6 complete and
                       root separately authorizes Phase 7
```

### 2.1 不允許「先做 Phase 7 prototype 上線」
- Phase 0 cleanup 已 closed；但 Phase 1 / 2 / 4 / 6 沒完成前**只允許 DRAFT / mock / dry-run**
- mock 階段：可以建立 schema、寫 service、跑 unit test，但**不可真實 payout**
- dry-run 階段：可在 dev_ready 模式下 simulate，但 ledger 寫入要標 `is_dryrun=1` 並在 incident_lockdown 時自動清

### 2.2 不允許「Phase 並行」
- 鏈核心建議單線推進降低 race condition 風險
- 例外：UI 與後端可並行，但兩端 schema / API 必須 lock 後再動 UI

### 2.3 AI Agent 平行軌道（Design approved，implementation NOT authorized）

> AI Agent Stage A 是與 PointsChain phase plan 並行的軌道，但與本文件 §2.2 「不允許 Phase 並行」不衝突 — agent 不寫 chain，不動 wallet schema，僅讀 user / system 既有資料。

**狀態**：
```
AI Agent Stage A is design-approved.
AI Agent Skill Layer proposal is approved in principle (docs-only merged).
Phase 0 cleanup blockers are already closed.
Implementation still requires AGENT_STAGE_A_GATE §8.A A1–A7
(incl. A7 skill layer)
and explicit root approval.
```

**動工門檻**：
- Phase 0 Cleanup Gate blockers 已 close
- [`AGENT_STAGE_A_GATE.md §8.A` Implementation Authorization Gate](../AGENTS/reports/claude/ai_agent_design_2026-05-04/AGENT_STAGE_A_GATE.md#8a-implementation-authorization-gate動工前) A1–A7 全綠（A7 = skill layer docs-only 升級已完成；正式啟動仍需 root 核准）
- root 對 Stage A implementation 個別簽核
- 新分支 / 隔離環境，不可在 main / production 直接動工
- 嚴格限定 Stage A 只做 5 個 read-only tools + 5 個對應 skill markdown

**對 PointsChain v2 phase plan 的依賴**：
- Stage A：不依賴 wallet_addresses，可在 root 核准後動
- Stage B：依賴 Phase 1（wallet_addresses）+ Phase 2（ledger v2）；新增第 10 個官方地址 `AI_AGENT_OPS` + `AI_AGENT_OPS_ESCROW`
- Stage C：依賴 Phase 4 multisig（30 天觀察期後）
- Stage D：依賴 Phase 7 QA Mining

**正式設計文件位置**：[../AGENTS/reports/claude/ai_agent_design_2026-05-04/](../AGENTS/reports/claude/ai_agent_design_2026-05-04/)

---

## 3. 每個 Phase 動工流程模板

每個 phase 都套這個流程：

### 3.1 phase 啟動 checklist

- [ ] 上一 phase 出口 gate 100% 過（`docs/archive/research/BLOCKCHAIN/POINTSCHAIN_QA.md` 對應 §）
- [ ] 已通知 root「準備動 Phase N」並獲准
- [ ] 在 `docs/AGENTS/reports/<agent>/pointschain_v2_phase{N}_<date>/` 開報告目錄
- [ ] 開好 isolated QA workspace（`/tmp/hackme_web_blockchain_qa_<phase>_<ts>/`）

### 3.2 動工順序

1. **Schema migration** 寫好 + ALTER + 自動 backfill
2. **Service layer** (`services/points_chain.py` 或新 module) — 含所有 invariant guard
3. **Routes** (`routes/economy.py` 或新 file) — 含 CSRF / role check / rate limit
4. **Pytest** — 對應 phase 的 QA 文件項目逐項驗
5. **smoke / pentest** — 跑 `tests/smoke_suite.py` + 對應的 pentest scripts
6. **UI** — 後台 dashboard / 用戶頁 / mobile RWD 8 breakpoint
7. **Docs sync** — 對應 BLOCKCHAIN/ 文件補實際路徑、line number、測試命令
8. **Audit / monitoring** — 補 `secure_audit` event + dashboard metric
9. **Phase gate report** — 寫 `PHASE{N}_GATE_REPORT.md` 並請 root review

### 3.3 phase 完成 checklist

- [ ] 對應 QA gate 全勾
- [ ] pytest 100% 綠（含原 `tests/` + 新增）
- [ ] smoke / functional / pentest 全 PASS
- [ ] 報告歸檔在 `docs/AGENTS/reports/<agent>/pointschain_v2_phase{N}_<date>/`
- [ ] BLOCKCHAIN/ 對應文件加上「Phase N 實作完成 YYYY-MM-DD」狀態
- [ ] root 簽核
- [ ] 打 tag `04.blockchain.phase{N}.YYYYMMDD`

---

## 4. 不可踩的紅線（任一違反 = release blocker）

### 4.1 鏈核心紅線

- ❌ `OFFICIAL_BURN` / `OFFICIAL_MINT` 寫入 `encrypted wallet secret`
- ❌ ledger 寫入 `from_address=OFFICIAL_BURN`
- ❌ 一般 transfer 路徑寫入 `to_address=OFFICIAL_MINT`（mint 必走 multisig）
- ❌ multisig threshold = 1
- ❌ supply invariant 失敗仍可繼續啟動 server
- ❌ chain block hash 鏈中斷
- ❌ private key 出現在 log / API response / stack trace / `secure_audit`

### 4.2 Phase 7 QA Mining 紅線

- ❌ reporter == verifier 仍能 approve
- ❌ admin 單人 approve reward ≥ 1000
- ❌ root 自己領獎不走 multisig
- ❌ multisig signer 對自己相關 reward 仍能投票
- ❌ reward_pool 餘額變負
- ❌ reward 公式繞過 hard cap
- ❌ incident_lockdown 期間 mining payout 仍 execute
- ❌ **第一版自動 burn 用戶資產**
- ❌ explorer 洩漏 user_id / IP / device

### 4.3 流程紅線

- ❌ 跳過上一 phase 出口 gate 直接做下一 phase
- ❌ 私自修改 `docs/archive/research/BLOCKCHAIN/` 既有設計取捨而沒先 root 拍板
- ❌ 跳過 isolated QA 直接動 production runtime
- ❌ 鏈化分支 fast-forward 整個 trunk
- ❌ Phase 7 在 Phase 1 / 2 / 4 / 6 完成且 root 個別授權 Phase 7 之前真實 payout（Phase 0 cleanup 已 closed，不再是阻擋條件）

---

## 5. 對既有系統的修改範圍預期

每個 phase 大致改動的檔案（**僅供估算，實際以 ENGINEERING / 各 phase 文件為準**）：

| Phase | 預期改動檔案 |
|---|---|
| 1 | `services/points_chain.py`（schema migration + 9 官方地址）、`routes/economy.py`（讀地址 endpoint）、`public/js/55-economy.js`（個人頁地址欄）、`tests/test_points_wallet_addresses.py` (新)、`tests/test_supply_invariant.py` (新) |
| 2 | `services/points_chain.py`（dual-write）、`services/trading_engine.py`（fee_pool dual-write）、`services/videos.py`（tip event）、`services/snapshots.py`（manifest 加 supply_state hash） |
| 3 | `routes/economy.py`（transfer endpoints）、`services/points_chain.py`（transfer service）、`public/js/55-economy.js`（轉帳頁）、`tests/test_points_transfer.py` (新) |
| 4 | `services/points_chain.py`（multisig service）、`routes/economy.py`（multisig endpoints）、`public/js/50-admin.js`（後台 proposal 頁） |
| 5 | `public/js/55-economy.js`（self-custody 啟用 + 簽章）、`services/auth.py`（signer 整合？）、`tests/test_self_custody_signature.py` (新) |
| 6 | `routes/economy.py`（explorer endpoints）、`public/explorer.html` (新) + `public/js/explorer.js` (新)、`tests/test_explorer.py` (新) |
| 7 | `routes/bug_reports.py`（升級欄 + mining claim 連結）、`services/mining/...` (新 module)、`public/js/mining-center.js` (新)、`tests/test_mining_*.py` (新 5 個) |

**重點**：每個 phase 的源碼改動 + 文件補強 + pytest 補強 必須一次到位，不允許「先寫 code 之後補測試」。

---

## 6. QA gate 與報告歸檔

每個 phase 完成都要產出 `docs/AGENTS/reports/<agent>/pointschain_v2_phase{N}_<date>/`：

```
pointschain_v2_phase{N}_<date>/
├── README.md                      # 對應 phase 摘要
├── PHASE{N}_GATE_REPORT.md        # 出口 gate 逐項 PASS 證據
├── scripts/                       # 自動測試 runner
│   ├── 01_<key_test_1>.py
│   └── ...
└── evidence/                      # JSON 結果 + log
    ├── schema/
    ├── replay/
    ├── ui/
    └── ...
```

GATE_REPORT.md 模板可沿用既有 `docs/AGENTS/reports/*` 的報告格式：Verdict / Branch / Commit / Coverage Matrix / Findings / Required Fixes，但 canonical 狀態仍以 `docs/archive/research/BLOCKCHAIN/` 為準。

---

## 7. 提案新功能或修正的方式

> 你看到 `BLOCKCHAIN/` 有設計缺漏 / 想加新功能 / 想替換技術選型？

### 7.1 流程

1. 在 `docs/AGENTS/reports/<agent>/blockchain_proposal_<topic>_<date>/PROPOSAL.md` 寫提案
2. 提案內列：問題、建議、影響、風險、替代
3. ping root 並等待答覆（不要自己動）
4. root 拍板：
   - 同意 → 由你或 root 指定的 agent 升級 `BLOCKCHAIN/` 對應文件 → 再動工
   - 拒絕 → 提案存檔，狀態標 `rejected`
   - 部分同意 → 列出 root 修改後的版本，重新確認

### 7.2 鼓勵提案的範圍

- 補強 / 細化（不破壞既有取捨）
- 加新 phase（如 Phase 8 / 9）
- 找出 schema 缺欄 / API 命名不一致 / ledger event 漏項
- 補強紅線檢查
- 跨 phase 一致性問題

### 7.3 不鼓勵提案的範圍

- 把 ed25519 改 secp256k1（除非有強理由；root 已選）
- 把 PNT1 base58check 改其他格式
- 降低 multisig 門檻（永遠 ≥ 2 是紅線）
- 加「root 一鍵 mint」的便利路徑
- 改 reward 公式跳過 hard cap

如果你還是想提案改紅線範圍 → 在 PROPOSAL.md 開頭明確標 `WARNING: PROPOSING CHANGE TO RED LINE`，root 會看得格外仔細。

---

## 8. 跨 agent 協作

如果你不是第一個動工的 agent，動工前：

1. 看 `docs/AGENTS/reports/<all-agents>/pointschain_v2_phase*_<date>/` 目錄，了解前面 agent 跑到哪
2. `git log 04.blockchain --oneline` 看歷史
3. 看 `docs/archive/research/BLOCKCHAIN/` 是否已有「Phase N 實作完成」狀態標記
4. 開工前 ping root「我準備接手 Phase X 從 step Y 開始」

避免：

- 同一 phase 多 agent 重複做
- 不同 agent 對同一 schema 各寫一版
- 直接 force-push 鏈化分支

---

## 9. 何時需要 root 介入

立即停手並 ping root：

- 發現 invariant boot-time check 失敗（supply 不對 / ledger replay 不對 / chain hash 斷）
- 發現紅線被踩（§4 任一）
- 發現某 phase 設計與另一 phase 衝突
- multisig signer 名單需要更換但你不是 root
- supply hard cap 達到需要 multisig 改 cap
- 鏈化分支與主線出現 merge conflict 在 schema 層
- production 出現 incident_lockdown 但不知道是設計預期還是 bug

不需要 ping root（自己處理）：

- 一般 lint / 格式問題
- pytest 失敗自己修
- 補測試 / 補 docs（在不改設計取捨的前提下）
- code review feedback

---

## 10. 動工開始前最後檢查

在你寫第一行 PointsChain v2 / Phase 7 源碼前再次確認：

- [ ] 我已 push 完所有非區塊鏈相關變更到原分支
- [ ] 我已 `git checkout -b 04.blockchain`
- [ ] 我已讀完 **本 phase 必讀**的文件（依下表，非全部 18 份）
- [ ] 我知道我接的是哪個 phase
- [ ] 我已通知 root 並獲得「動工」明確授權
- [ ] 我已建立 `docs/AGENTS/reports/<agent>/pointschain_v2_phase{N}_<date>/` 報告目錄
- [ ] 我已建立 isolated QA workspace
- [ ] 我已準備好對應的 pytest 與 evidence 收集

### Phase-specific required reading

不要要求每個 agent 都讀完整個 `docs/archive/research/BLOCKCHAIN/`（含 governance / mining / dispute）。下表列每個 phase 的**必讀最小集**，其他文件按需查閱：

| Phase | 必讀（依序） |
|---|---|
| **Phase 1（地址化）** | README.md → IMPLEMENTATION_GUIDE.md（本檔） → POINTSCHAIN_ENGINEERING.md §1–4 → POINTS_WALLET_ADDRESSING.md → POINTSCHAIN_QA.md §1–3 → PHASE_0_CLEANUP_GATE.md（context） |
| **Phase 2（Ledger v2）** | README → IMPLEMENTATION_GUIDE → POINTSCHAIN_ENGINEERING.md §4 → POINTSCHAIN_QA.md §4 |
| **Phase 3（Transfer）** | README → IMPLEMENTATION_GUIDE → POINTS_TRANSFER_API.md → POINTSCHAIN_QA.md §5 |
| **Phase 4（Multisig）** | README → IMPLEMENTATION_GUIDE → MULTISIG_WALLETS.md → POINTSCHAIN_QA.md §6 |
| **Phase 5（Self-custody）** | README → IMPLEMENTATION_GUIDE → POINTSCHAIN_ENGINEERING.md §7 → POINTSCHAIN_QA.md §7 |
| **Phase 6（Explorer）** | README → IMPLEMENTATION_GUIDE → POINTSCHAIN_ENGINEERING.md §8 → POINTSCHAIN_QA.md §8 |
| **Phase 7（QA Mining）** | README → IMPLEMENTATION_GUIDE → POINTS_MINING_REWARDS.md → POINTSCHAIN_QA.md §8a |
| **Governance phase G-0 / G-1** | README → IMPLEMENTATION_GUIDE → GOVERNANCE_FRAMEWORK.md → GOVERNANCE_PROPOSAL_LIFECYCLE.md → GOVERNANCE_QA_GATE.md |
| **Governance phase G-2** | 上 4 份 + POINTS_MONETARY_POLICY.md + TREASURY_BUDGET_POLICY.md |
| **Governance phase G-3** | 上 6 份 + EMERGENCY_GOVERNANCE.md + DISPUTE_AND_APPEALS.md |
| **Governance phase G-5** | 上 8 份 + GOVERNANCE_VOTING_POWER.md |

> Phase 1 地址化的 agent **不需要讀完**整套 governance / mining / dispute 文件。
> 跨 phase 的設計取捨已透過 §10「文件關係圖」串連；需要時用 `grep` 查具體規則即可，不必全文背誦。
> Governance docs 仍是 **draft / approval pending**，Phase 1–6 動工不依賴它。

任一未勾 → 不要動工。

---

## 11. 文件關係圖

```
docs/archive/research/BLOCKCHAIN/
├── README.md                          ← 進入點 / 索引
├── IMPLEMENTATION_GUIDE.md            ← 本文件 / 給 agent
├── POINTSCHAIN_WHITEPAPER.md          ← user 看的承諾
├── POINTSCHAIN_ENGINEERING.md         ← dev 看的工程地圖
├── POINTSCHAIN_QA.md                  ← qa 看的 gate
├── POINTS_WALLET_ADDRESSING.md        ← Phase 1 詳規
├── POINTS_TRANSFER_API.md             ← Phase 3 詳規
├── MULTISIG_WALLETS.md                ← Phase 4 詳規
└── POINTS_MINING_REWARDS.md           ← Phase 7 詳規

docs/AGENTS/reports/<agent>/
├── prechain_qa_2026-05-04/                              ← Phase 0 base line
├── multi_role_audit_2026-05-04/                         ← Multi-role audit 證據
└── pointschain_v2_phase{N}_<date>/                      ← 之後 agent 動工每個 phase 的報告（你會自己建）
```

---

## 12. 最終提醒

> **這是獎勵系統，不是印鈔系統。**
> **這是區塊鏈，不是資料庫包裝。**
> **這份指引是為了讓鏈化能被別人接手，不是為了讓設計被一個人擅改。**

對齊 [POINTSCHAIN_WHITEPAPER.md §12](POINTSCHAIN_WHITEPAPER.md) 與
[POINTS_MINING_REWARDS.md §24](POINTS_MINING_REWARDS.md)：

| 精神 | 你動工時的對應 |
|---|---|
| 不要把錯誤上鏈 | 每寫一段 service 都先想「這個錯誤會不會被永久寫進 chain block？」 |
| 不要把錯誤永久化 | invariant guard 寫在 boot-time + write-time + seal-time 三層 |
| 不讓區塊鏈變成 bug 永久保存器 | snapshot/restore 寫 marker；reconcile 不過進 incident_lockdown |
| 官方絕不單人濫權 | multisig 永遠 ≥ 2；signer 對自己相關決議自動排除 |
| 使用者自主但不被迫 | custodial 預設；self-custody opt-in 含 2 警告 + 倒數 |
| 獎勵不是印鈔 | reward_pool 補充走 multisig；不允許自動 mint / 自動 burn |
| 可審計可重建 | 每筆變動進 ledger_v2 + chain_block_v2 + audit chain |
| 不洩漏個資 | explorer 永不顯 user_id / IP / device / 私鑰 |

---

*Implementation Guide v1 by Claude，root 拍板 2026-05-04。*
*動工授權需 root 個別簽核。*
*動工後遇任何疑問先停手再 ping root。*
