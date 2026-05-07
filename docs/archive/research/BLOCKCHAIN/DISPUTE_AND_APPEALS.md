# Dispute and Appeals v1

> **Status：Design draft (Claude, 2026-05-06). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 2 / 4 / 6 complete + Governance Phase G-3 authorization.**
>
> 屬 [GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md) §2 維度 9。本文是「司法層」spec — 處理 governance / trading / reward / admin action 的爭議與翻案。

---

## 0. 設計參照

| 系統 | 借鑑 |
|---|---|
| **Cosmos governance** | dispute pool 概念 / 不立即燒毀押金，由 committee 仲裁 |
| **Lido Easy Track** | 普通 dispute 由 committee 處理，重大 dispute 走完整 governance |
| **Optimism Citizens' House** | 1 member 1 vote 仲裁複雜 dispute |
| **MakerDAO governance** | dispute 結果可觸發 emergency governance |

---

## 1. 為什麼需要 dispute system

PointsChain 已有：

```
- audit log（審計）
- bug bounty review（QA mining）
- multisig（多簽防 collusion）
- emergency governance（最後手段）
```

但**沒有「平民可申訴」的司法層**。下列場景目前無解：

| 場景 | 影響的人 | 目前怎麼辦 |
|---|---|---|
| Bug bounty 認定 invalid 但 reporter 認為被偷雷同 | reporter | 沒地方申訴 |
| Reward mining 重複回報 → 第二人領 | 第一人（被搶獎勵） | 沒地方申訴 |
| 商城交易糾紛（買到瑕疵 / 賣家欺詐） | 買方 / 賣方 | 沒地方申訴 |
| Transfer 誤發（地址打錯） | 發送者 | 沒地方申訴 |
| Admin 懲罰不服（封號 / 扣點 / shadow ban） | 被罰用戶 | 沒地方申訴 |
| Governance proposal 被惡意 spam 標記 | proposer | 沒地方申訴 |
| 投票被誤判 sybil 歸零 | voter | 沒地方申訴 |

本 spec 把這些統一進一個 dispute system，有完整流程 + committee 仲裁 + 上鏈紀錄。

---

## 2. Dispute 種類

```
bounty          # bug bounty 爭議
reward          # reward mining 爭議
trade           # 交易糾紛 / 商城糾紛
transfer        # 轉帳誤發
admin_action    # admin 封號 / 扣點 / shadow ban 申訴
governance      # proposal spam 標記、sybil 歸零、proposal 翻案
emergency       # emergency action 個人受害申訴
```

每類有對應的 mediator committee：

| 種類 | mediator | 上訴最終仲裁 |
|---|---|---|
| `bounty` | Bug Bounty Reviewers | Security Council |
| `reward` | Reward Committee | Security Council |
| `trade` | Content Council | Treasury Committee |
| `transfer` | Treasury Committee | Security Council |
| `admin_action` | Security Council | Emergency Committee |
| `governance` | Treasury Committee | Emergency Committee |
| `emergency` | Emergency Committee | root + multisig 4-of-5 |

---

## 3. Dispute schema

```sql
CREATE TABLE disputes (
    id                   TEXT PRIMARY KEY,                  -- disp_<yyyymmdd>_<rand>
    kind                 TEXT NOT NULL,                      -- 對應 §2
    related_kind         TEXT NOT NULL,                      -- 對應 governance proposal_type 或 ledger event_type
    related_id           TEXT NOT NULL,                      -- proposal_id / ledger_event_id / order_id / etc
    claimant_user_id     INTEGER NOT NULL,                   -- 申訴方
    respondent_user_id   INTEGER,                             -- 被申訴方（admin / 系統 / 對方 user）
    respondent_role      TEXT,                                -- system|admin|user|committee
    title                TEXT NOT NULL,
    summary              TEXT NOT NULL,
    evidence_hashes      TEXT NOT NULL DEFAULT '[]',          -- JSON array of off-chain evidence sha256
    remedy_requested     TEXT NOT NULL,                       -- refund|reverse|reissue|warning|reset|other
    remedy_amount        INTEGER,                             -- 金額（若是 refund）

    status               TEXT NOT NULL DEFAULT 'submitted',   -- submitted|under_review|temporarily_frozen|mediated|appealed|finalized|withdrawn|rejected
    temporary_freeze_event_id INTEGER,                         -- 暫時凍結相關資產的 ledger event
    mediator_role        TEXT,                                -- 對應 §2
    mediator_assigned_at TEXT,
    mediator_decision    TEXT,                                -- approved|rejected|partial|defer
    mediator_decision_at TEXT,
    mediator_decision_rationale_hash TEXT,

    appeal_window_seconds INTEGER NOT NULL DEFAULT 1209600,   -- 14 days default
    appealed_at          TEXT,
    appeal_committee_role TEXT,
    appeal_decision      TEXT,
    appeal_decision_at   TEXT,
    final_executor_role  TEXT,
    final_execution_proposal_id TEXT,                          -- 走 proposal flow 執行 final remedy

    deposit_amount       INTEGER NOT NULL DEFAULT 0,
    deposit_status       TEXT NOT NULL DEFAULT 'pending',     -- pending|locked|refunded|forfeited
    sybil_flag           INTEGER NOT NULL DEFAULT 0,
    sybil_flag_reason    TEXT,

    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX idx_disputes_kind ON disputes(kind, status);
CREATE INDEX idx_disputes_claimant ON disputes(claimant_user_id, created_at);

CREATE TABLE dispute_evidence (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    dispute_id           TEXT NOT NULL,
    submitter_user_id    INTEGER NOT NULL,
    submitter_role       TEXT NOT NULL,                       -- claimant|respondent|mediator|witness
    evidence_kind        TEXT NOT NULL,                       -- text|file|on_chain_event|external_link
    evidence_hash        TEXT NOT NULL,
    storage_pointer      TEXT,                                -- off-chain storage location
    submitted_at         TEXT NOT NULL,
    rejected             INTEGER NOT NULL DEFAULT 0,           -- mediator 判定不採納
    rejection_reason     TEXT
);

CREATE TABLE dispute_lifecycle_logs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    dispute_id           TEXT NOT NULL,
    from_status          TEXT,
    to_status            TEXT NOT NULL,
    actor_user_id        INTEGER,
    actor_role           TEXT,
    detail_json          TEXT,
    chain_event_id       INTEGER,
    created_at           TEXT NOT NULL
);

CREATE TABLE dispute_pool (
    -- 收 forfeit 的 deposit / penalty 暫管
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_dispute_id    TEXT NOT NULL,
    amount               INTEGER NOT NULL,
    received_at          TEXT NOT NULL,
    disposition          TEXT NOT NULL DEFAULT 'pending',     -- pending|burned|refunded|treasury|reward
    disposition_proposal_id TEXT,
    disposed_at          TEXT
);
```

---

## 4. Dispute lifecycle

```
submitted
  ├─ withdrawn
  └─→ under_review
        ├─ rejected           (claim 明顯無理 / sybil flagged)
        └─→ temporarily_frozen (若需要凍結相關資產等候裁決)
              └─→ mediated
                    ├─ appealed → finalized
                    └─→ finalized
```

| 狀態 | 誰能轉移 | 條件 |
|---|---|---|
| `submitted` | claimant | 提交 + deposit |
| `withdrawn` | claimant | 主動撤回（48h 內無條件，之後罰 deposit） |
| `under_review` | mediator | 接案 |
| `rejected` | mediator | claim 無理 / sybil flag / out-of-scope |
| `temporarily_frozen` | mediator | 需要凍結資產（trade dispute / transfer 誤發） |
| `mediated` | mediator | 給出 decision |
| `appealed` | claimant 或 respondent | 14 天 appeal window 內 |
| `finalized` | 系統 | appeal window 過 / appeal committee decision |

---

## 5. Deposit 規範

| 種類 | 申訴 deposit | 申訴成功退還 | 申訴失敗 | sybil flag |
|---|---|---|---|---|
| `bounty` | 50 points | 全退 | 50% 進 dispute pool, 50% 退 | 100% forfeit |
| `reward` | 50 points | 全退 | 50% 進 dispute pool | 100% forfeit |
| `trade` | trade amount × 0.5%（min 100） | 全退 | 50% 進 dispute pool | 100% forfeit |
| `transfer` | 100 points | 全退 | 50% 進 dispute pool | 100% forfeit |
| `admin_action` | 200 points | 全退 | 50% 進 dispute pool | 100% forfeit |
| `governance` | 500 points | 全退 + 補償 spam_score 0 | 50% 進 dispute pool | 100% forfeit |
| `emergency` | waived | — | — | 不適用 |

⚠️ **第一版禁止自動 burn deposit**。所有 forfeit 暫存 `dispute_pool`，最終處置走 L3 proposal（burn / treasury / reward 分配）。

---

## 6. Mediator 流程

### 6.1 接案

```
mediator 收到 dispute（系統依 dispute kind 自動分派 committee）
  → 14 days 內必須做出 decision
  → 超時 → 自動 escalate 到 appeal committee
```

### 6.2 暫時凍結（若 mediator 認為必要）

```
trade / transfer / admin_action 類:
  - 凍結相關 ledger event 對應的後續 spending（freeze_address 部分）
  - ledger event: dispute_temporary_freeze
  - 凍結期最長 30 天
  - 期間 user 仍可看餘額，但不可花

governance / bounty / reward 類:
  - 暫不執行對應 governance proposal / payout
  - 已執行的不 reverse；mediator 寫入「pending appeal」flag
```

### 6.3 Decision 種類

```
approved:    完全採納申訴 → 走 final_execution_proposal
rejected:    完全駁回 → deposit 退 / forfeit 依 §5
partial:     部分採納 → 部分 remedy
defer:       資訊不足，回 claimant 補件（最多 30 天）
```

### 6.4 自審禁止

```
mediator 不可仲裁：
  - 自己提的 dispute
  - 自己參與的 trade / proposal
  - 與自己有 declared_conflict 關係的人
  - 同 commitee 其他成員提的（避免 quid-pro-quo）

→ 系統自動 reroute 到 backup mediator (appeal committee)
```

---

## 7. Final execution（remedy 怎麼執行）

approved / partial 後走完整 governance proposal：

```
proposal_type: dispute_remedy
payload:
  dispute_id: <id>
  remedy: refund|reverse|reissue|warning|reset
  amount: int (若 refund / reverse)
  source_address: PNT1RESERVE|PNT1TREASURY|dispute_pool
  to_address: claimant_wallet
  reverse_target_event_id: <ledger event id>  (若 reverse 一筆 ledger)
governance:
  tier: L1 (low remedy < 1000 points) / L2 (medium) / L3 (large)
  multisig: dispute mediator committee
  timelock: 短 (24h–48h)
```

執行後寫 ledger event：

```
event_type: dispute_remedy_executed
metadata: {
  dispute_id, remedy, amount, source, target,
  mediator_role, executor_role
}
```

---

## 8. Appeal（上訴）

```
mediated 後 14 days 內 claimant 或 respondent 都可上訴
  → status='appealed'
  → 進 appeal_committee（§2 表格右側）
  → committee multisig 2-of-3 投票
  → 上訴成功率 < 30%（鼓勵 mediator 仔細處理）
  → 上訴勝訴 → 原 mediator 該 case 計入「reversal rate」
                 reversal rate > 30% → 該 mediator 進 30 day cooldown
```

上訴失敗：

```
原 deposit 額外扣 10% 進 dispute pool
appeal record 永久寫進 user 的 governance profile
  （影響未來 dispute 提交 sybil score）
```

---

## 9. 重大 dispute → 觸發 emergency

某些 dispute 嚴重到應該走 emergency：

| 觸發 | 進什麼 emergency |
|---|---|
| 大額 transfer 誤發 + 涉及攻擊 / 駭客嫌疑 | `incident_lockdown_enter` |
| 大量同類 dispute（24h 內 100+ 同 admin / 同 type） | `governance_pause` + 該 admin / committee 凍結 |
| Mediator decision 自相矛盾（同類 case 不同結果） | `governance_pause` + Audit |
| 偵測 mediator collusion | `incident_lockdown_enter` + emergency committee 介入 |

---

## 10. 公開透明

```
/disputes                列表（脫敏）+ status 篩選
/disputes/<id>           詳情（不公開 evidence_hashes 內容，只露 hash）
/disputes/<id>/timeline  生命週期 logs
/dispute-pool            待處置 forfeit 餘額 + 月度處置 proposal
/mediator-stats          mediator 仲裁次數 / reversal rate / 平均處理天數
```

每月公開：

```
本月 disputes:                     X
平均處理時間:                      Y days
mediation 結果分布:                approved/rejected/partial/defer
appeal rate:                       Z%
reversal rate:                     W%
sybil flagged dispute:             V
dispute pool 餘額:                 N
```

---

## 11. 反 Sybil（dispute 防濫用）

```
sybil_score_for_dispute:
  same_user_dispute_in_30days × 5
  + same_ip_cluster_dispute_in_30days × 3
  + frequency_of_rejected_disputes × 4
  + dispute_kind_concentration × 2     # 同一 kind 反覆提
  - account_age_days × 0.05
  - successful_dispute_history × 2

sybil_score >= 25 → flag, deposit 100% forfeit, dispute auto-rejected
連續 3 次被 sybil flagged → 90 days dispute cooldown
```

---

## 12. 與既有系統的整合

| 既有 | 整合方式 |
|---|---|
| `bug_reports` | bounty dispute 直接引用 bug_report.id 作為 related_id |
| `points_ledger` | transfer / reward / trade dispute 引用 ledger_event_id |
| `trading_orders` | trade dispute 引用 order_uuid |
| `governance_proposals` | governance dispute 引用 proposal_id |
| `audit_log` | admin_action dispute 引用 audit log id |
| `MULTISIG_WALLETS` | 重大 remedy 走 multisig |
| `EMERGENCY_GOVERNANCE` | 重大 dispute 升級走 §9 |

---

## 13. Implementation Phase

```
Governance Phase G-3 (MVP partial):
  - disputes / dispute_evidence / dispute_lifecycle_logs schema
  - 基本 dispute kind: bounty / reward / transfer / admin_action
  - mediator API + 自審禁止 trigger
  - 14-day appeal window
  - 公開 /disputes 頁

Governance Phase G-6 (full version):
  - trade / governance / emergency dispute kind
  - 完整 sybil scoring
  - 月度 dispute pool 處置 proposal
  - mediator stats public page
  - emergency 觸發路徑（§9）
```

依賴：

- PointsChain v2 Phase 6 explorer
- GOVERNANCE_PROPOSAL_LIFECYCLE 完整實作（remedy 走 proposal）
- TREASURY_BUDGET_POLICY committee 結構
- EMERGENCY_GOVERNANCE 完整實作

---

## 14. 跨參考

- 主框架：[GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md)
- proposal lifecycle：[GOVERNANCE_PROPOSAL_LIFECYCLE.md](GOVERNANCE_PROPOSAL_LIFECYCLE.md)
- 預算（mediator committee 來源）：[TREASURY_BUDGET_POLICY.md](TREASURY_BUDGET_POLICY.md)
- 緊急升級：[EMERGENCY_GOVERNANCE.md](EMERGENCY_GOVERNANCE.md)
- voting power（sybil 共用）：[GOVERNANCE_VOTING_POWER.md](GOVERNANCE_VOTING_POWER.md)
- multisig：[MULTISIG_WALLETS.md](MULTISIG_WALLETS.md)
- bug bounty 既有設計：[POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md)
