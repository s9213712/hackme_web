# Governance Proposal Lifecycle v1

> **Status：Design draft (Claude, 2026-05-05). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 2 / 4 / 6 complete + Governance Phase G-0 authorization.**
>
> 屬 [GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md) §2 維度 1 / 3 / 14 的細節 spec。

---

## 1. 11 個 lifecycle 狀態

```
draft
  └─→ discussion
        └─→ temperature_check
              └─→ formal_proposal
                    └─→ voting
                          ├─→ rejected
                          ├─→ vetoed
                          ├─→ expired
                          └─→ passed
                                └─→ queued_timelock
                                      ├─→ executable
                                      │     └─→ executed
                                      └─→ rolled_back
```

| 狀態 | 誰能轉移 | 必要條件 | 寫鏈 event |
|---|---|---|---|
| `draft` | proposer | 草稿，可隨時編輯 | — |
| `discussion` | proposer | discussion_url 必填，公示 ≥ 24h（L1+） | — |
| `temperature_check` | proposer | 收溫度（非綁定信號）≥ 7 天（L3+） | `proposal_temperature_check` |
| `formal_proposal` | proposer | deposit 鎖定、payload_hash 確認 | `proposal_created` |
| `voting` | system（reach vote_start_at） | quorum 與 threshold 公布 | `proposal_voting_started` |
| `rejected` | system | quorum 達標但 yes < threshold | `proposal_rejected` |
| `vetoed` | vetoer 角色 | veto threshold 達標 | `proposal_vetoed` |
| `expired` | system | quorum 不達標到 vote_end_at | `proposal_expired` |
| `passed` | system | quorum 達且 yes ≥ threshold 且 no veto | `proposal_voting_closed` |
| `queued_timelock` | system | passed → 進 timelock 計時 | `proposal_queued` |
| `executable` | system（reach timelock_eta） | timelock 結束、execute window 內 | — |
| `executed` | executor 角色 | payload simulation = actual diff | `proposal_executed` |
| `rolled_back` | emergency committee | execute 後發現 state diff 不符 | `emergency_action_taken` |

**關鍵不變式**：

- `draft / discussion` 編輯不上鏈；`formal_proposal` 起每個轉移都上鏈
- `payload_hash` 從 `formal_proposal` 起鎖定，**不可改**；要改要重新提案
- proposer 隨時可主動 `withdraw`（轉 `expired`），但 deposit 退還規則依下方 §5

---

## 2. Proposal schema

```sql
CREATE TABLE governance_proposals (
    id                   TEXT PRIMARY KEY,                -- prop_<yyyymmdd>_<rand>
    proposal_type        TEXT NOT NULL,                    -- mint|burn|param_change|treasury_spend|emergency|content|dispute
    risk_tier            TEXT NOT NULL,                    -- L0..L5（見 FRAMEWORK §4）
    proposer_user_id     INTEGER NOT NULL,
    proposer_address     TEXT NOT NULL,
    title                TEXT NOT NULL,
    summary              TEXT NOT NULL,
    discussion_url       TEXT,                              -- forum / wiki / GitHub thread
    payload_json         TEXT NOT NULL,                     -- canonical JSON payload
    payload_hash         TEXT NOT NULL,                     -- sha256(canonical_json(payload))
    affected_modules     TEXT NOT NULL DEFAULT '[]',        -- JSON array: ['mint','transfer_fee',...]
    risk_warnings        TEXT NOT NULL DEFAULT '[]',        -- JSON array (auto-generated + manual)

    deposit_amount       INTEGER NOT NULL DEFAULT 0,
    deposit_address      TEXT,                              -- proposer wallet address
    deposit_status       TEXT NOT NULL DEFAULT 'pending',   -- pending|locked|refunded|burned|forfeited

    status               TEXT NOT NULL DEFAULT 'draft',     -- 對應 §1
    temperature_check_url TEXT,
    temperature_signal_count INTEGER DEFAULT 0,

    vote_start_at        TEXT,
    vote_end_at          TEXT,
    quorum_required_pct  REAL,
    pass_threshold_pct   REAL,
    veto_threshold_pct   REAL,

    yes_weight           REAL NOT NULL DEFAULT 0,
    no_weight            REAL NOT NULL DEFAULT 0,
    abstain_weight       REAL NOT NULL DEFAULT 0,
    veto_weight          REAL NOT NULL DEFAULT 0,
    total_voter_count    INTEGER NOT NULL DEFAULT 0,

    timelock_seconds     INTEGER NOT NULL DEFAULT 0,
    timelock_eta         TEXT,
    execute_window_seconds INTEGER NOT NULL DEFAULT 604800,  -- 預設 7 天 execute window
    executor_user_id     INTEGER,
    executed_at          TEXT,
    execution_ledger_event_id INTEGER,
    actual_state_diff_hash TEXT,
    expected_state_diff_hash TEXT,

    rejected_reason      TEXT,
    vetoed_by_role       TEXT,
    vetoed_reason        TEXT,
    rolled_back_proposal_id TEXT,
    rolled_back_reason   TEXT,

    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX idx_gov_proposals_status ON governance_proposals(status, vote_end_at);
CREATE INDEX idx_gov_proposals_proposer ON governance_proposals(proposer_user_id, created_at);
CREATE INDEX idx_gov_proposals_tier ON governance_proposals(risk_tier, status);

CREATE TABLE governance_proposal_votes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id          TEXT NOT NULL,
    voter_user_id        INTEGER NOT NULL,
    voter_address        TEXT NOT NULL,
    vote                 TEXT NOT NULL,                     -- yes|no|abstain|veto
    weight               REAL NOT NULL,
    weight_components_json TEXT NOT NULL,                    -- 計算依據（trust + age + lock + delegation）
    delegated_from_user_id INTEGER,                          -- 若是被委託投的
    comment_hash         TEXT,                                -- 評論可選；存 hash + off-chain 內文
    cast_at              TEXT NOT NULL,
    sybil_flagged        INTEGER NOT NULL DEFAULT 0,
    sybil_flag_reason    TEXT,
    UNIQUE(proposal_id, voter_user_id)                       -- 一人一票（含委託聚合）
);
CREATE INDEX idx_gov_votes_proposal ON governance_proposal_votes(proposal_id, cast_at);

CREATE TABLE governance_proposal_lifecycle_logs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id          TEXT NOT NULL,
    from_status          TEXT,
    to_status            TEXT NOT NULL,
    actor_user_id        INTEGER,
    actor_role           TEXT,
    detail_json          TEXT,
    chain_event_id       INTEGER,                            -- points_ledger event id（若上鏈）
    created_at           TEXT NOT NULL
);
CREATE INDEX idx_gov_lifecycle_proposal ON governance_proposal_lifecycle_logs(proposal_id, created_at);
```

---

## 3. Payload schema by proposal_type

每個 `proposal_type` 有獨立 payload schema，proposer 必須 conform：

```yaml
mint:
  destination: PNT1TREASURY|PNT1RESERVE|PNT1REWARD|PNT1EXCHFUND|PNT1AIRDROP
  amount: int (≤ tier-specific cap)
  reason: string
  observation_metric: optional         # for emergency mint
  observation_value: optional

burn:
  source: PNT1TREASURY|PNT1REWARD|PNT1FEEPOOL  # 不可從 user wallet
  amount: int
  reason: string

param_change:
  param_key: string                    # 必須在 governance_parameters
  to_value: string
  rollback_value: string                # 自動填當前值
  effective_at: timestamp (≥ timelock_eta)

treasury_spend:
  budget_id: string
  from_address: PNT1TREASURY|<budget pool>
  to_address: string
  amount: int
  recipient_invoice_hash: string        # off-chain invoice / contract hash

emergency:
  action: pause|unpause|incident_lockdown_enter|incident_lockdown_exit
  scope: trading|transfer|mint|burn|reward|all
  justification_hash: string            # postmortem 預備

content:
  action: remove|hide|restore|reannounce
  target_id: string
  reason: string

dispute:
  related_kind: bounty|reward|trade|transfer|admin_action
  related_id: string
  remedy: string                        # 申請賠償 / 翻案 / 警告
  evidence_hash: string

delegation_change:
  delegator: address
  delegate: address
  weight_committed: float
  expires_at: timestamp
```

`payload_hash = sha256(canonical_json(payload))`。一個 proposal 鎖定後 payload 不可改；要改 → 撤銷 + 新提一個。

---

## 4. Tier-specific 時程與門檻

對應 [GOVERNANCE_FRAMEWORK.md §4](GOVERNANCE_FRAMEWORK.md#4-治理動作分類risk-tiers)：

| Tier | 提案門檻 | discussion 公示 | temperature 期 | voting 期 | quorum | pass threshold | veto threshold | timelock | execute window |
|---|---|---|---|---|---|---|---|---|---|
| L0 | 1 user + deposit_low | 24 h | — | 48 h | 5% | 簡單多數 | — | 0 | 24 h |
| L1 | 3 contributors + deposit_med | 48 h | — | 5 d | 15% | 60% | 33% | 24–48 h | 48 h |
| L2 | committee + multisig 2-of-3 | 24 h（內部 review） | — | 3 d | committee quorum | committee approve | — | 48 h | 7 d |
| L3 | committee + multisig 3-of-5 | 7 d | 7 d | 7 d | 30% | 60% | 33% | 7 d | 14 d |
| L4 | root + multisig 4-of-5 | 14 d | 14 d | 14 d | 40% | 66% | 33% | 14 d | 30 d |
| L5 | emergency committee 3-of-5 | 0（事中公示） | — | 0 | committee | committee approve | — | 0 | 立即 |

`quorum` 計算方式：

```
quorum_pct = (yes_weight + no_weight + abstain_weight) / eligible_total_weight
```

`veto_threshold_pct` 達標 → 即使 yes 過 threshold 也不通過（防 51% 攻擊治理）。

---

## 5. Proposal Deposit（spam 防護）

採用 Cosmos-style minimum deposit + refund / forfeit / burn 規則：

```
governance.proposal_deposit.L0   = small (e.g. 50 points)
governance.proposal_deposit.L1   = medium (e.g. 500 points)
governance.proposal_deposit.L2   = committee waived（仍記錄 sponsor）
governance.proposal_deposit.L3   = high (e.g. 5,000 points)
governance.proposal_deposit.L4   = root waived but record sponsor weight
governance.proposal_deposit.L5   = emergency committee waived
```

**Refund / Forfeit 矩陣**：

| 結果 | deposit 處置 |
|---|---|
| `passed` + `executed` | 全額退回 proposer |
| `rejected`（quorum 達 / yes 不過） | 全額退回 |
| `expired`（quorum 不達） | 50% 退、50% 進 PNT1FEEPOOL（防為了名聲洗 proposal） |
| `vetoed` | 50% 進 dispute pool、50% 退 |
| **判定 spam / malicious**（committee 仲裁） | 100% forfeit；first version **進 dispute pool 不直接 burn**，由 committee 裁決去向 |
| proposer 自願 withdraw（formal_proposal 之前） | 全額退 |
| proposer 自願 withdraw（formal_proposal 之後 voting 之前） | 退 80% |
| proposer 自願 withdraw（voting 期間） | 退 50% |

⚠️ **第一版禁止自動扣用戶資產** — 所有 forfeit 都先暫扣到 dispute pool，由 committee multisig 2-of-3 才能最終處置。對應 [DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md)。

---

## 6. Spam / duplicate guards

```
proposal_spam_score = max(
  duplicate_payload_within_30days_count × 10,
  same_proposer_within_24h_count × 5,
  rejected_by_proposer_in_last_30days × 3,
  short_lived_account_modifier,
  same_ip_cluster_in_24h_count × 2
)
```

`spam_score >= 30` → reject formal_proposal、deposit 退 80%；連續 3 次 spam → 該 proposer 進入 90 天 governance cooldown（不能再提案，仍可投票）。

`payload_hash` UNIQUE 在 30 天滑窗內 — 同 hash 30 天內只能提一次，避免 duplicate spam。

---

## 7. Voting flow

```
voting_started
  ├─ 每筆 vote 寫 governance_proposal_votes
  ├─ 即時更新 yes_weight / no_weight / abstain_weight / veto_weight
  ├─ explorer 公布即時統計（不公布個人 voter id，露 weight + vote）
  └─ vote_end_at 到 → system 計算結果

cast_vote rules:
  - 一人一票（同一 proposal 不可重投，可在 voting 期內 update vote 一次）
  - delegate 投票 = 把 delegator 的 weight 聚合
  - sybil_flagged 票仍記錄但不計入 yes/no/abstain；veto 仍計入
  - 投票後 6h 內可改票一次（防誤點）；之後鎖定
  - voting 期最後 1h 不接受改票（防 last-minute manipulation）
```

`weight_components_json` 必須記錄完整來源讓事後可重算：

```json
{
  "base_weight": 0.65,
  "contribution_score": 1.2,
  "account_age_w": 0.8,
  "optional_lock_w": 0.5,
  "delegation_received": [
    {"from_user_id": 102, "weight": 0.4, "delegated_at": "..."}
  ],
  "final_weight": 1.85,
  "formula_version": "v1"
}
```

---

## 8. Simulation + state diff

對應 Uniswap Seatbelt 思路：

```
proposal_simulation_run
  input:  payload_json, current_governance_parameters, current_balances_snapshot
  output: expected_state_diff_hash + breakdown
          - param changes (key -> from, to)
          - balance changes (address -> delta)
          - new ledger events expected
          - new chain block events expected
  warnings:
          - "this mint exceeds rolling_30day_max_percent"
          - "this param change rolls back another in-flight proposal"
          - "expected balance change exceeds budget"
```

simulation 在 `formal_proposal` 階段強制跑；warnings 不阻擋提案，但會列在 proposal page 紅底警示。

`executed` 後再跑一次 actual_state_diff，計算 hash；不一致 → 自動觸發 `rolled_back` proposal（emergency committee 3-of-5）。

---

## 9. API 概要

| Method | Path | 角色 | 說明 |
|---|---|---|---|
| POST | `/api/governance/proposals` | logged-in（resp tier） | draft 提案（可改） |
| PUT | `/api/governance/proposals/<id>` | proposer | 編輯 draft |
| POST | `/api/governance/proposals/<id>/discussion` | proposer | 進 discussion 階段 |
| POST | `/api/governance/proposals/<id>/temperature-check` | proposer | 進 temperature 階段（L3+） |
| POST | `/api/governance/proposals/<id>/finalize` | proposer | 進 formal_proposal（鎖 payload + 鎖 deposit） |
| POST | `/api/governance/proposals/<id>/withdraw` | proposer | 撤案（依 §5 退 deposit 比例） |
| POST | `/api/governance/proposals/<id>/votes` | eligible voter | 投票 |
| PUT | `/api/governance/proposals/<id>/votes/me` | voter | 改票（限 voting 中） |
| POST | `/api/governance/proposals/<id>/veto` | vetoer 角色 | veto |
| POST | `/api/governance/proposals/<id>/queue` | system / executor | passed → queued_timelock |
| POST | `/api/governance/proposals/<id>/execute` | executor + multisig | 觸發 execution |
| POST | `/api/governance/proposals/<id>/rollback` | emergency committee | execute 失敗時走 |
| GET | `/api/governance/proposals/<id>` | public | 詳情 + 即時投票統計（脫敏） |
| GET | `/api/governance/proposals` | public | 列表 + filter（tier / status / type） |
| GET | `/api/governance/parameters` | public | 參數註冊表 |
| GET | `/api/governance/parameters/<key>/history` | public | 該參數歷史（含 proposal id） |

寫入路徑全走 `require_csrf` + tier-specific role check + multisig（L2+）。

---

## 10. 與 PointsChain ledger 的整合

每個 lifecycle 轉移都產生一筆 ledger event（type=`governance_*`），event_payload 含 `proposal_id`。

`executed` 階段最複雜：

```
proposal: mint, payload={destination:PNT1REWARD, amount: 1_000_000, reason:"Q3 reward expansion"}

execute flow:
  1. assert proposal.status == 'queued_timelock' AND now >= timelock_eta
  2. assert simulation hash matches latest payload_hash
  3. multisig executor signature 3-of-5 verified (per tier)
  4. write ledger:
       event_type='proposal_executed'
       event_payload={proposal_id, action:'mint', amount, destination}
  5. write ledger:
       event_type='points_minted'
       from_address=PNT1MINT
       to_address=PNT1REWARD
       amount=1_000_000
       reference_type='proposal'
       reference_id=proposal_id
  6. update governance_proposals.status='executed'
  7. update governance_parameters if param_change
  8. compute actual_state_diff_hash; assert == expected
  9. on mismatch → trigger rollback proposal automatically
```

---

## 11. 失敗訊息（user-facing）

```
"未達 proposal 門檻 / vote_weight 不足 / trust_score 不足"
"deposit 不足"
"payload schema 不符（key=...）"
"重複 payload（30 天內同 hash）"
"discussion_url 必填（L1+）"
"temperature_check 期未到"
"vote 已關閉"
"timelock 未到"
"actual_state_diff 與 expected 不符（已觸發 rollback）"
"自審不可（提案人 / 執行人 / 投票人不可同一）"
```

---

## 12. 跨參考

- 主索引：[GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md)
- 參數白名單：[GOVERNANCE_FRAMEWORK.md §6](GOVERNANCE_FRAMEWORK.md#6-parameter-registry治理參數註冊表)
- multisig 門檻：[MULTISIG_WALLETS.md §3](MULTISIG_WALLETS.md#3-門檻矩陣拍板)
- ledger schema：[POINTSCHAIN_ENGINEERING.md §4](POINTSCHAIN_ENGINEERING.md)
- 測試 gate：[GOVERNANCE_QA_GATE.md](GOVERNANCE_QA_GATE.md)
- 緊急路徑：[EMERGENCY_GOVERNANCE.md](EMERGENCY_GOVERNANCE.md)
- 司法層：[DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md)
