# Workflow Template Competition — Final Report

Generated: 2026-05-06T18:37:33

> All 22 competition templates were normalized to **1h timeframe** to avoid timeframe shopping. Fee = 0.3% per side, slippage = 0.1% per side. Initial cash = 100,000 POINTS. Backtests run on real Binance BTCUSDT/ETHUSDT/XRPUSDT/BNBUSDT/PAXGUSDT 1h candles (2021-05-07 → 2026-05-06).

Data quality (Stage 1): **WARNING**.  All 5 assets have 43,800 candles with 3 cross-asset Binance maintenance gaps (~10h total), no OHLC violations, no outliers — WARNING is platform-event noise, not data corruption.

## 1. Final Ranking

| Rank | Template | Source | Verdict | Avg Ret% | Max DD% | Avg PF | Avg Trades | Avg Sharpe | Forward% |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `ma200_trend_entry` | 📦 original | **FAIL** | +8.76% | 23.41% | 0.00 | 1.0 | +0.275 | -0.22% |
| 2 | `ma_pullback` | 📦 original | **FAIL** | +5.62% | 18.36% | 0.00 | 1.0 | +0.237 | -0.20% |
| 3 | `dip_buy` | 📦 original | **FAIL** | +3.34% | 14.14% | 0.00 | 1.0 | +0.209 | +0.10% |
| 4 | `kd_momentum` | 📦 original | **FAIL** | +3.01% | 13.75% | 0.00 | 1.0 | +0.197 | +0.14% |
| 5 | `bollinger_reversion` | 📦 original | **FAIL** | +1.65% | 7.52% | 99999.00 | 2.0 | +0.190 | +0.08% |
| 6 | `rsi_scale` | 📦 original | **FAIL** | +0.73% | 7.89% | 39999.60 | 2.0 | +0.129 | +0.04% |
| 7 | `ma200_rsi_reclaim_codex` | ⚙️ codex | **FAIL** | +0.30% | 1.28% | 19999.80 | 0.8 | +0.053 | +0.53% |
| 8 | `risk_guard` | 📦 original | **FAIL** | +0.00% | 0.00% | 0.00 | 0.0 | +0.000 | +0.00% |
| 9 | `staged_profit_taking` | 📦 original | **FAIL** | +0.00% | 0.00% | 0.00 | 0.0 | +0.000 | +0.00% |
| 10 | `stop_loss` | 📦 original | **FAIL** | +0.00% | 0.00% | 0.00 | 0.0 | +0.000 | +0.00% |
| 11 | `trend_pyramid_claude` | 🤖 claude | **FAIL** | -0.13% | 3.15% | 39999.60 | 2.6 | -0.257 | +0.00% |
| 12 | `bb_rsi_reversion_codex` | ⚙️ codex | **FAIL** | -0.32% | 1.37% | 0.50 | 3.0 | -0.156 | +0.00% |
| 13 | `breakout_buy` | 📦 original | **FAIL** | -0.58% | 9.01% | 0.00 | 0.2 | -0.032 | -0.38% |
| 14 | `breakout_guarded_codex` | ⚙️ codex | **FAIL** | -0.73% | 1.76% | 0.00 | 2.0 | -0.380 | +0.00% |
| 15 | `swing_bb_ma50` | 📦 original | **FAIL** | -0.77% | 2.24% | 0.42 | 2.6 | -0.382 | +0.00% |
| 16 | `trend_floor_rebalance_codex` | ⚙️ codex | **FAIL** | -0.85% | 1.58% | 0.13 | 2.2 | -0.565 | +0.00% |
| 17 | `kd_trend_scaleout_codex` | ⚙️ codex | **FAIL** | -0.88% | 1.70% | 0.00 | 2.0 | -0.302 | +0.00% |
| 18 | `golden_cross_dual_ma_claude` | 🤖 claude | **FAIL** | -1.23% | 5.88% | 19999.80 | 2.0 | -0.205 | +0.00% |
| 19 | `triple_confirmation_dip_claude` | 🤖 claude | **FAIL** | -1.38% | 14.32% | 0.99 | 2.4 | -0.170 | +0.00% |
| 20 | `bb_breakout_momentum_claude` | 🤖 claude | **FAIL** | -1.95% | 4.06% | 0.00 | 2.0 | -0.424 | +0.00% |
| 21 | `adaptive_profit_ladder_claude` | 🤖 claude | **FAIL** | -2.17% | 5.09% | 0.19 | 2.6 | -0.325 | +0.00% |
| 22 | `full_entry_exit` | 📦 original | **FAIL** | -4.52% | 16.44% | 19999.80 | 2.0 | -0.072 | +0.00% |

Legend: 📦 original (12), ⚙️ codex (5), 🤖 claude (5). Verdict — PASS = no FAIL no WARNING; WARNING = at least one warning condition; FAIL = at least one fail condition. **All 22 templates failed at least one criterion**.

## 2. Codex vs Claude — Head-to-Head

### ⚙️ Codex 5

| Template | Avg Ret% | Max DD% | Avg Trades | Forward% | Verdict |
|---|---:|---:|---:|---:|---|
| `ma200_rsi_reclaim_codex` | +0.30% | 1.28% | 0.8 | +0.53% | FAIL |
| `bb_rsi_reversion_codex` | -0.32% | 1.37% | 3.0 | +0.00% | FAIL |
| `breakout_guarded_codex` | -0.73% | 1.76% | 2.0 | +0.00% | FAIL |
| `trend_floor_rebalance_codex` | -0.85% | 1.58% | 2.2 | +0.00% | FAIL |
| `kd_trend_scaleout_codex` | -0.88% | 1.70% | 2.0 | +0.00% | FAIL |

### 🤖 Claude 5

| Template | Avg Ret% | Max DD% | Avg Trades | Forward% | Verdict |
|---|---:|---:|---:|---:|---|
| `trend_pyramid_claude` | -0.13% | 3.15% | 2.6 | +0.00% | FAIL |
| `golden_cross_dual_ma_claude` | -1.23% | 5.88% | 2.0 | +0.00% | FAIL |
| `triple_confirmation_dip_claude` | -1.38% | 14.32% | 2.4 | +0.00% | FAIL |
| `bb_breakout_momentum_claude` | -1.95% | 4.06% | 2.0 | +0.00% | FAIL |
| `adaptive_profit_ladder_claude` | -2.17% | 5.09% | 2.6 | +0.00% | FAIL |

**Codex 5 平均**: ret=-0.49%, DD=1.54%
**Claude 5 平均**: ret=-1.37%, DD=6.50%
⚙️ **Codex wins on avg return by +0.88pp**.

## 3. Per-Template Verdict & Diagnosis

### `ma200_trend_entry` — **FAIL**  (original)

- Rank: #1 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +8.76% / 23.41% / +0.275 / +0.306 / +1.62%
- Avg trades / win rate / exposure / PF: 1.0 / 0.0% / 99.29% / 0.00
- Best asset: **PAXG +22.38%**
- Worst asset: **ETH -5.87%**
- Profitable on assets: ['BTC', 'BNB', 'PAXG']
- Walk-forward (2025-2026): -0.22%
- ❌ **FAIL reasons**: trade_count<5 (avg 1.0); walk-forward forward negative (-0.22%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 1.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; forward 段為負，疑似過度擬合 train 段條件

### `ma_pullback` — **FAIL**  (original)

- Rank: #2 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +5.62% / 18.36% / +0.237 / +0.259 / +1.05%
- Avg trades / win rate / exposure / PF: 1.0 / 0.0% / 99.42% / 0.00
- Best asset: **PAXG +17.58%**
- Worst asset: **ETH -4.37%**
- Profitable on assets: ['BTC', 'XRP', 'PAXG']
- Walk-forward (2025-2026): -0.20%
- ❌ **FAIL reasons**: trade_count<5 (avg 1.0); walk-forward forward negative (-0.20%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 1.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; forward 段為負，疑似過度擬合 train 段條件

### `dip_buy` — **FAIL**  (original)

- Rank: #3 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +3.34% / 14.14% / +0.209 / +0.224 / +0.63%
- Avg trades / win rate / exposure / PF: 1.0 / 0.0% / 100.00% / 0.00
- Best asset: **PAXG +15.43%**
- Worst asset: **ETH -3.04%**
- Profitable on assets: ['BTC', 'BNB', 'PAXG']
- Walk-forward (2025-2026): +0.10%
- ❌ **FAIL reasons**: trade_count<5 (avg 1.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 1.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `kd_momentum` — **FAIL**  (original)

- Rank: #4 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +3.01% / 13.75% / +0.197 / +0.211 / +0.56%
- Avg trades / win rate / exposure / PF: 1.0 / 0.0% / 99.95% / 0.00
- Best asset: **PAXG +15.19%**
- Worst asset: **ETH -3.23%**
- Profitable on assets: ['BTC', 'BNB', 'PAXG']
- Walk-forward (2025-2026): +0.14%
- ❌ **FAIL reasons**: trade_count<5 (avg 1.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 1.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `bollinger_reversion` — **FAIL**  (original)

- Rank: #5 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +1.65% / 7.52% / +0.190 / +0.200 / +0.32%
- Avg trades / win rate / exposure / PF: 2.0 / 100.0% / 99.88% / 99999.00
- Best asset: **PAXG +7.68%**
- Worst asset: **ETH -1.59%**
- Profitable on assets: ['BTC', 'BNB', 'PAXG']
- Walk-forward (2025-2026): +0.08%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `rsi_scale` — **FAIL**  (original)

- Rank: #6 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +0.73% / 7.89% / +0.129 / +0.131 / +0.13%
- Avg trades / win rate / exposure / PF: 2.0 / 40.0% / 99.72% / 39999.60
- Best asset: **PAXG +7.97%**
- Worst asset: **ETH -3.10%**
- Profitable on assets: ['BTC', 'PAXG']
- Walk-forward (2025-2026): +0.04%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0); only-BTC profitable (≥3 non-BTC assets negative)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `ma200_rsi_reclaim_codex` — **FAIL**  (codex)

- Rank: #7 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +0.30% / 1.28% / +0.053 / +0.027 / +0.06%
- Avg trades / win rate / exposure / PF: 0.8 / 20.0% / 0.81% / 19999.80
- Best asset: **PAXG +2.63%**
- Worst asset: **BTC -1.13%**
- Profitable on assets: ['PAXG']
- Walk-forward (2025-2026): +0.53%
- ❌ **FAIL reasons**: trade_count<5 (avg 0.8)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 0.8)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 只在 PAXG 獲利，缺乏跨資產通用性

### `risk_guard` — **FAIL**  (original)

- Rank: #8 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +0.00% / 0.00% / +0.000 / +0.000 / +0.00%
- Avg trades / win rate / exposure / PF: 0.0 / 0.0% / 0.00% / 0.00
- Best asset: **BTC +0.00%**
- Worst asset: **BTC +0.00%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 0.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 0.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `staged_profit_taking` — **FAIL**  (original)

- Rank: #9 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +0.00% / 0.00% / +0.000 / +0.000 / +0.00%
- Avg trades / win rate / exposure / PF: 0.0 / 0.0% / 0.00% / 0.00
- Best asset: **BTC +0.00%**
- Worst asset: **BTC +0.00%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 0.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 0.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `stop_loss` — **FAIL**  (original)

- Rank: #10 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: +0.00% / 0.00% / +0.000 / +0.000 / +0.00%
- Avg trades / win rate / exposure / PF: 0.0 / 0.0% / 0.00% / 0.00
- Best asset: **BTC +0.00%**
- Worst asset: **BTC +0.00%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 0.0)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 0.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）

### `trend_pyramid_claude` — **FAIL**  (claude)

- Rank: #11 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.13% / 3.15% / -0.257 / -0.006 / -0.03%
- Avg trades / win rate / exposure / PF: 2.6 / 40.0% / 0.04% / 39999.60
- Best asset: **ETH +0.68%**
- Worst asset: **XRP -0.81%**
- Profitable on assets: ['ETH', 'BNB']
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.6); fee-adjusted return negative (-0.13%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.6)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `bb_rsi_reversion_codex` — **FAIL**  (codex)

- Rank: #12 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.32% / 1.37% / -0.156 / -0.023 / -0.06%
- Avg trades / win rate / exposure / PF: 3.0 / 50.0% / 4.84% / 0.50
- Best asset: **ETH -0.03%**
- Worst asset: **BTC -0.50%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 3.0); PF<1.1 (0.50); fee-adjusted return negative (-0.32%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 3.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `breakout_buy` — **FAIL**  (original)

- Rank: #13 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.58% / 9.01% / -0.032 / -0.022 / -0.12%
- Avg trades / win rate / exposure / PF: 0.2 / 0.0% / 5.67% / 0.00
- Best asset: **ETH +0.00%**
- Worst asset: **BTC -2.91%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): -0.38%
- ❌ **FAIL reasons**: trade_count<5 (avg 0.2); fee-adjusted return negative (-0.58%); walk-forward forward negative (-0.38%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 0.2)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）; forward 段為負，疑似過度擬合 train 段條件

### `breakout_guarded_codex` — **FAIL**  (codex)

- Rank: #14 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.73% / 1.76% / -0.380 / -0.030 / -0.15%
- Avg trades / win rate / exposure / PF: 2.0 / 0.0% / 1.11% / 0.00
- Best asset: **XRP -0.64%**
- Worst asset: **BNB -0.82%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0); fee-adjusted return negative (-0.73%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `swing_bb_ma50` — **FAIL**  (original)

- Rank: #15 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.77% / 2.24% / -0.382 / -0.023 / -0.15%
- Avg trades / win rate / exposure / PF: 2.6 / 30.0% / 0.55% / 0.42
- Best asset: **ETH +0.05%**
- Worst asset: **BNB -1.66%**
- Profitable on assets: ['ETH']
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.6); PF<1.1 (0.42); fee-adjusted return negative (-0.77%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.6)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）; 只在 ETH 獲利，缺乏跨資產通用性

### `trend_floor_rebalance_codex` — **FAIL**  (codex)

- Rank: #16 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.85% / 1.58% / -0.565 / -0.028 / -0.17%
- Avg trades / win rate / exposure / PF: 2.2 / 10.0% / 0.38% / 0.13
- Best asset: **BNB -0.29%**
- Worst asset: **XRP -1.12%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.2); PF<1.1 (0.13); fee-adjusted return negative (-0.85%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.2)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `kd_trend_scaleout_codex` — **FAIL**  (codex)

- Rank: #17 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -0.88% / 1.70% / -0.302 / -0.021 / -0.18%
- Avg trades / win rate / exposure / PF: 2.0 / 0.0% / 0.59% / 0.00
- Best asset: **PAXG -0.75%**
- Worst asset: **BTC -1.01%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0); fee-adjusted return negative (-0.88%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `golden_cross_dual_ma_claude` — **FAIL**  (claude)

- Rank: #18 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -1.23% / 5.88% / -0.205 / -0.005 / -0.25%
- Avg trades / win rate / exposure / PF: 2.0 / 20.0% / 0.06% / 19999.80
- Best asset: **PAXG +0.29%**
- Worst asset: **XRP -2.62%**
- Profitable on assets: ['PAXG']
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0); fee-adjusted return negative (-1.23%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）; 只在 PAXG 獲利，缺乏跨資產通用性

### `triple_confirmation_dip_claude` — **FAIL**  (claude)

- Rank: #19 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -1.38% / 14.32% / -0.170 / -0.017 / -0.29%
- Avg trades / win rate / exposure / PF: 2.4 / 20.0% / 24.84% / 0.99
- Best asset: **XRP +2.70%**
- Worst asset: **BNB -4.59%**
- Profitable on assets: ['BTC', 'XRP']
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.4); PF<1.1 (0.99); fee-adjusted return negative (-1.38%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.4); only-BTC profitable (≥3 non-BTC assets negative)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `bb_breakout_momentum_claude` — **FAIL**  (claude)

- Rank: #20 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -1.95% / 4.06% / -0.424 / -0.030 / -0.39%
- Avg trades / win rate / exposure / PF: 2.0 / 0.0% / 1.05% / 0.00
- Best asset: **BTC -1.58%**
- Worst asset: **BNB -2.60%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0); fee-adjusted return negative (-1.95%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `adaptive_profit_ladder_claude` — **FAIL**  (claude)

- Rank: #21 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -2.17% / 5.09% / -0.325 / -0.022 / -0.44%
- Avg trades / win rate / exposure / PF: 2.6 / 30.0% / 4.84% / 0.19
- Best asset: **PAXG -1.14%**
- Worst asset: **ETH -3.40%**
- Profitable on assets: (none)
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.6); PF<1.1 (0.19); fee-adjusted return negative (-2.17%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.6)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）

### `full_entry_exit` — **FAIL**  (original)

- Rank: #22 of 22
- Avg return / DD / Sharpe / Sortino / CAGR: -4.52% / 16.44% / -0.072 / -0.021 / -0.98%
- Avg trades / win rate / exposure / PF: 2.0 / 20.0% / 5.64% / 19999.80
- Best asset: **ETH +12.38%**
- Worst asset: **BNB -9.44%**
- Profitable on assets: ['ETH']
- Walk-forward (2025-2026): +0.00%
- ❌ **FAIL reasons**: trade_count<5 (avg 2.0); fee-adjusted return negative (-4.52%)
- ⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)
- 💡 改良建議: 讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）; 移除過早出場邏輯（在長多市場 buy-hold 多半勝出）; 只在 ETH 獲利，缺乏跨資產通用性

## 4. Baselines（不參與排名，僅參考）

| Baseline | BTC | ETH | XRP | BNB | PAXG | Avg |
|---|---:|---:|---:|---:|---:|---:|
| **buy_and_hold** | +46.24% | -30.52% | -7.43% | +3.71% | +153.80% | +33.16% |
| **cash_only** | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| **fixed_dca** | +41.96% | -36.73% | -6.62% | -0.33% | +151.35% | +29.93% |
| **simple_grid** | +30.27% | +44.00% | +23.66% | +62.51% | +26.50% | +37.39% |
| **simple_ma_cross** | +0.64% | +8.39% | -1.13% | -0.18% | -0.50% | +1.44% |

> **重要**：buy_and_hold (PAXG) +153.80%、simple_grid (BTC) +48.88% — **所有 22 個競賽模板都明顯遜於 buy_and_hold 與 simple_grid**。原因：競賽模板每次只動 10–50% 資金，在長多市場吃不到完整趨勢；而 baseline 全倉部署。

## 5. Slippage Sensitivity（前 5 名）

| Template | Asset | 0.05% | 0.10% (主跑) | 0.20% |
|---|---|---:|---:|---:|
| `bollinger_reversion` | BTC | +2.36% | +2.35% | +2.33% |
| `bollinger_reversion` | ETH | -1.60% | -1.61% | -1.62% |
| `bollinger_reversion` | XRP | -0.27% | -0.28% | -0.30% |
| `bollinger_reversion` | BNB | +0.08% | +0.07% | +0.05% |
| `bollinger_reversion` | PAXG | +7.68% | +7.67% | +7.66% |
| `dip_buy` | BTC | +4.65% | +4.64% | +4.63% |
| `dip_buy` | ETH | -3.04% | -3.05% | -3.06% |
| `dip_buy` | XRP | -0.73% | -0.73% | -0.74% |
| `dip_buy` | BNB | +0.39% | +0.38% | +0.37% |
| `dip_buy` | PAXG | +15.43% | +15.42% | +15.41% |
| `kd_momentum` | BTC | +4.01% | +4.00% | +3.99% |
| `kd_momentum` | ETH | -3.24% | -3.24% | -3.25% |
| `kd_momentum` | XRP | -1.05% | -1.05% | -1.06% |
| `kd_momentum` | BNB | +0.14% | +0.13% | +0.12% |
| `kd_momentum` | PAXG | +15.18% | +15.18% | +15.16% |
| `ma200_trend_entry` | BTC | +15.85% | +15.84% | +15.83% |
| `ma200_trend_entry` | ETH | -5.88% | -5.88% | -5.90% |
| `ma200_trend_entry` | XRP | -0.54% | -0.54% | -0.56% |
| `ma200_trend_entry` | BNB | +11.95% | +11.95% | +11.93% |
| `ma200_trend_entry` | PAXG | +22.38% | +22.37% | +22.35% |
| `ma_pullback` | BTC | +14.39% | +14.39% | +14.38% |
| `ma_pullback` | ETH | -4.37% | -4.38% | -4.39% |
| `ma_pullback` | XRP | +0.77% | +0.77% | +0.75% |
| `ma_pullback` | BNB | -0.30% | -0.30% | -0.32% |
| `ma_pullback` | PAXG | +17.57% | +17.57% | +17.55% |

## 6. Stress Test 7 個場景（各場景最佳模板）

| Scenario | Best Template | Source | Return |
|---|---|---|---:|
| fake_breakout | `full_entry_exit` | original | +12.50% |
| flash_crash | `adaptive_profit_ladder_claude` | claude | +7.28% |
| gap_down | `full_entry_exit` | original | +1.41% |
| low_vol_chop | (no profitable template) | - | - |
| outlier_candle | `full_entry_exit` | original | +11.82% |
| stale_price | `full_entry_exit` | original | +11.82% |
| volume_spike_fake_signal | `full_entry_exit` | original | +11.82% |

## 7. 結論

- 22 個模板 verdict 分布: **PASS 0 / WARNING 0 / FAIL 22**
- 競賽模板表現均不如 baseline buy-and-hold（PAXG +153.8%, BTC +46.2%）
- 主要 FAIL 原因：trade_count 太少（多數 1-3 筆 over 5y）+ walk-forward forward 階段為 0 或負
- ⚙️ Codex 與 🤖 Claude 模板都沒能贏過原始 12 個的領先群
- ✨ Claude `triple_confirmation_dip_claude` 是 BTC bull regime 的冠軍 (+4.84%)
- ✨ Claude `adaptive_profit_ladder_claude` 是 flash_crash 場景的冠軍 (+7.28%)
- ⚙️ Codex `ma200_rsi_reclaim_codex` 是 walk-forward forward 階段冠軍 (+0.53%)
- 改良方向：1) 提高首次部署比例；2) 縮減出場邏輯；3) 加入加碼/再進場機制讓 trade_count 提升
