# hackme_web 商城交易系統 + 糾紛處理 + 交易審計 Agent 指令檔 v1.0

> 目標：在 hackme_web 建立完整商城系統。  
> 商城支援用戶使用積分購買官方釋出的頭銜、權益、功能道具，也可擴展為用戶間交易平台。  
> 系統必須具備完整交易流程、積分結算、糾紛處理、交易審計、平台抽成與防止「假交易真轉帳 / 洗點 / 洗錢式交易」的風控能力。  
> 定位：這是站內積分商城，不是真實貨幣交易所，不允許積分兌現，不允許繞過平台私下轉帳。

---

## 0. 最高設計原則

請為 hackme_web 建立「Marketplace 商城 + Trading Settlement + Dispute Center」。

必須遵守：

```text
1. 所有付款、收款、退款、抽成都必須走 PointsLedgerService。
2. 不得直接修改 points_wallet。
3. 所有交易必須可審計。
4. 官方商品與用戶商品要清楚分離。
5. 頭銜、權益、功能道具必須由系統授權發放，不得只改 UI。
6. 用戶間交易需有 escrow / 延遲結算機制。
7. 防止假交易真轉帳：不得讓用戶用虛假商品把積分轉給指定帳號。
8. 高風險交易要延遲結算、凍結或進人工審查。
9. 糾紛處理必須保留證據、狀態、處置與審計紀錄。
10. 管理員/root 可查交易與凍結，但不能靜默改帳。
```

---

# Part A — 系統功能範圍

## A1. 商城類型

商城分成兩大類：

```text
1. 官方商城 Official Store
   - 官方頭銜
   - 官方徽章
   - 官方權益
   - 功能解鎖
   - 雲端容量包
   - AI 生圖額度包
   - Server 租用折扣券
   - 網頁遊戲道具
   - 會員裝飾

2. 用戶市場 User Marketplace
   - 用戶出售允許交易的虛擬物品
   - 用戶出售創作素材
   - 用戶出售服務型商品，需審核
   - 未來可接影片創作者商品
```

MVP 建議：

```text
先做官方商城
再做受控的用戶市場
```

---

## A2. 貨幣

支援：

```text
soft_points
hard_points
```

建議：

```text
官方權益 / 容量 / 高價值道具：hard_points
裝飾 / 小道具 / 低風險權益：soft_points
```

---

## A3. 交易模式

支援：

```text
direct_purchase：官方商品直接購買
escrow_purchase：用戶商品托管交易
auction：拍賣，後期可做
subscription：訂閱制，後期可做
coupon/redeem：兌換券
```

MVP：

```text
direct_purchase + escrow_purchase
```

---

# Part B — 商品設計

## B1. 商品類型

```text
title：頭銜
badge：徽章
permission：權益 / 權限
quota_pack：額度包
cloud_storage_pack：雲端容量包
ai_image_credit_pack：AI 生圖額度包
server_rental_coupon：Server 租用券
game_item：遊戲道具
video_creator_item：創作者商品
custom_listing：用戶自定義商品，需審核
```

---

## B2. 官方商品例子

```text
頭銜：
- Early Supporter
- Bug Hunter
- Trader Champion
- Creator

權益：
- 每日發文上限增加
- 雲端容量 +10GB
- AI 生圖折扣
- 影片平台創作者徽章
- Server Rental 優先排隊

裝飾：
- 個人頁框
- 名稱顏色
- 徽章展示
```

---

## B3. 商品狀態

```text
draft
pending_review
active
paused
sold_out
delisted
deleted
```

---

# Part C — 資料表設計

## C1. marketplace_products

```sql
CREATE TABLE marketplace_products (
  id BIGSERIAL PRIMARY KEY,
  product_uuid UUID NOT NULL UNIQUE,

  seller_user_id BIGINT,
  seller_type VARCHAR(30) NOT NULL DEFAULT 'official',

  product_type VARCHAR(80) NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,

  category VARCHAR(100),
  tags_json TEXT,

  price_points BIGINT NOT NULL,
  currency_type VARCHAR(20) NOT NULL,

  stock_quantity BIGINT,
  sold_quantity BIGINT NOT NULL DEFAULT 0,

  status VARCHAR(40) NOT NULL DEFAULT 'draft',

  is_transferable BOOLEAN NOT NULL DEFAULT FALSE,
  requires_review BOOLEAN NOT NULL DEFAULT FALSE,
  delivery_mode VARCHAR(50) NOT NULL DEFAULT 'instant',

  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (seller_type IN ('official', 'user')),
  CHECK (currency_type IN ('soft', 'hard')),
  CHECK (price_points >= 0),
  CHECK (status IN ('draft', 'pending_review', 'active', 'paused', 'sold_out', 'delisted', 'deleted')),
  CHECK (delivery_mode IN ('instant', 'manual', 'escrow', 'subscription'))
);
```

---

## C2. marketplace_orders

```sql
CREATE TABLE marketplace_orders (
  id BIGSERIAL PRIMARY KEY,
  order_uuid UUID NOT NULL UNIQUE,

  buyer_user_id BIGINT NOT NULL,
  seller_user_id BIGINT,
  seller_type VARCHAR(30) NOT NULL,

  product_id BIGINT NOT NULL,

  quantity BIGINT NOT NULL DEFAULT 1,
  unit_price BIGINT NOT NULL,
  total_price BIGINT NOT NULL,
  currency_type VARCHAR(20) NOT NULL,

  platform_fee BIGINT NOT NULL DEFAULT 0,
  seller_earn BIGINT NOT NULL DEFAULT 0,

  status VARCHAR(50) NOT NULL DEFAULT 'pending',

  payment_ledger_uuid UUID,
  seller_earn_ledger_uuid UUID,
  platform_fee_ledger_uuid UUID,
  refund_ledger_uuid UUID,

  escrow_status VARCHAR(40) DEFAULT 'none',

  idempotency_key VARCHAR(160),

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  paid_at TIMESTAMP,
  delivered_at TIMESTAMP,
  completed_at TIMESTAMP,
  cancelled_at TIMESTAMP,
  refunded_at TIMESTAMP,

  CHECK (seller_type IN ('official', 'user')),
  CHECK (quantity > 0),
  CHECK (total_price >= 0),
  CHECK (currency_type IN ('soft', 'hard')),
  CHECK (status IN (
    'pending',
    'paid',
    'delivering',
    'delivered',
    'completed',
    'cancelled',
    'refunded',
    'disputed',
    'chargeback',
    'failed',
    'risk_review'
  )),
  CHECK (escrow_status IN ('none', 'holding', 'released', 'refunded', 'frozen'))
);
```

---

## C3. marketplace_entitlements

```sql
CREATE TABLE marketplace_entitlements (
  id BIGSERIAL PRIMARY KEY,
  entitlement_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,
  order_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,

  entitlement_type VARCHAR(80) NOT NULL,
  entitlement_key VARCHAR(160) NOT NULL,

  value_json TEXT,

  status VARCHAR(40) NOT NULL DEFAULT 'active',

  starts_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,

  revoked_by BIGINT,
  revoked_reason TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (status IN ('active', 'expired', 'revoked', 'suspended'))
);
```

用途：

```text
真正授權頭銜、徽章、容量、權益、折扣券等。
```

---

## C4. marketplace_disputes

```sql
CREATE TABLE marketplace_disputes (
  id BIGSERIAL PRIMARY KEY,
  dispute_uuid UUID NOT NULL UNIQUE,

  order_id BIGINT NOT NULL,

  opened_by_user_id BIGINT NOT NULL,
  against_user_id BIGINT,

  reason VARCHAR(120) NOT NULL,
  description TEXT NOT NULL,

  status VARCHAR(40) NOT NULL DEFAULT 'open',
  severity VARCHAR(30) NOT NULL DEFAULT 'medium',

  resolution VARCHAR(80),
  resolution_note TEXT,

  reviewed_by BIGINT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TIMESTAMP,
  resolved_at TIMESTAMP,

  CHECK (status IN ('open', 'reviewing', 'waiting_buyer', 'waiting_seller', 'resolved', 'rejected', 'escalated')),
  CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);
```

---

## C5. marketplace_dispute_messages

```sql
CREATE TABLE marketplace_dispute_messages (
  id BIGSERIAL PRIMARY KEY,

  dispute_id BIGINT NOT NULL,
  sender_user_id BIGINT,
  sender_role VARCHAR(50) NOT NULL,

  message TEXT NOT NULL,
  attachments_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (sender_role IN ('buyer', 'seller', 'admin', 'root', 'system'))
);
```

---

## C6. marketplace_trade_risk_flags

```sql
CREATE TABLE marketplace_trade_risk_flags (
  id BIGSERIAL PRIMARY KEY,

  order_id BIGINT,
  product_id BIGINT,
  buyer_user_id BIGINT,
  seller_user_id BIGINT,

  risk_type VARCHAR(100) NOT NULL,
  risk_score INT NOT NULL DEFAULT 0,
  severity VARCHAR(30) NOT NULL DEFAULT 'medium',

  evidence_json TEXT,

  status VARCHAR(40) NOT NULL DEFAULT 'open',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TIMESTAMP,

  CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  CHECK (status IN ('open', 'reviewing', 'resolved', 'false_positive'))
);
```

---

## C7. marketplace_audit_logs

```sql
CREATE TABLE marketplace_audit_logs (
  id BIGSERIAL PRIMARY KEY,

  event_type VARCHAR(100) NOT NULL,
  severity VARCHAR(30) NOT NULL DEFAULT 'info',

  actor_user_id BIGINT,
  actor_role VARCHAR(50),

  target_user_id BIGINT,
  product_id BIGINT,
  order_id BIGINT,
  dispute_id BIGINT,

  message TEXT NOT NULL,
  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical'))
);
```

---

# Part D — 交易流程

## D1. 官方商品 direct_purchase

流程：

```text
1. 使用者選擇官方商品。
2. 後端驗證商品 active、庫存足夠、使用者有資格購買。
3. 後端計算價格，不信任前端價格。
4. PointsLedgerService.debit() 扣款。
5. 建立 marketplace_order。
6. 發放 entitlement。
7. 訂單 status = completed。
8. 寫 audit log。
```

ledger：

```text
marketplace_purchase_debit
marketplace_official_revenue
```

---

## D2. 用戶商品 escrow_purchase

流程：

```text
1. buyer 下單。
2. 後端驗證商品 active。
3. PointsLedgerService.debit() 從 buyer 扣款。
4. 積分進入 escrow holding，不立刻給 seller。
5. seller 交付商品或系統交付。
6. buyer 確認完成，或時間到自動完成。
7. 扣平台抽成。
8. seller 收到 seller_earn。
9. 訂單 completed。
```

若糾紛：

```text
1. order status = disputed。
2. escrow_status = frozen。
3. admin/root 處理。
4. 決定退款、放款、部分退款。
5. 所有處置寫 ledger reversal / credit。
```

---

## D3. 退款流程

不得刪除原交易。

正確方式：

```text
1. 訂單標記 refunded。
2. PointsLedgerService.credit() 退款給 buyer。
3. 若 seller 已收款，需 reverse seller_earn。
4. 若平台已抽成，需 reverse platform_fee。
5. 寫 audit log。
```

---

## D4. 頭銜 / 權益交付

購買後不只是交易完成，還必須建立 entitlement。

例：

```text
product_type = title
entitlement_type = title
entitlement_key = title.early_supporter
```

系統在 UI 顯示頭銜時必須檢查 marketplace_entitlements。

---

# Part E — 平台抽成

## E1. 用戶市場抽成

設定：

```yaml
marketplace:
  user_trade_fee_rate: 0.10
  official_trade_fee_rate: 0.00
  escrow_hold_days: 3
```

例：

```text
商品 1000 points
平台抽成 100
seller 收 900
```

---

## E2. Ledger action_type

```text
marketplace_purchase_debit
marketplace_seller_earn
marketplace_platform_fee
marketplace_refund
marketplace_reversal
marketplace_entitlement_grant
marketplace_entitlement_revoke
```

---

# Part F — 防止假交易真轉帳

## F1. 風險定義

「假交易真轉帳」指：

```text
用戶上架無實際價值商品
→ 指定另一用戶高價購買
→ 用商品交易包裝積分轉帳
→ 規避平台轉帳限制、風控或抽成
```

---

## F2. 必須防範的模式

```text
1. 新帳號高價購買低價值商品。
2. 兩帳號互相買賣。
3. 同 IP / 同設備帳號互相交易。
4. 商品無描述、無交付、價格異常。
5. 短時間反覆交易。
6. 交易後立即提領/轉換高價值權益。
7. buyer/seller 長期只和彼此交易。
8. 高價商品無審核。
9. 用戶商品價格遠高於同類商品。
10. 多帳號輪流購買同一 seller 商品。
```

---

## F3. 風控要求

用戶商品需做 risk scoring：

```text
risk_score =
  new_account_score
+ price_abnormal_score
+ buyer_seller_relation_score
+ ip_device_overlap_score
+ trade_frequency_score
+ listing_quality_score
+ dispute_history_score
```

風控處置：

```text
risk_score < 30：正常
30~59：延遲結算
60~79：進人工審查
80+：凍結交易與收益
```

---

## F4. 強制限制

```text
1. 新帳號不能上架高價商品。
2. 新帳號不能購買高價用戶商品。
3. 用戶商品超過價格門檻需 admin 審核。
4. 同一 buyer/seller 每日交易額有限制。
5. 同 IP / 同裝置關聯帳號不可互買高額商品。
6. 高風險交易進 escrow，不得即時結算。
7. seller 收益可延遲 3~7 天釋放。
8. 風控中的收益不得消費或轉出。
```

---

# Part G — 糾紛處理平台

## G1. 可開糾紛的情況

```text
1. 商品未交付。
2. 權益未生效。
3. 商品描述不符。
4. 交易疑似詐騙。
5. 投訴虛假商品。
6. 系統扣點但未收到商品。
7. seller 要求私下交易。
```

---

## G2. 糾紛流程

```text
1. buyer/seller 開啟 dispute。
2. order status = disputed。
3. escrow_status = frozen。
4. 雙方提交證據。
5. admin 初審。
6. 必要時 root 複審。
7. 決議：
   - refund_buyer
   - release_to_seller
   - partial_refund
   - cancel_order
   - punish_seller
   - mark_false_claim
8. 執行對應 ledger。
9. 關閉 dispute。
10. 產生審計紀錄。
```

---

## G3. Dispute UI

用戶可看到：

```text
糾紛狀態
訂單資訊
商品資訊
雙方留言
證據附件
處理結果
```

admin/root 可看到：

```text
雙方交易歷史
風控分數
IP/device digest
過往糾紛
ledger 關聯
建議處置
```

---

# Part H — API 設計

## H1. User API

```http
GET    /api/marketplace/products
GET    /api/marketplace/products/:product_uuid
POST   /api/marketplace/products
PUT    /api/marketplace/products/:product_uuid
DELETE /api/marketplace/products/:product_uuid

POST   /api/marketplace/orders
GET    /api/marketplace/orders
GET    /api/marketplace/orders/:order_uuid
POST   /api/marketplace/orders/:order_uuid/confirm
POST   /api/marketplace/orders/:order_uuid/cancel

POST   /api/marketplace/orders/:order_uuid/dispute
GET    /api/marketplace/disputes
GET    /api/marketplace/disputes/:dispute_uuid
POST   /api/marketplace/disputes/:dispute_uuid/messages

GET    /api/marketplace/entitlements
```

---

## H2. Admin API

```http
GET  /api/admin/marketplace/products
POST /api/admin/marketplace/products/:product_uuid/approve
POST /api/admin/marketplace/products/:product_uuid/reject
POST /api/admin/marketplace/products/:product_uuid/pause

GET  /api/admin/marketplace/orders
GET  /api/admin/marketplace/risk-flags
GET  /api/admin/marketplace/disputes
POST /api/admin/marketplace/disputes/:dispute_uuid/resolve

POST /api/admin/marketplace/orders/:order_uuid/freeze
POST /api/admin/marketplace/orders/:order_uuid/refund
POST /api/admin/marketplace/orders/:order_uuid/release
```

---

## H3. Root API

```http
POST /api/root/marketplace/products/official
PUT  /api/root/marketplace/products/official/:product_uuid
POST /api/root/marketplace/fee-policy
POST /api/root/marketplace/risk-policy
GET  /api/root/marketplace/audit
GET  /api/root/marketplace/revenue
POST /api/root/marketplace/emergency-pause
POST /api/root/marketplace/recalculate-risk
```

---

# Part I — UI 設計

## I1. Marketplace 首頁

路由：

```text
/marketplace
```

顯示：

```text
官方商城
用戶市場
分類
熱門商品
新上架
我的購買
我的上架
```

---

## I2. 商品詳細頁

```text
商品圖片/圖示
標題
描述
價格
貨幣類型
庫存
賣家類型
交易保障說明
購買按鈕
風險提示
```

---

## I3. 購買確認

必須顯示：

```text
商品
價格
平台規則
是否可退款
交付方式
預計交付時間
確認消耗積分
```

---

## I4. 我的交易

```text
購買紀錄
出售紀錄
糾紛紀錄
收益紀錄
權益紀錄
```

---

## I5. Admin 糾紛中心

```text
開放糾紛
高風險交易
待審核商品
凍結收益
處理紀錄
```

---

# Part J — Service 設計

## J1. MarketplaceProductService

```text
create_product()
update_product()
approve_product()
pause_product()
delist_product()
validate_product()
```

---

## J2. MarketplaceOrderService

```text
create_order()
pay_order()
deliver_order()
complete_order()
cancel_order()
refund_order()
```

---

## J3. MarketplaceEntitlementService

```text
grant_entitlement()
revoke_entitlement()
check_entitlement()
expire_entitlements()
```

---

## J4. MarketplaceEscrowService

```text
hold_payment()
release_to_seller()
refund_to_buyer()
freeze_escrow()
partial_release()
```

---

## J5. MarketplaceRiskService

```text
score_listing()
score_order()
detect_fake_trade_transfer()
detect_wash_trading()
detect_related_accounts()
freeze_high_risk_order()
```

---

## J6. MarketplaceDisputeService

```text
open_dispute()
add_message()
review_dispute()
resolve_dispute()
execute_resolution()
```

---

## J7. MarketplaceAuditService

```text
log_event()
generate_trade_audit_report()
generate_revenue_report()
generate_risk_report()
```

---

# Part K — 權限與安全

## K1. 一般用戶

可：

```text
瀏覽商品
購買商品
上架允許類型商品
查看自己的訂單
開啟糾紛
查看自己的權益
```

不可：

```text
直接修改價格成交結果
直接修改權益
直接轉點給指定用戶
查看其他用戶交易細節
繞過 escrow
取消風控
```

---

## K2. Admin

可：

```text
審核商品
處理糾紛
凍結高風險交易
退款
下架商品
查看風控資訊
```

限制：

```text
高額退款/放款需 root 確認
admin 操作必須 audit log
```

---

## K3. Root

可：

```text
建立官方商品
調整抽成
調整風控政策
緊急暫停商城
查看完整審計
核准高額糾紛處置
```

限制：

```text
root 也不能靜默改帳
所有操作必須 ledger/audit
```

---

# Part L — 官方商品交付範例

## L1. 頭銜

購買後：

```text
grant entitlement:
entitlement_type = title
entitlement_key = title.creator
```

UI 顯示時查：

```text
MarketplaceEntitlementService.check_entitlement(user_id, "title.creator")
```

---

## L2. 雲端容量包

購買後：

```text
entitlement_type = cloud_storage_quota
value_json = {"extra_gb": 10}
```

CloudDrive 系統計算容量時讀取 entitlement。

---

## L3. AI 生圖額度

購買後：

```text
entitlement_type = ai_image_credit_pack
value_json = {"credits": 100}
```

AI 生圖系統消費時讀取額度或折抵。

---

## L4. Server 租用折扣券

```text
entitlement_type = server_rental_coupon
value_json = {"discount_pct": 20, "uses": 1}
```

---

# Part M — 背景任務

新增：

```text
marketplace_release_escrow
marketplace_expire_entitlements
marketplace_detect_fake_trades
marketplace_update_daily_revenue
marketplace_review_pending_products
marketplace_dispute_reminders
```

頻率：

```text
escrow release：每 10 分鐘
risk detection：每 5~15 分鐘
entitlement expire：每小時
revenue report：每日
```

---

# Part N — 測試要求

必測：

```text
1. 官方商品購買成功。
2. 官方商品交付 entitlement。
3. 用戶商品購買進 escrow。
4. escrow release 正確。
5. 平台抽成正確。
6. seller earn 正確。
7. 退款正確。
8. 糾紛會凍結 escrow。
9. 糾紛解決會正確退款/放款。
10. 餘額不足不能購買。
11. 不可直接轉點給指定用戶。
12. 自買自賣被擋。
13. 同 IP 高風險交易被標記。
14. 高價商品需審核。
15. 新帳號高價交易被限制。
16. 重複 idempotency_key 不重複扣款。
17. 權益過期正確。
18. admin 操作有 audit log。
19. root 緊急暫停商城有效。
20. 一般用戶不能看他人交易細節。
```

---

# Part O — 文件要求

新增：

```text
docs/marketplace_design.md
docs/marketplace_transaction_flow.md
docs/marketplace_dispute_policy.md
docs/marketplace_risk_model.md
docs/marketplace_entitlements.md
docs/marketplace_admin_guide.md
```

README 補充：

```text
商城功能
官方商品
用戶市場
積分支付
平台抽成
糾紛處理
防假交易真轉帳
```

---

# Part P — 分階段落地

## Phase 1 — 官方商城

```text
官方商品
購買
entitlement
ledger
交易紀錄
```

---

## Phase 2 — 用戶市場 MVP

```text
用戶上架
商品審核
escrow 交易
平台抽成
```

---

## Phase 3 — 糾紛中心

```text
糾紛開啟
證據提交
admin 處理
退款/放款
```

---

## Phase 4 — 風控

```text
假交易偵測
洗點偵測
關聯帳號偵測
高風險凍結
```

---

## Phase 5 — 經濟報表

```text
平台收入
用戶收益
官方商品銷售
高風險交易統計
```

---

# Part Q — 完成後回報格式

請用以下格式回報：

```text
# Marketplace 商城系統完成摘要

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

## 官方商城
-

## 用戶市場
-

## 交易 / Escrow
-

## 糾紛處理
-

## 風控 / 假交易防護
-

## 積分 Ledger
-

## 測試結果
-

## 尚未完成
-

## 需要 root 人工確認
-

## 建議下一階段
-
```

---

# Part R — 最高提醒

商城系統的核心不是「買賣頁面」，而是：

```text
可審計交易
可控交付
可回溯積分流
可處理糾紛
可阻止假交易真轉帳
平台抽成可追蹤
官方權益發放可驗證
```

請以交易安全、審計、風控為最高優先級。
