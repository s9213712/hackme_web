# 回測效能量測與 Workflow 範本歷史回測

> 本文件記錄兩件事：
> 1. **First-boot 量測機制**（capacity probe）的方法、原理、結果
> 2. **12 個 system workflow 範本**在 5 種 K 線間隔下的歷史 PnL 排名（含相對值閾值改造）

最後更新：2026-05-06

---

## Part 1 — First-boot Capacity Probe（回測機器人本機極限量測）

### 1.1 動機

`backtest_trading_bot()` 接受任意長度的 K 棒做回測，但每根 K 棒都要：
- 跑指標（MA / RSI / KD / BB）
- 評估 workflow graph 的所有 condition node
- 觸發時記帳 + 生 audit event

不同 bot 類別的 per-candle 成本差異很大（例如 `conditional` 只是條件比對，`workflow:swing_bb_ma50` 要算 BB+MA50+stop_loss 三層 condition）。如果 root 把 `trading.backtest_max_candles` cap 設得太大，**最慢的範本**可能在用戶 UI 上跑超時。所以需要一個本機量測，告訴 root 這台機器在某個時間預算內的真實上限是多少。

### 1.2 設計原理

1. **量測單一基準**：不假設「某個策略」具代表性，而是把所有支援的 bot 類別都跑一遍。
2. **取最差為準**：root 設的 cap 必須 ≤ 最慢 bot 的 capacity，否則任一範本選用 max cap 都會超時。
3. **首次啟動才量測**：避免每次 boot 都消耗 ~30-45s。後續啟動讀取已存的量測值。
4. **不阻塞啟動**：在 daemon thread 跑，伺服器啟動流程不等它完成。
5. **保留 root override**：如果 root 已手動設過 cap，後續 probe 不會覆蓋。

### 1.3 量測對象（15 種）

| # | 類別 | 標籤 |
|---|---|---|
| 1 | 基本策略 | `conditional` |
| 2 | 基本策略 | `dca` |
| 3 | 基本策略 | `grid` |
| 4 | Workflow 模板 | `bollinger_reversion` |
| 5 | Workflow 模板 | `breakout_buy` |
| 6 | Workflow 模板 | `dip_buy` |
| 7 | Workflow 模板 | `full_entry_exit` |
| 8 | Workflow 模板 | `kd_momentum` |
| 9 | Workflow 模板 | `ma200_trend_entry` |
| 10 | Workflow 模板 | `ma_pullback` |
| 11 | Workflow 模板 | `risk_guard` |
| 12 | Workflow 模板 | `rsi_scale` |
| 13 | Workflow 模板 | `staged_profit_taking` |
| 14 | Workflow 模板 | `stop_loss` |
| 15 | Workflow 模板 | `swing_bb_ma50` |

### 1.4 演算法

```
probe_candles = 20,000               # 合成 K 棒（不會觸發任何條件，純粹 scan cost）
budget_seconds = 60                  # root 可調，預設 60，範圍 5-600

for strategy in 15_bot_types:
    t0 = time.now()
    backtest_trading_bot(strategy, candles=20K)
    elapsed[strategy] = time.now() - t0

bottleneck = strategy with max(elapsed)
fastest    = strategy with min(elapsed)

capacity_min = floor(budget_seconds / (elapsed[bottleneck] / 20K))
capacity_max = floor(budget_seconds / (elapsed[fastest]    / 20K))
```

`capacity_min` 自動寫入 `trading.backtest_max_candles`（僅當 root 未手動設過時）。  
`capacity_max` 顯示在輸入框旁做為「最快策略可達」的參考。

### 1.5 設定與儲存的 keys

| key | 角色 | 預設 / 範圍 |
|---|---|---|
| `trading.backtest_max_candles` | root 可改的實際 cap | 1,000 – 10,000,000，預設 20,000 |
| `trading.backtest_capacity_time_budget_seconds` | 量測秒數預算 | 5 – 600，預設 60 |
| `trading.backtest_measured_capacity` | 量測到的最差 capacity | 唯讀 |
| `trading.backtest_measured_capacity_max` | 量測到的最佳 capacity | 唯讀 |
| `trading.backtest_capacity_measured_at` | 量測時間戳 | 唯讀 |
| `trading.backtest_capacity_bottleneck` | 最慢策略名稱 | 唯讀 |
| `trading.backtest_capacity_fastest` | 最快策略名稱 | 唯讀 |

### 1.6 本機實測結果（2026-05-06，1 次量測）

```
總量測時間：~41s（daemon thread 跑，不擋啟動）
probe_candles = 20,000
budget = 60s

per-strategy 時序（由快到慢）：
  conditional                       0.203s   98,440 c/s
  dca                               0.240s   83,467 c/s
  grid                              0.676s   29,578 c/s
  workflow:dip_buy                  2.123s    9,418 c/s
  workflow:risk_guard               2.518s    7,941 c/s
  workflow:stop_loss                2.592s    7,716 c/s
  workflow:kd_momentum              2.620s    7,632 c/s
  workflow:breakout_buy             2.791s    7,165 c/s
  workflow:ma_pullback              3.183s    6,282 c/s
  workflow:rsi_scale                3.317s    6,030 c/s
  workflow:ma200_trend_entry        3.321s    6,022 c/s
  workflow:bollinger_reversion      3.553s    5,629 c/s
  workflow:staged_profit_taking     4.118s    4,856 c/s
  workflow:full_entry_exit          4.232s    4,725 c/s
  workflow:swing_bb_ma50            5.480s    3,649 c/s   ← 瓶頸
```

**結論：**
- **最慢 = `workflow:swing_bb_ma50`（3,649 c/s）→ 60s 內 218,974 根** ← 自動套到預設 cap
- **最快 = `conditional`（98,440 c/s）→ 60s 內 5,906,400 根** ← 顯示在輸入框旁參考
- 倍率差距 ~27 倍，所以「不可」用最快策略的數字當 cap。

### 1.7 相關 commits

- `4743714` — root-configurable backtest cap + 60s budget setting
- `add66da` — probe 改成跑所有 15 種 bot，取最差為預設 cap

### 1.8 相關檔案

- `services/trading/backtest_capacity.py` — probe 主邏輯
- `services/server/startup.py:measure_backtest_capacity_if_needed` — 啟動鉤子
- `services/trading/trading_engine.py` — `get_max_backtest_candles()` / `record_backtest_capacity_measurement()` / `_settings_payload()`
- `public/js/50-admin.js` — 前端輸入框 + hint 顯示

---

## Part 2 — Workflow 範本歷史回測（5 種 K 線 × 4 時長）

### 2.1 動機

12 個範本在「shipped 預設行為」下表現如何？哪些範本適合長線、哪些短線？範本中有 4 個用了**絕對價閾值**（如 `price_below 90000`），這在不同價格區間會失準，需要改成相對值才能公平比較。

### 2.2 資料來源

- **API**：Binance public klines (`https://api.binance.com/api/v3/klines`)
- **Symbol**：BTCUSDT
- **目標時長**：5 年（按各 K 線間隔換算根數）
- **窗格**：6mo / 1yr / 3yr / 5yr 切片，從最新往回算
- **初始資金**：100,000 POINTS
- **量測機器**：WSL2 (Linux 6.6.87.2-microsoft-standard-WSL2)，Python 3.10.14，單執行緒
- **資料區間**：~2021-05-06 → 2026-05-06（依 K 線間隔略有差異）

### 2.3 相對值閾值改造

12 個範本中 8 個本來就是相對值（`bb_position`, `ma_position`, `rsi_*`, `kd_*`, `stop_loss_percent`, `take_profit_percent`），4 個用了絕對價：

| 範本 | 原閾值（絕對） | 相對版本 |
|---|---|---|
| `breakout_buy` | `price_above 100000` | `ma_position above MA20`（突破短期均線） |
| `dip_buy` | `price_below 90000` | `rsi_below 35`（弱勢區買入） |
| `full_entry_exit` | `price_below 85000` | `rsi_below 30`（極度超賣才進場） |
| `stop_loss` | `price_below 80000` | `stop_loss_percent 7`（持倉 -7% 停損） |

腳本以 `--use-relative-thresholds` 旗標啟用改造（**不**修改原始 `workflows/system/*.json`，僅執行時 in-memory 套用）。

### 2.4 K 線間隔對應的 5 年根數

| Interval | bars/day | 5y 根數 |
|---|---:|---:|
| 5m | 288 | 525,600 |
| 15m | 96 | 175,200 |
| 1h | 24 | 43,800 |
| 4h | 6 | 10,950 |
| 4d | 0.25 | 456 |

> 4d 因為 Binance API 不支援，腳本內由 1d × 4 重採樣（open=第1日開盤、high/low=4日極值、close=第4日收盤）。

### 2.5 各間隔執行時間

| Interval | 5y 根數 | Fetch 時間 | 回測時間 | 總時間 |
|---|---:|---:|---:|---:|
| 4d | 456 | 0.8s | 2.4s | **3.1s** |
| 4h | 10,950 | 4.0s | 40.5s | **44.5s** |
| 1h | 43,800 | 16.5s | 166.9s | **183.4s** |
| 15m | 175,200 | 63.5s | 659.6s | **723.2s** |
| 5m | 525,600 | 211.8s | 1989.1s | **2200.9s（≈ 36.7 min）** |

> 回測時間隨 K 棒數量約成線性（單純 scan cost），但部分指標（RSI/MA/BB）需要 warmup window，所以 5m 與 4d 的「per-candle 成本」會有些微差異。

### 2.6 實測結果（5y window 排名）

#### 2.6.1 4d 間隔（456 根，相對值）

| 排名 | 模板 | PnL | 交易 | 最大回撤 |
|---:|---|---:|---:|---:|
| 1 | 保守逢低買入（相對 RSI≤35）| **+15.47%** | 1 | 14.57% |
| 2 | MA200 長線趨勢進場 | +14.30% | 1 | 16.64% |
| 3 | KD 動能追蹤 | +10.58% | 1 | 12.50% |
| 4 | RSI 分批買賣 | +8.80% | 2 | 8.86% |
| 5 | 布林通道均值回歸 | +8.06% | 2 | 8.92% |
| 6 | MA 趨勢回踩 | +7.32% | 1 | 12.12% |
| 7 | 突破追價買入（相對 MA20）| +6.32% | 1 | 13.37% |
| 8-10 | (3 個 0-trade 風控模板) | 0.00% | 0 | - |
| 11 | 布林波段 + MA50 支撐 | -1.61% | 2 | 1.61% |
| 12 | 完整進出場策略（相對 RSI≤30）| **-24.03%** | 2 | 29.22% |

#### 2.6.2 4h 間隔（10,950 根，相對值）

| 排名 | 模板 | PnL | 交易 | 最大回撤 |
|---:|---|---:|---:|---:|
| 1 | MA200 長線趨勢進場 | **+16.17%** | 1 | 18.19% |
| 2 | 突破追價買入（相對）| +15.83% | 1 | 18.04% |
| 3 | MA 趨勢回踩 | +12.64% | 1 | 15.04% |
| 4 | 保守逢低買入（相對）| +6.36% | 1 | 10.92% |
| 5 | KD 動能追蹤 | +3.93% | 1 | 9.61% |
| 6 | 布林通道均值回歸 | +2.46% | 2 | 5.26% |
| 7 | RSI 分批買賣 | +2.27% | 2 | 5.89% |
| 8-10 | (3 個 0-trade 風控模板) | 0.00% | 0 | - |
| 11 | 布林波段 + MA50 支撐 | -0.01% | 3 | 2.63% |
| 12 | 完整進出場策略（相對）| **-10.96%** | 2 | 13.11% |

#### 2.6.3 1h 間隔（43,800 根，相對值）

| 排名 | 模板 | PnL | 交易 | 最大回撤 |
|---:|---|---:|---:|---:|
| 1 | MA200 長線趨勢進場 | **+15.69%** | 1 | 18.04% |
| 2 | MA 趨勢回踩 | +14.26% | 1 | 15.84% |
| 3 | 突破追價買入（相對）| +5.59% | 1 | 13.68% |
| 4 | 保守逢低買入（相對）| +4.38% | 1 | 9.95% |
| 5 | KD 動能追蹤 | +4.02% | 1 | 9.75% |
| 6 | 布林通道均值回歸 | +2.32% | 2 | 5.26% |
| 7 | RSI 分批買賣 | +1.16% | 2 | 5.54% |
| 8-10 | (3 個 0-trade 風控模板) | 0.00% | 0 | - |
| 11 | 布林波段 + MA50 支撐 | -0.03% | 3 | 1.80% |
| 12 | 完整進出場策略（相對）| **-8.20%** | 2 | 8.74% |

#### 2.6.4 15m 間隔（175,200 根，相對值）

| 排名 | 模板 | PnL | 交易 | 最大回撤 |
|---:|---|---:|---:|---:|
| 1 | 突破追價買入（相對）| **+6.55%** | 1 | 14.72% |
| 2 | MA200 長線趨勢進場 | +5.70% | 1 | 14.30% |
| 3 | MA 趨勢回踩 | +4.98% | 1 | 12.02% |
| 4 | KD 動能追蹤 | +4.52% | 1 | 10.44% |
| 5 | 保守逢低買入（相對）| +4.10% | 1 | 10.20% |
| 6 | 布林通道均值回歸 | +2.31% | 2 | 5.55% |
| 7 | RSI 分批買賣 | +2.30% | 2 | 5.43% |
| 8-10 | (3 個 0-trade 風控模板) | 0.00% | 0 | - |
| 11 | 布林波段 + MA50 支撐 | -1.56% | 2 | 2.24% |
| 12 | 完整進出場策略（相對）| **-8.15%** | 2 | 11.15% |

#### 2.6.5 5m 間隔（525,600 根，相對值）

| 排名 | 模板 | PnL | 交易 | 最大回撤 |
|---:|---|---:|---:|---:|
| 1 | 突破追價買入（相對 MA20）| **+6.77%** | 1 | 14.87% |
| 2 | MA200 長線趨勢進場 | +6.35% | 1 | 14.67% |
| 3 | MA 趨勢回踩 | +5.15% | 1 | 12.15% |
| 4 | 保守逢低買入（相對 RSI≤35）| +4.59% | 1 | 10.51% |
| 5 | KD 動能追蹤 | +4.36% | 1 | 10.38% |
| 6 | 布林通道均值回歸 | +2.25% | 2 | 5.53% |
| 7 | RSI 分批買賣 | +2.01% | 2 | 5.38% |
| 8-10 | (3 個 0-trade 風控模板) | 0.00% | 0 | - |
| 11 | 布林波段 + MA50 支撐 | -0.66% | 3 | 1.21% |
| 12 | 完整進出場策略（相對）| **-8.62%** | 2 | 10.58% |

### 2.7 跨間隔 5y 第一名比較

| Interval | 第一名 | PnL | 觀察 |
|---|---|---:|---|
| 4d | 保守逢低買入（相對 RSI≤35）| +15.47% | 在低頻週線上，RSI 才能精準抓到「弱勢區」 |
| 4h | MA200 長線趨勢進場 | +16.17% | 趨勢追隨在中頻最有效 |
| 1h | MA200 長線趨勢進場 | +15.69% | 同 4h，但訊號略遜 |
| 15m | 突破追價買入（相對 MA20）| +6.55% | 高頻噪音多，趨勢追隨折損變大 |
| 5m | 突破追價買入（相對 MA20）| +6.77% | 與 15m 同冠軍，但 PnL 略升、回撤略大 |

### 2.8 跨間隔 5y 最後一名比較

| Interval | 最差 | PnL | 觀察 |
|---|---|---:|---|
| 4d | 完整進出場策略 | -24.03% | 在低頻 4d 上，RSI 進場 + 固定停損停利的組合在長多市場最不利 |
| 4h | 完整進出場策略 | -10.96% | 同上，但程度較輕 |
| 1h | 完整進出場策略 | -8.20% | 同上 |
| 15m | 完整進出場策略 | -8.15% | 同上 |
| 5m | 完整進出場策略 | -8.62% | 同上，所有間隔一致最差 |

> **完整進出場策略在所有間隔的 5y window 都墊底**。它的設計（RSI 進場 + 10% 止損 / 15% 止盈）在過去 5 年的長多市場下，停利點被頻繁觸發後賣掉就回不來。

### 2.9 關鍵觀察（綜合 5 個間隔）

1. **長期 5y 的冠軍因 K 線而異**：4d 是 RSI 抓底，4h/1h 是 MA200 趨勢追隨，15m 是 MA20 突破。沒有「萬用第一名」。
2. **完整進出場策略一直墊底（5y）**：固定百分比停利會在長多市場頻繁出場，無法吃到大趨勢。
3. **3 個 exit-only 範本永遠 0 trades**：停利停損風控、分批獲利了結、持倉跌破停損。獨立回測下沒持倉，無法觸發。**預期行為**，建議使用者搭配 entry 模板組合用。
4. **trade_count 普遍仍偏低（1-3 筆）**：即便用相對值，多數範本在 5 年內只觸發一次。原因是進場後沒有再加碼/減碼條件（只有 buy / sell %，沒有 scaling logic）。
5. **時間框架越短 → PnL 越分散**：3yr 在 1h/4h 上多範本可達 +25% 以上，但 5yr 只剩 +15% 左右——表示部分模板在 2024-2025 的回檔期吃到負報酬。
6. **回撤與 PnL 同向**：表現好的趨勢追隨範本（MA200/MA pullback）也都有 ~15-18% 的最大回撤，沒有「高 PnL + 低回撤」的免費午餐。
7. **回測時間隨 K 棒數量幾乎成完美線性**：4d 3.1s → 4h 44.5s → 1h 183s → 15m 723s → 5m 2201s，每升一級時間漲 4-12 倍。5m 5y 的 525,600 根需要 ~37 分鐘，已接近單機可承受的極限。
8. **5m 與 15m 在 5y window 排名極相似**：第 1-7 名順序完全一樣（突破/MA200/MA 回踩/逢低/KD/BB/RSI），PnL 差距 < 0.5pp。意味著：對長窗格（5y）來說，更細的 K 線解析度沒有帶來實質訊號優勢，主要差別在「進場時機點」差幾根 K 棒。

### 2.10 給使用者的選擇建議（基於這份資料）

| 需求 | 建議範本 | 適合間隔 |
|---|---|---|
| 想長期 hold（年單位） | **MA200 長線趨勢進場** / **MA 趨勢回踩** | 1h / 4h |
| 想低頻被動買入 | **保守逢低買入（RSI≤35）** | 4d / 1d |
| 想短期波段（月單位） | 完整進出場策略 | 4h（注意 3yr 以上會虧） |
| 想保守試水溫 | 布林通道均值回歸 / RSI 分批買賣 | 1h / 4h |
| **不適合單獨用** | 3 個 exit-only 模組 | 任何間隔 |

### 2.11 前 3 個間隔（4d/4h/1h）的 6mo 結果

短期窗格下大部分範本是負報酬或 0 trade，這反映 2025-11 ~ 2026-05 的 BTC 震盪行情：

| Interval (6mo) | 唯一正報酬範本 | PnL |
|---|---|---:|
| 4d | 完整進出場策略 | +13.67% |
| 4h | 全部 ≤ 0% | - |
| 1h | 全部 ≤ 0% | - |
| 15m | 全部 ≤ 0% | - |
| 5m | 全部 ≤ 0% | - |

> 完整進出場策略在 4d 6mo 唯一表現好——因為它有止損保護（4d 在這 6 個月內可能還沒觸發 -10% 止損，反而吃到了反彈）。但同樣這個範本在 5yr 一律最差，**短期保護 = 長期錯失**。

### 2.12 相關 commits

- `9cd6a33` — 12 範本 5y BTC 1h 真實回測 + 前端範本面板加歷史 PnL 表（**絕對值閾值版本，shipped 給前端的版本**）
- 本次新增（待 commit）— 5 種 K 線 + 相對值閾值的擴充 benchmark + doc

### 2.13 相關檔案

- `scripts/trading/competition/workflow_template_backtest_benchmark.py` — 主腳本（接 `--interval` / `--use-relative-thresholds`）
- `public/data/workflow_template_benchmarks.json` — 前端用的 1h **絕對值**版（canonical，會被 commit）
- `public/data/workflow_template_benchmarks_<interval>.json` — 各 variant 結果（gitignored，本地查閱用）
- `public/js/56-trading.js:renderTradingWorkflowTemplateBenchmark` — 前端顯示（吃 canonical JSON）

### 2.14 重跑指令

```bash
# 1h 預設值（canonical，會更新前端用的 JSON）
python scripts/trading/competition/workflow_template_backtest_benchmark.py --interval 1h

# 1h 相對值版（產出 _1h_relative.json，gitignored）
python scripts/trading/competition/workflow_template_backtest_benchmark.py --interval 1h --use-relative-thresholds

# 其他間隔
python scripts/trading/competition/workflow_template_backtest_benchmark.py --interval 5m  --use-relative-thresholds
python scripts/trading/competition/workflow_template_backtest_benchmark.py --interval 15m --use-relative-thresholds
python scripts/trading/competition/workflow_template_backtest_benchmark.py --interval 4h  --use-relative-thresholds
python scripts/trading/competition/workflow_template_backtest_benchmark.py --interval 4d  --use-relative-thresholds
```
