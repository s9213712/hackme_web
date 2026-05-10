# Treasury Budget Policy v1

> **Status：Design draft (Claude, 2026-05-05). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 1A / 2 / 4 / 6 complete + Governance Phase G-2 authorization.**
>
> Treasury / budget 規則保留於本檔；遠期 governance framework 已移出本資料夾。

---

## 1. 為什麼需要預算制度

Treasury 不能變成「root 隨手撥款」的池子。對標 Lido committee + Easy Track：日常 routine 在預算內可由授權地址快速處理，但所有 spending 都受治理約束 + explorer 公開。

Treasury 也不能被拿來掩蓋 exchange fund 壞帳或 reward pool 超支。官方池必須分帳：

- `PNT1TREASURY`：長期儲備與預算支出。
- `PNT1RESERVE`：危機儲備與跨池補位，仍需 multisig。
- `PNT1REWARD`：貢獻獎勵與 mining payout，只能按 budget / solvency 支出。
- `PNT1EXCHFUND`：交易所基金，獨立承擔交易 payout / market making risk；不得和 treasury 混帳。

本 policy 把 treasury 切成多個 budget bucket，每個 bucket 有：

```
- quarterly cap
- 授權使用 committee
- 容許支出 type
- spending limit per transaction
- 每筆 spending 必須帶 proposal_id 或 budget_authorization_id
- 月底 reconcile + 公開 report
```

---

## 2. 預算 buckets（v1）

| Budget | 來源池 | 季度上限 | 授權 committee | 用途 |
|---|---|---|---|---|
| **Security Council** | PNT1TREASURY | 2% of treasury | Security Council 2-of-3 | 滲透測試、安全工具、bug bounty over-cap |
| **Bug Bounty** | PNT1REWARD | 1% of reward pool | Bug Bounty Reviewers + multisig 2-of-3 | 經審核的 bug bounty payout |
| **Reward Mining** | PNT1REWARD | 自動規則（formula 控制） | Reward Committee | QA mining 公式自動 payout |
| **Content Mining** | PNT1REWARD | 1.5% of reward pool | Content Council 2-of-3 | 內容創作 / community contribution |
| **Market Reserve** | PNT1RESERVE / PNT1EXCHFUND | 視 health | Market Risk Committee 2-of-3 | 市場流動性危機補注 |
| **Infra / AI Compute** | PNT1TREASURY | 1.5% of treasury | Treasury Committee 2-of-3 | 基礎設施、外部服務、AI 計算費 |
| **Grants** | PNT1TREASURY | 1% of treasury | Treasury Committee 2-of-3 | 第三方開發 / 整合 / research |
| **Emergency Reserve** | PNT1TREASURY | 0.5% of treasury 永遠保留 | Emergency Committee 3-of-5 | 緊急事件處理 |

合計每季最多動用：**8% of treasury + 2.5% of reward pool**（自動 mining 不計）。任何超過 → 必須 L3 proposal 補增 budget。

---

## 3. Budget schema

```sql
CREATE TABLE governance_budgets (
    id                   TEXT PRIMARY KEY,                  -- budget_<name>_<period>
    name                 TEXT NOT NULL,                      -- security_council|bug_bounty|...
    period               TEXT NOT NULL,                      -- 2026Q1, 2026Q2, ...
    source_address       TEXT NOT NULL,                      -- 從哪個官方地址撥
    cap_amount           INTEGER NOT NULL,
    spent_amount         INTEGER NOT NULL DEFAULT 0,
    allocated_amount     INTEGER NOT NULL DEFAULT 0,         -- pending（已批准但未執行）
    committee_role       TEXT NOT NULL,
    authorization_proposal_id TEXT NOT NULL,                  -- 開預算的提案
    status               TEXT NOT NULL DEFAULT 'active',     -- active|frozen|closed|over_budget
    closed_at            TEXT,
    closing_proposal_id  TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX idx_gov_budgets_period ON governance_budgets(period, name);

CREATE TABLE governance_budget_spends (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_id            TEXT NOT NULL,
    proposal_id          TEXT,                                -- 若是走完整 proposal
    fast_track_authorization_id TEXT,                         -- 若走 fast track
    from_address         TEXT NOT NULL,
    to_address           TEXT NOT NULL,
    amount               INTEGER NOT NULL CHECK (amount > 0),
    reason               TEXT NOT NULL,
    evidence_hash        TEXT,                                -- 發票 / 合約 / contributor 提交 hash
    ledger_event_id      INTEGER NOT NULL,
    chain_block_id       INTEGER,
    actor_user_id        INTEGER NOT NULL,
    actor_role           TEXT NOT NULL,
    spent_at             TEXT NOT NULL
);
CREATE INDEX idx_gov_budget_spends_budget ON governance_budget_spends(budget_id, spent_at);

CREATE TABLE governance_budget_reconciliation (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_id            TEXT NOT NULL,
    reconcile_period     TEXT NOT NULL,                      -- 2026Q1-month-3
    starting_balance     INTEGER NOT NULL,
    spent_total          INTEGER NOT NULL,
    refunded_total       INTEGER NOT NULL DEFAULT 0,
    over_budget_amount   INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL,                      -- pending|signed_off|disputed
    signed_off_by        TEXT,
    report_url           TEXT,
    reconciled_at        TEXT
);
```

---

## 4. Budget lifecycle

### 4.1 開預算（每季 / 年初）

走 L3 proposal：

```yaml
proposal_type: treasury_spend (variant: open_budget)
payload:
  budget_name: security_council
  period: 2026Q1
  cap_amount: 1_500_000
  source_address: PNT1TREASURY
  committee_role: security_council_committee
  spending_rules:
    max_per_transaction: 100_000
    fast_track_under: 50_000
    full_proposal_over: 500_000
governance:
  tier: L3
  voting: 7d
  timelock: 7d
```

通過後 governance_budgets 開 row，`status='active'`。

### 4.2 季中支出（兩條路徑）

**Fast track**（金額 ≤ `fast_track_under`）：

```
committee 簽 multisig 即可（不走完整 proposal）
寫入 governance_budget_spends + ledger event
explorer 即時公開
```

**Full proposal**（金額 ≥ `full_proposal_over` 或敏感 spending）：

```
走 L2 / L3 proposal（依金額）
proposal_type: treasury_spend
payload:
  budget_id: budget_security_council_2026Q1
  to_address: <recipient>
  amount: <amt>
  reason: <text>
  evidence_hash: <hash>
通過 + 執行後 spent_amount 增加
```

中段（`fast_track_under` < amount < `full_proposal_over`）走簡化 proposal（L1）。

### 4.3 季底 reconciliation

每季最後一天系統自動產 reconciliation report：

```
starting_balance         開季初 cap
spent_total              所有已執行 spending 加總
allocated_amount_outstanding  已批准未執行
refunded_total           退回（unused，回 source_address）
over_budget_amount       超額（觸發 alert + 必須 L3 補預算）
```

由 committee multisig 2-of-3 sign-off；sign-off 後寫入 chain block 並公開。

未 sign-off 預設 30 天 → 自動進 `budget_dispute` 狀態，由 root / finance_admin / independent reviewer 走人工處理；不得自動放行下季同名 budget。

### 4.4 Budget 關閉

季底自動：

```
未動用部分 → 退回 source_address（自動 ledger event：budget_returned_unused）
status='closed'
closing_proposal_id=auto_close_<budget_id>
```

下季同名 budget 重新開 → 走新 proposal。

---

## 5. Spending 鐵律

```
- 每筆 spending 必須有 proposal_id 或 fast_track_authorization_id
- to_address 必須是合法 user wallet 或 official address
- amount > 0；超過 budget cap 直接拒
- spent_amount + allocated_amount + amount > cap → 拒
- 同一 proposal_id 不可重複 spending（idempotency）
- ledger event 必填 budget_id
- spending 的 ledger event 在 explorer 永遠可追溯到 budget + proposal
- committee 不可 spend 給自己（self-deal 鐵律）
```

DB 層 trigger 強制最後兩條：

```sql
CREATE TRIGGER forbid_budget_spend_self_deal
BEFORE INSERT ON governance_budget_spends
WHEN NEW.actor_user_id IN (
    SELECT user_id FROM governance_committee_members
    WHERE committee_role = (SELECT committee_role FROM governance_budgets WHERE id = NEW.budget_id)
) AND NEW.to_address IN (
    SELECT primary_address FROM points_wallet_addresses
    WHERE user_id = NEW.actor_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'budget self-deal forbidden');
END;
```

---

## 6. 緊急超支（emergency over-budget spending）

唯一允許超支的場景：incident response 進行中（incident_lockdown active）。

```
governance:
  tier: L5
  emergency_committee 3-of-5 即時批准
  立即執行 + ledger
required_after:
  - 7 天內 postmortem + 補申請 L3 budget top-up（合理化）
  - 若 top-up proposal 否決 → spending 不退錢，但 emergency committee 個人 governance weight 扣 30 天
```

---

## 7. Treasury Health Indicators（公開）

每月 explorer 自動產：

```
treasury_balance               當前餘額
treasury_runway_months         按目前 quarterly burn 估還能撐幾個月
budget_utilization_pct         所有 budget 平均使用率
over_budget_count              本季超支次數
emergency_spending_total       本季 emergency 累計
oldest_unsigned_reconcile      最舊未 sign-off reconciliation
source_sink_ratio              earned / spent / burned / locked
reward_pool_runway_weeks       reward pool 依 weekly_budget 可支撐週數
exchange_fund_health           交易所基金健康度（完整 denominator）
```

`treasury_runway_months < 24` → 自動建議 L3 提案（增 mint to treasury / 砍 budget）。

任一情況不得用 treasury 直接靜默補洞：

| 情況 | 正確處置 |
|---|---|
| reward_pool < pending payouts | 暫停 payout execute，產 `mining_pool_refill` proposal |
| exchange_fund_health < 0.75 | trading reduce-only，產 reserve top-up proposal |
| exchange bad debt 產生 | 寫 bad debt ledger + incident report，不得用 treasury adjustment 抹平 |
| source/sink 連續 2 週失衡 | freeze 新 campaign budget，產 inflation-risk review |

root dashboard 必須顯示「可支出預算」與「不可動用儲備」分開的數字；不能只顯示總餘額。

---

## 8. Committee 規範

每個 committee：

```sql
CREATE TABLE governance_committees (
    role                 TEXT PRIMARY KEY,
    description          TEXT,
    multisig_threshold   TEXT NOT NULL,                      -- e.g. '2-of-3'
    member_count_min     INTEGER NOT NULL,
    member_count_max     INTEGER NOT NULL,
    annual_budget_cap_pct REAL,                              -- 該 committee 一年動用上限
    rotation_period_days INTEGER NOT NULL DEFAULT 365,
    activated_at         TEXT,
    activation_proposal_id TEXT
);

CREATE TABLE governance_committee_members (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    committee_role       TEXT NOT NULL,
    user_id              INTEGER NOT NULL,
    seat_number          INTEGER NOT NULL,
    appointed_at         TEXT NOT NULL,
    term_ends_at         TEXT NOT NULL,
    appointment_proposal_id TEXT NOT NULL,
    removed_at           TEXT,
    removal_reason       TEXT,
    removal_proposal_id  TEXT,
    UNIQUE(committee_role, seat_number, appointed_at)
);
```

委員規則：

- 同一 user 不可同時在 ≥ 2 個 committee（避免 cross-committee collusion）
- 任期 365 天，到期前 14 天必須通過 re-appointment proposal（L3）
- 一次最多換 1/3 委員（任期錯開，避免一次清空）
- 委員自願退出 → 14 天 notice → committee 自動 down 一個席位 → 14 天內補位

---

## 9. 與其他 governance 文件的整合

| 場景 | 走哪個流程 |
|---|---|
| 開季度 budget | L3 proposal（lifecycle 完整） |
| budget 內 fast track 支出 | committee multisig 2-of-3（不走 proposal） |
| budget 內 full spending | L1 / L2 proposal（依金額） |
| 改 budget cap（中途加碼） | L3 proposal |
| 提名 / 罷免 committee 委員 | L3 proposal |
| 改 committee 結構 / multisig 門檻 | L4 proposal |
| 緊急超支 | L5（emergency committee） + 7 天內補 L3 |

---

## 10. Public Report Sample

每月公開：

```
== 2026Q1 Treasury Report (month 1) ==

Treasury balance:                15,234,000 / 50,000,000 (30.5%)
Runway estimate:                 28.4 months at current burn

Budgets active this quarter (8):
  security_council                  450,000 / 1,500,000  (30.0%)
  bug_bounty                        180,000 /   500,000  (36.0%)
  reward_mining                  (formula) /          —  (auto)
  content_mining                    220,000 /   750,000  (29.3%)
  market_reserve                          0 / on-demand  (—)
  infra_ai_compute                  600,000 / 1,500,000  (40.0%)
  grants                            150,000 /   500,000  (30.0%)
  emergency_reserve                       0 /   250,000  (—)

Spending breakdown:
  full_proposal:        12 events     780,000
  fast_track:           34 events     440,000
  emergency:            0  events           0

Over-budget incidents: 0
Pending reconciliations: 0
Pending L3 proposals:   2 (re-appoint security_council seat 3, mid-quarter top-up bug_bounty)
```

---

## 11. Implementation Phase

```
Governance Phase G-2:
  - governance_budgets / governance_budget_spends / reconciliation schema
  - committee schema + appointment proposal type
  - fast track authorization API（multisig，不走 proposal）
  - monthly reconciliation job
  - public treasury page
```

依賴：

- PointsChain v2 Phase 4 multisig 完成
- proposal / timelock / simulation / execution flow 完成
- POINTS_MONETARY_POLICY 完成（為了精確 cap 計算）

---

## 12. 跨參考

- [POINTS_MONETARY_POLICY.md](POINTS_MONETARY_POLICY.md)
- [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md)
- [POINTSCHAIN_WHITEPAPER.md §3.5](POINTSCHAIN_WHITEPAPER.md#35-genesis-allocation初始分配)
