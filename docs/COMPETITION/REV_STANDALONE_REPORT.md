# Standalone Evaluation: `triple_trend_recovery_claude_rev`

Generated: 2026-05-06T18:26:24

**模板標籤**: 趨勢三重接力（Claude rev）
**設計依據**: 競賽 22 模板全 FAIL 的教訓 — 提高 trade_count、移除固定%止盈、首倉 90%、加碼 50%、step=100、MA50 主動出場、18% 寬鬆止損

## Verdict: **FAIL**

❌ **FAIL reasons**: trade_count<5 (avg 2.2); fee-adjusted return negative (-0.62%)

⚠️ **WARNING reasons**: trade_count<10 (avg 2.2)

- 平均報酬: -0.62%
- 最大回撤: 6.07%
- 平均 PF: 19999.80
- 平均交易次數: 2.2
- Walk-forward forward 平均: +0.00%

## 1. 主矩陣（5 資產 × 1h × 5y）

| Asset | Ret% | Trades | Max DD% | PF | Sharpe | Sortino | Win% | Exposure% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | -0.70 | 2 | 2.30 | 0.00 | -0.182 | -0.006 | 0.0 | 0.02 |
| ETH | -0.10 | 3 | 6.07 | 0.00 | +0.012 | +0.001 | 0.0 | 0.08 |
| XRP | -2.43 | 2 | 3.40 | 0.00 | -0.389 | -0.022 | 0.0 | 0.03 |
| BNB | +0.56 | 2 | 4.35 | 99999.00 | +0.057 | +0.003 | 100.0 | 0.08 |
| PAXG | -0.44 | 2 | 0.44 | 0.00 | -0.433 | -0.005 | 0.0 | 0.01 |

## 2. Regime Breakdown

| Regime | Asset | Ret% | DD% | Trades | Note |
|---|---|---:|---:|---:|---|
| btc_bull_2020_2021 | BTC | -0.70 | 2.30 | 2 | ok |
| btc_bear_2022 | BTC | +0.00 | 0.00 | 0 | ok |
| btc_range_2023 | BTC | +0.00 | 0.00 | 0 | ok |
| btc_high_vol_2024 | BTC | +0.00 | 0.00 | 0 | ok |
| btc_low_vol_2023h2 | BTC | +0.00 | 0.00 | 0 | ok |
| btc_bull_2020_2021 | ETH | -0.10 | 6.07 | 3 | ok |
| btc_bear_2022 | ETH | +0.00 | 0.00 | 0 | ok |
| btc_range_2023 | ETH | +0.00 | 0.00 | 0 | ok |
| btc_high_vol_2024 | ETH | +0.00 | 0.00 | 0 | ok |
| btc_low_vol_2023h2 | ETH | +0.00 | 0.00 | 0 | ok |
| btc_bull_2020_2021 | XRP | -2.43 | 3.40 | 2 | ok |
| btc_bear_2022 | XRP | +0.00 | 0.00 | 0 | ok |
| btc_range_2023 | XRP | +0.00 | 0.00 | 0 | ok |
| btc_high_vol_2024 | XRP | +0.00 | 0.00 | 0 | ok |
| btc_low_vol_2023h2 | XRP | +0.00 | 0.00 | 0 | ok |
| btc_bull_2020_2021 | BNB | +0.56 | 4.35 | 2 | ok |
| btc_bear_2022 | BNB | +0.00 | 0.00 | 0 | ok |
| btc_range_2023 | BNB | +0.00 | 0.00 | 0 | ok |
| btc_high_vol_2024 | BNB | +0.00 | 0.00 | 0 | ok |
| btc_low_vol_2023h2 | BNB | +0.00 | 0.00 | 0 | ok |
| btc_bull_2020_2021 | PAXG | -0.44 | 0.44 | 2 | ok |
| btc_bear_2022 | PAXG | +0.00 | 0.00 | 0 | ok |
| btc_range_2023 | PAXG | +0.00 | 0.00 | 0 | ok |
| btc_high_vol_2024 | PAXG | +0.00 | 0.00 | 0 | ok |
| btc_low_vol_2023h2 | PAXG | +0.00 | 0.00 | 0 | ok |

## 3. Walk-Forward

| Phase | Asset | Ret% | DD% | Trades | Note |
|---|---|---:|---:|---:|---|
| train | BTC | -0.70 | 2.30 | 2 | ok |
| validate | BTC | +0.00 | 0.00 | 0 | ok |
| forward | BTC | +0.00 | 0.00 | 0 | ok |
| train | ETH | -0.10 | 6.07 | 3 | ok |
| validate | ETH | +0.00 | 0.00 | 0 | ok |
| forward | ETH | +0.00 | 0.00 | 0 | ok |
| train | XRP | -2.43 | 3.40 | 2 | ok |
| validate | XRP | +0.00 | 0.00 | 0 | ok |
| forward | XRP | +0.00 | 0.00 | 0 | ok |
| train | BNB | +0.56 | 4.35 | 2 | ok |
| validate | BNB | +0.00 | 0.00 | 0 | ok |
| forward | BNB | +0.00 | 0.00 | 0 | ok |
| train | PAXG | -0.44 | 0.44 | 2 | ok |
| validate | PAXG | +0.00 | 0.00 | 0 | ok |
| forward | PAXG | +0.00 | 0.00 | 0 | ok |

## 4. Stress Test 7 場景

| Scenario | Ret% | Trades | DD% | Error |
|---|---:|---:|---:|---|
| flash_crash | -20.96 | 2 | 27.30 | - |
| fake_breakout | +4.32 | 2 | 6.15 | - |
| gap_down | -3.28 | 2 | 9.29 | - |
| low_vol_chop | +0.00 | 0 | 0.00 | - |
| volume_spike_fake_signal | +11.04 | 1 | 0.38 | - |
| stale_price | +11.04 | 1 | 0.38 | - |
| outlier_candle | +11.04 | 1 | 0.38 | - |

## 5. 對比既有 5 個 Claude 模板（5y 平均）

| Template | 5y avg Ret% | 平均交易次數 | 來源 |
|---|---:|---:|---|
| `trend_pyramid_claude` | -0.13% | 2.6 | claude (v1) |
| `triple_trend_recovery_claude_rev` | -0.62% | 2.2 | **claude rev** |
| `golden_cross_dual_ma_claude` | -1.23% | 2.0 | claude (v1) |
| `triple_confirmation_dip_claude` | -1.38% | 2.4 | claude (v1) |
| `bb_breakout_momentum_claude` | -1.95% | 2.0 | claude (v1) |
| `adaptive_profit_ladder_claude` | -2.17% | 2.6 | claude (v1) |
