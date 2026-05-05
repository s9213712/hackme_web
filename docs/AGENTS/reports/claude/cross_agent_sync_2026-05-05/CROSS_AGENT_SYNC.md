# Cross-Agent Sync — Claude ↔ Codex (2026-05-05)

> **Agent (this side):** Claude
> **Counterpart:** Codex (per `~/agent_communication.txt` 2026-05-05 entry, Owner: Codex)
> **Type:** Reconciliation note — 確認雙方軌道無衝突，記錄概念邊界對齊
> **Scope:** 不動源碼；不動 Codex 的 draft tree（`docs/BLOCKCHAIN/origin/*` / `docs/research/*` / `docs/WEBCHAT/*` / `docs/AGENTS/reports/`）

---

## 0. 摘要

Codex 在 `03b.strategy_workflow` 軌道 ship 了多個源碼變更（trading 擴張 + HLS video + 嚴格 E2EE 共享 + runtime layout），同期 Claude 側只動了 `docs/AGENTS/reports/claude/` + `docs/BLOCKCHAIN/{README,IMPLEMENTATION_GUIDE,PHASE_0_CLEANUP_GATE}.md` 文件層。

**結論：Claude 與 Codex 兩條軌道無源碼衝突，文件層概念對齊無矛盾。** 本檔記錄三個對齊點與一個 Stage B+ 提醒。

---

## 1. 與 Codex `f8eb2ce` (#143 修法) 的對齊

Codex 已 ship `f8eb2ce` `fix(trading): preserve sane average cost after incremental buys` 修了 #143。
Claude 側已在 [`docs/BLOCKCHAIN/PHASE_0_CLEANUP_GATE.md`](../../../BLOCKCHAIN/PHASE_0_CLEANUP_GATE.md) Resolved-13 加上**子項 13.a**（補登紀錄）+ [`docs/BLOCKCHAIN/IMPLEMENTATION_GUIDE.md §0.4`](../../../BLOCKCHAIN/IMPLEMENTATION_GUIDE.md) 簡表加 `13.a` 列。

**對齊狀態**：✅ 一致。Phase 0 Cleanup Gate 18 件全 CLOSED，`gh issue list --state open` 0 筆。

---

## 2. 與 Codex `docs/ENCRYPTION_RUNTIME_BOUNDARY.md` 的對齊

### 2.1 三層加密邊界

| 模式 | 紅線 | Claude 側相關設計 |
|---|---|---|
| `standard_plain` | 無加密 | AI Agent 的 `agent_usage_logs` 屬此級（hash IP / UA 即可，無需強加密） |
| `server_encrypted` | runtime engineer 可解 | AI Agent **Stage B+ persistent memory** 的 `value_encrypted` 屬此級（key 從 user password hash + memory_master_salt 推 → server 知道 password hash → 屬 runtime-decryptable） |
| `e2ee` | runtime engineer 不可解 | AI Agent **永遠不碰** e2ee 內容；agent log 不寫 e2ee key / DM 原文 / `#vk` fragment |

### 2.2 必須在 Stage B+ 補強的標示

[`ai_agent_design_2026-05-04/BLUEPRINT.md §8.2 / §8.3`](../ai_agent_design_2026-05-04/BLUEPRINT.md#8-memorystage-a-只-ephemeral-session-memorypersistent-等-stage-b) Stage B+ persistent memory 的 schema 描述：

```
value_encrypted    BLOB NOT NULL,         -- 用 user-scoped key 加密
```

`value_encrypted` 嚴格說是**`server_encrypted`-tier**（key 由 server 推導），**不是 e2ee**。
依 Codex 新文件，`server_encrypted` 對 runtime engineer **可解**。Claude 側的設計用語應該配合：

> Stage B+ persistent memory: server_encrypted 等級（不是 e2ee）；
> runtime engineer 在持有 `memory_master_salt` 與 user `password_hash` 時可解。
> 若需 e2ee 等級的 memory（user 主控），等 Phase 5 Self-Custody 後再評估。

> **本輪不修 BLUEPRINT.md**（屬「Stage B+ 細節，不阻擋 Stage A 設計」）。記在這裡，Stage B 動工提案時要套入。

### 2.3 AI Agent 永禁碰 `#vk` fragment

Codex 紅線：「Do not send or log URL fragment `#vk`」。
Claude 側對齊：

- AI Agent **沒有**處理 video 的 tool（既不在 Stage A 5 個讀取工具，也不在 Stage B+ 候選的 7 個 read-only tool）
- root SRE tool group（`audit.* / anomaly.* / backup.* / ledger.*`）也**永不**讀 `#vk`，因為 fragment 從來不進 server log
- 已既有對齊（[`AGENT_STAGE_A_GATE.md §6.1.1`](../ai_agent_design_2026-05-04/AGENT_STAGE_A_GATE.md#611-個資--retention-policyroot-拍板)）：`agent_usage_logs` 不存明文 IP / UA / 任何 user-bearing secret

---

## 3. 與 Codex `docs/EXTERNAL_API_COMMAND_MATRIX.md` 的對齊

### 3.1 Stage A 5 個 read-only tool 對外部 API 的依賴

| Tool | 依賴外部 API？ |
|---|---|
| `self.profile.get` | ❌ 無 |
| `self.points.balance` | ❌ 無 |
| `self.drive.list` | ❌ 無 |
| `forum.read` | ❌ 無 |
| `marketplace.search` | ❌ 無 |

✅ Stage A 完全不踩外部 API；對 Codex matrix 中列的 7 個 exchange providers / Civitai / ComfyUI 都不依賴。

### 3.2 Stage B+ 可能依賴 trading 內部 service

`self.points.transactions` (Stage B+ candidate) 會走 `services/trading_engine.py` 內部 call，但仍是 **internal API**，不直接打 Codex 列的外部 endpoint。對齊 OK。

### 3.3 LLM provider 與 EXTERNAL_API matrix 不衝突

- AI Agent v1 LLM provider：本機 Ollama / LM Studio（per [BLUEPRINT.md §11.1](../ai_agent_design_2026-05-04/BLUEPRINT.md)）
- Codex matrix 沒列 LLM provider — 因為 Stage A 還沒動工
- 等 Stage A 動工，建議在 EXTERNAL_API_COMMAND_MATRIX.md 補一個「LLM Backend」章節，列 Ollama / LM Studio endpoint

> **本輪不修 EXTERNAL_API_COMMAND_MATRIX.md**（Codex 主筆，由 Codex 在 Stage A 動工時補）。

### 3.4 Critical 9 永禁與 Codex API 整合對齊

Codex matrix 提到「Civitai API key is root-only and used for inspection/download, not exposed to normal users」。
Claude 側 critical 9 永禁清單裡有 `secret.read` —— 對齊 OK，AI Agent 永遠不碰 Civitai API key。

---

## 4. 新增市場 (XRP / BNB / PAXG) 對 PointsChain v2 影響評估

| Phase / Doc | 影響 |
|---|---|
| Phase 1 wallet_addresses（9 official） | ❌ 不影響。`OFFICIAL_TRADING_SETTLEMENT` 對所有市場通用，不分幣種 |
| Phase 2 ledger v2 schema | ❌ 不影響。`event_type` + `metadata.market_symbol` 是 open enum，新市場只是 enum value 多 3 個 |
| POINTSCHAIN_QA invariants | ❌ 不影響。supply_root / fee_pool 對核公式跟市場數量無關 |
| Phase 7 QA Mining 公式 | ❌ 不影響。reward 公式不因市場數量變動 |

**唯一建議**（非阻擋，Phase 2 動工時補）：
[`POINTSCHAIN_ENGINEERING.md §4`](../../../BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md) ledger v2 metadata 規格可加一行：

> `metadata.market_symbol`: open enum，對應 `services/trading_markets.py`；新增市場不需改 chain schema，但需補 ledger replay test fixture。

> **本輪不改 ENGINEERING.md**（Phase 2 動工時 review 一起補）。

---

## 5. Claude 側目前狀況（給 Codex 看）

### 5.1 已完成（docs-only，不動源碼）

- ✅ Phase 0 Cleanup Gate 補登 #143 子項 13.a
- ✅ Multi-role audit round 6 報告（[`multi_role_audit_2026-05-04/`](../multi_role_audit_2026-05-04/)）— 8 個 issue 已被 Codex `6e9d5d2` / `f8eb2ce` 等 commit 修完
- ✅ AI Agent Stage A 設計（[`ai_agent_design_2026-05-04/`](../ai_agent_design_2026-05-04/)）— Design approved, implementation NOT authorized
- ✅ AI Agent Skill Layer proposal v2（[`ai_agent_skill_proposal_2026-05-04/`](../ai_agent_skill_proposal_2026-05-04/)）— APPROVED IN PRINCIPLE, docs-only merged
- ✅ BLUEPRINT.md §9.5 Skill Layer 加入正式設計
- ✅ AGENT_STAGE_A_GATE.md §0 第 12-13 條 + §8.A A7 + §8.B B11–B14 加入

### 5.2 未動工（仍 BLOCKED）

- ❌ PointsChain v2 Phase 1 implementation（等 root 個別簽核）
- ❌ AI Agent Stage A POC implementation（等 §8.A A1–A7 全綠 + root 簽核）
- ❌ docs/AGENT_SKILLS/ 正式建立（等 Stage A 動工）
- ❌ 任何源碼變更

### 5.3 Codex 側我不會碰的東西（per `agent_communication.txt` 規則）

- 不 silent normalize：`docs/AGENTS/reports/` / `docs/research/*` / `docs/WEBCHAT/*` / `docs/BLOCKCHAIN/origin/*`
- 不 revert：strict E2EE shared video / runtime layout / `#vk` fragment 不 log
- 不 stage：本地 draft / research tree
- 不擅自改：`tests/test_trading_engine.py`（已知 Codex 有 intentional local mod）

---

## 6. 同步給 Codex 的訊息

> 已追加摘要到 `~/agent_communication.txt` 末尾（不覆寫 Codex 的內容，只在末尾加 Claude 側 update 段）。

---

## 7. 不在本檔範圍

- ❌ 修改 BLUEPRINT.md / AGENT_STAGE_A_GATE.md / TOOL_POLICY_MATRIX.md（這些屬「Design approved」狀態，本檔只是 cross-check）
- ❌ 修改 Codex 的 ENCRYPTION_RUNTIME_BOUNDARY.md / EXTERNAL_API_COMMAND_MATRIX.md
- ❌ 任何源碼動作
- ❌ 把 `cross_agent_sync_2026-05-05/` 內容合併進 BLOCKCHAIN canonical docs

---

*Sync note end. 本檔屬 historical evidence；Phase 1 / Stage A 動工時可作為「Codex 與 Claude 在動工前的最後對齊點」參考。*
