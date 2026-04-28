# hackme_web 全站積分經濟模型建置指令書 v1.0

> 目標：為 hackme_web 建立一套可長期營運、可審計、可防濫用、可擴展到論壇、雲端硬碟、商城、Server 租借、ComfyUI 生圖服務、網頁遊戲虛寶與未來串流平台的全站積分經濟系統。

---

## 0. 給 Agent 的最高原則

你是負責實作 hackme_web 全站經濟模型的工程 Agent。請在新分支作業，不得直接污染 main。

建議分支名稱：

```bash
git checkout -b feature/points-economy-system
```

本任務不是只做「會員點數欄位」，而是要建立完整的「平台經濟系統」。必須包含：

1. 錢包 Wallet
2. 不可竄改式帳本 Ledger
3. 積分規則 Rules Engine
4. 任務與收益 Earn System
5. 消費與服務計費 Spend System
6. 商城與交易抽成 Marketplace Layer
7. 防刷點與風控 Anti-Abuse
8. 管理員審核與調整 Admin Review
9. 經濟監控與防通膨 Economy Dashboard
10. 測試、文件、Migration、回滾策略

嚴格要求：

- 積分系統必須與違規計點系統完全分離。
- 所有加點、扣點、凍結、退款、調整都必須寫入 ledger。
- 不允許只修改餘額而不留帳。
- 前端不得決定點數數量。
- 所有價格、獎勵、限制必須由後端規則決定。
- 所有扣點必須是 transaction 原子操作。
- 點數餘額不得變成負數。
- 管理員手動調整點數必須有 audit log。
- 高價值收益，例如有效 bug 回報、商城收入、Server 租借退款，必須支援審核流程。

---

## 1. 經濟系統定位

系統名稱：Points Economy System

平台內部名稱建議：

```text
soft_points = 一般積分 / 活動點 / 免費點
hard_points = 高價值點 / 付費點 / 現金等價點
```

### 1.1 雙幣制設計

必須實作雙幣制，避免平台經濟失控。

| 幣種 | 來源 | 主要用途 | 是否可交易 | 是否可退款 |
|---|---|---|---|---|
| soft_points | 發文、留言、互動、遊戲、任務、低風險獎勵 | 發文成本、低階生圖、低階雲端容量、遊戲小道具 | 預設不可直接轉讓 | 通常不可退款 |
| hard_points | 充值、商城售出收入、官方活動、審核通過的高價值貢獻 | Server 租借、高階生圖、商城、高價值服務 | 可配置是否允許 | 可依規則退款 |

### 1.2 與違規計點分離

不得將以下兩者混用：

```text
points / wallet / ledger：經濟用途
violation_score / moderation_score：違規、處分、風控用途
```

違規可以導致：

- 禁止收益
- 凍結錢包
- 限制提領 / 轉讓
- 降低每日收益上限

但違規點本身不得直接等於扣點，除非 root/admin 透過明確審核流程執行「經濟處分」，且必須寫入 ledger 與 audit log。

---

## 2. 經濟閉環設計

平台經濟必須形成以下閉環：

```text
內容 / 貢獻 / 互動 / 遊戲 / 商城 / Bug 回報
        ↓
      獲得點數
        ↓
雲端容量 / AI 生圖 / Server 租借 / 虛寶 / 商城 / 發文 / 新功能
        ↓
      點數回收
        ↓
  平台服務活躍度提升
        ↓
  更多內容、交易、互動與消費
```

### 2.1 點數來源 Faucet

收益來源分成三類。

#### A. 自動低價值收益

- 每日登入
- 發文
- 留言
- 被按讚
- 內容收藏
- 文章被回覆
- 遊戲每日任務
- 低階論壇活動

這類收益必須有：

- 每日上限
- 冷卻時間
- 品質門檻
- 反互刷限制
- 新帳號限制

#### B. 半自動中價值收益

- 高品質文章
- 高互動率內容
- 被管理員標記為優質內容
- 有效教學文
- 串流平台有效觀看 / 互動
- 遊戲活動排名獎勵

這類收益必須有：

- 風控分數
- 延遲入帳
- 可被撤銷
- 可進入待審核狀態

#### C. 審核型高價值收益

- 有效 bug 回報
- 安全漏洞回報
- 商城賣東西收入
- Server 資源提供者收益
- 官方活動大獎
- 重要貢獻獎勵

這類收益必須：

- 先進入 pending 狀態
- 由 admin/root 審核
- 支援 approve/reject
- 支援 clawback 回收
- 有完整 audit log

### 2.2 點數回收 Sink

必須設計足夠的點數消耗場景，避免通膨。

消耗場景：

- 發文成本 / 置頂成本
- 附件上傳成本
- 雲端硬碟容量購買
- ComfyUI 生圖服務
- 高解析度 / 批次生圖
- Server 租借
- 商城購買
- 網頁遊戲虛寶
- 遊戲抽卡 / 裝飾品 / 通行證
- 串流平台打賞
- 改名、頭像框、稱號、個人頁裝飾
- API 額度
- 優先佇列費用

### 2.3 點數回收稅與平台抽成

商城、玩家交易、打賞、資源租借必須支援平台抽成。

建議預設：

```text
一般商城交易：平台抽成 5% ~ 15%
玩家對玩家交易：平台抽成 3% ~ 10%
Server 資源租借：平台抽成 10% ~ 20%
串流打賞：平台抽成 5% ~ 30%
```

抽成應進入 platform_sink，不應直接消失而無紀錄。

---

## 3. 資料庫設計

請依現有 hackme_web 技術棧建立 migration。以下為邏輯 schema，可按實際 DB 語法調整。

### 3.1 points_wallets

```sql
CREATE TABLE points_wallets (
  user_id BIGINT PRIMARY KEY,
  soft_balance BIGINT NOT NULL DEFAULT 0,
  hard_balance BIGINT NOT NULL DEFAULT 0,
  soft_frozen BIGINT NOT NULL DEFAULT 0,
  hard_frozen BIGINT NOT NULL DEFAULT 0,
  total_soft_earned BIGINT NOT NULL DEFAULT 0,
  total_hard_earned BIGINT NOT NULL DEFAULT 0,
  total_soft_spent BIGINT NOT NULL DEFAULT 0,
  total_hard_spent BIGINT NOT NULL DEFAULT 0,
  wallet_status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (soft_balance >= 0),
  CHECK (hard_balance >= 0),
  CHECK (soft_frozen >= 0),
  CHECK (hard_frozen >= 0)
);
```

wallet_status：

```text
active
frozen
limited
closed
```

### 3.2 points_ledger

所有點數變動都必須寫入此表。

```sql
CREATE TABLE points_ledger (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  currency_type VARCHAR(16) NOT NULL,
  direction VARCHAR(16) NOT NULL,
  amount BIGINT NOT NULL,
  balance_before BIGINT NOT NULL,
  balance_after BIGINT NOT NULL,
  action_type VARCHAR(64) NOT NULL,
  source_type VARCHAR(64),
  reference_id VARCHAR(128),
  idempotency_key VARCHAR(128) UNIQUE,
  status VARCHAR(32) NOT NULL DEFAULT 'committed',
  reason TEXT,
  metadata JSONB,
  created_by BIGINT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (amount > 0)
);
```

currency_type：

```text
soft
hard
```

direction：

```text
earn
spend
refund
freeze
unfreeze
adjust
clawback
transfer_in
transfer_out
sink
```

status：

```text
pending
committed
rejected
reversed
```

### 3.3 points_rules

```sql
CREATE TABLE points_rules (
  id BIGSERIAL PRIMARY KEY,
  rule_key VARCHAR(64) UNIQUE NOT NULL,
  action_type VARCHAR(64) NOT NULL,
  currency_type VARCHAR(16) NOT NULL,
  amount BIGINT NOT NULL,
  daily_limit BIGINT,
  weekly_limit BIGINT,
  monthly_limit BIGINT,
  cooldown_seconds INT DEFAULT 0,
  min_account_age_days INT DEFAULT 0,
  min_reputation INT DEFAULT 0,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  requires_review BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 3.4 points_pending_rewards

```sql
CREATE TABLE points_pending_rewards (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  currency_type VARCHAR(16) NOT NULL,
  amount BIGINT NOT NULL,
  action_type VARCHAR(64) NOT NULL,
  reference_id VARCHAR(128),
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  submitted_by BIGINT,
  reviewed_by BIGINT,
  review_note TEXT,
  metadata JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TIMESTAMP
);
```

status：

```text
pending
approved
rejected
expired
cancelled
```

### 3.5 points_economy_daily_stats

用於觀察通膨與經濟健康。

```sql
CREATE TABLE points_economy_daily_stats (
  stat_date DATE PRIMARY KEY,
  soft_issued BIGINT NOT NULL DEFAULT 0,
  soft_spent BIGINT NOT NULL DEFAULT 0,
  soft_sinked BIGINT NOT NULL DEFAULT 0,
  hard_issued BIGINT NOT NULL DEFAULT 0,
  hard_spent BIGINT NOT NULL DEFAULT 0,
  hard_sinked BIGINT NOT NULL DEFAULT 0,
  active_wallets INT NOT NULL DEFAULT 0,
  suspicious_events INT NOT NULL DEFAULT 0,
  marketplace_volume BIGINT NOT NULL DEFAULT 0,
  ai_generation_volume BIGINT NOT NULL DEFAULT 0,
  server_rental_volume BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 3.6 economy_price_catalog

所有服務價格必須從後端 catalog 讀取。

```sql
CREATE TABLE economy_price_catalog (
  id BIGSERIAL PRIMARY KEY,
  item_key VARCHAR(64) UNIQUE NOT NULL,
  item_name VARCHAR(128) NOT NULL,
  category VARCHAR(64) NOT NULL,
  currency_type VARCHAR(16) NOT NULL,
  base_price BIGINT NOT NULL,
  dynamic_pricing BOOLEAN NOT NULL DEFAULT FALSE,
  min_price BIGINT,
  max_price BIGINT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. 核心服務設計

請建立 PointsEconomyService 或等價服務層。

### 4.1 必要方法

```text
get_balance(user_id)
earn_points(user_id, rule_key, reference_id, metadata, idempotency_key)
spend_points(user_id, item_key, quantity, reference_id, metadata, idempotency_key)
refund_points(user_id, ledger_id, reason)
freeze_points(user_id, currency_type, amount, reason)
unfreeze_points(user_id, currency_type, amount, reason)
adjust_points(admin_id, user_id, currency_type, amount, reason)
create_pending_reward(user_id, action_type, amount, metadata)
approve_pending_reward(admin_id, pending_reward_id)
reject_pending_reward(admin_id, pending_reward_id, reason)
calculate_risk(user_id, action_type, metadata)
get_daily_economy_stats()
```

### 4.2 原子操作要求

每次加點 / 扣點都必須：

```text
BEGIN TRANSACTION
1. lock wallet row
2. check rule / price / balance / limits / risk
3. update wallet balance
4. insert points_ledger
5. insert audit log if admin/system action
COMMIT
```

若任一步驟失敗，必須 rollback。

### 4.3 Idempotency 防重複入帳

每次加點或扣點必須有 idempotency_key。

範例：

```text
post_reward:user_id:post_id
comment_reward:user_id:comment_id
ai_generation:user_id:generation_job_id
marketplace_order:user_id:order_id
bug_bounty:user_id:report_id
```

若同一 idempotency_key 已存在，不得重複給點或扣點。

---

## 5. 收益規則設計

### 5.1 初始 points_rules 建議

請建立 seed rules。

| rule_key | 行為 | 幣種 | 點數 | 限制 |
|---|---|---|---|---|
| daily_login | 每日登入 | soft | +5 | 每日一次 |
| create_post | 發文 | soft | +3 | 每日最多 10 次，新帳號限制 |
| create_comment | 留言 | soft | +1 | 60 秒冷卻，每日最多 50 |
| receive_like | 被按讚 | soft | +1 | 同一對用戶每日最多 3 次有效 |
| quality_post_bonus | 優質文章 | soft | +20 | 需審核或演算法判定 |
| valid_bug_report_low | 低風險有效 bug | soft | +50 | 需審核 |
| valid_bug_report_medium | 中風險有效 bug | hard | +50 | 需審核 |
| valid_bug_report_high | 高風險有效 bug | hard | +200 | 需 root/admin 審核 |
| game_daily_quest | 遊戲每日任務 | soft | +10 | 每日一次 |
| marketplace_sale_income | 商城收入 | hard | variable | 訂單完成後入帳 |

### 5.2 收益品質條件

發文 / 留言給點必須符合：

- 內容長度達最低門檻
- 非重複內容
- 非短時間洗版
- 非被刪除內容
- 非違規內容
- 新帳號可降低收益
- 低信任帳號收益延遲入帳

### 5.3 被按讚收益防刷

必須防止互刷。

規則：

```text
同一 liker 對同一 author 每日有效收益最多 N 次。
新帳號按讚不一定產生收益。
低信任帳號按讚權重降低。
A/B 高頻互讚觸發風控。
同 IP / 同裝置 / 同瀏覽器指紋互動權重降低。
```

---

## 6. 消費價格模型

### 6.1 初始價格 catalog 建議

| item_key | 服務 | 幣種 | 價格 |
|---|---|---|---|
| post_cost_standard | 一般發文成本 | soft | 1 |
| post_pin_24h | 文章置頂 24 小時 | soft | 100 |
| cloud_storage_1gb_30d | 雲端容量 1GB / 30天 | soft | 100 |
| cloud_storage_10gb_30d | 雲端容量 10GB / 30天 | hard | 30 |
| comfyui_txt2img_basic | 基礎生圖一次 | soft | 5 |
| comfyui_txt2img_highres | 高解析生圖一次 | hard | 2 |
| comfyui_batch_10 | 批次生圖 10 張 | hard | 15 |
| server_rental_cpu_1h | CPU Server 1 小時 | hard | 5 |
| server_rental_gpu_1h | GPU Server 1 小時 | hard | 50 |
| game_virtual_item_common | 普通虛寶 | soft | 20 |
| game_virtual_item_premium | 高級虛寶 | hard | 5 |
| username_change | 改名 | soft | 200 |
| profile_decoration | 個人頁裝飾 | soft | 50 |

### 6.2 動態定價

Server、GPU、ComfyUI 生圖服務必須預留動態定價。

動態定價因素：

```text
目前佇列長度
GPU VRAM 使用率
尖峰時間
用戶等級
每日免費額度是否用完
是否使用 high priority queue
```

動態定價公式可先簡化：

```text
final_price = base_price * load_multiplier * priority_multiplier
```

限制：

```text
final_price 不得低於 min_price
final_price 不得高於 max_price
```

---

## 7. 市場與交易模型

### 7.1 Marketplace Order Flow

商城交易流程：

```text
1. buyer 建立訂單
2. buyer 點數進入 escrow/frozen
3. seller 出貨或交付
4. buyer 確認 / 系統到期自動確認
5. 平台抽成
6. seller 收入入帳
7. 交易寫入 ledger
```

### 7.2 Escrow 必須實作

不得買家扣點後直接給賣家，必須先進 escrow。

需要支援：

```text
order_created
payment_frozen
seller_delivered
buyer_confirmed
auto_confirmed
refund_requested
refund_approved
dispute_opened
dispute_resolved
seller_paid
platform_fee_sinked
```

### 7.3 平台抽成

所有 marketplace 收入必須紀錄：

```text
gross_amount
platform_fee
seller_net_amount
```

ledger 必須可追蹤完整金流。

---

## 8. ComfyUI 生圖計費模型

### 8.1 Job Flow

```text
1. user 建立 generation job
2. 系統計算價格
3. 檢查點數餘額
4. 先扣點或凍結點數
5. job 進入 queue
6. ComfyUI 執行
7. 成功：確認扣款
8. 失敗：退款或部分退款
9. 保存 job 與 ledger reference
```

### 8.2 計費因素

```text
模型類型
解析度
步數 steps
batch size
ControlNet / LoRA / Upscale
是否高優先級
是否保存到雲端硬碟
```

### 8.3 退款規則

```text
使用者取消且尚未開始：全額退款
ComfyUI 失敗：全額退款
生成完成但結果不滿意：不自動退款
系統錯誤：可補償點數
```

---

## 9. Server / 資源租借計費模型

### 9.1 租借流程

```text
1. user 選擇 server/resource
2. 系統顯示每小時價格
3. user 確認租借時間
4. 預扣或凍結點數
5. 啟動資源
6. 按時間扣款
7. 到期釋放資源
8. 未使用額度退款
```

### 9.2 必要限制

```text
不得讓低餘額用戶無限租借
資源啟動失敗必須退款
超時必須自動停止
高風險用戶不可租借高價資源
root/admin 可強制停止資源並依規則退款
```

---

## 10. 防通膨與經濟健康模型

### 10.1 每日監控指標

必須建立管理頁或每日統計：

```text
每日 soft_points 發行量
每日 soft_points 消耗量
每日 hard_points 發行量
每日 hard_points 消耗量
平台抽成總額
商城交易總額
AI 生圖消耗量
Server 租借消耗量
前 1% 用戶持有點數比例
異常收益帳號數
沉睡點數量
新帳號平均收益
老帳號平均收益
```

### 10.2 通膨警戒條件

若出現以下情況，系統應標記警告：

```text
soft_points 每日發行量 > 消耗量 3 倍，連續 7 天
前 1% 用戶持有超過 50% 流通點數
單一收益來源佔總發行量超過 60%
新帳號收益異常高
互刷網路快速成長
```

### 10.3 自動調節措施

先不要自動大幅修改經濟規則，但要支援 admin 手動調整：

```text
降低每日收益上限
提高消費價格
增加服務 sink
提高平台抽成
暫停某類收益規則
改為 pending rewards
對新帳號降低收益倍率
```

---

## 11. 風控與反作弊

### 11.1 Risk Score

每個收益事件都應計算 risk_score。

因素：

```text
帳號年齡
email 是否驗證
是否同 IP 大量互動
是否同裝置大量帳號
互讚頻率
留言相似度
短時間行為密度
過去違規紀錄
收益來源異常程度
```

### 11.2 風控動作

```text
risk_score < 30：正常入帳
30 <= risk_score < 60：延遲入帳
60 <= risk_score < 80：pending 審核
risk_score >= 80：拒絕收益並記錄 suspicious event
```

### 11.3 帳號限制

可對用戶套用：

```text
收益上限降低
禁止 marketplace 交易
禁止 hard_points 提領 / 轉移
禁止 Server 租借
錢包 frozen
只允許消費，不允許收益
```

---

## 12. API 設計

### 12.1 User APIs

```http
GET /api/points/balance
GET /api/points/ledger
GET /api/points/rules/public
GET /api/points/prices
POST /api/points/spend
POST /api/points/transfer-request   # 若未來開放轉讓，初版可不啟用
```

### 12.2 Internal APIs

```http
POST /internal/points/earn
POST /internal/points/spend
POST /internal/points/refund
POST /internal/points/freeze
POST /internal/points/unfreeze
POST /internal/points/pending-reward
```

Internal API 必須：

- 僅內部可呼叫
- 需要 service token 或等價認證
- 不可暴露給一般前端
- 有完整 log

### 12.3 Admin APIs

```http
GET /api/admin/points/users/:user_id/wallet
GET /api/admin/points/users/:user_id/ledger
POST /api/admin/points/users/:user_id/adjust
POST /api/admin/points/users/:user_id/freeze
POST /api/admin/points/users/:user_id/unfreeze
GET /api/admin/points/pending-rewards
POST /api/admin/points/pending-rewards/:id/approve
POST /api/admin/points/pending-rewards/:id/reject
GET /api/admin/economy/stats
GET /api/admin/economy/alerts
POST /api/admin/economy/rules/:id/update
POST /api/admin/economy/prices/:id/update
```

---

## 13. 前端頁面要求

### 13.1 使用者頁面

新增：

```text
/points
/points/history
/points/earn
/points/spend
```

內容：

- soft/hard 餘額
- frozen 數量
- 近期交易紀錄
- 如何賺點
- 可消費服務
- pending rewards
- 退款 / 申訴入口

### 13.2 消費確認元件

所有扣點前必須顯示確認：

```text
服務名稱
幣種
價格
餘額
扣款後餘額
是否可退款
取消規則
```

### 13.3 Admin 後台

新增：

```text
/admin/economy/dashboard
/admin/economy/rules
/admin/economy/prices
/admin/economy/pending-rewards
/admin/economy/suspicious-events
/admin/users/:id/wallet
```

Dashboard 顯示：

- 每日發行 / 消耗
- sink 比例
- 交易量
- top earners
- top spenders
- 異常帳號
- pending rewards
- 通膨警告

---

## 14. 安全要求

### 14.1 後端權威

前端不得傳入：

```text
amount
final_price
reward_amount
admin_override
currency_type 任意值
```

前端只能傳：

```text
item_key
quantity
reference_id
使用者確認資訊
```

實際價格與點數必須由後端 rules/catalog 計算。

### 14.2 CSRF / Auth

所有會改變點數狀態的 API 必須：

- 需要登入
- 需要 CSRF token
- 檢查權限
- 檢查 idempotency_key
- 寫入 audit log

### 14.3 管理員調點

Admin 手動調點必須：

```text
輸入原因
限制單次最大調整量
高額調整需要 root 或多管理員審核
寫入 admin_audit_log
寫入 points_ledger
不可直接改 wallet balance
```

---

## 15. 測試要求

### 15.1 單元測試

必測：

```text
加點成功
扣點成功
餘額不足扣點失敗
重複 idempotency_key 不重複入帳
pending reward approve 入帳
pending reward reject 不入帳
refund 正確回補
freeze/unfreeze 正確
admin adjust 寫 ledger
rule disabled 時不給點
每日上限生效
cooldown 生效
```

### 15.2 併發測試

必測：

```text
同一用戶同時發起 100 次扣點，不得扣成負數
同一 idempotency_key 同時送出 100 次，只能成功一次
商城 escrow 交易同時確認，不得重複付款
ComfyUI job 成功/失敗同時回調，不得重複退款
```

### 15.3 安全測試

必測：

```text
一般用戶不可呼叫 internal API
一般用戶不可改 amount
一般用戶不可查他人 ledger
CSRF 缺失請求失敗
低權限 admin 不可高額調點
凍結錢包不可消費
風控高分收益不得直接入帳
```

### 15.4 經濟測試

建立模擬腳本：

```text
1000 個用戶
30 天模擬
每日發文、留言、按讚、遊戲、AI 生圖、商城交易
輸出每日發行、消耗、餘額分布、通膨警告
```

輸出：

```text
reports/economy_simulation.md
reports/economy_simulation.json
```

---

## 16. Migration 與回滾

必須提供：

```text
migration up
migration down
seed rules
seed price catalog
測試資料 seed
```

回滾時：

- 不得刪除已有 ledger，除非是開發環境。
- production 回滾必須保留帳本資料。
- schema 變更需向後相容。

---

## 17. 文件要求

請更新或新增：

```text
docs/points_economy_system.md
docs/points_rules.md
docs/economy_admin_guide.md
docs/economy_security_model.md
docs/economy_api.md
docs/economy_testing.md
```

文件必須說明：

- soft/hard 差異
- 如何新增收益規則
- 如何新增消費項目
- 如何處理退款
- 如何審核 bug bounty
- 如何處理異常刷點
- 如何讀 ledger
- 如何調整價格防通膨

---

## 18. 分階段實作計畫

### Phase 1：核心錢包與帳本

完成：

```text
points_wallets
points_ledger
PointsEconomyService
get balance
earn
spend
refund
idempotency
transaction lock
unit tests
```

驗收：

```text
所有點數變動都有 ledger
高併發扣點不會負數
重複請求不會重複入帳
```

### Phase 2：規則與價格

完成：

```text
points_rules
economy_price_catalog
seed rules
seed prices
rules engine
price calculation
limits/cooldown
```

驗收：

```text
發文、留言、每日登入可依規則給點
生圖、雲端、發文成本可依價格扣點
```

### Phase 3：防濫用與 pending rewards

完成：

```text
risk_score
pending rewards
admin approve/reject
互刷防護基本版
每日收益上限
新帳號限制
```

驗收：

```text
高風險收益不直接入帳
bug 回報可審核後給點
互刷收益被限制
```

### Phase 4：消費場景整合

完成：

```text
雲端容量購買
ComfyUI 生圖扣點介面
Server 租借計費接口
商城 escrow 基礎模型
遊戲虛寶購買接口
```

驗收：

```text
每個消費場景都能扣點、退款、寫 ledger
```

### Phase 5：Admin 經濟後台

完成：

```text
economy dashboard
rules management
price management
pending review
suspicious events
wallet inspection
admin adjustment
```

驗收：

```text
管理員可觀察經濟狀態
可調整規則與價格
可審核高價值收益
```

### Phase 6：經濟模擬與文件

完成：

```text
30 天經濟模擬
通膨警告
完整 docs
README 更新
測試報告
```

驗收：

```text
能用模擬結果判斷目前規則是否會通膨
```

---

## 19. 最終交付清單

Agent 完成後必須回報：

```text
1. 新增/修改檔案列表
2. Migration 列表
3. API 列表
4. 測試結果
5. 經濟模擬結果
6. 安全檢查結果
7. 已知限制
8. 後續建議
```

產物至少包含：

```text
backend/services/points_economy_service.*
backend/models/points_wallet.*
backend/models/points_ledger.*
backend/models/points_rules.*
backend/routes/points.*
backend/routes/admin_economy.*
migrations/*points*.sql
seeds/points_rules_seed.*
seeds/economy_price_catalog_seed.*
frontend/pages/points/*
frontend/pages/admin/economy/*
tests/points/*
tests/economy/*
docs/points_economy_system.md
docs/economy_admin_guide.md
docs/economy_security_model.md
reports/economy_simulation.md
```

---

## 20. 完成回報格式

請用以下格式回報：

```text
# Points Economy System 完成摘要

## 分支
- branch:

## 已完成 Phase
- Phase 1:
- Phase 2:
- Phase 3:
- Phase 4:
- Phase 5:
- Phase 6:

## 新增資料表
-

## 新增 API
-

## 初始收益規則
-

## 初始消費價格
-

## 安全防護
-

## 測試結果
- unit tests:
- concurrency tests:
- security tests:
- economy simulation:

## 重要設計決策
-

## 已知限制
-

## 下一步建議
-
```

---

## 21. 特別提醒

這套系統未來會牽涉商城、雲端容量、AI 生圖、Server 租借與遊戲虛寶，因此必須從第一版就做到：

```text
可追帳
可退款
可凍結
可審核
可風控
可調價
可統計
可回滾
```

不要實作成單純 user.points += 1 的玩具系統。

