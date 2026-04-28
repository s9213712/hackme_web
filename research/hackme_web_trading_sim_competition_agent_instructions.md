# hackme_web 模擬投資競賽系統 Agent 指令檔 v1.0

> 目標：在 hackme_web 建立「模擬投資」分頁，支援 BTC/USDT、ETH/USDT，以 Binance 公開行情作為價格與 K 線來源。  
> 功能：每位用戶初始模擬資金 10,000 USDT，可進行現貨與合約模擬交易，合約支援 1x~100x 槓桿、做多/做空，全站每週競賽，週五 16:00（Asia/Taipei）結算績效，前幾名發放積分獎勵。  
> 定位：純模擬交易，不涉及真實資金，不接真實交易 API，不提供投資建議。

---

## 0. 最高設計原則

請為 hackme_web 建立一套「模擬投資競賽系統」。

必須遵守：

```text
1. 這是純模擬交易，不得連接真實下單 API。
2. 只使用 Binance 公開 market data。
3. 不需要 Binance API key。
4. 前端不得直接打 Binance，必須透過 hackme_web backend 代理與快取。
5. 使用者不得自行傳入成交價、PnL、equity。
6. 成交價、PnL、強平、排名都必須由後端計算。
7. 排行榜不得暴露 username、email、user_id。
8. 週五 16:00 結算以 Asia/Taipei 為準。
9. 發放積分獎勵必須走 PointsLedgerService。
10. 重複結算不得重複發獎。
```

---

# Part A — 功能總覽

## A1. 使用者功能

一般用戶可使用：

```text
1. 進入 /trading-sim 模擬投資分頁。
2. 查看 BTC/USDT、ETH/USDT 即時價格。
3. 查看 K 線圖。
4. 初始獲得 10,000 USDT 模擬資金。
5. 進行現貨買入 / 賣出。
6. 進行合約開多 / 開空 / 平倉。
7. 合約槓桿可選 1x~100x。
8. 查看自己的帳戶淨值、持倉、交易紀錄、未實現盈虧。
9. 查看本週匿名排行榜。
10. 查看歷史週排行榜。
```

---

## A2. Root/Admin 功能

admin/root 可使用：

```text
1. 查看所有用戶模擬帳戶。
2. 查看異常交易。
3. 暫停模擬交易系統。
4. 恢復模擬交易系統。
5. 手動觸發週結算。
6. 重置特定用戶模擬帳戶。
7. 查看發獎紀錄。
8. 查看 Binance 行情服務狀態。
```

---

## A3. 支援交易商品

MVP 支援：

```text
BTCUSDT
ETHUSDT
```

市場類型：

```text
spot
futures
```

---

# Part B — 行情來源

## B1. Binance 公開 API

使用 Binance 公開 market data。

Spot 參考：

```text
GET /api/v3/ticker/price
GET /api/v3/klines
```

Futures 參考：

```text
GET /fapi/v1/ticker/price
GET /fapi/v1/klines
GET /fapi/v1/premiumIndex
GET /fapi/v1/markPriceKlines
```

要求：

```text
1. 不使用 Binance 私有 API。
2. 不需要 API key。
3. 不執行真實交易。
4. 後端定時抓取價格並快取。
5. 前端只呼叫 hackme_web API。
6. 價格快取建議 1~5 秒。
7. K 線快取建議 30~60 秒。
8. 若 Binance API 失敗，顯示行情暫時不可用。
9. 若價格 stale 超過 10 秒，暫停交易。
```

---

## B2. 價格來源策略

Spot 成交價：

```text
使用 spot ticker price。
```

Futures 成交價與 PnL：

```text
優先使用 mark price。
若 mark price 不可用，使用 futures ticker price，並標記資料來源降級。
```

---

# Part C — 前端頁面

## C1. 路由

新增：

```text
/trading-sim
```

admin/root：

```text
/admin/trading-sim
/root/trading-sim
```

---

## C2. /trading-sim 頁面區塊

頁面需包含：

```text
1. 資產選擇
   - BTC/USDT
   - ETH/USDT

2. 市場類型
   - 現貨
   - 合約

3. K 線圖
   - 1m
   - 5m
   - 15m
   - 1h
   - 4h
   - 1d

4. 下單面板

5. 我的帳戶

6. 持倉列表

7. 交易紀錄

8. 本週排行榜

9. 歷史排行榜
```

---

## C3. 現貨下單面板

現貨功能：

```text
買入
賣出
```

欄位：

```text
symbol
quantity
使用資金比例：25% / 50% / 75% / 100%
預估成交價
預估手續費
確認下單
```

限制：

```text
1. 買入不得超過 cash_balance。
2. 賣出不得超過 spot 持倉。
3. 使用後端最新價格成交。
4. 前端傳入的 price 僅能當顯示，不可作為成交依據。
```

---

## C4. 合約下單面板

合約功能：

```text
開多
開空
平倉
```

欄位：

```text
symbol
side: long / short
margin
leverage: 1x~100x
notional 預估
entry price 預估
liquidation price 預估
fee 預估
確認下單
```

限制：

```text
1. 槓桿 1x~100x。
2. 單筆 margin 不得超過帳戶 equity 的 50%。
3. 每人同時最多 5 筆開倉。
4. 每分鐘最多 20 筆交易。
5. 價格 stale 時禁止交易。
```

---

## C5. 我的帳戶顯示

顯示：

```text
初始資金：10,000 USDT
可用餘額 cash_balance
現貨持倉價值
合約保證金
未實現盈虧
已實現盈虧
帳戶淨值 equity
本週報酬率 return_pct
交易次數
強平次數
```

---

## C6. 排行榜顯示

本週排行榜：

```text
排名
匿名名稱
報酬率
淨值
交易次數
獎勵預估
```

歷史排行榜：

```text
week_id
排名
匿名名稱
報酬率
淨值
獎勵積分
```

不得顯示：

```text
username
email
user_id
真實暱稱
```

---

# Part D — 匿名排行

## D1. 匿名名稱產生

排行榜不得直接顯示 username。

匿名名稱：

```text
display_name = "Trader-" + first_8_to_12_chars(
  HMAC_SHA256(server_secret, user_id + ":" + week_id)
)
```

範例：

```text
Trader-8F3A91C2
```

要求：

```text
1. 每週匿名名稱可不同，避免長期追蹤。
2. root/admin 可在後台查真實用戶。
3. 一般用戶只看匿名名稱。
4. 排行榜 API 不得回傳 user_id / username / email。
```

---

# Part E — 資料表設計

## E1. sim_trading_accounts

```sql
CREATE TABLE sim_trading_accounts (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL UNIQUE,

  initial_balance NUMERIC(30, 10) NOT NULL DEFAULT 10000,
  cash_balance NUMERIC(30, 10) NOT NULL DEFAULT 10000,

  equity NUMERIC(30, 10) NOT NULL DEFAULT 10000,
  realized_pnl NUMERIC(30, 10) NOT NULL DEFAULT 0,
  unrealized_pnl NUMERIC(30, 10) NOT NULL DEFAULT 0,

  spot_value NUMERIC(30, 10) NOT NULL DEFAULT 0,
  futures_margin_used NUMERIC(30, 10) NOT NULL DEFAULT 0,

  status VARCHAR(30) NOT NULL DEFAULT 'active',

  current_week_id VARCHAR(30),

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (initial_balance >= 0),
  CHECK (cash_balance >= 0),
  CHECK (status IN ('active', 'paused', 'banned', 'resetting'))
);
```

---

## E2. sim_spot_holdings

```sql
CREATE TABLE sim_spot_holdings (
  id BIGSERIAL PRIMARY KEY,

  user_id BIGINT NOT NULL,
  symbol VARCHAR(20) NOT NULL,

  quantity NUMERIC(30, 10) NOT NULL DEFAULT 0,
  avg_entry_price NUMERIC(30, 10) NOT NULL DEFAULT 0,

  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (user_id, symbol),
  CHECK (quantity >= 0)
);
```

---

## E3. sim_trading_positions

```sql
CREATE TABLE sim_trading_positions (
  id BIGSERIAL PRIMARY KEY,
  position_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,

  market_type VARCHAR(20) NOT NULL,
  symbol VARCHAR(20) NOT NULL,

  side VARCHAR(20) NOT NULL,
  quantity NUMERIC(30, 10) NOT NULL,
  entry_price NUMERIC(30, 10) NOT NULL,

  leverage INT NOT NULL DEFAULT 1,
  margin NUMERIC(30, 10) NOT NULL DEFAULT 0,

  liquidation_price NUMERIC(30, 10),
  unrealized_pnl NUMERIC(30, 10) NOT NULL DEFAULT 0,
  realized_pnl NUMERIC(30, 10) NOT NULL DEFAULT 0,

  status VARCHAR(30) NOT NULL DEFAULT 'open',

  opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at TIMESTAMP,

  CHECK (market_type IN ('futures')),
  CHECK (side IN ('long', 'short')),
  CHECK (leverage >= 1 AND leverage <= 100),
  CHECK (quantity > 0),
  CHECK (margin >= 0),
  CHECK (status IN ('open', 'closed', 'liquidated'))
);
```

---

## E4. sim_trading_orders

```sql
CREATE TABLE sim_trading_orders (
  id BIGSERIAL PRIMARY KEY,
  order_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,

  market_type VARCHAR(20) NOT NULL,
  symbol VARCHAR(20) NOT NULL,

  order_type VARCHAR(30) NOT NULL,
  side VARCHAR(30) NOT NULL,

  price NUMERIC(30, 10) NOT NULL,
  quantity NUMERIC(30, 10) NOT NULL,
  notional NUMERIC(30, 10) NOT NULL,

  leverage INT NOT NULL DEFAULT 1,
  margin NUMERIC(30, 10) DEFAULT 0,

  fee NUMERIC(30, 10) NOT NULL DEFAULT 0,
  realized_pnl NUMERIC(30, 10) NOT NULL DEFAULT 0,

  position_id BIGINT,

  status VARCHAR(30) NOT NULL DEFAULT 'filled',

  reject_reason TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (market_type IN ('spot', 'futures')),
  CHECK (order_type IN ('market')),
  CHECK (status IN ('filled', 'rejected', 'cancelled', 'liquidated'))
);
```

---

## E5. sim_price_cache

```sql
CREATE TABLE sim_price_cache (
  id BIGSERIAL PRIMARY KEY,

  symbol VARCHAR(20) NOT NULL,
  market_type VARCHAR(20) NOT NULL,

  price NUMERIC(30, 10) NOT NULL,
  mark_price NUMERIC(30, 10),

  source VARCHAR(50) NOT NULL DEFAULT 'binance',

  stale BOOLEAN NOT NULL DEFAULT FALSE,
  fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (symbol, market_type)
);
```

---

## E6. sim_kline_cache

```sql
CREATE TABLE sim_kline_cache (
  id BIGSERIAL PRIMARY KEY,

  symbol VARCHAR(20) NOT NULL,
  market_type VARCHAR(20) NOT NULL,
  interval VARCHAR(10) NOT NULL,

  klines_json TEXT NOT NULL,

  source VARCHAR(50) NOT NULL DEFAULT 'binance',
  fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (symbol, market_type, interval)
);
```

---

## E7. sim_weekly_competitions

```sql
CREATE TABLE sim_weekly_competitions (
  id BIGSERIAL PRIMARY KEY,

  week_id VARCHAR(30) NOT NULL UNIQUE,

  starts_at TIMESTAMP NOT NULL,
  ends_at TIMESTAMP NOT NULL,

  timezone VARCHAR(80) NOT NULL DEFAULT 'Asia/Taipei',

  status VARCHAR(30) NOT NULL DEFAULT 'active',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  settled_at TIMESTAMP,

  CHECK (status IN ('active', 'settling', 'settled', 'cancelled'))
);
```

---

## E8. sim_weekly_rankings

```sql
CREATE TABLE sim_weekly_rankings (
  id BIGSERIAL PRIMARY KEY,

  week_id VARCHAR(30) NOT NULL,
  user_id BIGINT NOT NULL,

  anonymous_name VARCHAR(80) NOT NULL,

  starting_equity NUMERIC(30, 10) NOT NULL DEFAULT 10000,
  ending_equity NUMERIC(30, 10) NOT NULL,
  return_pct NUMERIC(20, 8) NOT NULL,

  trade_count INT NOT NULL DEFAULT 0,
  liquidation_count INT NOT NULL DEFAULT 0,

  rank INT,

  reward_points BIGINT NOT NULL DEFAULT 0,
  reward_ledger_uuid UUID,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (week_id, user_id)
);
```

---

## E9. sim_trading_audit_logs

```sql
CREATE TABLE sim_trading_audit_logs (
  id BIGSERIAL PRIMARY KEY,

  event_type VARCHAR(100) NOT NULL,
  severity VARCHAR(30) NOT NULL DEFAULT 'info',

  actor_user_id BIGINT,
  target_user_id BIGINT,

  related_order_id BIGINT,
  related_position_id BIGINT,
  related_week_id VARCHAR(30),

  message TEXT NOT NULL,
  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical'))
);
```

---

# Part F — 交易規則

## F1. 現貨規則

```text
1. 使用 USDT 買入 BTC/ETH。
2. 賣出不得超過持倉。
3. 成交價使用後端最新 spot price。
4. 模擬手續費：0.1%。
5. 不允許負餘額。
6. 現貨持倉不會強平。
```

現貨買入：

```text
quote_amount = 使用者花費 USDT
fee = quote_amount * 0.001
net_quote = quote_amount - fee
base_quantity = net_quote / price
```

現貨賣出：

```text
gross_quote = quantity * price
fee = gross_quote * 0.001
net_quote = gross_quote - fee
cash_balance += net_quote
```

---

## F2. 合約規則

```text
1. 支援 BTCUSDT、ETHUSDT。
2. 支援 long / short。
3. 槓桿 1x~100x。
4. 開倉需 margin。
5. notional = margin * leverage。
6. quantity = notional / entry_price。
7. 手續費依 notional 計算，建議 0.04%。
8. PnL 使用 mark_price 計算。
```

未實現 PnL：

```text
long:  quantity * (mark_price - entry_price)
short: quantity * (entry_price - mark_price)
```

帳戶 equity：

```text
equity = cash_balance + spot_value + futures_margin_used + unrealized_pnl
```

---

## F3. 合約強平簡化規則

MVP 維持保證金：

```text
maintenance_margin_rate = 0.005 + leverage * 0.0002
maintenance_margin = notional * maintenance_margin_rate
```

若：

```text
margin + unrealized_pnl <= maintenance_margin
```

則強平。

強平後：

```text
position status = liquidated
margin loss
寫入 sim_trading_orders
寫入 audit log
更新 account equity
```

---

## F4. 合約限制

```text
1. leverage >= 1 且 <= 100。
2. 單筆 margin 不得超過 account equity 的 50%。
3. 每人最多同時 5 筆 open positions。
4. 每分鐘最多 20 筆交易。
5. price stale 超過 10 秒禁止交易。
6. Binance 行情失敗時暫停開倉。
```

---

# Part G — 週五 16:00 結算

## G1. 時區

使用：

```text
Asia/Taipei
```

結算時間：

```text
每週五 16:00
```

---

## G2. 結算流程

```text
1. 將當週 competition status 改為 settling。
2. 暫停交易，避免結算中變動。
3. 抓取最新價格。
4. 更新所有帳戶 spot value / futures unrealized_pnl / equity。
5. 計算 return_pct：
   (ending_equity - starting_equity) / starting_equity * 100
6. 依 return_pct 排名。
7. 報酬率相同時：
   a. 較少 liquidation_count 優先
   b. 較少 trade_count 優先
   c. 較早建立帳戶優先
8. 產生匿名排行榜。
9. 發放前幾名積分獎勵。
10. 設定 competition status = settled。
11. 建立下一週 competition。
12. 重置所有模擬帳戶為 10,000 USDT。
13. 清理或封存持倉。
14. 恢復交易。
```

---

## G3. MVP 每週重置

MVP 使用：

```text
每週重置模擬帳戶到 10,000 USDT。
```

理由：

```text
1. 公平競賽。
2. 新用戶可加入。
3. 避免早期大戶長期壟斷。
4. 結算容易。
```

---

## G4. 獎勵規則

建議：

```text
第 1 名：1000 soft_points
第 2 名：700 soft_points
第 3 名：500 soft_points
第 4~10 名：200 soft_points
```

可放入設定：

```yaml
trading_sim:
  weekly_rewards:
    1: 1000
    2: 700
    3: 500
    4-10: 200
```

所有獎勵必須：

```text
PointsLedgerService.credit()
```

ledger：

```text
action_type = sim_trading_weekly_reward
reference_type = sim_weekly_competition
reference_id = week_id
```

---

# Part H — API 設計

## H1. User API

```http
GET  /api/trading-sim/symbols
GET  /api/trading-sim/price?symbol=BTCUSDT&market_type=spot
GET  /api/trading-sim/klines?symbol=BTCUSDT&market_type=spot&interval=1m

GET  /api/trading-sim/account
GET  /api/trading-sim/holdings
GET  /api/trading-sim/positions
GET  /api/trading-sim/orders

POST /api/trading-sim/spot/buy
POST /api/trading-sim/spot/sell

POST /api/trading-sim/futures/open
POST /api/trading-sim/futures/close

GET  /api/trading-sim/leaderboard
GET  /api/trading-sim/competitions/current
GET  /api/trading-sim/competitions/history
```

---

## H2. Admin / Root API

```http
GET  /api/admin/trading-sim/users/:user_id
GET  /api/admin/trading-sim/risk
GET  /api/admin/trading-sim/orders
GET  /api/admin/trading-sim/positions

POST /api/admin/trading-sim/users/:user_id/reset

POST /api/root/trading-sim/settle-week
POST /api/root/trading-sim/pause
POST /api/root/trading-sim/resume
POST /api/root/trading-sim/refresh-prices
GET  /api/root/trading-sim/price-feed-status
```

---

## H3. API 安全要求

```text
1. 使用者只能查自己的 account / orders / positions。
2. 排行榜 API 不得回傳真實 user_id。
3. admin/root API 必須檢查權限。
4. 下單 API 不接受 price / PnL / equity。
5. 下單 API 只接受 symbol、side、quantity 或 margin、leverage 等必要參數。
6. 後端必須重新驗證所有參數。
```

---

# Part I — 後端 Service 設計

## I1. BinanceMarketDataService

必須實作：

```text
get_spot_price(symbol)
get_futures_price(symbol)
get_mark_price(symbol)
get_klines(symbol, market_type, interval)
refresh_price_cache()
refresh_kline_cache()
is_price_stale(symbol, market_type)
```

---

## I2. SimTradingAccountService

必須實作：

```text
get_or_create_account(user_id)
reset_weekly_account(user_id)
update_equity(user_id)
update_all_equities()
calculate_spot_value(user_id)
calculate_unrealized_pnl(user_id)
```

---

## I3. SimSpotTradingService

必須實作：

```text
buy(user_id, symbol, quote_amount)
sell(user_id, symbol, quantity)
get_holdings(user_id)
```

---

## I4. SimFuturesTradingService

必須實作：

```text
open_position(user_id, symbol, side, margin, leverage)
close_position(user_id, position_uuid)
update_unrealized_pnl(user_id)
check_liquidation(user_id)
check_all_liquidations()
calculate_liquidation_price(position)
```

---

## I5. SimCompetitionService

必須實作：

```text
get_current_week()
create_current_week_if_missing()
calculate_rankings(week_id)
settle_week(week_id)
issue_rewards(week_id)
create_next_week()
reset_accounts_for_next_week()
generate_anonymous_name(user_id, week_id)
```

---

## I6. SimTradingRiskService

必須實作：

```text
detect_abnormal_trading()
limit_trade_frequency(user_id)
pause_trading_if_price_feed_unstable()
flag_extreme_leverage_abuse(user_id)
```

---

# Part J — K 線圖

## J1. 前端圖表

可使用：

```text
lightweight-charts
或專案現有圖表套件
```

---

## J2. K 線 API 回傳格式

```json
{
  "symbol": "BTCUSDT",
  "interval": "1m",
  "market_type": "spot",
  "klines": [
    {
      "time": 1710000000,
      "open": 65000,
      "high": 65100,
      "low": 64900,
      "close": 65050,
      "volume": 123.45
    }
  ]
}
```

---

## J3. 圖表要求

```text
1. 支援 BTC/ETH 切換。
2. 支援 spot/futures 切換。
3. 支援 interval 切換。
4. 價格資料失敗時顯示錯誤狀態。
5. K 線資料載入時顯示 loading。
6. 不要讓前端直接打 Binance。
```

---

# Part K — 安全與公平

## K1. 必須防止

```text
1. 使用者自行傳入成交價。
2. 使用者自行傳入 PnL。
3. 使用者繞過後端更新帳戶。
4. 排行榜洩漏 username。
5. 高頻刷交易壓垮系統。
6. 價格 API 失敗導致錯誤成交。
7. 結算重複發獎。
8. 時區錯誤導致提前/延後結算。
9. 使用者利用極端槓桿短時間洗榜。
10. SQL injection / IDOR / 權限繞過。
```

---

## K2. 強制要求

```text
1. 成交價只能由後端 price service 決定。
2. 所有資金變化要寫 sim_trading_orders。
3. 排名只顯示 anonymous_name。
4. 獎勵發放要有 idempotency。
5. 每週結算只能成功執行一次。
6. price stale 超過 10 秒時禁止交易。
7. root 可暫停交易系統。
8. 所有 admin/root 操作寫 audit log。
```

---

# Part L — 背景任務

請新增 background jobs：

```text
sim_refresh_price_cache
sim_refresh_kline_cache
sim_update_equities
sim_check_liquidations
sim_weekly_settlement
sim_detect_abuse
```

建議頻率：

```text
price cache：1~5 秒
kline cache：30~60 秒
equity update：5~10 秒
liquidation check：1~5 秒
weekly settlement：每分鐘檢查是否到週五 16:00
abuse detection：1~5 分鐘
```

---

# Part M — 測試要求

必測：

```text
1. 新用戶初始資金為 10000。
2. 現貨買入扣 USDT 並增加持倉。
3. 現貨賣出不可超過持倉。
4. 現貨手續費正確。
5. 合約 1x~100x 限制有效。
6. 合約 long PnL 正確。
7. 合約 short PnL 正確。
8. 合約手續費正確。
9. 強平邏輯有效。
10. 價格 stale 時禁止交易。
11. Binance API 失敗時系統可降級。
12. 排行榜匿名名稱不洩漏 username。
13. 一般排行榜 API 不回傳 user_id。
14. 週五 16:00 Asia/Taipei 結算。
15. 重複結算不會重複發獎。
16. 獎勵透過 PointsLedgerService 發放。
17. 每週重置帳戶正確。
18. 使用者不能操作別人的帳戶。
19. admin/root 權限檢查正確。
20. root 可暫停 / 恢復交易系統。
```

---

# Part N — 交付項目

請交付：

```text
1. trading sim database migrations
2. BinanceMarketDataService
3. SimTradingAccountService
4. SimSpotTradingService
5. SimFuturesTradingService
6. SimCompetitionService
7. SimTradingRiskService
8. User API routes
9. Admin/root API routes
10. /trading-sim frontend page
11. K 線圖元件
12. 現貨下單面板
13. 合約下單面板
14. 帳戶/持倉/交易紀錄 UI
15. 匿名排行榜 UI
16. 結算 background job
17. 強平 background job
18. 積分獎勵整合
19. tests
20. docs/trading_sim_design.md
21. docs/trading_sim_rules.md
22. docs/trading_sim_settlement_runbook.md
```

---

# Part O — 文件要求

新增：

```text
docs/trading_sim_design.md
docs/trading_sim_rules.md
docs/trading_sim_settlement_runbook.md
docs/trading_sim_risk_model.md
docs/trading_sim_api_reference.md
```

README 補充：

```text
模擬交易說明
非真實投資聲明
支援商品
週結算規則
排行榜匿名化
積分獎勵規則
```

---

# Part P — 完成後回報格式

請用以下格式回報：

```text
# 模擬投資系統完成摘要

## 已完成
-

## 行情來源
-

## 交易功能
-

## 合約 / 槓桿 / 強平
-

## 排行榜匿名化
-

## 週五 16:00 結算
-

## 積分獎勵
-

## 新增資料表
-

## 新增 API
-

## 新增 UI
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

# Part Q — MVP 建議範圍

第一版請優先完成：

```text
1. BTC/USDT、ETH/USDT。
2. 市價單。
3. 現貨買賣。
4. 合約開多 / 開空 / 平倉。
5. 1x~100x 槓桿。
6. 強平簡化模型。
7. K 線圖。
8. 本週匿名排行榜。
9. 週五 16:00 結算。
10. 積分獎勵。
```

第二版再做：

```text
限價單
止盈止損
最大回撤排名
複雜維持保證金模型
戰績頁
公開策略分享
更多幣種
```

---

# Part R — 最高提醒

這是模擬投資遊戲與競賽系統，不是真實金融交易平台。

核心原則：

```text
公平
匿名
可審計
不接真實交易
不暴露用戶身份
不讓前端決定價格或盈虧
不重複發獎
不因價格 API 異常造成錯誤交易
```
