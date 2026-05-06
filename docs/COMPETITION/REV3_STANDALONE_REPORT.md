# Standalone Evaluation: `auto_search_winner_claude_rev3_return`

Generated: 2026-05-06T21:15:58

**模板標籤**: 自動搜索 rev3（size99 + TP ladder + pyramid）
**設計依據**: 由 `competition_param_search_rev3.py` 對 36 個 TP-ladder 變體（2 size × 3 ladder × 3 sell% × 2 pyramid）跑 5 資產 × 5y 自動選出。

## vs rev2 vs buy_and_hold（核心對照）

| Asset | rev3 winner | rev2 winner | buy_and_hold |
|---|---:|---:|---:|
| BTC | +104.61% (DD 59.75) | +107.40% (DD 76.89) | +46.24% |
| ETH | -38.50% | -38.50% | -30.52% |
| XRP | **+31.31%** | -2.35% | -7.43% |
| BNB | +91.25% (DD 56.23) | +76.08% (DD 71.57) | +3.71% |
| PAXG | +115.07% | +148.49% | +153.80% |
| **平均** | **+60.75%** | +58.23% | +33.16% |
| **vs B&H** | **+27.59pp** ✅ | +25.07pp ✅ | — |

## 進化軌跡

| 版本 | avg ret | DD | trades | walk-forward | FAIL 條件數 |
|---|---:|---:|---:|---:|:---:|
| rev1（人工教訓清單）| -0.62% | 6.07% | 2.2 | +0.00% | 4 |
| rev2（自動 36 候選）| +58.23% | 81.82% | 2.0 | -1.11% | 3 |
| **rev3（自動 36 TP ladder 候選）** | **+60.75%** | 81.82% | **4.0** | **+2.59%** ✅ | **2** |

rev3 **解決了 walk-forward forward 為負的 FAIL 條件**（TP ladder 階梯了結讓 forward 段轉正），剩兩條未過：
- trade_count < 5（4.0，差 1 筆）
- max_DD > 25%（81.82%，被 ETH 拖累）

## TP ladder 真實效果（按資產分）

| Asset | rev2→rev3 trades | rev2→rev3 DD | TP 觸發 |
|---|---|---|---|
| BTC | 2 → **5** | 76.89% → **59.75%** | ✅ TP1+TP2 都觸發，分批了結 |
| ETH | 2 → 2 | 80.88% → 80.88% | ❌ 從沒漲到 +50% |
| XRP | 2 → 4 | 81.82% → 81.82% | ✅ TP1 觸發 |
| BNB | 2 → 5 | 71.57% → **56.23%** | ✅ TP1+TP2 都觸發 |
| PAXG | 2 → 4 | 24.48% → 22.02% | ✅ TP 觸發但漲太快 size 縮太快 |

**TP ladder 對「漲幅 ≥ 50% 的資產」確實能降 DD**（BTC -17pp、BNB -15pp）；對 ETH 這種沒漲到 50% 就轉跌的無能為力。

## Verdict: **FAIL**

❌ **FAIL reasons**: trade_count<5 (avg 4.0); max_DD>25% (81.8%)

⚠️ **WARNING reasons**: trade_count<10 (avg 4.0)

- 平均報酬: +60.75%
- 最大回撤: 81.82%
- 平均 PF: 79999.20
- 平均交易次數: 4.0
- Walk-forward forward 平均: +2.59%

## 1. 主矩陣（5 資產 × 1h × 5y）

| Asset | Ret% | Trades | Max DD% | PF | Sharpe | Sortino | Win% | Exposure% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | +104.61 | 5 | 59.75 | 99999.00 | +0.572 | +0.706 | 100.0 | 98.96 |
| ETH | -38.50 | 2 | 80.88 | 0.00 | +0.228 | +0.283 | 0.0 | 99.54 |
| XRP | +31.31 | 4 | 81.82 | 99999.00 | +0.462 | +0.572 | 100.0 | 99.53 |
| BNB | +91.25 | 5 | 56.23 | 99999.00 | +0.511 | +0.602 | 100.0 | 98.96 |
| PAXG | +115.07 | 4 | 22.02 | 99999.00 | +0.892 | +1.118 | 100.0 | 99.55 |

## 2. Regime Breakdown

| Regime | Asset | Ret% | DD% | Trades | Note |
|---|---|---:|---:|---:|---|
| btc_bull_2020_2021 | BTC | +65.05 | 27.89 | 3 | ok |
| btc_bear_2022 | BTC | -57.97 | 59.75 | 0 | ok |
| btc_range_2023 | BTC | +28.52 | 12.75 | 0 | ok |
| btc_high_vol_2024 | BTC | +29.11 | 15.26 | 0 | ok |
| btc_low_vol_2023h2 | BTC | +35.21 | 5.92 | 0 | ok |
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
| btc_bull_2020_2021 | BNB | +67.68 | 45.81 | 3 | ok |
| btc_bear_2022 | BNB | -47.01 | 55.81 | 0 | ok |
| btc_range_2023 | BNB | -7.21 | 27.08 | 0 | ok |
| btc_high_vol_2024 | BNB | +52.82 | 15.29 | 0 | ok |
| btc_low_vol_2023h2 | BNB | +23.34 | 9.53 | 0 | ok |
| btc_bull_2020_2021 | PAXG | -2.44 | 15.02 | 2 | ok |
| btc_bear_2022 | PAXG | -0.54 | 22.02 | 0 | ok |
| btc_range_2023 | PAXG | +2.51 | 9.11 | 0 | ok |
| btc_high_vol_2024 | PAXG | +20.10 | 15.02 | 1 | ok |
| btc_low_vol_2023h2 | PAXG | +5.64 | 6.33 | 0 | ok |

## 3. Walk-Forward

| Phase | Asset | Ret% | DD% | Trades | Note |
|---|---|---:|---:|---:|---|
| train | BTC | +18.25 | 59.75 | 3 | ok |
| validate | BTC | +75.92 | 25.39 | 1 | ok |
| forward | BTC | -2.50 | 26.74 | 1 | ok |
| train | ETH | -41.16 | 80.88 | 2 | ok |
| validate | ETH | +44.87 | 46.34 | 0 | ok |
| forward | ETH | -28.82 | 62.86 | 0 | ok |
| train | XRP | -57.83 | 81.82 | 2 | ok |
| validate | XRP | +242.48 | 45.15 | 1 | ok |
| forward | XRP | -10.02 | 43.86 | 1 | ok |
| train | BNB | +1.62 | 56.23 | 3 | ok |
| validate | BNB | +79.23 | 33.91 | 1 | ok |
| forward | BNB | +3.87 | 33.30 | 1 | ok |
| train | PAXG | +7.92 | 22.02 | 2 | ok |
| validate | PAXG | +32.24 | 15.33 | 1 | ok |
| forward | PAXG | +50.44 | 16.87 | 1 | ok |

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
| `auto_search_winner_claude_rev3_return` | +60.75% | 4.0 | **claude rev** |
| `trend_pyramid_claude` | -0.13% | 2.6 | claude (v1) |
| `golden_cross_dual_ma_claude` | -1.23% | 2.0 | claude (v1) |
| `triple_confirmation_dip_claude` | -1.38% | 2.4 | claude (v1) |
| `bb_breakout_momentum_claude` | -1.95% | 2.0 | claude (v1) |
| `adaptive_profit_ladder_claude` | -2.17% | 2.6 | claude (v1) |
