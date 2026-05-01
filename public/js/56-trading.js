'use strict';

let tradingState = {
  markets: [],
  positions: [],
  orders: [],
  fills: [],
  rootReport: null,
};
let tradingEventsBound = false;

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

function renderTradingMarketOptions() {
  const select = $("trading-market-select");
  const rootSelect = $("trading-root-market-select");
  const options = tradingState.markets.length
    ? tradingState.markets.map((market) => `<option value="${sanitize(market.symbol)}">${sanitize(market.symbol)} · ${Number(market.manual_price_points || 0)} 點</option>`).join("")
    : `<option value="">沒有可用市場</option>`;
  [select, rootSelect].forEach((target) => {
    if (!target) return;
    const previous = target.value;
    target.innerHTML = options;
    if (previous && Array.from(target.options).some((option) => option.value === previous)) target.value = previous;
  });
}

function renderTradingSummary() {
  const market = selectedTradingMarket();
  if ($("trading-current-price")) $("trading-current-price").textContent = market ? String(Number(market.manual_price_points || 0)) : "-";
  if ($("trading-current-market")) $("trading-current-market").textContent = market ? `${market.symbol} · ${market.price_source || "manual_root"}` : "-";
  if ($("trading-fee-bps")) $("trading-fee-bps").textContent = market ? String(Number(market.fee_bps || 0)) : "-";
  const position = market ? tradingState.positions.find((row) => row.market_symbol === market.symbol) : null;
  if ($("trading-position-quantity")) $("trading-position-quantity").textContent = position ? sanitize(position.quantity || "0") : "0";
  if ($("trading-position-locked")) $("trading-position-locked").textContent = `鎖定 ${position ? sanitize(position.locked_quantity || "0") : "0"}`;
  const limit = $("trading-limit-price");
  if (limit && market && !$("trading-root-price")?.matches(":focus")) {
    limit.placeholder = `目前 ${Number(market.manual_price_points || 0)}`;
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
          <div class="drive-card-sub">${sanitize(row.market_symbol)} · 數量 ${sanitize(row.quantity)} · 價格 ${sanitize(price || "-")} · 凍結 ${Number(row.frozen_points || 0)}</div>
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
        <strong>${sanitize(row.side)} · ${sanitize(row.market_symbol)} · ${sanitize(row.quantity)}</strong>
        <div class="drive-card-sub">價格 ${Number(row.price_points || 0)} · 成交 ${Number(row.notional_points || 0)} 點 · 手續費 ${Number(row.fee_points || 0)}</div>
        <div class="drive-card-sub">${sanitize(row.created_at || "")}</div>
      </div>
    </div>
  `).join("");
}

function renderTradingWalletSummary(payload = {}) {
  const positions = Array.isArray(payload.positions) ? payload.positions : [];
  const futuresPositions = Array.isArray(payload.futures_positions) ? payload.futures_positions : [];
  const orders = Array.isArray(payload.orders) ? payload.orders : [];
  const fills = Array.isArray(payload.fills) ? payload.fills : [];
  const state = payload.state || {};
  const status = $("economy-trading-safe-mode");
  if (status) {
    status.textContent = state.safe_mode ? `交易 safe mode：${state.reason || "已啟用"}` : "交易引擎正常";
    status.style.color = state.safe_mode ? "#ffb74d" : "var(--muted)";
  }
  const activePositions = positions.filter((row) => Number(row.quantity || 0) !== 0 || Number(row.locked_quantity || 0) !== 0);
  const totalSpotQuantity = activePositions.reduce((total, row) => total + Number(row.quantity || 0), 0);
  if ($("economy-spot-position-quantity")) $("economy-spot-position-quantity").textContent = String(Number.isFinite(totalSpotQuantity) ? totalSpotQuantity : 0);
  if ($("economy-spot-position-summary")) {
    $("economy-spot-position-summary").textContent = activePositions.length
      ? activePositions.slice(0, 2).map((row) => `${row.market_symbol}: ${row.quantity || "0"}`).join(" / ")
      : "尚無現貨";
  }
  const activeFuturesPositions = futuresPositions.filter((row) => row.status === "open" && Number(row.quantity || 0) !== 0);
  if ($("economy-contract-position-count")) $("economy-contract-position-count").textContent = String(activeFuturesPositions.length);
  if ($("economy-contract-position-summary")) {
    $("economy-contract-position-summary").textContent = activeFuturesPositions.length
      ? activeFuturesPositions.slice(0, 2).map((row) => `${row.market_symbol}: ${row.side} ${row.quantity || "0"}`).join(" / ")
      : "未開放";
  }
  if ($("economy-trading-fill-count")) $("economy-trading-fill-count").textContent = String(fills.length);
  if ($("economy-trading-order-count")) $("economy-trading-order-count").textContent = `訂單 ${orders.length}`;
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
  if ($("trading-risk-flags")) $("trading-risk-flags").textContent = "futures=false / pvp=false";
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
  const rootCard = $("trading-root-card");
  if (card && !tradingEnabled) {
    card.style.display = "none";
  }
  if (summaryCard) summaryCard.style.display = tradingEnabled ? "" : "none";
  if (rootCard) rootCard.style.display = tradingEnabled && currentUser === "root" ? "" : "none";
  if (!tradingEnabled) return;
  if (card) card.style.display = "";
  try {
    const json = await fetchTradingJson("/trading/dashboard");
    const payload = json.trading || {};
    tradingState.markets = payload.markets || [];
    tradingState.positions = payload.positions || [];
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
    renderTradingWalletSummary(payload);
    if (currentUser === "root") await loadTradingRootReport();
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
    ["economy-trading-open-btn", openTradingModuleFromWallet],
  ];
  bindings.forEach(([id, handler]) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("click", handler);
  });
  const marketSelect = $("trading-market-select");
  if (marketSelect) marketSelect.addEventListener("change", renderTradingSummary);
  const rootMarketSelect = $("trading-root-market-select");
  if (rootMarketSelect) rootMarketSelect.addEventListener("change", populateTradingRootMarketForm);
  setInterval(syncTradingReserveUserOptions, 1500);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindTradingEvents);
} else {
  bindTradingEvents();
}
