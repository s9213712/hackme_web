# Emergency Governance v1

> **Status：Design draft (Claude, 2026-05-05). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 2 / 4 / 6 complete + Governance Phase G-3 authorization.**
>
> 屬 [GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md) §2 維度 8。

---

## 0. 設計參照

| 系統 | 借鑑 | 不借鑑 |
|---|---|---|
| **MakerDAO Emergency Shutdown** | last-resort 觸發條件、保護用戶資產、postmortem 必要性 | global settlement（我們不結算用戶資產） |
| **Lido Dual Governance** | veto signaling、dynamic timelock、staker objection window | Rage Quit 的代幣燒毀 |
| **Cosmos governance** | veto threshold 的概念用在 emergency veto | on-chain auto-burn deposit |

PointsChain 不是公鏈，沒有 collateral / stETH 那種 user-redemption 義務。我們的 emergency 主要是**保護 audit chain 完整性 + 防 mint / burn 異常 + 給用戶 export 視窗**。

---

## 1. 為什麼需要 emergency governance

`incident_lockdown` 已存在於 Server Mode v2，但只是**機制**——按下開關 → server 進 read-mostly。沒有寫死「**誰**能按、**什麼條件**該按、**如何**解除、解除後**要交什麼報告**」。

這份 spec 把 emergency 升級成完整治理流程：

```
trigger (auto / manual) → 7 角色批准 → 進 emergency mode →
  user-facing exit window (N days) → 應急動作 → 解除 (multisig) →
  postmortem (7 days) → state diff verify → governance proposal 補 ratify
```

---

## 2. 緊急動作 taxonomy

| Action | scope | 自動觸發條件 | 手動觸發角色 |
|---|---|---|---|
| `incident_lockdown_enter` | 整站 read-mostly | audit chain 雜湊鏈異常 / supply invariant fail / multisig key 連續失效 / production 偵測到大量未授權 mint / burn | Emergency Committee 3-of-5 |
| `emergency_pause` | trading / transfer / mint / burn / reward 任一 | exchange_fund.health ≤ 0.3 持續 24h（trading） / fee_rate change rollback | Emergency Committee 3-of-5 / Market Risk 2-of-3（trading scope only） |
| `emergency_mint` | mint to PNT1EXCHFUND / PNT1RESERVE | exchange_fund / reserve depletion 觸發（[POINTS_MONETARY_POLICY §4.3](POINTS_MONETARY_POLICY.md#43-emergency-mint)） | Emergency Committee 4-of-5 |
| `emergency_burn` | burn from official pool | 偵測到惡意 mint 必須立即 reverse 同等量到 burn | Emergency Committee 4-of-5 + root |
| `emergency_freeze_address` | freeze 單一 wallet | 偵測到密鑰外洩 / 強烈疑似攻擊 | Security Council 2-of-3 |
| `emergency_unfreeze_address` | unfreeze | freeze 後查證無誤 | Security Council 2-of-3 |
| `governance_pause` | 暫停所有 governance 提案執行 | governance 系統本身偵測異常（vote stuffing / proposal spam wave） | Emergency Committee 3-of-5 |

每個 action 都對應一個 `emergency_event` row，永久上鏈。

---

## 3. Emergency event schema

```sql
CREATE TABLE emergency_events (
    id                   TEXT PRIMARY KEY,                  -- emerg_<yyyymmdd>_<rand>
    action               TEXT NOT NULL,                      -- 對應 §2 action
    scope                TEXT NOT NULL,                      -- trading|transfer|mint|burn|address|all
    trigger_kind         TEXT NOT NULL,                      -- auto|manual|hybrid
    trigger_metric       TEXT,
    trigger_value        TEXT,
    observation_window_seconds INTEGER,
    initiator_user_id    INTEGER NOT NULL,
    initiator_role       TEXT NOT NULL,
    approval_signatures  TEXT NOT NULL,                      -- JSON: [{user_id, role, signed_at}, ...]
    approval_threshold   TEXT NOT NULL,                      -- e.g. '3-of-5'

    justification_hash   TEXT NOT NULL,                      -- sha256(off-chain incident report draft)
    expected_state_diff_hash TEXT,
    actual_state_diff_hash TEXT,

    user_exit_window_seconds INTEGER NOT NULL DEFAULT 0,     -- 0 if scope is too narrow to need it
    user_exit_window_started_at TEXT,
    user_exit_window_ends_at TEXT,
    user_exit_actions    TEXT NOT NULL DEFAULT '[]',         -- JSON: ['cancel_orders', 'export_ledger_proof', ...]

    entered_at           TEXT NOT NULL,
    exited_at            TEXT,
    exit_proposal_id     TEXT,                                -- 解除走的 proposal id
    postmortem_url       TEXT,
    postmortem_signed_off_by TEXT,                            -- JSON: signer roles

    ratification_proposal_id TEXT,                            -- 事後補 ratify 的 L4 proposal
    ratification_status  TEXT NOT NULL DEFAULT 'pending',    -- pending|ratified|rejected|expired

    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX idx_emergency_events_action ON emergency_events(action, entered_at);
CREATE INDEX idx_emergency_events_scope ON emergency_events(scope, exited_at);

CREATE TABLE emergency_event_logs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    emergency_event_id   TEXT NOT NULL,
    log_kind             TEXT NOT NULL,                      -- enter|exit|veto_signal|postmortem|ratify
    actor_user_id        INTEGER,
    actor_role           TEXT,
    detail_json          TEXT,
    chain_event_id       INTEGER,
    created_at           TEXT NOT NULL
);
```

---

## 4. Trigger paths

### 4.1 Auto trigger（system-driven）

| Metric | Threshold | Auto action |
|---|---|---|
| `audit_chain_verify_fail` | any | `incident_lockdown_enter` (immediate) |
| `supply_invariant_fail` | any | `incident_lockdown_enter` (immediate) |
| `exchange_fund.health < 0.3` | 24h sustained | `emergency_mint` draft（[POINTS_MONETARY_POLICY §4.3](POINTS_MONETARY_POLICY.md#43-emergency-mint)） |
| `unauthorized_mint_detected` | any | `incident_lockdown_enter` + `emergency_burn` proposal |
| `multisig_signer_key_failure_count` | ≥ 2 in 24h | Security Council notify + `emergency_pause` for that signer |
| `proposal_spam_wave` | > 100 proposals / hr | `governance_pause` |

Auto trigger 仍需 Emergency Committee 在 30 分鐘內**人工確認**才能持續：

```
auto trigger fires
  → emergency_event created with status='pending_confirmation'
  → broadcast to Emergency Committee
  → 30-min window:
      if 3-of-5 confirm → status='active'
      else → auto-revert (system reverses the lockdown)
  → all activity in this window is logged
```

### 4.2 Manual trigger

```
emergency_committee 3-of-5 簽 multisig
+ initiator role 必填
+ justification_hash 必填（postmortem draft 預備）
立即進入 emergency_event status='active'
```

---

## 5. User Exit Window（用戶制衡）

對標 Lido Dual Governance：重大治理變更前留時間給用戶 export / cancel。

PointsChain 不結算用戶資產，但仍應該保留：

```
trigger:
  - L4 proposal 進 timelock（含 hard cap raise / multisig signer 換 / governance framework 改）
  - 任何 emergency_event scope='all'（incident_lockdown_enter）

exit window:
  - L4 timelock = 14 days; window 從 timelock_eta 前 14 天開始
  - emergency = scope='all' 啟動後立即開 ≥ 7 天 window

可做的 user actions during window:
  - cancel pending trading orders
  - cancel pending reward claim
  - export ledger proof（自己錢包的 merkle proof）
  - export wallet keystore（self-custody opt-in）
  - 設定 representative / delegate（提前準備代議）

不可做：
  - withdraw points to external system（我們不是公鏈）
  - 新開高槓桿倉位（trading 已在 read-mostly）
```

---

## 6. Veto Signal（用戶反對信號）

對標 Lido：當足夠用戶用 governance lock 反對某 proposal，會延長 timelock。

```
governance_objection_signal:
  user lock points into PNT1ESCROW (special objection slot)
  signal_weight = locked_amount × time_locked_factor (Curve-style decay)

threshold:
  - 10% of eligible_total_weight 反對 → timelock 延長 5 days
  - 20% → 延長 14 days
  - 33% → 觸發 emergency_committee review（4-of-5 才能繼續）
  - 50% → 自動進 vetoed status

unlock:
  - 提案 expire / withdraw 後 14 days，objection points 自動解鎖回 user wallet
  - 點數不被燒；只是「鎖時間 = 表態時間」
```

注意：

- objection signal **只能用在 L3+ proposal**（L0 / L1 不需這層保護）
- 一個 user 對一個 proposal 只能 signal 一次
- signal 上鏈但 voter id 脫敏

---

## 7. 解除 emergency

```
exit flow:
  1. emergency event status='active'
  2. trigger condition 已恢復（metric 回正常 / threat 已隔離）
  3. emergency_committee 3-of-5 + root 個別 sign-off
  4. 寫 emergency_events.exited_at + exit_proposal_id
  5. 服務逐步 unpause（依 scope 分階段）
  6. 進入 postmortem 期（7 days）

unpause 不可一次全開：
  - phase 1: read access restored (1h)
  - phase 2: existing positions / orders accessible (6h)
  - phase 3: new orders / mint / burn proposals (after postmortem signed)
```

---

## 8. Postmortem（事後報告）

`exited_at` 後 **7 天內必須交 postmortem**：

```
required sections:
  - timeline (UTC, minute-resolution)
  - root cause analysis
  - what was at risk
  - what was actually affected (state diff)
  - remediation taken
  - prevention plan
  - parameter changes proposed (if any)
  - sign-off (root + emergency committee + at least 1 user representative)

publish:
  - explorer /emergency-events/<id>/postmortem
  - hash 上鏈
  - linked to emergency_events.postmortem_url
```

不交 postmortem ≥ 7 天 → emergency committee 自動進 30 天 governance cooldown（不能再批准 emergency action）。

---

## 9. Ratification（事後補 proposal）

emergency action 是 last-resort，但**不能取代正式治理**。事後必須：

```
within 30 days of exited_at:
  - 提交 L4 ratification proposal
  - payload: 把 emergency 期間做的所有 mint / burn / param change 列表
  - 通過 → emergency_events.ratification_status='ratified'
  - 否決 → committee 自動扣 30 天 governance weight + 補 burn / refund 補正

ratification_status='rejected':
  - 等同社群否認該 emergency action 是合理的
  - 該 emergency committee 必須改選（[TREASURY_BUDGET_POLICY §8](TREASURY_BUDGET_POLICY.md#8-committee-規範)）
  - 影響的用戶可走 [DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md) 申訴
```

---

## 10. Severity-based unpause path

| Severity | unpause | 後續動作 |
|---|---|---|
| **L1 false positive**（auto trigger 確認是誤報） | 30 min 內 unpause | postmortem 記為 false positive；改 trigger 閾值 |
| **L2 minor**（單一 wallet freeze） | unpause when investigation closed | postmortem 7 days |
| **L3 moderate**（exchange_fund 補注） | unpause after mint executed + 24h observation | postmortem 7 days + L3 ratify |
| **L4 major**（incident_lockdown 全站） | unpause 走 §7 三階段；最快 24h，最長 14d | postmortem 7 days + L4 ratify |
| **L5 critical**（audit chain 異常 / 駭客） | unpause 必須 root + 4-of-5 + 完整 forensic report | postmortem 30 days + L4 ratify + 可能換 governance signer |

---

## 11. 不可繞過的鐵律

```
1. emergency_event 不可繞 multisig（即使 single root 想按）
2. emergency_event 必須產生 ledger event；不上鏈的 lockdown 不算合法
3. user_exit_window 一旦設定 > 0，不可中途縮短（只能延長）
4. emergency_burn / emergency_mint 仍受 hard cap 約束（cap 不變）
5. postmortem 不交 = 該 committee 自動凍結
6. ratification_status='rejected' 的 emergency 動作要 reverse / refund，不可保留結果
7. emergency_event 上鏈後 SQL trigger 阻擋直接 UPDATE / DELETE（append-only）
```

---

## 12. Public-facing pages

```
/emergency-events           列表（可篩 active / closed / pending_postmortem）
/emergency-events/<id>      事件詳情 + timeline + 影響範圍 + ratification 狀態
/emergency-events/<id>/postmortem    完整 postmortem
/governance/objection-signals       目前在 signal 中的 proposal + 累計 weight（脫敏）
```

每月公開 emergency statistics：

```
本月 emergency 次數                         X
auto / manual 比例                          X / Y
平均 unpause 時間                          X 分鐘
未交 postmortem                            X
ratification rejected                       X
```

---

## 13. Implementation Phase

```
Governance Phase G-3:
  - emergency_events / emergency_event_logs schema
  - auto trigger metrics integration (audit chain / supply invariant / exchange_fund health)
  - emergency_committee multisig API
  - user_exit_window 公開頁 + cancel pending order helper
  - veto signal API + objection slot escrow
  - postmortem upload + verification
  - ratification proposal type
  - explorer /emergency-events
```

依賴：

- PointsChain v2 Phase 6 explorer（公開頁要它）
- Server Mode v2 incident_lockdown 機制（已落地）
- GOVERNANCE_PROPOSAL_LIFECYCLE 完整實作（ratification 走 L4）
- TREASURY_BUDGET_POLICY committee 結構（emergency_committee 是其中之一）

---

## 14. 跨參考

- 主框架：[GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md)
- 提案 lifecycle：[GOVERNANCE_PROPOSAL_LIFECYCLE.md](GOVERNANCE_PROPOSAL_LIFECYCLE.md)
- 預算：[TREASURY_BUDGET_POLICY.md](TREASURY_BUDGET_POLICY.md)
- monetary：[POINTS_MONETARY_POLICY.md](POINTS_MONETARY_POLICY.md)
- 司法：[DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md)
- multisig：[MULTISIG_WALLETS.md](MULTISIG_WALLETS.md)
- 既有 incident_lockdown：`docs/server_mode/SERVER_MODE_V2_PROFILE_MATRIX.md`
- 設計參照：MakerDAO Emergency Shutdown / Lido Dual Governance / Cosmos veto
