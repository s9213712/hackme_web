# hackme_web 積分經濟系統 + 私有鏈記帳整合 Agent 指令檔 v2.0

> 目的：為 hackme_web 建立一套完整的「全站積分經濟系統」與「私有鏈式不可竄改記帳系統」。  
> 定位：這是站內積分經濟，不是公鏈代幣，不是可自由兌現的加密貨幣。  
> 核心要求：可營運、可審計、可追溯、可防竄改、可防濫用、可擴展到商城 / 雲端容量 / Server 租用 / ComfyUI 生圖 / 網頁遊戲 / 串流互動收益。

---

## 0. 給 Agent 的最高指令

你要在 hackme_web 中設計並實作一套完整系統：

```text
Points Economy System
+
Private Points Chain Ledger
+
Risk & Anti-abuse System
+
Admin / Root Audit System
+
User Wallet UI
```

你必須遵守：

```text
1. 積分系統與違規計點系統完全分離。
2. 所有積分變動只能透過 PointsLedgerService。
3. 所有積分變動都必須寫入 append-only ledger。
4. points_wallet 只是餘額快照，不是最終真相來源。
5. 最終真相來源是 points_ledger + points_chain_blocks。
6. 不得直接 UPDATE wallet 來改點數。
7. 不得 DELETE 或 UPDATE 歷史 ledger。
8. 錯誤修正必須用 reversal transaction。
9. 使用者隱私不得被寫進鏈上資料。
10. 任何 admin/root 操作都要 audit log。
```

---

# Part A — 系統目標與範圍

## A1. 系統總目標

建立一套全站通用積分經濟：

```text
使用者行為 → 賺取積分
積分 → 消費平台服務
消費 → 推動內容 / 資源 / 商城 / AI / 遊戲活躍
活躍 → 再產生積分需求
```

同時建立私有鏈式記帳：

```text
每筆交易可回溯
每筆交易不可靜默竄改
每批交易可封成 block
每筆交易可提供 proof
root 可驗證全鏈完整性
```

---

## A2. 功能範圍

本系統包含：

```text
1. soft_points / hard_points 雙幣制
2. wallet 餘額快照
3. ledger append-only 交易紀錄
4. ledger hash chain
5. block + Merkle tree 私有鏈封存
6. user wallet UI
7. admin 補償 / 扣回 / 爭議處理
8. root 封塊 / 驗證 / 錨定
9. 風控與防洗點
10. 經濟規則引擎
11. 報表與稽核
12. 測試與文件
```

---

## A3. 明確不做的事情

不得把本系統做成：

```text
1. 公鏈代幣
2. 可自由兌現的虛擬貨幣
3. 可匿名轉移資產的系統
4. 繞過平台審計的私下交易系統
5. 與違規點共用的懲罰分數系統
```

---

# Part B — 積分經濟模型

## B1. 雙幣制

必須建立兩種積分：

```text
soft_points：免費 / 互動 / 任務 / 活動獲得
hard_points：付費 / 高價值 / 管理員核發 / 商業用途
```

### soft_points 用途

```text
發文成本
留言互動
部分 AI 生圖
遊戲基礎虛寶
論壇功能
活動兌換
低價值商城功能
```

### hard_points 用途

```text
雲端容量
Server 租用
高階 AI 生圖
商城高價值商品
遊戲高價值虛寶
付費服務
```

---

## B2. 獲得積分來源

可獲得 soft_points 的行為：

```text
1. 發文通過基本品質檢查
2. 留言通過基本品質檢查
3. 被其他使用者按讚
4. 文章互動率達標
5. 有效 bug 回報
6. 網頁遊戲任務
7. 串流平台互動收益
8. 活動任務
9. 商城賣東西所得
10. 管理員補償
```

可獲得 hard_points 的行為：

```text
1. 付費儲值
2. root/admin 特別核發
3. 高價值 bug bounty
4. 商城結算後的高價值收益
5. 活動獎勵
```

---

## B3. 消費積分用途

可消費積分的項目：

```text
1. 發文成本，防止洗版
2. 購買雲端硬碟容量
3. ComfyUI 生圖服務
4. Server / GPU / 資源租用
5. 商城買東西
6. 網頁遊戲虛寶
7. 高階功能解鎖
8. 串流平台加值功能
9. API 使用額度
```

---

## B4. 經濟閉環

設計目標：

```text
內容創作 → 互動 → 賺點 → 消費 → 服務體驗提升 → 更多創作
```

範例：

```text
使用者發好文章
→ 被按讚與留言
→ 獲得 soft_points
→ 用 points 生圖 / 買容量 / 買虛寶
→ 產生新內容
→ 帶來更多互動
```

---

## B5. 防通膨設計

必須加入：

```text
1. 每日個人得點上限
2. 每日全站得點上限
3. 高風險行為延遲結算
4. 互刷行為收益遞減
5. 新帳號收益限制
6. 低品質內容不給點
7. 任務獎勵可動態調整
8. 消費回收機制
```

---

# Part C — 資料庫設計

## C1. points_wallet

用途：儲存目前餘額快照。

```sql
CREATE TABLE points_wallet (
  user_id BIGINT PRIMARY KEY,

  soft_points BIGINT NOT NULL DEFAULT 0,
  hard_points BIGINT NOT NULL DEFAULT 0,

  frozen_soft_points BIGINT NOT NULL DEFAULT 0,
  frozen_hard_points BIGINT NOT NULL DEFAULT 0,

  total_soft_earned BIGINT NOT NULL DEFAULT 0,
  total_soft_spent BIGINT NOT NULL DEFAULT 0,
  total_hard_earned BIGINT NOT NULL DEFAULT 0,
  total_hard_spent BIGINT NOT NULL DEFAULT 0,

  risk_level VARCHAR(30) NOT NULL DEFAULT 'normal',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (soft_points >= 0),
  CHECK (hard_points >= 0),
  CHECK (frozen_soft_points >= 0),
  CHECK (frozen_hard_points >= 0)
);
```

---

## C2. points_ledger

用途：每筆積分異動的 append-only 交易紀錄。

```sql
CREATE TABLE points_ledger (
  id BIGSERIAL PRIMARY KEY,
  ledger_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,
  public_account_id CHAR(64) NOT NULL,

  currency_type VARCHAR(20) NOT NULL,
  direction VARCHAR(20) NOT NULL,
  amount BIGINT NOT NULL,

  balance_before BIGINT NOT NULL,
  balance_after BIGINT NOT NULL,

  action_type VARCHAR(100) NOT NULL,
  reference_type VARCHAR(100),
  reference_id VARCHAR(160),
  idempotency_key VARCHAR(160),

  reason TEXT,

  public_metadata_json TEXT,
  private_metadata_json TEXT,
  sensitive_metadata_encrypted TEXT,

  metadata_hash CHAR(64) NOT NULL,

  previous_ledger_hash CHAR(64),
  ledger_hash CHAR(64) NOT NULL UNIQUE,

  chain_block_id BIGINT,

  risk_flag VARCHAR(50) DEFAULT 'none',
  risk_score INT NOT NULL DEFAULT 0,

  created_by BIGINT,
  created_by_role VARCHAR(50),

  status VARCHAR(30) NOT NULL DEFAULT 'confirmed',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (amount > 0),
  CHECK (currency_type IN ('soft', 'hard')),
  CHECK (direction IN ('credit', 'debit', 'freeze', 'unfreeze', 'reverse', 'transfer_in', 'transfer_out')),
  CHECK (status IN ('pending', 'confirmed', 'reversed', 'disputed', 'frozen'))
);
```

必要限制：

```text
1. points_ledger 不可 UPDATE 核心欄位。
2. points_ledger 不可 DELETE。
3. action_type + reference_id + idempotency_key 必須可防止重複入帳。
4. 每筆 ledger 必須包含 ledger_hash。
5. 每筆 ledger 必須串 previous_ledger_hash。
```

---

## C3. points_rules

用途：動態定義加點 / 扣點規則。

```sql
CREATE TABLE points_rules (
  id BIGSERIAL PRIMARY KEY,

  action_type VARCHAR(100) NOT NULL UNIQUE,
  direction VARCHAR(20) NOT NULL,
  currency_type VARCHAR(20) NOT NULL,

  base_amount BIGINT NOT NULL,
  min_amount BIGINT DEFAULT 0,
  max_amount BIGINT,

  daily_user_limit BIGINT,
  daily_global_limit BIGINT,
  cooldown_seconds INT DEFAULT 0,

  requires_quality_check BOOLEAN NOT NULL DEFAULT FALSE,
  requires_admin_review BOOLEAN NOT NULL DEFAULT FALSE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,

  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (direction IN ('credit', 'debit')),
  CHECK (currency_type IN ('soft', 'hard'))
);
```

---

## C4. points_chain_blocks

用途：私有鏈 block。

```sql
CREATE TABLE points_chain_blocks (
  id BIGSERIAL PRIMARY KEY,

  block_number BIGINT NOT NULL UNIQUE,

  previous_block_hash CHAR(64),
  merkle_root CHAR(64) NOT NULL,
  block_hash CHAR(64) NOT NULL UNIQUE,

  ledger_count INT NOT NULL,
  first_ledger_id BIGINT NOT NULL,
  last_ledger_id BIGINT NOT NULL,

  sealed_by BIGINT,
  sealed_by_node VARCHAR(120),
  sealed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  seal_status VARCHAR(30) NOT NULL DEFAULT 'sealed',

  anchor_status VARCHAR(30) NOT NULL DEFAULT 'local_only',
  external_anchor_ref TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## C5. points_chain_block_signatures

Phase 2 多節點簽章使用。

```sql
CREATE TABLE points_chain_block_signatures (
  id BIGSERIAL PRIMARY KEY,

  block_id BIGINT NOT NULL,
  node_id VARCHAR(120) NOT NULL,

  signature_algorithm VARCHAR(50) NOT NULL,
  public_key_fingerprint CHAR(64) NOT NULL,
  signature TEXT NOT NULL,

  signed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (block_id, node_id)
);
```

---

## C6. points_chain_nodes

```sql
CREATE TABLE points_chain_nodes (
  id BIGSERIAL PRIMARY KEY,

  node_id VARCHAR(120) NOT NULL UNIQUE,
  node_name VARCHAR(120) NOT NULL,

  node_type VARCHAR(50) NOT NULL,
  public_key TEXT NOT NULL,
  public_key_fingerprint CHAR(64) NOT NULL,

  enabled BOOLEAN NOT NULL DEFAULT TRUE,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

node_type：

```text
root
sealer
auditor
backup
reporter
```

---

## C7. points_chain_audit_logs

```sql
CREATE TABLE points_chain_audit_logs (
  id BIGSERIAL PRIMARY KEY,

  event_type VARCHAR(100) NOT NULL,
  severity VARCHAR(20) NOT NULL,

  actor_user_id BIGINT,
  actor_role VARCHAR(50),

  target_user_id BIGINT,
  related_ledger_id BIGINT,
  related_block_id BIGINT,

  message TEXT NOT NULL,
  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## C8. points_disputes

```sql
CREATE TABLE points_disputes (
  id BIGSERIAL PRIMARY KEY,

  ledger_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,

  status VARCHAR(30) NOT NULL DEFAULT 'open',
  reason TEXT NOT NULL,
  resolution TEXT,

  resolved_by BIGINT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TIMESTAMP
);
```

---

## C9. points_economy_daily_stats

用途：防通膨與報表。

```sql
CREATE TABLE points_economy_daily_stats (
  id BIGSERIAL PRIMARY KEY,

  stat_date DATE NOT NULL UNIQUE,

  soft_issued BIGINT NOT NULL DEFAULT 0,
  soft_spent BIGINT NOT NULL DEFAULT 0,
  soft_burned BIGINT NOT NULL DEFAULT 0,

  hard_issued BIGINT NOT NULL DEFAULT 0,
  hard_spent BIGINT NOT NULL DEFAULT 0,
  hard_burned BIGINT NOT NULL DEFAULT 0,

  active_users INT NOT NULL DEFAULT 0,
  suspicious_transactions INT NOT NULL DEFAULT 0,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

# Part D — Hash / Chain / Merkle 設計

## D1. Canonical JSON

所有 hash payload 必須 canonicalize。

要求：

```text
1. 欄位順序固定
2. null 表示固定
3. timestamp 統一 UTC ISO-8601
4. 數字不可用浮點
5. metadata 先 hash
6. 不放入 email / ip / token / cookie
```

---

## D2. public_account_id

不得對外顯示連續 user_id。

```text
public_account_id = HMAC_SHA256(server_secret, user_id)
```

---

## D3. ledger_hash payload

```json
{
  "ledger_uuid": "...",
  "public_account_id": "...",
  "currency_type": "soft",
  "direction": "credit",
  "amount": 100,
  "balance_before": 50,
  "balance_after": 150,
  "action_type": "forum_post_reward",
  "reference_type": "post",
  "reference_id": "123",
  "metadata_hash": "...",
  "previous_ledger_hash": "...",
  "created_at": "2026-04-28T00:00:00Z"
}
```

計算：

```text
ledger_hash = SHA256(canonical_json(payload))
```

---

## D4. metadata_hash

```text
metadata_hash = SHA256(canonical_json({
  public_metadata,
  private_metadata_digest,
  sensitive_metadata_ciphertext_digest
}))
```

---

## D5. Merkle Tree

規則：

```text
1. ledger_hash 依 ledger id 升序排序。
2. 若數量為奇數，複製最後一個 hash。
3. parent = SHA256(left + right)。
4. 最終 root = merkle_root。
```

---

## D6. block_hash

```text
block_hash = SHA256(canonical_json({
  block_number,
  previous_block_hash,
  merkle_root,
  ledger_count,
  first_ledger_id,
  last_ledger_id,
  sealed_at
}))
```

---

# Part E — 核心 Service

## E1. PointsLedgerService

必須實作：

```text
credit(user_id, currency_type, amount, action_type, reference, metadata)
debit(user_id, currency_type, amount, action_type, reference, metadata)
freeze(user_id, currency_type, amount, reason)
unfreeze(user_id, currency_type, amount, reason)
reverse(ledger_uuid, reason)
transfer(from_user_id, to_user_id, amount, currency_type, reason)
get_balance(user_id)
get_ledger(user_id)
replay_wallet(user_id)
```

強制要求：

```text
1. 所有積分變動只能走此 service。
2. wallet + ledger 必須在同一個 DB transaction。
3. wallet row 必須 SELECT FOR UPDATE。
4. 餘額不足必須 rollback。
5. idempotency_key 重複時不得重複入帳。
6. 每筆交易必須寫 audit log。
```

---

## E2. PointsEconomyService

負責經濟規則。

必須實作：

```text
apply_rule(action_type, user_id, reference)
calculate_reward(action_type, user_id, context)
calculate_cost(action_type, user_id, context)
check_daily_limit(user_id, action_type)
check_cooldown(user_id, action_type)
check_quality_gate(action_type, content)
```

---

## E3. PointsRiskService

負責防濫用。

必須實作：

```text
check_before_credit(user_id, action_type, context)
check_before_debit(user_id, action_type, context)
detect_like_farming()
detect_multi_account_abuse()
detect_marketplace_wash_trade()
detect_game_score_anomaly()
detect_bug_report_duplication()
freeze_suspicious_points(user_id, amount, reason)
mark_risk_flag(ledger_uuid, risk_flag)
```

---

## E4. PointsChainService

必須實作：

```text
seal_pending_ledgers(limit)
verify_ledger(ledger_uuid)
verify_block(block_number)
verify_chain()
get_merkle_proof(ledger_uuid)
anchor_daily_root()
rebuild_wallet_from_ledger(user_id)
generate_audit_report()
```

---

# Part F — 交易流程

## F1. 加點 credit

```text
BEGIN TRANSACTION

1. lock points_wallet row FOR UPDATE
2. run PointsRiskService.check_before_credit
3. run PointsEconomyService rule limit
4. read balance_before
5. calculate balance_after
6. find previous_ledger_hash
7. build metadata_hash
8. build ledger_hash
9. INSERT points_ledger
10. UPDATE points_wallet
11. UPDATE daily stats
12. INSERT audit log

COMMIT
```

---

## F2. 扣點 debit

```text
BEGIN TRANSACTION

1. lock points_wallet row FOR UPDATE
2. run PointsRiskService.check_before_debit
3. check available balance
4. read balance_before
5. calculate balance_after
6. find previous_ledger_hash
7. build metadata_hash
8. build ledger_hash
9. INSERT points_ledger
10. UPDATE points_wallet
11. UPDATE daily stats
12. INSERT audit log

COMMIT
```

---

## F3. 凍結 freeze

```text
available_points -= amount
frozen_points += amount
```

必須寫 ledger。

---

## F4. 解凍 unfreeze

```text
frozen_points -= amount
available_points += amount
```

必須寫 ledger。

---

## F5. 沖正 reverse

禁止修改原交易。

範例：

```text
原交易：credit +100
沖正：debit 100，reference_type = reversal，reference_id = 原 ledger_uuid
```

或：

```text
原交易：debit 100
沖正：credit 100，reference_type = reversal，reference_id = 原 ledger_uuid
```

---

# Part G — 封塊流程

## G1. 觸發條件

```text
每 100 筆未封 ledger
或每 5 分鐘
或 root 手動封塊
```

---

## G2. seal_block

```text
BEGIN TRANSACTION

1. select unsealed ledgers ORDER BY id ASC LIMIT 100 FOR UPDATE
2. ensure ledger_hash valid
3. build merkle tree
4. find previous block hash
5. calculate block_hash
6. insert points_chain_blocks
7. update selected points_ledger.chain_block_id
8. insert audit log
9. optional sign block hash

COMMIT
```

---

## G3. Genesis Block

```text
block_number = 0
previous_block_hash = null
merkle_root = SHA256("GENESIS")
block_hash = SHA256(canonical_json(genesis_payload))
```

---

# Part H — API 設計

## H1. User API

```http
GET /api/points/balance
GET /api/points/ledger
GET /api/points/ledger/{ledger_uuid}
GET /api/points/ledger/{ledger_uuid}/proof
POST /api/points/ledger/{ledger_uuid}/verify
POST /api/points/ledger/{ledger_uuid}/dispute
```

---

## H2. Economy API

```http
GET /api/points/rules
GET /api/points/earning-methods
GET /api/points/spending-methods
POST /api/points/spend
```

前端不得傳入實際扣點數值，只能傳：

```text
action_type
reference_id
idempotency_key
```

實際 amount 必須由後端根據 points_rules 計算。

---

## H3. Admin API

```http
GET /api/admin/points/users/{user_id}/balance
GET /api/admin/points/users/{user_id}/ledger
POST /api/admin/points/credit
POST /api/admin/points/debit
POST /api/admin/points/freeze
POST /api/admin/points/unfreeze
GET /api/admin/points/disputes
POST /api/admin/points/disputes/{dispute_id}/resolve
GET /api/admin/points/risk-flags
```

---

## H4. Root API

```http
POST /api/root/points-chain/seal
POST /api/root/points-chain/verify
GET /api/root/points-chain/status
GET /api/root/points-chain/blocks
GET /api/root/points-chain/blocks/{block_number}
POST /api/root/points-chain/anchor
POST /api/root/points-chain/nodes
GET /api/root/points-economy/daily-stats
```

---

# Part I — UI 要求

## I1. User UI

新增：

```text
1. 我的錢包
2. soft_points / hard_points 顯示
3. frozen points 顯示
4. 交易紀錄
5. 交易 proof
6. 爭議申請
7. 積分獲得方式
8. 積分消費方式
```

每筆交易顯示：

```text
時間
類型
金額
餘額變化
來源
狀態
proof 按鈕
dispute 按鈕
```

---

## I2. Admin UI

新增：

```text
1. 用戶積分查詢
2. 交易查詢
3. 補償加點
4. 小額扣回
5. 凍結 / 解凍
6. 爭議處理
7. 風控標記
8. 異常交易列表
```

---

## I3. Root UI

新增：

```text
1. Points Chain 狀態
2. 最新 block
3. 未封 ledger 數量
4. 手動封塊
5. 全鏈驗證
6. 節點管理
7. 每日 anchor
8. 經濟統計報表
9. 通膨指標
10. 異常報告
```

---

# Part J — 風控與防濫用

## J1. 必做風控

```text
1. 每日得點上限
2. 每小時得點上限
3. 行為 cooldown
4. 互刷 likes 偵測
5. 多帳號互動偵測
6. 低品質內容不給點
7. 新帳號限制
8. 高額交易延遲結算
9. 商城洗交易偵測
10. 遊戲異常得分偵測
11. bug bounty 重複回報偵測
```

---

## J2. 風控處置

```text
1. 降低獎勵
2. 暫緩結算
3. 凍結可疑積分
4. 標記交易
5. 要求 admin review
6. 高風險交 root review
```

---

## J3. 風控不可做

```text
1. 不可直接刪除積分
2. 不可靜默改 ledger
3. 不可把違規點與積分混用
4. 不可無 audit log 凍結
```

---

# Part K — 權限設計

## K1. User

可做：

```text
查自己餘額
查自己交易
取得自己的 proof
提出爭議
使用積分消費
```

不可做：

```text
看別人 ledger
看 sensitive metadata
封塊
驗證全鏈
手動加扣點
```

---

## K2. Admin

可做：

```text
查詢用戶積分
處理爭議
小額補償
小額扣回
凍結可疑積分
查看風控標記
```

限制：

```text
高額加扣點需要 root approve
不得直接改 wallet
不得刪改 ledger
```

---

## K3. Root

可做：

```text
全鏈驗證
封塊
管理 chain node
每日 anchor
核准高額加扣點
查看完整 audit
```

限制：

```text
root 也不能靜默改帳
root 操作也必須寫 audit log
```

---

# Part L — CLI / Management Commands

請實作：

```bash
python manage.py points-chain seal
python manage.py points-chain verify
python manage.py points-chain verify-ledger <ledger_uuid>
python manage.py points-chain verify-block <block_number>
python manage.py points-chain proof <ledger_uuid>
python manage.py points-chain anchor-daily
python manage.py points-chain rebuild-wallet --dry-run
python manage.py points-chain audit-report
python manage.py points-economy daily-stats
python manage.py points-economy detect-abuse
```

若 hackme_web 不是 Python，請用現有技術棧實作等效命令。

---

# Part M — 測試要求

## M1. Ledger 測試

```text
加點成功
扣點成功
餘額不足扣點失敗
凍結成功
解凍成功
沖正成功
重複 reference_id 不會重複入帳
ledger_hash 可重算
previous_ledger_hash 正確
wallet 可由 ledger replay 重建
```

---

## M2. Chain 測試

```text
封塊成功
merkle_root 正確
block_hash 正確
已封 ledger 不可重複封塊
漏 ledger 會 verify 失敗
竄改 ledger 後 verify 失敗
竄改 block 後 verify 失敗
proof 可驗證交易存在
```

---

## M3. Economy 測試

```text
每日上限正確
cooldown 正確
不同 action_type 規則正確
soft/hard points 分離
低品質內容不給點
消費扣點正確
退款沖正正確
```

---

## M4. Concurrency 測試

```text
同一用戶同時扣點不會變負數
同時加點不會 lost update
同時消費與退款不會錯帳
seal block 時不會漏封或重封
idempotency_key 防重放有效
```

---

## M5. Permission 測試

```text
user 不能看別人 ledger
user 不能封塊
admin 不能直接改 wallet
admin 高額加扣點需要 root
root 操作必須留 audit log
```

---

## M6. Privacy 測試

```text
proof 不含個資
API 不洩漏 email
API 不洩漏 IP
public_account_id 不可反推 user_id
sensitive metadata 有加密
一般 user 看不到 private metadata
```

---

## M7. Abuse 測試

```text
互刷 likes 被降收益
多帳號異常被標記
遊戲異常得分被標記
商城洗交易被標記
bug bounty 重複回報不重複給點
```

---

# Part N — Migration 策略

若已有舊積分資料：

```text
1. backup database
2. 建立新資料表
3. 匯入舊 wallet
4. 產生 migration ledger
5. 建立 genesis block
6. 封存歷史 ledger
7. verify_chain
8. replay wallet 比對餘額
9. 產生 migration report
```

若 wallet 與 ledger 對不起來：

```text
不得直接修改歷史 ledger
產生 reconciliation report
root 人工確認
用 correction ledger 修正
```

---

# Part O — 文件要求

必須新增或更新：

```text
README.md
SECURITY.md
docs/points_economy_design.md
docs/points_chain_private_blockchain_design.md
docs/points_chain_operations_runbook.md
docs/points_chain_threat_model.md
docs/points_api_reference.md
docs/points_admin_manual.md
docs/points_user_manual.md
```

---

# Part P — 實作階段

## Phase 1 — Ledger MVP

完成：

```text
points_wallet
points_ledger
ledger_hash
previous_ledger_hash
credit/debit
balance API
ledger API
audit log
基本測試
```

---

## Phase 2 — Economy Rules

完成：

```text
points_rules
PointsEconomyService
每日上限
cooldown
soft/hard 分離
發文 / 留言 / 按讚 / 消費基本規則
```

---

## Phase 3 — Private Chain

完成：

```text
points_chain_blocks
Merkle tree
block_hash
seal block
verify block
verify chain
proof API
```

---

## Phase 4 — Risk System

完成：

```text
PointsRiskService
互刷偵測
多帳號偵測
高額交易 review
freeze/unfreeze
dispute system
```

---

## Phase 5 — Admin / Root UI

完成：

```text
admin ledger search
admin credit/debit/freeze
admin dispute review
root chain status
root verify
root seal
root economy stats
```

---

## Phase 6 — Platform Integrations

接入：

```text
發文成本
留言獎勵
按讚獎勵
bug bounty
商城
雲端容量
ComfyUI 生圖
server 租用
網頁遊戲
串流平台
```

---

## Phase 7 — Anchor / Multi-node

完成：

```text
daily anchor
block signatures
points_chain_nodes
M-of-N signatures
external anchor report
```

---

# Part Q — 禁止事項

嚴禁：

```text
1. 直接 UPDATE points_wallet 增減點數。
2. DELETE points_ledger。
3. UPDATE points_ledger 核心欄位。
4. 讓前端傳 points amount。
5. 未寫 ledger 就改餘額。
6. 把 email / IP / token / cookie 放進 ledger hash。
7. 把積分做成公開加密貨幣。
8. 把違規點與積分共用。
9. 沒 audit log 的 admin/root 操作。
10. 沒測試就交付。
```

---

# Part R — 最終交付項目

Agent 必須交付：

```text
1. database migrations
2. PointsLedgerService
3. PointsEconomyService
4. PointsRiskService
5. PointsChainService
6. MerkleTree utility
7. Hash canonicalization utility
8. API routes
9. user wallet UI
10. admin points UI
11. root chain UI
12. management commands
13. unit tests
14. integration tests
15. concurrency tests
16. privacy tests
17. abuse tests
18. README update
19. SECURITY.md update
20. docs/*
21. migration report if applicable
```

---

# Part S — 完成後回報格式

請用以下格式回報：

```text
# hackme_web Points Economy + Private Chain 完成摘要

## 已完成
-

## 新增資料表
-

## 新增 Service
-

## 新增 API
-

## 新增 UI
-

## Chain 驗證結果
-

## Economy 規則
-

## 風控機制
-

## 測試結果
-

## 安全限制
-

## 尚未完成
-

## 需要 root 人工確認
-

## 建議下一階段
-
```

---

# Part T — 最高優先級提醒

此系統的核心不是「炫技上鏈」，而是：

```text
每一筆積分都有來源
每一筆積分都能追溯
每一筆積分都不能靜默竄改
每一筆積分都能被驗證
用戶隱私不被公開
平台仍保留營運、退款、凍結、爭議處理能力
```

請以此為最高設計原則。
