# Trading System And Bots

This guide explains the Economy branch trading system, root settings, trading
bots, workflow editor, backtesting, and validation scripts.

The trading system is a simulation and education feature. It is designed to
exercise accounting, auditability, permission checks, and strategy workflows.
It is not a real-money exchange.

## Current Scope

Enabled in this line:

- Spot trading for `BTC/USDT` and `ETH/USDT` display pairs.
- Internal API symbols remain `BTC/POINTS` and `ETH/POINTS`.
- `1 POINT = 1 USDT` for trading display and calculation.
- Market orders, limit orders, cancellation, and scheduled limit-order matching.
- Public reference prices and candlestick chart with Binance, OKX, Coinbase,
  Kraken, Gemini, Bitstamp, and CoinGecko fallbacks where supported.
- Last-good-price fallback with a root-configured staleness window.
- Root-configurable trading fee, order minimum/maximum, price source, and price
  jump threshold.
- DCA bots, node-graph workflow bots, and backtesting.
- Experimental borrow trading: margin long and short selling with original
  margin, maintenance margin, collateral top-up, and liquidation scan.
- Trading stress/security validation script.

Not enabled for normal users in this stage:

- Futures contracts.
- PVP matching.
- Real external settlement.

Root can see reserved futures/PVP switches in settings, but they are disabled by
default and should remain disabled until a separate review stage.

## Funds And Accounting

Normal users trade with their actual PointsChain points. Trading freezes,
unfreezes, debits, credits, fees, and realized profit are all written through
PointsChain. The trading engine must not directly mutate wallet balances.

Root uses a separate simulated trading balance:

- Initial root simulated trading balance: `10000 POINTS`.
- Root can reset this simulated balance from the trading UI.
- Root spot/contract simulation does not write to PointsChain and does not
  affect account points.

The trading funding pool is conservative:

- It starts at `10000 POINTS`.
- It is the lending source for margin long and short borrow trades.
- It only grows from explicit root allocation, trading fees, and borrow
  interest.
- Borrowed principal is debited from the pool when a margin position opens and
  repaid when the position closes.
- User margin profit is paid from the pool; user margin loss, fees, and
  interest return to the pool.
- Borrow interest is floating: the configured base daily rate rises as pool
  utilization increases.
- Borrow interest is accrued by started hour. The engine first tries to deduct
  each accrued interest charge from the user's remaining points through
  PointsChain. If the user does not have enough remaining points, the unpaid
  interest is capitalized into the open margin position cost and affects
  equity, liquidation price, and final close-out.
- It has no automatic money-creation behavior. If the pool cannot cover a
  requested borrow amount, the trade is rejected.

## Spot Trading

Use the trading page to:

1. Select market: `BTC/USDT` or `ETH/USDT`.
2. Choose buy or sell.
3. Choose market or limit order.
4. Enter quantity.
5. Review the estimated notional and fee beside the order button.
6. Submit the order.

Buy orders are rejected when estimated notional plus fee exceeds available
trading points. Sell orders are rejected when quantity exceeds the available
spot position.

The wallet page shows spot details per asset:

- Spot quantity.
- Cost basis.
- Current value.
- Realized/unrealized PnL.
- Sell quantity/price controls.
- Emergency market close button.

Emergency market close sells the whole spot position immediately and charges the
configured spot fee at double rate.

## Price Source And Chart

By default the backend tries public live providers for `BTCUSDT` and `ETHUSDT`.
Execution price fallback is attempted in this order:

1. Binance public ticker.
2. OKX public ticker.
3. Coinbase Exchange product ticker.
4. Kraken public ticker.
5. Gemini public ticker.
6. Bitstamp public ticker.
7. CoinGecko simple price.
8. Last-good cached price within the root-configured staleness window.

If all live providers fail and the last-good price is too old, trading fails
closed instead of using a root-entered manual price.

The frontend shows a candlestick chart for reference. The chart endpoint tries
Binance candles first, then OKX candles, Coinbase Exchange candles, Kraken
OHLC, Gemini candles, and Bitstamp OHLC. The default chart interval is 15
minutes, with other supported intervals available from the UI.

The backend always re-checks the execution price before order execution. The
frontend chart is a reference display, not the source of final settlement.

Root manual pricing is not exposed as a production trading fallback. It should
only exist in legacy/local tests where explicitly enabled by the test harness.

If a live price jump exceeds the configured maximum price jump percent, the
engine raises a circuit-breaker error instead of silently accepting the price.

Future production hardening should replace simple priority fallback with a
weighted reference price: collect several fresh providers, discard stale or
extreme outliers, calculate a median/weighted mean, and halt trading when too
few providers agree. That design avoids accepting a single abnormal exchange
print during extreme markets.

## BTC_trade Signal Panel

The trading page can optionally show a BTC-only signal panel from the separate
`BTC_trade` project. This is a soft integration:

- It only appears when the selected market is `BTC/USDT`.
- It only reads files from the configured `BTC_trade` folder.
- It does not start the other project, import its code, or make trading depend
  on it.
- If the folder or report file is missing, the signal panel stays hidden and
  the trading page continues to work normally.
- The bridge helper now lives in this project at
  `scripts/btc_signal_bridge.py`; the external `BTC_trade` project only needs
  to produce runtime files.

To enable it:

1. Prepare the `BTC_trade` project on the same server.
2. In `BTC_trade`, generate the runtime signal files:

   ```bash
   cd /home/s92137/NN/BTC_trade
   python3 update_data.py
   python3 hourly_check.py --timeframe 4h
   python3 backtest_report.py --timeframe 4h
   ```

3. Log in as `root` in `hackme_web`.
4. Open `安全中心 -> 伺服器設定 -> 計費 -> 交易所參數`.
5. Set `BTC_trade 專案資料夾`, for example:

   ```text
   /home/s92137/NN/BTC_trade
   ```

6. Press `檢查 BTC_trade`.
7. If the check says it is available, press `儲存交易所參數`.
8. Open the trading page and select `BTC/USDT`.

The panel reads the latest line from:

```text
runtime/report_log_4h.jsonl
```

It can also show a compact portfolio/last-trade summary when these files exist:

```text
runtime/portfolio_state_4h.json
runtime/trade_log_4h.json
```

The current reader understands the newer BTC_trade report fields, including
`generated_at`, `strategy_version`, `report_title`, `fear_greed`, `capital`,
`btc`, `total_equity`, `total_pnl_pct`, `report_text`, `telegram_text`, and
`timeframe`.

To bridge BTC_trade trade events into hackme_web simulated spot orders, run the
hackme_web-owned bridge script after BTC_trade generates `trade_log_4h.json`:

```bash
cd /path/to/hackme_web
python3 scripts/btc_signal_bridge.py --btc-trade-dir /home/s92137/NN/BTC_trade --status
python3 scripts/btc_signal_bridge.py --btc-trade-dir /home/s92137/NN/BTC_trade --dry-run
python3 scripts/btc_signal_bridge.py --btc-trade-dir /home/s92137/NN/BTC_trade
```

The bridge expects a normal hackme_web user named `btc_bridge` by default. You
can override this with `--bridge-username` or `BTC_TRADE_BRIDGE_USERNAME`. It
uses the configured market `BTC/USDT` by default and maps BTC_trade events as:

- `ENTRY`: buy the BTC amount from the event, multiplied by `--quantity-scale`.
- `PARTIAL_EXIT`: sell one third of the bridge account's current BTC position.
- `FULL_EXIT`: sell the bridge account's full BTC position.

If the root check reports initialization is needed, run the commands shown in
the root UI from inside the `BTC_trade` directory, then check again.

## Root Trading Settings

Root settings live under the root settings page, billing/trading section.

Important fields:

- Trading enabled: enables or disables the trading subsystem.
- Borrow trading enabled: enables experimental margin long and short selling.
- Borrow interest percent daily: daily interest percentage for borrow positions.
- Margin long financing percent: how much of a long position can be financed.
  Example: `90` means financing 90%, user collateral 10%.
- Short collateral percent: original collateral requirement for short selling.
  Example: `60` means collateral must be at least 60% of notional.
- Maintenance margin percent: threshold used by risk and liquidation checks.
- Price source: public live price providers with last-good cache fallback.
- Max price staleness seconds: how long a cached last-good live price can be
  used when all live providers are unavailable.
- Market fee percent: percentage fee charged on spot/margin orders.
- Market min/max order points: per-order notional boundaries.
- BTC_trade project folder: optional local path for the BTC-only signal panel.
  This should point to the `BTC_trade` project root, not to the `runtime`
  subfolder.

All user-facing and API settings use percent values directly. For example,
`0.3` means `0.3%`; `15` means `15%`.

## Borrow Trading

Borrow trading is experimental and root-controlled.

Margin long:

- User provides collateral.
- The system finances the remaining notional according to the configured margin
  long financing percent.
- Price decreases reduce equity and can trigger maintenance/liquidation risk.

Short selling:

- User provides collateral according to the configured short collateral percent.
- Price increases reduce equity and can trigger maintenance/liquidation risk.

Each open borrow position shows:

- Entry price.
- Principal.
- Original margin.
- Maintenance margin.
- Equity.
- Unrealized PnL.
- Liquidation price estimate.
- Risk status and reason.

Users can add collateral. Root can run the liquidation scan. The scan must
re-check risk before liquidating, so a recovered position is not force-closed
based on stale candidate data.

## Trading Bots

The trading page separates bots into:

- DCA bot.
- Workflow strategy bot.
- Backtest analysis.
- Bot execution records.

Bot execution is manual scan in this stage. This avoids unattended runaway
trading while the strategy system is still evolving.

### DCA Bot

DCA bots repeatedly buy a fixed POINTS budget.

Configuration:

- Market.
- Budget in POINTS per run.
- Interval.
- Optional price upper/lower limits.
- Maximum runs.
- Enabled/disabled.

At scan time, the bot converts budget points to quantity using the current
backend execution price.

### Workflow Strategy Bot

Workflow strategy bots use a node graph generated by
`/trading-workflow-editor.html`.

The graph format contains:

- `nodes`: start, condition, logic, control, and action nodes.
- `edges`: directed connections between node ports.
- input/output ports.
- TRUE/FALSE branches from condition and logic nodes.
- nested AND/OR/NOT decisions through logic nodes.
- control nodes for cooldown and maximum execution count.
- action nodes for buy percent, buy amount, sell percent, close all, or hold.

Execution order:

1. Start node begins graph evaluation.
2. Condition and logic nodes evaluate their input path.
3. Action nodes are considered by priority.
4. Matching action nodes execute by step order.
5. Executed step IDs are remembered so the same batch step is not repeated.
6. Higher-priority actions, such as forced stop loss, win over normal entries.

## Workflow Editor

Open:

```text
/trading-workflow-editor.html
```

Login is required. The page is not public.

Basic workflow:

1. Click "載入範例" to load a complete multi-branch sample.
2. Add condition, logic, control, and action nodes from the toolbox.
3. Click an output port, then click an input port to create an edge.
4. Use condition TRUE/FALSE ports for branches.
5. Use AND/OR/NOT logic nodes for nested decisions.
6. Select a node to edit its condition, operator, cooldown, or action.
7. Check the strategy validation panel.
8. Save or copy the generated readable JSON.
9. Return to the trading page and load the JSON into a workflow bot.

Validation checks include:

- exactly one start node.
- action nodes are connected.
- edge endpoints exist.
- edge ports are valid for the source/target node.
- action percentages are within range.
- warnings for unconnected nodes.

## Backtesting

Backtesting uses the same bot configuration used for live bot scans.

Supported inputs:

- DCA bot config.
- Workflow graph strategy config.
- Market symbol.
- Start/end time.
- Timeframe.
- Initial cash.
- Order points or workflow action sizing.

If candles are not supplied by the frontend, the backend fetches historical
K-lines from Binance for the selected market and timeframe.

Backtest output includes:

- total return percent.
- max drawdown percent.
- win rate percent.
- trade count.
- every simulated trade.
- equity curve.

Backtests do not place real orders, mutate PointsChain, mutate wallet balances,
or write trading ledger entries.

## Reset, Restore, And Verification

Server snapshot/restore should restore trading tables together with normal
server state. Trading verification checks replay spot positions, open-order
locks, funding pool state, root simulated account, and margin collateral locks.

If trading replay or margin collateral validation fails, trading enters safe
mode and write operations are blocked until root handles the issue.

PointsChain restore is separate from server snapshot restore. Trading funds for
normal users still depend on PointsChain as the source of truth.

## Validation Scripts

Use the normal pre-push suite:

```bash
python3 scripts/pre_push_checks.py
```

Focused trading stress/security run:

```bash
PYTHONPATH=. python3 security/trading_stress_pentest.py \
  --base-url https://127.0.0.1:5000 \
  --root-password root \
  --mode full \
  --users 3 \
  --orders-per-user 8 \
  --concurrency 4 \
  --rate 8
```

See [Trading Stress Pentest](security/TRADING_STRESS_PENTEST.md) for all modes
and safety limits.
