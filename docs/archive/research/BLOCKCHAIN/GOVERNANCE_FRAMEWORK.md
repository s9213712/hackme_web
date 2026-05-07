# PointsChain Governance Framework v1

> **Status：Design draft (Claude, 2026-05-05). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 2 / 4 / 6 complete and root separately authorizes Governance Phase.**
>
> 本文是 PointsChain 治理框架的**主索引**，把 8 份治理 spec 串起來。讀完這份再去看細節 spec。

---

## 0. 為什麼需要這份文件

PointsChain v1 / v2 已有：

```
ledger / wallet / chain block / 10 official addresses / multisig /
mint / burn / reward pool / audit / explorer / anti-abuse
```

這是**可驗證帳本**，但還不是**可治理的區塊鏈經濟系統**。

差別在 governance — 系統怎麼**集體決定**：

- 要不要 mint / 多少 / 進哪個池
- 要不要改 fee rate / emission rate / margin maintenance
- 要不要批准一筆 treasury 支出
- 要不要懲罰一個違規帳號 / 解除誤封
- 要不要進 / 出 emergency pause
- 治理權怎麼分配、能否委託、能否買賣

沒有這層，**多簽只是「批准器」**，不是治理。本框架補上這層。

---

## 1. 設計參照

| 系統 | 借鑑點 | 不借鑑 |
|---|---|---|
| **Uniswap** | proposal lifecycle / 投票期 / timelock / Seatbelt simulation | token-weighted voting（容易被大戶買走） |
| **Compound Governor Bravo** | review → voting → queue → timelock → execute 流程 | 完全可交易 governance token |
| **Optimism** | Bicameral（Token House + Citizens' House） | Layer-2 specifics |
| **Curve veCRV** | 鎖倉時間 → 治理權衰減（時間加權） | 可交易 veToken |
| **Cosmos** | minimum deposit / quorum / veto threshold / deposit period | on-chain auto-burn deposit |
| **Lido** | Committee 分工 / Easy Track / Dual Governance veto | 雙 token 結構 |
| **MakerDAO** | Emergency Shutdown 概念 / postmortem | global settlement（我們不會結算用戶資產） |

**核心原則**（與上述系統不同）：

1. **治理權 ≠ 可交易積分** — points 可轉、governance weight 不可轉
2. **治理權 = trust + age + contribution + (optional) reputation lock**
3. **最終仲裁權保留給 root + multisig** — 我們不是 DAO，是有治理諮詢的私有積分鏈
4. **所有治理事件上鏈** — 提案、投票、執行都進 ledger，explorer 公開
5. **Phase 0 user-exit window** — 重大治理變更前留 N 天讓用戶 export / cancel

---

## 2. 14 個治理維度（覆蓋對照）

| # | 維度 | 對應文件 | MVP? |
|---|---|---|---|
| 1 | Proposal lifecycle | [GOVERNANCE_PROPOSAL_LIFECYCLE.md](GOVERNANCE_PROPOSAL_LIFECYCLE.md) | ✅ |
| 2 | Voting power model | [GOVERNANCE_VOTING_POWER.md](GOVERNANCE_VOTING_POWER.md) | partial |
| 3 | Proposal deposit / spam guard | GOVERNANCE_PROPOSAL_LIFECYCLE.md §5 | ✅ |
| 4 | Parameter registry | GOVERNANCE_FRAMEWORK.md §6（below） + POINTS_MONETARY_POLICY §5 | ✅ |
| 5 | Treasury / budget | [TREASURY_BUDGET_POLICY.md](TREASURY_BUDGET_POLICY.md) | ✅ |
| 6 | Monetary policy | [POINTS_MONETARY_POLICY.md](POINTS_MONETARY_POLICY.md) | ✅ |
| 7 | Delegation / councils | GOVERNANCE_VOTING_POWER.md §6 | ❌ Phase 2 |
| 8 | Emergency governance | [EMERGENCY_GOVERNANCE.md](EMERGENCY_GOVERNANCE.md) | ✅ |
| 9 | Dispute / appeal | [DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md) | partial |
| 10 | Anti-Sybil eligibility | GOVERNANCE_VOTING_POWER.md §3 | ✅ |
| 11 | Governance explorer | GOVERNANCE_FRAMEWORK.md §8（below） | ✅ |
| 12 | Governance QA gate | [GOVERNANCE_QA_GATE.md](GOVERNANCE_QA_GATE.md) | ✅ |
| 13 | Role matrix | GOVERNANCE_FRAMEWORK.md §3（below） | ✅ |
| 14 | Simulation / state diff | GOVERNANCE_PROPOSAL_LIFECYCLE.md §8 | partial |

---

## 3. Role Matrix（角色矩陣）

10 個角色 × 9 種 capability：

| Role | propose | vote | veto | execute | pause | unpause | review | spend_budget | change_param |
|---|---|---|---|---|---|---|---|---|---|
| **Root Owner** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | (multisig) | (proposal) |
| **Security Council** | ✓ | ✓ | ✓ | (multisig) | ✓ | ✓ (multisig) | ✓ | (budget) | (proposal) |
| **Treasury Committee** | ✓ | ✓ | — | (multisig) | — | — | ✓ | ✓ | (proposal) |
| **Reward Committee** | ✓ | ✓ | — | (multisig) | — | — | ✓ | ✓ (reward budget) | (reward params) |
| **Market Risk Committee** | ✓ | ✓ | ✓ (market) | (multisig) | ✓ (market) | ✓ (market) | ✓ | — | (margin / oracle) |
| **Content Council** | ✓ | ✓ | — | (multisig) | — | — | ✓ | ✓ (content budget) | — |
| **Bug Bounty Reviewers** | ✓ (low/med) | ✓ | — | — | — | — | ✓ (bounty) | — | — |
| **Emergency Committee** | ✓ (emergency) | ✓ | ✓ (emergency) | ✓ (emergency) | ✓ | ✓ | ✓ | (emergency budget) | (emergency only) |
| **Delegates / Contributors** | ✓ (low only) | ✓ | — | — | — | — | — | — | — |
| **Citizens / regular users** | (low + deposit) | ✓ | — | — | — | — | — | — | — |
| **Auditors（可選）** | — | — | — | — | — | — | ✓ (read-only) | — | — |

**鐵律**：

- **沒有任何角色可以 self-approve**（提案人不可投自己的提案、執行人不可同時是 propose+approve+execute 三角的單一個體）
- **multisig 簽署門檻仍以 [`MULTISIG_WALLETS.md` §3](MULTISIG_WALLETS.md#3-門檻矩陣拍板) 為準**；governance proposal **觸發** multisig 而不是繞過 multisig
- **Citizens / 一般用戶**只能提 low-risk proposal（內容治理、bounty review、社群預算），且需要 deposit 防 spam
- **Emergency Committee 是時間盒（time-boxed）授權**，事件結束後 7 天必須交出 emergency power 並產 postmortem

---

## 4. 治理動作分類（Risk Tiers）

每個治理動作要先標 risk tier，後續 timelock / quorum / threshold 都依此計算：

| Tier | 範圍 | 範例 | 提案門檻 | 通過門檻 | timelock |
|---|---|---|---|---|---|
| **L0 內容** | 內容治理、bounty review、社群活動 | 移除特定看板貼文、bounty 重新評議 | 1 user + deposit_low | simple majority | 0–24 h |
| **L1 參數** | 非關鍵參數調整 | reward formula 微調、daily cap 微調 | 3 contributors + deposit_med | 60% vote + 30% quorum | 24–48 h |
| **L2 預算** | budget 內 treasury 支出 | 撥款 reward budget 給某活動 | committee + multisig 2-of-3 | committee approve + multisig | 48 h |
| **L3 經濟** | mint / burn / fee rate / margin maintenance | scheduled mint、改 transfer fee | committee + multisig 3-of-5 | 7-day vote + veto window | 7 days |
| **L4 結構** | 改 hard cap / 改 multisig signer / 改 governance framework | 升 supply cap、換 signer | root + multisig 4-of-5 | 14-day vote + 33% veto threshold | 14 days |
| **L5 緊急** | incident_lockdown / emergency_pause / emergency_mint | 凍結 trading、緊急鏈 freeze | emergency committee 3-of-5 | 立即（含公示） | 0（事後 7 天 postmortem） |

L0–L4 走完整 lifecycle（[GOVERNANCE_PROPOSAL_LIFECYCLE.md](GOVERNANCE_PROPOSAL_LIFECYCLE.md)）；L5 走特殊路徑（[EMERGENCY_GOVERNANCE.md](EMERGENCY_GOVERNANCE.md)）但**事後仍要回補完整稽核**。

---

## 5. 治理事件上鏈

每個治理事件都產生一筆 ledger event，與 PointsChain v2 既有事件並存：

```
proposal_created          payload_hash, proposer, tier, deposit
proposal_temperature_check  signal_count, signal_distribution
proposal_voting_started   voting_start_at, voting_end_at, quorum_required
proposal_vote_cast        voter, vote, weight, comment_hash?
proposal_voting_closed    yes / no / abstain / veto, quorum_met
proposal_queued           timelock_eta, queued_at
proposal_executed         executor, ledger_event_id, state_diff_hash
proposal_rejected         reason, rejected_at
proposal_vetoed           vetoer_role, reason
proposal_expired          expired_at
emergency_action_taken    actor, scope, justification_hash
budget_allocated          budget_id, amount, source_address
budget_spent              budget_id, amount, recipient, proposal_id
parameter_changed         param_key, from, to, proposal_id, effective_at
delegation_changed        delegator, new_delegate, weight, expires_at
```

每個 event 都帶 `proposal_id`（除 emergency 走獨立 id space 但仍寫進 ledger），可以用 `governance_proposal_id` 反查鏈上痕跡。

---

## 6. Parameter Registry（治理參數註冊表）

⚠️ **不要把治理參數散在 system_settings 隨手改**。所有需要治理的參數要走 `governance_parameters` 表 + 改值要走 proposal。

```sql
CREATE TABLE governance_parameters (
    param_key            TEXT PRIMARY KEY,              -- e.g. 'mint.core_points.hard_cap'
    current_value        TEXT NOT NULL,                  -- 字串保留，由 type adapter parse
    default_value        TEXT NOT NULL,
    value_type           TEXT NOT NULL,                  -- int|decimal|percent|enum|json
    min_value            TEXT,
    max_value            TEXT,
    risk_level           TEXT NOT NULL,                  -- L0..L5（見 §4）
    change_requires      TEXT NOT NULL,                  -- 對應 §4 通過門檻
    timelock_seconds     INTEGER NOT NULL DEFAULT 0,
    last_changed_by      INTEGER,                        -- proposer / executor
    last_proposal_id     TEXT,
    effective_at         TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE governance_parameter_history (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    param_key            TEXT NOT NULL,
    from_value           TEXT,
    to_value             TEXT NOT NULL,
    proposal_id          TEXT NOT NULL,
    effective_at         TEXT NOT NULL,
    rolled_back          INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL
);
```

**初始參數白名單**（v1 啟用）：

```
# Monetary
mint.core_points.hard_cap                L4
mint.scheduled.annual_rate_max           L3
mint.targeted.event_max_percent          L3
mint.emergency.event_max_percent         L4
mint.rolling_30day_max_percent           L3
burn.fee_burn_rate                       L3
burn.penalty.severe_percent              L3

# Transfer
transfer.fee_rate                        L3
transfer.fee_min_absolute                L3

# Trading
exchange_fund.health_warn_threshold      L3
exchange_fund.health_critical_threshold  L3
margin.maintenance_percent               L3
oracle.min_provider_count                L3
oracle.max_single_provider_weight        L3

# Reward
reward.formula_version                   L3
reward.daily_user_cap_base               L1
reward.weekly_user_cap_base              L1
reward.qa_mining.severity_caps_json      L3

# Governance meta
governance.proposal_deposit.L0           L1
governance.proposal_deposit.L1           L1
governance.proposal_deposit.L2           L1
governance.quorum.percent.L1             L4
governance.veto_threshold.percent        L4
governance.delegate_lockup_days          L4
```

**改參數鐵律**：

- 不可繞過 proposal flow 直接 UPDATE — DB trigger 在 production mode 拒絕直寫
- 改值的 ledger event 必須帶 `proposal_id` 且 `proposal_id` 在 `governance_proposals` 中是 `executed` 狀態
- 任何 `min_value` / `max_value` violation 在 proposal 階段就 reject

---

## 7. Anti-Sybil（治理資格）

不要直接「持有最多 points 的人 = 治理權最大」。一般 voting eligibility 公式：

```
eligible_voter = (
  account_age >= 30 days
  AND trust_score >= 50
  AND email_verified == true
  AND not_in_active_dispute
  AND not_recently_violation_clamped
)
```

vote weight：

```
base_weight     = trust_score / 100             # 0..1
contribution    = clamp(reward_lifetime_log / 10, 0, 2)
                                                # log-scaled，避免囤積壓制
account_age_w   = clamp(age_days / 365, 0, 1.5)
optional_lock_w = governance_lock_balance × lock_remaining_days / 365
                                                # 自願鎖（不可轉、不可贖）

vote_weight = base_weight × (1 + contribution + account_age_w + optional_lock_w)
```

各 tier 的最小 weight：

| Tier | 提案 vote_weight | 投票 vote_weight |
|---|---|---|
| L0 | ≥ 0.5 | ≥ 0.1 |
| L1 | ≥ 1.5 | ≥ 0.3 |
| L2 | committee only | ≥ 0.5 |
| L3 | committee + multisig | ≥ 1.0 |
| L4 | root + multisig | ≥ 2.0 + 7-day notice |

**Sybil triggers**（自動降權重 / 暫停 governance 資格）：

- 同 IP cluster 多帳號短期內同向投票
- 同 device fingerprint 多帳號
- 帳號年齡 < 投票期 + 7 天
- 過去 30 天有未結 violation
- 委託鏈出現 cycle（A delegate B, B delegate A）

詳細：[GOVERNANCE_VOTING_POWER.md §3](GOVERNANCE_VOTING_POWER.md)

---

## 8. Governance Explorer

新增 explorer 頁面（公開、不需登入；敏感欄位脫敏）：

```
/proposals                 列表 + 篩 tier / status
/proposals/<id>            完整 lifecycle / 投票分布 / payload hash / state diff
/votes/<proposal_id>       逐票（脫敏 voter，露 weight + vote）
/treasury                  各 budget 餘額 / 月支出 / 預估剩餘
/parameters                所有 governance_parameters 當前值 + 上次改動 proposal
/delegates                 delegate 名單 + statement + activity
/emissions                 mint 歷史按 tier
/burns                     burn 歷史按 reason
/budgets                   各 committee budget 用量
/emergency-events          emergency 事件 + postmortem 連結
```

**simulation 結果**（Uniswap Seatbelt 模式）：

```
proposal_simulation_result {
  expected_state_diff: { table -> rows },
  expected_balance_changes: { address -> delta },
  expected_param_changes: [ { param_key, from, to } ],
  warnings: [],
  generated_at, simulator_version
}
```

executed 後對比 actual_state_diff；不一致 → 自動 incident_lockdown 提案。

---

## 9. MVP（10 件最小可行版本）

第一版 governance 只做這 10 件，**先不做** 完整 user 投票 / 完整 delegation / Citizens House / ve-lock / rage quit：

```
1. Proposal registry        (governance_proposals 表)
2. Proposal type taxonomy   (L0..L5 × type_enum)
3. Multisig approval        (沿用 MULTISIG_WALLETS)
4. Timelock                 (queued_eta + execute window)
5. Parameter registry       (§6)
6. Treasury budget proposal (TREASURY_BUDGET_POLICY 簡化版)
7. Mint / burn proposal     (POINTS_MONETARY_POLICY)
8. Emergency pause / unpause(EMERGENCY_GOVERNANCE)
9. Public governance explorer (§8 minimal pages)
10. Governance QA gate      (GOVERNANCE_QA_GATE 12 條測試)
```

Phase 2+ 才補：

```
- 完整 user 投票權公式
- delegate / council 系統
- Citizens House 雙院
- ve-lock 時間加權
- rage quit / user exit window
- dispute court 完整版
```

---

## 10. 與既有 PointsChain phase 的關係

```
PointsChain v2 phases：
  Phase 0  cleanup gate     ✅ closed
  Phase 1  地址化            (Phase 1 candidate, root pending)
  Phase 2  ledger v2
  Phase 3  transfer
  Phase 4  multisig
  Phase 5  self-custody
  Phase 6  explorer + audit
  Phase 7  QA mining

Governance phase（new）：
  Phase G-0  parameter registry + proposal schema
  Phase G-1  proposal lifecycle + multisig integration
  Phase G-2  treasury budget + monetary policy enforcement
  Phase G-3  emergency governance + dispute MVP
  Phase G-4  governance explorer + QA gate
  Phase G-5  voting power + delegation (Phase 2 future)
```

**前置依賴**：Governance Phase 必須在 PointsChain Phase 1+2+4 完成後才開工（需要 ledger v2 + multisig 落地）。Phase 4 的 multisig 完成 = Governance Phase G-0 可開工。

---

## 11. Implementation Authorization

| 動作 | 授權狀態 |
|---|---|
| 寫 docs | ✅ 已授權（本框架就是 docs） |
| 讀 + 註冊 governance_parameters schema | ❌ 待 root + Phase 4 完成 |
| 啟動 proposal API（即使 read-only） | ❌ 待 root |
| 任何 mint / burn 走 proposal flow | ❌ 待 PointsChain v2 mainnet 啟用 |

**目前所有 governance 文件 = 設計草稿。** 實作要等：

1. PointsChain v2 Phase 1 / 2 / 4 / 6 全部 close
2. Governance Phase G-0 由 root 個別授權
3. 5 priority docs 全部 root review pass

---

## 12. 8 份治理文件總清單

| 文件 | 角色 | 優先序 |
|---|---|---|
| **GOVERNANCE_FRAMEWORK.md** | 主索引（本檔） | ⭐ 1 |
| **GOVERNANCE_PROPOSAL_LIFECYCLE.md** | 提案 11 種狀態 + schema + timelock | ⭐ 2 |
| **POINTS_MONETARY_POLICY.md** | mint / burn / emission 制度 | ⭐ 3 |
| **TREASURY_BUDGET_POLICY.md** | 預算制度 + committee 分工 | ⭐ 4 |
| **EMERGENCY_GOVERNANCE.md** | 緊急治理 + postmortem + exit window | ⭐ 5 |
| **GOVERNANCE_VOTING_POWER.md** | 投票權公式 + Bicameral + delegation | 6 |
| **GOVERNANCE_QA_GATE.md** | 12 條 governance QA 必過測試 | 7 |
| **DISPUTE_AND_APPEALS.md** | 司法層 / 申訴流程 | 8 |

---

## 13. 結語

> **PointsChain 現在像「可驗證帳本」。**
> **補上 governance framework 後，才會變成「可治理的區塊鏈經濟系統」。**

完整治理 = ledger（已有）+ governance（這套 8 文件）+ enforcement（multisig + timelock + QA gate）。

任何人在閱讀這份框架時若發現某個維度沒被覆蓋，請開 issue 並引用 §2 對照表 — 框架是活的，但每次擴充都要走 governance 自己定義的 proposal flow（meta-governance）。
