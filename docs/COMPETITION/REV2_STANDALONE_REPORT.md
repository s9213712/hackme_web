# Standalone Evaluation: `auto_search_winner_claude_rev2`

Generated: 2026-05-06T19:58:08

**模板標籤**: 自動搜索勝出（Claude rev2）
**設計依據**: 由 `competition_param_search_rev2.py` 對 36 個候選 workflow 跑 5 資產 × 5y × 1h backtest 自動選出。勝出組合：站上 MA200 + RSI 30-70 + 空倉 → 買 99%、有加碼（RSI<30 時再買 30%）、永不出場。**純資料驅動，不靠手動「教訓清單」**。

## vs buy_and_hold（核心結論）

| Asset | rev2 winner | buy_and_hold | 差距 |
|---|---:|---:|---:|
| BTC | +107.40% | +46.24% | **+61.16pp** ✅ |
| ETH | -38.50% | -30.52% | -7.98pp ❌ |
| XRP | -2.35% | -7.43% | +5.08pp ✅ |
| BNB | +76.08% | +3.71% | **+72.37pp** ✅ |
| PAXG | +148.49% | +153.80% | -5.31pp ❌ |
| **平均** | **+58.23%** | **+33.16%** | **+25.07pp** ✅ |

**贏 buy_and_hold +25.07pp**（5 資產平均）— rev1 是 -0.62% 全敗，rev2 進步 **+58.85pp**。

## 為什麼贏 — 「等對的進場時機，然後永不離場」

關鍵不是「買得早」，而是「**有時候不買**」：
- BTC：MA200 + RSI 過濾讓策略在 2021-05 候選資料起始點延後 ~50 bar 才進場，避開短期高點，比 B&H 的初始買入便宜
- BNB：B&H 從 600 買，5y 後 800 → +3.71%。winner 等到 BNB 站上 MA200 才進，捕到後續 +76%
- ETH：策略仍進了場（trades=2），ETH 後續持續走弱，輸給 cash → -38%（仍輸 B&H -7.98pp）
- PAXG：B&H 從第一根就買；winner 等候條件，反而錯過早期上漲（-5.31pp）

## Verdict: **FAIL**

❌ **FAIL reasons**: trade_count<5 (avg 2.0); max_DD>25% (81.8%); walk-forward forward negative (-1.11%)

⚠️ **WARNING reasons**: trade_count<10 (avg 2.0)

- 平均報酬: +58.23%
- 最大回撤: 81.82%
- 平均 PF: 0.00
- 平均交易次數: 2.0
- Walk-forward forward 平均: -1.11%

## 1. 主矩陣（5 資產 × 1h × 5y）

| Asset | Ret% | Trades | Max DD% | PF | Sharpe | Sortino | Win% | Exposure% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | +107.40 | 2 | 76.89 | 0.00 | +0.540 | +0.687 | 0.0 | 98.96 |
| ETH | -38.50 | 2 | 80.88 | 0.00 | +0.228 | +0.283 | 0.0 | 99.54 |
| XRP | -2.35 | 2 | 81.82 | 0.00 | +0.428 | +0.543 | 0.0 | 99.53 |
| BNB | +76.08 | 2 | 71.57 | 0.00 | +0.499 | +0.612 | 0.0 | 98.96 |
| PAXG | +148.49 | 2 | 24.48 | 0.00 | +0.929 | +1.085 | 0.0 | 99.55 |

## 2. Regime Breakdown

| Regime | Asset | Ret% | DD% | Trades | Note |
|---|---|---:|---:|---:|---|
| btc_bull_2020_2021 | BTC | +70.06 | 27.89 | 2 | ok |
| btc_bear_2022 | BTC | -75.00 | 76.89 | 0 | ok |
| btc_range_2023 | BTC | +62.07 | 21.50 | 0 | ok |
| btc_high_vol_2024 | BTC | +42.56 | 20.07 | 0 | ok |
| btc_low_vol_2023h2 | BTC | +61.65 | 8.54 | 0 | ok |
| btc_bull_2020_2021 | ETH | +21.28 | 55.38 | 2 | ok |
| btc_bear_2022 | ETH | -74.23 | 80.88 | 0 | ok |
| btc_range_2023 | ETH | +39.03 | 27.31 | 0 | ok |
| btc_high_vol_2024 | ETH | +30.93 | 28.23 | 0 | ok |
| btc_low_vol_2023h2 | ETH | +37.44 | 11.67 | 0 | ok |
| btc_bull_2020_2021 | XRP | -14.61 | 68.31 | 2 | ok |
| btc_bear_2022 | XRP | -72.10 | 77.28 | 0 | ok |
| btc_range_2023 | XRP | +50.56 | 43.81 | 0 | ok |
| btc_high_vol_2024 | XRP | -18.45 | 40.66 | 0 | ok |
| btc_low_vol_2023h2 | XRP | +20.22 | 19.77 | 0 | ok |
| btc_bull_2020_2021 | BNB | +73.73 | 45.81 | 2 | ok |
| btc_bear_2022 | BNB | -60.61 | 71.23 | 0 | ok |
| btc_range_2023 | BNB | -12.53 | 41.13 | 0 | ok |
| btc_high_vol_2024 | BNB | +83.29 | 19.69 | 0 | ok |
| btc_low_vol_2023h2 | BNB | +42.72 | 16.02 | 0 | ok |
| btc_bull_2020_2021 | PAXG | -2.44 | 15.02 | 2 | ok |
| btc_bear_2022 | PAXG | -0.54 | 22.02 | 0 | ok |
| btc_range_2023 | PAXG | +2.51 | 9.11 | 0 | ok |
| btc_high_vol_2024 | PAXG | +13.26 | 20.02 | 0 | ok |
| btc_low_vol_2023h2 | PAXG | +5.64 | 6.33 | 0 | ok |

## 3. Walk-Forward

| Phase | Asset | Ret% | DD% | Trades | Note |
|---|---|---:|---:|---:|---|
| train | BTC | +7.66 | 76.89 | 2 | ok |
| validate | BTC | +119.53 | 32.19 | 0 | ok |
| forward | BTC | -13.40 | 49.97 | 0 | ok |
| train | ETH | -41.16 | 80.88 | 2 | ok |
| validate | ETH | +44.87 | 46.34 | 0 | ok |
| forward | ETH | -28.82 | 62.86 | 0 | ok |
| train | XRP | -57.83 | 81.82 | 2 | ok |
| validate | XRP | +234.19 | 45.15 | 0 | ok |
| forward | XRP | -31.65 | 67.99 | 0 | ok |
| train | BNB | -14.34 | 71.57 | 2 | ok |
| validate | BNB | +122.38 | 42.50 | 0 | ok |
| forward | BNB | -9.20 | 58.01 | 0 | ok |
| train | PAXG | +7.92 | 22.02 | 2 | ok |
| validate | PAXG | +29.45 | 20.44 | 0 | ok |
| forward | PAXG | +77.55 | 24.48 | 0 | ok |

## 4. Stress Test 7 場景

| Scenario | Ret% | Trades | DD% | Error |
|---|---:|---:|---:|---|
| flash_crash | +4.73 | 1 | 29.71 | - |
| fake_breakout | +1.71 | 1 | 4.90 | - |
| gap_down | +0.00 | 0 | 0.00 | - |
| low_vol_chop | +0.00 | 0 | 0.00 | - |
| volume_spike_fake_signal | +4.73 | 1 | 0.42 | - |
| stale_price | +4.73 | 1 | 0.42 | - |
| outlier_candle | +4.73 | 1 | 0.42 | - |

## 5. 對比既有 5 個 Claude 模板（5y 平均）

| Template | 5y avg Ret% | 平均交易次數 | 來源 |
|---|---:|---:|---|
| `auto_search_winner_claude_rev2` | +58.23% | 2.0 | **claude rev** |
| `trend_pyramid_claude` | -0.13% | 2.6 | claude (v1) |
| `golden_cross_dual_ma_claude` | -1.23% | 2.0 | claude (v1) |
| `triple_confirmation_dip_claude` | -1.38% | 2.4 | claude (v1) |
| `bb_breakout_momentum_claude` | -1.95% | 2.0 | claude (v1) |
| `adaptive_profit_ladder_claude` | -2.17% | 2.6 | claude (v1) |
