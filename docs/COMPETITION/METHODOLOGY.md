# Methodology — Workflow Template Competition

## Parameters

| Parameter | Value | Source |
|---|---|---|
| `interval` | `1h` | competition_config.json |
| `fee_rate_percent` | `0.3` | competition_config.json |
| `slippage_percent_main` | `0.1` | competition_config.json |
| `slippage_percent_sensitivity` | `[0.05, 0.1, 0.2]` | competition_config.json |
| `initial_cash_points` | `100000` | competition_config.json |
| `min_trade_count_warning` | `10` | competition_config.json |
| `min_trade_count_fail` | `5` | competition_config.json |
| `max_drawdown_fail_percent` | `25.0` | competition_config.json |
| `min_profit_factor_pass` | `1.1` | competition_config.json |
| `outlier_pct_threshold` | `50.0` | competition_config.json |

## Assets

- `BTC` (Binance `BTCUSDT`, market `BTC/POINTS`)
- `ETH` (Binance `ETHUSDT`, market `ETH/POINTS`)
- `XRP` (Binance `XRPUSDT`, market `XRP/POINTS`)
- `BNB` (Binance `BNBUSDT`, market `BNB/POINTS`)
- `PAXG` (Binance `PAXGUSDT`, market `PAXG/POINTS`)

## Regimes (BTC-anchored windows)

- `btc_bull_2020_2021`: 2020-04-01 → 2021-11-09 — BTC bull (covid bottom → ATH)
- `btc_bear_2022`: 2021-11-10 → 2022-12-31 — BTC bear (ATH → 16k)
- `btc_range_2023`: 2023-01-01 → 2023-09-30 — BTC range (16k–30k consolidation)
- `btc_high_vol_2024`: 2024-01-01 → 2024-04-30 — BTC high-vol (ETF approval shock)
- `btc_low_vol_2023h2`: 2023-09-01 → 2023-12-31 — BTC low-vol (slow climb)

## Walk-Forward Phases

- `train`: 2020-01-01 → 2023-12-31
- `validate`: 2024-01-01 → 2024-12-31
- `forward`: 2025-01-01 → 2026-05-06

## Stress Scenarios

- `flash_crash`
- `fake_breakout`
- `gap_down`
- `low_vol_chop`
- `volume_spike_fake_signal`
- `stale_price`
- `outlier_candle`

## Verdict Rules

**FAIL** (任一條件):
- trade_count < 5
- max_drawdown_percent > 25
- profit_factor < 1.1
- fee_adjusted_return < 0
- walk_forward_forward_return < 0

**WARNING** (任一條件):
- trade_count < 10
- only_btc_profitable_other_4_assets_loss
- fee_adjusted_return - return_percent > 5

## Output Files

- `docs/COMPETITION/data/data_quality.json` (Stage 1)
- `docs/COMPETITION/data/raw_results.csv` (Stage 2)
- `docs/COMPETITION/data/raw_trades.csv` (Stage 2)
- `docs/COMPETITION/data/asset_matrix.csv` (Stage 2)
- `docs/COMPETITION/data/equity/<template>__<asset>.csv` (Stage 2)
- `docs/COMPETITION/data/regime_matrix.csv` (Stage 3)
- `docs/COMPETITION/data/walk_forward_matrix.csv` (Stage 4)
- `docs/COMPETITION/data/stress_test_matrix.csv` (Stage 5)
- `docs/COMPETITION/data/sensitivity_matrix.csv` (Stage 6)
- `docs/COMPETITION/data/baselines.csv` (Stage 7)
- `docs/COMPETITION/DATA_QUALITY.md` (Stage 1, human readable)
- `docs/COMPETITION/report.md` (Stage 8, human readable)
- `docs/COMPETITION/METHODOLOGY.md` (this file)

## Pipeline Scripts

- `docs/COMPETITION/scripts/competition_stage1_data.py` — fetch + quality check
- `docs/COMPETITION/scripts/competition_stage2_matrix.py` — main matrix
- `docs/COMPETITION/scripts/competition_backfill_equity_ts.py` — bug-fix backfill (BUG-1)
- `docs/COMPETITION/scripts/competition_stage3_regime.py` — regime breakdown
- `docs/COMPETITION/scripts/competition_stage4_walkforward.py` — walk-forward
- `docs/COMPETITION/scripts/competition_stage5_stress.py` — stress test (synthetic)
- `docs/COMPETITION/scripts/competition_stage6_sensitivity.py` — slippage sensitivity
- `docs/COMPETITION/scripts/competition_stage7_baselines.py` — baselines
- `docs/COMPETITION/scripts/competition_stage8_report.py` — report generator (this script)

## Known Issues / Caveats

- **Long-only system**: no template can profit during BTC bear (2022); all 22 are 0% or negative.
- **Conservative position sizing**: most templates use 10–50% of cash per entry, vastly underperforming buy-and-hold which is 100% deployed.
- **PAXG window shorter than 5y at the early end**: PAXG/USDT listed mid-2020 on Binance; we actually got 43,800 candles back to 2021-05-07 (same as others). Pre-2021-05 portion of any regime is `insufficient_data`.
- **BTC bull (2020-04 to 2021-11)**: only ~6 months of overlap with our data start (2021-05-07). Reported regime returns reflect partial overlap.
- **No short / no margin**: spot only per the test spec. Templates that include `margin_short` semantics would not be runnable in this harness.
- **Slippage as flat 0.1%**: per-asset liquidity differences (e.g. PAXG less liquid) not modeled. Sensitivity step 0.05/0.1/0.2 covers conservative range.
- **BUG-1 (resolved)**: Stage 2's equity CSV writer originally used `candle_time`/`candle_iso` keys not present in engine output, leaving all timestamps blank. Backfill script (`competition_backfill_equity_ts.py`) re-derived them from `bar_index` × candle file. Stage 2 source patched. Verified with 1065 → re-runs clean.
