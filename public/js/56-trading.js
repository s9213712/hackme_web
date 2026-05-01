'use strict';

let tradingState = {
  markets: [],
  positions: [],
  orders: [],
  fills: [],
  rootReport: null,
  referencePrices: null,
};
let tradingEventsBound = false;
let tradingReferencePriceAbort = null;
let tradingReferenceChartAbort = null;
let tradingReferenceAutoTimer = null;
let tradingReferenceAutoBusy = false;
let tradingReferenceChartAutoTimer = null;
let tradingReferenceChartAutoBusy = false;
let tradingReferenceChartModel = null;
let tradingReferenceHoverIndex = null;
let tradingDashboardAutoTimer = null;
let tradingDashboardAutoBusy = false;

function tradingSetMsg(text, ok = true) {
  const msg = $("trading-msg");
  if (msg && currentModuleTab === "trading") {
    msg.textContent = text || "";
    msg.className = text ? `msg show ${ok ? "ok" : "err"}` : "msg";
  } else if (typeof economySetMsg === "function") {
    economySetMsg(text, ok);
  }
}

async function fetchTradingJson(url, options = {}) {
  await fetchCsrfToken({ force: true });
  const headers = { ...(options.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await apiFetch(API + url, { credentials: "same-origin", ...options, headers });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
  return json;
}

function selectedTradingMarket() {
  const symbol = $("trading-market-select")?.value || "";
  return tradingState.markets.find((market) => market.symbol === symbol) || tradingState.markets[0] || null;
}

function tradingDisplaySymbol(symbol) {
  return String(symbol || "").replace("/POINTS", "/USDT");
}

function formatTradingPointsValue(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function tradingNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function currentTradingPosition(marketSymbol) {
  return tradingState.positions.find((row) => row.market_symbol === marketSymbol) || null;
}

function tradingOrderDraftEstimate() {
  const market = selectedTradingMarket();
  if (!market) return { ok: false, blocking: true, message: "沒有可用交易市場" };
  const side = $("trading-side")?.value || "buy";
  const orderType = $("trading-order-type")?.value || "market";
  const quantity = tradingNumber($("trading-quantity")?.value, 0);
  const limitPrice = tradingNumber($("trading-limit-price")?.value, 0);
  const price = orderType === "limit" ? limitPrice : tradingNumber(market.manual_price_points, 0);
  const feeRate = tradingNumber(market.fee_bps, 0) / 10000;
  if (!quantity || quantity <= 0) {
    return { ok: false, blocking: false, message: "輸入數量後顯示預估金額" };
  }
  if (!price || price <= 0) {
    return { ok: false, blocking: true, message: orderType === "limit" ? "請輸入有效限價" : "目前市場價格不可用，暫停下單" };
  }
  const notional = quantity * price;
  const fee = Math.max(0, notional * feeRate);
  const funding = tradingState.funding || {};
  const availablePoints = tradingNumber(funding.available_points, 0);
  const position = currentTradingPosition(market.symbol);
  const positionQuantity = tradingNumber(position?.quantity, 0);
  const lockedQuantity = tradingNumber(position?.locked_quantity, 0);
  const sellableQuantity = Math.max(0, positionQuantity - lockedQuantity);
  if (side === "buy") {
    const total = notional + fee;
    return {
      ok: total <= availablePoints,
      blocking: total > availablePoints,
      side,
      quantity,
      price,
      notional,
      fee,
      total,
      availablePoints,
      message: total > availablePoints
        ? `買入預估 ${formatTradingPointsValue(total)} 點（含手續費 ${formatTradingPointsValue(fee)}），超過可用 ${formatTradingPointsValue(availablePoints)} 點`
        : `買入預估 ${formatTradingPointsValue(total)} 點（成交 ${formatTradingPointsValue(notional)} + 手續費 ${formatTradingPointsValue(fee)}）`,
    };
  }
  const net = Math.max(0, notional - fee);
  return {
    ok: quantity <= sellableQuantity,
    blocking: quantity > sellableQuantity,
    side,
    quantity,
    price,
    notional,
    fee,
    total: net,
    sellableQuantity,
    message: quantity > sellableQuantity
      ? `賣出 ${formatTradingPointsValue(quantity)} 超過可賣現貨 ${formatTradingPointsValue(sellableQuantity)}`
      : `賣出預估收入 ${formatTradingPointsValue(net)} 點（成交 ${formatTradingPointsValue(notional)} - 手續費 ${formatTradingPointsValue(fee)}）`,
  };
}

function updateTradingOrderEstimate() {
  const estimate = tradingOrderDraftEstimate();
  const target = $("trading-order-estimate");
  const submitBtn = $("trading-submit-order-btn");
  if (target) {
    target.textContent = estimate.message || "";
    target.style.color = estimate.blocking ? "#ff6b7a" : "var(--muted)";
  }
  if (submitBtn) submitBtn.disabled = !!estimate.blocking;
  return estimate;
}

function syncTradingOrderSideTheme() {
  const side = $("trading-side")?.value === "sell" ? "sell" : "buy";
  const form = $("trading-order-form");
  const submitBtn = $("trading-submit-order-btn");
  if (form) {
    form.classList.toggle("trading-order-buy", side === "buy");
    form.classList.toggle("trading-order-sell", side === "sell");
  }
  if (submitBtn) {
    submitBtn.classList.toggle("trading-submit-buy", side === "buy");
    submitBtn.classList.toggle("trading-submit-sell", side === "sell");
    submitBtn.textContent = side === "buy" ? "買入下單" : "賣出下單";
  }
}

function rootVirtualSpotValue(positions = [], markets = []) {
  const marketMap = new Map(markets.map((market) => [market.symbol, Number(market.manual_price_points || 0)]));
  return positions.reduce((total, row) => {
    const quantity = Number(row.quantity || 0);
    const price = marketMap.get(row.market_symbol) || 0;
    if (!Number.isFinite(quantity) || !Number.isFinite(price)) return total;
    return total + (quantity * price);
  }, 0);
}

function tradingPositionLabel(row) {
  return `${tradingDisplaySymbol(row.market_symbol)} ${formatTradingPointsValue(row.quantity || 0)}`;
}

function economySpotMarkets(markets = []) {
  const desiredAssets = ["BTC", "ETH"];
  return desiredAssets.map((asset) => (
    markets.find((market) => String(market.base_asset || "").toUpperCase() === asset)
    || markets.find((market) => String(market.symbol || "").toUpperCase().startsWith(`${asset}/`))
    || { symbol: `${asset}/POINTS`, base_asset: asset, manual_price_points: 0, fee_bps: 0, price_source: "-" }
  ));
}

function spotPositionNumber(position, key) {
  return tradingNumber(position?.[key], 0);
}

function spotPositionTotalQuantity(position) {
  return spotPositionNumber(position, "quantity") + spotPositionNumber(position, "locked_quantity");
}

function tradingSpotPnl(position, market) {
  if (position && position.unrealized_pnl_points !== undefined) {
    return tradingNumber(position.unrealized_pnl_points, 0);
  }
  const quantity = spotPositionTotalQuantity(position);
  const costBasis = tradingSpotCostBasis(position, market);
  const currentValue = tradingSpotCurrentValue(position, market);
  if (!quantity || !costBasis || !currentValue) return 0;
  return currentValue - costBasis;
}

function tradingSpotFee(value, market, multiplier = 1) {
  const feeRate = tradingNumber(market?.fee_bps, 0) * Number(multiplier || 1) / 10000;
  return Math.max(0, Number(value || 0) * feeRate);
}

function tradingSpotCurrentValue(position, market) {
  if (position && position.current_value_points !== undefined) {
    return tradingNumber(position.current_value_points, 0);
  }
  const quantity = spotPositionTotalQuantity(position);
  const currentPrice = tradingNumber(market?.manual_price_points, 0);
  return quantity > 0 && currentPrice > 0 ? quantity * currentPrice : 0;
}

function tradingSpotCostBasis(position, market) {
  if (position && position.cost_basis_points !== undefined) {
    return tradingNumber(position.cost_basis_points, 0);
  }
  const quantity = spotPositionTotalQuantity(position);
  const avgCost = spotPositionNumber(position, "avg_cost_points");
  const currentValue = tradingSpotCurrentValue(position, market);
  if (!quantity || !avgCost) return 0;
  const buyNotional = quantity * avgCost;
  const buyFeeEstimate = tradingSpotFee(buyNotional, market);
  const sellFeeEstimate = tradingSpotFee(currentValue, market);
  return buyNotional + buyFeeEstimate + sellFeeEstimate;
}

function economySpotRowForSymbol(symbol) {
  return Array.from(document.querySelectorAll("[data-economy-spot-row]"))
    .find((row) => row.dataset.economySpotRow === symbol) || null;
}

function renderEconomySpotPositionDetails(positions = [], markets = []) {
  const list = $("economy-spot-position-detail-list");
  if (!list) return;
  const positionMap = new Map(positions.map((row) => [row.market_symbol, row]));
  const rows = economySpotMarkets(markets);
  list.innerHTML = rows.map((market) => {
    const symbol = market.symbol;
    const position = positionMap.get(symbol) || null;
    const availableQuantity = spotPositionNumber(position, "quantity");
    const locked = spotPositionNumber(position, "locked_quantity");
    const quantity = availableQuantity + locked;
    const sellable = Math.max(0, availableQuantity);
    const currentPrice = tradingNumber(market.manual_price_points, 0);
    const costBasis = tradingSpotCostBasis(position, market);
    const currentValue = tradingSpotCurrentValue(position, market);
    const pnl = tradingSpotPnl(position, market);
    const realizedPnl = tradingNumber(position?.realized_pnl_points, 0);
    const totalFee = tradingNumber(position?.total_fee_points, 0);
    const pnlClass = pnl > 0 ? "positive" : (pnl < 0 ? "negative" : "");
    const realizedClass = realizedPnl > 0 ? "positive" : (realizedPnl < 0 ? "negative" : "");
    return `
      <div class="trading-spot-row" data-economy-spot-row="${sanitize(symbol)}" data-sellable="${sanitize(String(sellable))}">
        <div>
          <strong>${sanitize(tradingDisplaySymbol(symbol))}</strong>
          <div class="drive-card-sub">${sanitize(market.price_source || "-")}</div>
        </div>
        <div class="trading-spot-metric">
          <span>現貨數</span>
          <b>${formatTradingPointsValue(quantity)}</b>
          <small class="drive-card-sub">可賣 ${formatTradingPointsValue(sellable)}${locked ? ` · 鎖定 ${formatTradingPointsValue(locked)}` : ""}</small>
        </div>
        <div class="trading-spot-metric">
          <span>成本價（總額）</span>
          <b>${costBasis ? formatTradingPointsValue(costBasis) : "-"}</b>
          <small class="drive-card-sub">含買入手續費與預估賣出手續費</small>
        </div>
        <div class="trading-spot-metric">
          <span>目前部位價值</span>
          <b>${currentValue ? formatTradingPointsValue(currentValue) : "-"}</b>
          <small class="drive-card-sub">現價 ${currentPrice ? formatTradingPointsValue(currentPrice) : "-"}</small>
        </div>
        <div class="trading-spot-metric">
          <span>盈虧</span>
          <b class="trading-spot-pnl ${pnlClass}">${pnl >= 0 ? "+" : ""}${formatTradingPointsValue(pnl)} 點</b>
          <small class="drive-card-sub">未實現</small>
        </div>
        <div class="trading-spot-metric">
          <span>已實現盈虧</span>
          <b class="trading-spot-pnl ${realizedClass}">${realizedPnl >= 0 ? "+" : ""}${formatTradingPointsValue(realizedPnl)} 點</b>
          <small class="drive-card-sub">累計手續費 ${formatTradingPointsValue(totalFee)}</small>
        </div>
        <div class="trading-spot-actions">
          <div class="field">
            <label>賣出數量</label>
            <input type="number" min="0" step="0.00000001" placeholder="${sellable ? formatTradingPointsValue(sellable) : "0"}" data-economy-spot-qty="${sanitize(symbol)}" />
          </div>
          <div class="field">
            <label>限價</label>
            <input type="number" min="1" step="1" placeholder="${currentPrice ? formatTradingPointsValue(currentPrice) : "-"}" data-economy-spot-price="${sanitize(symbol)}" />
          </div>
          <button class="btn" type="button" data-economy-spot-limit="${sanitize(symbol)}" ${sellable <= 0 ? "disabled" : ""}>確認</button>
          <button class="btn btn-danger" type="button" data-economy-spot-market-close="${sanitize(symbol)}" ${sellable <= 0 ? "disabled" : ""}>市價平倉</button>
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-economy-spot-limit]").forEach((btn) => {
    btn.addEventListener("click", () => submitEconomySpotSell(btn.dataset.economySpotLimit || "", "limit"));
  });
  list.querySelectorAll("[data-economy-spot-market-close]").forEach((btn) => {
    btn.addEventListener("click", () => submitEconomySpotSell(btn.dataset.economySpotMarketClose || "", "market"));
  });
}

function renderEconomyMarginPositionDetails(rows = []) {
  const list = $("economy-margin-position-detail-list");
  if (!list) return;
  const activeRows = rows.filter((row) => row.status === "open");
  if (!activeRows.length) {
    list.innerHTML = `<div class="drive-empty">尚無進階倉位</div>`;
    return;
  }
  list.innerHTML = activeRows.map((row) => tradingMarginPositionRow(row, "economy")).join("");
  list.querySelectorAll("[data-economy-margin-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeTradingMarginPosition(btn.dataset.economyMarginClose || ""));
  });
  list.querySelectorAll("[data-economy-margin-add-collateral]").forEach((btn) => {
    btn.addEventListener("click", () => addTradingMarginCollateral(btn.dataset.economyMarginAddCollateral || "", "economy"));
  });
}

function tradingMarginRiskText(row) {
  const risk = row?.risk || {};
  const ratio = risk.maintenance_ratio_percent ?? row.maintenance_ratio_percent;
  const status = risk.risk_status || row.risk_status || "normal";
  const reason = risk.risk_reason || row.risk_reason || "";
  const ratioText = ratio === null || ratio === undefined ? "無法計算" : `${formatTradingPointsValue(ratio)}%`;
  const statusLabel = status === "liquidation" ? "清算風險"
    : (status === "warning" ? "維持率偏低"
      : (status === "short_price_risk" ? "放空價格風險" : "正常"));
  return { ratioText, statusLabel, reason };
}

function tradingMarginPositionRow(row, scope = "trading") {
  const typeLabel = row.position_label || (row.position_type === "short" ? "借券放空" : "融資買入");
  const principal = tradingNumber(row.principal_points, 0);
  const collateral = tradingNumber(row.risk?.initial_margin_points ?? row.initial_margin_points ?? row.collateral_points, 0);
  const fee = tradingNumber(row.open_fee_points, 0);
  const interest = tradingNumber(row.risk?.interest_points ?? row.interest_points, 0);
  const entry = tradingNumber(row.entry_price_points, 0);
  const currentPrice = tradingNumber(row.risk?.price_points ?? row.current_price_points, 0);
  const equity = tradingNumber(row.risk?.equity_after_points ?? row.equity_after_points, 0);
  const maintenance = tradingNumber(row.risk?.maintenance_margin_points ?? row.risk?.maintenance_points ?? row.maintenance_margin_points ?? row.maintenance_points, 0);
  const initialMarginBps = tradingNumber(row.risk?.initial_margin_bps ?? row.initial_margin_bps, 0);
  const maintenanceBps = tradingNumber(row.risk?.maintenance_margin_bps ?? row.risk?.maintenance_bps ?? row.maintenance_margin_bps, 0);
  const unrealizedPnl = tradingNumber(row.risk?.unrealized_pnl_points ?? row.unrealized_pnl_points, 0);
  const liquidationPrice = tradingNumber(row.risk?.liquidation_price_points ?? row.liquidation_price_points, 0);
  const pnlClass = unrealizedPnl > 0 ? "positive" : (unrealizedPnl < 0 ? "negative" : "");
  const leverageHint = collateral > 0 ? `${(principal / collateral).toFixed(2)}x 風險倍數` : "未提供風險倍數";
  const riskText = tradingMarginRiskText(row);
  const prefix = scope === "economy" ? "economy-" : "";
  return `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(typeLabel)} · ${sanitize(tradingDisplaySymbol(row.market_symbol || "-"))} · ${sanitize(row.quantity || "0")}</strong>
        <div class="drive-card-sub">
          入場 ${formatTradingPointsValue(entry)} · 現價 ${currentPrice ? formatTradingPointsValue(currentPrice) : "-"} · 本金 ${formatTradingPointsValue(principal)} · 原始保證金 ${formatTradingPointsValue(collateral)}
        </div>
        <div class="drive-card-sub">
          原始保證金率 ${formatTradingPointsValue(initialMarginBps / 100)}% · 維持率 ${sanitize(riskText.ratioText)} · 權益 ${formatTradingPointsValue(equity)} · 維持保證金 ${formatTradingPointsValue(maintenance)}（${formatTradingPointsValue(maintenanceBps / 100)}%） · ${sanitize(riskText.statusLabel)}
        </div>
        <div class="drive-card-sub">
          未實現盈虧 <b class="trading-spot-pnl ${pnlClass}">${unrealizedPnl >= 0 ? "+" : ""}${formatTradingPointsValue(unrealizedPnl)} 點</b> · 強平價格 ${liquidationPrice ? formatTradingPointsValue(liquidationPrice) : "無法估算"}
        </div>
        <div class="drive-card-sub">${sanitize(riskText.reason || "")}</div>
        <div class="drive-card-sub">開倉費 ${formatTradingPointsValue(fee)} · 日息 ${formatTradingPointsValue(row.interest_bps_daily || 0)} bps · 已計利息 ${formatTradingPointsValue(interest)} · ${sanitize(leverageHint)}</div>
        <div class="economy-ledger-hash">${sanitize(row.position_uuid || "")}</div>
      </div>
      <div class="trading-spot-actions">
        <div class="field">
          <label>補保證金</label>
          <input type="number" min="1" step="1" placeholder="點數" data-${prefix}margin-collateral-amount="${sanitize(row.position_uuid || "")}" />
        </div>
        <button class="btn" type="button" data-${prefix}margin-add-collateral="${sanitize(row.position_uuid || "")}">補保證金</button>
        <button class="btn btn-danger" type="button" data-${prefix}margin-close="${sanitize(row.position_uuid || "")}">平倉</button>
      </div>
    </div>
  `;
}

function renderTradingMarketOptions() {
  const select = $("trading-market-select");
  const rootSelect = $("trading-root-market-select");
  const contractSelect = $("trading-contract-market-select");
  const marginSelect = $("trading-margin-market-select");
  const options = tradingState.markets.length
    ? tradingState.markets.map((market) => `<option value="${sanitize(market.symbol)}">${sanitize(tradingDisplaySymbol(market.symbol))}</option>`).join("")
    : `<option value="">沒有可用市場</option>`;
  [select, rootSelect, contractSelect, marginSelect].forEach((target) => {
    if (!target) return;
    const previous = target.value;
    target.innerHTML = options;
    if (previous && Array.from(target.options).some((option) => option.value === previous)) target.value = previous;
  });
}

function renderTradingSummary() {
  const market = selectedTradingMarket();
  const funding = tradingState.funding || {};
  const orderForm = $("trading-order-form");
  const submitBtn = $("trading-submit-order-btn");
  const availabilityNote = $("trading-availability-note");
  const contractCard = $("trading-root-contract-card");
  const marginCard = $("trading-margin-card");
  if (orderForm) orderForm.style.display = "";
  if (submitBtn) submitBtn.disabled = false;
  if (contractCard) contractCard.style.display = currentUser === "root" ? "" : "none";
  const borrowingEnabled = !!tradingState.settings?.borrowing_enabled;
  if (marginCard) marginCard.style.display = "";
  const marginControlsDisabled = !borrowingEnabled;
  ["trading-margin-market-select", "trading-margin-type", "trading-margin-quantity", "trading-margin-collateral", "trading-margin-open-btn"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = marginControlsDisabled;
  });
  if ($("trading-margin-note")) {
    $("trading-margin-note").textContent = borrowingEnabled
      ? (currentUser === "root"
        ? `root 可用模擬資金進行融資 / 借券，日息 ${Number(tradingState.settings?.borrow_interest_bps_daily || 0)} bps；不寫入 PointsChain。`
        : `已開啟，日息 ${Number(tradingState.settings?.borrow_interest_bps_daily || 0)} bps；手續費與利息計入儲備池統計。`)
      : "root 尚未開啟借貸交易，目前僅可查看此區。";
  }
  if (availabilityNote) {
    availabilityNote.textContent = currentUser === "root"
      ? "root 可使用現貨、進階交易與合約模擬；root 以外用戶目前僅開放現貨與已啟用的進階交易。"
      : "目前僅對 root 以外用戶開放 BTC/USDT、ETH/USDT 現貨。";
  }
  if ($("trading-funding-available")) $("trading-funding-available").textContent = funding.available_points != null ? String(Number(funding.available_points || 0)) : "-";
  if ($("trading-funding-mode")) {
    $("trading-funding-mode").textContent = funding.mode === "root_simulated"
      ? `root 模擬資金 · 鎖定 ${Number(funding.locked_points || 0)}`
      : `體驗金優先 · 錢包 ${Number(funding.wallet_available_points || 0)} · 鎖定 ${Number(funding.locked_points || 0)}`;
  }
  const trial = funding.trial_credit || null;
  if ($("trading-trial-credit-available")) {
    $("trading-trial-credit-available").textContent = trial ? String(Number(trial.available_points || 0)) : "-";
  }
  if ($("trading-trial-credit-note")) {
    if (!trial) {
      $("trading-trial-credit-note").textContent = "root 不適用";
    } else if (trial.status !== "active") {
      $("trading-trial-credit-note").textContent = `狀態 ${trial.status}`;
    } else {
      const expires = trial.expires_at ? new Date(trial.expires_at).toLocaleString() : "-";
      $("trading-trial-credit-note").textContent = `鎖定 ${Number(trial.locked_points || 0)} · 部位 ${Number(trial.deployed_points || 0)} · 到期 ${expires}`;
    }
  }
  if ($("trading-current-price")) $("trading-current-price").textContent = market ? String(Number(market.manual_price_points || 0)) : "-";
  if ($("trading-current-market")) $("trading-current-market").textContent = market ? `${tradingDisplaySymbol(market.symbol)} · ${market.price_source || "manual_root"}` : "-";
  if ($("trading-fee-bps")) $("trading-fee-bps").textContent = market ? String(Number(market.fee_bps || 0)) : "-";
  const position = market ? tradingState.positions.find((row) => row.market_symbol === market.symbol) : null;
  if ($("trading-position-quantity")) $("trading-position-quantity").textContent = position ? sanitize(position.quantity || "0") : "0";
  if ($("trading-position-locked")) $("trading-position-locked").textContent = `鎖定 ${position ? sanitize(position.locked_quantity || "0") : "0"}`;
  const limit = $("trading-limit-price");
  if (limit && market && !$("trading-root-price")?.matches(":focus")) {
    limit.placeholder = `目前 ${Number(market.manual_price_points || 0)}`;
  }
  syncTradingOrderSideTheme();
  updateTradingOrderEstimate();
  updateTradingMarginEstimate();
  loadTradingReferencePrices();
}

function tradingReferenceLabel(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "-";
  return number >= 1000
    ? `$${number.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    : `$${number.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function tradingReferenceTimeLabel(point, interval = "") {
  const rawTime = Number(point?.time || 0);
  const date = Number.isFinite(rawTime) && rawTime > 0
    ? new Date(rawTime)
    : new Date(point?.time_iso || Date.now());
  if (Number.isNaN(date.getTime())) return "-";
  return interval === "1d"
    ? date.toLocaleDateString()
    : date.toLocaleString();
}

function hideTradingReferenceTooltip() {
  const tooltip = $("trading-reference-tooltip");
  if (tooltip) {
    tooltip.hidden = true;
    tooltip.textContent = "";
  }
  if (tradingReferenceHoverIndex !== null) {
    tradingReferenceHoverIndex = null;
    if (tradingState.referencePrices) renderTradingReferenceChart(tradingState.referencePrices);
  }
}

function tradingIndicatorEnabled(id) {
  const el = $(id);
  return !!el?.checked;
}

function tradingIndicatorSeries(candles, period, mode = "sma") {
  const closes = candles.map((point) => Number(point.close_usdt || point.price_usdt || point.close || 0));
  const values = Array(closes.length).fill(null);
  if (!period || period < 1 || closes.length < period) return values;
  if (mode === "ema") {
    const alpha = 2 / (period + 1);
    let ema = null;
    closes.forEach((close, index) => {
      if (!Number.isFinite(close) || close <= 0) return;
      ema = ema == null ? close : close * alpha + ema * (1 - alpha);
      values[index] = ema;
    });
    return values;
  }
  for (let index = period - 1; index < closes.length; index += 1) {
    const windowValues = closes.slice(index - period + 1, index + 1).filter((value) => Number.isFinite(value) && value > 0);
    if (windowValues.length !== period) continue;
    values[index] = windowValues.reduce((sum, value) => sum + value, 0) / period;
  }
  return values;
}

function tradingBollingerSeries(candles, period = 20, multiplier = 2) {
  const closes = candles.map((point) => Number(point.close_usdt || point.price_usdt || point.close || 0));
  const upper = Array(closes.length).fill(null);
  const middle = Array(closes.length).fill(null);
  const lower = Array(closes.length).fill(null);
  for (let index = period - 1; index < closes.length; index += 1) {
    const windowValues = closes.slice(index - period + 1, index + 1).filter((value) => Number.isFinite(value) && value > 0);
    if (windowValues.length !== period) continue;
    const mean = windowValues.reduce((sum, value) => sum + value, 0) / period;
    const variance = windowValues.reduce((sum, value) => sum + (value - mean) ** 2, 0) / period;
    const stddev = Math.sqrt(variance);
    upper[index] = mean + multiplier * stddev;
    middle[index] = mean;
    lower[index] = mean - multiplier * stddev;
  }
  return { upper, middle, lower };
}

function buildTradingReferenceIndicators(candles) {
  const indicators = [];
  if (tradingIndicatorEnabled("trading-indicator-ma5")) {
    indicators.push({ key: "ma5", label: "MA5", color: "#f59e0b", values: tradingIndicatorSeries(candles, 5) });
  }
  if (tradingIndicatorEnabled("trading-indicator-ma20")) {
    indicators.push({ key: "ma20", label: "MA20", color: "#38bdf8", values: tradingIndicatorSeries(candles, 20) });
  }
  if (tradingIndicatorEnabled("trading-indicator-ma60")) {
    indicators.push({ key: "ma60", label: "MA60", color: "#a78bfa", values: tradingIndicatorSeries(candles, 60) });
  }
  if (tradingIndicatorEnabled("trading-indicator-ema12")) {
    indicators.push({ key: "ema12", label: "EMA12", color: "#22d3ee", values: tradingIndicatorSeries(candles, 12, "ema") });
  }
  if (tradingIndicatorEnabled("trading-indicator-ema26")) {
    indicators.push({ key: "ema26", label: "EMA26", color: "#fb7185", values: tradingIndicatorSeries(candles, 26, "ema") });
  }
  if (tradingIndicatorEnabled("trading-indicator-bollinger")) {
    const bands = tradingBollingerSeries(candles, 20, 2);
    indicators.push({ key: "bb_upper", label: "BB上", color: "rgba(16, 185, 129, .82)", values: bands.upper, dash: [4, 4] });
    indicators.push({ key: "bb_mid", label: "BB中", color: "rgba(16, 185, 129, .5)", values: bands.middle });
    indicators.push({ key: "bb_lower", label: "BB下", color: "rgba(16, 185, 129, .82)", values: bands.lower, dash: [4, 4] });
  }
  return indicators;
}

function drawTradingIndicatorLine(ctx, indicator, candleModels, yForPrice) {
  ctx.save();
  ctx.strokeStyle = indicator.color;
  ctx.lineWidth = 1.45;
  if (indicator.dash) ctx.setLineDash(indicator.dash);
  let drawing = false;
  ctx.beginPath();
  indicator.values.forEach((value, index) => {
    if (!Number.isFinite(value) || value <= 0 || !candleModels[index]) {
      drawing = false;
      return;
    }
    const x = candleModels[index].x;
    const y = yForPrice(value);
    if (!drawing) {
      ctx.moveTo(x, y);
      drawing = true;
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
  ctx.restore();
}

function tradingIndicatorLegend(indicators) {
  const active = indicators
    .filter((item) => item.values.some((value) => Number.isFinite(value) && value > 0))
    .map((item) => item.label);
  return active.length ? ` · 指標 ${active.join(" / ")}` : "";
}

function renderTradingReferenceChart(payload, errorText = "") {
  const canvas = $("trading-reference-chart");
  const meta = $("trading-reference-price-meta");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width || canvas.width || 920));
  const height = Math.max(180, Math.floor(rect.height || canvas.height || 240));
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.floor(width * ratio) || canvas.height !== Math.floor(height * ratio)) {
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const bg = ctx.createLinearGradient(0, 0, 0, height);
  bg.addColorStop(0, "#111827");
  bg.addColorStop(1, "#0b1120");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);
  const candles = Array.isArray(payload?.candles) ? payload.candles : (Array.isArray(payload?.points) ? payload.points : []);
  if (!candles.length) {
    tradingReferenceChartModel = null;
    hideTradingReferenceTooltip();
    ctx.fillStyle = "#94a3b8";
    ctx.font = "14px system-ui, sans-serif";
    ctx.fillText(errorText || "參考價格讀取中", 18, 34);
    if (meta) meta.textContent = errorText || "公開 API 蠟燭圖載入中；成交引擎會由後端重新取得即時價。";
    return;
  }
  const indicators = buildTradingReferenceIndicators(candles);
  const prices = candles.flatMap((point) => [
    Number(point.high_usdt || point.high_points || point.price_usdt || point.price_points || 0),
    Number(point.low_usdt || point.low_points || point.price_usdt || point.price_points || 0),
  ]).concat(indicators.flatMap((indicator) => indicator.values)).filter((value) => Number.isFinite(value) && value > 0);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const spread = Math.max(1, maxPrice - minPrice);
  const pad = { left: 58, right: 18, top: 22, bottom: 34 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const yForPrice = (price) => pad.top + chartH - ((price - minPrice) / spread) * chartH;
  ctx.strokeStyle = "rgba(148, 163, 184, .22)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (chartH * i / 4);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    const label = tradingReferenceLabel(maxPrice - (spread * i / 4));
    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px system-ui, sans-serif";
    ctx.fillText(label, 8, y + 4);
  }
  const slot = chartW / Math.max(candles.length, 1);
  const bodyW = Math.max(5, Math.min(18, slot * 0.64));
  const candleModels = candles.map((point, index) => {
    const open = Number(point.open_usdt || point.price_usdt || 0);
    const high = Number(point.high_usdt || open);
    const low = Number(point.low_usdt || open);
    const close = Number(point.close_usdt || point.price_usdt || open);
    const x = pad.left + slot * index + slot / 2;
    const yHigh = yForPrice(high);
    const yLow = yForPrice(low);
    const yOpen = yForPrice(open);
    const yClose = yForPrice(close);
    const up = close >= open;
    const color = up ? "#22c55e" : "#ef4444";
    const fillColor = up ? "rgba(34, 197, 94, .82)" : "rgba(239, 68, 68, .86)";
    ctx.strokeStyle = color;
    ctx.fillStyle = fillColor;
    ctx.lineWidth = 1.25;
    ctx.beginPath();
    ctx.moveTo(x, yHigh);
    ctx.lineTo(x, yLow);
    ctx.stroke();
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(2, Math.abs(yOpen - yClose));
    ctx.fillRect(x - bodyW / 2, bodyTop, bodyW, bodyH);
    ctx.strokeRect(x - bodyW / 2, bodyTop, bodyW, bodyH);
    return { ...point, index, open, high, low, close, x, yHigh, yLow, yOpen, yClose, bodyTop, bodyH };
  });
  indicators.forEach((indicator) => drawTradingIndicatorLine(ctx, indicator, candleModels, yForPrice));
  tradingReferenceChartModel = { payload, candles: candleModels, indicators, pad, width, height, chartW, chartH, slot };
  if (tradingReferenceHoverIndex !== null && candleModels[tradingReferenceHoverIndex]) {
    const hover = candleModels[tradingReferenceHoverIndex];
    ctx.save();
    ctx.strokeStyle = "rgba(248, 250, 252, .72)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(hover.x, pad.top);
    ctx.lineTo(hover.x, height - pad.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "rgba(248, 250, 252, .9)";
    ctx.strokeRect(hover.x - bodyW / 2 - 2, hover.bodyTop - 2, bodyW + 4, hover.bodyH + 4);
    ctx.restore();
  }
  const first = candles[0];
  const last = candles[candles.length - 1];
  const lastPrice = Number(last.close_usdt || last.price_usdt || 0);
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "12px system-ui, sans-serif";
  ctx.fillText(`${payload.display_market || payload.symbol || ""} ${tradingReferenceLabel(lastPrice)}`, pad.left, 16);
  ctx.fillStyle = "#94a3b8";
  ctx.fillText(new Date(first.time || Date.now()).toLocaleDateString(), pad.left, height - 10);
  ctx.textAlign = "right";
  ctx.fillText(new Date(last.time || Date.now()).toLocaleDateString(), width - pad.right, height - 10);
  ctx.textAlign = "left";
  if (meta) {
    const open = tradingReferenceLabel(last.open_usdt || last.price_usdt || lastPrice);
    const high = tradingReferenceLabel(last.high_usdt || lastPrice);
    const low = tradingReferenceLabel(last.low_usdt || lastPrice);
    const close = tradingReferenceLabel(last.close_usdt || lastPrice);
    meta.textContent = `${payload.display_market || payload.symbol || "-"} · ${payload.interval || "-"} · Binance 公開 API 蠟燭圖 · 最新 ${close} · O ${open} / H ${high} / L ${low} / C ${close}${tradingIndicatorLegend(indicators)}`;
  }
}

function updateTradingReferenceTooltip(event) {
  const model = tradingReferenceChartModel;
  const canvas = $("trading-reference-chart");
  const tooltip = $("trading-reference-tooltip");
  if (!model || !canvas || !tooltip || !model.candles.length) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (x < model.pad.left || x > model.width - model.pad.right || y < model.pad.top || y > model.height - model.pad.bottom) {
    hideTradingReferenceTooltip();
    return;
  }
  const index = Math.max(0, Math.min(model.candles.length - 1, Math.floor((x - model.pad.left) / model.slot)));
  const point = model.candles[index];
  if (!point) {
    hideTradingReferenceTooltip();
    return;
  }
  if (tradingReferenceHoverIndex !== index) {
    tradingReferenceHoverIndex = index;
    renderTradingReferenceChart(model.payload);
  }
  tooltip.innerHTML = `
    <strong>${sanitize(tradingReferenceTimeLabel(point, model.payload?.interval || ""))}</strong>
    <span>開 ${sanitize(tradingReferenceLabel(point.open))} · 高 ${sanitize(tradingReferenceLabel(point.high))}</span>
    <span>低 ${sanitize(tradingReferenceLabel(point.low))} · 收 ${sanitize(tradingReferenceLabel(point.close))}</span>
    ${model.indicators?.map((indicator) => {
      const value = indicator.values?.[index];
      return Number.isFinite(value) && value > 0
        ? `<span>${sanitize(indicator.label)} ${sanitize(tradingReferenceLabel(value))}</span>`
        : "";
    }).join("") || ""}
  `;
  tooltip.hidden = false;
  const tooltipWidth = tooltip.offsetWidth || 180;
  const tooltipHeight = tooltip.offsetHeight || 70;
  const left = Math.min(Math.max(point.x + 12, 8), Math.max(8, rect.width - tooltipWidth - 8));
  const top = Math.min(Math.max(y - tooltipHeight - 10, 8), Math.max(8, rect.height - tooltipHeight - 8));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function tradingReferenceAutoRefreshMs() {
  return 1000;
}

function tradingReferenceChartLimit(interval) {
  return interval === "1d" ? 90 : 96;
}

function tradingReferenceCandles(payload) {
  return Array.isArray(payload?.candles)
    ? payload.candles
    : (Array.isArray(payload?.points) ? payload.points : []);
}

function tradingReferencePayloadHasCandles(payload) {
  return tradingReferenceCandles(payload).length > 0;
}

function mergeTradingReferenceLatestPayload(currentPayload, latestPayload, maxCandles) {
  const latestCandles = tradingReferenceCandles(latestPayload);
  if (!latestCandles.length) return currentPayload || null;
  const existingCandles = tradingReferenceCandles(currentPayload);
  const mergedCandles = existingCandles.slice();
  latestCandles.forEach((candle) => {
    const candleTime = Number(candle?.time || 0);
    const lastIndex = mergedCandles.length - 1;
    const lastTime = Number(mergedCandles[lastIndex]?.time || 0);
    if (lastIndex >= 0 && candleTime > 0 && candleTime === lastTime) {
      mergedCandles[lastIndex] = candle;
      return;
    }
    if (lastIndex < 0 || !lastTime || candleTime > lastTime) {
      mergedCandles.push(candle);
      return;
    }
    const existingIndex = mergedCandles.findIndex((item) => Number(item?.time || 0) === candleTime);
    if (existingIndex >= 0) mergedCandles[existingIndex] = candle;
  });
  const trimmedCandles = mergedCandles.slice(Math.max(0, mergedCandles.length - maxCandles));
  return {
    ...(currentPayload || {}),
    ...(latestPayload || {}),
    candles: trimmedCandles,
    points: trimmedCandles,
    latest_only: false,
  };
}

function restartTradingReferenceAutoRefresh() {
  if (tradingReferenceAutoTimer) clearInterval(tradingReferenceAutoTimer);
  if (tradingReferenceChartAutoTimer) clearInterval(tradingReferenceChartAutoTimer);
  tradingReferenceAutoTimer = setInterval(async () => {
    if (!currentUser || currentModuleTab !== "trading" || tradingReferenceAutoBusy) return;
    tradingReferenceAutoBusy = true;
    try {
      await loadTradingReferencePrices({ silent: true, priceOnly: true });
    } finally {
      tradingReferenceAutoBusy = false;
    }
  }, tradingReferenceAutoRefreshMs());
  tradingReferenceChartAutoTimer = setInterval(async () => {
    if (!currentUser || currentModuleTab !== "trading" || tradingReferenceChartAutoBusy) return;
    tradingReferenceChartAutoBusy = true;
    try {
      await loadTradingReferencePrices({ silent: true, latestOnly: true });
    } finally {
      tradingReferenceChartAutoBusy = false;
    }
  }, 5000);
}

async function loadTradingReferencePrices(options = {}) {
  const market = selectedTradingMarket();
  const canvas = $("trading-reference-chart");
  if (!market || !canvas) return;
  const interval = $("trading-reference-interval")?.value || "15m";
  const isPriceOnly = !!options.priceOnly;
  const abortKey = isPriceOnly ? "price" : "chart";
  if (abortKey === "price") {
    if (tradingReferencePriceAbort) tradingReferencePriceAbort.abort();
    tradingReferencePriceAbort = new AbortController();
  } else {
    if (tradingReferenceChartAbort) tradingReferenceChartAbort.abort();
    tradingReferenceChartAbort = new AbortController();
  }
  const signal = abortKey === "price" ? tradingReferencePriceAbort.signal : tradingReferenceChartAbort.signal;
  const hasReusableChart = !!(
    tradingReferencePayloadHasCandles(tradingState.referencePrices)
    && tradingState.referencePrices.market === market.symbol
    && tradingState.referencePrices.interval === interval
  );
  if (!options.silent && !hasReusableChart) {
    renderTradingReferenceChart(null, "參考價格讀取中");
  } else if (!options.silent && hasReusableChart && $("trading-reference-price-meta")) {
    $("trading-reference-price-meta").textContent = "正在更新參考價格，保留上一張蠟燭圖。";
  }
  try {
    const maxCandles = tradingReferenceChartLimit(interval);
    const canPatchLatest = !!(
      options.latestOnly
      && tradingReferencePayloadHasCandles(tradingState.referencePrices)
      && tradingState.referencePrices.market === market.symbol
      && tradingState.referencePrices.interval === interval
    );
    const latestOnly = !!(isPriceOnly || canPatchLatest);
    const limit = latestOnly ? 1 : maxCandles;
    const latestParam = latestOnly ? "&latest=1" : "";
    const json = await fetchTradingJson(`/trading/reference-prices?market=${encodeURIComponent(market.symbol)}&interval=${encodeURIComponent(interval)}&limit=${limit}${latestParam}`, {
      signal,
    });
    const responseCandles = tradingReferenceCandles(json);
    let nextPayload = null;
    if (!isPriceOnly) {
      nextPayload = latestOnly
        ? mergeTradingReferenceLatestPayload(tradingState.referencePrices, json, maxCandles)
        : json;
      if (tradingReferencePayloadHasCandles(nextPayload)) {
        tradingState.referencePrices = nextPayload;
      } else if (!hasReusableChart) {
        renderTradingReferenceChart(null, "Binance 參考價格暫無有效資料");
      }
    }
    const last = responseCandles[responseCandles.length - 1] || null;
    if (last && last.close_points) {
      market.manual_price_points = Number(last.close_points || 0);
      market.price_source = json.source || "binance_public_api";
      if ($("trading-current-price")) $("trading-current-price").textContent = String(Number(market.manual_price_points || 0));
      if ($("trading-current-market")) $("trading-current-market").textContent = `${tradingDisplaySymbol(market.symbol)} · ${market.price_source || "binance_public_api"}`;
      updateTradingOrderEstimate();
    }
    if (!isPriceOnly && tradingReferencePayloadHasCandles(tradingState.referencePrices)) {
      renderTradingReferenceChart(tradingState.referencePrices);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    if (!isPriceOnly && !options.silent) {
      if (tradingReferencePayloadHasCandles(tradingState.referencePrices)) {
        renderTradingReferenceChart(tradingState.referencePrices);
        if ($("trading-reference-price-meta")) {
          $("trading-reference-price-meta").textContent = `參考價格更新失敗，已保留上一張蠟燭圖：${err.message || "Binance 參考價格讀取失敗"}`;
        }
      } else {
        renderTradingReferenceChart(null, err.message || "Binance 參考價格讀取失敗");
      }
    }
  }
}

function renderTradingOrders(rows, targetId = "trading-order-list", allowCancel = true) {
  const list = $(targetId);
  if (!list) return;
  if (!rows || !rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無訂單</div>`;
    return;
  }
  list.innerHTML = rows.map((row) => {
    const canCancel = row.status === "open" || row.status === "partially_filled";
    const price = row.order_type === "limit" ? row.limit_price_points : row.execution_price_points;
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.side)} · ${sanitize(row.order_type)} · ${sanitize(row.status)}</strong>
          <div class="drive-card-sub">${sanitize(tradingDisplaySymbol(row.market_symbol))} · 數量 ${sanitize(row.quantity)} · 價格 ${sanitize(price || "-")} · 凍結 ${Number(row.frozen_points || 0)}</div>
          <div class="economy-ledger-hash">${sanitize(row.order_uuid || "")}</div>
        </div>
        ${allowCancel && canCancel ? `<button class="btn" type="button" data-trading-cancel="${sanitize(row.order_uuid || "")}">取消</button>` : ""}
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-trading-cancel]").forEach((btn) => {
    btn.addEventListener("click", () => cancelTradingOrder(btn.dataset.tradingCancel || ""));
  });
}

function renderTradingFills(rows, targetId = "trading-fill-list") {
  const list = $(targetId);
  if (!list) return;
  if (!rows || !rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無成交</div>`;
    return;
  }
  list.innerHTML = rows.map((row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.side)} · ${sanitize(tradingDisplaySymbol(row.market_symbol))} · ${sanitize(row.quantity)}</strong>
        <div class="drive-card-sub">價格 ${Number(row.price_points || 0)} · 成交 ${Number(row.notional_points || 0)} 點 · 手續費 ${Number(row.fee_points || 0)}</div>
        <div class="drive-card-sub">${sanitize(row.created_at || "")}</div>
      </div>
    </div>
  `).join("");
}

function renderTradingContracts(rows = []) {
  const list = $("trading-contract-position-list");
  if (!list) return;
  const contracts = rows.filter((row) => row.status === "open");
  if (!contracts.length) {
    list.innerHTML = `<div class="drive-empty">尚無 root 合約持倉</div>`;
    return;
  }
  list.innerHTML = contracts.map((row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.side || "-")} · ${sanitize(tradingDisplaySymbol(row.market_symbol || "-"))} · ${sanitize(row.quantity || "0")}</strong>
        <div class="drive-card-sub">入場 ${Number(row.entry_price_points || 0)} 點 · 槓桿 ${Number(row.leverage || 1)}x · 保證金 ${Number(row.margin_points || 0)} 點</div>
        <div class="economy-ledger-hash">${sanitize(row.position_uuid || "")}</div>
      </div>
      <button class="btn" type="button" data-contract-close="${sanitize(row.position_uuid || "")}">平倉</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-contract-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeRootTradingContract(btn.dataset.contractClose || ""));
  });
}

function updateTradingMarginEstimate() {
  const market = tradingState.markets.find((row) => row.symbol === ($("trading-margin-market-select")?.value || "")) || selectedTradingMarket();
  const estimate = $("trading-margin-estimate");
  const openBtn = $("trading-margin-open-btn");
  if (!estimate || !market) return { ok: false, blocking: true, message: "沒有可用進階交易市場" };
  const quantity = tradingNumber($("trading-margin-quantity")?.value, 0);
  const collateral = tradingNumber($("trading-margin-collateral")?.value, 0);
  const price = tradingNumber(market.manual_price_points, 0);
  const notional = quantity > 0 && price > 0 ? Math.ceil(quantity * price) : 0;
  const positionType = $("trading-margin-type")?.value || "margin_long";
  const marginLongFinancingBps = tradingNumber(tradingState.settings?.margin_long_financing_bps, 9000);
  const shortCollateralBps = tradingNumber(tradingState.settings?.short_collateral_bps, 6000);
  const minCollateral = positionType === "short"
    ? Math.ceil(notional * shortCollateralBps / 10000)
    : Math.ceil(notional * Math.max(0, 10000 - marginLongFinancingBps) / 10000);
  const fee = Math.ceil(notional * tradingNumber(market.fee_bps, 0) / 10000);
  const available = tradingNumber(tradingState.funding?.available_points, 0);
  const typeLabel = positionType === "short" ? "借券放空" : "融資買入";
  if (!quantity || !collateral || !notional) {
    estimate.textContent = "輸入數量與保證金後顯示預估風險。";
    estimate.style.color = "var(--muted)";
    if (openBtn) openBtn.disabled = true;
    return { ok: false, blocking: true, message: estimate.textContent };
  }
  let message = `${typeLabel} · 名目金額約 ${notional} 點 · 開倉費 ${fee} 點 · 原始保證金最低需求 ${minCollateral} 點 · 目前填寫 ${collateral} 點`;
  if (positionType === "short") {
    message = `${message}；借券放空風險：價格上漲會虧損並降低維持率；借券保證金比例 ${shortCollateralBps} bps`;
  } else {
    message = `${message}；融資可貸比例 ${marginLongFinancingBps} bps`;
  }
  let blocking = false;
  if (collateral < minCollateral) {
    message = `${message}；原始保證金不足，至少需要 ${minCollateral} 點`;
    blocking = true;
  } else if ((collateral + fee) > available) {
    message = `${message}；可用資金不足，需要 ${collateral + fee} 點，目前可用 ${available} 點`;
    blocking = true;
  }
  estimate.textContent = message;
  estimate.style.color = blocking ? "#ff6b7a" : "var(--muted)";
  if (openBtn) openBtn.disabled = blocking || !tradingState.settings?.borrowing_enabled;
  return { ok: !blocking, blocking, message };
}

function renderTradingMarginPositions(rows = []) {
  const list = $("trading-margin-position-list");
  if (!list) return;
  const openRows = rows.filter((row) => row.status === "open");
  if (!openRows.length) {
    list.innerHTML = `<div class="drive-empty">尚無進階交易倉位</div>`;
    return;
  }
  list.innerHTML = openRows.map((row) => tradingMarginPositionRow(row)).join("");
  list.querySelectorAll("[data-margin-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeTradingMarginPosition(btn.dataset.marginClose || ""));
  });
  list.querySelectorAll("[data-margin-add-collateral]").forEach((btn) => {
    btn.addEventListener("click", () => addTradingMarginCollateral(btn.dataset.marginAddCollateral || ""));
  });
}

function renderTradingWalletSummary(payload = {}) {
  const positions = Array.isArray(payload.positions) ? payload.positions : [];
  const futuresPositions = Array.isArray(payload.futures_positions) ? payload.futures_positions : [];
  const marginPositions = Array.isArray(payload.margin_positions) ? payload.margin_positions : [];
  const orders = Array.isArray(payload.orders) ? payload.orders : [];
  const fills = Array.isArray(payload.fills) ? payload.fills : [];
  const markets = Array.isArray(payload.markets) ? payload.markets : tradingState.markets;
  const funding = payload.funding || tradingState.funding || {};
  const state = payload.state || {};
  const marginSummary = payload.margin_summary || {};
  const status = $("economy-trading-safe-mode");
  if (status) {
    status.textContent = state.safe_mode ? `交易 safe mode：${state.reason || "已啟用"}` : "交易引擎正常";
    status.style.color = state.safe_mode ? "#ffb74d" : "var(--muted)";
  }
  const activePositions = positions.filter((row) => Number(row.quantity || 0) !== 0 || Number(row.locked_quantity || 0) !== 0);
  if ($("economy-spot-position-quantity")) {
    $("economy-spot-position-quantity").textContent = activePositions.length
      ? activePositions.map((row) => tradingPositionLabel(row)).join(" / ")
      : "尚無現貨";
  }
  if ($("economy-spot-position-summary")) {
    $("economy-spot-position-summary").textContent = activePositions.length
      ? "BTC、ETH 等交易對分開顯示"
      : "各交易對分開計算";
  }
  const activeMarginPositions = marginPositions.filter((row) => row.status === "open");
  if ($("economy-margin-position-count")) $("economy-margin-position-count").textContent = String(activeMarginPositions.length);
  if ($("economy-margin-position-summary")) {
    $("economy-margin-position-summary").textContent = activeMarginPositions.length
      ? `整戶維持率 ${marginSummary.maintenance_ratio_percent == null ? "無法計算" : `${formatTradingPointsValue(marginSummary.maintenance_ratio_percent)}%`} · ${marginSummary.reason || "風險正常"}`
      : "融資 / 借券";
  }
  const activeFuturesPositions = futuresPositions.filter((row) => row.status === "open" && Number(row.quantity || 0) !== 0);
  if ($("economy-contract-position-count")) $("economy-contract-position-count").textContent = String(activeFuturesPositions.length);
  if ($("economy-contract-position-summary")) {
    $("economy-contract-position-summary").textContent = activeFuturesPositions.length
      ? activeFuturesPositions.slice(0, 2).map((row) => `${tradingDisplaySymbol(row.market_symbol)}: ${row.side} ${row.quantity || "0"}`).join(" / ")
      : "未開放";
  }
  if ($("economy-trading-fill-count")) $("economy-trading-fill-count").textContent = String(fills.length);
  if ($("economy-trading-order-count")) $("economy-trading-order-count").textContent = `訂單 ${orders.length}`;
  renderEconomySpotPositionDetails(positions, markets);
  renderEconomyMarginPositionDetails(marginPositions);
  if (currentUser === "root") {
    const spotValue = rootVirtualSpotValue(activePositions, markets);
    const available = Number(funding.available_points || 0);
    const locked = Number(funding.locked_points || 0);
    const total = available + spotValue;
    if ($("economy-root-virtual-total")) $("economy-root-virtual-total").textContent = `${formatTradingPointsValue(total)} 點`;
    if ($("economy-root-virtual-available")) $("economy-root-virtual-available").textContent = `${formatTradingPointsValue(available)} 點`;
    if ($("economy-root-virtual-locked")) $("economy-root-virtual-locked").textContent = `鎖定 ${formatTradingPointsValue(locked)} 點`;
    if ($("economy-root-virtual-spot-value")) $("economy-root-virtual-spot-value").textContent = `${formatTradingPointsValue(spotValue)} 點`;
    if ($("economy-root-virtual-spot-summary")) {
      $("economy-root-virtual-spot-summary").textContent = activePositions.length
        ? activePositions.slice(0, 3).map((row) => tradingPositionLabel(row)).join(" / ")
        : "尚無現貨";
    }
  }
  renderTradingOrders(orders, "economy-trading-order-list", false);
  renderTradingFills(fills, "economy-trading-fill-list");
}

function renderTradingRootReport(report) {
  const safe = report && typeof report === "object" ? report : {};
  const reserve = safe.reserve_pool || {};
  const verification = safe.verification || {};
  if ($("trading-reserve-balance")) $("trading-reserve-balance").textContent = String(Number(reserve.balance_points || 0));
  if ($("trading-verification-status")) $("trading-verification-status").textContent = verification.ok === false ? "異常" : "正常";
  if ($("trading-verification-detail")) $("trading-verification-detail").textContent = `${Array.isArray(verification.errors) ? verification.errors.length : 0} 個問題`;
  const settings = safe.settings || {};
  if ($("trading-risk-flags")) $("trading-risk-flags").textContent = `borrow=${settings.borrowing_enabled ? "true" : "false"} / liquidation=${settings.margin_liquidation_enabled ? "true" : "false"} / futures=${settings.futures_enabled ? "true" : "false"} / pvp=${settings.pvp_matching_enabled ? "true" : "false"}`;
  if ($("trading-liquidation-status")) {
    $("trading-liquidation-status").textContent = settings.margin_liquidation_enabled
      ? `自動清算排程：啟用，維持保證金 ${Number(settings.margin_maintenance_bps || 0)} bps`
      : "自動清算排程：停用";
  }
  if ($("trading-root-sim-balance")) {
    const funding = tradingState.funding || {};
    $("trading-root-sim-balance").textContent = funding.mode === "root_simulated" ? String(Number(funding.available_points || 0)) : "10000";
  }
  const markets = Array.isArray(safe.markets) ? safe.markets : tradingState.markets;
  tradingState.markets = markets;
  renderTradingMarketOptions();
  populateTradingRootMarketForm();
  const auditList = $("trading-audit-list");
  if (auditList) {
    const rows = Array.isArray(safe.audit_events) ? safe.audit_events : [];
    auditList.innerHTML = rows.length ? rows.map((row) => `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.event_type || "-")} · ${sanitize(row.severity || "-")}</strong>
          <div class="drive-card-sub">${sanitize(row.market_symbol || "-")} · ${sanitize(row.created_at || "")}</div>
          <div class="drive-card-sub">${sanitize(row.message || "")}</div>
        </div>
      </div>
    `).join("") : `<div class="drive-empty">尚無交易審計</div>`;
  }
  const eventList = $("trading-reserve-event-list");
  if (eventList) {
    const rows = Array.isArray(safe.reserve_events) ? safe.reserve_events : [];
    eventList.innerHTML = rows.length ? rows.map((row) => `
      <div class="drive-file-row">
        <div>
          <strong>${Number(row.delta_points || 0)} 點 · ${sanitize(row.event_type || "-")}</strong>
          <div class="drive-card-sub">餘額 ${Number(row.balance_after || 0)} · ${sanitize(row.reason || "-")} · ${sanitize(row.created_at || "")}</div>
        </div>
      </div>
    `).join("") : `<div class="drive-empty">尚無儲備池事件</div>`;
  }
}

function populateTradingRootMarketForm() {
  const symbol = $("trading-root-market-select")?.value || "";
  const market = tradingState.markets.find((row) => row.symbol === symbol) || tradingState.markets[0];
  if (!market) return;
  if ($("trading-root-market-select")) $("trading-root-market-select").value = market.symbol;
  if ($("trading-root-price")) $("trading-root-price").value = Number(market.manual_price_points || 0);
  if ($("trading-root-jump-bps")) $("trading-root-jump-bps").value = Number(market.max_price_jump_bps || 0);
  if ($("trading-root-fee-bps")) $("trading-root-fee-bps").value = Number(market.fee_bps || 0);
  if ($("trading-root-min-order")) $("trading-root-min-order").value = Number(market.min_order_points || 1);
  if ($("trading-root-max-order")) $("trading-root-max-order").value = Number(market.max_order_points || 1);
  if ($("trading-root-enabled")) $("trading-root-enabled").checked = !!market.enabled;
}

async function loadTradingDashboard() {
  if (!currentUser || !canAccessModule("economy")) return;
  const tradingEnabled = !siteConfig || siteConfig.feature_trading_enabled !== false;
  const card = $("trading-card");
  const summaryCard = $("economy-trading-summary-card");
  const rootVirtualCard = $("economy-root-virtual-card");
  const rootCard = $("trading-root-card");
  if (card && !tradingEnabled) {
    card.style.display = "none";
  }
  if (summaryCard) summaryCard.style.display = tradingEnabled ? "" : "none";
  if (rootVirtualCard) rootVirtualCard.style.display = tradingEnabled && currentUser === "root" ? "" : "none";
  if (rootCard) rootCard.style.display = tradingEnabled && currentUser === "root" ? "" : "none";
  if (!tradingEnabled) return;
  if (card) card.style.display = "";
  try {
    const json = await fetchTradingJson("/trading/dashboard");
    const payload = json.trading || {};
    tradingState.funding = payload.funding || null;
    tradingState.markets = payload.markets || [];
    tradingState.settings = payload.settings || {};
    tradingState.positions = payload.positions || [];
    tradingState.marginPositions = payload.margin_positions || [];
    tradingState.orders = payload.orders || [];
    tradingState.fills = payload.fills || [];
    const state = payload.state || {};
    const status = $("trading-safe-mode");
    if (status) {
      status.textContent = state.safe_mode ? `交易 safe mode：${state.reason || "已啟用"}` : "交易引擎正常";
      status.style.color = state.safe_mode ? "#ffb74d" : "var(--muted)";
    }
    renderTradingMarketOptions();
    renderTradingSummary();
    renderTradingOrders(tradingState.orders);
    renderTradingFills(tradingState.fills);
    renderTradingContracts(payload.futures_positions || []);
    renderTradingMarginPositions(tradingState.marginPositions);
    renderTradingWalletSummary(payload);
    if (currentUser === "root") {
      await loadTradingRootReport();
    }
  } catch (err) {
    const status = $("trading-safe-mode");
    if (status) {
      status.textContent = err.message || "交易狀態讀取失敗";
      status.style.color = "#ff4f6d";
    }
  }
}

async function loadTradingRootReport() {
  if (currentUser !== "root") return;
  try {
    const json = await fetchTradingJson("/admin/trading/report");
    tradingState.rootReport = json.report || {};
    renderTradingRootReport(tradingState.rootReport);
  } catch (err) {
    tradingSetMsg(err.message || "交易報告讀取失敗", false);
  }
}

async function submitTradingOrder() {
  const market = selectedTradingMarket();
  if (!market) {
    tradingSetMsg("沒有可用交易市場", false);
    return;
  }
  const estimate = updateTradingOrderEstimate();
  if (estimate.blocking) {
    tradingSetMsg(estimate.message || "下單資料超出可用資產", false);
    return;
  }
  const orderType = $("trading-order-type")?.value || "market";
  const payload = {
    market_symbol: market.symbol,
    side: $("trading-side")?.value || "buy",
    order_type: orderType,
    quantity: $("trading-quantity")?.value || "",
  };
  if (orderType === "limit") payload.limit_price_points = Number($("trading-limit-price")?.value || 0);
  try {
    await fetchTradingJson("/trading/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    tradingSetMsg("訂單已送出");
    await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "下單失敗", false);
  }
}

async function submitEconomySpotSell(symbol, orderType) {
  const row = economySpotRowForSymbol(symbol);
  const market = tradingState.markets.find((item) => item.symbol === symbol);
  if (!row || !market) {
    tradingSetMsg("找不到現貨市場資料", false);
    return;
  }
  const sellable = tradingNumber(row.dataset.sellable, 0);
  const quantityInput = row.querySelector("[data-economy-spot-qty]");
  const priceInput = row.querySelector("[data-economy-spot-price]");
  const quantity = orderType === "market"
    ? sellable
    : tradingNumber(quantityInput?.value, 0);
  const limitPrice = tradingNumber(priceInput?.value, 0);
  if (!quantity || quantity <= 0) {
    tradingSetMsg("請輸入有效賣出數量", false);
    return;
  }
  if (quantity > sellable) {
    tradingSetMsg(`賣出 ${formatTradingPointsValue(quantity)} 超過可賣現貨 ${formatTradingPointsValue(sellable)}`, false);
    return;
  }
  if (orderType === "limit" && (!limitPrice || limitPrice <= 0)) {
    tradingSetMsg("限價賣出需要輸入有效價格", false);
    return;
  }
  const displaySymbol = tradingDisplaySymbol(symbol);
  if (orderType === "limit" && !confirm(`確認限價賣出 ${displaySymbol} ${formatTradingPointsValue(quantity)}，價格 ${formatTradingPointsValue(limitPrice)}？`)) return;
  try {
    const payload = {
      market_symbol: symbol,
      side: "sell",
      order_type: orderType,
      quantity: String(quantity),
    };
    if (orderType === "limit") payload.limit_price_points = limitPrice;
    if (orderType === "market") payload.emergency_close = true;
    await fetchTradingJson("/trading/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    tradingSetMsg(orderType === "market" ? `${displaySymbol} 已直接市價平倉，手續費按平時 2 倍計算` : `${displaySymbol} 限價賣出已送出`);
    await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "現貨賣出失敗", false);
  }
}

async function openRootTradingContract() {
  if (currentUser !== "root") {
    tradingSetMsg("只有 root 可以使用合約模擬交易", false);
    return;
  }
  const symbol = $("trading-contract-market-select")?.value || selectedTradingMarket()?.symbol || "";
  if (!symbol) {
    tradingSetMsg("請先選擇合約市場", false);
    return;
  }
  try {
    const json = await fetchTradingJson("/root/trading/contracts", {
      method: "POST",
      body: JSON.stringify({
        market_symbol: symbol,
        side: $("trading-contract-side")?.value || "long",
        quantity: $("trading-contract-quantity")?.value || "",
        leverage: Number($("trading-contract-leverage")?.value || 1),
        margin_points: Number($("trading-contract-margin")?.value || 0),
      }),
    });
    if (json.funding) tradingState.funding = json.funding;
    tradingSetMsg("root 合約模擬倉位已建立");
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "合約開倉失敗", false);
  }
}

async function closeRootTradingContract(positionUuid) {
  if (!positionUuid) return;
  try {
    const json = await fetchTradingJson(`/root/trading/contracts/${encodeURIComponent(positionUuid)}/close`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (json.funding) tradingState.funding = json.funding;
    tradingSetMsg(`合約已平倉，損益 ${Number(json.pnl_points || 0)} 點`);
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "合約平倉失敗", false);
  }
}

async function openTradingMarginPosition() {
  const symbol = $("trading-margin-market-select")?.value || selectedTradingMarket()?.symbol || "";
  if (!symbol) {
    tradingSetMsg("請先選擇進階交易市場", false);
    return;
  }
  const estimate = updateTradingMarginEstimate();
  if (estimate?.blocking) {
    tradingSetMsg(estimate.message || "進階交易參數不符合開倉條件", false);
    return;
  }
  try {
    const json = await fetchTradingJson("/trading/margin/open", {
      method: "POST",
      body: JSON.stringify({
        market_symbol: symbol,
        position_type: $("trading-margin-type")?.value || "margin_long",
        quantity: $("trading-margin-quantity")?.value || "",
        collateral_points: Number($("trading-margin-collateral")?.value || 0),
      }),
    });
    if (json.funding) tradingState.funding = json.funding;
    tradingSetMsg("進階交易倉位已建立");
    await loadTradingDashboard();
  } catch (err) {
    const detail = err.message || "後端未提供錯誤原因";
    tradingSetMsg(`進階交易開倉失敗：${detail}`, false);
  }
}

async function closeTradingMarginPosition(positionUuid) {
  if (!positionUuid) return;
  if (!confirm("確定平掉這筆進階交易倉位？")) return;
  try {
    const json = await fetchTradingJson(`/trading/margin/${encodeURIComponent(positionUuid)}/close`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (json.funding) tradingState.funding = json.funding;
    tradingSetMsg(`進階交易已平倉，損益 ${Number(json.delta_points || 0)} 點，利息 ${Number(json.interest_points || 0)} 點`);
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "進階交易平倉失敗", false);
  }
}

async function addTradingMarginCollateral(positionUuid, scope = "trading") {
  if (!positionUuid) return;
  const selector = scope === "economy"
    ? `[data-economy-margin-collateral-amount="${CSS.escape(positionUuid)}"]`
    : `[data-margin-collateral-amount="${CSS.escape(positionUuid)}"]`;
  const input = document.querySelector(selector);
  const amount = Number(input?.value || 0);
  if (!amount || amount <= 0) {
    tradingSetMsg("請輸入要補入的保證金點數", false);
    return;
  }
  try {
    const json = await fetchTradingJson(`/trading/margin/${encodeURIComponent(positionUuid)}/collateral`, {
      method: "POST",
      body: JSON.stringify({ amount_points: amount }),
    });
    if (json.funding) tradingState.funding = json.funding;
    tradingSetMsg(`已補入 ${formatTradingPointsValue(amount)} 點保證金`);
    await loadTradingDashboard();
    if (typeof loadEconomyDashboard === "function") await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(`補保證金失敗：${err.message || "後端未提供錯誤原因"}`, false);
  }
}

async function cancelTradingOrder(orderUuid) {
  if (!orderUuid) return;
  try {
    await fetchTradingJson(`/trading/orders/${encodeURIComponent(orderUuid)}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    tradingSetMsg("訂單已取消");
    await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "取消訂單失敗", false);
  }
}

async function saveTradingRootMarket() {
  const symbol = $("trading-root-market-select")?.value || "";
  if (!symbol) {
    tradingSetMsg("請先選擇市場", false);
    return;
  }
  try {
    await fetchTradingJson(`/root/trading/markets/${encodeURIComponent(symbol)}`, {
      method: "POST",
      body: JSON.stringify({
        manual_price_points: Number($("trading-root-price")?.value || 0),
        max_price_jump_bps: Number($("trading-root-jump-bps")?.value || 0),
        fee_bps: Number($("trading-root-fee-bps")?.value || 0),
        min_order_points: Number($("trading-root-min-order")?.value || 0),
        max_order_points: Number($("trading-root-max-order")?.value || 0),
        enabled: !!$("trading-root-enabled")?.checked,
        confirm_jump: !!$("trading-root-confirm-jump")?.checked,
      }),
    });
    if ($("trading-root-confirm-jump")) $("trading-root-confirm-jump").checked = false;
    tradingSetMsg("交易市場設定已儲存");
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "市場設定儲存失敗", false);
  }
}

async function allocateTradingReserve() {
  const userId = Number($("trading-reserve-source-user-id")?.value || 0);
  const amount = Number($("trading-reserve-amount")?.value || 0);
  if (!userId || !amount) {
    tradingSetMsg("請選擇撥入來源帳戶與點數", false);
    return;
  }
  if (!confirm("確認要從指定帳戶扣點並撥入交易儲備池？")) return;
  try {
    await fetchTradingJson("/root/trading/reserve/allocate", {
      method: "POST",
      body: JSON.stringify({
        source_user_id: userId,
        amount_points: amount,
        reason: "ROOT_RESERVE_ALLOCATION",
      }),
    });
    if ($("trading-reserve-amount")) $("trading-reserve-amount").value = "";
    tradingSetMsg("已撥入交易儲備池");
    await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "儲備池撥入失敗", false);
  }
}

async function resetRootTradingSimulatedBalance() {
  if (!confirm("確認重置 root 模擬交易？這會刪除 root 的模擬訂單、成交紀錄、現貨與合約持倉，並把虛擬積分回到 10000。")) return;
  try {
    const json = await fetchTradingJson("/root/trading/simulated-balance/reset", {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (json.funding) tradingState.funding = json.funding;
    const deleted = json.deleted || {};
    tradingSetMsg(
      `root 模擬交易已重置為 ${Number(json.funding?.available_points || 10000)} 點；` +
      `已清除訂單 ${Number(deleted.orders || 0)}、成交 ${Number(deleted.fills || 0)}、現貨 ${Number(deleted.spot_positions || 0)}。`
    );
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "root 模擬資金重設失敗", false);
  }
}

async function scanTradingLiquidations() {
  if (currentUser !== "root") return;
  const status = $("trading-liquidation-status");
  if (status) status.textContent = "正在掃描強平條件...";
  try {
    const json = await fetchTradingJson("/root/trading/liquidations/scan", {
      method: "POST",
      body: JSON.stringify({ limit: 100 }),
    });
    const liquidated = Array.isArray(json.liquidated) ? json.liquidated.length : 0;
    const errors = Array.isArray(json.errors) ? json.errors.length : 0;
    tradingSetMsg(`強平掃描完成：掃描 ${Number(json.scanned || 0)} 筆，清算 ${liquidated} 筆，錯誤 ${errors} 筆`, errors === 0);
    if (status) status.textContent = `最近手動掃描：清算 ${liquidated} 筆，錯誤 ${errors} 筆`;
    await loadTradingDashboard();
  } catch (err) {
    if (status) status.textContent = err.message || "強平掃描失敗";
    tradingSetMsg(err.message || "強平掃描失敗", false);
  }
}

async function matchTradingLimitOrders() {
  if (currentUser !== "root") return;
  try {
    const json = await fetchTradingJson("/root/trading/orders/match", {
      method: "POST",
      body: JSON.stringify({ limit: 200 }),
    });
    const matched = Array.isArray(json.matched) ? json.matched.length : 0;
    const errors = Array.isArray(json.errors) ? json.errors.length : 0;
    tradingSetMsg(`限價單撮合完成：掃描 ${Number(json.scanned || 0)} 筆，成交 ${matched} 筆，錯誤 ${errors} 筆`, errors === 0);
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "限價單撮合失敗", false);
  }
}

function openTradingModuleFromWallet() {
  if (typeof switchModuleTab === "function") switchModuleTab("trading");
}

function syncTradingReserveUserOptions() {
  const source = $("economy-adjust-user-id");
  const target = $("trading-reserve-source-user-id");
  if (!source || !target || !source.options.length) return;
  const previous = target.value;
  target.innerHTML = Array.from(source.options).map((option) => `<option value="${sanitize(option.value)}">${sanitize(option.textContent || "")}</option>`).join("");
  if (previous && Array.from(target.options).some((option) => option.value === previous)) target.value = previous;
}

function bindTradingEvents() {
  if (tradingEventsBound) return;
  tradingEventsBound = true;
  const bindings = [
    ["trading-refresh-btn", loadTradingDashboard],
    ["trading-submit-order-btn", submitTradingOrder],
    ["trading-root-refresh-btn", loadTradingRootReport],
    ["trading-root-save-market-btn", saveTradingRootMarket],
    ["trading-reserve-allocate-btn", allocateTradingReserve],
    ["trading-root-reset-sim-btn", resetRootTradingSimulatedBalance],
    ["trading-contract-open-btn", openRootTradingContract],
    ["trading-margin-open-btn", openTradingMarginPosition],
    ["trading-limit-match-btn", matchTradingLimitOrders],
    ["trading-liquidation-scan-btn", scanTradingLiquidations],
    ["economy-trading-open-btn", openTradingModuleFromWallet],
    ["economy-root-virtual-open-btn", openTradingModuleFromWallet],
  ];
  bindings.forEach(([id, handler]) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("click", handler);
  });
  const marketSelect = $("trading-market-select");
  if (marketSelect) marketSelect.addEventListener("change", renderTradingSummary);
  const marginMarketSelect = $("trading-margin-market-select");
  if (marginMarketSelect) marginMarketSelect.addEventListener("change", updateTradingMarginEstimate);
  ["trading-margin-type", "trading-margin-quantity", "trading-margin-collateral"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("input", updateTradingMarginEstimate);
    el.addEventListener("change", updateTradingMarginEstimate);
  });
  ["trading-side", "trading-order-type", "trading-quantity", "trading-limit-price"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("input", () => {
      syncTradingOrderSideTheme();
      updateTradingOrderEstimate();
    });
    el.addEventListener("change", () => {
      syncTradingOrderSideTheme();
      updateTradingOrderEstimate();
    });
  });
  const referenceInterval = $("trading-reference-interval");
  if (referenceInterval) {
    referenceInterval.addEventListener("change", () => {
      hideTradingReferenceTooltip();
      restartTradingReferenceAutoRefresh();
      loadTradingReferencePrices();
    });
  }
  [
    "trading-indicator-ma5",
    "trading-indicator-ma20",
    "trading-indicator-ma60",
    "trading-indicator-ema12",
    "trading-indicator-ema26",
    "trading-indicator-bollinger",
  ].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("change", () => renderTradingReferenceChart(tradingState.referencePrices));
  });
  const referenceChart = $("trading-reference-chart");
  if (referenceChart) {
    referenceChart.addEventListener("mousemove", updateTradingReferenceTooltip);
    referenceChart.addEventListener("mouseleave", hideTradingReferenceTooltip);
  }
  const rootMarketSelect = $("trading-root-market-select");
  if (rootMarketSelect) rootMarketSelect.addEventListener("change", populateTradingRootMarketForm);
  setInterval(syncTradingReserveUserOptions, 1500);
  restartTradingReferenceAutoRefresh();
  if (!tradingDashboardAutoTimer) {
    tradingDashboardAutoTimer = setInterval(async () => {
      if (!currentUser || currentModuleTab !== "trading" || tradingDashboardAutoBusy) return;
      tradingDashboardAutoBusy = true;
      try {
        await loadTradingDashboard();
      } finally {
        tradingDashboardAutoBusy = false;
      }
    }, 5000);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindTradingEvents);
} else {
  bindTradingEvents();
}
