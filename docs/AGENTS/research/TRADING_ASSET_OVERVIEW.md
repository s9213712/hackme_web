# Trading Asset Overview 交易所與積分資產總覽規劃

## 結論

積分頁已開始整合現貨與借貸權益，但仍需要更完整的資產總覽，讓使用者和 root 清楚看到可用積分、現貨估值、借貸倉位、未實現盈虧、利息、風險與資金池壓力。

本功能不是恢復價格可信度 gate；交易可否執行應與價格可信度脫鉤。價格可信度只影響風險提示、估值信心與 root/admin 監控。

## 目標

- 統一顯示資產總價值。
- 區分可用積分、鎖定積分、現貨估值、借貸倉位權益、未實現盈虧、應計利息。
- 顯示估值信心，不阻擋一般交易。
- root 可看到資金池健康度、借貸池壓力與交易所基金風險。

## 使用者資產公式

```text
total_equity =
  available_points
  + locked_points
  + spot_market_value_points
  + margin_position_equity_points
  + unsettled_pnl_points
  - accrued_interest_points
```

注意：

- `account_equity_points` 若已含 available/free margin，不能再直接加總，避免重複計算。
- 借貸倉位應使用 position equity 或由 open positions replay 推算。
- 價格可信度只標示 confidence，不作為交易硬 gate。

## root/admin 指標

```text
exchange_fund_balance
total_user_equity
total_spot_liability
total_margin_exposure
total_borrowed_points
accrued_interest
liquidation_risk_count
low_confidence_price_count
fund_runway_days
insolvency_gap
```

## API 草案

```text
GET /api/economy/portfolio
GET /api/economy/portfolio/history
GET /api/trading/risk-summary
GET /api/admin/trading/exchange-fund-health
GET /api/root/trading/system-solvency
```

## UI 草案

- 積分頁新增總覽卡：
  - 總權益
  - 可用積分
  - 鎖定積分
  - 現貨估值
  - 借貸權益
  - 未實現盈虧
  - 應計利息
- 借貸區塊顯示：
  - 開倉數
  - 借入本金
  - 槓桿
  - 清算距離
  - 利息
- root/admin 顯示：
  - 資金池健康
  - 低信心價格列表
  - 清算風險列表
  - 交易所基金破產風險

## Server Mode 規則

- production：顯示正式資料。
- internal_test/test：顯示 shadow/isolated 資料，不混入 production。
- maintenance/incident_lockdown：read-only。
- superweak：交易功能關閉，但可顯示只讀摘要。

## 測試要求

- 現貨估值包含不同資產。
- 借貸權益包含 open margin positions。
- 不重複計算 available/free margin。
- 價格 confidence low 時仍可下單，但 UI 顯示警告。
- root override 可關閉相關 gate。
- 手機版資產卡不爆版。

## 驗收標準

- 使用者總價值包含現貨與借貸。
- root 可看到交易所整體風險。
- 價格可信度不阻擋交易。
- 所有錯誤在交易操作區附近顯示，不沉到頁底。
