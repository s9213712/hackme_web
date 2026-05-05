# Governance Voting Power v1

> **Status：Design draft (Claude, 2026-05-06). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 2 / 4 / 6 complete + Governance Phase G-5 authorization (Phase 2 of governance, after MVP).**
>
> 屬 [GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md) §2 維度 2 / 7 / 10 細節 spec。

---

## 0. 設計參照

| 系統 | 借鑑 | 不借鑑 |
|---|---|---|
| **Uniswap / Compound（token-weighted）** | delegate / delegated voting power 概念 | 持幣即治理權（容易被買走） |
| **Curve veCRV（time-weighted）** | 鎖時間越久權重越高 + 隨剩餘時間衰減 | 可交易的 veToken |
| **Optimism Bicameral** | Token House + Citizens' House 雙院 / 1-member-1-vote / Citizen 反 Sybil | Layer-2 specifics |
| **Cosmos governance** | 一人一票（per-validator）的 quorum / veto threshold | 質押為治理基礎 |
| **OpenZeppelin Governor Votes module** | voting_power_provider 模組化 | 完全 on-chain 計算（成本太高） |

**核心原則**：

```
治理權 ≠ 可交易積分
治理權 = trust + age + contribution + (optional) reputation lock
治理權可委託；不可被私下買賣
```

---

## 1. 為什麼不直接用 token-weighted

PointsChain 的 points 同時是：

- 站內貨幣（買服務 / 交易）
- reward / mining 獎勵媒介
- 違規罰金扣除目標

如果 voting weight = points balance：

```
1. 大戶買票（買 points → 影響治理）
2. 借票（短時間 points 互轉刷投票權）
3. 反 contributor（contributor 把 points 用掉就治理權變小）
4. 反 user（一般用戶手上點數少 → 永遠沒治理權）
```

且 PointsChain 的 points 沒有 lock-up 機制（可以隨時花 / 轉），不像 stETH / veCRV 有天然 lock。

→ 採用**多維加權 + 時間鎖選項**模型。

---

## 2. Voting Eligibility（基本資格）

要有任何 vote weight 必須先過 eligibility：

```
eligible_voter = (
  account_age >= 30 days
  AND trust_score >= 50
  AND email_verified == true
  AND not_in_active_dispute
  AND not_recently_violation_clamped (last 90 days no severe violation)
  AND not_in_governance_cooldown (e.g. spam proposal cooldown)
)
```

不過 eligibility 的 user：

- 仍可在 explorer 看 proposal
- 可開 dispute 申訴 governance 結果
- 不可投票、不可提案、不可 delegate
- 可發 objection signal（[EMERGENCY_GOVERNANCE §6](EMERGENCY_GOVERNANCE.md#6-veto-signal用戶反對信號)）— 但只能用低權重模式

---

## 3. Voting Weight 公式

```
base_weight     = trust_score / 100                          # 0..1
contribution    = clamp(log10(reward_lifetime + 1) / 6, 0, 2)
                                                              # log-scaled，避免囤積優勢；6 個數量級壓到 0..2
account_age_w   = clamp(account_age_days / 365, 0, 1.5)
identity_score  = optional 0..0.5 (proof-of-personhood / verified contributor)
optional_lock_w = locked_amount × time_decay_factor / max_lock_amount
                                                              # 自願鎖（不可轉、不可贖；time_decay 用 Curve-style）

vote_weight = base_weight × (1 + contribution + account_age_w + identity_score + optional_lock_w)
```

`time_decay_factor`（borrowed from veCRV）：

```
time_decay_factor = remaining_lock_seconds / max_lock_seconds (4 years)
```

鎖剛開始 → factor 接近 1；鎖快到期 → 接近 0。鎖滿 4 年的 user 比鎖 6 個月的權重大。

**最大可達**：trust 100 + contribution 2 + age 1.5 + identity 0.5 + lock 1 = `1.0 × 6.0 = 6.0`

**最小**：trust 50 + 0 + 0 + 0 + 0 = `0.5 × 1 = 0.5`（剛過 eligibility）

---

## 4. Tier-specific 最小 weight

對應 [GOVERNANCE_FRAMEWORK.md §4](GOVERNANCE_FRAMEWORK.md#4-治理動作分類risk-tiers) 的 tier matrix：

| Tier | 提案 weight ≥ | 投票 weight ≥ | 補充條件 |
|---|---|---|---|
| L0 | 0.5 | 0.1 | + deposit_low |
| L1 | 1.5 | 0.3 | + 3 contributors（co-sponsor） |
| L2 | committee only | 0.5 | committee + multisig |
| L3 | committee + multisig | 1.0 | committee 提案、用戶投票 |
| L4 | root + multisig | 2.0 | + 7-day public notice |
| L5 emergency | emergency committee | committee internal | postmortem 必交 |

---

## 5. Bicameral Houses（Optimism-style，Phase 2 才啟用）

| House | 組成 | 投票模式 | Voting power 來源 | Veto |
|---|---|---|---|---|
| **Council House**（管理層 / multisig 角色） | 5 multisig signer + 7 committee 共 12 席 | 1 person 1 vote（per seat） | 角色席位 | 對 L4 結構性提案有 veto |
| **Contributor House**（一般用戶 / 開發者 / contributor） | 過 eligibility 的全體 | weight-based（§3 公式） | base / contribution / age / lock | 對 L3 經濟提案有 objection signal（§6）|

**雙院通過規則**：

| Tier | 通過條件 |
|---|---|
| L0 | Contributor House simple majority |
| L1 | Contributor House 60% + 30% quorum |
| L2 | Council House majority |
| L3 | **兩院都過**：Contributor 60% + 30% quorum AND Council majority |
| L4 | **兩院都過 + Council House 4-of-5 multisig** |
| L5 | Emergency Committee 3-of-5 即時，事後 ratify L4 |

`L3 / L4` 任一院否決 → proposal 進 `vetoed` status（[GOVERNANCE_PROPOSAL_LIFECYCLE.md §1](GOVERNANCE_PROPOSAL_LIFECYCLE.md#1-11-個-lifecycle-狀態)）。

**v1 MVP 不啟用雙院**，只用 Council House（multisig）+ user objection signal；雙院在 Governance Phase G-5 才開啟。

---

## 6. Delegation（委託）

對標 Uniswap / Compound delegated voting power。

```sql
CREATE TABLE governance_delegations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    delegator_user_id    INTEGER NOT NULL,
    delegate_user_id     INTEGER NOT NULL,
    domain               TEXT NOT NULL DEFAULT 'all',        -- all|economy|security|content|market
    weight_committed     REAL NOT NULL,                       -- 委託出去的 weight 比例 0..1
    started_at           TEXT NOT NULL,
    expires_at           TEXT NOT NULL,                       -- 強制有 expiry，預防永久委託
    revoked_at           TEXT,
    revoke_reason        TEXT,
    UNIQUE(delegator_user_id, delegate_user_id, domain, started_at)
);
CREATE INDEX idx_gov_delegations_delegate ON governance_delegations(delegate_user_id, expires_at);

CREATE TABLE governance_delegate_profiles (
    user_id              INTEGER PRIMARY KEY,
    statement_url        TEXT,                                -- delegate 公開立場 / 政綱
    statement_hash       TEXT,
    activity_score       REAL NOT NULL DEFAULT 0,             -- 委託收到後的投票活躍度
    last_voted_at        TEXT,
    conflict_disclosure  TEXT,                                -- 利益衝突聲明
    domains              TEXT NOT NULL DEFAULT '[]',          -- JSON: ['economy', 'security', ...]
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
```

### 6.1 Delegation 鐵律

```
1. 委託只能用 vote_weight，不可委託 points balance
2. delegator 隨時可 revoke（24h cooldown 後生效）
3. expires_at 強制存在；最多 365 天，到期自動失效
4. 一個 domain 只能委託給一個人（防多重委託混亂）
5. delegate 不可委託出去（防 cycle）
6. delegate 收到的 weight 上限：not exceed 5% of total eligible weight
   （防超大 delegate 累積 → 重新中心化）
7. delegate 每 30 天必須投至少 1 票，否則 activity_score 下降；< 0.3 自動暫停接受新委託
```

### 6.2 委託 domain 分類

```
economy        # mint / burn / fee / emission
security       # incident lockdown / multisig signer / emergency
content        # 內容治理 / community 預算
market         # margin / oracle / exchange fund
all            # 一次全委託（不建議，但允許）
```

User 可以**在不同 domain 委託給不同人**（security 給安全代議、economy 給經濟代議）。

### 6.3 不可代議的 actions

委託只代理「投票」，**不代理**：

```
- 提案（proposer 必須是 delegator 本人）
- objection signal（用戶本人才能表態）
- dispute 申訴
- self-custody 操作
- treasury budget approval（多簽委員必須親簽）
```

---

## 7. Optional Lock（自願鎖）

Curve-style 但不發 ve-token；只是 boost vote weight。

```sql
CREATE TABLE governance_locks (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL,
    locked_amount        INTEGER NOT NULL CHECK (locked_amount > 0),
    locked_at            TEXT NOT NULL,
    unlock_at            TEXT NOT NULL,
    base_weight_boost    REAL NOT NULL,                       -- 鎖時的 boost
    early_release_proposal_id TEXT,                            -- 提前 unlock 必走 proposal
    released_at          TEXT,
    released_amount      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, locked_at)
);
```

```
governance.parameters:
  governance.lock.max_amount_per_user_pct: 5%   # 不能鎖超過自己 balance 5%
  governance.lock.max_lock_seconds:        4 * 365 * 86400 (4 years)
  governance.lock.min_lock_seconds:        14 * 86400 (14 days)
```

### 7.1 鎖 / 解鎖

```
lock:
  user POST /api/governance/locks
  payload: { amount, lock_seconds }
  amount transferred from user wallet → governance escrow address
  ledger event: governance_lock_created
  weight_boost = (amount / max_amount_per_user) × (lock_seconds / max_lock_seconds)

natural unlock:
  unlock_at 到期 → user 主動 claim → 退回 user wallet
  ledger event: governance_lock_released

early release:
  必須走 L1 proposal（justification 必填）
  通過後 → 釋放但 boost 從 active 移除
  proposer 自己投自己提案不算（Sybil 防護）
  early release 罰：剩餘 boost time × 1% locked_amount → 進 dispute pool
```

---

## 8. 反 Sybil（governance eligibility scoring）

對標 Optimism Citizens' House 的 proof-of-personhood + 行為分析：

```
governance_sybil_score:
  account_age_days × 0.1
  + email_verified ? 5 : 0
  + identity_verified (optional, manual) ? 10 : 0
  + reward_lifetime_log × 2
  + positive_reputation × 1
  - same_ip_cluster_size × 2
  - same_device_fingerprint_size × 3
  - rapid_account_creation_pattern × 5
  - violation_count × 3
```

`sybil_score < 0` → 自動標 sybil_flagged，governance 行為走 read-only。

特殊情況：

```
detected sybil cluster:
  → 同 cluster 帳號 voting weight 自動歸零該 proposal
  → 該 proposal 重新計算 quorum（剔除 cluster 後）
  → 寫 governance_sybil_event 上鏈
  → cluster 內帳號被通知，可走 dispute 申訴
```

---

## 9. Snapshot 機制

對標 Uniswap / Compound：voting weight 在 proposal `vote_start_at` 那一刻 snapshot，後續變動不影響該 proposal 投票權。

```
proposal vote_start_at = T:
  snapshot governance_voting_power_at_T 對所有 eligible voter
  存入 governance_proposal_snapshots
  vote 該 proposal 時讀 snapshot 而非 live

snapshot scope:
  - eligibility flag
  - vote_weight at T
  - delegations active at T
  - locks active at T
  - sybil flags at T
```

`vote_start_at` 之後新增 / 註銷的權重不影響該 proposal。**這防止 proposal 公布後跑去買 trust / age**（雖然 trust 不能直接買，但仍是嚴格保險）。

---

## 10. Phase 對應

```
Governance MVP (G-0..G-3):
  - eligibility check（§2）
  - simple weight公式（§3 但無 lock 部分）
  - Council House only（multisig as Council）
  - 沒 delegation, 沒 lock, 沒 Bicameral
  - sybil basic（同 IP / same device cluster）

Governance Phase G-5（Phase 2，MVP 後）:
  - 完整 §3 公式（含 lock）
  - delegation §6
  - Bicameral §5
  - 完整 §8 sybil scoring
  - snapshot mechanism §9
```

---

## 11. 跨參考

- 主框架：[GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md)
- proposal lifecycle：[GOVERNANCE_PROPOSAL_LIFECYCLE.md](GOVERNANCE_PROPOSAL_LIFECYCLE.md)
- objection signal：[EMERGENCY_GOVERNANCE.md §6](EMERGENCY_GOVERNANCE.md)
- 申訴：[DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md)
- 設計參照：Uniswap / Compound delegate model / Curve veCRV / Optimism Bicameral / OpenZeppelin Governor Votes module
