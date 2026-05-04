# PointsChain Mining Rewards v1

> **Status：Design approved (root, 2026-05-04)，implementation blocked until PointsChain v2 Phase 0/1/2/4/6 complete.**
>
> 此文件是 PointsChain v2 **Phase 7** 正式設計書。
> 對應 [`docs/research/QA Mining.txt`](../research/QA%20Mining.txt) 與
> 設計提案 [`docs/research/POINTS_MINING_REWARDS_PLAN.md`](../research/POINTS_MINING_REWARDS_PLAN.md)。
>
> 在 PointsChain v2 Phase 0/1/2/4/6 完成前，僅允許 DRAFT / mock / dry-run；不准真實 payout。

---

## 0. 拍板的核心決策摘要（root, 2026-05-04）

| # | 拍板 | 來源 |
|---|---|---|
| 1 | 列為 PointsChain v2 **Phase 7**；前置依賴 Phase 0/1/2/4/6 | §1 |
| 2 | reward 公式：`base × repro × novelty × security × trust_multiplier`；**有 hard cap** | §2 |
| 3 | reward ≥ 1000 必走 multisig；root 自己領一律 3-of-5；**signer 對自己相關 reward 自動排除投票** | §3 |
| 4 | reporter ≠ verifier 是紅線；連 root 都不能同人；DB + API + UI + 測試覆蓋 | §4 |
| 5 | 與既有 `bug_reports` 整合，不另起平行系統 | §5 |
| 6 | FP 給 5 points 但有條件（只給格式完整、善意提交，垃圾不給；FP 也算 daily cap） | §6 |
| 7 | Split payout 預設 reporter 80% / verifier 20%；高額 verifier payout 也走 multisig | §7 |
| 8 | trust_score 起始 50；high/blocker bug 額外 +5；malicious 直接 suspend | §8 |
| 9 | Retroactive reward 只走 multisig batch；explorer 公開但不洩 user_id/IP/device | §9 |
| 10 | Anti-Sybil：client_ip_hash + device_fingerprint + account_age + same_payment/browser/device risk flag | §10 |
| 11 | reward_pool solvency：< 4 週黃 / < 1 週紅 / pending > pool 暫停；不可自動 mint 補 | §11 |
| 12 | claim 30 天過期 / pending 可撤回 / 已 approve/paid 不可撤回 | §12 |
| 13 | Explorer 公開 payout / category / severity / amount，禁顯 user_id/IP/device | §13 |
| 14 | 第一版只設計懲罰路徑，**不啟用自動罰金**；扣分/burn 必走 multisig；不允許系統自動 burn 用戶資產 | §14 |
| 15 | Severity 分級審核：Low/Medium 雙人；High root/security_admin + verifier；Blocker multisig 或 2-of-3 emergency；reward ≥ 1000 multisig | §15 |

---

## 1. Phase 順序

正式列為：

> **PointsChain v2 Phase 7：QA Mining / Contribution Rewards**

依賴鏈：

| 依賴 phase | 提供能力 |
|---|---|
| Phase 0 清債 | 讓錯誤計算不被永久寫入鏈 |
| Phase 1 地址化 | 提供 `OFFICIAL_REWARD_POOL` address |
| Phase 2 Ledger v2 | 提供 address-centric ledger 與 chain block |
| Phase 4 Multisig | 提供 reward ≥ 1000 + retroactive batch + 罰金路徑的多簽 |
| Phase 6 Explorer | 提供公開查詢介面 |

**前置未完前只允許 DRAFT / mock / dry-run；不准真實 payout。**

---

## 2. Reward 公式

### 2.1 公式

```
reward = base[severity]
       × reproduce_factor       # 1.0 / 0.5 / 0.2
       × novelty_factor         # 1.0 / 0.3 / 0.0
       × security_multiplier    # 1.5 (有安全洞) / 1.0
       × trust_multiplier       # trust_score / 50, clamp [0.4, 2.0]
```

### 2.2 base × hard cap 對照

| severity | base | hard cap |
|---|---:|---:|
| low | 30 | **50** |
| medium | 150 | **250** |
| high | 600 | **1200** |
| blocker | 2500 | **5000** |

`approved_reward = min(formula_result, hard_cap[severity])`

### 2.3 必須可解釋

前後台都要顯示 reward breakdown：

```
suggested_reward = 600 (high base)
                 × 1.0  (full repro)
                 × 1.0  (novel)
                 × 1.5  (security)
                 × 1.6  (trust 80 → 80/50)
                 = 1440
hard_cap = 1200
approved_reward = min(1440, 1200) = 1200  ← capped
```

API response `claim` 必含：

```json
{
  "claim_id": "...",
  "severity": "high",
  "formula": {
    "base": 600,
    "reproduce_factor": 1.0,
    "novelty_factor": 1.0,
    "security_multiplier": 1.5,
    "trust_multiplier": 1.6,
    "raw": 1440,
    "hard_cap": 1200,
    "capped": true
  },
  "suggested_reward": 1200
}
```

### 2.4 admin 可微調但不能繞 hard cap

- admin review 時可向**下調**（風控判斷），不可向**上**超過 hard_cap
- 任何調整都寫 audit event `mining_reward_adjusted` 含 reason

---

## 3. Multisig 門檻

### 3.1 金額門檻

| reward 金額 | 審核 |
|---|---|
| ≤ 200 | Low/Medium 嚴格走 §15 雙人；High 以上走嚴格分級 |
| 201–999 | 同上 |
| ≥ 1000 | **必須 multisig**（mainnet 3-of-5，internal_test 2-of-3）|
| root 自己領獎 | **一律 3-of-5 multisig**，不論金額 |
| Verifier payout（split 後）≥ 1000 | **同樣須 multisig** |

### 3.2 Signer 自動排除

> **signer 對自己相關的 reward proposal，必須自動排除自己投票權。**

實作要求：

- 對 mining payout 的 multisig proposal，多簽 service 計算門檻時：
  ```
  effective_threshold = nominal_threshold
  effective_signers   = active_signers - { reporter_user_id, verifier_user_id }
  if len(effective_signers) < effective_threshold:
      reject "insufficient independent signers; escalate review"
  ```
- 不僅排除「投票」，**proposal 視自動排除的 signer 為棄權**，需另從剩餘 signer 集滿足門檻
- 若排除後不夠人 → proposal 進 `awaiting_independent_signer` 狀態，由 root 加 emergency_recovery_admin 補簽，或 reject 該 claim

### 3.3 Multisig action 名稱（補入 [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) 的 action_type list）

```
'mining_reward_payout'        # 大額單筆 payout
'mining_retroactive_batch'    # retroactive 批次
'mining_pool_refill'          # treasury → reward_pool 補充
'mining_burn_penalty'         # 惡意提交扣分到 BURN（第一版仍只走人工提案）
'mining_signer_quarantine'    # 把違規 signer 暫停
```

---

## 4. Reporter ≠ Verifier 紅線

### 4.1 必須四層守護

| 層 | 機制 |
|---|---|
| DB | `points_mining_claims.verified_by` 與 `user_id` (reporter) 之間 CHECK；split 表 `payee_user_id` 不可同時是 reporter 與 verifier |
| Service | `approve_claim()` / `verify_claim()` 進入時硬 check；違反拋 ValueError |
| API | route handler 在驗證階段 reject 並回明確訊息「不能驗證自己提的 claim」 |
| UI | verifier 列表 disable 自己；前端不可送出（disabled state）|

### 4.2 連 root 也不行

- `actor.id == claim.user_id` 時 verify 路徑必拒
- root 想讓自己領獎只能透過 retroactive batch + 3-of-5 multisig，且 multisig signer 不能含 root（依 §3.2）

### 4.3 測試覆蓋（Phase 7 QA gate 必過）

- DB CHECK 試 INSERT 同 user_id == verified_by → IntegrityError
- API 試 root verify 自己 claim → 403 + 訊息正確
- UI test：verifier 下拉不可選自己

---

## 5. 與 bug_reports 整合

### 5.1 不要平行 schema

- bug 的 reproduction / expected / actual / evidence 全部留在 `bug_reports` 表
- mining claim 表只記 reward / review / payout 狀態
- `points_mining_claims.reference_type='bug_report'` + `reference_id=bug_reports.id`

### 5.2 既有 bug_reports 的欄位升級

```sql
ALTER TABLE bug_reports ADD COLUMN is_mining_eligible INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bug_reports ADD COLUMN mining_claim_id TEXT;  -- one-to-one with points_mining_claims
ALTER TABLE bug_reports ADD COLUMN severity TEXT
    CHECK (severity IN ('low','medium','high','blocker') OR severity IS NULL);
```

`is_mining_eligible=0` 用於：admin 判定不適合計獎勵的 bug（例如測試資料、內部報告等）。

### 5.3 流程

1. user 透過 bug-reports 頁送 bug（既有 UX）
2. 若 `is_mining_eligible=1` 且 PointsChain v2 已到 Phase 7：自動建立 `points_mining_claims`，狀態 `pending`
3. admin 在 bug_reports review 頁標記 verified/duplicate/false_positive；對應 mining claim status 同步
4. mining claim 走 §3 的審核分級
5. payout 透過 ledger_v2 + multisig（如需）執行

---

## 6. False Positive 獎勵

### 6.1 條件式 5 points 象徵獎

只給：

- ✅ 格式完整（含 9 項必填欄）
- ✅ 善意提交（admin 主觀但須留 review_note）
- ✅ trust_score ≥ 30
- ✅ 該 user 當日 / 當週尚有 cap 額度

不給：

- ❌ 明顯垃圾（無 evidence、AI 生成空殼）
- ❌ 惡意（誣陷、灌水、刷分）
- ❌ trust_score < 30
- ❌ 已用完 cap

### 6.2 FP reward 同樣計入 cap

`approved_reward = 5` 仍佔用：

- daily_user_cap
- weekly_user_cap
- weekly_budget
- 對應 reward_pool 餘額扣除

### 6.3 連續 5 次 FP → suspend

trust_score：

- 一般 FP：-10（floor 0）
- 連續 5 次 FP：trust_score 直接設 30、suspended_until = now + 7 days
- 黃名單期間：不可送 claim、可看 explorer

---

## 7. Split Payout

### 7.1 預設

```
reporter:  80%
verifier:  20%
```

### 7.2 可調限制

- admin review 時可調比例，但 verifier 上限 50%（避免「verifier 多領鼓勵亂驗」）
- 任何 verifier payout 超過 1000 points → 觸發 multisig
- split 加總必須 = 100.00%（DB level CHECK `share_basis_points` 加總 = 10000）

### 7.3 Verifier 必須有實際驗證 evidence

- review 表單強制 verifier 填「驗證步驟」與「驗證結果」
- 缺驗證 evidence → claim 不可標記 verified
- audit event `mining_claim_verified` 記錄 verifier 提交的 evidence_hash

### 7.4 Verifier ≠ Reporter

對齊 §4。任何 split payee 不能同時擔任 reporter 與 verifier。

---

## 8. Trust Score

### 8.1 起始與邊界

- new user：50（起始）
- 邊界：[0, 100]

### 8.2 變動規則

| 事件 | trust Δ | 備註 |
|---|---|---|
| verified bug (low/medium) | +5 | cap 100 |
| verified bug (high/blocker) | +5 + 額外 +5 = **+10** | 鼓勵高品質 |
| duplicate | -2 | floor 0 |
| false_positive | -10 | floor 0 |
| 連續 5 次 FP | trust → 30；suspended 7 days | |
| malicious / spam（admin 標記） | -30 或直接 suspend | 視 admin 決策 |
| 30 天無活動 | +1/day 回升至 50 | 不超過 50 |

### 8.3 trust 影響

| 項目 | 公式 |
|---|---|
| reward multiplier | `clamp(trust_score / 50, 0.4, 2.0)` |
| effective_daily_cap | `daily_cap_base × clamp(trust_score / 50, 0.4, 2.0)` |
| effective_weekly_cap | `weekly_cap_base × clamp(trust_score / 50, 0.4, 2.0)` |
| 是否需人工預審 | trust_score < 30 自動進 manual review |
| 是否進黃名單 | suspended_until > now |

### 8.4 trust 變動透明

- 每次 trust 變動寫 audit event `mining_trust_adjusted` 含 (delta, reason, old, new)
- user 自己可在 trust 詳情頁看到歷史

---

## 9. Retroactive Reward

### 9.1 規則

- 只走 multisig batch（`mining_retroactive_batch` action）
- 不自動 payout
- 必須人工列清單：每筆要有 `reference_type='github_issue' or 'bug_report'` + `reference_id`
- 每批要有 multisig approval（mainnet 3-of-5）

### 9.2 適用範圍

`#115–#131` 等已 close / 已驗證的 issues 適用。

實際清單由 root 在 multisig proposal 內附；本文件不預先指定具體分配。

### 9.3 Explorer 顯示

可查：

- payout block_id / event_id
- category=qa
- severity
- approved_reward
- 對應 reference（GitHub issue 公開連結 OK）

不可洩漏：

- 領獎者 user_id / 帳號
- IP / device fingerprint
- 多簽 signer 個人簽章內容（顯示 signer count 即可）

---

## 10. Anti-Sybil

### 10.1 必記欄位

```sql
ALTER TABLE points_mining_claims ADD COLUMN client_ip_hash TEXT;
ALTER TABLE points_mining_claims ADD COLUMN device_fingerprint TEXT;
ALTER TABLE points_mining_claims ADD COLUMN account_age_days INTEGER;
ALTER TABLE points_mining_claims ADD COLUMN risk_flags TEXT;  -- JSON array
```

### 10.2 risk flags

- `same_ip_24h_multi_user` — 同 IP 24h 內 ≥ 3 user 提 claim
- `same_device_24h_multi_user` — 同 device fingerprint 同上
- `same_payment_account` — 同 payment instrument 對應多 user
- `same_browser_session` — 同 session 處理多帳號
- `new_account` — account_age < 7 days
- `low_trust` — trust_score < 30

### 10.3 顯示與隱私

| 欄位 | 後台 | 前台 | Explorer |
|---|---|---|---|
| client_ip_hash | 顯示 hash 與重複度統計 | 不顯示 | 不顯示 |
| device_fingerprint | 顯示 hash | 不顯示 | 不顯示 |
| account_age_days | 顯示 | 顯示自己 | 不顯示 |
| risk_flags | 顯示 | 不顯示（避免 user 自我規避）| 不顯示 |

明確寫進：

- `docs/BLOCKCHAIN/POINTS_MINING_REWARDS.md`（本文件 §10）
- `docs/03_ADMIN_GUIDE.md` 隱私段落
- 隱私政策

---

## 11. Reward Pool Solvency

### 11.1 Boot-time + 週期性 check

| 條件 | 動作 |
|---|---|
| reward_pool ≥ 4 × weekly_budget | dashboard 綠燈 |
| 1 × weekly_budget ≤ reward_pool < 4 × weekly_budget | dashboard **黃燈** + alert finance_admin |
| reward_pool < 1 × weekly_budget | dashboard **紅燈** + 通知 root + 限制新 approve |
| reward_pool < pending approved payout 總和 | **暫停所有 payout**；可繼續送 / 審 claim 但不 execute |

### 11.2 不允許自動 mint

- reward_pool 補充必須走 `treasury_transfer` multisig（已在 [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) 列為 3-of-5 mainnet）
- 不存在「自動補充」「自動 mint」「rate-based 補充」設計
- root 也不可單人補

### 11.3 Solvency event

任何 solvency 改變寫 audit event `mining_reward_pool_solvency_changed` 含 (state_before, state_after, reward_pool_balance, weekly_budget)。

---

## 12. Claim 過期與撤回

| 狀態 | 規則 |
|---|---|
| pending | 30 天未審核自動 → `expired` |
| pending | user 可主動撤回 → `withdrawn`（不影響 trust） |
| pending_next_period | 因 cap 觸發延後；下個週期自動回 pending |
| approved | 不可撤回（只能 admin 走 reject 流程，需 audit + 補償邏輯） |
| paid | 不可撤回（只能走 retroactive 反向 multisig batch） |
| rejected / expired / withdrawn | 不執行 payout，但保留 audit record（永久保留）|

過期 / 撤回不消耗 weekly_budget。

---

## 13. Explorer 公開化

### 13.1 顯示

- payout event（`mining_payout` ledger event）
- claim category / severity / approved_reward
- from = `OFFICIAL_REWARD_POOL`
- to = anonymized 縮寫（`PNT1ab8K…wxyz` 顯示前 8 + 後 4）
- block_id / events_root

### 13.2 禁止顯示

- user_id / username
- email / phone
- IP / device fingerprint
- private evidence（內部 admin note）
- 未公開安全細節（reproduction step 內含 0-day 風險時 admin 可標 `public_visible=0` 隱藏）

### 13.3 排行榜

- 顯示 top contributors（用匿名地址）
- 顯示 contribution score（總獎勵；不顯示具體 user）
- 用戶可在自己頁面選擇「公開暱稱」進入排行榜（opt-in）

---

## 14. 惡意提交 / Burn 路徑

### 14.1 第一版限制

> **第一版只設計懲罰路徑，不啟用自動罰金。**

具體規則：

- spam / malicious claim 標記 → 自動 `suspend_mining`（不領取資產）
- 嚴重濫用 → admin 發 multisig proposal `mining_burn_penalty`
- 任何「扣分 / burn 用戶資產」必須 multisig（mainnet 3-of-5）
- **不允許系統自動 burn 用戶資產**

### 14.2 schema 預留

```sql
ALTER TABLE points_mining_trust_state ADD COLUMN suspended_until TEXT;
ALTER TABLE points_mining_trust_state ADD COLUMN burn_penalty_proposal_id TEXT;
```

### 14.3 何時開啟自動罰金

- 至少 Phase 7 上線 6 個月後 + 無重大投訴 + root multisig 投票決定
- 開啟前必須先在後台與用戶 FAQ 公告 30 天

---

## 15. Severity 最終決定（分級審核）

| severity | 審核流程 |
|---|---|
| low / medium | **雙人審核**（兩位 admin 各自 review；同意才 approve） |
| high | **root 或 security_admin + verifier**（共 2 人；不可同 user） |
| blocker | **multisig 或 2-of-3 emergency review** |
| reward ≥ 1000 | **必走 multisig**（無論 severity） |
| root 自己領 | **3-of-5 multisig**（無論 severity） |

### 15.1 雙人審核細節

- 兩位 admin 必須不同 user_id（DB CHECK）
- 兩位都不可是 reporter
- 兩位之一可以是 verifier，但 verifier 的 review 與第二位 admin 的 approve **必須是兩個獨立步驟**

### 15.2 emergency review

對 blocker 級的快速通道：

- 2-of-3 emergency_review_admin（emergency_recovery_admin + security_admin + 一位指定）
- 24h 內必須結案
- 過後自動 escalate 到 multisig

---

## 16. 資料表（最終版，整合 §1-§15）

```sql
-- 任務（admin 創建）
CREATE TABLE points_mining_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('qa','content','validator')),
    title TEXT NOT NULL,
    description TEXT,
    severity_default TEXT,
    reward_base INTEGER NOT NULL CHECK (reward_base > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','closed')),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT
);

-- Claim：與 bug_reports 透過 reference_id 連結
CREATE TABLE points_mining_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT UNIQUE NOT NULL,
    task_id TEXT REFERENCES points_mining_tasks(task_id),
    user_id INTEGER NOT NULL REFERENCES users(id),                  -- reporter
    category TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    reference_type TEXT NOT NULL,                                   -- 'bug_report' | 'video' | ...
    reference_id TEXT NOT NULL,
    severity TEXT CHECK (severity IN ('low','medium','high','blocker') OR severity IS NULL),
    evidence_json TEXT,
    formula_json TEXT,                                              -- 公式拆解
    requested_reward INTEGER,
    suggested_reward INTEGER,
    approved_reward INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','pending_next_period','approved','rejected',
                          'expired','withdrawn','duplicate','false_positive','paid')),
    verified_by INTEGER REFERENCES users(id),                       -- verifier
    second_reviewer_id INTEGER REFERENCES users(id),                -- 雙人審核之第二位
    review_note TEXT,
    risk_flags TEXT,
    client_ip_hash TEXT,
    device_fingerprint TEXT,
    account_age_days INTEGER,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    UNIQUE(reference_type, reference_id, claim_type),
    CHECK (verified_by IS NULL OR user_id != verified_by),                                    -- §4 紅線
    CHECK (second_reviewer_id IS NULL OR
           (second_reviewer_id != user_id AND second_reviewer_id != verified_by))             -- §15 雙人不重疊
);

-- Split：協作分潤
CREATE TABLE points_mining_claim_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES points_mining_claims(claim_id),
    payee_user_id INTEGER NOT NULL REFERENCES users(id),
    payee_address TEXT NOT NULL REFERENCES points_wallet_addresses(address),
    role TEXT NOT NULL CHECK (role IN ('reporter','verifier','fixer')),
    share_basis_points INTEGER NOT NULL CHECK (share_basis_points BETWEEN 1 AND 10000),
    multisig_proposal_id TEXT,                                      -- 高額自動升級用
    created_at TEXT NOT NULL
);

-- Trust score
CREATE TABLE points_mining_trust_state (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    trust_score INTEGER NOT NULL DEFAULT 50 CHECK (trust_score BETWEEN 0 AND 100),
    verified_count INTEGER NOT NULL DEFAULT 0,
    fp_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    last_fp_at TEXT,
    consecutive_fp INTEGER NOT NULL DEFAULT 0,
    suspended_until TEXT,
    burn_penalty_proposal_id TEXT,                                  -- §14 預留
    last_activity_at TEXT,
    updated_at TEXT NOT NULL
);

-- 預算狀態
CREATE TABLE points_mining_budget_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    reward_pool_address TEXT NOT NULL REFERENCES points_wallet_addresses(address),
    weekly_budget INTEGER NOT NULL CHECK (weekly_budget > 0),
    weekly_spent INTEGER NOT NULL DEFAULT 0,
    daily_cap_base INTEGER NOT NULL,
    weekly_cap_base INTEGER NOT NULL,
    max_emission_rate_pct INTEGER NOT NULL,
    qa_share_pct INTEGER NOT NULL DEFAULT 30,
    content_share_pct INTEGER NOT NULL DEFAULT 50,
    validator_share_pct INTEGER NOT NULL DEFAULT 20,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    last_solvency_state TEXT NOT NULL DEFAULT 'green',              -- green | yellow | red | suspended
    updated_at TEXT NOT NULL,
    CHECK (qa_share_pct + content_share_pct + validator_share_pct = 100)
);

-- 個人 daily / weekly 額度
CREATE TABLE points_mining_user_quota (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    period_start TEXT NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('day','week')),
    spent_amount INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, period_type, period_start)
);

-- 實際 payout
CREATE TABLE points_reward_payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payout_id TEXT UNIQUE NOT NULL,
    claim_id TEXT NOT NULL REFERENCES points_mining_claims(claim_id),
    payee_user_id INTEGER NOT NULL REFERENCES users(id),
    from_address TEXT NOT NULL,                                     -- OFFICIAL_REWARD_POOL
    to_address TEXT NOT NULL,                                       -- payee primary address
    amount INTEGER NOT NULL CHECK (amount > 0),
    ledger_event_id TEXT REFERENCES points_ledger_v2(event_id),
    block_id INTEGER REFERENCES points_chain_blocks_v2(block_id),
    multisig_proposal_id TEXT,                                      -- if reward >= 1000
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','paid','rejected','expired')),
    created_at TEXT NOT NULL,
    paid_at TEXT
);
```

---

## 17. API（最終版）

### 17.1 用戶端

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/points/mining/tasks` | 列當前 active 任務 |
| GET | `/api/points/mining/tasks/<task_id>` | 任務詳情 |
| POST | `/api/points/mining/claims` | 新建 claim（含 evidence） |
| GET | `/api/points/mining/claims/me` | 自己 claim 紀錄 |
| GET | `/api/points/mining/claims/<claim_id>` | 自己 claim 詳情（含 formula breakdown） |
| POST | `/api/points/mining/claims/<claim_id>/withdraw` | 撤回 pending |
| GET | `/api/points/mining/rewards/me` | 自己 payout 紀錄 |
| GET | `/api/points/mining/quota/me` | 今日/本週剩餘 cap（含 trust 加權結果） |
| GET | `/api/points/mining/trust/me` | trust_score + 變動歷史 |
| POST | `/api/points/mining/bug-report` | 從 trading bot audit 黃燈一鍵提（自動填欄）|

### 17.2 Admin / Root

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/admin/points/mining/claims` | 列 claims (filter status/category/severity/risk) |
| POST | `/api/admin/points/mining/claims/<claim_id>/verify` | verifier 驗證（必填 evidence） |
| POST | `/api/admin/points/mining/claims/<claim_id>/approve` | 第二位審核者 approve（雙人審核） |
| POST | `/api/admin/points/mining/claims/<claim_id>/reject` | 拒絕（含 false_positive / duplicate 標記） |
| POST | `/api/admin/points/mining/claims/<claim_id>/escalate-multisig` | reward >= 1000 自動觸發 |
| POST | `/api/admin/points/mining/tasks` | 建任務 |
| PUT | `/api/admin/points/mining/tasks/<task_id>` | 改任務 |
| GET | `/api/admin/points/mining/budget` | 預算狀態 |
| PUT | `/api/admin/points/mining/budget` | 改預算（>10% 變動須 multisig） |
| GET | `/api/admin/points/mining/trust` | 列各 user trust_score |
| POST | `/api/admin/points/mining/trust/<user_id>/adjust` | 手動調 trust（須 multisig） |
| GET | `/api/admin/points/mining/risk-flags` | 風控旗標清單 |
| POST | `/api/admin/points/mining/retroactive` | 發起 retroactive batch（必走 multisig） |

### 17.3 公開 explorer

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/points/mining/explorer/leaderboard` | 排行（匿名地址） |
| GET | `/api/points/mining/explorer/payouts` | 已 paid 列表（去敏感） |
| GET | `/api/points/mining/explorer/budget` | reward_pool / weekly_budget / solvency 燈號 |

---

## 18. Ledger v2 Event Types（補入 [POINTSCHAIN_ENGINEERING.md §4.1](POINTSCHAIN_ENGINEERING.md)）

```
'mining_claim_submitted'      # 不影響 supply
'mining_claim_approved'       # 不影響 supply（純 marker）
'mining_claim_rejected'
'mining_payout'               # 真實移轉，from=REWARD_POOL
'mining_pool_refill'          # 從 TREASURY 進 REWARD_POOL（multisig 觸發）
'mining_burn_penalty'         # multisig 提案才觸發（§14）
'mining_trust_adjusted'       # 不影響 supply
```

---

## 19. UI / UX

### 19.1 用戶端

| 元件 | 必要 |
|---|---|
| 挖礦中心首頁 | trust_score 進度條 / daily/weekly 剩餘 cap / 可參與任務 |
| 提 bug 表單 | 9 欄強制；缺項 → 預估 reward 自動降 50% 並顯示原因 |
| Claim 詳情頁 | status / **公式 breakdown 完整顯示** / 預計到帳時間 |
| Payout 紀錄 | 連 explorer 顯示 ledger event 與 chain block |
| Trust 詳情 | verified/fp/duplicate count + 規則說明 + 變動歷史 |
| 黃燈一鍵提 bug | 從 [TRADING_BOT_AUDIT.md](../TRADING_BOT_AUDIT.md) 整合 |

### 19.2 後台

| 元件 | 必要 |
|---|---|
| Claims 列表 | filter status/category/severity/risk；嚴重程度標色 |
| Claim review 頁 | evidence 全展開 / 公式拆解 / 同人歷史 / IP 重複度 / 多簽升級提示 |
| Reward Pool 儀表板 | 餘額 / 預算 / 已花 / **solvency 4 級燈號（綠/黃/紅/暫停）** |
| Trust 管理 | 列 user trust / 黃名單 / 手動調整（須 multisig）|
| Multisig 升級提示 | reward ≥ 1000 自動標「需 multisig」按鈕；signer 自動排除自己 |
| Retroactive batch builder | admin 拉清單 / 預估金額 / 提 multisig proposal |

### 19.3 Mobile RWD

所有上述頁面 8 breakpoint（420/480/560/720/860/900/1100/1320px）必過。

---

## 20. 風控規則明細

| 規則 | 觸發 | 動作 |
|---|---|---|
| 同 (reference_type, reference_id, claim_type) 重複 | DB UNIQUE | reject `duplicate` |
| reporter == verifier | DB CHECK + service check | reject + 通知 root |
| 第二審 == reporter or verifier | DB CHECK | reject 該 approve |
| 同 IP 24h 多 user | risk_flags `same_ip_24h_multi_user` | reward × 0.3 + 進 manual review |
| 同 device 24h 多 user | risk_flags `same_device_24h_multi_user` | 同上 |
| same_payment_account | risk_flags `same_payment_account` | 進 manual review |
| 新帳號 < 7 天 + 高頻 | risk_flags `new_account` + `high_frequency` | 強制 manual + 預估 × 0.5 |
| trust < 30 | service check | 強制 manual review |
| trust = 0 / suspended | service check | 直接 reject + 不可送新 claim |
| reward_pool < 1× weekly_budget | boot + nightly | 紅燈 + 暫停新 approve |
| reward_pool < pending payouts | live check | 暫停 payout execute |
| weekly_spent ≥ weekly_budget | approve 時 | 後續 approve 進 `pending_next_period` |
| 個人 daily/weekly cap 達 | approve 時 | claim → `pending_next_period` |
| 連續 5 次 FP | trust_state | suspend 7 days + trust = 30 |
| incident_lockdown | server mode | 暫停所有 payout execute（可繼續 submit/review/approve） |

---

## 21. Phase 7 出口 Gate（補入 [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md)）

### 21.1 Schema / 結構

- [ ] 6 張 mining 表 + bug_reports 升級欄全建立
- [ ] 所有 CHECK constraint 啟用（reporter≠verifier / second≠reporter,verifier / share_bp 1-10000 / status enum）
- [ ] OFFICIAL_REWARD_POOL address 存在（依賴 Phase 1）

### 21.2 公式

- [ ] base × repro × novelty × security × trust 計算與 hard cap 一致（10 case 手算）
- [ ] formula_json 內每項都記錄
- [ ] admin 試圖向上超過 hard cap → reject
- [ ] formula breakdown 在前後台都顯示

### 21.3 Reporter ≠ Verifier

- [ ] DB INSERT verified_by = user_id → IntegrityError
- [ ] API root 試 verify 自己 claim → 403
- [ ] UI verifier 下拉禁選自己
- [ ] Split 表 verifier 同 reporter user_id → reject

### 21.4 雙人審核 / Multisig

- [ ] low/medium 雙 admin 同意才 approve；同人不算
- [ ] high 須 root 或 security_admin + verifier 兩人
- [ ] blocker 走 multisig 或 2-of-3 emergency
- [ ] reward ≥ 1000 自動 escalate multisig
- [ ] root 自己領獎強制 3-of-5 multisig
- [ ] **multisig signer 自動排除自己相關 reward 的投票**（threshold = nominal；剩餘 signer 不夠 → awaiting_independent_signer 狀態）

### 21.5 Cap / Budget / Solvency

- [ ] daily_cap × trust 加權 = effective cap 正確
- [ ] reach cap → 進 pending_next_period
- [ ] reward_pool 不足 4 週 → 黃燈
- [ ] reward_pool 不足 1 週 → 紅燈
- [ ] reward_pool < pending payouts → 暫停 execute
- [ ] reward_pool 永不變負
- [ ] 不可自動 mint 補 reward_pool

### 21.6 Trust score

- [ ] verified low/medium +5；high/blocker +10
- [ ] FP -10；連續 5 次 FP → trust=30 + suspended 7 days
- [ ] suspended 期間不可送 claim
- [ ] 30 天無活動慢慢回升至 50

### 21.7 FP / Reject 流程

- [ ] FP 給 5 points 但只在格式完整 + 善意提交 + trust ≥ 30 + 還有 cap
- [ ] FP 仍計入 daily/weekly cap
- [ ] duplicate 給 10% reward
- [ ] reject 不消耗 budget

### 21.8 Retroactive

- [ ] retroactive batch 必走 multisig 3-of-5
- [ ] 一筆 batch 內所有 reference 都記錄
- [ ] explorer 顯示但不洩 user_id/IP

### 21.9 Anti-Sybil

- [ ] client_ip_hash / device_fingerprint / account_age 全記
- [ ] 同 IP/device 24h 多 user 自動 risk_flag
- [ ] same_payment_account 自動偵測
- [ ] 後台只顯示 hash 不顯示明文

### 21.10 Burn / 罰金

- [ ] **第一版自動 burn 必拒**（任何路徑）
- [ ] suspend 路徑可運作
- [ ] 罰金提案必走 multisig

### 21.11 Explorer

- [ ] 顯示 payout / category / severity / amount / from REWARD_POOL / to anonymized address
- [ ] 不顯示 user_id / IP / device
- [ ] 排行榜匿名（opt-in 才顯示暱稱）

### 21.12 Mobile / UX / docs

- [ ] 所有頁面 8 breakpoint RWD
- [ ] 失敗訊息使用者可懂
- [ ] formula breakdown 清楚
- [ ] docs / README / test scripts 同步更新

---

## 22. Release Blocker（鏈化版補強）

加入 [POINTSCHAIN_QA.md §10](POINTSCHAIN_QA.md) 的 Release Blocker 列表：

```
mining reward 公式繞過 hard cap
admin 單人 approve ≥ 1000 reward
root 自己領獎未走 multisig
signer 對自己相關 reward 仍可投票
reporter == verifier 仍可 approve
雙人審核兩人同人
reward_pool 變負
incident_lockdown 期間 payout execute
自動 burn 用戶資產
explorer 洩漏 user_id / IP / device
retroactive batch 未走 multisig
mining payout 不寫 ledger_v2 + chain_block
```

---

## 23. 文件同步狀態

本文件升級後，以下文件需同步：

- [x] [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md) — 加 Phase 7 段落（已隨此文件升級）
- [x] [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) — Phase 7 補入 §1 phase map
- [x] [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) — 加 §9 Phase 7 Gate（含 §21 全部）
- [x] [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) — action_type list 加 mining_* 5 項
- [x] [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md) — 不變（mining 不走 transfer 路徑）
- [x] [../README.md](../../README.md) — 加 mining feature 摘要
- [x] [../03_ADMIN_GUIDE.md](../03_ADMIN_GUIDE.md) — 加 mining 審核流程段
- [x] [../TRADING_BOT_AUDIT.md](../TRADING_BOT_AUDIT.md) — 黃燈整合段落

---

## 24. 最終原則

> **QA Mining 是獎勵系統，不是印鈔系統。**

對應到本文件的具體保證：

| 精神 | 保證 |
|---|---|
| 從 reward_pool 出 | 所有 payout from_address = OFFICIAL_REWARD_POOL（其餘路徑 reject） |
| 可審核 | 雙人審核 / multisig / signer 自動排除 / formula breakdown 公開 |
| 可重建 | reward_pool 餘額由 ledger_v2 mining_* event replay 重建 |
| 可上鏈 | 每筆 mining_payout 進 ledger_v2 + chain_block_v2 |
| 可在 explorer 查 | 公開 anonymous 顯示 |
| 不洩漏個資 | user_id / IP / device 永不公開 |
| 不超發 | hard cap + weekly_budget + per-user cap + solvency 守護 |
| 不繞 multisig | ≥ 1000 / root 自己領 / retroactive / burn 全強制 |
| 不打擊新人 | trust 50 起步 + FP 5 points 象徵獎 |
| 不鼓勵刷量 | trust × cap × risk_flag × manual review |
| 不自動印鈔 | reward_pool 補充必走 multisig |
| 不自動扣資產 | 第一版禁止自動 burn / 自動罰金 |

---

*Approved by root, 2026-05-04. Implementation blocked until PointsChain v2 Phase 0/1/2/4/6 complete.*
