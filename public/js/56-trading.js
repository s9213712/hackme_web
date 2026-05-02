'use strict';

let tradingState = {
  markets: [],
  positions: [],
  orders: [],
  fills: [],
  bots: [],
  botRuns: [],
  rootReport: null,
  fundingPool: null,
  marginSummary: null,
  referencePrices: null,
  btcSignal: null,
  workflowTemplates: [],
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
let tradingTrialCountdownTimer = null;
let tradingBtcSignalCountdownTimer = null;
let tradingBotCountdownTimer = null;
let tradingCurrentBotTab = "dca";
const TRADING_WORKFLOW_STORAGE_KEY = "hackme_trading_workflow_json";

function tradingRequestId(prefix = "trading") {
  if (typeof economyRequestId === "function") return economyRequestId(prefix);
  if (window.crypto && typeof window.crypto.randomUUID === "function") return `${prefix}:${window.crypto.randomUUID()}`;
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function tradingSetMsg(text, ok = true) {
  const msg = $("trading-msg");
  if (msg && currentModuleTab === "trading") {
    msg.textContent = text || "";
    msg.className = text ? `msg show ${ok ? "ok" : "err"}` : "msg";
  } else if (typeof economySetMsg === "function") {
    economySetMsg(text, ok);
  }
}

function tradingErrorText(json, fallback = "操作失敗") {
  if (!json || typeof json !== "object") return fallback;
  if (json.msg) return String(json.msg);
  if (json.message) return String(json.message);
  if (json.error) return String(json.error);
  if (Array.isArray(json.errors) && json.errors.length) {
    return json.errors.map((item) => {
      if (!item) return "";
      if (typeof item === "string") return item;
      return item.msg || item.message || item.error || JSON.stringify(item);
    }).filter(Boolean).slice(0, 3).join("；");
  }
  return fallback;
}

async function fetchTradingJson(url, options = {}) {
  await fetchCsrfToken({ force: true });
  const headers = { ...(options.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await apiFetch(API + url, { credentials: "same-origin", ...options, headers });
  const raw = await res.text().catch(() => "");
  let json = {};
  try {
    json = raw ? JSON.parse(raw) : {};
  } catch (_) {
    json = {};
  }
  if (!res.ok || !json.ok) {
    let fallback = `HTTP ${res.status}`;
    if (res.status === 404) fallback = `交易所 API 不存在：${url}。請確認伺服器已重啟且目前是包含交易所功能的分支。`;
    else if (raw && raw.trim() && !/^not found$/i.test(raw.trim())) fallback = raw.slice(0, 220);
    const text = tradingErrorText(json, fallback);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return json;
}

function bindTradingActionButton(el, handler, pendingText, fallbackText) {
  if (!el || typeof handler !== "function") return;
  el.addEventListener("click", async (event) => {
    event.preventDefault();
    if (el.disabled) return;
    const previousText = el.textContent;
    el.disabled = true;
    el.setAttribute("aria-busy", "true");
    if (pendingText) tradingSetMsg(pendingText);
    try {
      await handler(event);
    } catch (err) {
      tradingSetMsg(`${fallbackText || "操作失敗"}：${err?.message || "未提供錯誤原因"}`, false);
    } finally {
      el.disabled = false;
      el.removeAttribute("aria-busy");
      if (previousText) el.textContent = previousText;
    }
  });
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

function tradingPercentValue(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function tradingInputPercent(value, fallback = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.round(number * 10000) / 10000;
}

function formatTradingPercent(value, fallback = 0) {
  return formatTradingPointsValue(tradingPercentValue(value, fallback));
}

function formatTradingDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}天 ${hours}小時 ${minutes}分`;
  if (hours > 0) return `${hours}小時 ${minutes}分 ${seconds}秒`;
  if (minutes > 0) return `${minutes}分 ${seconds}秒`;
  return `${seconds}秒`;
}

function tradingTrialCountdownText(trial) {
  if (!trial || trial.status !== "active") return "";
  const expiresAt = trial.expires_at ? new Date(trial.expires_at).getTime() : 0;
  if (!expiresAt || Number.isNaN(expiresAt)) return "到期時間未設定";
  const remaining = expiresAt - Date.now();
  if (remaining <= 0) return "體驗金已到期，等待下次交易狀態刷新";
  return `倒數 ${formatTradingDuration(remaining)}`;
}

function updateTradingTrialCountdown() {
  const funding = tradingState.funding || {};
  const trial = funding.trial_credit || null;
  const note = $("trading-trial-credit-note");
  if (!note) return;
  if (!trial) {
    note.textContent = "root 不適用";
    return;
  }
  if (trial.status !== "active") {
    note.textContent = `狀態 ${trial.status}`;
    return;
  }
  const countdown = tradingTrialCountdownText(trial);
  note.textContent = `${countdown} · 鎖定 ${formatTradingPointsValue(trial.locked_points)} · 部位 ${formatTradingPointsValue(trial.deployed_points)} · 初始 ${formatTradingPointsValue(trial.initial_points)}`;
}

function tradingNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function currentTradingPosition(marketSymbol) {
  return tradingState.positions.find((row) => row.market_symbol === marketSymbol) || null;
}

function tradingOrderInputMode() {
  return $("trading-input-mode")?.value === "points" ? "points" : "quantity";
}

function formatTradingQuantityValue(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

function tradingQuantityForSubmit(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "";
  return number.toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
}

function syncTradingOrderInputMode() {
  const inputMode = tradingOrderInputMode();
  const input = $("trading-quantity");
  const label = $("trading-quantity-label");
  const note = $("trading-input-mode-note");
  if (label) label.textContent = inputMode === "points" ? "點數金額" : "數量";
  if (input) {
    input.min = inputMode === "points" ? "1" : "0.00000001";
    input.step = inputMode === "points" ? "1" : "0.00000001";
    input.placeholder = inputMode === "points" ? "例如 1000" : "例如 0.01";
  }
  if (note) {
    note.textContent = inputMode === "points"
      ? "買入時點數視為含手續費的總支出；賣出時點數視為成交名目金額，系統自動換算枚數。"
      : "直接輸入 BTC/ETH 枚數。";
  }
}

function tradingOrderDraftEstimate() {
  const market = selectedTradingMarket();
  if (!market) return { ok: false, blocking: true, message: "沒有可用交易市場" };
  const side = $("trading-side")?.value || "buy";
  const orderType = $("trading-order-type")?.value || "market";
  const inputMode = tradingOrderInputMode();
  const inputValue = tradingNumber($("trading-quantity")?.value, 0);
  const limitPrice = tradingNumber($("trading-limit-price")?.value, 0);
  const price = orderType === "limit" ? limitPrice : tradingNumber(market.manual_price_points, 0);
  const feeRate = tradingNumber(market.fee_rate_percent, 0) / 100;
  if (!inputValue || inputValue <= 0) {
    return {
      ok: false,
      blocking: false,
      message: inputMode === "points" ? "輸入點數後自動換算枚數" : "輸入數量後顯示預估金額",
    };
  }
  if (!price || price <= 0) {
    return { ok: false, blocking: true, message: orderType === "limit" ? "請輸入有效限價" : "目前市場價格不可用，暫停下單" };
  }
  let quantity = inputValue;
  if (inputMode === "points") {
    const denominator = side === "buy" ? price * (1 + feeRate) : price;
    quantity = denominator > 0 ? inputValue / denominator : 0;
  }
  if (!quantity || quantity <= 0) {
    return { ok: false, blocking: true, message: "點數金額太小，無法換算有效枚數" };
  }
  const notional = quantity * price;
  const fee = Math.max(0, notional * feeRate);
  const quantityNote = inputMode === "points"
    ? `，約 ${formatTradingQuantityValue(quantity)} ${tradingDisplaySymbol(market.symbol).split("/")[0]}`
    : "";
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
        ? `買入預估 ${formatTradingPointsValue(total)} 點${quantityNote}（含手續費 ${formatTradingPointsValue(fee)}），超過可用 ${formatTradingPointsValue(availablePoints)} 點`
        : `買入預估 ${formatTradingPointsValue(total)} 點${quantityNote}（成交 ${formatTradingPointsValue(notional)} + 手續費 ${formatTradingPointsValue(fee)}）`,
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
      ? `賣出 ${formatTradingQuantityValue(quantity)} 超過可賣現貨 ${formatTradingQuantityValue(sellableQuantity)}`
      : `賣出預估收入 ${formatTradingPointsValue(net)} 點${quantityNote}（成交 ${formatTradingPointsValue(notional)} - 手續費 ${formatTradingPointsValue(fee)}）`,
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
    || { symbol: `${asset}/POINTS`, base_asset: asset, manual_price_points: 0, fee_rate_percent: 0, price_source: "-" }
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
  const feeRate = tradingNumber(market?.fee_rate_percent, 0) * Number(multiplier || 1) / 100;
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
  const allRows = economySpotMarkets(markets);
  const rows = allRows.filter((market) => {
    const pos = positionMap.get(market.symbol) || null;
    const qty = spotPositionNumber(pos, "quantity") + spotPositionNumber(pos, "locked_quantity");
    return qty > 0;
  });
  const card = list.closest(".drive-card");
  if (card) card.style.display = rows.length ? "" : "none";
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
    bindTradingActionButton(btn, () => submitEconomySpotSell(btn.dataset.economySpotLimit || "", "limit"), "正在送出限價賣出...", "限價賣出失敗");
  });
  list.querySelectorAll("[data-economy-spot-market-close]").forEach((btn) => {
    bindTradingActionButton(btn, () => submitEconomySpotSell(btn.dataset.economySpotMarketClose || "", "market"), "正在市價平倉...", "市價平倉失敗");
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
    bindTradingActionButton(btn, () => closeTradingMarginPosition(btn.dataset.economyMarginClose || ""), "正在平倉進階交易...", "進階交易平倉失敗");
  });
  list.querySelectorAll("[data-economy-margin-add-collateral]").forEach((btn) => {
    bindTradingActionButton(btn, () => addTradingMarginCollateral(btn.dataset.economyMarginAddCollateral || "", "economy"), "正在補入保證金...", "補保證金失敗");
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
  const paidInterest = tradingNumber(row.interest_paid_points, 0);
  const interestHours = tradingNumber(row.interest_accrued_hours, 0);
  const entry = tradingNumber(row.entry_price_points, 0);
  const currentPrice = tradingNumber(row.risk?.price_points ?? row.current_price_points, 0);
  const equity = tradingNumber(row.risk?.equity_after_points ?? row.equity_after_points, 0);
  const maintenance = tradingNumber(row.risk?.maintenance_margin_points ?? row.risk?.maintenance_points ?? row.maintenance_margin_points ?? row.maintenance_points, 0);
  const initialMarginRatePercent = tradingNumber(row.risk?.initial_margin_percent ?? row.initial_margin_percent, 0);
  const maintenanceRatePercent = tradingNumber(row.risk?.maintenance_margin_percent ?? row.risk?.maintenance_percent ?? row.maintenance_margin_percent, 0);
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
          原始保證金率 ${formatTradingPointsValue(initialMarginRatePercent)}% · 維持率 ${sanitize(riskText.ratioText)} · 權益 ${formatTradingPointsValue(equity)} · 維持保證金 ${formatTradingPointsValue(maintenance)}（${formatTradingPointsValue(maintenanceRatePercent)}%） · ${sanitize(riskText.statusLabel)}
        </div>
        <div class="drive-card-sub">
          未實現盈虧 <b class="trading-spot-pnl ${pnlClass}">${unrealizedPnl >= 0 ? "+" : ""}${formatTradingPointsValue(unrealizedPnl)} 點</b> · 逐倉估算強平價 ${liquidationPrice ? formatTradingPointsValue(liquidationPrice) : "無法估算"} · 實際清算依全倉維持率
        </div>
        <div class="drive-card-sub">${sanitize(riskText.reason || "")}</div>
        <div class="drive-card-sub">開倉費 ${formatTradingPointsValue(fee)} · 日息 ${formatTradingPercent(row.interest_percent_daily || 0)}% · 已扣利息 ${formatTradingPointsValue(paidInterest)} · 持倉成本利息 ${formatTradingPointsValue(interest)} · 已計 ${formatTradingPointsValue(interestHours)} 小時 · ${sanitize(leverageHint)}</div>
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
  const botSelects = [
    $("trading-auto-bot-market"),
    $("trading-dca-bot-market"),
    $("trading-backtest-market"),
    $("trading-grid-bot-market"),
  ];
  const options = tradingState.markets.length
    ? tradingState.markets.map((market) => `<option value="${sanitize(market.symbol)}">${sanitize(tradingDisplaySymbol(market.symbol))}</option>`).join("")
    : `<option value="">沒有可用市場</option>`;
  [select, rootSelect, contractSelect, marginSelect, ...botSelects].forEach((target) => {
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
  const fundingPoolCard = $("trading-funding-pool-public");
  if (orderForm) orderForm.style.display = "";
  if (submitBtn) submitBtn.disabled = false;
  if (contractCard) contractCard.style.display = currentUser === "root" ? "" : "none";
  const borrowingEnabled = !!tradingState.settings?.borrowing_enabled;
  if (marginCard) marginCard.style.display = "";
  if (fundingPoolCard) fundingPoolCard.style.display = borrowingEnabled ? "" : "none";
  const marginControlsDisabled = !borrowingEnabled;
  ["trading-margin-market-select", "trading-margin-type", "trading-margin-quantity", "trading-margin-collateral", "trading-margin-open-btn"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = marginControlsDisabled;
  });
  if ($("trading-margin-note")) {
    const pool = tradingState.fundingPool || {};
    const effectiveRate = pool.effective_interest_percent_daily ?? tradingState.settings?.borrow_interest_percent_daily ?? 0;
    $("trading-margin-note").textContent = borrowingEnabled
      ? (currentUser === "root"
        ? `root 可用模擬資金進行融資 / 借券，目前浮動日息 ${formatTradingPercent(effectiveRate)}%；不寫入 PointsChain。`
        : `已開啟，目前浮動日息 ${formatTradingPercent(effectiveRate)}%；本金由資金池借出，手續費與利息回到資金池。`)
      : "root 尚未開啟借貸交易，目前僅可查看此區。";
  }
  const fundingPool = tradingState.fundingPool || {};
  if ($("trading-funding-pool-available")) $("trading-funding-pool-available").textContent = formatTradingPointsValue(fundingPool.available_points);
  if ($("trading-funding-pool-outstanding")) $("trading-funding-pool-outstanding").textContent = formatTradingPointsValue(fundingPool.outstanding_principal_points);
  if ($("trading-funding-pool-utilization")) $("trading-funding-pool-utilization").textContent = formatTradingPercent(fundingPool.utilization_percent);
  if ($("trading-funding-pool-rate")) $("trading-funding-pool-rate").textContent = formatTradingPercent(fundingPool.effective_interest_percent_daily);
  if (availabilityNote) {
    availabilityNote.textContent = currentUser === "root"
      ? "root 可使用現貨、進階交易與合約模擬；root 以外用戶目前僅開放現貨與已啟用的進階交易。"
      : "目前僅對 root 以外用戶開放 BTC/USDT、ETH/USDT 現貨。";
  }
  const trial = funding.trial_credit || null;
  const trialAvailable = trial ? Number(trial.available_points || 0) : 0;
  const trialInitial = trial ? Number(trial.initial_points || 0) : 0;
  const walletAvailable = Number(funding.wallet_available_points || 0);
  const totalAvailable = Number(funding.available_points ?? (walletAvailable + trialAvailable));
  if ($("trading-funding-available")) $("trading-funding-available").textContent = funding.available_points != null ? formatTradingPointsValue(totalAvailable) : "-";
  if ($("trading-funding-mode")) {
    $("trading-funding-mode").textContent = funding.mode === "root_simulated"
      ? `root 模擬資金 · 鎖定 ${formatTradingPointsValue(funding.locked_points)}`
      : `體驗金優先 · 總可用 ${formatTradingPointsValue(totalAvailable)} = 體驗金 ${formatTradingPointsValue(trialAvailable)} + 真實積分 ${formatTradingPointsValue(walletAvailable)} · 鎖定 ${formatTradingPointsValue(funding.locked_points)}`;
  }
  if ($("trading-trial-credit-available")) {
    $("trading-trial-credit-available").textContent = trial ? `${formatTradingPointsValue(trialAvailable)} / ${formatTradingPointsValue(trialInitial)}` : "-";
  }
  updateTradingTrialCountdown();
  if ($("trading-current-price")) $("trading-current-price").textContent = market ? String(Number(market.manual_price_points || 0)) : "-";
  if ($("trading-current-market")) $("trading-current-market").textContent = market ? `${tradingDisplaySymbol(market.symbol)} · ${market.price_source || "last_good_cache"}` : "-";
  if ($("trading-fee-rate-percent")) $("trading-fee-rate-percent").textContent = market ? formatTradingPercent(market.fee_rate_percent || 0) : "-";
  const position = market ? tradingState.positions.find((row) => row.market_symbol === market.symbol) : null;
  if ($("trading-position-quantity")) $("trading-position-quantity").textContent = position ? sanitize(position.quantity || "0") : "0";
  if ($("trading-position-locked")) $("trading-position-locked").textContent = `鎖定 ${position ? sanitize(position.locked_quantity || "0") : "0"}`;
  const limit = $("trading-limit-price");
  if (limit && market && !$("trading-root-price")?.matches(":focus")) {
    limit.placeholder = `目前 ${Number(market.manual_price_points || 0)}`;
  }
  syncTradingOrderSideTheme();
  syncTradingOrderInputMode();
  updateTradingOrderEstimate();
  updateTradingMarginEstimate();
  loadTradingBtcSignal();
  loadTradingReferencePrices();
}

function tradingSignalBoolLabel(value) {
  if (value === true) return "通過";
  if (value === false) return "未通過";
  return "-";
}

function tradingBtcSignalCountdownText(signal) {
  const nextAt = signal?.next_prediction_at ? new Date(signal.next_prediction_at).getTime() : 0;
  if (!Number.isFinite(nextAt) || nextAt <= 0) return "";
  const remainingMs = Math.max(0, nextAt - Date.now());
  return remainingMs > 0
    ? `下次預測倒數 ${formatTradingDuration(remainingMs)}`
    : "下次預測即將更新";
}

function updateTradingBtcSignalMeta() {
  const meta = $("trading-btc-signal-meta");
  const card = $("trading-btc-signal-card");
  const payload = tradingState.btcSignal || null;
  const signal = payload?.signal || null;
  if (!meta || !card || card.style.display === "none" || !payload?.available || !signal) return;
  const updatedAt = signal.updated_at ? new Date(signal.updated_at) : null;
  const updated = updatedAt && Number.isFinite(updatedAt.getTime()) ? updatedAt.toLocaleString() : "-";
  const ageMs = updatedAt && Number.isFinite(updatedAt.getTime()) ? Math.max(0, Date.now() - updatedAt.getTime()) : Number(signal.age_seconds || 0) * 1000;
  const countdown = tradingBtcSignalCountdownText(signal);
  meta.textContent = `來源 BTC_trade · 週期 ${signal.timeframe || "4h"} · 更新 ${updated}${ageMs ? ` · 約 ${formatTradingDuration(ageMs)} 前` : ""}${countdown ? ` · ${countdown}` : ""}`;
}

function renderTradingBtcSignal(payload = null) {
  const card = $("trading-btc-signal-card");
  if (!card) return;
  const market = selectedTradingMarket();
  if (!market || tradingDisplaySymbol(market.symbol) !== "BTC/USDT" || !payload?.available || !payload.signal) {
    card.style.display = "none";
    return;
  }
  const signal = payload.signal || {};
  const entryChecks = signal.entry_checks && typeof signal.entry_checks === "object" ? signal.entry_checks : {};
  const ml = signal.ml_status && typeof signal.ml_status === "object" ? signal.ml_status : {};
  const signalOk = signal.signal_ok === true;
  const mlOk = signal.ml_ok === true;
  const badge = $("trading-btc-signal-badge");
  const meta = $("trading-btc-signal-meta");
  const body = $("trading-btc-signal-body");
  const checks = $("trading-btc-signal-checks");
  card.style.display = "";
  if (badge) {
    badge.textContent = signalOk && mlOk ? "偏多觀察" : "等待條件";
    badge.style.background = signalOk && mlOk ? "rgba(76,175,80,.18)" : "rgba(255,183,77,.16)";
    badge.style.color = signalOk && mlOk ? "#4caf50" : "#ffb74d";
  }
  if (meta) {
    updateTradingBtcSignalMeta();
  }
  if (body) {
    body.innerHTML = `
      <div><span class="drive-card-sub">目前價格</span><strong>${sanitize(tradingReferenceLabel(signal.current_price))}</strong><small>BTC/USDT</small></div>
      <div><span class="drive-card-sub">七條件信號</span><strong>${sanitize(tradingSignalBoolLabel(signal.signal_ok))}</strong><small>${signalOk ? "可進場觀察" : "未全滿足"}</small></div>
      <div><span class="drive-card-sub">ML 過濾</span><strong>${sanitize(tradingSignalBoolLabel(signal.ml_ok))}</strong><small>${sanitize(ml.situation || (ml.blocked ? "已阻擋" : "未提供"))}</small></div>
      <div><span class="drive-card-sub">BTC_trade 持倉</span><strong>${sanitize(signal.position || signal.portfolio?.position || "空手")}</strong><small>${sanitize(signal.last_trade?.action || "無最新交易")}</small></div>
      <div><span class="drive-card-sub">策略版本</span><strong>${sanitize(signal.strategy_version || "-")}</strong><small>Fear & Greed ${sanitize(signal.fear_greed ?? "-")}</small></div>
      ${signal.next_prediction_at ? `<div><span class="drive-card-sub">下次預測</span><strong>${sanitize(tradingBtcSignalCountdownText(signal).replace("下次預測", "").trim())}</strong><small>${sanitize(new Date(signal.next_prediction_at).toLocaleString())}</small></div>` : ""}
    `;
  }
  if (checks) {
    const rows = Object.entries(entryChecks).map(([name, ok]) => `${ok ? "✓" : "×"} ${name}`).slice(0, 12);
    checks.textContent = rows.length ? rows.join(" · ") : "尚無條件細節";
  }
}

async function loadTradingBtcSignal() {
  const market = selectedTradingMarket();
  if (!market || tradingDisplaySymbol(market.symbol) !== "BTC/USDT") {
    renderTradingBtcSignal(null);
    return;
  }
  try {
    const json = await fetchTradingJson(`/trading/btc-signal?market=${encodeURIComponent(market.symbol)}`);
    tradingState.btcSignal = json;
    renderTradingBtcSignal(json);
  } catch (_) {
    tradingState.btcSignal = null;
    renderTradingBtcSignal(null);
  }
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
      if (currentModuleTab === "economy" && tradingState.positions.length) {
        renderEconomySpotPositionDetails(tradingState.positions, tradingState.markets);
      }
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
    const botTag = row.bot_name ? `<span class="trading-bot-tag">🤖 ${sanitize(row.bot_name)}</span>` : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.side)} · ${sanitize(row.order_type)} · ${sanitize(row.status)}${botTag ? ` ${botTag}` : ""}</strong>
          <div class="drive-card-sub">${sanitize(tradingDisplaySymbol(row.market_symbol))} · 數量 ${sanitize(row.quantity)} · 價格 ${sanitize(price || "-")} · 凍結 ${Number(row.frozen_points || 0)}</div>
          <div class="economy-ledger-hash">${sanitize(row.order_uuid || "")}</div>
        </div>
        ${allowCancel && canCancel ? `<button class="btn" type="button" data-trading-cancel="${sanitize(row.order_uuid || "")}">取消</button>` : ""}
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-trading-cancel]").forEach((btn) => {
    bindTradingActionButton(btn, () => cancelTradingOrder(btn.dataset.tradingCancel || ""), "正在取消訂單...", "取消訂單失敗");
  });
}

function renderTradingFills(rows, targetId = "trading-fill-list") {
  const list = $(targetId);
  if (!list) return;
  if (!rows || !rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無成交</div>`;
    return;
  }
  list.innerHTML = rows.map((row) => {
    const isMargin = String(row.record_type || "").startsWith("margin_");
    const pnl = row.realized_pnl_points == null ? null : Number(row.realized_pnl_points || 0);
    const interest = Number(row.interest_points || 0);
    const extra = isMargin
      ? `${pnl == null ? "" : ` · 損益 ${pnl >= 0 ? "+" : ""}${pnl} 點`}${interest ? ` · 利息 ${interest} 點` : ""}`
      : "";
    const botTag = row.bot_name ? `<span class="trading-bot-tag">🤖 ${sanitize(row.bot_name)}</span>` : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.side)} · ${sanitize(tradingDisplaySymbol(row.market_symbol))} · ${sanitize(row.quantity)}${botTag ? ` ${botTag}` : ""}</strong>
          <div class="drive-card-sub">${isMargin ? "進階交易" : "現貨成交"} · 價格 ${Number(row.price_points || 0) || "-"} · 成交 ${Number(row.notional_points || 0)} 點 · 手續費 ${Number(row.fee_points || 0)}${extra}</div>
          <div class="drive-card-sub">${sanitize(row.created_at || "")}</div>
          ${row.position_uuid ? `<div class="economy-ledger-hash">${sanitize(row.position_uuid || "")}</div>` : ""}
        </div>
      </div>
    `;
  }).join("");
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
    bindTradingActionButton(btn, () => closeRootTradingContract(btn.dataset.contractClose || ""), "正在平倉合約...", "合約平倉失敗");
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
  const marginLongFinancingRatePercent = tradingNumber(tradingState.settings?.margin_long_financing_percent, 90);
  const shortCollateralRatePercent = tradingNumber(tradingState.settings?.short_collateral_percent, 60);
  const feeRatePercent = tradingNumber(market.fee_rate_percent, 0);
  const maintenancePercent = tradingNumber(tradingState.settings?.margin_maintenance_percent, 15);
  const baseMinCollateral = positionType === "short"
    ? Math.ceil(notional * shortCollateralRatePercent / 100)
    : Math.ceil(notional * Math.max(0, 100 - marginLongFinancingRatePercent) / 100);
  const safetyMinCollateral = Math.ceil(notional * Math.max(0, maintenancePercent + feeRatePercent) / 100) + 1;
  const minCollateral = Math.max(baseMinCollateral, safetyMinCollateral);
  const fee = Math.ceil(notional * feeRatePercent / 100);
  const available = tradingNumber(tradingState.funding?.available_points, 0);
  const principal = positionType === "short" ? notional : Math.max(0, notional - collateral);
  const fundingPool = tradingState.fundingPool || {};
  const poolAvailable = tradingNumber(fundingPool.available_points, 0);
  const poolRate = tradingNumber(
    fundingPool.projected_interest_percent_daily ?? fundingPool.effective_interest_percent_daily,
    tradingState.settings?.borrow_interest_percent_daily || 0
  );
  const typeLabel = positionType === "short" ? "借券放空" : "融資買入";
  if (!quantity || !collateral || !notional) {
    estimate.textContent = "輸入數量與保證金後顯示預估風險。";
    estimate.style.color = "var(--muted)";
    if (openBtn) openBtn.disabled = true;
    return { ok: false, blocking: true, message: estimate.textContent };
  }
  let message = `${typeLabel} · 名目金額約 ${notional} 點 · 開倉費 ${fee} 點 · 原始保證金最低需求 ${minCollateral} 點 · 目前填寫 ${collateral} 點`;
  if (positionType === "short") {
    message = `${message}；借券放空風險：價格上漲會虧損並降低維持率；借券保證金比例 ${formatTradingPercent(shortCollateralRatePercent)}%`;
  } else {
    message = `${message}；融資可貸比例 ${formatTradingPercent(marginLongFinancingRatePercent)}%`;
  }
  let blocking = false;
  if (positionType === "margin_long" && collateral >= notional) {
    const maxLongCollateral = Math.max(1, notional - 1);
    message = `${message}；融資保證金不可大於或等於名目金額，最高 ${maxLongCollateral} 點。若不需要借貸，請改用現貨買入。`;
    blocking = true;
  } else if (collateral < minCollateral) {
    message = `${message}；原始保證金不足，至少需要 ${minCollateral} 點`;
    blocking = true;
  } else if ((collateral + fee) > available) {
    message = `${message}；可用資金不足，需要 ${collateral + fee} 點，目前可用 ${available} 點`;
    blocking = true;
  } else if (principal > poolAvailable && currentUser !== "root") {
    message = `${message}；資金池不足，需要借出 ${principal} 點，目前可借 ${poolAvailable} 點`;
    blocking = true;
  } else if (tradingState.settings?.borrowing_enabled) {
    message = `${message}；預估借出本金 ${principal} 點，目前浮動日息約 ${formatTradingPercent(poolRate)}%`;
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
    bindTradingActionButton(btn, () => closeTradingMarginPosition(btn.dataset.marginClose || ""), "正在平倉進階交易...", "進階交易平倉失敗");
  });
  list.querySelectorAll("[data-margin-add-collateral]").forEach((btn) => {
    bindTradingActionButton(btn, () => addTradingMarginCollateral(btn.dataset.marginAddCollateral || ""), "正在補入保證金...", "補保證金失敗");
  });
}

function renderTradingMarginAccountSummary(summary = null) {
  const wrap = $("trading-margin-account-summary");
  if (!wrap) return;
  const data = summary || {};
  if (!data.open_count) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";
  const ratio = data.cross_margin_ratio_percent ?? data.maintenance_ratio_percent;
  if ($("trading-margin-cross-ratio")) {
    $("trading-margin-cross-ratio").textContent = ratio == null ? "無法計算" : `${formatTradingPointsValue(ratio)}%`;
  }
  if ($("trading-margin-cross-status")) $("trading-margin-cross-status").textContent = data.reason || "整戶維持率正常";
  if ($("trading-margin-account-equity")) $("trading-margin-account-equity").textContent = `${formatTradingPointsValue(data.account_equity_points || 0)} 點`;
  if ($("trading-margin-free-margin")) $("trading-margin-free-margin").textContent = `${formatTradingPointsValue(data.free_margin_points || 0)} 點`;
  if ($("trading-margin-available-margin")) $("trading-margin-available-margin").textContent = `維持後可用 ${formatTradingPointsValue(data.available_margin_points || 0)} 點`;
  if ($("trading-margin-total-borrowed")) $("trading-margin-total-borrowed").textContent = `${formatTradingPointsValue(data.total_borrowed_points || 0)} 點`;
  if ($("trading-margin-maintenance-total")) $("trading-margin-maintenance-total").textContent = `總維持需求 ${formatTradingPointsValue(data.total_maintenance_requirement_points || data.total_maintenance_points || 0)} 點`;
}

function tradingBotTriggerLabel(row) {
  if (row.bot_type === "dca") return `每 ${Number(row.interval_hours || 24)} 小時定投 ${formatTradingPointsValue(row.budget_points)} 點`;
  if (row.workflow) {
    const branches = Array.isArray(row.workflow.branches) ? row.workflow.branches : [];
    return branches.length ? `${branches.length} 個 workflow 分支` : "Workflow 尚未設定";
  }
  const price = formatTradingPointsValue(row.trigger_price_points || 0);
  if (row.trigger_type === "price_above") return `價格 >= ${price}`;
  if (row.trigger_type === "price_below") return `價格 <= ${price}`;
  return "每次掃描";
}

function switchTradingBotTab(tab) {
  tradingCurrentBotTab = tab || "dca";
  document.querySelectorAll("[data-trading-bot-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tradingBotTab === tradingCurrentBotTab);
  });
  document.querySelectorAll(".trading-bot-tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `trading-bot-tab-${tradingCurrentBotTab}`);
  });
}

function tradingWorkflowTemplates() {
  if (!Array.isArray(tradingState.workflowTemplates) || !tradingState.workflowTemplates.length) return {};
  return tradingState.workflowTemplates.reduce((acc, item) => {
    if (item && item.id && item.workflow) {
      acc[item.id] = {
          label: item.label || item.id,
          description: item.description || "",
          explanation: item.explanation || {},
          scope: item.scope || "system",
          source_path: item.source_path || "",
          workflow: item.workflow,
      };
    }
    return acc;
  }, {});
}

function renderTradingWorkflowTemplateOptions() {
  const select = $("trading-workflow-template-select");
  if (!select) return;
  const previous = select.value;
  const templates = tradingWorkflowTemplates();
  const entries = Object.entries(templates);
  if (!entries.length) {
    select.innerHTML = `<option value="">沒有可用模板</option>`;
    return;
  }
  select.innerHTML = entries.map(([id, item]) => {
    const scopeLabel = item.scope === "custom" ? "自訂" : "系統";
    return `<option value="${sanitize(id)}">${sanitize(item.label || id)}（${scopeLabel}）</option>`;
  }).join("");
  if (previous && entries.some(([id]) => id === previous)) select.value = previous;
  renderTradingWorkflowTemplateExplanation();
}

function tradingWorkflowExplanationList(items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `<ul>${items.map((item) => `<li>${sanitize(item)}</li>`).join("")}</ul>`;
}

function renderTradingWorkflowTemplateExplanation() {
  const box = $("trading-workflow-template-explanation");
  if (!box) return;
  const key = $("trading-workflow-template-select")?.value || "";
  const item = tradingWorkflowTemplates()[key];
  if (!item) {
    box.innerHTML = `<div class="muted">選擇模板後會顯示用途、條件、行為與風險提醒。</div>`;
    return;
  }
  const detail = item.explanation || {};
  const sections = [
    ["用途", detail.purpose || item.description],
    ["觸發條件", tradingWorkflowExplanationList(detail.entry_conditions)],
    ["執行行為", tradingWorkflowExplanationList(detail.actions)],
    ["風險提醒", tradingWorkflowExplanationList(detail.risk_notes)],
    ["適合情境", tradingWorkflowExplanationList(detail.best_for)],
    ["可調參數", tradingWorkflowExplanationList(detail.tuning)],
  ].filter(([, content]) => !!content);
  box.innerHTML = `
    <div class="drive-card-title">${sanitize(item.label || key)}</div>
    ${sections.map(([title, content]) => `
      <div class="workflow-template-section">
        <strong>${sanitize(title)}</strong>
        <div>${content.startsWith("<") ? content : sanitize(content)}</div>
      </div>
    `).join("")}
    <div class="muted">來源：${sanitize(item.source_path || item.scope || "workflow")}</div>
  `;
}

async function loadTradingWorkflowTemplates({ force = false } = {}) {
  if (!force && Array.isArray(tradingState.workflowTemplates) && tradingState.workflowTemplates.length) {
    renderTradingWorkflowTemplateOptions();
    return;
  }
  try {
    const json = await fetchTradingJson("/trading/workflow-templates");
    tradingState.workflowTemplates = Array.isArray(json.templates) ? json.templates : [];
    renderTradingWorkflowTemplateOptions();
    populateBacktestWorkflowTemplates();
    if (Array.isArray(json.errors) && json.errors.length) {
      tradingSetMsg(`部分 Workflow 模板載入失敗：${json.errors[0].error || "未知錯誤"}`, false);
    }
  } catch (err) {
    renderTradingWorkflowTemplateOptions();
    tradingSetMsg(err.message || "Workflow 模板讀取失敗，請確認 workflows/system 內有模板檔", false);
  }
}

async function saveTradingWorkflowCustomTemplate() {
  const textarea = $("trading-auto-workflow-json");
  if (!textarea) {
    tradingSetMsg("找不到 Workflow JSON 編輯欄位", false);
    return;
  }
  let workflow;
  try {
    workflow = JSON.parse(textarea.value || tradingWorkflowText());
  } catch (err) {
    tradingSetMsg("Workflow JSON 格式錯誤，無法儲存自訂模板", false);
    return;
  }
  const label = ($("trading-workflow-custom-name")?.value || workflow.name || "自訂 Workflow").trim();
  try {
    const json = await fetchTradingJson("/trading/workflow-templates/custom", {
      method: "POST",
      body: JSON.stringify({
        id: label,
        label,
        description: workflow.description || "",
        workflow,
      }),
    });
    if (json.template) {
      tradingState.workflowTemplates = [
        ...(tradingState.workflowTemplates || []).filter((item) => item.id !== json.template.id),
        json.template,
      ];
      renderTradingWorkflowTemplateOptions();
      const select = $("trading-workflow-template-select");
      if (select) select.value = json.template.id;
    } else {
      await loadTradingWorkflowTemplates({ force: true });
    }
    tradingSetMsg(json.msg || "Workflow 自訂模板已儲存到 workflows/custom");
  } catch (err) {
    tradingSetMsg(err.message || "Workflow 自訂模板儲存失敗", false);
  }
}

function tradingWorkflowTemplate(name = "dip_buy") {
  const templates = tradingWorkflowTemplates();
  const item = templates[name] || templates.dip_buy || Object.values(templates)[0];
  if (!item || !item.workflow) {
    return {
      version: 2,
      strategy_kind: "workflow_graph",
      name: "空白 Workflow",
      start_node_id: "start",
      nodes: [{ id: "start", type: "start", label: "開始", x: 80, y: 100 }],
      edges: [],
    };
  }
  return JSON.parse(JSON.stringify(item.workflow));
}

function applyTradingWorkflowTemplate() {
  const key = $("trading-workflow-template-select")?.value || "dip_buy";
  const templates = tradingWorkflowTemplates();
  const item = templates[key] || templates.dip_buy;
  if (!item || !item.workflow) {
    tradingSetMsg("沒有可用 Workflow 模板，請確認 workflows/system 內有模板檔", false);
    return;
  }
  const textarea = $("trading-auto-workflow-json");
  if (!textarea) {
    tradingSetMsg("找不到 Workflow JSON 編輯欄位", false);
    return;
  }
  textarea.value = JSON.stringify(item.workflow, null, 2);
  localStorage.setItem(TRADING_WORKFLOW_STORAGE_KEY, textarea.value);
  renderTradingWorkflowTemplateExplanation();
  tradingSetMsg(`已套用基礎模板：${item.label}。請依市場價格調整門檻後再儲存機器人。`);
}

function tradingWorkflowText() {
  const raw = $("trading-auto-workflow-json")?.value || "";
  if (raw.trim()) return raw.trim();
  const saved = localStorage.getItem(TRADING_WORKFLOW_STORAGE_KEY);
  return saved || JSON.stringify(tradingWorkflowTemplate(), null, 2);
}

function loadTradingWorkflowFromEditor() {
  const saved = localStorage.getItem(TRADING_WORKFLOW_STORAGE_KEY);
  const textarea = $("trading-auto-workflow-json");
  if (!textarea) return;
  textarea.value = saved || JSON.stringify(tradingWorkflowTemplate(), null, 2);
  tradingSetMsg(saved ? "已載入 Workflow 編輯器結果" : "尚無編輯器結果，已載入預設範例");
}

function parseTradingWorkflowInput() {
  try {
    return JSON.parse(tradingWorkflowText());
  } catch (err) {
    throw new Error("Workflow JSON 格式錯誤，請回編輯器修正後再載入");
  }
}

function formatTradingCountdown(ms) {
  const seconds = Math.max(0, Math.ceil(Number(ms || 0) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours > 0) return `${hours} 小時 ${String(minutes).padStart(2, "0")} 分 ${String(rest).padStart(2, "0")} 秒`;
  return `${minutes} 分 ${String(rest).padStart(2, "0")} 秒`;
}

function parseTradingDateMs(value) {
  if (!value) return NaN;
  const raw = String(value);
  let parsed = Date.parse(raw);
  if (!Number.isNaN(parsed)) return parsed;
  parsed = Date.parse(raw.replace(" ", "T"));
  return parsed;
}

function tradingBotNextRunInfo(row) {
  if (!row || !row.enabled) return { text: "下次執行：已停用", ready: false };
  if (Number(row.run_count || 0) >= Number(row.max_runs || 1)) return { text: "下次執行：已達最大次數", ready: false };
  let nextMs = parseTradingDateMs(row.next_run_at);
  if (Number.isNaN(nextMs)) {
    const lastMs = parseTradingDateMs(row.last_run_at);
    nextMs = Number.isNaN(lastMs) ? Date.now() : lastMs + (Number(row.cooldown_seconds || 0) * 1000);
  }
  const remaining = nextMs - Date.now();
  if (remaining <= 0) {
    const neverRan = !row.last_run_at && Number(row.run_count || 0) === 0;
    return { text: neverRan ? "下次執行：等待首次執行…" : "下次執行：可立即執行", ready: true };
  }
  const when = new Date(nextMs).toLocaleString("zh-TW", { hour12: false });
  const intervalHours = Number(row.interval_hours || 0);
  const intervalText = intervalHours > 0 ? `　每 ${intervalHours} 小時定投` : "";
  return { text: `下次執行：${formatTradingCountdown(remaining)} 後（${when}）${intervalText}`, ready: false };
}

function tradingBotNextRunText(row) {
  return tradingBotNextRunInfo(row).text;
}

function updateTradingBotCountdowns() {
  document.querySelectorAll("[data-trading-bot-next-run]").forEach((node) => {
    const uuid = node.dataset.tradingBotNextRun || "";
    const row = (tradingState.bots || []).find((item) => item.bot_uuid === uuid);
    node.textContent = tradingBotNextRunText(row);
  });
}

function restartTradingBotCountdown() {
  if (tradingBotCountdownTimer) window.clearInterval(tradingBotCountdownTimer);
  tradingBotCountdownTimer = null;
  updateTradingBotCountdowns();
  if ((tradingState.bots || []).some((row) => row.enabled && Number(row.run_count || 0) < Number(row.max_runs || 1))) {
    tradingBotCountdownTimer = window.setInterval(updateTradingBotCountdowns, 1000);
  }
}

function renderTradingBots(rows = [], runs = []) {
  const dcaList = $("trading-dca-bot-list");
  const strategyList = $("trading-strategy-bot-list");
  const runList = $("trading-bot-run-list");
  const renderRows = (items, emptyText) => items.length ? items.map((row) => {
    const checks = Array.isArray(row.condition_checks) ? row.condition_checks : [];
    const condHtml = checks.length
      ? `<div class="drive-card-sub trading-bot-conditions">${checks.map((c) => `<span class="${c.met ? "trading-condition-met" : "trading-condition-unmet"}">${sanitize(c.label)}</span>`).join("")}</div>`
      : "";
    return `
        <div class="drive-file-row">
          <div>
            <strong>${sanitize(row.name || "未命名機器人")} · ${sanitize(tradingDisplaySymbol(row.market_symbol || ""))}</strong>
            <div class="drive-card-sub">
              ${sanitize(row.bot_type_label || (row.bot_type === "dca" ? "定投機器人" : "Workflow 機器人"))} · ${sanitize(tradingBotTriggerLabel(row))} 時 ${row.side === "sell" ? "賣出" : "買入"} ${row.bot_type === "dca" ? "系統換算數量" : sanitize(row.quantity_text || "workflow 決定")}，
              ${row.order_type === "limit" ? `限價 ${formatTradingPointsValue(row.limit_price_points)}` : "市價單"}
            </div>
            <div class="drive-card-sub">
              狀態 ${row.enabled ? "啟用" : "停用"} · 已觸發 ${Number(row.run_count || 0)} / ${Number(row.max_runs || 1)} · 冷卻 ${Number(row.cooldown_seconds || 0)} 秒
            </div>
            ${condHtml}
            <div class="drive-card-sub" data-trading-bot-next-run="${sanitize(row.bot_uuid || "")}">${sanitize(tradingBotNextRunText(row))}</div>
            ${row.last_error ? `<div class="drive-card-sub negative">上次錯誤：${sanitize(row.last_error)}</div>` : ""}
          </div>
          <div class="drive-file-actions">
            <button class="btn" type="button" data-trading-bot-toggle="${sanitize(row.bot_uuid || "")}" data-trading-bot-enabled="${row.enabled ? "0" : "1"}">${row.enabled ? "暫停" : "啟用"}</button>
            <button class="btn" type="button" data-trading-bot-backtest="${sanitize(row.bot_uuid || "")}">回測</button>
            <button class="btn btn-danger" type="button" data-trading-bot-delete="${sanitize(row.bot_uuid || "")}">刪除</button>
          </div>
        </div>
      `;
  }).join("") : `<div class="drive-empty">${sanitize(emptyText)}</div>`;
  if (dcaList) dcaList.innerHTML = renderRows(rows.filter((row) => row.bot_type === "dca"), "尚無定投機器人");
  if (strategyList) strategyList.innerHTML = renderRows(rows.filter((row) => row.bot_type !== "dca"), "尚無自動化 Workflow");
  [dcaList, strategyList].forEach((list) => {
    if (!list) return;
    list.querySelectorAll("[data-trading-bot-delete]").forEach((btn) => {
      bindTradingActionButton(btn, () => deleteTradingBot(btn.dataset.tradingBotDelete || ""), "準備刪除交易機器人...", "交易機器人刪除失敗");
    });
    list.querySelectorAll("[data-trading-bot-toggle]").forEach((btn) => {
      bindTradingActionButton(
        btn,
        () => toggleTradingBot(btn.dataset.tradingBotToggle || "", btn.dataset.tradingBotEnabled === "1"),
        btn.dataset.tradingBotEnabled === "1" ? "準備啟用交易機器人..." : "準備暫停交易機器人...",
        "交易機器人狀態更新失敗"
      );
    });
    list.querySelectorAll("[data-trading-bot-backtest]").forEach((btn) => {
      bindTradingActionButton(btn, () => prepareTradingBacktestFromBot(btn.dataset.tradingBotBacktest || ""), "正在帶入回測設定...", "回測設定帶入失敗");
    });
  });
  const botSelect = $("trading-backtest-bot-select");
  if (botSelect) {
    const previous = botSelect.value;
    botSelect.innerHTML = `<option value="">使用目前表單設定</option>` + rows.map((row) => `<option value="${sanitize(row.bot_uuid || "")}">${sanitize(row.bot_type === "dca" ? "定投" : "Workflow")} · ${sanitize(row.name || row.market_symbol || "")}</option>`).join("");
    if (previous && Array.from(botSelect.options).some((option) => option.value === previous)) botSelect.value = previous;
  }
  if (runList) {
    if (!runs.length) {
      runList.innerHTML = `<div class="drive-empty">尚無執行紀錄</div>`;
    } else {
      runList.innerHTML = runs.slice(0, 20).map((row) => `
        <div class="drive-file-row">
          <div>
            <strong>${sanitize(row.status || "-")} · ${sanitize(tradingDisplaySymbol(row.market_symbol || ""))}</strong>
            <div class="drive-card-sub">觀測價 ${formatTradingPointsValue(row.observed_price_points)} · 條件 ${sanitize(row.trigger_type || "-")} ${row.trigger_price_points ? formatTradingPointsValue(row.trigger_price_points) : ""}</div>
            <div class="drive-card-sub">${sanitize(row.created_at || "")}${row.order_uuid ? ` · 訂單 ${sanitize(row.order_uuid)}` : ""}</div>
            ${row.error ? `<div class="drive-card-sub negative">${sanitize(row.error)}</div>` : ""}
          </div>
        </div>
      `).join("");
    }
  }
  restartTradingBotCountdown();
}

// ── Grid Trading Bot ────────────────────────────────────────────────────────

let tradingGridBots = [];

function renderGridBotPreview() {
  const upper = Number($("trading-grid-upper-price")?.value || 0);
  const lower = Number($("trading-grid-lower-price")?.value || 0);
  const count = Number($("trading-grid-count")?.value || 10);
  const amount = Number($("trading-grid-order-amount")?.value || 0);
  const preview = $("trading-grid-preview");
  if (!preview) return;
  if (!upper || !lower || upper <= lower || count < 2) {
    preview.textContent = "";
    return;
  }
  const step = (upper - lower) / (count - 1);
  const levels = count;
  const totalCost = amount * levels;
  const stepPct = ((step / lower) * 100).toFixed(2);
  preview.textContent = `${levels} 個網格，間距 ${formatTradingPointsValue(Math.round(step))} 點（約 ${stepPct}%），預估最大投入約 ${formatTradingPointsValue(totalCost)} 點`;
}

function renderGridBotVisual(bot, currentPrice) {
  const levels = Array.isArray(bot.grid_levels) ? bot.grid_levels : [];
  if (!levels.length) return `<div class="drive-card-sub">（無網格層）</div>`;
  const orders = Array.isArray(bot.orders) ? bot.orders : [];
  const orderByLevel = {};
  for (const o of orders) {
    orderByLevel[o.level_index] = o;
  }
  const cp = Number(currentPrice || bot.initial_price_points || 0);
  const rows = [...levels].reverse().map((price, revIdx) => {
    const idx = levels.length - 1 - revIdx;
    const order = orderByLevel[idx];
    const isCurrent = cp > 0 && Math.abs(price - cp) / cp < 0.005;
    let statusClass = "grid-level-empty";
    let statusText = "—";
    let sideLabel = "";
    if (order) {
      if (order.status === "open") {
        if (order.side === "buy") { statusClass = "grid-level-buy"; statusText = "掛買"; sideLabel = "BUY"; }
        else { statusClass = "grid-level-sell"; statusText = "掛賣"; sideLabel = "SELL"; }
      } else if (order.status === "filled") {
        statusClass = "grid-level-filled";
        statusText = order.side === "buy" ? "買入成交" : "賣出成交";
        sideLabel = order.side === "buy" ? "BUY✓" : "SELL✓";
      } else {
        statusClass = "grid-level-cancelled";
        statusText = "已取消";
      }
    }
    const currentMark = isCurrent ? `<span class="grid-current-price-mark">◀ 現價</span>` : "";
    return `<div class="grid-level-row ${statusClass}${isCurrent ? " grid-current-price-row" : ""}">
      <span class="grid-level-price">${formatTradingPointsValue(price)}</span>
      <span class="grid-level-side">${sideLabel}</span>
      <span class="grid-level-status">${statusText}</span>
      ${currentMark}
    </div>`;
  });
  return `<div class="grid-visual">${rows.join("")}</div>`;
}

function renderGridBotList(bots, currentPriceMap) {
  const container = $("trading-grid-bot-list");
  if (!container) return;
  if (!bots.length) {
    container.innerHTML = `<div class="drive-empty">尚無網格機器人，在上方建立第一個網格</div>`;
    return;
  }
  container.innerHTML = bots.map((bot) => {
    const cp = (currentPriceMap || {})[bot.market_symbol] || bot.initial_price_points || 0;
    const symbol = sanitize(tradingDisplaySymbol(bot.market_symbol || ""));
    const profit = Number(bot.total_profit_points || 0);
    const profitClass = profit >= 0 ? "positive" : "negative";
    const orders = Array.isArray(bot.orders) ? bot.orders : [];
    const openOrders = orders.filter((o) => o.status === "open");
    const buyOrders = openOrders.filter((o) => o.side === "buy");
    const sellOrders = openOrders.filter((o) => o.side === "sell");
    const levels = Array.isArray(bot.grid_levels) ? bot.grid_levels : [];
    return `<div class="drive-file-row grid-bot-card" data-grid-bot-uuid="${sanitize(bot.bot_uuid || "")}">
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;">
          <strong>${sanitize(bot.name || "網格機器人")} · ${symbol}</strong>
          <span class="grid-status-badge ${bot.enabled ? "grid-status-running" : "grid-status-stopped"}">${bot.enabled ? "運行中" : "已暫停"}</span>
        </div>
        <div class="drive-card-sub">
          區間 ${formatTradingPointsValue(bot.lower_price_points)} ～ ${formatTradingPointsValue(bot.upper_price_points)} · ${Number(bot.grid_count)} 格 · 每格 ${formatTradingPointsValue(bot.order_amount_points)} 點
        </div>
        <div class="drive-card-sub">
          現價 ${formatTradingPointsValue(cp)} · 掛單：<span class="grid-buy-count">買 ${buyOrders.length}</span> / <span class="grid-sell-count">賣 ${sellOrders.length}</span> · 已成交 ${Number(bot.total_trades || 0)} 次 · 累計損益 <span class="${profitClass}">${profit >= 0 ? "+" : ""}${formatTradingPointsValue(profit)}</span> 點
        </div>
        ${bot.last_error ? `<div class="drive-card-sub negative">錯誤：${sanitize(bot.last_error)}</div>` : ""}
        <details class="grid-visual-details">
          <summary class="drive-card-sub" style="cursor:pointer;user-select:none;">展開網格掛單圖（共 ${levels.length} 層）</summary>
          ${renderGridBotVisual(bot, cp)}
        </details>
      </div>
      <div class="drive-file-actions" style="flex-shrink:0;">
        <button class="btn btn-sm" type="button" data-grid-toggle="${sanitize(bot.bot_uuid || "")}" data-grid-enabled="${bot.enabled ? "0" : "1"}">${bot.enabled ? "暫停" : "啟用"}</button>
        <button class="btn btn-sm btn-danger" type="button" data-grid-delete="${sanitize(bot.bot_uuid || "")}">刪除</button>
      </div>
    </div>`;
  }).join("");
  container.querySelectorAll("[data-grid-toggle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const uuid = btn.dataset.gridToggle;
      const enable = btn.dataset.gridEnabled === "1";
      btn.disabled = true;
      try {
        const csrf = getCsrfToken() || await fetchCsrfToken({ force: true });
        const res = await apiFetch(`${API}/trading/grid-bots/${uuid}/toggle`, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
          body: JSON.stringify({ enabled: enable }),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json.ok) { tradingSetMsg(json.msg || "狀態更新失敗", false); return; }
        await loadGridBots();
      } catch (e) { tradingSetMsg(e.message || "網格機器人狀態更新失敗", false); }
      finally { btn.disabled = false; }
    });
  });
  container.querySelectorAll("[data-grid-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("確定刪除網格機器人？這會取消所有掛單並移除機器人。")) return;
      const uuid = btn.dataset.gridDelete;
      btn.disabled = true;
      try {
        const csrf = getCsrfToken() || await fetchCsrfToken({ force: true });
        const res = await apiFetch(`${API}/trading/grid-bots/${uuid}`, {
          method: "DELETE", credentials: "same-origin",
          headers: { "X-CSRF-Token": csrf || "" },
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json.ok) { tradingSetMsg(json.msg || "刪除失敗", false); return; }
        tradingSetMsg("網格機器人已刪除");
        await loadGridBots();
      } catch (e) { tradingSetMsg(e.message || "網格機器人刪除失敗", false); }
      finally { btn.disabled = false; }
    });
  });
}

async function loadGridBots() {
  try {
    const res = await apiFetch(`${API}/trading/grid-bots`, { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) return;
    tradingGridBots = Array.isArray(json.bots) ? json.bots : [];
    const priceMap = {};
    for (const m of (tradingState.markets || [])) {
      priceMap[m.symbol] = m.manual_price_points || 0;
    }
    renderGridBotList(tradingGridBots, priceMap);
  } catch (e) {
    // silent
  }
}

async function createGridBot() {
  const name = $("trading-grid-bot-name")?.value?.trim() || "";
  const marketSymbol = $("trading-grid-bot-market")?.value || "";
  const upper = Number($("trading-grid-upper-price")?.value || 0);
  const lower = Number($("trading-grid-lower-price")?.value || 0);
  const count = Number($("trading-grid-count")?.value || 10);
  const amount = Number($("trading-grid-order-amount")?.value || 0);
  if (!name) { tradingSetMsg("請填寫機器人名稱", false); return; }
  if (!marketSymbol) { tradingSetMsg("請選擇交易市場", false); return; }
  if (!upper || !lower || upper <= lower) { tradingSetMsg("上限價格必須大於下限價格", false); return; }
  if (count < 2) { tradingSetMsg("網格數量至少為 2", false); return; }
  if (amount < 1) { tradingSetMsg("每格金額必須大於 0", false); return; }
  const btn = $("trading-grid-bot-create-btn");
  if (btn) btn.disabled = true;
  tradingSetMsg("正在建立網格機器人並掛單...");
  try {
    const csrf = getCsrfToken() || await fetchCsrfToken({ force: true });
    const res = await apiFetch(`${API}/trading/grid-bots`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify({ name, market_symbol: marketSymbol, upper_price_points: upper, lower_price_points: lower, grid_count: count, order_amount_points: amount }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) { tradingSetMsg(json.msg || "網格建立失敗", false); return; }
    const placed = (json.placed || []).length;
    const errors = json.errors || [];
    let msg = `網格機器人已建立，成功掛單 ${placed} 筆`;
    if (errors.length) msg += `，${errors.length} 個層級失敗`;
    tradingSetMsg(msg, !errors.length);
    if ($("trading-grid-bot-name")) $("trading-grid-bot-name").value = "";
    await loadGridBots();
    await loadTradingDashboard();
  } catch (e) { tradingSetMsg(e.message || "網格機器人建立失敗", false); }
  finally { if (btn) btn.disabled = false; }
}

async function scanGridBots() {
  tradingSetMsg("掃描網格機器人中...");
  const btn = $("trading-grid-scan-btn");
  if (btn) btn.disabled = true;
  try {
    const csrf = getCsrfToken() || await fetchCsrfToken({ force: true });
    const res = await apiFetch(`${API}/trading/grid-bots/scan`, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" },
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) { tradingSetMsg(json.msg || "掃描失敗", false); return; }
    const results = json.results || [];
    const fills = results.reduce((s, r) => s + (r.fills_processed || []).length, 0);
    const placed = results.reduce((s, r) => s + (r.counter_orders_placed || []).length, 0);
    tradingSetMsg(`網格掃描完成：${json.scanned} 個機器人，處理 ${fills} 筆成交，新掛 ${placed} 筆反向單`);
    await loadGridBots();
    await loadTradingDashboard();
  } catch (e) { tradingSetMsg(e.message || "掃描失敗", false); }
  finally { if (btn) btn.disabled = false; }
}

// ── End Grid Trading Bot ────────────────────────────────────────────────────

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
  tradingState.fundingPool = safe.funding_pool || tradingState.fundingPool || null;
  if ($("trading-reserve-balance")) $("trading-reserve-balance").textContent = String(Number(reserve.balance_points || 0));
  if ($("trading-verification-status")) $("trading-verification-status").textContent = verification.ok === false ? "異常" : "正常";
  if ($("trading-verification-detail")) $("trading-verification-detail").textContent = `${Array.isArray(verification.errors) ? verification.errors.length : 0} 個問題`;
  const settings = safe.settings || {};
  if ($("trading-risk-flags")) $("trading-risk-flags").textContent = `borrow=${settings.borrowing_enabled ? "true" : "false"} / liquidation=${settings.margin_liquidation_enabled ? "true" : "false"} / futures=${settings.futures_enabled ? "true" : "false"} / pvp=${settings.pvp_matching_enabled ? "true" : "false"}`;
  if ($("trading-liquidation-status")) {
    $("trading-liquidation-status").textContent = settings.margin_liquidation_enabled
      ? `自動清算排程：啟用，維持保證金 ${formatTradingPercent(settings.margin_maintenance_percent || 0)}%`
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
    `).join("") : `<div class="drive-empty">尚無資金池事件</div>`;
  }
}

function populateTradingRootMarketForm() {
  const symbol = $("trading-root-market-select")?.value || "";
  const market = tradingState.markets.find((row) => row.symbol === symbol) || tradingState.markets[0];
  if (!market) return;
  if ($("trading-root-market-select")) $("trading-root-market-select").value = market.symbol;
  if ($("trading-root-price")) $("trading-root-price").value = Number(market.manual_price_points || 0);
  if ($("trading-root-jump-percent")) $("trading-root-jump-percent").value = formatTradingPercent(market.max_price_jump_percent || 0);
  if ($("trading-root-fee-percent")) $("trading-root-fee-percent").value = formatTradingPercent(market.fee_rate_percent || 0);
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
    await loadTradingWorkflowTemplates();
    const json = await fetchTradingJson("/trading/dashboard");
    const payload = json.trading || {};
    tradingState.funding = payload.funding || null;
    tradingState.fundingPool = payload.funding_pool || null;
    tradingState.marginSummary = payload.margin_summary || null;
    tradingState.markets = payload.markets || [];
    tradingState.settings = payload.settings || {};
    tradingState.positions = payload.positions || [];
    tradingState.marginPositions = payload.margin_positions || [];
    tradingState.orders = payload.orders || [];
    tradingState.fills = payload.fills || [];
    tradingState.bots = payload.bots || [];
    tradingState.botRuns = payload.bot_runs || [];
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
    renderTradingBots(tradingState.bots, tradingState.botRuns);
    loadGridBots().catch(() => {});
    renderTradingContracts(payload.futures_positions || []);
    renderTradingMarginPositions(tradingState.marginPositions);
    renderTradingMarginAccountSummary(tradingState.marginSummary);
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
  if (currentUser !== "root") {
    tradingSetMsg("只有 root 可以讀取交易管理報告", false);
    return;
  }
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
    quantity: tradingQuantityForSubmit(estimate.quantity),
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

async function saveTradingBot() {
  const marketSymbol = $("trading-auto-bot-market")?.value || selectedTradingMarket()?.symbol || "";
  if (!marketSymbol) {
    tradingSetMsg("請先選擇自動化機器人市場", false);
    return;
  }
  let workflow;
  try {
    workflow = parseTradingWorkflowInput();
  } catch (err) {
    tradingSetMsg(err.message || "Workflow JSON 格式錯誤", false);
    return;
  }
  const payload = {
    bot_type: "conditional",
    name: $("trading-auto-bot-name")?.value || "",
    market_symbol: marketSymbol,
    trigger_type: "always",
    trigger_price_points: null,
    side: "buy",
    order_type: "market",
    quantity: "0.00000001",
    limit_price_points: null,
    workflow_json: workflow,
    strategy_mode: $("trading-auto-strategy-mode")?.value || "and",
    max_daily_runs: Number($("trading-auto-daily-runs")?.value || 5),
    max_runs: Number($("trading-auto-bot-max-runs")?.value || 1),
    cooldown_seconds: Number($("trading-auto-bot-cooldown")?.value || 300),
    enabled: !!$("trading-auto-bot-enabled")?.checked,
  };
  try {
    tradingSetMsg("正在新增自動化機器人...");
    await fetchTradingJson("/trading/bots", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    tradingSetMsg("自動化條件機器人已新增");
    if ($("trading-auto-bot-name")) $("trading-auto-bot-name").value = "";
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(`自動化機器人新增失敗：${err.message || "後端未提供錯誤原因"}`, false);
  }
}

async function saveTradingDcaBot() {
  const marketSymbol = $("trading-dca-bot-market")?.value || selectedTradingMarket()?.symbol || "";
  if (!marketSymbol) {
    tradingSetMsg("請先選擇定投市場", false);
    return;
  }
  const preset = $("trading-dca-bot-interval-preset")?.value || "24";
  const intervalHours = preset === "custom" ? Number($("trading-dca-bot-interval-hours")?.value || 24) : Number(preset || 24);
  const payload = {
    bot_type: "dca",
    name: $("trading-dca-bot-name")?.value || "",
    market_symbol: marketSymbol,
    budget_points: Number($("trading-dca-bot-budget-points")?.value || 0),
    interval_hours: intervalHours,
    price_upper_limit: Number($("trading-dca-price-upper")?.value || 0) || null,
    price_lower_limit: Number($("trading-dca-price-lower")?.value || 0) || null,
    max_runs: Number($("trading-dca-bot-max-runs")?.value || 1),
    enabled: !!$("trading-dca-bot-enabled")?.checked,
  };
  try {
    tradingSetMsg("正在新增定投機器人...");
    const json = await fetchTradingJson("/trading/bots", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const initial = json.initial_run || null;
    const failed = Array.isArray(initial?.failed) ? initial.failed : [];
    const triggered = Array.isArray(initial?.triggered) ? initial.triggered : [];
    const skipped = Array.isArray(initial?.skipped) ? initial.skipped : [];
    if (!payload.enabled) {
      tradingSetMsg("定投機器人已新增（目前停用，未立即執行）");
    } else if (failed.length) {
      tradingSetMsg(`定投機器人已新增，但首次執行失敗：${tradingErrorText(failed[0], "後端未提供錯誤原因")}`, false);
    } else if (triggered.length) {
      tradingSetMsg("定投機器人已新增，已立即執行第一筆");
    } else if (skipped.length) {
      tradingSetMsg(`定投機器人已新增，但首次執行被略過：${sanitize(skipped[0].reason || "未符合條件")}`, false);
    } else {
      tradingSetMsg("定投機器人已新增，等待下一次掃描");
    }
    if ($("trading-dca-bot-name")) $("trading-dca-bot-name").value = "";
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(`定投機器人新增失敗：${err.message || "後端未提供錯誤原因"}`, false);
  }
}

const BACKTEST_BATCH_SIZE = 5000;

function downloadBacktestTrades(trades, marketSymbol) {
  if (!trades || !trades.length) return;
  const header = "時間,方向,數量,價格（點）,金額（點）,手續費（點）";
  const rows = trades.map((r) => [
    `"${String(r.time || "").replace(/"/g, '""')}"`,
    r.side === "sell" ? "賣出" : "買入",
    r.quantity || "0",
    r.price_points || 0,
    r.spend_points || 0,
    r.fee_points || 0,
  ].join(","));
  const csv = [header, ...rows].join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `backtest_${(marketSymbol || "trades").replace(/\//g, "-")}_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

async function backtestTradingBot() {
  const result = $("trading-bot-backtest-result");
  const marketSymbol = $("trading-backtest-market")?.value || selectedTradingMarket()?.symbol || "";
  let allCandles = tradingState.referencePrices?.candles || tradingState.referencePrices?.points || [];
  if (!marketSymbol) {
    tradingSetMsg("請先選擇回測市場", false);
    return;
  }
  const botUuid = $("trading-backtest-bot-select")?.value || "";
  const selectedBot = botUuid ? tradingState.bots.find((row) => row.bot_uuid === botUuid) : null;
  const botType = $("trading-backtest-strategy")?.value || (selectedBot ? (selectedBot.bot_type === "dca" ? "dca" : "workflow") : "dca");
  let workflow = null;
  if (botType === "workflow") {
    try {
      const wfRaw = $("trading-backtest-workflow-json")?.value?.trim() || "";
      workflow = wfRaw ? JSON.parse(wfRaw) : (selectedBot?.workflow || parseTradingWorkflowInput());
    } catch (err) {
      tradingSetMsg(err.message || "Workflow JSON 格式錯誤", false);
      return;
    }
  }
  const orderPoints = botType === "workflow"
    ? Number($("trading-backtest-workflow-order-points")?.value || 100)
    : Number($("trading-backtest-order-points")?.value || 100);
  const intervalCandles = botType === "dca"
    ? Math.max(1, Number($("trading-backtest-interval-candles")?.value || 1))
    : Math.max(1, Math.ceil(Number(selectedBot?.interval_hours ? selectedBot.interval_hours / 0.25 : 1)));
  const basePayload = {
    market_symbol: marketSymbol,
    strategy: botType,
    workflow_json: workflow,
    initial_cash_points: Number($("trading-backtest-initial-cash")?.value || 10000),
    order_points: orderPoints,
    interval_candles: intervalCandles,
    timeframe: $("trading-backtest-timeframe")?.value || "15m",
    start_time: $("trading-backtest-start")?.value || "",
    end_time: $("trading-backtest-end")?.value || "",
    slippage_percent: Number($("trading-backtest-slippage-percent")?.value || 0),
  };
  const hasCandleData = Array.isArray(allCandles) && allCandles.length >= 2;
  if (!hasCandleData) {
    basePayload.candle_limit = 500;
    tradingSetMsg("未載入圖表，正在由後端下載歷史 K 線後回測...");
  } else {
    basePayload.data_source = tradingState.referencePrices?.source || "browser_loaded_chart";
    basePayload.provider_symbol = tradingState.referencePrices?.symbol || "";
  }
  try {
    let combinedJson = null;
    let allTrades = [];
    let totalCandles = 0;
    if (hasCandleData && allCandles.length > BACKTEST_BATCH_SIZE) {
      const batches = [];
      for (let i = 0; i < allCandles.length; i += BACKTEST_BATCH_SIZE) {
        batches.push(allCandles.slice(i, i + BACKTEST_BATCH_SIZE));
      }
      tradingSetMsg(`K 線共 ${allCandles.length} 根，自動分 ${batches.length} 批回測中...`);
      let carryUnits = 0, carryCash = basePayload.initial_cash_points, carryAvgCost = 0;
      for (let bi = 0; bi < batches.length; bi++) {
        const batchPayload = { ...basePayload, candles: batches[bi], initial_cash_points: carryCash, initial_units: carryUnits, initial_avg_cost: carryAvgCost };
        if (result) result.textContent = `分批回測中…第 ${bi + 1}/${batches.length} 批`;
        const batchJson = await fetchTradingJson("/trading/bots/backtest", { method: "POST", body: JSON.stringify(batchPayload) });
        allTrades = allTrades.concat(Array.isArray(batchJson.trades) ? batchJson.trades : []);
        totalCandles += Number(batchJson.candle_count || 0);
        carryUnits = batchJson.end_units ?? 0;
        carryCash = batchJson.end_cash_points ?? carryCash;
        carryAvgCost = batchJson.end_avg_cost ?? 0;
        combinedJson = { ...batchJson, candle_count: totalCandles, trades: allTrades, trade_count: allTrades.length };
      }
    } else {
      if (hasCandleData) basePayload.candles = allCandles;
      combinedJson = await fetchTradingJson("/trading/bots/backtest", { method: "POST", body: JSON.stringify(basePayload) });
      allTrades = Array.isArray(combinedJson.trades) ? combinedJson.trades : [];
    }
    const sourceText = combinedJson.data_source ? `，資料 ${sanitize(combinedJson.data_source)} ${Number(combinedJson.candle_count || 0)} 根` : "";
    const batchNote = hasCandleData && allCandles.length > BACKTEST_BATCH_SIZE ? `（分 ${Math.ceil(allCandles.length / BACKTEST_BATCH_SIZE)} 批）` : "";
    const text = `回測完成${batchNote}：交易 ${Number(combinedJson.trade_count || 0)} 次，期末 ${formatTradingPointsValue(combinedJson.final_value_points)} 點，損益 ${Number(combinedJson.pnl_points || 0) >= 0 ? "+" : ""}${formatTradingPointsValue(combinedJson.pnl_points)} 點，報酬 ${formatTradingPointsValue(combinedJson.return_percent)}%${sourceText}`;
    if (result) result.textContent = text;
    renderTradingBacktestResult(combinedJson);
    tradingSetMsg(text, Number(combinedJson.pnl_points || 0) >= 0);
  } catch (err) {
    const text = err.message || "回測失敗";
    if (result) result.textContent = text;
    tradingSetMsg(text, false);
  }
}

function renderTradingBacktestResult(json) {
  const metrics = $("trading-backtest-metrics");
  const trades = $("trading-backtest-trades");
  const warnings = $("trading-backtest-warnings");
  if (warnings) {
    const rangeWarns = Array.isArray(json.range_warnings) ? json.range_warnings : [];
    warnings.innerHTML = rangeWarns.length
      ? rangeWarns.map((w) => `<div class="trading-backtest-warning">⚠ ${sanitize(w)}</div>`).join("")
      : "";
    warnings.style.display = rangeWarns.length ? "" : "none";
  }
  if (metrics) {
    metrics.innerHTML = `
      <div><span class="drive-card-sub">初始資金</span><strong>${formatTradingPointsValue(json.initial_cash_points)}</strong><small>POINTS</small></div>
      <div><span class="drive-card-sub">最終資金</span><strong>${formatTradingPointsValue(json.final_value_points)}</strong><small>POINTS</small></div>
      <div><span class="drive-card-sub">總損益</span><strong>${Number(json.pnl_points || 0) >= 0 ? "+" : ""}${formatTradingPointsValue(json.pnl_points)}</strong><small>${formatTradingPointsValue(json.return_percent)}%</small></div>
      <div><span class="drive-card-sub">交易次數</span><strong>${Number(json.trade_count || 0)}</strong><small>回測未修改帳本</small></div>
      <div><span class="drive-card-sub">資料來源</span><strong>${sanitize(json.data_source || "-")}</strong><small>${Number(json.candle_count || 0)} 根 K 線</small></div>
      <div><span class="drive-card-sub">資料範圍</span><strong>${sanitize(String(json.first_candle_time || "-"))}</strong><small>～ ${sanitize(String(json.last_candle_time || "-"))}</small></div>
      <div><span class="drive-card-sub">回測上限</span><strong>${Number(json.max_backtest_candles || 0).toLocaleString()} 根</strong><small>已使用 ${Number(json.candle_count || 0).toLocaleString()} 根</small></div>
    `;
  }
  if (trades) {
    const rows = Array.isArray(json.trades) ? json.trades : [];
    const dlBtn = rows.length ? `<button class="btn btn-sm" type="button" id="trading-backtest-download-btn" style="margin-bottom:.5rem;">下載成交記錄 CSV（${rows.length} 筆）</button>` : "";
    trades.innerHTML = dlBtn + (rows.length ? rows.map((row) => `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.time || "-")}</strong>
          <div class="drive-card-sub">${sanitize(row.side === "sell" ? "賣出" : "買入")} ${sanitize(row.quantity || "0")} · 價格 ${formatTradingPointsValue(row.price_points)} · 金額 ${formatTradingPointsValue(row.spend_points)} · 手續費 ${formatTradingPointsValue(row.fee_points)}</div>
        </div>
      </div>
    `).join("") : `<div class="drive-empty">回測期間沒有交易</div>`);
    if (rows.length) {
      const dlBtnEl = $("trading-backtest-download-btn");
      if (dlBtnEl) dlBtnEl.addEventListener("click", () => downloadBacktestTrades(rows, json.market_symbol));
    }
  }
}

function updateBacktestStrategyUI() {
  const strategy = $("trading-backtest-strategy")?.value || "dca";
  const dcaOpts = $("trading-backtest-dca-options");
  const wfOpts = $("trading-backtest-workflow-options");
  if (dcaOpts) dcaOpts.style.display = strategy === "dca" ? "" : "none";
  if (wfOpts) wfOpts.style.display = strategy === "workflow" ? "" : "none";
  const botUuid = $("trading-backtest-bot-select")?.value || "";
  if (botUuid) {
    const bot = tradingState.bots.find((row) => row.bot_uuid === botUuid);
    if (bot) {
      const isWf = bot.bot_type !== "dca";
      if ($("trading-backtest-strategy")) $("trading-backtest-strategy").value = isWf ? "workflow" : "dca";
      if (dcaOpts) dcaOpts.style.display = isWf ? "none" : "";
      if (wfOpts) wfOpts.style.display = isWf ? "" : "none";
      if (!isWf) {
        if ($("trading-backtest-order-points")) $("trading-backtest-order-points").value = bot.budget_points || 100;
        if ($("trading-backtest-interval-candles")) {
          const intervalCandles = Math.max(1, Math.ceil(Number(bot.interval_hours ? bot.interval_hours / 0.25 : 1)));
          $("trading-backtest-interval-candles").value = intervalCandles;
        }
      } else {
        if ($("trading-backtest-workflow-order-points")) $("trading-backtest-workflow-order-points").value = bot.budget_points || 100;
        if (bot.workflow && $("trading-backtest-workflow-json")) $("trading-backtest-workflow-json").value = JSON.stringify(bot.workflow, null, 2);
      }
    }
  }
  populateBacktestWorkflowTemplates();
}

function populateBacktestWorkflowTemplates() {
  const sel = $("trading-backtest-workflow-template");
  if (!sel) return;
  const templates = Array.isArray(tradingState.workflowTemplates) ? tradingState.workflowTemplates : [];
  const prev = sel.value;
  sel.innerHTML = `<option value="">自訂（JSON 編輯器）</option>` +
    templates.map((t) => `<option value="${sanitize(String(t.id || ""))}">${sanitize(t.label || t.id || "")}</option>`).join("");
  if (prev && Array.from(sel.options).some((o) => o.value === prev)) sel.value = prev;
  sel.removeEventListener("change", sel._backtestTemplateHandler);
  sel._backtestTemplateHandler = () => {
    const tid = sel.value;
    if (!tid) return;
    const tmpl = templates.find((t) => String(t.id) === tid);
    if (tmpl && tmpl.workflow && $("trading-backtest-workflow-json")) {
      $("trading-backtest-workflow-json").value = JSON.stringify(tmpl.workflow, null, 2);
    }
  };
  sel.addEventListener("change", sel._backtestTemplateHandler);
}

function prepareTradingBacktestFromBot(botUuid) {
  const bot = tradingState.bots.find((row) => row.bot_uuid === botUuid);
  if (!bot) {
    tradingSetMsg("找不到要回測的交易機器人", false);
    return;
  }
  switchTradingBotTab("backtest");
  if ($("trading-backtest-bot-select")) $("trading-backtest-bot-select").value = botUuid;
  if ($("trading-backtest-market")) $("trading-backtest-market").value = bot.market_symbol || "";
  updateBacktestStrategyUI();
  tradingSetMsg("已帶入機器人回測設定，請確認時間範圍後執行回測");
}

async function deleteTradingBot(botUuid) {
  if (!botUuid) {
    tradingSetMsg("找不到要刪除的交易機器人", false);
    return;
  }
  if (!confirm("確定刪除這個交易機器人？")) {
    tradingSetMsg("已取消刪除交易機器人");
    return;
  }
  try {
    tradingSetMsg("正在刪除交易機器人...");
    await fetchTradingJson(`/trading/bots/${encodeURIComponent(botUuid)}`, {
      method: "DELETE",
      body: JSON.stringify({}),
    });
    tradingSetMsg("交易機器人已刪除");
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "交易機器人刪除失敗", false);
  }
}

async function toggleTradingBot(botUuid, enabled) {
  const bot = tradingState.bots.find((row) => row.bot_uuid === botUuid);
  if (!bot) {
    tradingSetMsg("找不到要更新的交易機器人", false);
    return;
  }
  const payload = {
    bot_type: bot.bot_type || "conditional",
    name: bot.name || "",
    market_symbol: bot.market_symbol,
    side: bot.side || "buy",
    order_type: bot.order_type || "market",
    quantity: bot.quantity_text || "0.00000001",
    limit_price_points: bot.limit_price_points || null,
    trigger_type: bot.trigger_type || "always",
    trigger_price_points: bot.trigger_price_points || null,
    budget_points: Number(bot.budget_points || 0),
    interval_hours: Number(bot.interval_hours || 24),
    max_runs: Number(bot.max_runs || 1),
    cooldown_seconds: Number(bot.cooldown_seconds || 0),
    workflow_json: bot.workflow || null,
    enabled,
  };
  try {
    tradingSetMsg(enabled ? "正在啟用機器人..." : "正在暫停機器人...");
    const json = await fetchTradingJson(`/trading/bots/${encodeURIComponent(botUuid)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    if (!enabled) {
      tradingSetMsg("機器人已暫停");
    } else if (bot.bot_type === "dca") {
      const initial = json.initial_run || null;
      const failed   = Array.isArray(initial?.failed)   ? initial.failed   : [];
      const triggered = Array.isArray(initial?.triggered) ? initial.triggered : [];
      const skipped  = Array.isArray(initial?.skipped)  ? initial.skipped  : [];
      if (failed.length) {
        tradingSetMsg(`機器人已啟用，但首次執行失敗：${tradingErrorText(failed[0], "後端未提供錯誤原因")}`, false);
      } else if (triggered.length) {
        tradingSetMsg("機器人已啟用，已立即執行第一筆定投");
      } else if (skipped.length && skipped[0]?.reason === "cooldown") {
        tradingSetMsg("機器人已啟用，定投冷卻中，將依排程執行下一筆");
      } else {
        tradingSetMsg("機器人已啟用");
      }
    } else {
      tradingSetMsg("機器人已啟用");
    }
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "機器人狀態更新失敗", false);
  }
}

async function scanTradingBots() {
  try {
    tradingSetMsg("正在掃描已啟用交易機器人...");
    const json = await fetchTradingJson("/trading/bots/scan", {
      method: "POST",
      body: JSON.stringify({ limit: 50 }),
    });
    const triggered = Array.isArray(json.triggered) ? json.triggered.length : 0;
    const failed = Array.isArray(json.failed) ? json.failed.length : 0;
    tradingSetMsg(`機器人掃描完成：掃描 ${Number(json.scanned || 0)} 個，觸發 ${triggered} 個，失敗 ${failed} 個`, failed === 0);
    await loadTradingDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "交易機器人掃描失敗", false);
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
  if (!positionUuid) {
    tradingSetMsg("找不到要平倉的合約倉位", false);
    return;
  }
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
        idempotency_key: tradingRequestId("margin-open"),
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
  if (!positionUuid) {
    tradingSetMsg("找不到要平倉的進階交易倉位", false);
    return;
  }
  if (!confirm("確定平掉這筆進階交易倉位？")) {
    tradingSetMsg("已取消進階交易平倉");
    return;
  }
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
  if (!positionUuid) {
    tradingSetMsg("找不到要補保證金的進階交易倉位", false);
    return;
  }
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
    const idempotencyKey = `margin-collateral:${positionUuid}:${amount}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    const json = await fetchTradingJson(`/trading/margin/${encodeURIComponent(positionUuid)}/collateral`, {
      method: "POST",
      body: JSON.stringify({ amount_points: amount, idempotency_key: idempotencyKey }),
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
  if (!orderUuid) {
    tradingSetMsg("找不到要取消的訂單", false);
    return;
  }
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
        max_price_jump_percent: tradingInputPercent($("trading-root-jump-percent")?.value || 0),
        fee_rate_percent: tradingInputPercent($("trading-root-fee-percent")?.value || 0),
        min_order_points: Number($("trading-root-min-order")?.value || 0),
        max_order_points: Number($("trading-root-max-order")?.value || 0),
        enabled: !!$("trading-root-enabled")?.checked,
      }),
    });
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
  if (!confirm("確認要從指定帳戶扣點並撥入交易資金池？")) return;
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
    tradingSetMsg("已撥入交易資金池");
    await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(err.message || "資金池撥入失敗", false);
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
  if (currentUser !== "root") {
    tradingSetMsg("只有 root 可以手動掃描強平條件", false);
    return;
  }
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
  if (currentUser !== "root") {
    tradingSetMsg("只有 root 可以手動掃描限價單撮合", false);
    return;
  }
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
    ["trading-refresh-btn", loadTradingDashboard, "正在重新整理交易資料...", "交易資料重新整理失敗"],
    ["trading-submit-order-btn", submitTradingOrder, "正在送出訂單...", "下單失敗"],
    ["trading-auto-bot-save-btn", saveTradingBot, "正在新增自動化機器人...", "自動化機器人新增失敗"],
    ["trading-dca-bot-save-btn", saveTradingDcaBot, "正在新增定投機器人...", "定投機器人新增失敗"],
    ["trading-bot-scan-btn", scanTradingBots, "正在掃描已啟用交易機器人...", "交易機器人掃描失敗"],
    ["trading-backtest-run-btn", backtestTradingBot, "正在執行回測...", "回測失敗"],
    ["trading-workflow-load-btn", loadTradingWorkflowFromEditor, "正在載入 Workflow 編輯器結果...", "Workflow 載入失敗"],
    ["trading-workflow-template-apply-btn", applyTradingWorkflowTemplate, "正在套用 Workflow 基礎模板...", "Workflow 模板套用失敗"],
    ["trading-workflow-custom-save-btn", saveTradingWorkflowCustomTemplate, "正在儲存 Workflow 自訂模板...", "Workflow 自訂模板儲存失敗"],
    ["trading-root-refresh-btn", loadTradingRootReport, "正在讀取 root 交易報告...", "交易報告讀取失敗"],
    ["trading-root-save-market-btn", saveTradingRootMarket, "正在儲存交易市場設定...", "市場設定儲存失敗"],
    ["trading-reserve-allocate-btn", allocateTradingReserve, "正在撥入交易資金池...", "資金池撥入失敗"],
    ["trading-root-reset-sim-btn", resetRootTradingSimulatedBalance, "準備重置 root 模擬交易...", "root 模擬資金重設失敗"],
    ["trading-contract-open-btn", openRootTradingContract, "正在建立 root 合約模擬倉位...", "合約開倉失敗"],
    ["trading-margin-open-btn", openTradingMarginPosition, "正在建立進階交易倉位...", "進階交易開倉失敗"],
    ["trading-limit-match-btn", matchTradingLimitOrders, "正在掃描限價單撮合...", "限價單撮合失敗"],
    ["trading-liquidation-scan-btn", scanTradingLiquidations, "正在掃描強平條件...", "強平掃描失敗"],
    ["economy-trading-open-btn", openTradingModuleFromWallet, "正在切換到交易所...", "交易所切換失敗"],
    ["economy-root-virtual-open-btn", openTradingModuleFromWallet, "正在切換到交易所...", "交易所切換失敗"],
  ];
  bindings.forEach(([id, handler, pendingText, fallbackText]) => {
    const el = $(id);
    if (!el) return;
    bindTradingActionButton(el, handler, pendingText, fallbackText);
  });
  const workflowTemplateSelect = $("trading-workflow-template-select");
  if (workflowTemplateSelect) workflowTemplateSelect.addEventListener("change", renderTradingWorkflowTemplateExplanation);
  const backtestStrategy = $("trading-backtest-strategy");
  if (backtestStrategy) backtestStrategy.addEventListener("change", updateBacktestStrategyUI);
  const backtestBotSelect = $("trading-backtest-bot-select");
  if (backtestBotSelect) backtestBotSelect.addEventListener("change", updateBacktestStrategyUI);
  updateBacktestStrategyUI();
  // Grid bot wiring
  const gridCreateBtn = $("trading-grid-bot-create-btn");
  if (gridCreateBtn) bindTradingActionButton(gridCreateBtn, createGridBot, "正在建立網格機器人...", "網格機器人建立失敗");
  const gridScanBtn = $("trading-grid-scan-btn");
  if (gridScanBtn) bindTradingActionButton(gridScanBtn, scanGridBots, "掃描網格機器人中...", "網格掃描失敗");
  ["trading-grid-upper-price", "trading-grid-lower-price", "trading-grid-count", "trading-grid-order-amount"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("input", renderGridBotPreview);
  });
  document.querySelectorAll("[data-trading-bot-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchTradingBotTab(btn.dataset.tradingBotTab || "dca");
      tradingSetMsg(`已切換到${btn.textContent?.trim() || "交易機器人"}分頁`);
    });
  });
  const dcaPreset = $("trading-dca-bot-interval-preset");
  if (dcaPreset) {
    dcaPreset.addEventListener("change", () => {
      const target = $("trading-dca-bot-interval-hours");
      if (!target) return;
      target.disabled = dcaPreset.value !== "custom";
      if (dcaPreset.value !== "custom") target.value = dcaPreset.value;
      tradingSetMsg(dcaPreset.value === "custom" ? "已切換為自訂定投間隔" : `已選擇每 ${dcaPreset.value} 小時定投`);
    });
  }
  const backtestBotSelectEl = $("trading-backtest-bot-select");
  if (backtestBotSelectEl) {
    backtestBotSelectEl.addEventListener("change", () => {
      if (backtestBotSelectEl.value) prepareTradingBacktestFromBot(backtestBotSelectEl.value);
      else tradingSetMsg("已切換為使用目前表單設定回測");
    });
  }
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
  ["trading-side", "trading-order-type", "trading-input-mode", "trading-quantity", "trading-limit-price"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("input", () => {
      syncTradingOrderSideTheme();
      syncTradingOrderInputMode();
      updateTradingOrderEstimate();
    });
    el.addEventListener("change", () => {
      syncTradingOrderSideTheme();
      syncTradingOrderInputMode();
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
  if (!tradingTrialCountdownTimer) {
    tradingTrialCountdownTimer = setInterval(updateTradingTrialCountdown, 1000);
  }
  if (!tradingBtcSignalCountdownTimer) {
    tradingBtcSignalCountdownTimer = setInterval(updateTradingBtcSignalMeta, 1000);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindTradingEvents);
} else {
  bindTradingEvents();
}
