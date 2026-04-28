# hackme_web 私有鏈積分記帳系統 Agent 指令檔 v1.0

> 目標：在 hackme_web 建立一套「私有鏈式 Points Chain Ledger」，用於支撐全站積分經濟系統。  
> 定位：這不是公開加密貨幣，也不是可自由兌現代幣，而是站內積分的私有鏈記帳、稽核、追溯與防竄改系統。

---

## 0. 嚴格定位

本系統要做的是：

```text
站內積分私有鏈
Append-only ledger
Hash chain
Block chain
Merkle tree
可驗證交易證明
可稽核封塊
可隱私保護
可爭議處理
可營運管理
```

本系統**不是**：

```text
公鏈代幣
可自由交易的加密貨幣
證券型 token
支付工具
匿名洗錢工具
繞過平台管理的外部資產
```

---

## 1. 核心目標

在 hackme_web 內建立一套積分記帳私有鏈，滿足：

1. 每筆積分異動可追溯。
2. 每筆交易不可直接修改或刪除。
3. 修改歷史帳本會被驗證機制發現。
4. 用戶可查自己的積分交易紀錄。
5. 用戶可取得單筆交易 proof。
6. root 可驗證全鏈完整性。
7. admin 可處理爭議，但不能直接改帳。
8. 所有補償、退款、沖正都必須新增 reversal transaction。
9. 隱私資料不得上鏈。
10. 未來可把每日 block root 錨定到外部公開位置。

---

## 2. 建議系統名稱

請使用以下名稱之一：

```text
Points Chain Ledger
hackme_web PointsChain
Tamper-evident Points Ledger
Private Points Blockchain
```

不建議在 UI 上稱為「加密貨幣」或「Token」。

---

## 3. 架構總覽

```text
User Action
  ↓
Points Economy Service
  ↓
PointsLedgerService
  ↓
points_ledger append-only transaction
  ↓
PointsChainService
  ↓
points_chain_blocks
  ↓
Merkle Proof / Chain Verification
  ↓
Optional External Anchor
```

---

## 4. 核心概念

### 4.1 Wallet

Wallet 是目前餘額快照。

```text
wallet = current balance cache
```

Wallet 可以被更新，但必須由 ledger transaction 驅動，不能直接手動改。

### 4.2 Ledger

Ledger 是每筆積分異動。

```text
ledger = append-only transaction record
```

任何加點、扣點、退款、凍結、解凍，都要寫入 ledger。

### 4.3 Block

Block 是一批 ledger 的封存結果。

```text
block = batch of ledger hashes
```

每個 block 都保存：

```text
previous_block_hash
merkle_root
block_hash
first_ledger_id
last_ledger_id
ledger_count
```

### 4.4 Private Chain

這是私有鏈，由 hackme_web 控制節點與權限。

MVP 可先做單節點封塊，後續再擴展多節點簽章。

---

## 5. 私有鏈模式選擇

### Phase 1：單節點私有鏈

適合 MVP。

```text
1 個主資料庫
1 個 system sealer
root 可手動 verify
每 100 筆或每 5 分鐘封塊
```

優點：

```text
簡單
可快速落地
不影響現有系統
容易測試
```

### Phase 2：多節點簽章私有鏈

適合平台成長後。

```text
root node
audit node
backup node
report node
```

每個 block 需要至少 M-of-N 簽章。

範例：

```text
3 個節點中至少 2 個節點簽章才可封塊
```

### Phase 3：外部錨定

每日把最後 block hash 發佈到：

```text
GitHub commit
公開 transparency page
第三方 timestamp service
公鏈 transaction memo
```

只公開 hash，不公開交易內容。

---

## 6. 資料表設計

### 6.1 points_wallet

```sql
CREATE TABLE points_wallet (
  user_id BIGINT PRIMARY KEY,

  soft_points BIGINT NOT NULL DEFAULT 0,
  hard_points BIGINT NOT NULL DEFAULT 0,

  frozen_soft_points BIGINT NOT NULL DEFAULT 0,
  frozen_hard_points BIGINT NOT NULL DEFAULT 0,

  total_earned BIGINT NOT NULL DEFAULT 0,
  total_spent BIGINT NOT NULL DEFAULT 0,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (soft_points >= 0),
  CHECK (hard_points >= 0),
  CHECK (frozen_soft_points >= 0),
  CHECK (frozen_hard_points >= 0)
);
```

---

### 6.2 points_ledger

```sql
CREATE TABLE points_ledger (
  id BIGSERIAL PRIMARY KEY,
  ledger_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,

  currency_type VARCHAR(20) NOT NULL,
  direction VARCHAR(20) NOT NULL,
  amount BIGINT NOT NULL,

  balance_before BIGINT NOT NULL,
  balance_after BIGINT NOT NULL,

  action_type VARCHAR(80) NOT NULL,
  reference_type VARCHAR(80),
  reference_id VARCHAR(120),

  reason TEXT,

  public_metadata_json TEXT,
  private_metadata_json TEXT,
  sensitive_metadata_encrypted TEXT,

  metadata_hash CHAR(64) NOT NULL,

  previous_ledger_hash CHAR(64),
  ledger_hash CHAR(64) NOT NULL UNIQUE,

  chain_block_id BIGINT,

  created_by BIGINT,
  created_by_role VARCHAR(50),

  status VARCHAR(30) NOT NULL DEFAULT 'confirmed',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (amount > 0),
  CHECK (direction IN ('credit', 'debit', 'freeze', 'unfreeze', 'reverse')),
  CHECK (currency_type IN ('soft', 'hard')),
  CHECK (status IN ('pending', 'confirmed', 'reversed', 'disputed'))
);
```

要求：

```text
points_ledger 不允許 UPDATE 歷史核心欄位
points_ledger 不允許 DELETE
修正錯誤只能新增 reversal ledger
```

---

### 6.3 points_chain_blocks

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

### 6.4 points_chain_block_signatures

Phase 2 多節點簽章用。

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

### 6.5 points_chain_nodes

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

### 6.6 points_chain_audit_logs

```sql
CREATE TABLE points_chain_audit_logs (
  id BIGSERIAL PRIMARY KEY,

  event_type VARCHAR(80) NOT NULL,
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

### 6.7 points_disputes

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

## 7. Hash 設計

### 7.1 Canonical JSON

所有 hash payload 必須使用 canonical JSON：

要求：

```text
欄位順序固定
null 表示固定
timestamp 統一 UTC ISO-8601
數字不可使用浮點
字串不可有不穩定空白
metadata 先 hash 再放入 ledger hash
```

---

### 7.2 ledger_hash payload

```json
{
  "ledger_uuid": "...",
  "user_id_digest": "...",
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

注意：

```text
不要把 email、ip、cookie、token、真實姓名放入 hash payload
user_id 建議使用 HMAC 後的 digest
```

---

### 7.3 metadata_hash

```text
metadata_hash = SHA256(canonical_json(public_metadata + private_metadata + sensitive_metadata_ciphertext_digest))
```

---

### 7.4 block_hash

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

## 8. Merkle Tree

### 8.1 輸入

```text
ledger_hash list
```

### 8.2 規則

```text
依 ledger id 升序排序
若節點數為奇數，最後一個 hash 複製一次
父節點 = SHA256(left + right)
最終 root = merkle_root
```

### 8.3 Proof

單筆交易 proof 回傳：

```json
{
  "ledger_uuid": "...",
  "ledger_hash": "...",
  "block_number": 123,
  "merkle_root": "...",
  "merkle_path": [
    {
      "position": "left",
      "hash": "..."
    },
    {
      "position": "right",
      "hash": "..."
    }
  ],
  "block_hash": "..."
}
```

---

## 9. 交易流程

### 9.1 加點 credit

```text
BEGIN TRANSACTION

1. lock points_wallet row FOR UPDATE
2. read balance_before
3. calculate balance_after
4. find previous_ledger_hash
5. build metadata_hash
6. build ledger_hash
7. INSERT points_ledger
8. UPDATE points_wallet
9. INSERT points_chain_audit_logs

COMMIT
```

---

### 9.2 扣點 debit

```text
BEGIN TRANSACTION

1. lock points_wallet row FOR UPDATE
2. check available balance
3. read balance_before
4. calculate balance_after
5. find previous_ledger_hash
6. build metadata_hash
7. build ledger_hash
8. INSERT points_ledger
9. UPDATE points_wallet
10. INSERT audit log

COMMIT
```

若餘額不足：

```text
rollback
return insufficient_balance
```

---

### 9.3 凍結 freeze

```text
available_points -= amount
frozen_points += amount
```

也要寫 ledger。

---

### 9.4 解凍 unfreeze

```text
frozen_points -= amount
available_points += amount
```

也要寫 ledger。

---

### 9.5 沖正 reverse

禁止修改原交易。

正確做法：

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

## 10. 封塊流程

### 10.1 觸發條件

```text
每 100 筆未封 ledger
或每 5 分鐘
或 root 手動封塊
```

---

### 10.2 seal_block 流程

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
9. optional: sign block hash

COMMIT
```

---

### 10.3 不可重複封塊

```text
chain_block_id IS NULL 的 ledger 才能封塊
```

已封 ledger 不可重新封入其他 block。

---

## 11. 共識設計

### MVP：單節點 sealed-by-system

```text
system sealer 產生 block
root 可 verify
admin 只能查看
```

### Phase 2：M-of-N 簽章

設定：

```yaml
points_chain:
  consensus:
    mode: "multi_signature"
    required_signatures: 2
    nodes:
      - root-node
      - audit-node
      - backup-node
```

流程：

```text
1. sealer node 產生候選 block
2. auditor node 重新計算 merkle_root
3. backup node 重新計算 block_hash
4. 至少 2 個節點簽章
5. block status = sealed
```

---

## 12. API 設計

### 12.1 User API

#### 查詢餘額

```http
GET /api/points/balance
```

#### 查詢自己的 ledger

```http
GET /api/points/ledger
```

#### 查詢交易 proof

```http
GET /api/points/ledger/{ledger_uuid}/proof
```

#### 驗證自己的交易

```http
POST /api/points/ledger/{ledger_uuid}/verify
```

#### 提出爭議

```http
POST /api/points/ledger/{ledger_uuid}/dispute
```

---

### 12.2 Admin API

#### 查詢用戶積分交易

```http
GET /api/admin/points/users/{user_id}/ledger
```

#### 小額補償加點

```http
POST /api/admin/points/credit
```

限制：

```text
必須 reason
必須 audit log
超過門檻需 root approve
```

#### 小額扣回

```http
POST /api/admin/points/debit
```

限制：

```text
不得用於違規計點
必須 reason
高額需 root approve
```

#### 處理爭議

```http
POST /api/admin/points/disputes/{dispute_id}/resolve
```

---

### 12.3 Root API

#### 封塊

```http
POST /api/root/points-chain/seal
```

#### 驗證全鏈

```http
POST /api/root/points-chain/verify
```

#### 查詢 chain status

```http
GET /api/root/points-chain/status
```

#### 設定節點

```http
POST /api/root/points-chain/nodes
```

#### 產生每日 anchor

```http
POST /api/root/points-chain/anchor
```

---

## 13. Chain Verification

### 13.1 verify ledger

檢查：

```text
ledger_hash 是否可重算
previous_ledger_hash 是否正確
balance_before / balance_after 是否連續
metadata_hash 是否正確
```

---

### 13.2 verify block

檢查：

```text
block 內所有 ledger_hash
merkle_root 是否正確
previous_block_hash 是否正確
block_hash 是否正確
ledger id 範圍是否連續
ledger_count 是否正確
```

---

### 13.3 verify chain

檢查：

```text
從 genesis block 到 latest block
每個 block hash 都正確
每個 previous_block_hash 都正確
所有已封 ledger 都存在
沒有 ledger 被跳過
沒有 ledger 被重複封塊
wallet balance 可由 ledger replay 重建
```

---

## 14. 隱私設計

### 14.1 public_account_id

對外顯示：

```text
public_account_id = HMAC_SHA256(server_secret, user_id)
```

不要對外顯示連續 user_id。

---

### 14.2 metadata 分級

```text
public_metadata：用戶可看
private_metadata：admin/root 可看
sensitive_metadata：加密保存
```

---

### 14.3 不得進入鏈上資料的內容

不得把以下資料放進 ledger payload 或 block：

```text
email
phone
真實姓名
IP
cookie
token
session id
device id
OAuth token
JWT
private key
```

如需證明，使用：

```text
HMAC digest
redacted value
encrypted metadata
```

---

## 15. 外部錨定設計

### 15.1 MVP

先不做公鏈錨定，只做本地 chain verify。

### 15.2 Phase 2

每日產生：

```json
{
  "date": "2026-04-28",
  "last_block_number": 1000,
  "last_block_hash": "...",
  "daily_merkle_root": "...",
  "ledger_count": 12345
}
```

### 15.3 可錨定位置

```text
GitHub repository commit
公開 readonly web page
第三方 timestamp service
公鏈 memo transaction
離線簽章檔
```

只錨定 hash，不公開完整交易。

---

## 16. 安全要求

### 16.1 禁止直接改帳

禁止：

```text
UPDATE points_wallet SET soft_points = ...
UPDATE points_ledger SET amount = ...
DELETE FROM points_ledger
DELETE FROM points_chain_blocks
```

所有變更必須走 service。

---

### 16.2 DB 權限

應拆分 DB role：

```text
app_runtime：只能透過 application service 操作
migration：只能部署時使用
audit_readonly：只能讀取
root_maintenance：緊急維護用，需記錄
```

---

### 16.3 Admin 不可直接改帳

admin 補償或扣回必須：

```text
產生 ledger
產生 audit log
可被 root review
高額需 root approve
```

---

### 16.4 Root 也不可靜默改帳

root 操作必須：

```text
寫 audit log
保留 reason
保留 before/after
可在 chain verify 中看見
```

---

### 16.5 防 replay

所有交易必須有：

```text
ledger_uuid
reference_id
idempotency_key
```

相同 reference_id + action_type 不可重複入帳。

---

## 17. 風控規則

偵測：

```text
短時間大量得點
同一 IP 多帳號互轉
互刷 likes
異常遊戲得分
bug bounty 重複回報
商城洗交易
AI 服務刷退款
server rental 惡意佔用
```

風控動作：

```text
freeze points
mark transaction risk_flag
require admin review
require root approval
delay settlement
```

---

## 18. 經濟系統整合點

所有以下功能都必須接 PointsLedgerService：

```text
發文消費
留言獎勵
按讚獎勵
有效 bug 回報獎勵
商城購物
商城賣東西
雲端容量購買
ComfyUI 生圖消費
server 租借
網頁遊戲虛寶
串流平台互動收益
活動任務獎勵
```

禁止各模組自行改 points_wallet。

---

## 19. Service 設計

### 19.1 PointsLedgerService

必須提供：

```text
credit(user_id, currency_type, amount, action_type, reference, metadata)
debit(user_id, currency_type, amount, action_type, reference, metadata)
freeze(user_id, currency_type, amount, reason)
unfreeze(user_id, currency_type, amount, reason)
reverse(ledger_uuid, reason)
transfer(from_user_id, to_user_id, amount, currency_type, reason)
get_balance(user_id)
get_ledger(user_id)
```

---

### 19.2 PointsChainService

必須提供：

```text
seal_pending_ledgers(limit)
verify_ledger(ledger_uuid)
verify_block(block_number)
verify_chain()
get_merkle_proof(ledger_uuid)
anchor_daily_root()
```

---

### 19.3 PointsRiskService

必須提供：

```text
check_before_credit()
check_before_debit()
detect_abuse_patterns()
freeze_suspicious_points()
mark_risk_flag()
```

---

## 20. UI 要求

### 20.1 User UI

新增：

```text
我的錢包
積分餘額
交易紀錄
交易證明
爭議申請
凍結積分顯示
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
```

---

### 20.2 Admin UI

新增：

```text
用戶積分查詢
交易查詢
爭議處理
風控標記
小額補償
小額扣回
```

---

### 20.3 Root UI

新增：

```text
Points Chain 狀態
最新 block
封塊操作
全鏈驗證
節點管理
每日 anchor
異常報告
```

---

## 21. CLI / Management Commands

請實作以下命令：

```bash
python manage.py points-chain seal
python manage.py points-chain verify
python manage.py points-chain verify-ledger <ledger_uuid>
python manage.py points-chain verify-block <block_number>
python manage.py points-chain proof <ledger_uuid>
python manage.py points-chain anchor-daily
python manage.py points-chain rebuild-wallet --dry-run
python manage.py points-chain audit-report
```

若專案不是 Python，請依現有技術棧建立等效命令。

---

## 22. 測試要求

### 22.1 Ledger 測試

必測：

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
```

---

### 22.2 Block 測試

必測：

```text
封塊成功
merkle_root 正確
block_hash 正確
已封 ledger 不可重複封塊
漏 ledger 會 verify 失敗
竄改 ledger 後 verify 失敗
竄改 block 後 verify 失敗
```

---

### 22.3 Concurrency 測試

必測：

```text
同一用戶同時扣點不會變負數
同時加點不會 lost update
同時消費與退款不會錯帳
seal block 時不會漏封或重封
```

---

### 22.4 Permission 測試

必測：

```text
user 不能看別人 ledger
user 不能封塊
admin 不能直接改 wallet
admin 高額加扣點需要 root
root 操作必須留 audit log
```

---

### 22.5 Privacy 測試

必測：

```text
proof 不含個資
API 不洩漏 email
API 不洩漏 IP
public_account_id 不可反推 user_id
sensitive metadata 有加密
```

---

## 23. Migration 策略

如果已存在 points_wallet / points_ledger：

```text
1. backup database
2. add hash columns
3. backfill ledger_hash
4. create genesis block
5. seal historical ledgers in batches
6. run verify_chain
7. compare wallet balance with ledger replay
```

若 wallet 與 ledger 對不起來：

```text
不得直接修改歷史 ledger
產生 reconciliation report
root 人工確認
用 correction ledger 修正
```

---

## 24. Genesis Block

第一個 block：

```text
block_number = 0
previous_block_hash = null
merkle_root = SHA256("GENESIS")
block_hash = SHA256(canonical_json(genesis_payload))
```

genesis_payload：

```json
{
  "chain_name": "hackme_web_points_chain",
  "version": "1.0",
  "created_at": "...",
  "created_by": "system"
}
```

---

## 25. 最終交付項目

Agent 必須交付：

```text
1. database migrations
2. PointsLedgerService
3. PointsChainService
4. PointsRiskService
5. MerkleTree utility
6. Hash canonicalization utility
7. API routes
8. user wallet UI
9. admin points UI
10. root chain UI
11. management commands
12. unit tests
13. integration tests
14. concurrency tests
15. privacy tests
16. README update
17. SECURITY.md update
18. docs/points_chain_private_blockchain_design.md
19. docs/points_chain_operations_runbook.md
20. docs/points_chain_threat_model.md
```

---

## 26. 禁止交付不完整設計

不得只做：

```text
單純 points +/-
沒有 ledger
沒有 hash
沒有 block
沒有 verify
沒有 audit log
沒有測試
```

若時間不夠，至少完成 Phase 1 MVP：

```text
wallet
ledger
ledger_hash
previous_ledger_hash
credit/debit
audit log
balance API
ledger API
verify-ledger command
tests
```

---

## 27. 完成後回報格式

請用以下格式回報：

```text
# hackme_web Points Private Chain 完成摘要

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

## 28. 最高優先級提醒

此功能的核心不是「炫技上鏈」，而是：

```text
每一筆積分都有來源
每一筆積分都能追溯
每一筆積分都不能靜默竄改
每一筆積分都能被驗證
用戶隱私不被公開
平台仍保留營運與爭議處理能力
```

請以此為最高設計原則。
