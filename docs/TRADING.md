# Trading System And Bots

This guide explains the Economy branch trading system, root settings, trading
bots, workflow editor, backtesting, and validation scripts.

For a faster operator view, read [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
first. This file keeps the full detailed reference for markets, bots,
workflow JSON, and validation scripts.

The trading system is a simulation and education feature. It is designed to
exercise accounting, auditability, permission checks, and strategy workflows.
It is not a real-money exchange.

## Current Scope

Enabled in this line:

- Spot trading for `BTC/USDT` and `ETH/USDT` display pairs.
- Internal API symbols remain `BTC/POINTS` and `ETH/POINTS`.
- Market/provider definitions are centralized in
  `services/trading_markets.py`, so future points-quoted assets can reuse the
  same live-price, reference-price, and UI mapping pipeline instead of adding
  new hardcoded maps in multiple files.
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
minutes, with other supported intervals available from the UI. The chart now
supports these built-in indicators directly in the trading page:

- Overlay indicators: `MA5`, `MA10`, `MA20`, `MA30`, `MA60`, `EMA12`,
  `EMA26`, `EMA50`, and Bollinger Bands.
- Oscillator subpanel: `RSI14` and `KD(9,3,3)`.

RSI and KD are rendered in a dedicated lower pane so they keep a meaningful
`0-100` scale instead of being squashed onto the same price axis as the
candlesticks.

The backend always re-checks the execution price before order execution. The
frontend chart is a reference display, not the source of final settlement.

The trading page current-price card now refreshes every two seconds through
`GET /api/trading/live-price`, and each successful refresh also recomputes the
order-entry estimate shown beside the buy/sell controls. The same lightweight
poll also refreshes wallet-side trading metrics on the `economy` page,
including spot current value / unrealized PnL, margin unrealized PnL, and the
root virtual total, so those cards move with the latest price instead of
waiting for the slower full dashboard refresh. That route is not purely
read-only: when a live or fused price is successfully resolved, it also
refreshes the cached `trading_markets.manual_price_points` and `price_source`
fields in SQLite so order-entry hints, wallet valuation, dashboard reads, and
later executions share the same latest reference price. If the live price
degrades to fallback / cached mode, the API returns `price_health`,
`fallback_reason`, `excluded_sources`, and `defaulted_market`, and the frontend
shows a yellow warning badge instead of pretending the source is still fully
healthy.

Spot wallet rows also show two unit-price helpers now: `持有成本` is the
current position acquisition cost including the estimated buy-side fee, and
`損益平均價格` is the break-even exit price after also accounting for the
estimated sell-side fee. This prevents the old UI problem where users only saw
gross PnL and had to mentally back-solve fee-adjusted break-even by hand.

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
`BTC_trade` project. This integration is disabled by default and only starts
after `root` explicitly enables it.

- It only appears when the selected market is `BTC/USDT`.
- When enabled, `hackme_web` can clone/update the configured GitHub branch,
  download data, train BTC_trade, run prediction, and generate the report.
- If cloning, training, prediction, or report generation fails, the signal panel
  stays hidden and the trading page continues to work normally.
- The configured folder defaults to `external/BTC_trade`, which is ignored by
  Git and must not be committed.
- The bridge helper now lives in this project at
  `scripts/btc_signal_bridge.py`; the external `BTC_trade` project only needs
  to produce runtime files.

To enable it:

1. Log in as `root` in `hackme_web`.
2. Open `安全中心 -> 伺服器設定 -> 計費 -> 交易所參數`.
3. Enable `啟用 BTC_trade 比特幣信號`.
4. Keep the default repo and branch unless you are testing another BTC_trade
   branch:

   ```text
   repo:   https://github.com/s9213712/BTC_trade.git
   branch: strategy/v15b-plus
   ```

5. Leave the project folder blank to use `external/BTC_trade`, or provide an
   existing local BTC_trade folder.
6. Press `儲存交易所參數`. When the setting changes from disabled to enabled,
   the web UI automatically calls the setup endpoint.
7. You can also press `下載/更新並建置` manually.
8. Press `檢查 BTC_trade` to inspect whether the runtime report is available,
   whether the data file is stale, and whether model / prediction artifacts are
   older than the latest data.
9. Press `一鍵啟動預測` to let `hackme_web` decide whether it must run
   `update_data.py`, `retrain_models.py --timeframe 4h`, and then
   `hourly_check.py --timeframe 4h`.
10. Open the trading page and select `BTC/USDT`.

The setup endpoint performs these steps:

```text
git clone/fetch/checkout/pull
python3 -m pip install <BTC_trade requirements or fallback packages>
python3 update_data.py
python3 retrain_models.py --timeframe 4h
python3 hourly_check.py --timeframe 4h
python3 backtest_report.py --timeframe 4h
```

Failures are reported to `root` as build status. They do not block login,
wallet, trading, or other server functions.

The one-click start path is different from the setup/build path:

- it runs as a background job
- it does not treat long model training as an immediate timeout failure
- it polls until a newer `runtime/report_log_4h.jsonl` appears, or explicitly
  reports that the latest prediction is still within the valid freshness window

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
python3 scripts/btc_signal_bridge.py --btc-trade-dir /path/to/BTC_trade --status
python3 scripts/btc_signal_bridge.py --btc-trade-dir /path/to/BTC_trade --dry-run
python3 scripts/btc_signal_bridge.py --btc-trade-dir /path/to/BTC_trade
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

Root settings live under the root settings page, dedicated `交易所` section.

Important fields:

- Trading enabled: enables or disables the trading subsystem.
- Borrow trading enabled: enables experimental margin long and short selling.
- Borrow APR by asset group:
  - BTC / ETH: default `8% APR`
  - USDT / POINTS: default `10% APR`
- Borrow interest interval hours: default `1`, so interest is accrued hourly.
- Borrow interest minimum hours: default `1`, so even positions shorter than one
  hour are billed as one full started hour.
- Margin long financing percent: how much of a long position can be financed.
  Example: `90` means financing 90%, user collateral 10%.
- Short collateral percent: original collateral requirement for short selling.
  Example: `60` means collateral must be at least 60% of notional.
- Maintenance margin percent: threshold used by risk and liquidation checks.
- Price source: public live price providers with last-good cache fallback.
- Max price staleness seconds: how long a cached last-good live price can be
  used when all live providers are unavailable.
- Market fee percent: percentage fee charged on spot/margin orders. The default
  spot fee is `0.10%`.
- Grid fee discount percent: default `25`, meaning grid orders pay `75%` of the
  configured spot fee rather than the older `50%` shortcut.
- Market min/max order points: per-order notional boundaries.
- BTC_trade project folder: optional local path for the BTC-only signal panel.
  This should point to the `BTC_trade` project root, not to the `runtime`
  subfolder.

All user-facing and API settings use percent values directly. For example,
`0.10` means `0.10%`; `15` means `15%`.

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
- Borrowed asset group APR.
- Accumulated interest.
- Next interest billing time.
- Billing cadence (`every N hours`, `minimum M hours`).
- Break-even price (includes open fee, accumulated interest, and estimated close fee).
- Principal.
- Original margin.
- Maintenance margin.
- Equity.
- Unrealized PnL.
- Per-position liquidation price estimate.
- Risk status and reason.

The borrow-position detail panel recalculates accumulated interest, break-even
price, and liquidation price on the same lightweight live-price refresh cadence
as the trading page. That means both prices can drift upward or downward over
time even if the user does not manually reload the whole dashboard.

Borrow trading now uses a cross-margin account check:

- Account equity = all open borrow-position equity + free trading balance.
- Total borrowed = sum of open borrow principal.
- Total maintenance requirement = sum of open-position maintenance margin.
- Cross margin ratio = account equity / total maintenance requirement.
- Free margin comes from available wallet/trial/root simulated trading balance.
- Adding collateral still freezes points on the selected position, but the
  liquidation decision is account-level.

Root can run the liquidation scan. The scan first checks the account-level
cross margin ratio, then chooses the worst-risk position as the first close
candidate. The engine re-checks account risk before force-closing, so recovered
accounts are not liquidated based on stale candidate data.

## Trading Bots

The trading page separates bots into:

- DCA bot.
- Grid trading bot.
- Workflow strategy bot.
- Backtest analysis.
- Bot execution records.

New enabled DCA bots execute their first run immediately after creation. Later
runs depend on the bot interval/cooldown and the bot scanner.

DCA and workflow bots can extend their `max_runs` limit directly from the bot
card without editing the rest of the configuration.

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
backend execution price. The bot card shows whether the bot is ready, cooling
down, disabled, exhausted, or waiting for the next run.

### Grid Trading Bot

Grid bots are spot-first range bots. They place multiple buy/sell levels inside
a configured price band and try to capture repeated price oscillation between
those levels.

Configuration:

- Market.
- Lower price.
- Upper price.
- Grid count.
- Order amount in POINTS per level.
- Spacing mode (`arithmetic` or `geometric`).

Creation flow:

- Before creation, the page calls `POST /api/trading/grid/preview`.
- The preview is fee-aware and backend-owned. It returns:
  - buy / sell fee percent after the Grid discount
  - break-even spread percent
  - worst-case per-grid gross profit / fee / net profit
  - risk light (`green` / `yellow` / `red`)
- The page estimates the sell-side inventory required for the upper grid
  levels.
- If the user already holds enough spot inventory, the grid can be created
  immediately.
- If inventory is missing, the page offers a底倉 confirmation card so the user
  can buy the missing spot first or continue creating the grid without the
  helper buy.
- `red`: blocked. The spacing is below fee break-even or the order amount is too
  small to buy the minimum asset unit.
- `yellow`: allowed only after a second confirmation because the remaining
  net spread is too thin and can be eaten by slippage.
- `green`: spacing stays profitable after fees.

Runtime behavior:

- Grid bots are scanned manually from the exchange page in this version.
- After a level is filled, the scan places the counter-order on the next level.
- In simulated/CFD-style paths, a price crossing can also fill a resting grid
  level even when no external matching engine event is received.
- Existing grid bots can be loaded into the backtest panel for what-if replay.

The earlier design report is still useful background material:
[Grid Trading Bot Design Report](research/finished/GRID_TRADING_BOT_DESIGN_REPORT.md).

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

Current semantics note:

- `stop_loss_percent` and `take_profit_percent` currently use long-position
  semantics only. They evaluate the scan window low/high against the average
  entry cost of an existing long spot position.
- Short / futures stop-loss and take-profit rules must be implemented as a
  separate condition family; do not assume the current workflow condition types
  are symmetric for short exposure.

Built-in reference templates:

- Conservative dip buy: price threshold plus cooldown.
- Breakout buy: price breakout plus MA50 trend filter.
- Stop-loss guard: position exists plus price threshold close.
- RSI scale in/out: RSI oversold buy and RSI overbought partial sell.
- MA trend pullback: MA50 trend plus RSI pullback entry.
- Bollinger mean reversion: lower-band entry and middle-band partial exit.
- KD momentum tracking: KD strength plus MA20 trend filter.
- Take-profit / stop-loss guard: unrealized PnL percent rules for partial
  profit taking or full close.

These templates are examples, not recommendations. Users should adjust
thresholds and backtest them before enabling live scans.

Workflow files are stored under the project-level `workflows/` directory:

- `workflows/system/` contains built-in templates tracked by Git.
- `workflows/custom/<username>/` contains user-created templates generated at
  runtime and ignored by Git.
- Official templates must include structured explanations: purpose, trigger
  conditions, actions, risk notes, suitable usage, and tuning guidance.
- The trading page loads template options through
  `GET /api/trading/workflow-templates`; saving a custom template writes it
  through `POST /api/trading/workflow-templates/custom`.

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
- Grid bot config.
- Workflow graph strategy config.
- Market symbol.
- Start/end time.
- Timeframe.
- Initial cash.
- Order points or workflow action sizing.

If candles are not supplied by the frontend, the backend downloads historical
K-lines for the selected market and timeframe. It tries Binance first, then
OKX, Coinbase Exchange, Kraken, Gemini, and Bitstamp where the selected
interval is supported. The backtest result shows the provider, provider symbol,
candle count, and first/last candle time so users can verify what data was
used.

Backtest length limits:

- The engine accepts at most `20,000` candles per backtest.
- Internal execution is segmented automatically in contiguous batches of at
  most `10,000` candles, so users no longer need to hand-split ranges that are
  larger than a single batch but still within the total limit.
- The user-facing backtest panel now converts that cap into date guidance.
  When the user picks a start or end datetime, the other field immediately
  shows how far it can be moved at the current timeframe instead of forcing the
  user to understand candle counts.
- When the browser has not loaded chart candles, the backend downloads candles
  automatically. One automatic provider request currently downloads at most
  `1000` candles per provider call, then paginates until it reaches the
  requested backtest range or the total cap.
- If the requested period still exceeds `20,000` candles, the UI and backend
  both reject it explicitly and ask the user to shrink the range or pick a
  larger timeframe.

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

Workflow / backtest validator follow-up:

```bash
PYTHONPATH=. python3 security/trading_workflow_template_validation.py \
  --no-download --limit 200 --out /tmp/trading_workflow_validation_followup

PYTHONPATH=. python3 scripts/trading_backtest_20000_probe.py \
  --include-route --json-out /tmp/trading_backtest_20000_followup.json
```

What these two scripts now prove:

- `trading_workflow_template_validation.py`
  - all 12 official system templates still have valid trigger semantics
  - Bollinger-based templates still pass the `flat sequence` no-false-trigger guard
  - graph workflow templates are validated with trigger scenarios + flat guard +
    engine backtest sanity, instead of an older stale replay oracle
- `trading_backtest_20000_probe.py`
  - all four bot families (`conditional / dca / workflow / grid`) still survive
    a segmented `20,000` candle backtest
  - the route still accepts `20,000` candles and rejects `20,001`
  - `candles < 2` is rejected instead of silently fetching public candles
  - outlier jump candles are skipped with warnings
  - flat Bollinger sequences still do not false trigger
