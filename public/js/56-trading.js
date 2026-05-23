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
  state: null,
  referencePrices: null,
  btcSignal: null,
  workflowTemplates: [],
  botCompetition: null,
  wallets: [],
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
let tradingMutationRefreshTimer = null;
let tradingMutationRefreshBusy = false;
let tradingLivePriceTimer = null;
let tradingLivePriceBusy = false;
let tradingLivePriceAbort = null;
let tradingReserveUserSyncTimer = null;
let tradingTrialCountdownTimer = null;
let tradingBtcSignalCountdownTimer = null;
let tradingBotCountdownTimer = null;
let tradingCurrentBotTab = "mybots";
let tradingBotChartOverlay = null;
let tradingActiveActionButton = null;
const tradingGridExpandedBots = new Set();
const TRADING_WORKFLOW_STORAGE_KEY = "hackme_trading_workflow_json";
const TRADING_PERSONAL_FORM_STORAGE_KEY = "hackme_trading_personal_form_v1";
let tradingAccountScope = "";

function tradingRefreshMs(key, fallbackSeconds, minSeconds = 1, maxSeconds = 300) {
  const seconds = Number(siteConfig?.[key] || fallbackSeconds);
  return Math.max(minSeconds, Math.min(maxSeconds, Number.isFinite(seconds) ? seconds : fallbackSeconds)) * 1000;
}

function tradingDashboardRefreshMs() {
  return tradingRefreshMs("trading_dashboard_refresh_seconds", 5, 2, 300);
}

function tradingLivePriceRefreshMs() {
  return tradingRefreshMs("trading_live_price_refresh_seconds", 2, 1, 60);
}

function tradingReferencePriceRefreshMs() {
  return tradingRefreshMs("trading_reference_price_refresh_seconds", 1, 1, 60);
}

function tradingReferenceChartRefreshMs() {
  return tradingRefreshMs("trading_reference_chart_refresh_seconds", 5, 2, 300);
}

function shouldRunTradingPolling(tab = currentModuleTab) {
  if (!currentUser || document.hidden) return false;
  if (tab === currentModuleTab && currentModuleTab !== "trading" && currentModuleTab !== "economy") return false;
  return tab === "trading" || tab === "economy";
}

function shouldRunTradingFullPolling(tab = currentModuleTab) {
  return Boolean(shouldRunTradingPolling(tab) && tab === "trading");
}

function stopTradingModuleTimers() {
  if (tradingReferenceAutoTimer) clearInterval(tradingReferenceAutoTimer);
  if (tradingReferenceChartAutoTimer) clearInterval(tradingReferenceChartAutoTimer);
  if (tradingDashboardAutoTimer) clearInterval(tradingDashboardAutoTimer);
  if (tradingMutationRefreshTimer) clearTimeout(tradingMutationRefreshTimer);
  if (tradingLivePriceTimer) clearInterval(tradingLivePriceTimer);
  if (tradingReserveUserSyncTimer) clearInterval(tradingReserveUserSyncTimer);
  if (tradingTrialCountdownTimer) clearInterval(tradingTrialCountdownTimer);
  if (tradingBtcSignalCountdownTimer) clearInterval(tradingBtcSignalCountdownTimer);
  if (tradingLivePriceAbort) tradingLivePriceAbort.abort();
  tradingReferenceAutoTimer = null;
  tradingReferenceChartAutoTimer = null;
  tradingDashboardAutoTimer = null;
  tradingMutationRefreshTimer = null;
  tradingLivePriceTimer = null;
  tradingReserveUserSyncTimer = null;
  tradingTrialCountdownTimer = null;
  tradingBtcSignalCountdownTimer = null;
  tradingLivePriceAbort = null;
}

function stopTradingFullModuleTimers() {
  if (tradingReferenceAutoTimer) clearInterval(tradingReferenceAutoTimer);
  if (tradingReferenceChartAutoTimer) clearInterval(tradingReferenceChartAutoTimer);
  if (tradingDashboardAutoTimer) clearInterval(tradingDashboardAutoTimer);
  if (tradingReserveUserSyncTimer) clearInterval(tradingReserveUserSyncTimer);
  if (tradingTrialCountdownTimer) clearInterval(tradingTrialCountdownTimer);
  if (tradingBtcSignalCountdownTimer) clearInterval(tradingBtcSignalCountdownTimer);
  tradingReferenceAutoTimer = null;
  tradingReferenceChartAutoTimer = null;
  tradingDashboardAutoTimer = null;
  tradingReserveUserSyncTimer = null;
  tradingTrialCountdownTimer = null;
  tradingBtcSignalCountdownTimer = null;
}

function startTradingModuleTimers() {
  if (!shouldRunTradingPolling()) {
    stopTradingModuleTimers();
    return;
  }
  if (shouldRunTradingFullPolling()) {
    if (!tradingReserveUserSyncTimer) {
      tradingReserveUserSyncTimer = setInterval(syncTradingReserveUserOptions, 1500);
    }
    restartTradingReferenceAutoRefresh();
    if (!tradingDashboardAutoTimer) {
      tradingDashboardAutoTimer = setInterval(async () => {
        if (!shouldRunTradingFullPolling() || tradingDashboardAutoBusy) return;
        tradingDashboardAutoBusy = true;
        try {
          await loadTradingDashboard();
        } finally {
          tradingDashboardAutoBusy = false;
        }
      }, tradingDashboardRefreshMs());
    }
    if (!tradingTrialCountdownTimer) {
      tradingTrialCountdownTimer = setInterval(updateTradingTrialCountdown, 1000);
    }
    if (!tradingBtcSignalCountdownTimer) {
      tradingBtcSignalCountdownTimer = setInterval(updateTradingBtcSignalMeta, 1000);
    }
  } else {
    stopTradingFullModuleTimers();
  }
  if (!tradingLivePriceTimer) {
    tradingLivePriceTimer = setInterval(async () => {
      if (!shouldRunTradingPolling() || tradingLivePriceBusy) return;
      tradingLivePriceBusy = true;
      try {
        await loadTradingLivePrice();
      } finally {
        tradingLivePriceBusy = false;
      }
    }, tradingLivePriceRefreshMs());
  }
}

function syncTradingModuleTimerLifecycle() {
  if (shouldRunTradingPolling()) startTradingModuleTimers();
  else stopTradingModuleTimers();
}

const TRADING_PERSONAL_FORM_FIELDS = [
  { id: "trading-market-select", value: "" },
  { id: "trading-side", value: "buy" },
  { id: "trading-order-type", value: "market" },
  { id: "trading-input-mode", value: "quantity" },
  { id: "trading-quantity", value: "0.01" },
  { id: "trading-limit-price", value: "" },
  { id: "trading-stop-loss-percent", value: "" },
  { id: "trading-take-profit-percent", value: "" },
  { id: "trading-margin-type", value: "margin_long" },
  { id: "trading-margin-market-select", value: "" },
  { id: "trading-margin-quantity", value: "0.01" },
  { id: "trading-margin-collateral", value: "100" },
  { id: "trading-margin-stop-loss-percent", value: "" },
  { id: "trading-margin-take-profit-percent", value: "" },
  { id: "trading-dca-bot-name", value: "" },
  { id: "trading-dca-bot-market", value: "" },
  { id: "trading-dca-bot-budget-points", value: "100" },
  { id: "trading-dca-bot-interval-preset", value: "24" },
  { id: "trading-dca-bot-interval-hours", value: "24" },
  { id: "trading-dca-price-upper", value: "" },
  { id: "trading-dca-price-lower", value: "" },
  { id: "trading-dca-stop-loss-percent", value: "" },
  { id: "trading-dca-take-profit-percent", value: "" },
  { id: "trading-dca-share-parameters", checked: false },
  { id: "trading-dca-bot-max-runs", value: "7" },
  { id: "trading-dca-bot-enabled", checked: true },
  { id: "trading-grid-bot-name", value: "" },
  { id: "trading-grid-bot-market", value: "" },
  { id: "trading-grid-preset", value: "" },
  { id: "trading-grid-upper-price", value: "" },
  { id: "trading-grid-lower-price", value: "" },
  { id: "trading-grid-count", value: "10" },
  { id: "trading-grid-order-amount", value: "100" },
  { id: "trading-grid-stop-loss-percent", value: "" },
  { id: "trading-grid-take-profit-percent", value: "" },
  { id: "trading-grid-spacing-mode", value: "arithmetic" },
  { id: "trading-grid-share-parameters", checked: false },
  { id: "trading-auto-bot-name", value: "" },
  { id: "trading-auto-bot-market", value: "" },
  { id: "trading-auto-bot-budget-points", value: "100" },
  { id: "trading-auto-strategy-mode", value: "single" },
  { id: "trading-auto-daily-runs", value: "5" },
  { id: "trading-auto-bot-max-runs", value: "5" },
  { id: "trading-auto-bot-cooldown", value: "300" },
  { id: "trading-auto-share-parameters", checked: false },
  { id: "trading-auto-bot-enabled", checked: true },
  { id: "trading-workflow-custom-name", value: "" },
  { id: "trading-dca-backtest-timeframe", value: "15m" },
  { id: "trading-dca-backtest-market", value: "" },
  { id: "trading-dca-backtest-start", value: "" },
  { id: "trading-dca-backtest-end", value: "" },
  { id: "trading-dca-backtest-initial-cash", value: "10000" },
  { id: "trading-dca-backtest-slippage-percent", value: "0" },
  { id: "trading-dca-backtest-order-points", value: "100" },
  { id: "trading-dca-backtest-interval-candles", value: "1" },
  { id: "trading-dca-backtest-stop-loss-percent", value: "" },
  { id: "trading-dca-backtest-take-profit-percent", value: "" },
  { id: "trading-grid-backtest-timeframe", value: "15m" },
  { id: "trading-grid-backtest-market", value: "" },
  { id: "trading-grid-backtest-start", value: "" },
  { id: "trading-grid-backtest-end", value: "" },
  { id: "trading-grid-backtest-initial-cash", value: "10000" },
  { id: "trading-grid-backtest-slippage-percent", value: "0" },
  { id: "trading-grid-backtest-grid-lower", value: "" },
  { id: "trading-grid-backtest-grid-upper", value: "" },
  { id: "trading-grid-backtest-grid-count", value: "10" },
  { id: "trading-grid-backtest-grid-amount", value: "100" },
  { id: "trading-grid-backtest-stop-loss-percent", value: "" },
  { id: "trading-grid-backtest-take-profit-percent", value: "" },
  { id: "trading-grid-backtest-grid-spacing", value: "arithmetic" },
  { id: "trading-workflow-backtest-timeframe", value: "15m" },
  { id: "trading-workflow-backtest-market", value: "" },
  { id: "trading-workflow-backtest-start", value: "" },
  { id: "trading-workflow-backtest-end", value: "" },
  { id: "trading-workflow-backtest-initial-cash", value: "10000" },
  { id: "trading-workflow-backtest-slippage-percent", value: "0" },
  { id: "trading-workflow-backtest-order-points", value: "100" },
];

function tradingUserStorageScope() {
  if (typeof getCurrentAccountStorageScope === "function") return getCurrentAccountStorageScope();
  const id = Number(currentUserId || 0);
  if (Number.isFinite(id) && id > 0) return `user:${id}`;
  const name = String(currentUser || "").trim().toLowerCase();
  return name ? `name:${name}` : "anonymous";
}

function tradingUserStorageKey(key) {
  if (typeof accountScopedStorageKey === "function") return accountScopedStorageKey(key, tradingUserStorageScope());
  return `hackme_web:${tradingUserStorageScope()}:${String(key || "state")}`;
}

function tradingDefaultSpendWalletAddress() {
  const tradingSelect = $("trading-payment-wallet");
  if (tradingSelect && String(tradingSelect.value || "").trim()) {
    return String(tradingSelect.value || "").trim().toLowerCase();
  }
  if (typeof readEconomyDefaultSpendWalletAddress === "function") {
    return String(readEconomyDefaultSpendWalletAddress() || "").trim().toLowerCase();
  }
  return "";
}

function tradingSourceWalletQuery() {
  const address = tradingDefaultSpendWalletAddress();
  return address ? `?source_wallet_address=${encodeURIComponent(address)}` : "";
}

function tradingShortWalletAddress(address) {
  const value = String(address || "");
  if (typeof shortEconomyWalletAddress === "function") return shortEconomyWalletAddress(value);
  return value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function tradingWalletOptionLabel(wallet) {
  if (typeof economyWalletOptionLabel === "function") return economyWalletOptionLabel(wallet);
  const label = String(wallet?.label || wallet?.wallet_type || "wallet");
  return `${label} · ${tradingShortWalletAddress(wallet?.address || "")}`;
}

function tradingSpendableWallets(wallets = []) {
  return (Array.isArray(wallets) ? wallets : []).filter((wallet) => {
    const status = String(wallet?.status || "");
    const mode = String(wallet?.custody_mode || "");
    const type = String(wallet?.wallet_type || "");
    return status === "active" && mode !== "system" && !["mint", "burn"].includes(type) && wallet?.address;
  });
}

function renderTradingPaymentWalletOptions(wallets = [], selectedAddress = "") {
  const select = $("trading-payment-wallet");
  const note = $("trading-payment-wallet-note");
  if (!select) return;
  const spendable = tradingSpendableWallets(wallets);
  if (!spendable.length) {
    select.innerHTML = `<option value="">尚無可用付款錢包</option>`;
    select.disabled = true;
    if (note) note.textContent = "請先到積分錢包管理建立或綁定錢包。";
    return;
  }
  const previous = select.value;
  const saved = typeof readEconomyDefaultSpendWalletAddress === "function"
    ? String(readEconomyDefaultSpendWalletAddress() || "").trim().toLowerCase()
    : "";
  const normalizedSelected = String(selectedAddress || "").trim().toLowerCase();
  select.disabled = false;
  select.innerHTML = spendable.map((wallet) => {
    return `<option value="${sanitize(wallet.address)}">${sanitize(tradingWalletOptionLabel(wallet))}</option>`;
  }).join("");
  const candidates = [previous, saved, normalizedSelected].filter(Boolean);
  const matched = candidates.find((address) => spendable.some((wallet) => String(wallet.address || "").toLowerCase() === address));
  if (matched) select.value = matched;
  else if (spendable.some((wallet) => wallet.is_primary)) select.value = spendable.find((wallet) => wallet.is_primary).address;
  else select.value = spendable[0].address;
  if (typeof writeEconomyDefaultSpendWalletAddress === "function") {
    writeEconomyDefaultSpendWalletAddress(select.value || "");
  }
  const wallet = spendable.find((item) => String(item.address || "").toLowerCase() === String(select.value || "").toLowerCase());
  if (note) {
    const warning = String(tradingState.funding?.wallet_selection_warning || "").trim();
    if (warning) {
      note.textContent = `原付款錢包不可用：${warning}；已切回可用錢包 ${tradingShortWalletAddress(select.value)}。`;
      return;
    }
    const balance = Number(wallet?.points_balance || 0);
    const frozen = Number(wallet?.points_frozen || 0);
    note.textContent = `${tradingShortWalletAddress(select.value)} · 可用 ${formatTradingPointsValue(balance)} · 凍結 ${formatTradingPointsValue(frozen)}。此設定只影響交易所下單。`;
  }
}

function tradingSetPersonalField(field, value) {
  const el = $(field.id);
  if (!el) return;
  if ("checked" in field) {
    el.checked = value === undefined ? !!field.checked : !!value;
    return;
  }
  const nextValue = value === undefined || value === null ? field.value : String(value);
  if (el.tagName === "SELECT" && nextValue) {
    const exists = Array.from(el.options || []).some((option) => option.value === nextValue);
    if (!exists) return;
  }
  if (el.tagName === "SELECT" && !nextValue && el.options?.length) {
    const emptyOption = Array.from(el.options || []).some((option) => option.value === "");
    if (!emptyOption) {
      el.selectedIndex = 0;
      return;
    }
  }
  el.value = nextValue;
}

function captureTradingPersonalFormState() {
  const state = {};
  TRADING_PERSONAL_FORM_FIELDS.forEach((field) => {
    const el = $(field.id);
    if (!el) return;
    state[field.id] = "checked" in field ? !!el.checked : el.value;
  });
  return state;
}

function saveTradingPersonalFormState() {
  try {
    localStorage.setItem(tradingUserStorageKey(TRADING_PERSONAL_FORM_STORAGE_KEY), JSON.stringify(captureTradingPersonalFormState()));
  } catch (err) {}
}

function applyTradingPersonalFormState(saved = {}) {
  TRADING_PERSONAL_FORM_FIELDS.forEach((field) => {
    const hasSavedValue = Object.prototype.hasOwnProperty.call(saved, field.id);
    tradingSetPersonalField(field, hasSavedValue ? saved[field.id] : undefined);
  });
  syncTradingDcaIntervalMode();
  syncTradingOrderSideTheme();
  syncTradingOrderInputMode();
  updateTradingOrderEstimate();
  updateTradingMarginEstimate();
  if ($("trading-grid-preset")?.value) applyGridPreset({ quiet: true, save: false });
  scheduleGridBotPreview();
}

function loadTradingPersonalFormState() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(tradingUserStorageKey(TRADING_PERSONAL_FORM_STORAGE_KEY)) || "{}") || {};
  } catch (err) {
    saved = {};
  }
  applyTradingPersonalFormState(saved);
}

function ensureTradingAccountScope(options = {}) {
  const nextScope = tradingUserStorageScope();
  if (!options.force && tradingAccountScope === nextScope) return false;
  tradingAccountScope = nextScope;
  loadTradingPersonalFormState();
  return true;
}

function bindTradingPersonalFormPersistence() {
  TRADING_PERSONAL_FORM_FIELDS.forEach((field) => {
    const el = $(field.id);
    if (!el || el.dataset.tradingPersonalBound === "1") return;
    el.dataset.tradingPersonalBound = "1";
    el.addEventListener("input", saveTradingPersonalFormState);
    el.addEventListener("change", saveTradingPersonalFormState);
  });
}

function syncTradingDcaIntervalMode() {
  const dcaPreset = $("trading-dca-bot-interval-preset");
  const target = $("trading-dca-bot-interval-hours");
  const field = $("trading-dca-custom-interval-field");
  if (!dcaPreset || !target) return false;
  const custom = dcaPreset.value === "custom";
  target.disabled = !custom;
  if (field) field.style.display = custom ? "" : "none";
  if (!custom) target.value = dcaPreset.value;
  return custom;
}

function tradingWarningLanguage() {
  const raw = String(tradingState.settings?.warning_language || "zh-TW").trim().toLowerCase();
  return raw.startsWith("en") ? "en" : "zh-TW";
}

function tradingWarningText(key, vars = {}) {
  if (tradingWarningLanguage() === "en") {
    const messages = {
      risk_grade_unavailable: "Risk-grade price is unavailable. Market orders and other high-risk paths remain paused; limit orders are still allowed.",
      degrade_light: "Price sources degraded. Whether trading auto-pauses depends on the root risk-control policy.",
      market_kind: "Market-order trading",
      bot_kind: "Bot trading",
      borrowing_kind: "Borrowing / margin trading",
      root_auto_pause: `Root auto-pause enabled: ${vars.kinds || "-"}`,
      root_warn_only: `Root warning only; trading remains enabled (healthy providers ${vars.providerCount || 0}/${vars.tradeMinProviders || 0})`,
      root_warn_only_short: "Root warning only; trading remains enabled",
      risk_grade_unavailable_short: "Risk-grade price is unavailable",
      reference_degraded: "Reference price degraded",
      reference_healthy_risk_usable: "Reference price healthy; risk-grade price still usable",
      reference_healthy_confidence: `Reference price healthy; risk-grade confidence ${vars.confidence || "-"}`,
      auto_selected_market: `No market selected; automatically using ${vars.market || "-"}`,
      current_price_purpose_short: "Display / valuation",
      current_price_degraded_short: "Price degraded",
      current_price_paused_short: "Price degraded · paused",
      current_price_warning_short: "Price OK · notice",
      current_price_healthy_short: "Price OK",
      current_price_unavailable_short: "Price unavailable",
      current_price_defaulted_short: "Market auto-selected",
      pause_message: `${vars.kindLabel || "Trading"} paused because price health degraded: ${vars.reason || "-"}; healthy providers ${vars.providerCount || 0}, need at least ${vars.tradeMinProviders || 0}`,
      risk_usable_yes: "risk usable yes",
      risk_usable_no: "risk usable no",
    };
    return messages[key] || key;
  }
  const messages = {
    risk_grade_unavailable: "目前風控級價格不可用，已暫停市價單與高風險交易；限價單仍可使用",
    degrade_light: "價格來源降級，交易是否自動暫停由 root 風控開關決定",
    market_kind: "市價交易",
    bot_kind: "機器人交易",
    borrowing_kind: "借貸交易",
    root_auto_pause: `root 已設定自動暫停：${vars.kinds || "-"}`,
    root_warn_only: `root 目前僅警示，不自動暫停交易（健康來源 ${vars.providerCount || 0}/${vars.tradeMinProviders || 0}）`,
    root_warn_only_short: "root 目前僅警示，不自動暫停交易",
    risk_grade_unavailable_short: "風控級價格目前不可用",
    reference_degraded: "reference 價格降級",
    reference_healthy_risk_usable: "reference 價格正常 · 風控級價格仍可用",
    reference_healthy_confidence: `reference 價格正常 · 風控級來源信心 ${vars.confidence || "-"}`,
    auto_selected_market: `未指定市場，已自動選用 ${vars.market || "-"}`,
    current_price_purpose_short: "展示 / 估值",
    current_price_degraded_short: "價格降級",
    current_price_paused_short: "價格降級 · 已暫停",
    current_price_warning_short: "價格正常 · 有提示",
    current_price_healthy_short: "價格正常",
    current_price_unavailable_short: "價格不可用",
    current_price_defaulted_short: "已自動選市場",
    pause_message: `${vars.kindLabel || "交易"}已因價格降級暫停：${vars.reason || "-"} · 目前健康來源 ${vars.providerCount || 0} 家，至少需要 ${vars.tradeMinProviders || 0} 家`,
    risk_usable_yes: "風控可用 yes",
    risk_usable_no: "風控可用 no",
  };
  return messages[key] || key;
}

function tradingPriceDegradePolicy(riskContext, kind = "market") {
  const settings = tradingState.settings || {};
  const safe = riskContext && typeof riskContext === "object" ? riskContext : {};
  const warningLanguage = tradingWarningLanguage();
  const priceConfidenceOnlyWarns = settings.disable_price_confidence_gates !== false;
  const tradeMinProviders = Math.max(1, Number(settings.price_fusion_trade_min_provider_count || 1));
  const providerCount = Math.max(
    0,
    Number.isFinite(Number(safe.provider_count))
      ? Number(safe.provider_count)
      : Number(safe.risk_grade_provider_count || 0)
  );
  const conservativeMode = !!safe.conservative_mode;
  const fallback = !!safe.fallback;
  const stale = !!safe.stale;
  const degraded = !!safe.degraded;
  const providerShort = conservativeMode && providerCount < tradeMinProviders;
  const severeDegrade = fallback || stale || (degraded && !conservativeMode) || providerShort;
  let policyEnabled = false;
  let kindLabel = warningLanguage === "en" ? "Trading" : "交易";
  if (kind === "bot") {
    policyEnabled = !priceConfidenceOnlyWarns && !!settings.price_degrade_pause_bots;
    kindLabel = tradingWarningText("bot_kind");
  } else if (kind === "borrowing") {
    policyEnabled = !priceConfidenceOnlyWarns && !!settings.price_degrade_pause_borrowing;
    kindLabel = tradingWarningText("borrowing_kind");
  } else {
    policyEnabled = !priceConfidenceOnlyWarns && !!settings.price_degrade_pause_market_orders;
    kindLabel = tradingWarningText("market_kind");
  }
  return {
    kind,
    kindLabel,
    policyEnabled,
    shouldPause: policyEnabled && severeDegrade,
    conservativeMode,
    severeDegrade,
    providerShort,
    providerCount,
    tradeMinProviders,
  };
}

function tradingPriceDegradePauseMessage(kindLabel, riskContext, policy) {
  const safe = riskContext && typeof riskContext === "object" ? riskContext : {};
  const applied = policy || tradingPriceDegradePolicy(safe);
  const fallbackReason = tradingWarningLanguage() === "en"
    ? "Current price source is not suitable for risk-grade execution"
    : "價格來源目前不適合風控級成交";
  const reason = String(safe.warning_message || safe.high_risk_block_reason || safe.fallback_reason || fallbackReason).trim();
  return tradingWarningText("pause_message", {
    kindLabel,
    reason,
    providerCount: applied.providerCount,
    tradeMinProviders: applied.tradeMinProviders,
  });
}

function tradingRequestId(prefix = "trading") {
  if (typeof economyRequestId === "function") return economyRequestId(prefix);
  if (window.crypto && typeof window.crypto.randomUUID === "function") return `${prefix}:${window.crypto.randomUUID()}`;
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function tradingSetMsg(text, ok = true) {
  const kind = ok === false ? "err" : ok === null ? "info" : "ok";
  const apply = (msg) => {
    if (!msg) return;
    msg.textContent = text || "";
    msg.className = text ? `msg show ${kind}` : "msg";
    scheduleInlineMessageClear(msg, text, ok);
  };
  const targets = [
    $("trading-inline-msg"),
    $("trading-root-inline-msg"),
    $("trading-msg"),
  ].filter(Boolean);
  targets.forEach(apply);
  if (!targets.length && typeof economySetMsg === "function") {
    economySetMsg(text, ok);
    return;
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

function tradingFriendlyErrorText(text, fallback = "操作失敗") {
  const raw = String(text || "").trim();
  if (!raw) return fallback;
  if (raw.includes("candles are required for selected backtest range")) {
    return "目前圖表 K 線不涵蓋你選的回測區間。系統會改由後端重抓歷史 K 線；若仍失敗，請縮小區間或改大時間週期。";
  }
  if (raw.includes("grid bot create is disabled for this market") || raw.includes("bots are disabled for this market")) {
    return "這個市場目前未開放交易機器人。請改選其他市場，或由 root 到交易市場 registry 開啟 allow_bots。";
  }
  if (raw.includes("unsupported workflow node type")) {
    const nodeType = raw.split(":").slice(1).join(":").trim();
    return nodeType
      ? `Workflow 節點類型目前不支援：${nodeType}。請重新套用目前版本模板或回編輯器重存。`
      : "Workflow 節點類型目前不支援。請重新套用目前版本模板或回編輯器重存。";
  }
  if (raw.includes("trading place_order forbidden in mode='dev_ready'")) {
    return "目前伺服器是 dev_ready 模式，交易下單被停用。請切到 test / internal_test / production 後再下單。";
  }
  if (raw.includes("market order is blocked while fused price is in conservative mode")) {
    const reason = raw.split(":").slice(1).join(":").trim();
    return reason
      ? `目前風控級價格不可用，市價單已暫停：${reason}。可等價格來源恢復，或改用有價格上限的限價單。`
      : "目前風控級價格不可用，市價單已暫停。可等價格來源恢復，或改用有價格上限的限價單。";
  }
  if (raw.includes("尚未收到任何即時價格更新") || raw.includes("啟動時的預設參考價")) {
    return `${raw}。開發測試站請用 test_for_develop.sh 啟動；正式站請等待價格來源完成暖機。`;
  }
  return raw;
}

async function fetchTradingJson(url, options = {}) {
  const rawOptions = options || {};
  const method = String(rawOptions.method || "GET").toUpperCase();
  const { forceCsrf = method !== "GET", allowMissingSnapshot = false, ...requestOptions } = rawOptions;
  await fetchCsrfToken({ force: !!forceCsrf });
  const headers = { ...(requestOptions.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (requestOptions.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await apiFetch(API + url, { credentials: "same-origin", ...requestOptions, headers });
  const raw = await res.text().catch(() => "");
  let json = {};
  try {
    json = raw ? JSON.parse(raw) : {};
  } catch (_) {
    json = {};
  }
  if (allowMissingSnapshot && json?.snapshot?.missing) return json;
  if (!res.ok || !json.ok) {
    let fallback = `HTTP ${res.status}`;
    if (res.status === 404) fallback = `交易所 API 不存在：${url}。請確認伺服器已重啟且目前是包含交易所功能的分支。`;
    else if (raw && raw.trim() && !/^not found$/i.test(raw.trim())) fallback = raw.slice(0, 220);
    const text = tradingFriendlyErrorText(tradingErrorText(json, fallback), fallback);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return json;
}

function scheduleTradingMutationRefresh(delayMs = 120) {
  if (tradingMutationRefreshTimer) clearTimeout(tradingMutationRefreshTimer);
  tradingMutationRefreshTimer = setTimeout(async () => {
    tradingMutationRefreshTimer = null;
    if (tradingMutationRefreshBusy) {
      scheduleTradingMutationRefresh(300);
      return;
    }
    tradingMutationRefreshBusy = true;
    try {
      await loadTradingDashboard();
    } catch (_) {
      // The order already succeeded; the next scheduled refresh will retry state sync.
    } finally {
      tradingMutationRefreshBusy = false;
    }
  }, Math.max(0, Number(delayMs) || 0));
}

async function tradingFreshCsrfToken() {
  return await fetchCsrfToken({ force: true });
}

function bindTradingActionButton(el, handler, pendingText, fallbackText) {
  if (!el || typeof handler !== "function") return;
  el.addEventListener("click", async (event) => {
    event.preventDefault();
    if (el.disabled) return;
    const previousText = el.textContent;
    el.disabled = true;
    el.setAttribute("aria-busy", "true");
    tradingActiveActionButton = el;
    if (pendingText) tradingSetMsg(pendingText, null);
    try {
      await handler(event);
    } catch (err) {
      tradingSetMsg(`${fallbackText || "操作失敗"}：${err?.message || "未提供錯誤原因"}`, false);
    } finally {
      tradingActiveActionButton = null;
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

function tradingUsablePricePoints(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0;
}

function tradingPriceContextHasUsablePrice(context) {
  return !!(context && typeof context === "object" && tradingUsablePricePoints(context.price_points));
}

function tradingMergeLivePriceContext(previousContext, nextContext) {
  const previous = previousContext && typeof previousContext === "object" ? previousContext : null;
  const next = nextContext && typeof nextContext === "object" ? nextContext : null;
  if (!next) return previous;
  if (tradingPriceContextHasUsablePrice(next)) return next;
  if (!tradingPriceContextHasUsablePrice(previous)) return next;
  const warning = String(next.warning_message || "").trim();
  return {
    ...next,
    price_points: previous.price_points,
    source: next.source || previous.source,
    source_label: next.source_label || previous.source_label,
    stale_price_for_display: true,
    warning_message: warning
      ? `${warning} · 沿用上一筆可用風控價顯示盈虧`
      : "沿用上一筆可用風控價顯示盈虧",
  };
}

function tradingMergeLiveMarket(previousMarket, nextMarket) {
  const previous = previousMarket && typeof previousMarket === "object" ? previousMarket : {};
  const next = nextMarket && typeof nextMarket === "object" ? nextMarket : {};
  const merged = { ...previous, ...next };
  [
    ["reference_price_context", "reference_price_points"],
    ["risk_grade_price_context", "risk_grade_price_points"],
  ].forEach(([contextKey, priceKey]) => {
    const context = tradingMergeLivePriceContext(previous[contextKey], next[contextKey]);
    if (context) merged[contextKey] = context;
    if (tradingPriceContextHasUsablePrice(context)) {
      merged[priceKey] = context.price_points;
    } else if (!tradingUsablePricePoints(merged[priceKey]) && tradingUsablePricePoints(previous[priceKey])) {
      merged[priceKey] = previous[priceKey];
    }
  });
  return merged;
}

function tradingMarketPriceContext(market, priceType = "reference") {
  const type = priceType === "risk_grade" ? "risk_grade" : "reference";
  const contextKey = type === "risk_grade" ? "risk_grade_price_context" : "reference_price_context";
  const symbol = String(market?.symbol || "");
  const liveMeta = tradingState.livePriceMeta || {};
  const liveContext = tradingMergeLivePriceContext(market?.[contextKey], liveMeta[symbol]?.[contextKey]);
  if (liveContext && typeof liveContext === "object") {
    return {
      ...liveContext,
      conservative_mode: !!liveMeta[symbol]?.conservative_mode || liveMeta[symbol]?.price_health === "conservative",
      minimum_provider_count: Number(liveMeta[symbol]?.minimum_provider_count || liveContext.minimum_provider_count || 0),
    };
  }
  if (market?.[contextKey] && typeof market[contextKey] === "object") {
    return {
      ...market[contextKey],
      conservative_mode: !!market?.conservative_mode || market?.price_health === "conservative",
      minimum_provider_count: Number(market?.minimum_provider_count || market[contextKey].minimum_provider_count || 0),
    };
  }
  const source = String(market?.price_source || "manual_root");
  const pricePoints = type === "risk_grade"
    ? tradingNumber(market?.risk_grade_price_points ?? market?.manual_price_points, 0)
    : tradingNumber(market?.reference_price_points ?? market?.manual_price_points, 0);
  return {
    price_type: type,
    price_points: pricePoints,
    source,
    source_label: source,
    confidence: source === "manual_root" ? "manual" : "unknown",
    stale: source.endsWith("_cached"),
    degraded: source === "manual_root" || source.endsWith("_cached"),
    provider_count: source === "manual_root" ? 0 : 1,
    purpose: type === "risk_grade" ? "融資 / 強平 / 保證金 / PnL / bot 風控 / 交易限制" : "展示 / 一般估值 / K 線 / 非風控參考",
    warning_message: source === "manual_root" ? "目前使用手動價格" : (source.endsWith("_cached") ? "目前使用最後健康快取" : ""),
    high_risk_blocked: false,
    risk_grade_usable: type === "risk_grade" && source !== "manual_root" && !source.endsWith("_cached"),
    conservative_mode: false,
    minimum_provider_count: 0,
    warnings: [],
    excluded_sources: [],
  };
}

function tradingMarketPricePoints(market, priceType = "reference") {
  const context = tradingMarketPriceContext(market, priceType);
  const fallback = priceType === "risk_grade"
    ? (market?.risk_grade_price_points ?? market?.reference_price_points ?? market?.manual_price_points)
    : (market?.reference_price_points ?? market?.manual_price_points);
  return tradingNumber(context?.price_points ?? fallback, 0);
}

function tradingPriceConfidenceLabel(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "high") return "高";
  if (normalized === "medium") return "中";
  if (normalized === "low") return "低";
  if (normalized === "manual") return "手動";
  return normalized || "-";
}

function tradingPriceContextSummary(context, { compact = false } = {}) {
  const safe = context && typeof context === "object" ? context : {};
  const sourceLabel = safe.source_label || safe.source || "未知來源";
  const providerText = Number.isFinite(Number(safe.provider_count))
    ? `來源 ${Number(safe.provider_count)} 家`
    : "來源數未知";
  const confidenceText = `信心 ${tradingPriceConfidenceLabel(safe.confidence)}`;
  const stateText = safe.stale ? "stale" : (safe.degraded ? "degraded" : "正常");
  const riskGradeUsableText = safe.price_type === "risk_grade"
    ? (safe.risk_grade_usable ? tradingWarningText("risk_usable_yes") : tradingWarningText("risk_usable_no"))
    : "";
  const warning = String(safe.warning_message || "").trim();
  if (compact) {
    return `${sourceLabel} · ${confidenceText} · ${stateText}${riskGradeUsableText ? ` · ${riskGradeUsableText}` : ""}${warning ? ` · ${warning}` : ""}`;
  }
  return `${safe.purpose || ""} · ${sourceLabel} · ${providerText} · ${confidenceText} · ${stateText}${riskGradeUsableText ? ` · ${riskGradeUsableText}` : ""}${warning ? ` · ${warning}` : ""}`;
}

function tradingTransportStateSummary(state, { compact = false } = {}) {
  const safe = state && typeof state === "object" ? state : {};
  const mode = String(safe.mode || safe.transport || "http_polling_only");
  const connection = safe.connected ? "connected" : "disconnected";
  const fallback = safe.fallback ? "HTTP fallback" : "直連";
  const stale = safe.stale ? "stale" : "fresh";
  const confidence = `信心 ${tradingPriceConfidenceLabel(safe.confidence)}`;
  const providerText = Number.isFinite(Number(safe.provider_count)) ? `provider ${Number(safe.provider_count)}` : "provider ?";
  const reason = String(safe.exclusion_reason || safe.message || "").trim();
  const base = `${mode} · ${connection} · ${fallback} · ${stale} · ${confidence} · ${providerText}`;
  if (compact) return reason ? `${base} · ${reason}` : base;
  return reason ? `provider input：${base} · ${reason}` : `provider input：${base}`;
}

function setTradingPriceTooltip(el, text, detail = "") {
  if (!el) return;
  const cleanText = String(text || "").trim();
  const cleanDetail = String(detail || "").trim();
  el.textContent = cleanText;
  if (cleanDetail && cleanDetail !== cleanText) {
    el.dataset.tooltip = cleanDetail;
    el.title = cleanDetail;
    el.tabIndex = 0;
    el.classList.add("trading-price-tooltip");
  } else {
    delete el.dataset.tooltip;
    el.removeAttribute("title");
    el.removeAttribute("tabindex");
    el.classList.remove("trading-price-tooltip");
  }
}

function renderTradingCurrentPrice(market, options = {}) {
  const priceEl = $("trading-current-price");
  const labelEl = $("trading-current-label");
  const marketEl = $("trading-current-market");
  const deltaEl = $("trading-current-delta");
  const purposeEl = $("trading-current-purpose");
  const healthEl = $("trading-current-health");
  const animate = options.animate !== false;
  const symbol = String(market?.symbol || "");
  const referenceContext = options.referencePriceContext || tradingMarketPriceContext(market, "reference");
  const riskContext = options.riskGradePriceContext || tradingMarketPriceContext(market, "risk_grade");
  const nextPrice = tradingMarketPricePoints(market, "reference");
  const priceHistory = tradingState.livePriceHistory || (tradingState.livePriceHistory = {});
  const liveMeta = tradingState.livePriceMeta || {};
  const health = options.priceHealth || referenceContext?.health || liveMeta[symbol]?.price_health || "healthy";
  const fallbackReason = options.fallbackReason || referenceContext?.warning_message || liveMeta[symbol]?.fallback_reason || "";
  const excludedSources = Array.isArray(options.excludedSources) ? options.excludedSources : (referenceContext?.excluded_sources || liveMeta[symbol]?.excluded_sources || []);
  const warnings = Array.isArray(options.warnings) ? options.warnings : (referenceContext?.warnings || liveMeta[symbol]?.warnings || []);
  const highRiskBlockReason = options.highRiskBlockReason || riskContext?.warning_message || liveMeta[symbol]?.high_risk_block_reason || "";
  const defaultedMarket = options.defaultedMarket === true || liveMeta[symbol]?.defaulted_market === true;
  const transportState = options.transportState || liveMeta[symbol]?.transport_state || {};
  const marketPausePolicy = tradingPriceDegradePolicy(riskContext, "market");
  const botPausePolicy = tradingPriceDegradePolicy(riskContext, "bot");
  const borrowingPausePolicy = tradingPriceDegradePolicy(riskContext, "borrowing");
  if (labelEl) labelEl.textContent = "目前價格（reference）";
  setTradingPriceTooltip(
    purposeEl,
    `用途：${tradingWarningText("current_price_purpose_short")}`,
    `用途：展示 / 一般估值 · ${tradingPriceContextSummary(referenceContext, { compact: true })} · ${tradingTransportStateSummary(transportState, { compact: true })}`,
  );
  const previousPrice = symbol && Number.isFinite(priceHistory[symbol]) ? Number(priceHistory[symbol]) : null;
  if (priceEl) {
    priceEl.textContent = market ? formatTradingPointsValue(nextPrice) : "-";
    priceEl.classList.remove("trading-price-up", "trading-price-down", "trading-price-flat", "trading-price-flash");
  }
  if (marketEl) {
    marketEl.textContent = market
      ? `${tradingDisplaySymbol(market.symbol)} · ${referenceContext?.source_label || market.price_source || "last_good_cache"} · ${Math.round(tradingLivePriceRefreshMs() / 1000)} 秒更新`
      : "-";
  }
  if (!market || !Number.isFinite(nextPrice)) {
    if (deltaEl) {
      deltaEl.textContent = "即時價格暫不可用";
      deltaEl.classList.remove("positive", "negative");
    }
    if (healthEl) {
      setTradingPriceTooltip(healthEl, `🟡 ${tradingWarningText("current_price_unavailable_short")}`, "即時 reference 價格暫不可用；請稍後重試或改用限價。");
      healthEl.classList.add("warning");
    }
    return;
  }
  let direction = "flat";
  let delta = 0;
  if (previousPrice != null && Number.isFinite(previousPrice)) {
    delta = nextPrice - previousPrice;
    direction = delta > 0 ? "up" : (delta < 0 ? "down" : "flat");
  }
  priceHistory[symbol] = nextPrice;
  if (priceEl) {
    priceEl.classList.add(direction === "up" ? "trading-price-up" : (direction === "down" ? "trading-price-down" : "trading-price-flat"));
    if (animate && direction !== "flat") {
      void priceEl.offsetWidth;
      priceEl.classList.add("trading-price-flash");
    }
  }
  if (deltaEl) {
    if (direction === "up") {
      deltaEl.textContent = `▲ +${formatTradingPointsValue(delta)}`;
      deltaEl.classList.add("positive");
      deltaEl.classList.remove("negative");
    } else if (direction === "down") {
      deltaEl.textContent = `▼ ${formatTradingPointsValue(delta)}`;
      deltaEl.classList.add("negative");
      deltaEl.classList.remove("positive");
    } else {
      deltaEl.textContent = `即時輪詢 ${Math.round(tradingLivePriceRefreshMs() / 1000)} 秒`;
      deltaEl.classList.remove("positive", "negative");
    }
  }
  if (healthEl) {
    if (health === "conservative") {
      const notes = [];
      if (defaultedMarket) notes.push(`未指定市場，已改用 ${tradingDisplaySymbol(symbol)}`);
      if (highRiskBlockReason) notes.push(highRiskBlockReason);
      if (excludedSources.length) notes.push(`排除 ${excludedSources.join(", ")}`);
      if (transportState.fallback) notes.push("WebSocket provider input 已退回 HTTP polling");
      if (transportState.stale) notes.push("provider input stale");
      const pauseKinds = [marketPausePolicy, botPausePolicy, borrowingPausePolicy]
        .filter((item) => item.shouldPause)
        .map((item) => item.kindLabel);
      if (pauseKinds.length) {
        notes.unshift(tradingWarningText("root_auto_pause", { kinds: pauseKinds.join(" / ") }));
      } else {
        notes.unshift(tradingWarningText("root_warn_only", {
          providerCount: marketPausePolicy.providerCount,
          tradeMinProviders: marketPausePolicy.tradeMinProviders,
        }));
      }
      setTradingPriceTooltip(
        healthEl,
        `🟡 ${tradingWarningText(pauseKinds.length ? "current_price_paused_short" : "current_price_degraded_short")}`,
        `${tradingWarningText("degrade_light")}${notes.length ? ` · ${notes.join(" · ")}` : ""}`,
      );
      healthEl.classList.add("warning");
    } else if (
      health === "fallback"
      || health === "degraded"
      || transportState.fallback
      || transportState.stale
      || transportState.degraded
      || riskContext?.high_risk_blocked
      || riskContext?.risk_grade_usable === false
    ) {
      const notes = [];
      if (excludedSources.length) notes.push(`排除 ${excludedSources.join(", ")}`);
      if (fallbackReason) notes.push(fallbackReason);
      if (!fallbackReason && warnings.length) notes.push(String(warnings[0]?.message || warnings[0]?.code || ""));
      if (!fallbackReason && !warnings.length && riskContext?.warning_message) notes.push(riskContext.warning_message);
      if (transportState.fallback) notes.push("WebSocket provider input 已退回 HTTP polling");
      if (transportState.stale) notes.push("provider input stale");
      if (riskContext?.risk_grade_usable === false && !riskContext?.high_risk_blocked) notes.push(tradingWarningText("risk_grade_unavailable_short"));
      const pauseKinds = [marketPausePolicy, botPausePolicy, borrowingPausePolicy]
        .filter((item) => item.shouldPause)
        .map((item) => item.kindLabel);
      if (pauseKinds.length) notes.unshift(tradingWarningText("root_auto_pause", { kinds: pauseKinds.join(" / ") }));
      else notes.unshift(tradingWarningText("root_warn_only_short"));
      if (defaultedMarket) notes.push(tradingWarningText("auto_selected_market", { market: tradingDisplaySymbol(symbol) }));
      setTradingPriceTooltip(
        healthEl,
        `🟡 ${tradingWarningText(pauseKinds.length ? "current_price_paused_short" : "current_price_degraded_short")}`,
        `${tradingWarningText("reference_degraded")}${notes.length ? ` · ${notes.join(" · ")}` : ""}`,
      );
      healthEl.classList.add("warning");
    } else if (excludedSources.length || warnings.length || referenceContext?.warning_only || riskContext?.warning_only) {
      const notes = [];
      if (excludedSources.length) notes.push(`已自動排除 ${excludedSources.join(", ")}`);
      if (warnings.length) notes.push(String(warnings[0]?.message || warnings[0]?.code || ""));
      setTradingPriceTooltip(
        healthEl,
        `🟢 ${tradingWarningText("current_price_warning_short")}`,
        `${tradingWarningText("reference_healthy_risk_usable")}${notes.length ? ` · ${notes.join(" · ")}` : ""}`,
      );
      healthEl.classList.remove("warning");
    } else if (defaultedMarket) {
      setTradingPriceTooltip(
        healthEl,
        `🟢 ${tradingWarningText("current_price_defaulted_short")}`,
        tradingWarningText("auto_selected_market", { market: tradingDisplaySymbol(symbol) }),
      );
      healthEl.classList.remove("warning");
    } else {
      setTradingPriceTooltip(
        healthEl,
        `🟢 ${tradingWarningText("current_price_healthy_short")}`,
        tradingWarningText("reference_healthy_confidence", { confidence: tradingPriceConfidenceLabel(riskContext?.confidence) }),
      );
      healthEl.classList.remove("warning");
    }
  }
}

function tradingDisplaySymbol(symbol) {
  const normalized = String(symbol || "").trim().toUpperCase();
  const market = (tradingState.markets || []).find((row) => String(row?.symbol || "").trim().toUpperCase() === normalized);
  if (market?.display_symbol) return String(market.display_symbol);
  return normalized.replace("/POINTS", "/USDT");
}

function tradingBaseAssetLabel(marketOrSymbol) {
  const market = typeof marketOrSymbol === "object"
    ? marketOrSymbol
    : tradingMarketBySymbol(String(marketOrSymbol || ""));
  return String(market?.base_asset || tradingDisplaySymbol(market?.symbol || marketOrSymbol).split("/")[0] || "資產").toUpperCase();
}

function tradingBorrowAprGroupForMarket(market, positionType = "margin_long") {
  const normalizedType = String(positionType || "margin_long").toLowerCase();
  const asset = normalizedType === "short"
    ? String(market?.base_asset || "").toUpperCase()
    : String(market?.quote_currency || "POINTS").toUpperCase();
  return asset === "BTC" || asset === "ETH" ? "btc_eth" : "usdt_points";
}

function tradingBorrowBaseAprPercent(group) {
  const settings = tradingState.settings || {};
  if (group === "btc_eth") return tradingNumber(settings.borrow_apr_btc_eth_percent, 8);
  return tradingNumber(settings.borrow_apr_usdt_points_percent, 10);
}

function tradingBorrowEffectiveAprPercent(group, utilizationPercent = null) {
  const util = tradingNumber(
    utilizationPercent ?? tradingState.fundingPool?.utilization_percent,
    0,
  ) / 100;
  const pressure = tradingNumber(tradingState.settings?.borrow_interest_pool_pressure_multiplier, 4);
  const baseApr = tradingBorrowBaseAprPercent(group);
  return baseApr * (1 + Math.max(0, util) * Math.max(0, pressure));
}

function tradingBorrowTimingSummary() {
  const intervalHours = Math.max(1, tradingNumber(tradingState.settings?.borrow_interest_interval_hours, 1));
  const minimumHours = Math.max(1, tradingNumber(tradingState.settings?.borrow_interest_minimum_hours, 1));
  return {
    intervalHours,
    minimumHours,
    text: `每 ${formatTradingPointsValue(intervalHours)} 小時計息，不足 ${formatTradingPointsValue(minimumHours)} 小時以 ${formatTradingPointsValue(minimumHours)} 小時計`,
  };
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

const BACKTEST_TOTAL_CANDLE_LIMIT = 20000;
const TRADING_BACKTEST_CONTEXTS = {
  dca: { tab: "dca", botType: "dca", prefix: "trading-dca-backtest" },
  grid: { tab: "grid", botType: "grid", prefix: "trading-grid-backtest" },
  workflow: { tab: "strategy", botType: "workflow", prefix: "trading-workflow-backtest" },
};

function tradingBacktestConfig(contextKey = "dca") {
  return TRADING_BACKTEST_CONTEXTS[contextKey] || TRADING_BACKTEST_CONTEXTS.dca;
}

function tradingBacktestEl(contextKey, suffix) {
  const cfg = tradingBacktestConfig(contextKey);
  return $(`${cfg.prefix}-${suffix}`);
}

function tradingTimeframeMinutes(timeframe) {
  const mapping = { "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440 };
  return mapping[String(timeframe || "15m").trim()] || 15;
}

function estimateBacktestRequestedCandles(startTime, endTime, timeframe) {
  const startMs = startTime ? Date.parse(startTime) : NaN;
  const endMs = endTime ? Date.parse(endTime) : NaN;
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return 0;
  const intervalMs = tradingTimeframeMinutes(timeframe) * 60 * 1000;
  return Math.max(2, Math.floor((endMs - startMs) / intervalMs) + 1);
}

function formatBacktestDatetimeLocal(ms) {
  if (!Number.isFinite(ms)) return "";
  const date = new Date(ms);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function backtestTimeframeLabel(contextKey = "dca") {
  const select = tradingBacktestEl(contextKey, "timeframe");
  return select?.selectedOptions?.[0]?.textContent?.trim() || `${tradingTimeframeMinutes(select?.value)} 分`;
}

function updateBacktestDateRangeGuidance(contextKey = "dca") {
  const hint = tradingBacktestEl(contextKey, "date-hint");
  const startEl = tradingBacktestEl(contextKey, "start");
  const endEl = tradingBacktestEl(contextKey, "end");
  if (!hint || !startEl || !endEl) return;
  const timeframe = tradingBacktestEl(contextKey, "timeframe")?.value || "15m";
  const timeframeText = backtestTimeframeLabel(contextKey);
  const intervalMs = tradingTimeframeMinutes(timeframe) * 60 * 1000;
  const maxSpanMs = Math.max(0, (BACKTEST_TOTAL_CANDLE_LIMIT - 1) * intervalMs);
  const maxSpanText = formatTradingDuration(maxSpanMs);
  const startMs = startEl.value ? Date.parse(startEl.value) : NaN;
  const endMs = endEl.value ? Date.parse(endEl.value) : NaN;

  endEl.min = Number.isFinite(startMs) ? formatBacktestDatetimeLocal(startMs) : "";
  endEl.max = Number.isFinite(startMs) ? formatBacktestDatetimeLocal(startMs + maxSpanMs) : "";
  startEl.max = Number.isFinite(endMs) ? formatBacktestDatetimeLocal(endMs) : "";
  startEl.min = Number.isFinite(endMs) ? formatBacktestDatetimeLocal(endMs - maxSpanMs) : "";

  let text = `以目前 ${timeframeText} 週期，單次回測最多約 ${maxSpanText}。`;
  let color = "var(--muted)";

  if (!Number.isFinite(startMs) && !Number.isFinite(endMs)) {
    text += " 先選開始或結束時間，系統會提示另一側最遠可選到哪裡。";
  } else if (Number.isFinite(startMs) && !Number.isFinite(endMs)) {
    text += ` 若保留開始時間，結束最晚可選 ${formatBacktestDatetimeLocal(startMs + maxSpanMs)}。`;
  } else if (!Number.isFinite(startMs) && Number.isFinite(endMs)) {
    text += ` 若保留結束時間，開始最早可選 ${formatBacktestDatetimeLocal(endMs - maxSpanMs)}。`;
  } else if (endMs < startMs) {
    color = "#ff4f6d";
    text = `結束時間不能早於開始時間。若保留開始時間，結束至少要從 ${formatBacktestDatetimeLocal(startMs)} 開始。`;
  } else {
    const estimatedCandles = estimateBacktestRequestedCandles(startEl.value, endEl.value, timeframe);
    const selectedWindowMs = Math.max(0, endMs - startMs);
    if (estimatedCandles > BACKTEST_TOTAL_CANDLE_LIMIT) {
      color = "#ffb74d";
      text = `這段時間對 ${timeframeText} 週期來說太長了。若保留開始時間，結束最晚可選 ${formatBacktestDatetimeLocal(startMs + maxSpanMs)}；若保留結束時間，開始最早可選 ${formatBacktestDatetimeLocal(endMs - maxSpanMs)}。`;
    } else {
      text += ` 目前區間約 ${formatTradingDuration(selectedWindowMs)}，仍在單次回測範圍內。若保留開始時間，結束最晚可選 ${formatBacktestDatetimeLocal(startMs + maxSpanMs)}。`;
    }
  }

  hint.textContent = text;
  hint.style.color = color;
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

function tradingSettlementFeePoints(notional, feeRatePercent) {
  return tradingMicropointsToSettlementPoints(tradingFeeMicropoints(notional, feeRatePercent));
}

function tradingFeeMicropoints(notional, feeRatePercent) {
  const exactFee = Number(notional || 0) * Number(feeRatePercent || 0) * TRADING_POINT_MICRO_SCALE / 100;
  if (!Number.isFinite(exactFee) || exactFee <= 0) return 0;
  return Math.round(exactFee);
}

function tradingMicropointsToSettlementPoints(totalMicropoints) {
  const micro = Math.max(0, Math.round(tradingNumber(totalMicropoints, 0)));
  if (micro <= 0) return 0;
  return Math.ceil(micro / TRADING_POINT_MICRO_SCALE - Number.EPSILON);
}

function currentTradingPosition(marketSymbol) {
  return tradingState.positions.find((row) => row.market_symbol === marketSymbol) || null;
}

function tradingMarketBySymbol(symbol) {
  return tradingState.markets.find((row) => row.symbol === symbol) || null;
}

function tradingLivePriceTargetSymbols() {
  const symbols = new Set();
  if (currentModuleTab === "trading") {
    const selected = selectedTradingMarket();
    if (selected?.symbol) symbols.add(selected.symbol);
  }
  (tradingState.positions || []).forEach((row) => {
    const quantity = tradingNumber(row?.quantity, 0) + tradingNumber(row?.locked_quantity, 0);
    if (quantity > 0 && row?.market_symbol) symbols.add(row.market_symbol);
  });
  (tradingState.marginPositions || []).forEach((row) => {
    if (row?.status === "open" && row?.market_symbol) symbols.add(row.market_symbol);
  });
  return Array.from(symbols);
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
    const assetLabel = tradingBaseAssetLabel(selectedTradingMarket());
    note.textContent = inputMode === "points"
      ? "買入時點數視為含手續費的總支出；賣出時點數視為成交名目金額，系統自動換算枚數。"
      : `直接輸入 ${assetLabel} 枚數。`;
  }
}

function tradingOrderDraftEstimate() {
  const market = selectedTradingMarket();
  if (!market) return { ok: false, blocking: true, message: "沒有可用交易市場" };
  const side = $("trading-side")?.value || "buy";
  const orderType = $("trading-order-type")?.value || "market";
  const inputMode = tradingOrderInputMode();
  const rawInputValue = String($("trading-quantity")?.value || "").trim();
  const inputValue = tradingNumber(rawInputValue, 0);
  const limitPrice = tradingNumber($("trading-limit-price")?.value, 0);
  const referenceContext = tradingMarketPriceContext(market, "reference");
  const riskContext = tradingMarketPriceContext(market, "risk_grade");
  const marketPausePolicy = tradingPriceDegradePolicy(riskContext, "market");
  const priceConfidenceOnlyWarns = tradingState.settings?.disable_price_confidence_gates !== false || !!tradingState.settings?.dev_allow_conservative_market_orders;
  const riskGradePrice = tradingMarketPricePoints(market, "risk_grade");
  const referencePrice = tradingMarketPricePoints(market, "reference");
  const price = orderType === "limit"
    ? limitPrice
    : (riskGradePrice > 0 ? riskGradePrice : (marketPausePolicy.shouldPause ? riskGradePrice : referencePrice));
  const feeRate = tradingNumber(market.fee_rate_percent, 0) / 100;
  if (rawInputValue && inputValue <= 0) {
    return {
      ok: false,
      blocking: true,
      message: inputMode === "points" ? "點數金額必須大於 0" : "交易數量必須大於 0",
    };
  }
  if (!inputValue) {
    return {
      ok: false,
      blocking: false,
      message: inputMode === "points" ? "輸入點數後自動換算枚數" : "輸入數量後顯示預估金額",
    };
  }
  if (!price || price <= 0) {
    return {
      ok: false,
      blocking: true,
      message: orderType === "limit"
        ? "請輸入有效限價"
        : (marketPausePolicy.shouldPause
          ? tradingPriceDegradePauseMessage("市價交易", riskContext, marketPausePolicy)
          : "目前無法取得可用成交估值，請稍後再試"),
    };
  }
  if (orderType !== "limit" && !priceConfidenceOnlyWarns && (riskContext?.high_risk_blocked || riskContext?.risk_grade_usable === false)) {
    return {
      ok: false,
      blocking: true,
      message: `${tradingPriceDegradePauseMessage("市價交易", riskContext, marketPausePolicy)}。可等價格來源恢復，或改用有價格上限的限價單。`,
    };
  }
  if (orderType !== "limit" && marketPausePolicy.shouldPause) {
    return {
      ok: false,
      blocking: true,
      message: `${tradingPriceDegradePauseMessage("市價交易", riskContext, marketPausePolicy)} · ${tradingPriceContextSummary(riskContext, { compact: true })}`,
    };
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
  const sellableQuantity = Math.max(0, positionQuantity);
  const orderPriceNote = orderType === "limit"
    ? `限價單以你輸入的價格為準；目前 reference 價 ${formatTradingPointsValue(tradingMarketPricePoints(market, "reference"))} · ${tradingPriceContextSummary(referenceContext, { compact: true })}`
    : (riskGradePrice > 0
      ? `市價單估值採用風控級價格；${tradingPriceContextSummary(riskContext, { compact: true })}`
      : `市價單暫以 reference 價估值；${tradingPriceContextSummary(referenceContext, { compact: true })}`);
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
        ? `買入預估 ${formatTradingPointsValue(total)} 點${quantityNote}（含手續費 ${formatTradingPointsValue(fee)}），超過可用 ${formatTradingPointsValue(availablePoints)} 點 · ${orderPriceNote}`
        : `買入預估 ${formatTradingPointsValue(total)} 點${quantityNote}（成交 ${formatTradingPointsValue(notional)} + 手續費 ${formatTradingPointsValue(fee)}） · ${orderPriceNote}`,
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
      ? `賣出 ${formatTradingQuantityValue(quantity)} 超過可賣現貨 ${formatTradingQuantityValue(sellableQuantity)} · ${orderPriceNote}`
      : `賣出預估收入 ${formatTradingPointsValue(net)} 點${quantityNote}（成交 ${formatTradingPointsValue(notional)} - 手續費 ${formatTradingPointsValue(fee)}） · ${orderPriceNote}`,
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
  if (submitBtn) {
    submitBtn.setAttribute("aria-disabled", estimate.blocking ? "true" : "false");
    submitBtn.classList.toggle("is-soft-disabled", !!estimate.blocking);
  }
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
  const marketMap = new Map(markets.map((market) => [market.symbol, tradingMarketPricePoints(market, "reference")]));
  return positions.reduce((total, row) => {
    const quantity = Number(row.quantity || 0);
    const price = marketMap.get(row.market_symbol) || 0;
    if (!Number.isFinite(quantity) || !Number.isFinite(price)) return total;
    return total + (quantity * price);
  }, 0);
}

function rootVirtualMarginPositionEquity(marginSummary = {}, marginPositions = []) {
  const summaryEquity = Number(marginSummary.total_position_equity_points);
  if (Number.isFinite(summaryEquity)) return summaryEquity;
  return (marginPositions || [])
    .filter((row) => row?.status === "open")
    .reduce((total, row) => {
      const risk = row?.risk && typeof row.risk === "object" ? row.risk : {};
      const equity = Number(risk.equity_after_points ?? row.equity_after_points ?? 0);
      return Number.isFinite(equity) ? total + equity : total;
    }, 0);
}

function tradingPositionLabel(row) {
  return `${tradingDisplaySymbol(row.market_symbol)} ${formatTradingPointsValue(row.quantity || 0)}`;
}

function economySpotMarkets(markets = []) {
  return (markets || []).filter((market) => String(market?.quote_currency || "POINTS").toUpperCase() === "POINTS");
}

function spotPositionNumber(position, key) {
  return tradingNumber(position?.[key], 0);
}

function spotPositionTotalQuantity(position) {
  return spotPositionNumber(position, "quantity") + spotPositionNumber(position, "locked_quantity");
}

function tradingSpotBackendPnl(position) {
  return tradingNumber(position?.risk_grade_unrealized_pnl_points ?? position?.unrealized_pnl_points, 0);
}

function tradingSpotHasBackendPnl(position) {
  return !!position && (position.risk_grade_unrealized_pnl_points !== undefined || position.unrealized_pnl_points !== undefined);
}

function tradingSpotPnl(position, market) {
  if (tradingSpotHasBackendPnl(position) && !market) return tradingSpotBackendPnl(position);
  const quantity = spotPositionTotalQuantity(position);
  const costBasis = tradingSpotCostBasis(position, market, "risk_grade");
  const currentValue = tradingSpotRiskGradeValue(position, market);
  if (!quantity || !costBasis || !currentValue) {
    return tradingSpotHasBackendPnl(position) ? tradingSpotBackendPnl(position) : 0;
  }
  return currentValue - costBasis;
}

function tradingSpotFee(value, market, multiplier = 1) {
  const feeRate = tradingNumber(market?.fee_rate_percent, 0) * Number(multiplier || 1) / 100;
  return Math.max(0, Number(value || 0) * feeRate);
}

function tradingSpotHoldingCost(position, market) {
  const quantity = spotPositionTotalQuantity(position);
  const avgCost = spotPositionNumber(position, "avg_cost_points");
  if (!quantity || !avgCost) return 0;
  const buyNotional = quantity * avgCost;
  const buyFeeEstimate = tradingSpotFee(buyNotional, market);
  return buyNotional + buyFeeEstimate;
}

function tradingSpotHoldingCostPerUnit(position, market) {
  const quantity = spotPositionTotalQuantity(position);
  const holdingCost = tradingSpotHoldingCost(position, market);
  if (!quantity || !holdingCost) return 0;
  return holdingCost / quantity;
}

function tradingSpotBreakEvenExitPrice(position, market) {
  const quantity = spotPositionTotalQuantity(position);
  const holdingCost = tradingSpotHoldingCost(position, market);
  const feeRate = tradingNumber(market?.fee_rate_percent, 0) / 100;
  if (!quantity || !holdingCost || feeRate >= 1) return 0;
  return holdingCost / (quantity * (1 - feeRate));
}

function tradingSpotCurrentValue(position, market) {
  if (position && position.reference_current_value_points !== undefined && !market) {
    return tradingNumber(position.reference_current_value_points, tradingNumber(position.current_value_points, 0));
  }
  const quantity = spotPositionTotalQuantity(position);
  const currentPrice = tradingMarketPricePoints(market, "reference");
  if (quantity > 0 && currentPrice > 0) return quantity * currentPrice;
  return tradingNumber(position?.reference_current_value_points ?? position?.current_value_points, 0);
}

function tradingSpotCostBasis(position, market, priceType = "reference") {
  if (position && position.cost_basis_points !== undefined && !market) {
    return tradingNumber(position.cost_basis_points, 0);
  }
  const holdingCost = tradingSpotHoldingCost(position, market);
  const currentValue = priceType === "risk_grade"
    ? tradingSpotRiskGradeValue(position, market)
    : tradingSpotCurrentValue(position, market);
  const fallbackCostBasis = priceType === "risk_grade"
    ? position?.cost_basis_points
    : (position?.reference_cost_basis_points ?? position?.cost_basis_points);
  if (!holdingCost || !currentValue) return tradingNumber(fallbackCostBasis, 0);
  const sellFeeEstimate = tradingSpotFee(currentValue, market);
  return holdingCost + sellFeeEstimate;
}

function tradingSpotRiskGradeValue(position, market) {
  if (position && position.risk_grade_current_value_points !== undefined && !market) {
    return tradingNumber(position.risk_grade_current_value_points, 0);
  }
  const quantity = spotPositionTotalQuantity(position);
  const currentPrice = tradingMarketPricePoints(market, "risk_grade");
  if (quantity > 0 && currentPrice > 0) return quantity * currentPrice;
  return tradingNumber(position?.risk_grade_current_value_points ?? position?.current_value_points, 0);
}

const TRADING_POINT_MICRO_SCALE = 1000000;

function tradingMarginBillableInterestPoints(totalMicropoints) {
  const micro = Math.max(0, Math.round(tradingNumber(totalMicropoints, 0)));
  if (micro <= 0) return 0;
  return tradingMicropointsToSettlementPoints(micro);
}

function tradingMarginPositionIsShort(row) {
  const type = String(row?.position_type || "").toLowerCase();
  return type === "short" || type === "margin_short";
}

function tradingMarginInterestTiming(row) {
  return {
    intervalHours: Math.max(1, tradingNumber(row?.interest_interval_hours, 1)),
    minimumHours: Math.max(1, tradingNumber(row?.interest_minimum_hours, 1)),
  };
}

function tradingMarginOpenedAtMs(row) {
  const opened = row?.opened_at ? new Date(row.opened_at).getTime() : 0;
  return Number.isFinite(opened) ? opened : 0;
}

function tradingMarginBillableInterestHours(row, nowMs = Date.now()) {
  const principal = tradingNumber(row?.principal_points, 0);
  const ratePercentDaily = tradingNumber(row?.interest_percent_daily, 0);
  const openedAtMs = tradingMarginOpenedAtMs(row);
  if (!principal || ratePercentDaily <= 0 || !openedAtMs || nowMs <= openedAtMs) return 0;
  const { intervalHours, minimumHours } = tradingMarginInterestTiming(row);
  const elapsedSeconds = Math.max(0, (nowMs - openedAtMs) / 1000);
  if (!elapsedSeconds) return 0;
  const billedHours = Math.ceil(elapsedSeconds / (intervalHours * 3600)) * intervalHours;
  return Math.max(minimumHours, billedHours);
}

function tradingMarginLiveInterest(row, nowMs = Date.now()) {
  const principal = tradingNumber(row?.principal_points, 0);
  const ratePercentDaily = tradingNumber(row?.interest_percent_daily, 0);
  const capitalized = tradingNumber(row?.interest_capitalized_points ?? row?.interest_points, 0);
  const carryMicropoints = tradingNumber(row?.interest_carry_micropoints, 0);
  const accruedHours = tradingNumber(row?.interest_accrued_hours, 0);
  const totalHours = tradingMarginBillableInterestHours(row, nowMs);
  const dueHours = Math.max(0, totalHours - accruedHours);
  if (!principal || ratePercentDaily <= 0 || dueHours <= 0) {
    const exact = capitalized + (carryMicropoints / TRADING_POINT_MICRO_SCALE);
    return { points: capitalized + tradingMarginBillableInterestPoints(carryMicropoints), exactPoints: exact, totalHours, dueHours, totalMicropoints: carryMicropoints };
  }
  const hourlyRate = (ratePercentDaily / 100) / 24;
  const dueMicropoints = Math.round(principal * hourlyRate * dueHours * TRADING_POINT_MICRO_SCALE);
  const totalMicropoints = carryMicropoints + dueMicropoints;
  const duePoints = tradingMarginBillableInterestPoints(totalMicropoints);
  const points = capitalized + duePoints;
  const exactPoints = capitalized + (totalMicropoints / TRADING_POINT_MICRO_SCALE);
  return { points, exactPoints, totalHours, dueHours, totalMicropoints };
}

function tradingMarginNextInterestAtMs(row, nowMs = Date.now()) {
  const openedAtMs = tradingMarginOpenedAtMs(row);
  if (!openedAtMs) return 0;
  const { intervalHours } = tradingMarginInterestTiming(row);
  const accruedHours = tradingNumber(row?.interest_accrued_hours, 0);
  let nextBillingHours = tradingMarginBillableInterestHours(row, nowMs);
  if (nextBillingHours && nextBillingHours <= accruedHours) {
    nextBillingHours = accruedHours + intervalHours;
  }
  return nextBillingHours > 0 ? openedAtMs + (nextBillingHours * 3600 * 1000) : 0;
}

function tradingMarginBreakEvenPrice(row, interestExactPoints, market = null) {
  const resolvedMarket = market || tradingMarketBySymbol(row?.market_symbol || "");
  const quantity = tradingNumber(row?.quantity, 0);
  const principal = tradingNumber(row?.principal_points, 0);
  const collateral = tradingNumber(row?.collateral_points, 0);
  const openFee = tradingNumber(row?.open_fee_points, 0);
  const feeRate = tradingNumber(resolvedMarket?.fee_rate_percent, 0) / 100;
  if (!resolvedMarket || !quantity || feeRate < 0 || feeRate >= 1) return 0;
  if (tradingMarginPositionIsShort(row)) {
    const recoverableValue = principal - openFee - interestExactPoints;
    if (recoverableValue <= 0) return 0;
    return recoverableValue / (quantity * (1 + feeRate));
  }
  const requiredExitValue = collateral + principal + openFee + interestExactPoints;
  return requiredExitValue > 0 ? requiredExitValue / (quantity * (1 - feeRate)) : 0;
}

function tradingLiveMarginRisk(row, market = null) {
  const fallback = row?.risk && typeof row.risk === "object" ? row.risk : {};
  const resolvedMarket = market || tradingMarketBySymbol(row?.market_symbol || "");
  if (!row || !resolvedMarket) return fallback;
  const quantity = tradingNumber(row.quantity, 0);
  const riskContext = tradingMarketPriceContext(resolvedMarket, "risk_grade");
  const currentPrice = tradingMarketPricePoints(resolvedMarket, "risk_grade") || tradingNumber(fallback.price_points, 0);
  const principal = tradingNumber(row.principal_points, 0);
  const collateral = tradingNumber(row.collateral_points, 0);
  const dynamicInterest = tradingMarginLiveInterest(row);
  const interest = tradingNumber(dynamicInterest.points, tradingNumber(fallback.interest_points, 0));
  const interestExact = tradingNumber(dynamicInterest.exactPoints, tradingNumber(fallback.interest_exact_points ?? fallback.interest_points, 0));
  const feeRatePercent = tradingNumber(resolvedMarket.fee_rate_percent, 0);
  const maintenancePercent = tradingNumber(tradingState.settings?.margin_maintenance_percent, tradingNumber(fallback.maintenance_percent, 0));
  const exitNotional = quantity > 0 && currentPrice > 0 ? Math.ceil(quantity * currentPrice) : tradingNumber(fallback.exit_notional_points, 0);
  const openFeeMicropoints = tradingNumber(row.open_fee_micropoints, tradingNumber(row.open_fee_points, 0) * TRADING_POINT_MICRO_SCALE);
  const closeFeeMicropoints = tradingFeeMicropoints(exitNotional, feeRatePercent);
  const closeFee = tradingMicropointsToSettlementPoints(openFeeMicropoints + closeFeeMicropoints);
  const isShort = tradingMarginPositionIsShort(row);
  const equityAfter = isShort
    ? (collateral + principal - exitNotional - interest - closeFee)
    : (exitNotional - principal - interest - closeFee);
  const delta = isShort
    ? (principal - exitNotional - interest - closeFee)
    : (equityAfter - collateral);
  const maintenancePoints = Math.max(0, Math.ceil(exitNotional * maintenancePercent / 100));
  const breakEvenPrice = tradingMarginBreakEvenPrice(row, interestExact, resolvedMarket);
  let liquidationPrice = 0;
  const quantityUnits = quantity * 100000000;
  if (quantityUnits > 0) {
    if (isShort) {
      const denominatorPercent = 100 + feeRatePercent + maintenancePercent;
      const liquidationBase = collateral + principal - interest;
      if (denominatorPercent > 0 && liquidationBase > 0) {
        liquidationPrice = (Math.ceil((liquidationBase * 100) / denominatorPercent) * 100000000) / quantityUnits;
      }
    } else {
      const denominatorPercent = 100 - feeRatePercent - maintenancePercent;
      if (denominatorPercent > 0) {
        liquidationPrice = (Math.ceil(((principal + interest) * 100) / denominatorPercent) * 100000000) / quantityUnits;
      }
    }
  }
  const maintenanceRatioPercent = maintenancePoints > 0
    ? Math.round((equityAfter * 10000) / maintenancePoints) / 100
    : tradingNumber(fallback.maintenance_ratio_percent, 0);
  let riskStatus = "normal";
  let riskReason = isShort
    ? "借券放空在價格上漲時會虧損，價格越高維持率越低"
    : "融資做多在價格下跌時會虧損，價格越低維持率越低";
  if (equityAfter <= maintenancePoints) {
    riskStatus = "liquidation";
    riskReason = "權益已低於維持保證金，會被列入強制平倉";
  } else if (maintenanceRatioPercent < 150) {
    riskStatus = "warning";
    riskReason = "整體維持率偏低，建議補保證金或降低倉位";
  } else if (isShort) {
    riskStatus = "short_price_risk";
  }
  const withdrawEstimate = tradingMarginWithdrawEstimate(row, {
    collateral_points: collateral,
    initial_margin_points: collateral,
    unrealized_pnl_points: delta,
    delta_points: delta,
    equity_after_points: equityAfter,
    maintenance_points: maintenancePoints,
    maintenance_margin_points: maintenancePoints,
  });
  return {
    ...fallback,
    price_points: currentPrice,
    price_context: riskContext,
    close_fee_points: closeFee,
    exit_notional_points: exitNotional,
    interest_points: interest,
    interest_exact_points: interestExact,
    interest_total_hours: dynamicInterest.totalHours,
    equity_after_points: equityAfter,
    unrealized_pnl_points: delta,
    delta_points: delta,
    breakeven_price_points: breakEvenPrice,
    maintenance_percent: maintenancePercent,
    maintenance_points: maintenancePoints,
    maintenance_margin_percent: maintenancePercent,
    maintenance_margin_points: maintenancePoints,
    liquidation_price_points: liquidationPrice || tradingNumber(fallback.liquidation_price_points, 0),
    maintenance_ratio_percent: maintenanceRatioPercent,
    risk_status: riskStatus,
    risk_reason: riskReason,
    liquidation_required: equityAfter <= maintenancePoints,
    max_withdrawable_collateral_points: withdrawEstimate.maxWithdrawable,
    withdrawable_collateral_points: withdrawEstimate.maxWithdrawable,
    withdrawable_collateral_reason: withdrawEstimate.reason,
    withdrawable_collateral_after_ratio_percent: withdrawEstimate.afterRatio,
  };
}

function tradingMarginWithdrawEstimate(row, liveRisk = null) {
  const risk = liveRisk || tradingLiveMarginRisk(row);
  const backendMax = Number(risk?.max_withdrawable_collateral_points);
  const collateral = Math.floor(tradingNumber(
    risk?.collateral_points ?? risk?.initial_margin_points ?? row?.collateral_points ?? row?.initial_margin_points,
    0
  ));
  const profitableSurplus = Math.max(0, Math.floor(tradingNumber(
    risk?.unrealized_pnl_points ?? risk?.delta_points ?? row?.unrealized_pnl_points,
    0
  )));
  const equity = Math.floor(tradingNumber(risk?.equity_after_points ?? row?.equity_after_points, 0));
  const maintenance = Math.max(0, Math.ceil(tradingNumber(
    risk?.maintenance_margin_points ?? risk?.maintenance_points ?? row?.maintenance_margin_points ?? row?.maintenance_points,
    0
  )));
  const collateralCap = Math.max(0, collateral - 1);
  const maintenanceCap = Math.max(0, equity - maintenance - 1);
  const fallbackMax = Math.max(0, Math.min(collateralCap, profitableSurplus, maintenanceCap));
  const maxWithdrawable = Number.isFinite(backendMax)
    ? Math.max(0, Math.floor(backendMax))
    : fallbackMax;
  const afterEquity = equity - maxWithdrawable;
  const afterRatio = maintenance > 0 && maxWithdrawable > 0
    ? Math.round((afterEquity * 10000) / maintenance) / 100
    : null;
  let reason = "後端仍會用最新風控價、利息與維持率重算";
  if (collateralCap <= 0) reason = "保證金已接近最低保留額，暫不可抽出";
  else if (profitableSurplus <= 0) reason = "目前沒有可抽出的未實現盈利";
  else if (maintenanceCap <= 0) reason = "抽出後會接近或低於維持保證金，暫不可抽出";
  return {
    maxWithdrawable,
    afterRatio,
    reason,
    collateralCap,
    profitableSurplus,
    maintenanceCap,
  };
}

function tradingMarginPositionByUuid(positionUuid) {
  const target = String(positionUuid || "");
  return (tradingState.marginPositions || []).find((row) => String(row.position_uuid || "") === target) || null;
}

function tradingLiveMarginFreeMarginPoints() {
  const fundingAvailable = Number(tradingState.funding?.available_points);
  if (Number.isFinite(fundingAvailable)) return Math.max(0, fundingAvailable);
  const summaryFreeMargin = Number(tradingState.marginSummary?.free_margin_points);
  if (Number.isFinite(summaryFreeMargin)) return Math.max(0, summaryFreeMargin);
  const walletAvailable = Number(tradingState.funding?.wallet_available_points);
  const trialAvailable = Number(tradingState.funding?.trial_credit?.available_points);
  const combined = (Number.isFinite(walletAvailable) ? walletAvailable : 0)
    + (Number.isFinite(trialAvailable) ? trialAvailable : 0);
  return Math.max(0, combined);
}

function tradingLiveMarginSummary(rows = []) {
  const openRows = rows.filter((row) => row.status === "open");
  if (!openRows.length) return { open_count: 0 };
  let totalPositionEquity = 0;
  let totalBorrowed = 0;
  let totalMaintenance = 0;
  openRows.forEach((row) => {
    const risk = tradingLiveMarginRisk(row);
    totalPositionEquity += tradingNumber(risk.equity_after_points, 0);
    totalBorrowed += tradingNumber(row.principal_points, 0);
    totalMaintenance += tradingNumber(risk.maintenance_margin_points ?? risk.maintenance_points, 0);
  });
  const freeMargin = tradingLiveMarginFreeMarginPoints();
  const accountEquity = totalPositionEquity + freeMargin;
  const availableMargin = accountEquity - totalMaintenance;
  const ratio = totalMaintenance > 0 ? Math.round((accountEquity * 10000) / totalMaintenance) / 100 : null;
  let reason = "整戶維持率正常";
  if (ratio !== null && ratio <= 100) reason = "整戶維持率已低於強平門檻";
  else if (ratio !== null && ratio < 150) reason = "整戶維持率偏低";
  return {
    open_count: openRows.length,
    cross_margin_ratio_percent: ratio,
    maintenance_ratio_percent: ratio,
    account_equity_points: accountEquity,
    total_position_equity_points: totalPositionEquity,
    free_margin_points: freeMargin,
    available_margin_points: availableMargin,
    total_borrowed_points: totalBorrowed,
    total_maintenance_requirement_points: totalMaintenance,
    total_maintenance_points: totalMaintenance,
    reason,
  };
}

function tradingDisplayedMarginSummary(summary = null, rows = null) {
  const marginRows = Array.isArray(rows) ? rows : (tradingState.marginPositions || []);
  const hasOpenMargin = marginRows.some((row) => row.status === "open");
  if (!hasOpenMargin) {
    return summary && typeof summary === "object" && Object.keys(summary).length ? summary : { open_count: 0 };
  }
  return tradingLiveMarginSummary(marginRows);
}

function refreshTradingWalletLiveMetrics() {
  const liveMarginSummary = tradingLiveMarginSummary(tradingState.marginPositions || []);
  renderEconomySpotPositionDetails(tradingState.positions || [], tradingState.markets || []);
  renderEconomyMarginPositionDetails(tradingState.marginPositions || []);
  renderTradingMarginPositions(tradingState.marginPositions || []);
  renderTradingMarginAccountSummary(liveMarginSummary);
  renderTradingWalletSummary({
    positions: tradingState.positions || [],
    futures_positions: [],
    margin_positions: tradingState.marginPositions || [],
    orders: tradingState.orders || [],
    fills: tradingState.fills || [],
    markets: tradingState.markets || [],
    funding: tradingState.funding || {},
    state: tradingState.state || {},
    margin_summary: liveMarginSummary,
  });
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
    const referenceContext = tradingMarketPriceContext(market, "reference");
    const riskContext = tradingMarketPriceContext(market, "risk_grade");
    const currentPrice = tradingMarketPricePoints(market, "reference");
    const holdingCost = tradingSpotHoldingCost(position, market);
    const holdingCostPerUnit = tradingSpotHoldingCostPerUnit(position, market);
    const breakEvenPrice = tradingSpotBreakEvenExitPrice(position, market);
    const costBasis = tradingSpotCostBasis(position, market);
    const currentValue = tradingSpotCurrentValue(position, market);
    const pnl = tradingSpotPnl(position, market);
    const realizedPnl = tradingNumber(position?.realized_pnl_points, 0);
    const totalFee = tradingNumber(position?.total_fee_points, 0);
    const stopLossPercent = tradingNumber(position?.stop_loss_percent, 0);
    const takeProfitPercent = tradingNumber(position?.take_profit_percent, 0);
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
          <span>持有成本</span>
          <b>${holdingCost ? formatTradingPointsValue(holdingCost) : "-"}</b>
          <small class="drive-card-sub">${holdingCostPerUnit ? `單顆 ${formatTradingPointsValue(holdingCostPerUnit)} 點` : "含買入手續費"}</small>
        </div>
        <div class="trading-spot-metric">
          <span>損益平均價格</span>
          <b>${breakEvenPrice ? formatTradingPointsValue(breakEvenPrice) : "-"}</b>
          <small class="drive-card-sub">已含預估賣出手續費</small>
        </div>
        <div class="trading-spot-metric">
          <span>目前部位價值</span>
          <b>${currentValue ? formatTradingPointsValue(currentValue) : "-"}</b>
          <small class="drive-card-sub">reference 價 ${currentPrice ? formatTradingPointsValue(currentPrice) : "-"} · ${sanitize(tradingPriceContextSummary(referenceContext, { compact: true }))}</small>
        </div>
        <div class="trading-spot-metric">
          <span>盈虧</span>
          <b class="trading-spot-pnl ${pnlClass}">${pnl >= 0 ? "+" : ""}${formatTradingPointsValue(pnl)} 點</b>
          <small class="drive-card-sub">risk-grade 價計算未實現盈虧 · ${sanitize(tradingPriceContextSummary(riskContext, { compact: true }))}</small>
        </div>
        <div class="trading-spot-metric">
          <span>已實現盈虧</span>
          <b class="trading-spot-pnl ${realizedClass}">${realizedPnl >= 0 ? "+" : ""}${formatTradingPointsValue(realizedPnl)} 點</b>
          <small class="drive-card-sub">累計手續費 ${formatTradingPointsValue(totalFee)} · 扣費成本基準 ${costBasis ? formatTradingPointsValue(costBasis) : "-"} · ${sanitize(tradingRiskTargetText(stopLossPercent, takeProfitPercent))}</small>
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
  list.querySelectorAll("[data-economy-margin-withdraw-collateral]").forEach((btn) => {
    bindTradingActionButton(btn, () => withdrawTradingMarginCollateral(btn.dataset.economyMarginWithdrawCollateral || "", "economy"), "正在抽出保證金...", "抽出保證金失敗");
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
  const liveRisk = tradingLiveMarginRisk(row);
  const isShort = tradingMarginPositionIsShort(row);
  const typeLabel = row.position_label || (isShort ? "借券放空" : "融資買入");
  const principal = tradingNumber(row.principal_points, 0);
  const collateral = tradingNumber(liveRisk.initial_margin_points ?? row.initial_margin_points ?? row.collateral_points, 0);
  const fee = tradingNumber(row.open_fee_points, 0);
  const interest = tradingNumber(liveRisk.interest_exact_points ?? row.interest_exact_points ?? row.interest_points, 0);
  const paidInterest = tradingNumber(row.interest_paid_points, 0);
  const interestHours = tradingNumber(liveRisk.interest_total_hours ?? row.interest_accrued_hours, 0);
  const totalElapsedHours = tradingMarginOpenedAtMs(row) ? Math.max(0, Math.floor((Date.now() - tradingMarginOpenedAtMs(row)) / 3600000)) : tradingNumber(row.total_elapsed_hours, 0);
  const interestAprPercent = tradingNumber(row.interest_apr_percent ?? ((tradingNumber(row.interest_percent_daily, 0) || 0) * 365), 0);
  const interestIntervalHours = tradingNumber(row.interest_interval_hours, 1);
  const minimumHours = tradingNumber(row.interest_minimum_hours, 1);
  const nextInterestAt = tradingMarginNextInterestAtMs(row);
  const nextInterestCountdown = (nextInterestAt && nextInterestAt > Date.now())
    ? `下次計息 ${formatTradingDuration(nextInterestAt - Date.now())} 後`
    : (totalElapsedHours > 0 ? "下次計息即將觸發" : "");
  const nextInterestLabel = nextInterestAt
    ? new Date(nextInterestAt).toLocaleString()
    : "尚未開始計息";
  const entry = tradingNumber(row.entry_price_points, 0);
  const currentPrice = tradingNumber(liveRisk.price_points ?? row.current_price_points, 0);
  const riskContext = liveRisk.price_context || tradingMarketPriceContext(tradingMarketBySymbol(row.market_symbol || ""), "risk_grade");
  const equity = tradingNumber(liveRisk.equity_after_points ?? row.equity_after_points, 0);
  const maintenance = tradingNumber(liveRisk.maintenance_margin_points ?? liveRisk.maintenance_points ?? row.maintenance_margin_points ?? row.maintenance_points, 0);
  const initialMarginRatePercent = tradingNumber(liveRisk.initial_margin_percent ?? row.initial_margin_percent, 0);
  const maintenanceRatePercent = tradingNumber(liveRisk.maintenance_margin_percent ?? liveRisk.maintenance_percent ?? row.maintenance_margin_percent, 0);
  const unrealizedPnl = tradingNumber(liveRisk.unrealized_pnl_points ?? row.unrealized_pnl_points, 0);
  const breakEvenPrice = tradingNumber(liveRisk.breakeven_price_points ?? row.breakeven_price_points, 0);
  const liquidationPrice = tradingNumber(liveRisk.liquidation_price_points ?? row.liquidation_price_points, 0);
  const pnlClass = unrealizedPnl > 0 ? "positive" : (unrealizedPnl < 0 ? "negative" : "");
  const leverageHint = collateral > 0 ? `${(principal / collateral).toFixed(2)}x 風險倍數` : "未提供風險倍數";
  const riskText = tradingMarginRiskText({ ...row, risk: liveRisk });
  const riskTargetText = tradingRiskTargetText(row.stop_loss_percent, row.take_profit_percent);
  const withdrawEstimate = tradingMarginWithdrawEstimate(row, liveRisk);
  const withdrawHint = withdrawEstimate.maxWithdrawable > 0
    ? `預估可抽出 ${formatTradingPointsValue(withdrawEstimate.maxWithdrawable)} 點；若全數抽出，維持率約 ${withdrawEstimate.afterRatio == null ? "無法估算" : `${formatTradingPointsValue(withdrawEstimate.afterRatio)}%`}`
    : `預估可抽出 0 點；${withdrawEstimate.reason}`;
  const withdrawDisabledAttr = withdrawEstimate.maxWithdrawable > 0 ? "" : " disabled";
  const prefix = scope === "economy" ? "economy-" : "";
  return `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(typeLabel)} · ${sanitize(tradingDisplaySymbol(row.market_symbol || "-"))} · ${sanitize(row.quantity || "0")}</strong>
        <div class="drive-card-sub">
          入場 ${formatTradingPointsValue(entry)} · 現價 ${currentPrice ? formatTradingPointsValue(currentPrice) : "-"} · 本金 ${formatTradingPointsValue(principal)} · 原始保證金 ${formatTradingPointsValue(collateral)}
        </div>
        <div class="drive-card-sub">風控級價格用途：融資 / 強平 / 保證金 / PnL · ${sanitize(tradingPriceContextSummary(riskContext, { compact: true }))}</div>
        <div class="drive-card-sub">
          原始保證金率 ${formatTradingPointsValue(initialMarginRatePercent)}% · 維持率 ${sanitize(riskText.ratioText)} · 權益 ${formatTradingPointsValue(equity)} · 維持保證金 ${formatTradingPointsValue(maintenance)}（${formatTradingPointsValue(maintenanceRatePercent)}%） · ${sanitize(riskText.statusLabel)}
        </div>
        <div class="drive-card-sub">
          未實現盈虧 <b class="trading-spot-pnl ${pnlClass}">${unrealizedPnl >= 0 ? "+" : ""}${formatTradingPointsValue(unrealizedPnl)} 點</b> · 損益平衡價 ${breakEvenPrice ? formatTradingPointsValue(breakEvenPrice) : "無法估算"} · 逐倉估算強平價 ${liquidationPrice ? formatTradingPointsValue(liquidationPrice) : "無法估算"}
        </div>
        <div class="drive-card-sub">損益平衡價已含開倉費、累積利息與預估平倉手續費；實際清算仍依全倉維持率</div>
        <div class="drive-card-sub">${sanitize(riskTargetText)}</div>
        <div class="drive-card-sub">${sanitize(riskText.reason || "")}</div>
        <div class="drive-card-sub">開倉費 ${formatTradingPointsValue(fee)} · 年利率 ${formatTradingPercent(interestAprPercent)}% APR · 累積利息 ${formatTradingPointsValue(interest)} 點 · 已實扣 ${formatTradingPointsValue(paidInterest)} 點 · 已持倉 ${totalElapsedHours} 小時 · 已計息 ${interestHours} 小時</div>
        <div class="drive-card-sub">下一次計息 ${sanitize(nextInterestLabel)}${nextInterestCountdown ? ` · ${sanitize(nextInterestCountdown)}` : ""} · 規則：每 ${formatTradingPointsValue(interestIntervalHours)} 小時、至少 ${formatTradingPointsValue(minimumHours)} 小時 · ${sanitize(leverageHint)}</div>
        <div class="economy-ledger-hash">${sanitize(row.position_uuid || "")}</div>
      </div>
      <div class="trading-spot-actions">
        <div class="field">
          <label>補保證金</label>
          <input type="number" min="1" step="1" placeholder="點數" data-${prefix}margin-collateral-amount="${sanitize(row.position_uuid || "")}" />
        </div>
        <button class="btn" type="button" data-${prefix}margin-add-collateral="${sanitize(row.position_uuid || "")}">補保證金</button>
        <div class="field">
          <label>抽出保證金</label>
          <input type="number" min="1" step="1" max="${sanitize(withdrawEstimate.maxWithdrawable)}" placeholder="${sanitize(withdrawEstimate.maxWithdrawable > 0 ? `${formatTradingPointsValue(withdrawEstimate.maxWithdrawable)} 點內` : "暫不可抽出")}" data-${prefix}margin-withdraw-collateral-amount="${sanitize(row.position_uuid || "")}" />
          <div class="field-hint">${sanitize(withdrawHint)}。此為提示，實際送出仍以後端最新風控價格為準。</div>
        </div>
        <button class="btn" type="button" data-${prefix}margin-withdraw-collateral="${sanitize(row.position_uuid || "")}"${withdrawDisabledAttr}>抽出保證金</button>
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
  const botSelects = [$("trading-auto-bot-market"), $("trading-dca-bot-market"), $("trading-grid-bot-market")];
  const botBacktestSelects = [$("trading-dca-backtest-market"), $("trading-grid-backtest-market"), $("trading-workflow-backtest-market")];
  const options = tradingState.markets.length
    ? tradingState.markets.map((market) => `<option value="${sanitize(market.symbol)}">${sanitize(tradingDisplaySymbol(market.symbol))}</option>`).join("")
    : `<option value="">沒有可用市場</option>`;
  const botMarkets = (tradingState.markets || []).filter((market) => market.allow_bots !== false);
  const botOptions = botMarkets.length
    ? botMarkets.map((market) => `<option value="${sanitize(market.symbol)}">${sanitize(tradingDisplaySymbol(market.symbol))}</option>`).join("")
    : `<option value="">目前沒有開放機器人的市場</option>`;
  [select, rootSelect, contractSelect, marginSelect, ...botBacktestSelects].forEach((target) => {
    if (!target) return;
    const previous = target.value;
    target.innerHTML = options;
    if (previous && Array.from(target.options).some((option) => option.value === previous)) target.value = previous;
  });
  botSelects.forEach((target) => {
    if (!target) return;
    const previous = target.value;
    target.innerHTML = botOptions;
    if (previous && Array.from(target.options).some((option) => option.value === previous)) target.value = previous;
  });
}

function tradingReadinessClass(state) {
  if (state === "bad") return "trading-readiness-bad";
  if (state === "warn") return "trading-readiness-warn";
  return "trading-readiness-ok";
}

function tradingWorstReadinessState(states = []) {
  if (states.includes("bad")) return "bad";
  if (states.includes("warn")) return "warn";
  if (states.includes("ok")) return "ok";
  return "unknown";
}

function tradingSignalStateLabel(state) {
  if (state === "bad") return "阻擋";
  if (state === "warn") return "觀察";
  if (state === "ok") return "正常";
  return "未讀取";
}

function updateTradingSignalLight(id, state, label, detail) {
  const el = $(id);
  if (!el) return;
  const normalized = state === "bad" || state === "warn" || state === "ok" ? state : "unknown";
  el.dataset.state = normalized;
  el.title = `${label}：${tradingSignalStateLabel(normalized)}${detail ? ` · ${detail}` : ""}`;
  el.setAttribute("aria-label", el.title);
}

function tradingMarketBootSummary() {
  const liveMarkets = (tradingState.markets || []).filter((market) => market.live_price_enabled !== false);
  const liveMeta = tradingState.livePriceMeta || {};
  let ready = 0;
  let warming = 0;
  let pending = 0;
  let degraded = 0;
  liveMarkets.forEach((market) => {
    const meta = liveMeta[market.symbol] || {};
    const health = String(meta.price_health || market.price_health || "").trim();
    if (health === "boot_pending") {
      pending += 1;
      return;
    }
    if (health === "fallback" || health === "degraded" || health === "conservative" || meta.high_risk_blocked || meta.risk_grade_price_context?.risk_grade_usable === false) {
      degraded += 1;
    }
    if (market.live_price_confirmed_at) ready += 1;
    else if (market.live_price_warmup_started_at) warming += 1;
    else pending += 1;
  });
  return {
    total: liveMarkets.length,
    ready,
    warming,
    pending,
    degraded,
    state: pending > 0 || degraded > 0 ? "warn" : "ok",
  };
}

function tradingSelectedPriceReadiness(market) {
  if (!market) return { state: "warn", value: "no market", detail: "尚未選擇市場" };
  const symbol = market.symbol;
  const meta = (tradingState.livePriceMeta || {})[symbol] || {};
  const referenceContext = tradingMarketPriceContext(market, "reference");
  const riskContext = tradingMarketPriceContext(market, "risk_grade");
  const health = String(meta.price_health || referenceContext?.health || "healthy").trim();
  const providerCount = Number(meta.provider_count ?? riskContext?.provider_count ?? 0);
  const minimum = Number(meta.minimum_provider_count ?? riskContext?.minimum_provider_count ?? 0);
  const reason = meta.fallback_reason || meta.high_risk_block_reason || riskContext?.warning_message || referenceContext?.warning_message || "";
  let state = "ok";
  if (health === "boot_pending" || health === "fallback" || health === "degraded" || health === "conservative" || riskContext?.risk_grade_usable === false) {
    state = health === "boot_pending" ? "warn" : "bad";
  }
  return {
    state,
    value: health === "boot_pending" ? "boot pending" : (riskContext?.risk_grade_usable === false ? "risk paused" : health),
    detail: `${tradingDisplaySymbol(symbol)} · provider ${providerCount || 0}/${minimum || 0}${reason ? ` · ${reason}` : ""}`,
  };
}

function renderTradingRiskDashboard() {
  const grid = $("trading-risk-dashboard-grid");
  if (!grid) return;
  const market = selectedTradingMarket();
  const boot = tradingMarketBootSummary();
  const selectedPrice = tradingSelectedPriceReadiness(market);
  const funding = tradingState.funding || {};
  const trial = funding.trial_credit || null;
  const fundingPool = tradingState.fundingPool || {};
  const settings = tradingState.settings || {};
  const bots = tradingState.bots || [];
  const enabledBots = bots.filter((bot) => bot.enabled);
  const runnableBots = enabledBots.filter((bot) => bot.can_run !== false);
  const botMarkets = (tradingState.markets || []).filter((row) => row.allow_bots !== false);
  const marginSummary = tradingDisplayedMarginSummary(tradingState.marginSummary);
  const openMargins = (tradingState.marginPositions || []).filter((row) => row.status === "open");
  const reserve = tradingState.rootReport?.reserve_pool || null;
  const reserveBalance = reserve ? Number(reserve.balance_points || 0) : Number(fundingPool.available_points || 0);
  const botState = boot.pending > 0 || boot.degraded > 0 ? "warn" : (enabledBots.length && runnableBots.length === 0 ? "warn" : "ok");
  const trialState = trial?.pending_reclaim ? "warn" : (trial && trial.status !== "active" ? "warn" : "ok");
  const marginRatio = marginSummary.cross_margin_ratio_percent ?? marginSummary.maintenance_ratio_percent;
  const marginState = !settings.borrowing_enabled ? "warn" : (marginRatio != null && Number(marginRatio) < Number(settings.margin_maintenance_percent || 0) ? "bad" : "ok");
  const priceItem = {
    label: "價格健康",
    value: selectedPrice.value,
    detail: selectedPrice.detail,
    state: selectedPrice.state,
  };
  const liveGateItem = {
    label: "Live price gate",
    value: `${boot.ready}/${boot.total || 0} ready`,
    detail: `boot pending ${boot.pending} · warming ${boot.warming} · degraded ${boot.degraded}`,
    state: boot.state,
  };
  const botItem = {
    label: "Bot / backtest",
    value: `${runnableBots.length}/${enabledBots.length} runnable`,
    detail: `可用 bot 市場 ${botMarkets.length} · 回測上限 ${Number(settings.backtest_max_candles || 0).toLocaleString()} candles`,
    state: botState,
  };
  const reserveItem = {
    label: currentUser === "root" ? "Reserve / pool" : "Funding pool",
    value: `${formatTradingPointsValue(reserveBalance)} POINTS`,
    detail: reserve
      ? `root reserve · events ${(tradingState.rootReport?.reserve_events || []).length}`
      : `借出 ${formatTradingPointsValue(fundingPool.outstanding_principal_points || 0)} · 使用率 ${formatTradingPercent(fundingPool.utilization_percent || 0)}%`,
    state: reserveBalance > 0 ? "ok" : "warn",
  };
  const trialItem = {
    label: "Trial credit",
    value: trial ? String(trial.status || "unknown") : "root / none",
    detail: trial
      ? `可用 ${formatTradingPointsValue(trial.available_points || 0)} · 鎖定 ${formatTradingPointsValue(trial.locked_points || 0)}${trial.reclaim_blocked_reason ? ` · ${trial.reclaim_blocked_reason}` : ""}`
      : "root 不使用體驗金",
    state: trialState,
  };
  const marginItem = {
    label: "Margin / lending",
    value: settings.borrowing_enabled ? `${openMargins.length} open` : "disabled",
    detail: settings.borrowing_enabled
      ? `強平 ${settings.margin_liquidation_enabled ? "on" : "off"} · 維持率 ${marginRatio == null ? "-" : `${formatTradingPointsValue(marginRatio)}%`} · pool ${formatTradingPercent(fundingPool.utilization_percent || 0)}%`
      : "root 尚未開啟借貸交易",
    state: marginState,
  };
  const items = [priceItem, liveGateItem, botItem, reserveItem, trialItem, marginItem];
  const priceState = tradingWorstReadinessState([priceItem.state, liveGateItem.state]);
  const riskState = tradingWorstReadinessState([reserveItem.state, trialItem.state, marginItem.state]);
  updateTradingSignalLight("trading-signal-light-price", priceState, "價格訊號", `${priceItem.value} · ${liveGateItem.value}`);
  updateTradingSignalLight("trading-signal-light-bot", botItem.state, "Bot 訊號", `${botItem.value} · ${botItem.detail}`);
  updateTradingSignalLight("trading-signal-light-risk", riskState, "風控訊號", `${reserveItem.value} · ${marginItem.value}`);
  grid.innerHTML = items.map((item) => `
    <div class="trading-readiness-item ${tradingReadinessClass(item.state)}">
      <span>${sanitize(item.label)}</span>
      <strong>${sanitize(item.value)}</strong>
      <small>${sanitize(item.detail)}</small>
    </div>
  `).join("");
  const badge = $("trading-risk-dashboard-badge");
  const sub = $("trading-risk-dashboard-sub");
  const badCount = items.filter((item) => item.state === "bad").length;
  const warnCount = items.filter((item) => item.state === "warn").length;
  const dashboard = $("trading-risk-dashboard");
  if (dashboard) dashboard.dataset.state = tradingWorstReadinessState(items.map((item) => item.state));
  if (badge) badge.textContent = badCount ? `${badCount} 阻擋` : (warnCount ? `${warnCount} 觀察` : "正常");
  if (sub) sub.textContent = `價格 ${tradingSignalStateLabel(priceState)} · Bot ${tradingSignalStateLabel(botItem.state)} · 風控 ${tradingSignalStateLabel(riskState)}；滑鼠移過查看細節`;
}

function renderTradingSummary() {
  const market = selectedTradingMarket();
  const funding = tradingState.funding || {};
  const orderForm = $("trading-order-form");
  const submitBtn = $("trading-submit-order-btn");
  const availabilityNote = $("trading-availability-note");
  const contractCard = $("trading-root-contract-card");
  const marginCard = $("trading-margin-card");
  const marginOpenForm = $("trading-margin-open-form");
  const marginEstimate = $("trading-margin-estimate");
  const fundingPoolCard = $("trading-funding-pool-public");
  if (orderForm) orderForm.style.display = "";
  if (submitBtn) submitBtn.disabled = false;
  if (contractCard) contractCard.style.display = currentUser === "root" ? "" : "none";
  const borrowingEnabled = !!tradingState.settings?.borrowing_enabled;
  const openMarginCount = (tradingState.marginPositions || []).filter((row) => row.status === "open").length;
  const showMarginCard = borrowingEnabled || openMarginCount > 0;
  if (marginCard) marginCard.style.display = showMarginCard ? "" : "none";
  if (marginOpenForm) marginOpenForm.style.display = borrowingEnabled ? "" : "none";
  if (marginEstimate) marginEstimate.style.display = borrowingEnabled ? "" : "none";
  if (fundingPoolCard) fundingPoolCard.style.display = borrowingEnabled ? "" : "none";
  const marginControlsDisabled = !borrowingEnabled;
  ["trading-margin-market-select", "trading-margin-type", "trading-margin-quantity", "trading-margin-collateral", "trading-margin-stop-loss-percent", "trading-margin-take-profit-percent", "trading-margin-open-btn"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = marginControlsDisabled;
  });
  if ($("trading-margin-note")) {
    const timing = tradingBorrowTimingSummary();
    const cryptoApr = tradingBorrowEffectiveAprPercent("btc_eth");
    const stableApr = tradingBorrowEffectiveAprPercent("usdt_points");
    $("trading-margin-note").textContent = borrowingEnabled
      ? (currentUser === "root"
        ? `root 可用模擬資金進行融資 / 借券；BTC/ETH 約 ${formatTradingPercent(cryptoApr)}% APR，USDT/POINTS 約 ${formatTradingPercent(stableApr)}% APR；${timing.text}；不寫入 PointsChain。`
        : `已開啟；BTC/ETH 約 ${formatTradingPercent(cryptoApr)}% APR，USDT/POINTS 約 ${formatTradingPercent(stableApr)}% APR；${timing.text}；本金由資金池借出，手續費與利息回到資金池。`)
      : "root 尚未開啟借貸交易，目前僅可查看此區。";
  }
  const fundingPool = tradingState.fundingPool || {};
  if ($("trading-funding-pool-available")) $("trading-funding-pool-available").textContent = formatTradingPointsValue(fundingPool.available_points);
  if ($("trading-funding-pool-outstanding")) $("trading-funding-pool-outstanding").textContent = formatTradingPointsValue(fundingPool.outstanding_principal_points);
  if ($("trading-funding-pool-utilization")) $("trading-funding-pool-utilization").textContent = formatTradingPercent(fundingPool.utilization_percent);
  if ($("trading-funding-pool-rate-btc-eth")) $("trading-funding-pool-rate-btc-eth").textContent = formatTradingPercent(tradingBorrowEffectiveAprPercent("btc_eth"));
  if ($("trading-funding-pool-rate-usdt-points")) $("trading-funding-pool-rate-usdt-points").textContent = formatTradingPercent(tradingBorrowEffectiveAprPercent("usdt_points"));
  if (availabilityNote) {
    const publicSpotSymbols = economySpotMarkets(tradingState.markets || [])
      .map((row) => tradingDisplaySymbol(row.symbol))
      .filter(Boolean);
    const pauseKinds = [];
    if (tradingState.settings?.price_degrade_pause_market_orders) pauseKinds.push("市價交易");
    if (tradingState.settings?.price_degrade_pause_bots) pauseKinds.push("機器人");
    if (tradingState.settings?.price_degrade_pause_borrowing) pauseKinds.push("借貸交易");
    const degradeNote = pauseKinds.length
      ? `價格降級時會自動暫停：${pauseKinds.join(" / ")}。`
      : "價格降級時目前只警示，不自動暫停交易。";
    availabilityNote.textContent = currentUser === "root"
      ? `root 可使用現貨、進階交易與合約模擬；root 以外用戶目前僅開放現貨與已啟用的進階交易。${degradeNote}`
      : `目前對 root 以外用戶開放 ${publicSpotSymbols.join("、") || "已啟用的積分現貨市場"} 現貨。${degradeNote}`;
  }
  const trial = funding.trial_credit || null;
  const trialAvailable = trial ? Number(trial.available_points || 0) : 0;
  const trialInitial = trial ? Number(trial.initial_points || 0) : 0;
  const walletAvailable = Number(funding.wallet_available_points || 0);
  const totalAvailable = Number(funding.available_points ?? (walletAvailable + trialAvailable));
  if ($("trading-funding-available")) $("trading-funding-available").textContent = funding.available_points != null ? formatTradingPointsValue(totalAvailable) : "-";
  if ($("trading-funding-mode")) {
    const selectedWallet = funding.selected_wallet_address || funding.active_wallet_address || "";
    const walletText = selectedWallet ? `付款錢包 ${tradingShortWalletAddress(selectedWallet)} · ` : "";
    $("trading-funding-mode").textContent = funding.mode === "root_simulated"
      ? `root 模擬資金 · 鎖定 ${formatTradingPointsValue(funding.locked_points)}`
      : `${walletText}體驗金優先 · 總可用 ${formatTradingPointsValue(totalAvailable)} = 體驗金 ${formatTradingPointsValue(trialAvailable)} + 真實積分 ${formatTradingPointsValue(walletAvailable)} · 鎖定 ${formatTradingPointsValue(funding.locked_points)}`;
  }
  if ($("trading-trial-credit-available")) {
    $("trading-trial-credit-available").textContent = trial ? `${formatTradingPointsValue(trialAvailable)} / ${formatTradingPointsValue(trialInitial)}` : "-";
  }
  updateTradingTrialCountdown();
  renderTradingCurrentPrice(market, { animate: false, ...(tradingState.livePriceMeta?.[market?.symbol] || {}) });
  renderTradingRiskDashboard();
  if ($("trading-fee-rate-percent")) $("trading-fee-rate-percent").textContent = market ? formatTradingPercent(market.fee_rate_percent || 0) : "-";
  const position = market ? tradingState.positions.find((row) => row.market_symbol === market.symbol) : null;
  if ($("trading-position-quantity")) $("trading-position-quantity").textContent = position ? sanitize(position.quantity || "0") : "0";
  if ($("trading-position-locked")) {
    const lockedText = `鎖定 ${position ? sanitize(position.locked_quantity || "0") : "0"}`;
    const targetText = position ? tradingRiskTargetText(position.stop_loss_percent, position.take_profit_percent) : "未設定停損 / 停利";
    $("trading-position-locked").textContent = `${lockedText} · ${targetText}`;
  }
  const limit = $("trading-limit-price");
  if (limit && market && !$("trading-root-price")?.matches(":focus")) {
    limit.placeholder = `目前 ${formatTradingPointsValue(tradingMarketPricePoints(market, "reference"))}`;
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
  if (!market || !market?.btc_trade_supported || !payload?.available || !payload.signal) {
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
      <div><span class="drive-card-sub">目前價格</span><strong>${sanitize(tradingReferenceLabel(signal.current_price))}</strong><small>${sanitize(tradingDisplaySymbol(market.symbol))}</small></div>
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
  if (!market || !market?.btc_trade_supported) {
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

function tradingIndicatorClose(point) {
  return Number(point?.close_usdt || point?.price_usdt || point?.close || 0);
}

function tradingIndicatorHigh(point) {
  return Number(point?.high_usdt || point?.high_points || point?.price_usdt || point?.close_usdt || point?.close || 0);
}

function tradingIndicatorLow(point) {
  return Number(point?.low_usdt || point?.low_points || point?.price_usdt || point?.close_usdt || point?.close || 0);
}

function tradingIndicatorSeries(candles, period, mode = "sma") {
  const closes = candles.map(tradingIndicatorClose);
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

function tradingIndicatorWindowAverage(values, period) {
  const output = Array(values.length).fill(null);
  if (!period || period < 1) return output;
  for (let index = period - 1; index < values.length; index += 1) {
    const windowValues = values.slice(index - period + 1, index + 1);
    if (windowValues.some((value) => !Number.isFinite(value))) continue;
    output[index] = windowValues.reduce((sum, value) => sum + value, 0) / period;
  }
  return output;
}

function tradingBollingerSeries(candles, period = 20, multiplier = 2) {
  const closes = candles.map(tradingIndicatorClose);
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

function tradingRsiSeries(candles, period = 14) {
  const closes = candles.map(tradingIndicatorClose);
  const values = Array(closes.length).fill(null);
  if (!period || period < 1 || closes.length <= period) return values;
  let gains = 0;
  let losses = 0;
  for (let index = 1; index <= period; index += 1) {
    const prev = closes[index - 1];
    const current = closes[index];
    if (!Number.isFinite(prev) || !Number.isFinite(current) || prev <= 0 || current <= 0) return values;
    const delta = current - prev;
    gains += Math.max(delta, 0);
    losses += Math.max(-delta, 0);
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  values[period] = avgLoss === 0 ? (avgGain === 0 ? 50 : 100) : 100 - (100 / (1 + (avgGain / avgLoss)));
  for (let index = period + 1; index < closes.length; index += 1) {
    const prev = closes[index - 1];
    const current = closes[index];
    if (!Number.isFinite(prev) || !Number.isFinite(current) || prev <= 0 || current <= 0) continue;
    const delta = current - prev;
    const gain = Math.max(delta, 0);
    const loss = Math.max(-delta, 0);
    avgGain = ((avgGain * (period - 1)) + gain) / period;
    avgLoss = ((avgLoss * (period - 1)) + loss) / period;
    values[index] = avgLoss === 0 ? (avgGain === 0 ? 50 : 100) : 100 - (100 / (1 + (avgGain / avgLoss)));
  }
  return values;
}

function tradingKdSeries(candles, lookback = 9, smoothK = 3, smoothD = 3) {
  const rawK = Array(candles.length).fill(null);
  for (let index = lookback - 1; index < candles.length; index += 1) {
    const windowPoints = candles.slice(index - lookback + 1, index + 1);
    const highs = windowPoints.map(tradingIndicatorHigh).filter((value) => Number.isFinite(value) && value > 0);
    const lows = windowPoints.map(tradingIndicatorLow).filter((value) => Number.isFinite(value) && value > 0);
    const close = tradingIndicatorClose(candles[index]);
    if (highs.length !== lookback || lows.length !== lookback || !Number.isFinite(close) || close <= 0) continue;
    const highest = Math.max(...highs);
    const lowest = Math.min(...lows);
    rawK[index] = highest === lowest ? 50 : ((close - lowest) * 100) / (highest - lowest);
  }
  const k = tradingIndicatorWindowAverage(rawK, smoothK);
  const d = tradingIndicatorWindowAverage(k, smoothD);
  return { k, d };
}

function buildTradingReferenceIndicators(candles) {
  const overlays = [];
  const oscillators = [];
  if (tradingIndicatorEnabled("trading-indicator-ma5")) {
    overlays.push({ key: "ma5", label: "MA5", color: "#f59e0b", values: tradingIndicatorSeries(candles, 5), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ma10")) {
    overlays.push({ key: "ma10", label: "MA10", color: "#fde047", values: tradingIndicatorSeries(candles, 10), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ma20")) {
    overlays.push({ key: "ma20", label: "MA20", color: "#38bdf8", values: tradingIndicatorSeries(candles, 20), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ma30")) {
    overlays.push({ key: "ma30", label: "MA30", color: "#34d399", values: tradingIndicatorSeries(candles, 30), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ma60")) {
    overlays.push({ key: "ma60", label: "MA60", color: "#a78bfa", values: tradingIndicatorSeries(candles, 60), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ema12")) {
    overlays.push({ key: "ema12", label: "EMA12", color: "#22d3ee", values: tradingIndicatorSeries(candles, 12, "ema"), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ema26")) {
    overlays.push({ key: "ema26", label: "EMA26", color: "#fb7185", values: tradingIndicatorSeries(candles, 26, "ema"), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-ema50")) {
    overlays.push({ key: "ema50", label: "EMA50", color: "#f97316", values: tradingIndicatorSeries(candles, 50, "ema"), axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-bollinger")) {
    const bands = tradingBollingerSeries(candles, 20, 2);
    overlays.push({ key: "bb_upper", label: "BB上", color: "rgba(16, 185, 129, .82)", values: bands.upper, dash: [4, 4], axis: "price" });
    overlays.push({ key: "bb_mid", label: "BB中", color: "rgba(16, 185, 129, .5)", values: bands.middle, axis: "price" });
    overlays.push({ key: "bb_lower", label: "BB下", color: "rgba(16, 185, 129, .82)", values: bands.lower, dash: [4, 4], axis: "price" });
  }
  if (tradingIndicatorEnabled("trading-indicator-rsi14")) {
    oscillators.push({ key: "rsi14", label: "RSI14", color: "#fbbf24", values: tradingRsiSeries(candles, 14), axis: "oscillator" });
  }
  if (tradingIndicatorEnabled("trading-indicator-kd")) {
    const kd = tradingKdSeries(candles, 9, 3, 3);
    oscillators.push({ key: "kd_k", label: "KD-K", color: "#f472b6", values: kd.k, axis: "oscillator" });
    oscillators.push({ key: "kd_d", label: "KD-D", color: "#60a5fa", values: kd.d, axis: "oscillator" });
  }
  return { overlays, oscillators };
}

function drawTradingIndicatorLine(ctx, indicator, candleModels, yForPrice) {
  ctx.save();
  ctx.strokeStyle = indicator.color;
  ctx.lineWidth = 1.45;
  if (indicator.dash) ctx.setLineDash(indicator.dash);
  let drawing = false;
  ctx.beginPath();
  indicator.values.forEach((value, index) => {
    const invalid = indicator?.axis === "oscillator"
      ? (!Number.isFinite(value) || value < 0)
      : (!Number.isFinite(value) || value <= 0);
    if (invalid || !candleModels[index]) {
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

function tradingIndicatorValueLabel(indicator, value) {
  if (!Number.isFinite(value)) return "-";
  return indicator?.axis === "oscillator"
    ? `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}`
    : tradingReferenceLabel(value);
}

function tradingIndicatorHasValue(indicator, value) {
  if (!Number.isFinite(value)) return false;
  return indicator?.axis === "oscillator" ? value >= 0 : value > 0;
}

function tradingIndicatorLegend(indicators) {
  const active = indicators
    .filter((item) => item.values.some((value) => tradingIndicatorHasValue(item, value)))
    .map((item) => item.label);
  return active.length ? ` · 指標 ${active.join(" / ")}` : "";
}

function drawTradingOscillatorPanel(ctx, indicators, candleModels, panel, width, pad) {
  if (!indicators.length) return;
  const yForValue = (value) => panel.top + panel.height - ((value - panel.min) / panel.spread) * panel.height;
  ctx.save();
  ctx.strokeStyle = "rgba(148, 163, 184, .18)";
  ctx.lineWidth = 1;
  [0, 20, 50, 80, 100].forEach((level) => {
    const y = yForValue(level);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillStyle = level === 50 ? "#e2e8f0" : "#94a3b8";
    ctx.font = "10px system-ui, sans-serif";
    ctx.fillText(`${level}`, 12, y + 4);
  });
  [
    { value: 70, color: "rgba(248, 113, 113, .55)" },
    { value: 30, color: "rgba(74, 222, 128, .55)" },
  ].forEach((line) => {
    const y = yForValue(line.value);
    ctx.save();
    ctx.strokeStyle = line.color;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.restore();
  });
  indicators.forEach((indicator) => drawTradingIndicatorLine(ctx, indicator, candleModels, yForValue));
  ctx.fillStyle = "#cbd5e1";
  ctx.font = "11px system-ui, sans-serif";
  ctx.fillText("RSI / KD", pad.left, panel.top - 4);
  ctx.restore();
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
  const indicatorGroups = buildTradingReferenceIndicators(candles);
  const overlayIndicators = indicatorGroups.overlays;
  const oscillatorIndicators = indicatorGroups.oscillators;
  const indicators = overlayIndicators.concat(oscillatorIndicators);
  const prices = candles.flatMap((point) => [
    Number(point.high_usdt || point.high_points || point.price_usdt || point.price_points || 0),
    Number(point.low_usdt || point.low_points || point.price_usdt || point.price_points || 0),
  ]).concat(overlayIndicators.flatMap((indicator) => indicator.values)).filter((value) => Number.isFinite(value) && value > 0);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const spread = Math.max(1, maxPrice - minPrice);
  const pad = { left: 58, right: 18, top: 22, bottom: 34 };
  const chartW = width - pad.left - pad.right;
  const panelGap = oscillatorIndicators.some((indicator) => indicator.values.some((value) => Number.isFinite(value) && value >= 0)) ? 12 : 0;
  const totalChartH = height - pad.top - pad.bottom;
  const oscillatorH = panelGap ? Math.max(72, Math.round(totalChartH * 0.24)) : 0;
  const mainChartH = totalChartH - oscillatorH - panelGap;
  const oscillatorPanel = panelGap ? { top: pad.top + mainChartH + panelGap, height: oscillatorH, min: 0, max: 100, spread: 100 } : null;
  const yForPrice = (price) => pad.top + mainChartH - ((price - minPrice) / spread) * mainChartH;
  ctx.strokeStyle = "rgba(148, 163, 184, .22)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (mainChartH * i / 4);
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
  overlayIndicators.forEach((indicator) => drawTradingIndicatorLine(ctx, indicator, candleModels, yForPrice));
  if (oscillatorPanel) {
    drawTradingOscillatorPanel(ctx, oscillatorIndicators, candleModels, oscillatorPanel, width, pad);
  }
  tradingReferenceChartModel = { payload, candles: candleModels, indicators, pad, width, height, chartW, chartH: mainChartH, slot, oscillatorPanel };
  if (tradingReferenceHoverIndex !== null && candleModels[tradingReferenceHoverIndex]) {
    const hover = candleModels[tradingReferenceHoverIndex];
    ctx.save();
    ctx.strokeStyle = "rgba(248, 250, 252, .72)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(hover.x, pad.top);
    ctx.lineTo(hover.x, oscillatorPanel ? oscillatorPanel.top + oscillatorPanel.height : height - pad.bottom);
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
  if (tradingBotChartOverlay) {
    drawBotChartOverlay(ctx, tradingBotChartOverlay, yForPrice, pad, width, mainChartH, candleModels);
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
      return tradingIndicatorHasValue(indicator, value)
        ? `<span>${sanitize(indicator.label)} ${sanitize(tradingIndicatorValueLabel(indicator, value))}</span>`
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

function updateTradingReferenceTooltipFromTouch(event) {
  const touch = event?.touches?.[0] || event?.changedTouches?.[0];
  if (touch) updateTradingReferenceTooltip(touch);
}

function tradingReferenceAutoRefreshMs() {
  return tradingReferencePriceRefreshMs();
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
  tradingReferenceAutoTimer = null;
  tradingReferenceChartAutoTimer = null;
  if (!shouldRunTradingFullPolling()) return;
  tradingReferenceAutoTimer = setInterval(async () => {
    if (!shouldRunTradingFullPolling() || tradingReferenceAutoBusy) return;
    tradingReferenceAutoBusy = true;
    try {
      await loadTradingReferencePrices({ silent: true, priceOnly: true });
    } finally {
      tradingReferenceAutoBusy = false;
    }
  }, tradingReferenceAutoRefreshMs());
  tradingReferenceChartAutoTimer = setInterval(async () => {
    if (!shouldRunTradingFullPolling() || tradingReferenceChartAutoBusy) return;
    tradingReferenceChartAutoBusy = true;
    try {
      await loadTradingReferencePrices({ silent: true, latestOnly: true });
    } finally {
      tradingReferenceChartAutoBusy = false;
    }
  }, tradingReferenceChartRefreshMs());
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
    const referenceContext = json.price_context && typeof json.price_context === "object" ? json.price_context : null;
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
      // Reference-price polling is for the chart only. The trading card's
      // "current price" must keep using the live/fused market price returned
      // by the trading dashboard, otherwise single-source reference candles can
      // visually overwrite the real execution reference price.
      if ($("trading-reference-price-meta")) {
        const providerLabel = Number.isFinite(Number(json.provider_count)) ? ` · 來源 ${Number(json.provider_count)} 家` : "";
        const staleLabel = json.stale ? " · stale" : "";
        const degradedLabel = json.degraded ? " · degraded" : "";
        const contextLabel = referenceContext ? ` · ${tradingPriceContextSummary(referenceContext, { compact: true })}` : "";
        $("trading-reference-price-meta").textContent = `reference price：${json.display_market || json.market || market.symbol} · ${json.interval || interval} · ${json.source || "reference_price"} · 信心 ${tradingPriceConfidenceLabel(json.confidence)}${providerLabel}${staleLabel}${degradedLabel} · 最新收盤 ${Number(last.close_points || 0)}${contextLabel}`;
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

function applyTradingOrderResult(order) {
  if (!order?.order_uuid) return;
  const rows = Array.isArray(tradingState.orders) ? tradingState.orders.slice() : [];
  const index = rows.findIndex((row) => row.order_uuid === order.order_uuid);
  if (index >= 0) rows[index] = { ...rows[index], ...order };
  else rows.unshift(order);
  tradingState.orders = rows.slice(0, 50);
  renderTradingOrders(tradingState.orders);
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
  const riskContext = tradingMarketPriceContext(market, "risk_grade");
  const borrowingPausePolicy = tradingPriceDegradePolicy(riskContext, "borrowing");
  const priceConfidenceOnlyWarns = tradingState.settings?.disable_price_confidence_gates !== false || !!tradingState.settings?.dev_disable_price_confidence_gates;
  const riskGradePrice = tradingMarketPricePoints(market, "risk_grade");
  const referencePrice = tradingMarketPricePoints(market, "reference");
  const price = riskGradePrice > 0 ? riskGradePrice : (borrowingPausePolicy.shouldPause ? riskGradePrice : referencePrice);
  const notional = quantity > 0 && price > 0 ? Math.ceil(quantity * price) : 0;
  const positionType = $("trading-margin-type")?.value || "margin_long";
  const marginLongFinancingRatePercent = tradingNumber(tradingState.settings?.margin_long_financing_percent, 90);
  const shortCollateralRatePercent = tradingNumber(tradingState.settings?.short_collateral_percent, 60);
  const feeRatePercent = tradingNumber(market.fee_rate_percent, 0);
  const maintenancePercent = tradingNumber(tradingState.settings?.margin_maintenance_percent, 15);
  const baseMinCollateral = positionType === "short"
    ? Math.ceil(notional * shortCollateralRatePercent / 100)
    : Math.ceil(notional * Math.max(0, 100 - marginLongFinancingRatePercent) / 100);
  const safetyMinCollateral = Math.ceil(notional * Math.max(0, maintenancePercent + feeRatePercent) / 100) + 2;
  const minCollateral = Math.max(baseMinCollateral, safetyMinCollateral);
  const minimumBorrowUnitPoints = 1;
  const maxLongCollateral = Math.max(0, notional - minimumBorrowUnitPoints);
  const feeMicropoints = tradingFeeMicropoints(notional, feeRatePercent);
  const fee = tradingMicropointsToSettlementPoints(feeMicropoints);
  const feeExact = feeMicropoints / TRADING_POINT_MICRO_SCALE;
  const available = tradingNumber(tradingState.funding?.available_points, 0);
  const upfrontRequired = collateral;
  const maxCollateralFromAvailable = Math.max(0, available);
  const principal = positionType === "short" ? notional : Math.max(0, notional - collateral);
  const fundingPool = tradingState.fundingPool || {};
  const poolAvailable = tradingNumber(fundingPool.available_points, 0);
  const borrowGroup = tradingBorrowAprGroupForMarket(market, positionType);
  const poolApr = tradingBorrowEffectiveAprPercent(
    borrowGroup,
    tradingNumber(fundingPool.projected_utilization_percent, fundingPool.utilization_percent)
  );
  const timing = tradingBorrowTimingSummary();
  const typeLabel = positionType === "short" ? "借券放空" : "融資買入";
  if (!quantity || !collateral || !notional) {
    estimate.textContent = "輸入數量與保證金後顯示預估風險。";
    estimate.style.color = "var(--muted)";
    if (openBtn) openBtn.disabled = true;
    return { ok: false, blocking: true, message: estimate.textContent };
  }
  let blocking = false;
  if (!priceConfidenceOnlyWarns && borrowingPausePolicy.shouldPause) {
    const message = `${tradingPriceDegradePauseMessage(typeLabel, riskContext, borrowingPausePolicy)} · ${tradingPriceContextSummary(riskContext, { compact: true })}`;
    blocking = true;
    estimate.textContent = message;
    estimate.style.color = "#ff6b7a";
    if (openBtn) openBtn.setAttribute("aria-disabled", "true");
    return { ok: false, blocking, message };
  }
  const priceLabel = riskGradePrice > 0 ? "風控級價格" : "reference 價格";
  const contextForMessage = riskGradePrice > 0 ? riskContext : tradingMarketPriceContext(market, "reference");
  const baseRuleText = positionType === "short"
    ? `借券保證金 ${formatTradingPercent(shortCollateralRatePercent)}% 底線 ${baseMinCollateral} 點`
    : `融資自備 ${formatTradingPercent(Math.max(0, 100 - marginLongFinancingRatePercent))}% 底線 ${baseMinCollateral} 點`;
  const safetyRuleText = `維持率 + 費率安全底線 ${safetyMinCollateral} 點`;
  let message = `${typeLabel} · ${priceLabel} ${formatTradingPointsValue(price)} 點 · ${tradingPriceContextSummary(contextForMessage, { compact: true })} · 名目金額約 ${notional} 點 · 預估開倉手續費 ${formatTradingPointsValue(feeExact)} 點（結算時合併進位，約 ${fee} 點）· 原始保證金最低需求 ${minCollateral} 點（${baseRuleText}；${safetyRuleText}）· 目前填寫保證金 ${collateral} 點 · 實際預扣 ${upfrontRequired} 點`;
  if (positionType === "short") {
    message = `${message}；借券放空風險：價格上漲會虧損並降低維持率；借券保證金比例 ${formatTradingPercent(shortCollateralRatePercent)}%`;
  } else {
    message = `${message}；融資可貸比例 ${formatTradingPercent(marginLongFinancingRatePercent)}%`;
  }
  if (positionType === "margin_long" && maxLongCollateral < minCollateral) {
    message = `${message}；這筆名目金額太小，扣除至少借 1 點後，已無法同時滿足最低原始保證金需求。請提高買入數量，或改用現貨買入。`;
    blocking = true;
  } else if (positionType === "margin_long" && collateral >= notional) {
    message = `${message}；你填寫的保證金已超過本次買入名目金額，這不屬於融資交易。請改用現貨買入；若要融資，保證金需介於 ${minCollateral}～${maxLongCollateral} 點之間，且至少要借 1 點。`;
    blocking = true;
  } else if (collateral < minCollateral) {
    message = `${message}；原始保證金不足，至少需要 ${minCollateral} 點。若要融資，保證金需介於 ${minCollateral}～${maxLongCollateral} 點之間。`;
    blocking = true;
  } else if (upfrontRequired > available) {
    if (maxCollateralFromAvailable >= minCollateral) {
      message = `${message}；可用資金不足：本欄位最多可填 ${maxCollateralFromAvailable} 點保證金（手續費會在平倉 / 清算時合併結算）。`;
    } else {
      message = `${message}；可用資金不足：最多只能填 ${maxCollateralFromAvailable} 點保證金，低於最低需求 ${minCollateral} 點；目前可用 ${available} 點。`;
    }
    blocking = true;
  } else if (principal > poolAvailable && currentUser !== "root") {
    message = `${message}；資金池不足，需要借出 ${principal} 點，目前可借 ${poolAvailable} 點`;
    blocking = true;
  } else if (tradingState.settings?.borrowing_enabled) {
    const borrowGroupLabel = borrowGroup === "btc_eth" ? "BTC / ETH" : "USDT / POINTS";
    message = `${message}；預估借出本金 ${principal} 點，目前浮動年利率約 ${formatTradingPercent(poolApr)}% APR（${borrowGroupLabel}）`;
    if (timing.text) message = `${message}；${timing.text}`;
  }
  estimate.textContent = message;
  estimate.style.color = blocking ? "#ff6b7a" : "var(--muted)";
  if (openBtn) {
    openBtn.disabled = !tradingState.settings?.borrowing_enabled;
    openBtn.setAttribute("aria-disabled", blocking ? "true" : "false");
  }
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
  list.querySelectorAll("[data-margin-withdraw-collateral]").forEach((btn) => {
    bindTradingActionButton(btn, () => withdrawTradingMarginCollateral(btn.dataset.marginWithdrawCollateral || ""), "正在抽出保證金...", "抽出保證金失敗");
  });
}

function renderTradingMarginAccountSummary(summary = null) {
  const wrap = $("trading-margin-account-summary");
  if (!wrap) return;
  const data = (summary && typeof summary === "object" && Object.keys(summary).length)
    ? summary
    : tradingLiveMarginSummary(tradingState.marginPositions || []);
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

function tradingBotBudgetText(bot) {
  const budget = Number(bot?.budget_points || 0);
  const frozen = Number(bot?.open_order_frozen_points || 0);
  const remaining = bot?.budget_remaining_points == null ? null : Number(bot.budget_remaining_points || 0);
  if (bot?.bot_type === "dca") return `每次投入 ${formatTradingPointsValue(budget)} 點`;
  if (budget <= 0) return frozen > 0
    ? `可用上限不設限 · 已掛單凍結 ${formatTradingPointsValue(frozen)} 點`
    : "可用上限不設限";
  return `可用上限 ${formatTradingPointsValue(budget)} 點 · 剩餘可掛 ${formatTradingPointsValue(remaining ?? Math.max(0, budget - frozen))} 點`;
}

function switchTradingBotTab(tab) {
  tradingCurrentBotTab = tab || "mybots";
  document.querySelectorAll("[data-trading-bot-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tradingBotTab === tradingCurrentBotTab);
  });
  document.querySelectorAll(".trading-bot-tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `trading-bot-tab-${tradingCurrentBotTab}`);
  });
  if (tradingCurrentBotTab === "grid") {
    renderGridBotPreview({ quiet: true }).catch(() => {});
  } else if (tradingCurrentBotTab === "competition") {
    loadTradingBotCompetition().catch(() => {});
  }
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
  const benchmarkHtml = renderTradingWorkflowTemplateBenchmark(key);
  box.innerHTML = `
    <div class="drive-card-title">${sanitize(item.label || key)}</div>
    ${sections.map(([title, content]) => `
      <div class="workflow-template-section">
        <strong>${sanitize(title)}</strong>
        <div>${content.startsWith("<") ? content : sanitize(content)}</div>
      </div>
    `).join("")}
    ${benchmarkHtml}
    <div class="muted">來源：${sanitize(item.source_path || item.scope || "workflow")}</div>
  `;
  loadTradingWorkflowBenchmarksAsync();
}

let tradingWorkflowBenchmarkCache = null;
let tradingWorkflowBenchmarkLoading = false;

function renderTradingWorkflowTemplateBenchmark(templateId) {
  const data = tradingWorkflowBenchmarkCache;
  if (!data) {
    return `
      <div class="workflow-template-section">
        <strong>歷史回測表現（BTC/USDT 1h）</strong>
        <div class="muted">資料載入中...</div>
      </div>
    `;
  }
  if (!Array.isArray(data.windows) || !data.windows.length) {
    return `
      <div class="workflow-template-section">
        <strong>歷史回測表現（BTC/USDT 1h）</strong>
        <div class="muted">${sanitize(data.load_error || "目前沒有可用的 Workflow 歷史回測資料。")}</div>
      </div>
    `;
  }
  const rows = data.windows.map((w) => {
    const r = (w.rankings || []).find((row) => row.template === templateId);
    if (!r || r.error) return [w.label, null, null, null];
    const pnl = Number(r.pnl_percent || 0);
    return [w.label, pnl, Number(r.trade_count || 0), Number(r.max_drawdown_percent || 0)];
  });
  if (!rows.length) return "";
  const fmtPct = (v) => {
    if (v === null || v === undefined) return "-";
    const n = Number(v);
    const cls = n > 0 ? "color:#00d4aa" : n < 0 ? "color:#ff6b6b" : "";
    return `<span style="${cls}">${n >= 0 ? "+" : ""}${n.toFixed(2)}%</span>`;
  };
  const table = `
    <table style="width:100%;border-collapse:collapse;font-size:.82rem;margin-top:.3rem;">
      <thead><tr style="border-bottom:1px solid var(--muted, #444);">
        <th style="text-align:left;padding:.2rem .4rem;">時長</th>
        <th style="text-align:right;padding:.2rem .4rem;">PnL</th>
        <th style="text-align:right;padding:.2rem .4rem;">交易次數</th>
        <th style="text-align:right;padding:.2rem .4rem;">最大回撤</th>
      </tr></thead>
      <tbody>${rows.map(([label, pnl, trades, dd]) => `
        <tr>
          <td style="padding:.2rem .4rem;">${sanitize(label)}</td>
          <td style="text-align:right;padding:.2rem .4rem;">${pnl === null ? "-" : fmtPct(pnl)}</td>
          <td style="text-align:right;padding:.2rem .4rem;">${trades === null ? "-" : trades}</td>
          <td style="text-align:right;padding:.2rem .4rem;">${dd === null ? "-" : fmtPct(-Math.abs(dd))}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
  return `
    <div class="workflow-template-section">
      <strong>歷史回測表現（BTC/USDT ${sanitize(data.interval || "1h")}，初始資金 ${Number(data.initial_cash_points || 0).toLocaleString()} POINTS）</strong>
      ${table}
      <div class="muted" style="font-size:.72rem;margin-top:.3rem;">資料來源：${sanitize(data.data_source || "")}；資料區間 ${sanitize(String(data.first_candle_iso || "").slice(0, 10))} → ${sanitize(String(data.last_candle_iso || "").slice(0, 10))}；產生時間 ${sanitize(data.generated_at || "")}</div>
    </div>
  `;
}

async function loadTradingWorkflowBenchmarksAsync() {
  if (tradingWorkflowBenchmarkCache || tradingWorkflowBenchmarkLoading) return;
  tradingWorkflowBenchmarkLoading = true;
  try {
    tradingWorkflowBenchmarkCache = await fetchTradingJson("/trading/workflow-template-benchmarks", { forceCsrf: false });
  } catch (_err) {
    tradingWorkflowBenchmarkCache = { windows: [], load_error: "Workflow 歷史回測報告讀取失敗。" };
  } finally {
    tradingWorkflowBenchmarkLoading = false;
    renderTradingWorkflowTemplateExplanation();
  }
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
    if (Array.isArray(json.errors) && json.errors.length) {
      tradingSetMsg(`部分 Workflow 模板載入失敗：${json.errors[0].error || "未知錯誤"}`, false);
    }
  } catch (err) {
    renderTradingWorkflowTemplateOptions();
    tradingSetMsg(err.message || "Workflow 模板讀取失敗，請確認 workflows/trading_bot 內有模板檔", false);
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
    tradingSetMsg(json.msg || `Workflow 自訂模板已儲存到 ${json.custom_workflow_root || "runtime/workflows/custom"}`);
  } catch (err) {
    tradingSetMsg(err.message || "Workflow 自訂模板儲存失敗", false);
  }
}

function tradingWorkflowTemplate(name = "dipbuy_rsi35_70_size99_late_tp15_nopyr_codex") {
  const templates = tradingWorkflowTemplates();
  const item = templates[name] || templates.dipbuy_rsi35_70_size99_late_tp15_nopyr_codex || Object.values(templates)[0];
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
  const key = $("trading-workflow-template-select")?.value || "dipbuy_rsi35_70_size99_late_tp15_nopyr_codex";
  const templates = tradingWorkflowTemplates();
  const item = templates[key] || templates.dipbuy_rsi35_70_size99_late_tp15_nopyr_codex || Object.values(templates)[0];
  if (!item || !item.workflow) {
    tradingSetMsg("沒有可用 Workflow 模板，請確認 workflows/trading_bot 內有模板檔", false);
    return;
  }
  const textarea = $("trading-auto-workflow-json");
  if (!textarea) {
    tradingSetMsg("找不到 Workflow JSON 編輯欄位", false);
    return;
  }
  textarea.value = JSON.stringify(item.workflow, null, 2);
  localStorage.setItem(tradingUserStorageKey(TRADING_WORKFLOW_STORAGE_KEY), textarea.value);
  renderTradingWorkflowTemplateExplanation();
  tradingSetMsg(`已套用基礎模板：${item.label}。請依市場價格調整門檻後再儲存機器人。`);
}

function tradingWorkflowText() {
  const raw = $("trading-auto-workflow-json")?.value || "";
  if (raw.trim()) return raw.trim();
  const saved = localStorage.getItem(tradingUserStorageKey(TRADING_WORKFLOW_STORAGE_KEY));
  return saved || JSON.stringify(tradingWorkflowTemplate(), null, 2);
}

function loadTradingWorkflowFromEditor() {
  const saved = localStorage.getItem(tradingUserStorageKey(TRADING_WORKFLOW_STORAGE_KEY));
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

function tradingBotMaxRunsValue(row) {
  return Number(row?.max_runs ?? 1);
}

function tradingBotMaxRunsLabel(row) {
  return tradingBotMaxRunsValue(row) === -1 ? "不限制" : String(tradingBotMaxRunsValue(row));
}

function tradingBotRunLimitReached(row) {
  const maxRuns = tradingBotMaxRunsValue(row);
  if (maxRuns === -1) return false;
  return Number(row?.run_count || 0) >= maxRuns;
}

function tradingBotNextRunInfo(row) {
  if (!row || !row.enabled) return { text: "下次執行：已停用", ready: false };
  if (tradingBotRunLimitReached(row)) return { text: "下次執行：已達最大次數", ready: false };
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
  if ((tradingState.bots || []).some((row) => row.enabled && !tradingBotRunLimitReached(row))) {
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
    const botRuns = runs.filter((r) => Number(r.bot_id) === Number(row.id) && r.status === "triggered").slice(0, 5);
    const tradeHistoryHtml = botRuns.length
      ? `<div class="drive-card-sub" style="margin-top:.25rem;">
          <span style="font-weight:600;">近期交易：</span>${botRuns.map((r) => {
            const price = Number(r.observed_price_points || 0);
            const sideLabel = row.side === "sell" ? "賣" : "買";
            const sideColor = row.side === "sell" ? "#ef4444" : "#22c55e";
            const timeStr = r.created_at ? new Date(r.created_at).toLocaleString() : "-";
            return `<span style="margin-left:.4rem;color:${sideColor};">${sideLabel} ${formatTradingPointsValue(price)} 點（${timeStr}）</span>`;
          }).join("")}
        </div>`
      : "";
    return `
        <div class="drive-file-row">
          <div>
            <strong>${sanitize(row.name || "未命名機器人")} · ${sanitize(tradingDisplaySymbol(row.market_symbol || ""))}</strong>
            <div class="drive-card-sub">
	              ${sanitize(row.bot_type_label || (row.bot_type === "dca" ? "定投機器人" : "Workflow 機器人"))} · ${sanitize(tradingBotTriggerLabel(row))} 時 ${row.side === "sell" ? "賣出" : "買入"} ${row.bot_type === "dca" ? "系統換算數量" : sanitize(row.quantity_text || "workflow 決定")}，
	              ${row.order_type === "limit" ? `限價 ${formatTradingPointsValue(row.limit_price_points)}` : "市價單"}
	              ${tradingParameterShareBadge(row)}
	            </div>
            <div class="drive-card-sub">
              狀態 ${row.enabled ? "啟用" : "停用"} · 已觸發 ${Number(row.run_count || 0)} / ${tradingBotMaxRunsLabel(row)} · 冷卻 ${Number(row.cooldown_seconds || 0)} 秒
            </div>
            <div class="drive-card-sub">${sanitize(tradingBotBudgetText(row))}</div>
            <div class="drive-card-sub">${sanitize(tradingRiskTargetText(row.stop_loss_percent, row.take_profit_percent))}</div>
            ${condHtml}
            ${tradeHistoryHtml}
            <div class="drive-card-sub" data-trading-bot-next-run="${sanitize(row.bot_uuid || "")}">${sanitize(tradingBotNextRunText(row))}</div>
            ${row.last_error ? `<div class="drive-card-sub negative">上次錯誤：${sanitize(row.last_error)}</div>` : ""}
          </div>
          <div class="drive-file-actions">
            ${tradingBotRunLimitReached(row) ? `<button class="btn" type="button" data-trading-bot-increase-runs="${sanitize(row.bot_uuid || "")}">增加次數</button>` : ""}
	            ${row.bot_type !== "dca" ? `<button class="btn" type="button" data-trading-bot-budget="${sanitize(row.bot_uuid || "")}">調整可用</button>` : ""}
	            <button class="btn" type="button" data-trading-bot-toggle="${sanitize(row.bot_uuid || "")}" data-trading-bot-enabled="${row.enabled ? "0" : "1"}">${row.enabled ? "暫停" : "啟用"}</button>
	            <button class="btn" type="button" data-trading-bot-share="${sanitize(row.bot_uuid || "")}" data-trading-bot-share-enabled="${row.share_parameters ? "0" : "1"}">${row.share_parameters ? "停止分享參數" : "分享參數"}</button>
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
	    list.querySelectorAll("[data-trading-bot-share]").forEach((btn) => {
	      bindTradingActionButton(
	        btn,
	        () => setTradingBotParameterShare(btn.dataset.tradingBotShare || "", btn.dataset.tradingBotShareEnabled === "1"),
	        btn.dataset.tradingBotShareEnabled === "1" ? "正在開啟參數分享..." : "正在停止參數分享...",
	        "參數分享狀態更新失敗"
	      );
	    });
    list.querySelectorAll("[data-trading-bot-increase-runs]").forEach((btn) => {
      bindTradingActionButton(btn, () => increaseTradingBotMaxRuns(btn.dataset.tradingBotIncreaseRuns || ""), "正在增加可執行次數...", "增加機器人次數失敗");
    });
    list.querySelectorAll("[data-trading-bot-budget]").forEach((btn) => {
      bindTradingActionButton(btn, () => adjustTradingBotBudget(btn.dataset.tradingBotBudget || ""), "正在調整機器人可用上限...", "調整機器人可用上限失敗");
    });
  });
  refreshBacktestBotSelect();
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
  renderMyBotsList();
}

function tradingParameterShareBadge(bot) {
  return bot?.share_parameters
    ? ` · <span class="trading-share-badge">參數已分享</span>`
    : ` · <span class="trading-share-badge muted">參數未分享</span>`;
}

function tradingSharedParametersHtml(params) {
  if (!params || typeof params !== "object") return `<div class="drive-card-sub">此用戶未分享參數</div>`;
  const rows = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => {
      const text = typeof value === "object" ? JSON.stringify(value) : String(value);
      return `<span><b>${sanitize(key)}</b> ${sanitize(text)}</span>`;
    });
  return rows.length
    ? `<div class="trading-shared-params">${rows.join("")}</div>`
    : `<div class="drive-card-sub">此用戶未分享參數</div>`;
}

function renderTradingBotCompetition(competition = null) {
  const container = $("trading-bot-competition-list");
  const meta = $("trading-bot-competition-meta");
  const rewardEl = $("trading-bot-competition-rewards");
  const weekInput = $("trading-bot-competition-week");
  const awardBtn = $("trading-bot-competition-award-btn");
  if (!container) return;
  const data = competition || tradingState.botCompetition || {};
  const week = data.week || "";
  if (weekInput && !weekInput.value) weekInput.value = week;
  const settings = data.settings || {};
  const enabled = settings.enabled !== false;
  const rewardPoints = Number(settings.weekly_reward_points || 0);
  if (meta) {
    meta.textContent = `${week || "-"} · ${enabled ? "週賽啟用" : "週賽停用"} · 各類第一名 ${rewardPoints.toLocaleString()} 點`;
  }
  const rewards = Array.isArray(data.rewards) ? data.rewards : [];
  const autoAwarded = Array.isArray(data.auto_awarded) ? data.auto_awarded : [];
  if (rewardEl) {
    const rewardText = rewards.length
      ? rewards.map((row) => `${row.category}：${row.username} +${Number(row.reward_points || 0).toLocaleString()} 點`).join(" · ")
      : "本週尚未發放競賽獎勵";
    const autoText = autoAwarded.length ? ` · 已自動補發 ${autoAwarded.length} 筆上週獎勵` : "";
    rewardEl.textContent = `${rewardText}${autoText}`;
  }
  if (awardBtn) {
    awardBtn.style.display = currentUser === "root" ? "" : "none";
    awardBtn.dataset.awardWeek = data.previous_week || "";
  }
  const categories = Array.isArray(data.categories) ? data.categories : [];
  if (!categories.length) {
    container.innerHTML = `<div class="drive-empty">尚無競賽資料</div>`;
    return;
  }
  container.innerHTML = categories.map((category) => {
    const rows = Array.isArray(category.leaderboard) ? category.leaderboard : [];
    const body = rows.length ? rows.slice(0, 10).map((row) => {
      const rank = row.rank ? `#${row.rank}` : "-";
      const perf = Number(row.performance_percent || 0);
      const pnl = Number(row.pnl_points || 0);
      const perfClass = perf >= 0 ? "positive" : "negative";
      const pnlClass = pnl >= 0 ? "positive" : "negative";
      return `<div class="trading-bot-competition-row">
        <div class="trading-bot-competition-rank">${sanitize(rank)}</div>
        <div>
          <strong>${sanitize(row.bot_name || "未命名")} · ${sanitize(row.username || "-")}</strong>
          <div class="drive-card-sub">${sanitize(row.display_symbol || row.market_symbol || "-")} · 成交 ${Number(row.fill_count || 0)} 筆 · 本金基準 ${formatTradingPointsValue(row.principal_points || 0)} 點${tradingParameterShareBadge(row)}</div>
          <details class="economy-collapse" style="margin-top:.25rem;">
            <summary>分享參數</summary>
            ${tradingSharedParametersHtml(row.shared_parameters)}
          </details>
        </div>
        <div class="trading-bot-competition-score">
          <span class="${perfClass}">${perf >= 0 ? "+" : ""}${perf.toFixed(4)}%</span>
          <small class="${pnlClass}">${pnl >= 0 ? "+" : ""}${formatTradingPointsValue(pnl)} 點</small>
        </div>
      </div>`;
    }).join("") : `<div class="drive-empty">本週此類型尚無有效成交</div>`;
    return `<section class="trading-bot-competition-card">
      <div class="drive-card-heading compact-heading">
        <div>
          <div class="drive-card-title">${sanitize(category.label || category.category || "-")}</div>
          <div class="drive-card-sub">第一名獎勵 ${Number(category.reward_points || rewardPoints || 0).toLocaleString()} 點</div>
        </div>
      </div>
      ${body}
    </section>`;
  }).join("");
}

function tradingWorkflowBotDetail(bot) {
  const parts = [];
  const wf = bot.workflow;
  if (wf && typeof wf === "object") {
    const branches = Array.isArray(wf.branches) ? wf.branches : [];
    const nodes = Array.isArray(wf.nodes) ? wf.nodes : [];
    if (branches.length) parts.push(`Workflow ${branches.length} 個分支`);
    else if (nodes.length) parts.push(`Workflow 圖（${nodes.length} 個節點）`);
    else parts.push("Workflow（無條件）");
  } else {
    const price = formatTradingPointsValue(bot.trigger_price_points || 0);
    if (bot.trigger_type === "price_above") parts.push(`價格 ≥ ${price} 點時觸發`);
    else if (bot.trigger_type === "price_below") parts.push(`價格 ≤ ${price} 點時觸發`);
    else parts.push("每次掃描觸發");
  }
  const action = bot.side === "sell" ? "賣出" : "買入";
  const order = bot.order_type === "limit" ? `限價 ${formatTradingPointsValue(bot.limit_price_points)} 點` : "市價單";
  parts.push(`${action} · ${order}`);
  parts.push(tradingBotBudgetText(bot));
  if (bot.quantity_text) parts.push(`數量：${bot.quantity_text}`);
  if (Number(bot.cooldown_seconds || 0) > 0) parts.push(`冷卻 ${bot.cooldown_seconds}s`);
  return parts.join(" · ");
}

function tradingBotRecentFills(bot) {
  if (!bot) return [];
  const orderUuids = new Set();
  const botRuns = Array.isArray(tradingState.botRuns) ? tradingState.botRuns : [];
  botRuns.forEach((run) => {
    const sameBot = (bot.id && Number(run.bot_id || 0) === Number(bot.id)) || (bot.bot_uuid && run.bot_uuid === bot.bot_uuid);
    if (sameBot && run.order_uuid) orderUuids.add(run.order_uuid);
  });
  const gridOrders = Array.isArray(bot.orders) ? bot.orders : [];
  gridOrders.forEach((order) => {
    if (order?.trading_order_uuid) orderUuids.add(order.trading_order_uuid);
    if (order?.order_uuid) orderUuids.add(order.order_uuid);
  });
  return (Array.isArray(tradingState.fills) ? tradingState.fills : [])
    .filter((fill) => {
      if (fill?.order_uuid && orderUuids.has(fill.order_uuid)) return true;
      return Boolean(fill?.bot_name && bot?.name && fill.bot_name === bot.name);
    })
    .slice(0, 30);
}

function renderTradingBotFillDetails(fills = []) {
  if (!fills.length) return `<div class="drive-card-sub">尚無交易明細</div>`;
  return fills.map((fill) => {
    const side = fill.side === "sell" ? "賣出" : "買入";
    const sideClass = fill.side === "sell" ? "negative" : "positive";
    const qty = sanitize(fill.quantity || "0");
    const market = sanitize(tradingDisplaySymbol(fill.market_symbol || ""));
    const time = fill.created_at ? sanitize(String(fill.created_at).slice(0, 16).replace("T", " ")) : "-";
    const feeText = Number(fill.fee_points || 0) > 0 ? ` · 手續費 ${formatTradingPointsValue(fill.fee_points)}` : "";
    const pnl = Number(fill.realized_pnl_points || 0);
    const pnlText = Number.isFinite(pnl) && pnl !== 0
      ? ` · 已實現 <span class="${pnl >= 0 ? "positive" : "negative"}">${pnl >= 0 ? "+" : ""}${formatTradingPointsValue(pnl)}</span>`
      : "";
    return `<div class="drive-card-sub" style="white-space:normal;">
      <span class="${sideClass}" style="font-weight:600;">${side}</span>
      ${market} ${qty} @ ${formatTradingPointsValue(fill.execution_price_points || fill.price_points || 0)}
      ${feeText}${pnlText}
      <span style="color:var(--muted);"> · ${time}</span>
    </div>`;
  }).join("");
}

function renderMyBotsList() {
  const container = $("trading-my-bots-list");
  if (!container) return;
  const dcaBots = (tradingState.bots || []).filter((b) => b.bot_type === "dca");
  const workflowBots = (tradingState.bots || []).filter((b) => b.bot_type !== "dca");
  const gridBots = tradingGridBots || [];
  if (!dcaBots.length && !workflowBots.length && !gridBots.length) {
    container.innerHTML = `<div class="drive-empty">尚無機器人，在各設定頁新增</div>`;
    return;
  }
  const priceMap = {};
  for (const m of (tradingState.markets || [])) {
    priceMap[m.symbol] = tradingMarketPricePoints(m, "reference");
  }

  const rows = [];

  for (const bot of dcaBots) {
    const symbol = sanitize(tradingDisplaySymbol(bot.market_symbol || ""));
    const condHtml = (Array.isArray(bot.condition_checks) ? bot.condition_checks : []).map(
      (c) => `<span class="${c.met ? "trading-condition-met" : "trading-condition-unmet"}">${sanitize(c.label)}</span>`
    ).join("") || "";
    const fills = tradingBotRecentFills(bot);
    rows.push(`<div class="drive-file-row" data-mybot-uuid="${sanitize(bot.bot_uuid || "")}" data-mybot-type="dca">
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;">
          <span class="grid-status-badge" style="background:rgba(79,195,247,.18);color:#4fc3f7;">定投</span>
          <strong>${sanitize(bot.name || "定投機器人")} · ${symbol}</strong>
          <span class="grid-status-badge ${bot.enabled ? "grid-status-running" : "grid-status-stopped"}">${bot.enabled ? "運行中" : "已暫停"}</span>
        </div>
	        <div class="drive-card-sub">已觸發 ${Number(bot.run_count || 0)} / ${tradingBotMaxRunsLabel(bot)} · 冷卻 ${Number(bot.cooldown_seconds || 0)} 秒${bot.last_error ? ` · <span class="negative">上次錯誤：${sanitize(bot.last_error)}</span>` : ""}</div>
	        <div class="drive-card-sub">${sanitize(tradingRiskTargetText(bot.stop_loss_percent, bot.take_profit_percent))}${tradingParameterShareBadge(bot)}</div>
        ${condHtml ? `<div class="drive-card-sub trading-bot-conditions">${condHtml}</div>` : ""}
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>設定摘要</summary>
          <div class="drive-card-sub">${sanitize(bot.bot_type_label || "定投機器人")} · ${sanitize(bot.order_type === "limit" ? `限價 ${bot.limit_price_points}` : "市價單")} · 每次 ${sanitize(bot.quantity_text || "?")}</div>
        </details>
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>交易明細（${fills.length} 筆）</summary>
          ${renderTradingBotFillDetails(fills)}
        </details>
      </div>
      <div class="drive-file-actions" style="flex-shrink:0;">
        <button class="btn btn-sm" type="button" data-chart-type="dca" data-chart-bot-uuid="${sanitize(bot.bot_uuid || "")}" data-chart-symbol="${sanitize(bot.market_symbol || "")}">圖表</button>
	        <button class="btn btn-sm" type="button" data-trading-bot-backtest="${sanitize(bot.bot_uuid || "")}">回測</button>
	        <button class="btn btn-sm" type="button" data-trading-bot-share="${sanitize(bot.bot_uuid || "")}" data-trading-bot-share-enabled="${bot.share_parameters ? "0" : "1"}">${bot.share_parameters ? "停止分享" : "分享參數"}</button>
	        ${tradingBotRunLimitReached(bot) ? `<button class="btn btn-sm" type="button" data-trading-bot-increase-runs="${sanitize(bot.bot_uuid || "")}">增加次數</button>` : ""}
        <button class="btn btn-sm" type="button" data-trading-bot-toggle="${sanitize(bot.bot_uuid || "")}" data-trading-bot-enabled="${bot.enabled ? "0" : "1"}">${bot.enabled ? "暫停" : "啟用"}</button>
        <button class="btn btn-sm btn-danger" type="button" data-trading-bot-delete="${sanitize(bot.bot_uuid || "")}">刪除</button>
      </div>
    </div>`);
  }

  for (const bot of workflowBots) {
    const symbol = sanitize(tradingDisplaySymbol(bot.market_symbol || ""));
    const condHtml = (Array.isArray(bot.condition_checks) ? bot.condition_checks : []).map(
      (c) => `<span class="${c.met ? "trading-condition-met" : "trading-condition-unmet"}">${sanitize(c.label)}</span>`
    ).join("") || "";
    const fills = tradingBotRecentFills(bot);
    rows.push(`<div class="drive-file-row" data-mybot-uuid="${sanitize(bot.bot_uuid || "")}" data-mybot-type="workflow">
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;">
          <span class="grid-status-badge" style="background:rgba(167,139,250,.18);color:#a78bfa;">Workflow</span>
          <strong>${sanitize(bot.name || "Workflow 機器人")} · ${symbol}</strong>
          <span class="grid-status-badge ${bot.enabled ? "grid-status-running" : "grid-status-stopped"}">${bot.enabled ? "運行中" : "已暫停"}</span>
        </div>
	        <div class="drive-card-sub">已觸發 ${Number(bot.run_count || 0)} / ${tradingBotMaxRunsLabel(bot)} · ${sanitize(bot.side === "sell" ? "賣出" : "買入")} · ${sanitize(bot.order_type === "limit" ? `限價 ${bot.limit_price_points}` : "市價單")}${tradingParameterShareBadge(bot)}${bot.last_error ? ` · <span class="negative">上次錯誤：${sanitize(bot.last_error)}</span>` : ""}</div>
        <div class="drive-card-sub">${sanitize(tradingBotBudgetText(bot))}</div>
        ${condHtml ? `<div class="drive-card-sub trading-bot-conditions">${condHtml}</div>` : ""}
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>設定摘要</summary>
          <div class="drive-card-sub">${sanitize(tradingWorkflowBotDetail(bot))}</div>
        </details>
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>交易明細（${fills.length} 筆）</summary>
          ${renderTradingBotFillDetails(fills)}
        </details>
      </div>
      <div class="drive-file-actions" style="flex-shrink:0;">
	        <button class="btn btn-sm" type="button" data-chart-type="workflow" data-chart-bot-uuid="${sanitize(bot.bot_uuid || "")}" data-chart-symbol="${sanitize(bot.market_symbol || "")}">圖表</button>
	        <button class="btn btn-sm" type="button" data-trading-bot-backtest="${sanitize(bot.bot_uuid || "")}">回測</button>
	        <button class="btn btn-sm" type="button" data-trading-bot-share="${sanitize(bot.bot_uuid || "")}" data-trading-bot-share-enabled="${bot.share_parameters ? "0" : "1"}">${bot.share_parameters ? "停止分享" : "分享參數"}</button>
	        <button class="btn btn-sm" type="button" data-trading-bot-budget="${sanitize(bot.bot_uuid || "")}">調整可用</button>
	        ${tradingBotRunLimitReached(bot) ? `<button class="btn btn-sm" type="button" data-trading-bot-increase-runs="${sanitize(bot.bot_uuid || "")}">增加次數</button>` : ""}
        <button class="btn btn-sm" type="button" data-trading-bot-toggle="${sanitize(bot.bot_uuid || "")}" data-trading-bot-enabled="${bot.enabled ? "0" : "1"}">${bot.enabled ? "暫停" : "啟用"}</button>
        <button class="btn btn-sm btn-danger" type="button" data-trading-bot-delete="${sanitize(bot.bot_uuid || "")}">刪除</button>
      </div>
    </div>`);
  }

  for (const bot of gridBots) {
    const cp = priceMap[bot.market_symbol] || bot.initial_price_points || 0;
    const symbol = sanitize(tradingDisplaySymbol(bot.market_symbol || ""));
    const profit = Number(bot.total_profit_points || 0);
    const profitClass = profit >= 0 ? "positive" : "negative";
    const fills = tradingBotRecentFills(bot);
    rows.push(`<div class="drive-file-row" data-mybot-uuid="${sanitize(bot.bot_uuid || "")}" data-mybot-type="grid">
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;">
          <span class="grid-status-badge" style="background:rgba(34,197,94,.18);color:#22c55e;">網格</span>
          <strong>${sanitize(bot.name || "網格機器人")} · ${symbol}</strong>
          <span class="grid-status-badge ${bot.enabled ? "grid-status-running" : "grid-status-stopped"}">${bot.enabled ? "運行中" : "已暫停"}</span>
        </div>
        <div class="drive-card-sub">
          區間 ${formatTradingPointsValue(bot.lower_price_points)} ～ ${formatTradingPointsValue(bot.upper_price_points)} · ${Number(bot.grid_count)} 格 · 現價 ${formatTradingPointsValue(cp)}
        </div>
        <div class="drive-card-sub">
	          成交 ${Number(bot.total_trades || 0)} 次 · 盈虧 <span class="${profitClass}">${profit >= 0 ? "+" : ""}${formatTradingPointsValue(profit)}</span> 點
	          ${tradingParameterShareBadge(bot)}
	        </div>
        <div class="drive-card-sub">${sanitize(tradingRiskTargetText(bot.stop_loss_percent, bot.take_profit_percent))}</div>
        ${bot.last_error ? `<div class="drive-card-sub negative">錯誤：${sanitize(bot.last_error)}</div>` : ""}
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>設定摘要</summary>
          <div class="drive-card-sub">${sanitize(symbol)} · 區間 ${formatTradingPointsValue(bot.lower_price_points)} ～ ${formatTradingPointsValue(bot.upper_price_points)} · ${Number(bot.grid_count)} 格 · 每格 ${formatTradingPointsValue(bot.order_amount_points)} 點</div>
        </details>
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>掛單明細（${(Array.isArray(bot.orders) ? bot.orders : []).filter((o) => o.status === "open").length} 筆掛單）</summary>
          ${renderGridBotVisual(bot, cp)}
        </details>
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>交易明細（${fills.length} 筆）</summary>
          ${renderTradingBotFillDetails(fills)}
        </details>
      </div>
      <div class="drive-file-actions" style="flex-shrink:0;">
	        <button class="btn btn-sm" type="button" data-chart-type="grid" data-chart-bot-uuid="${sanitize(bot.bot_uuid || "")}" data-chart-symbol="${sanitize(bot.market_symbol || "")}">圖表</button>
	        <button class="btn btn-sm" type="button" data-grid-backtest="${sanitize(bot.bot_uuid || "")}">回測</button>
	        <button class="btn btn-sm" type="button" data-grid-share="${sanitize(bot.bot_uuid || "")}" data-grid-share-enabled="${bot.share_parameters ? "0" : "1"}">${bot.share_parameters ? "停止分享" : "分享參數"}</button>
	        <button class="btn btn-sm" type="button" data-grid-toggle="${sanitize(bot.bot_uuid || "")}" data-grid-enabled="${bot.enabled ? "0" : "1"}">${bot.enabled ? "暫停" : "啟用"}</button>
        <button class="btn btn-sm btn-danger" type="button" data-grid-delete="${sanitize(bot.bot_uuid || "")}">立即平倉刪除</button>
      </div>
    </div>`);
  }

  container.innerHTML = rows.join("");

  container.querySelectorAll("[data-chart-type]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setBotChartOverlay(btn.dataset.chartType, btn.dataset.chartBotUuid || "", btn.dataset.chartSymbol || "");
    });
  });
  container.querySelectorAll("[data-trading-bot-delete]").forEach((btn) => {
    bindTradingActionButton(btn, () => deleteTradingBot(btn.dataset.tradingBotDelete || ""), "準備刪除交易機器人...", "交易機器人刪除失敗");
  });
  container.querySelectorAll("[data-trading-bot-toggle]").forEach((btn) => {
    bindTradingActionButton(
      btn,
      () => toggleTradingBot(btn.dataset.tradingBotToggle || "", btn.dataset.tradingBotEnabled === "1"),
      btn.dataset.tradingBotEnabled === "1" ? "準備啟用..." : "準備暫停...",
      "機器人狀態更新失敗"
    );
  });
  container.querySelectorAll("[data-trading-bot-increase-runs]").forEach((btn) => {
    bindTradingActionButton(btn, () => increaseTradingBotMaxRuns(btn.dataset.tradingBotIncreaseRuns || ""), "正在增加可執行次數...", "增加機器人次數失敗");
  });
  container.querySelectorAll("[data-trading-bot-budget]").forEach((btn) => {
    bindTradingActionButton(btn, () => adjustTradingBotBudget(btn.dataset.tradingBotBudget || ""), "正在調整機器人可用上限...", "調整機器人可用上限失敗");
  });
	  container.querySelectorAll("[data-trading-bot-backtest]").forEach((btn) => {
	    bindTradingActionButton(btn, () => prepareTradingBacktestFromBot(btn.dataset.tradingBotBacktest || ""), "正在帶入回測設定...", "回測設定帶入失敗");
	  });
	  container.querySelectorAll("[data-trading-bot-share]").forEach((btn) => {
	    bindTradingActionButton(
	      btn,
	      () => setTradingBotParameterShare(btn.dataset.tradingBotShare || "", btn.dataset.tradingBotShareEnabled === "1"),
	      btn.dataset.tradingBotShareEnabled === "1" ? "正在開啟參數分享..." : "正在停止參數分享...",
	      "參數分享狀態更新失敗"
	    );
	  });
  container.querySelectorAll("[data-grid-toggle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const uuid = btn.dataset.gridToggle;
      const enable = btn.dataset.gridEnabled === "1";
      btn.disabled = true;
      try {
        const csrf = await tradingFreshCsrfToken();
        const res = await apiFetch(`${API}/trading/grid-bots/${uuid}/toggle`, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
          body: JSON.stringify({ enabled: enable }),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json.ok) { tradingSetMsg(tradingFriendlyErrorText(json.msg || "狀態更新失敗"), false); return; }
        await loadGridBots();
        renderMyBotsList();
      } catch (e) { tradingSetMsg(e.message || "網格機器人狀態更新失敗", false); }
      finally { btn.disabled = false; }
    });
  });
	  container.querySelectorAll("[data-grid-delete]").forEach((btn) => {
	    bindTradingActionButton(btn, () => deleteGridBot(btn.dataset.gridDelete || ""), "正在刪除網格機器人...", "網格機器人刪除失敗");
	  });
	  container.querySelectorAll("[data-grid-share]").forEach((btn) => {
	    bindTradingActionButton(
	      btn,
	      () => setGridBotParameterShare(btn.dataset.gridShare || "", btn.dataset.gridShareEnabled === "1"),
	      btn.dataset.gridShareEnabled === "1" ? "正在開啟網格參數分享..." : "正在停止網格參數分享...",
	      "網格參數分享狀態更新失敗"
	    );
	  });
  container.querySelectorAll("[data-grid-backtest]").forEach((btn) => {
    bindTradingActionButton(btn, () => prepareTradingBacktestFromBot(btn.dataset.gridBacktest || ""), "正在帶入回測設定...", "回測設定帶入失敗");
  });
}

function clearBotChartOverlay() {
  tradingBotChartOverlay = null;
  const btn = $("trading-chart-clear-overlay-btn");
  if (btn) btn.style.display = "none";
  if (tradingState.referencePrices) renderTradingReferenceChart(tradingState.referencePrices);
}

function setBotChartOverlay(type, botUuid, marketSymbol) {
  if (type === "grid") {
    const bot = (tradingGridBots || []).find((b) => b.bot_uuid === botUuid);
    if (!bot) return;
    const levels = Array.isArray(bot.grid_levels) ? bot.grid_levels : [];
    tradingBotChartOverlay = { type: "grid", levels, symbol: marketSymbol };
  } else {
    const bot = (tradingState.bots || []).find((b) => b.bot_uuid === botUuid);
    if (!bot) return;
    const botRuns = (tradingState.botRuns || []).filter((r) => (Number(r.bot_id) === Number(bot.id) || r.bot_uuid === bot.bot_uuid) && r.status === "triggered");
    const runs = botRuns.map((r) => ({
      time: new Date(r.created_at || 0).getTime(),
      price: Number(r.observed_price_points || 0),
      side: bot.side || "buy",
    })).filter((r) => r.time > 0 && r.price > 0);
    tradingBotChartOverlay = { type: "bot", runs, symbol: marketSymbol };
  }
  const clearBtn = $("trading-chart-clear-overlay-btn");
  if (clearBtn) clearBtn.style.display = "";

  // Switch chart market to bot's market and reload
  const marketSelect = $("trading-market-select");
  if (marketSelect && marketSymbol && marketSelect.value !== marketSymbol) {
    if (Array.from(marketSelect.options).some((o) => o.value === marketSymbol)) {
      marketSelect.value = marketSymbol;
      renderTradingSummary();
    }
  }
  loadTradingReferencePrices().catch(() => {
    if (tradingState.referencePrices) renderTradingReferenceChart(tradingState.referencePrices);
  });
  tradingSetMsg(`圖表已切換到 ${tradingDisplaySymbol(marketSymbol || "")}，標記 ${type === "grid" ? "網格層級" : "交易點位"}`);
}

function drawBotChartOverlay(ctx, overlay, yForPrice, pad, width, chartH, candles) {
  if (!overlay) return;
  const chartMarket = tradingState.referencePrices?.market;
  if (chartMarket && overlay.symbol && chartMarket !== overlay.symbol) return;
  ctx.save();
  if (overlay.type === "grid") {
    ctx.setLineDash([5, 3]);
    const n = overlay.levels.length;
    overlay.levels.forEach((price, i) => {
      const y = yForPrice(price);
      if (y < pad.top - 2 || y > pad.top + chartH + 2) return;
      const isBoundary = i === 0 || i === n - 1;
      ctx.strokeStyle = isBoundary ? "rgba(239,68,68,.6)" : "rgba(250,204,21,.4)";
      ctx.lineWidth = isBoundary ? 1.5 : 0.8;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(width - pad.right, y);
      ctx.stroke();
    });
    ctx.setLineDash([]);
  } else if (overlay.type === "bot") {
    overlay.runs.forEach(({ time, price, side }) => {
      const y = yForPrice(price);
      if (y < pad.top || y > pad.top + chartH) return;
      let nearestX = null;
      let minDiff = Infinity;
      for (const c of candles) {
        const cTime = Number(c.time || 0);
        const diff = Math.abs(cTime - time);
        if (diff < minDiff) { minDiff = diff; nearestX = c.x; }
      }
      if (nearestX == null) return;
      const sz = 9;
      ctx.beginPath();
      if (side === "buy") {
        ctx.fillStyle = "rgba(34,197,94,.92)";
        ctx.moveTo(nearestX, y - sz);
        ctx.lineTo(nearestX - sz * 0.8, y + sz * 0.5);
        ctx.lineTo(nearestX + sz * 0.8, y + sz * 0.5);
      } else {
        ctx.fillStyle = "rgba(239,68,68,.92)";
        ctx.moveTo(nearestX, y + sz);
        ctx.lineTo(nearestX - sz * 0.8, y - sz * 0.5);
        ctx.lineTo(nearestX + sz * 0.8, y - sz * 0.5);
      }
      ctx.closePath();
      ctx.fill();
    });
  }
  ctx.restore();
}

// ── Grid Trading Bot ────────────────────────────────────────────────────────

let tradingGridBots = [];
let tradingGridPreviewState = null;
let tradingGridPreviewTimer = null;
let tradingGridPreviewRequestSeq = 0;

function gridComputeLevels(lower, upper, count, mode) {
  if (count < 2 || lower <= 0 || upper <= lower) return [];
  const levels = [];
  if (mode === "geometric") {
    const ratio = Math.pow(upper / lower, 1 / (count - 1));
    for (let i = 0; i < count; i++) levels.push(Math.round(lower * Math.pow(ratio, i)));
  } else {
    const step = (upper - lower) / (count - 1);
    for (let i = 0; i < count; i++) levels.push(Math.round(lower + step * i));
  }
  return levels;
}

// 6 grid presets keyed off current market reference price. Numbers
// validated in security/competition_grid_skyfloor_test.py + the spacing
// follow-up in security/competition_grid_spacing_test.py against 5
// assets × 5y × 1h. Each preset declares its OWN best spacing_mode
// based on that data — most sky-floor variants prefer geometric (a few
// pp better), but skyfloor_5x's 100× range actually favours arithmetic
// by ~19pp because the wider absolute steps capture larger per-grid
// profit when price moves are big.
const TRADING_GRID_PRESETS = {
  conservative:    { lower_factor: 0.80, upper_factor: 1.20, grid_count: 10,  order_amount: 5000, spacing_mode: "arithmetic" },
  balanced:        { lower_factor: 0.50, upper_factor: 1.50, grid_count: 20,  order_amount: 5000, spacing_mode: "arithmetic" },
  skyfloor_narrow: { lower_factor: 0.20, upper_factor: 1.80, grid_count: 50,  order_amount: 2000, spacing_mode: "geometric" },
  skyfloor_mid:    { lower_factor: 0.10, upper_factor: 3.00, grid_count: 50,  order_amount: 2000, spacing_mode: "geometric" },
  skyfloor_wide:   { lower_factor: 0.10, upper_factor: 3.00, grid_count: 100, order_amount: 1000, spacing_mode: "geometric" },
  // skyfloor_5x: 100× range; arithmetic empirically beats geometric by ~19pp
  // on the 5y benchmark — see GRID_SPACING_COMPARISON.md.
  skyfloor_5x:     { lower_factor: 0.05, upper_factor: 5.00, grid_count: 100, order_amount: 1000, spacing_mode: "arithmetic" },
};

function tradingSetGridPresetFieldValue(id, value, { notify = true } = {}) {
  const el = $(id);
  if (!el) return;
  el.value = String(value);
  if (!notify) return;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function tradingGridPresetMarket() {
  const markets = Array.isArray(tradingState.markets) ? tradingState.markets : [];
  const select = $("trading-grid-bot-market");
  const selectedSymbol = select?.value || "";
  const botMarkets = markets.filter((market) => market.allow_bots !== false);
  let market = botMarkets.find((row) => row.symbol === selectedSymbol) || null;
  if (!market) {
    const activeMarket = selectedTradingMarket();
    if (activeMarket && activeMarket.allow_bots !== false) market = activeMarket;
  }
  if (!market) market = botMarkets[0] || markets[0] || null;
  if (select && market?.symbol && Array.from(select.options || []).some((option) => option.value === market.symbol)) {
    select.value = market.symbol;
  }
  return market;
}

function tradingGridPresetReferencePrice(market) {
  return tradingMarketPricePoints(market, "reference") || tradingMarketPricePoints(market, "risk_grade");
}

function applyGridPreset(options = {}) {
  const opts = options && options.type ? {} : (options || {});
  const quiet = !!opts.quiet;
  const shouldSave = opts.save !== false;
  const select = $("trading-grid-preset");
  if (!select) return;
  const key = select.value || "";
  if (!key) return;
  const cfg = TRADING_GRID_PRESETS[key];
  if (!cfg) return;
  const market = tradingGridPresetMarket();
  if (!market?.symbol) {
    if (!quiet) tradingSetMsg("請先選擇市場再套用預設");
    return;
  }
  const refPrice = tradingGridPresetReferencePrice(market);
  if (!refPrice || refPrice <= 0) {
    if (!quiet) tradingSetMsg("該市場目前沒有可參考的市價，無法計算上下限");
    return;
  }
  const lower = Math.max(1, Math.round(refPrice * cfg.lower_factor));
  const upper = Math.max(lower + 1, Math.round(refPrice * cfg.upper_factor));
  tradingSetGridPresetFieldValue("trading-grid-lower-price", lower);
  tradingSetGridPresetFieldValue("trading-grid-upper-price", upper);
  tradingSetGridPresetFieldValue("trading-grid-count", cfg.grid_count);
  tradingSetGridPresetFieldValue("trading-grid-order-amount", cfg.order_amount);
  // Each preset carries its own empirically-tuned spacing_mode; see
  // docs/archive/competition_2026-05-06/GRID_SPACING_COMPARISON.md for the
  // per-config table.
  if (cfg.spacing_mode) tradingSetGridPresetFieldValue("trading-grid-spacing-mode", cfg.spacing_mode);
  if (shouldSave) saveTradingPersonalFormState();
  if (typeof scheduleGridBotPreview === "function") scheduleGridBotPreview();
  if (!quiet) tradingSetMsg(`已套用預設「${key}」（市價 ${refPrice}） — 區間 ${lower}–${upper}，間距 ${cfg.spacing_mode}`);
}

function clearGridBotPreview() {
  tradingGridPreviewState = null;
  const preview = $("trading-grid-preview");
  if (preview) preview.innerHTML = "";
}

function collectGridBotPreviewPayload() {
  const marketSymbol = $("trading-grid-bot-market")?.value || "";
  const upper = Number($("trading-grid-upper-price")?.value || 0);
  const lower = Number($("trading-grid-lower-price")?.value || 0);
  const count = Number($("trading-grid-count")?.value || 10);
  const amount = Number($("trading-grid-order-amount")?.value || 0);
  const mode = $("trading-grid-spacing-mode")?.value || "arithmetic";
  if (!upper || !lower || upper <= lower || count < 2 || amount < 1) {
    return null;
  }
  if (!marketSymbol) return null;
  return {
    market_symbol: marketSymbol,
    upper_price_points: upper,
    lower_price_points: lower,
    grid_count: count,
    order_amount_points: amount,
    spacing_mode: mode,
    order_mode: "maker",
  };
}

function scheduleGridBotPreview() {
  if (tradingGridPreviewTimer) clearTimeout(tradingGridPreviewTimer);
  tradingGridPreviewTimer = setTimeout(() => {
    renderGridBotPreview({ quiet: true }).catch(() => {});
  }, 150);
}

async function renderGridBotPreview({ quiet = true } = {}) {
  const preview = $("trading-grid-preview");
  if (!preview) return null;
  const payload = collectGridBotPreviewPayload();
  if (!payload) {
    clearGridBotPreview();
    return null;
  }
  const upper = Number(payload.upper_price_points || 0);
  const lower = Number(payload.lower_price_points || 0);
  const count = Number(payload.grid_count || 10);
  const amount = Number(payload.order_amount_points || 0);
  const mode = payload.spacing_mode || "arithmetic";
  const levels = gridComputeLevels(lower, upper, count, mode);
  if (levels.length < 2) {
    clearGridBotPreview();
    return null;
  }
  const requestSeq = ++tradingGridPreviewRequestSeq;
  let feePreview = null;
  try {
    const csrf = await tradingFreshCsrfToken();
    const res = await apiFetch(`${API}/trading/grid/preview`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload),
    });
    const json = await res.json().catch(() => ({}));
    if (requestSeq !== tradingGridPreviewRequestSeq) return tradingGridPreviewState;
    if (!res.ok || !json.ok) {
      tradingGridPreviewState = null;
      preview.innerHTML = `<div class="negative">網格試算失敗：${sanitize(tradingFriendlyErrorText(json.msg || "無法計算目前設定"))}</div>`;
      if (!quiet) tradingSetMsg(tradingFriendlyErrorText(json.msg || "網格試算失敗"), false);
      return null;
    }
    feePreview = json;
    tradingGridPreviewState = json;
  } catch (e) {
    if (requestSeq !== tradingGridPreviewRequestSeq) return tradingGridPreviewState;
    tradingGridPreviewState = null;
    preview.innerHTML = `<div class="negative">網格試算失敗：${sanitize(e.message || "請稍後再試")}</div>`;
    if (!quiet) tradingSetMsg(e.message || "網格試算失敗", false);
    return null;
  }

  const market = (tradingState.markets || []).find((m) => m.symbol === payload.market_symbol);
  const feeRatePct = market ? Number(market.fee_rate_percent || 0) : 0;
  const gridDiscountPct = Math.max(0, Math.min(100, tradingNumber(tradingState.settings?.grid_fee_discount_percent, 25)));
  const stepPcts = levels.slice(1).map((p, i) => ((p - levels[i]) / levels[i]) * 100);
  const minStepPct = Math.min(...stepPcts);
  const maxStepPct = Math.max(...stepPcts);
  const arithmeticStep = Math.round((upper - lower) / (count - 1));
  const stepInfo = mode === "geometric"
    ? `固定間距 ${minStepPct.toFixed(2)}%（等比）`
    : `固定間距 ${formatTradingPointsValue(arithmeticStep)} 點（等差）`;
  const midStepPct = ((upper - lower) / (count - 1) / ((upper + lower) / 2) * 100).toFixed(2);

  // Estimate current price from market or use midpoint
  const marketPrice = market ? tradingMarketPricePoints(market, "reference") : 0;
  const refPrice = marketPrice || Math.round((upper + lower) / 2);
  const buyLevels = levels.filter((p) => p < refPrice);
  const sellLevels = levels.filter((p) => p > refPrice);
  // Buy orders: freeze amount + fee per level
  const gridBuyFeePercent = tradingNumber(feePreview?.fee_model?.buy_fee_percent, feeRatePct * ((100 - gridDiscountPct) / 100));
  const feePerBuyOrder = Math.max(0, amount * gridBuyFeePercent / 100);
  const buyOrderCost = amount + feePerBuyOrder;
  const buyCostTotal = buyLevels.length * buyOrderCost;
  // Sell orders: need spot inventory (asset units); estimate cost at current price
  const spotUnitsNeeded = sellLevels.reduce((sum, p) => sum + (p > 0 ? amount / p : 0), 0);
  const assetLabel = market ? tradingDisplaySymbol(market.symbol).split("/")[0] : "資產";
  const spotDisplay = spotUnitsNeeded > 0 ? `約 ${spotUnitsNeeded.toFixed(6)} 個 ${assetLabel}` : "0";
  // Spot acquisition cost at current price + buy fee (full rate, not grid discount)
  const spotValueAtRefPrice = spotUnitsNeeded * refPrice;
  const spotBuyFee = spotValueAtRefPrice * feeRatePct / 100;
  const spotTotalCost = Math.ceil(spotValueAtRefPrice + spotBuyFee);
  // Total capital if opening ALL orders from scratch (buy frozen + spot acquisition)
  const totalCapital = Math.ceil(buyCostTotal) + spotTotalCost;
  const feeReserve = Number(feePreview?.grid_profit?.estimated_total_fee || 0);

  let feeHtml = "";
  if (feePreview) {
    const risk = feePreview.risk || {};
    const riskStatus = risk.status || "green";
    const riskColor = riskStatus === "green" ? "#16a34a" : (riskStatus === "yellow" ? "#f59e0b" : "#ef4444");
    const riskLabel = riskStatus === "green" ? "綠燈" : (riskStatus === "yellow" ? "黃燈" : "紅燈");
    feeHtml = `
      <div style="margin-top:.55rem;padding:.75rem;border:1px solid ${riskColor};border-radius:.6rem;background:rgba(15,23,42,.03);">
        <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin-bottom:.35rem;">
          <strong style="color:${riskColor};">${riskLabel}</strong>
          <span>網格費率試算（限價掛單 / maker）</span>
        </div>
        <div>每格間距：${formatTradingPointsValue(feePreview.grid_profit?.grid_spacing_percent || 0)}%</div>
        <div>買入手續費：${formatTradingPointsValue(feePreview.fee_model?.buy_fee_percent || 0)}% · 賣出手續費：${formatTradingPointsValue(feePreview.fee_model?.sell_fee_percent || 0)}% · 來回：${formatTradingPointsValue(feePreview.fee_model?.round_trip_fee_percent || 0)}%</div>
        <div>損益兩平間距：約 ${formatTradingPointsValue(feePreview.break_even?.min_spread_percent || 0)}%</div>
        <div>最不利一格毛利：約 ${formatTradingPointsValue(feePreview.grid_profit?.estimated_gross_profit_per_grid || 0)} 點</div>
        <div>最不利一格手續費：約 ${formatTradingPointsValue(feePreview.grid_profit?.estimated_fee_per_grid || 0)} 點</div>
        <div>最不利一格扣費後淨利：約 ${formatTradingPointsValue(feePreview.grid_profit?.estimated_net_profit_per_grid || 0)} 點（${formatTradingPointsValue(feePreview.grid_profit?.estimated_net_spread_percent || 0)}%）</div>
        <div>預估一輪全格總手續費：約 ${formatTradingPointsValue(feePreview.grid_profit?.estimated_total_fee || 0)} 點 · 預估一輪全格總淨利：約 ${formatTradingPointsValue(feePreview.grid_profit?.estimated_total_net_profit || 0)} 點</div>
        <div style="margin-top:.35rem;color:${riskColor};font-weight:600;">${sanitize(risk.message || "")}</div>
        <div style="margin-top:.25rem;color:var(--muted);font-size:.82em;">現貨基礎費率 ${formatTradingPointsValue(feePreview.fee_model?.spot_fee_percent || feeRatePct)}%，Grid 折扣 ${formatTradingPointsValue(feePreview.fee_model?.grid_discount_percent || gridDiscountPct)}%。實際建立網格前仍會由後端再次驗證，不接受前端自行改值。</div>
      </div>
    `.trim();
  }

  const capitalBreakdown = refPrice > 0
    ? `買單凍結 ${formatTradingPointsValue(Math.ceil(buyCostTotal))} ＋ 賣單底倉 ${formatTradingPointsValue(spotTotalCost)}（以現價購入含手續費）${feeReserve > 0 ? ` ＋ 手續費預留 ${formatTradingPointsValue(feeReserve)}` : ""}`
    : `買單凍結 ${formatTradingPointsValue(Math.ceil(buyCostTotal))}（賣單需現有底倉 ${spotDisplay}，無現價無法估算購入成本）`;
  const totalLine = refPrice > 0
    ? `<div style="margin-top:.35rem;font-weight:600;">預估開單所需總資金：${formatTradingPointsValue(totalCapital + feeReserve)} 點</div><div style="color:var(--muted);font-size:.82em;">${capitalBreakdown}</div>`
    : `<div style="margin-top:.35rem;">買單 ${buyLevels.length} 格需 ${formatTradingPointsValue(Math.ceil(buyCostTotal))} 點，賣單 ${sellLevels.length} 格需底倉 ${spotDisplay}</div>`;

  preview.innerHTML = `
    <div>${count} 格，${stepInfo}（中間位約 ${midStepPct}%），每格 ${formatTradingPointsValue(amount)} 點</div>
    <div>買單 ${buyLevels.length} 格（凍結積分），賣單 ${sellLevels.length} 格（需底倉 ${spotDisplay}）</div>
    ${totalLine}
    ${feeHtml}
  `.trim();
  return feePreview;
}

function renderGridBotVisual(bot, currentPrice) {
  const levels = Array.isArray(bot.grid_levels) ? bot.grid_levels : [];
  if (!levels.length) return `<div class="drive-card-sub">（無網格層）</div>`;
  const orders = Array.isArray(bot.orders) ? bot.orders : [];
  const orderByLevel = {};
  // Sort by id ascending so the highest id (most recent) wins per level
  const sortedOrders = [...orders].sort((a, b) => Number(a.id || 0) - Number(b.id || 0));
  for (const o of sortedOrders) {
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

function renderGridBotFills(fills) {
  if (!fills.length) return `<div class="drive-card-sub">尚無成交紀錄</div>`;
  return fills.slice().reverse().slice(0, 30).map((o) => {
    const side = o.side === "buy" ? "買入" : "賣出";
    const cls = o.side === "buy" ? "grid-buy-count" : "grid-sell-count";
    return `<div class="drive-card-sub" style="white-space:nowrap;"><span class="${cls}">${side}</span> ${formatTradingPointsValue(o.price_points)} 點 · 第 ${Number(o.level_index) + 1} 層${o.updated_at ? " · " + sanitize(String(o.updated_at).slice(0, 16).replace("T", " ")) : ""}</div>`;
  }).join("");
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
    const assetSymbol = sanitize((tradingDisplaySymbol(bot.market_symbol || "") || "").split("/")[0] || "資產");
    const profit = Number(bot.total_profit_points || 0);
    const profitClass = profit >= 0 ? "positive" : "negative";
    const orders = Array.isArray(bot.orders) ? bot.orders : [];
    const openOrders = orders.filter((o) => o.status === "open");
    const filledOrders = orders.filter((o) => o.status === "filled");
    const fills = tradingBotRecentFills(bot);
    const buyOrders = openOrders.filter((o) => o.side === "buy");
    const sellOrders = openOrders.filter((o) => o.side === "sell");
    const levels = Array.isArray(bot.grid_levels) ? bot.grid_levels : [];
    const SCALE = 100_000_000;
    // Net inventory: buy fills - sell fills (in asset units from filled_quantity_units)
    const buyFillUnits = filledOrders.filter((o) => o.side === "buy").reduce((s, o) => s + Number(o.filled_quantity_units || 0), 0);
    const sellFillUnits = filledOrders.filter((o) => o.side === "sell").reduce((s, o) => s + Number(o.filled_quantity_units || 0), 0);
    const netInventoryUnits = buyFillUnits - sellFillUnits;
    const netInventoryDisplay = (netInventoryUnits / SCALE).toFixed(6);
    // Open orders locked value
    const buyLockedPoints = buyOrders.length * Number(bot.order_amount_points || 0);
    const sellLockedUnits = sellOrders.reduce((s, o) => s + (o.price_points > 0 ? Number(bot.order_amount_points || 0) / o.price_points : 0), 0);
    // Fee estimate: total trades × amount × grid fee rate after root-configured discount.
    const marketObj = (tradingState.markets || []).find((m) => m.symbol === bot.market_symbol);
    const feeRatePct = marketObj ? Number(marketObj.fee_rate_percent || 0) : 0;
    const gridDiscountPct = Math.max(0, Math.min(100, tradingNumber(tradingState.settings?.grid_fee_discount_percent, 25)));
    const totalTrades = Number(bot.total_trades || 0);
    const estimatedFee = totalTrades * Number(bot.order_amount_points || 0) * feeRatePct * ((100 - gridDiscountPct) / 100) / 100;
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
          現價 ${formatTradingPointsValue(cp)} · 底倉 ${netInventoryDisplay} ${assetSymbol} · 掛單：<span class="grid-buy-count">買 ${buyOrders.length} 格（${formatTradingPointsValue(buyLockedPoints)} 點）</span> / <span class="grid-sell-count">賣 ${sellOrders.length} 格（約 ${sellLockedUnits.toFixed(6)} ${assetSymbol}）</span>
        </div>
	        <div class="drive-card-sub">
	          已成交 ${totalTrades} 次 · 估計手續費支出 ${formatTradingPointsValue(Math.round(estimatedFee))} 點 · 累計盈虧 <span class="${profitClass}">${profit >= 0 ? "+" : ""}${formatTradingPointsValue(profit)}</span> 點
	          ${tradingParameterShareBadge(bot)}
	        </div>
        <div class="drive-card-sub">${sanitize(tradingRiskTargetText(bot.stop_loss_percent, bot.take_profit_percent))}</div>
        ${bot.last_error ? `<div class="drive-card-sub negative">錯誤：${sanitize(bot.last_error)}</div>` : ""}
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>設定摘要</summary>
          <div class="drive-card-sub">${sanitize(symbol)} · 區間 ${formatTradingPointsValue(bot.lower_price_points)} ～ ${formatTradingPointsValue(bot.upper_price_points)} · ${Number(bot.grid_count)} 格 · 每格 ${formatTradingPointsValue(bot.order_amount_points)} 點 · ${sanitize(tradingRiskTargetText(bot.stop_loss_percent, bot.take_profit_percent))}</div>
        </details>
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>掛單明細（${openOrders.length} 筆掛單）</summary>
          <div style="display:flex;gap:1rem;align-items:flex-start;flex-wrap:wrap;">
            <div style="flex:0 0 auto;">
              ${renderGridBotVisual(bot, cp)}
            </div>
            <div style="flex:1;min-width:160px;">
              <div class="drive-card-sub" style="margin-bottom:.25rem;font-weight:600;">掛單成交層級（${orders.filter((o) => o.status === "filled").length} 筆）</div>
              ${renderGridBotFills(orders.filter((o) => o.status === "filled"))}
            </div>
          </div>
        </details>
        <details class="economy-collapse" style="margin-top:.35rem;">
          <summary>交易明細（${fills.length} 筆）</summary>
          ${renderTradingBotFillDetails(fills)}
        </details>
      </div>
	      <div class="drive-file-actions" style="flex-shrink:0;">
	        <button class="btn btn-sm" type="button" data-grid-backtest="${sanitize(bot.bot_uuid || "")}">回測</button>
	        <button class="btn btn-sm" type="button" data-grid-share="${sanitize(bot.bot_uuid || "")}" data-grid-share-enabled="${bot.share_parameters ? "0" : "1"}">${bot.share_parameters ? "停止分享" : "分享參數"}</button>
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
        const csrf = await tradingFreshCsrfToken();
        const res = await apiFetch(`${API}/trading/grid-bots/${uuid}/toggle`, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
          body: JSON.stringify({ enabled: enable }),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json.ok) { tradingSetMsg(tradingFriendlyErrorText(json.msg || "狀態更新失敗"), false); return; }
        await loadGridBots();
      } catch (e) { tradingSetMsg(e.message || "網格機器人狀態更新失敗", false); }
      finally { btn.disabled = false; }
    });
  });
	  container.querySelectorAll("[data-grid-delete]").forEach((btn) => {
	    bindTradingActionButton(btn, () => deleteGridBot(btn.dataset.gridDelete || ""), "正在刪除網格機器人...", "網格機器人刪除失敗");
	  });
	  container.querySelectorAll("[data-grid-share]").forEach((btn) => {
	    bindTradingActionButton(
	      btn,
	      () => setGridBotParameterShare(btn.dataset.gridShare || "", btn.dataset.gridShareEnabled === "1"),
	      btn.dataset.gridShareEnabled === "1" ? "正在開啟網格參數分享..." : "正在停止網格參數分享...",
	      "網格參數分享狀態更新失敗"
	    );
	  });
  container.querySelectorAll("[data-grid-backtest]").forEach((btn) => {
    bindTradingActionButton(btn, () => prepareTradingBacktestFromBot(btn.dataset.gridBacktest || ""), "正在帶入回測設定...", "回測設定帶入失敗");
  });
}

async function deleteGridBot(uuid) {
  if (!uuid) return;
  if (!confirm("確定結束網格機器人？這會取消所有網格掛單並移除機器人。")) return;
  const sellBase = confirm("網格結束後要賣出這個網格鎖定的現貨底倉嗎？\n\n確定：用市價賣出底倉\n取消：保留為現貨底倉");
  const baseAction = sellBase ? "sell" : "keep";
  const csrf = await tradingFreshCsrfToken();
  const res = await apiFetch(`${API}/trading/grid-bots/${uuid}`, {
    method: "DELETE", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ base_action: baseAction }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(tradingFriendlyErrorText(json.msg || "刪除失敗"));
  const baseQty = formatTradingQuantityValue(Number(json.base_quantity_units || 0) / 100000000);
  if (json.sell_error) {
    tradingSetMsg(`網格機器人已結束；底倉賣出失敗，已改為保留現貨（底倉約 ${baseQty}）。${tradingFriendlyErrorText(json.sell_error)}`, false);
  } else if (baseAction === "sell") {
    tradingSetMsg(`網格機器人已結束；已送出底倉賣出（約 ${baseQty}）。`);
  } else {
    tradingSetMsg(`網格機器人已結束；底倉已保留為現貨（約 ${baseQty}）。`);
  }
  tradingGridExpandedBots.delete(uuid);
  await loadGridBots();
  await loadTradingDashboard();
}

async function loadGridBots() {
  try {
    const res = await apiFetch(`${API}/trading/grid-bots`, { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) return;
    tradingGridBots = Array.isArray(json.bots) ? json.bots : [];
    const priceMap = {};
    for (const m of (tradingState.markets || [])) {
      priceMap[m.symbol] = tradingMarketPricePoints(m, "reference");
    }
    renderGridBotList(tradingGridBots, priceMap);
    renderMyBotsList();
    refreshBacktestBotSelect();
  } catch (e) {
    // silent
  }
}

async function loadTradingBotCompetition() {
  if (!currentUser || !canAccessModule("economy")) return;
  const week = $("trading-bot-competition-week")?.value?.trim() || "";
  const path = `/trading/bot-competition${week ? `?week=${encodeURIComponent(week)}` : ""}`;
  const json = await fetchTradingJson(path, { forceCsrf: false });
  tradingState.botCompetition = json.competition || json;
  renderTradingBotCompetition(tradingState.botCompetition);
}

async function awardTradingBotCompetition() {
  if (currentUser !== "root") {
    tradingSetMsg("只有 root 可以發放競賽獎勵", false);
    return;
  }
  const week = $("trading-bot-competition-award-btn")?.dataset?.awardWeek || tradingState.botCompetition?.previous_week || "";
  const json = await fetchTradingJson("/root/trading/bot-competition/award", {
    method: "POST",
    body: JSON.stringify({ week }),
  });
  const awarded = Array.isArray(json.awarded) ? json.awarded : [];
  tradingSetMsg(awarded.length ? `已發放 ${awarded.length} 筆機器人週賽獎勵` : "沒有新的週賽獎勵需要發放");
  await loadTradingBotCompetition();
  if (typeof loadEconomyDashboard === "function") loadEconomyDashboard().catch(() => {});
}

function computeGridSpotSituation(marketSymbol, lower, upper, count, amount, mode) {
  const market = (tradingState.markets || []).find((m) => m.symbol === marketSymbol);
  const currentPrice = market ? tradingMarketPricePoints(market, "reference") : 0;
  if (!currentPrice || lower >= upper || count < 2) return null;
  const levels = gridComputeLevels(lower, upper, count, mode);
  const sellLevels = levels.filter((p) => p > currentPrice);
  if (!sellLevels.length) return null;
  const spotNeeded = sellLevels.reduce((sum, p) => sum + (p > 0 ? amount / p : 0), 0);
  const position = currentTradingPosition(marketSymbol);
  const currentSpot = tradingNumber(position?.quantity, 0) + tradingNumber(position?.locked_quantity, 0);
  const deficit = Math.max(0, spotNeeded - currentSpot);
  const feeRatePct = market ? tradingNumber(market.fee_rate_percent, 0) : 0;
  const assetSymbol = (tradingDisplaySymbol(marketSymbol) || "").split("/")[0] || "資產";
  return { spotNeeded, currentSpot, deficit, currentPrice, feeRatePct, market, assetSymbol, sellLevels };
}

function showGridSpotConfirm(situation, formData) {
  const confirmDiv = $("trading-grid-spot-confirm");
  if (!confirmDiv) { doCreateGridBot(formData); return; }
  const { spotNeeded, currentSpot, deficit, currentPrice, feeRatePct, assetSymbol } = situation;
  const fmtQty = (n) => n.toFixed(6);

  let html = "";
  if (deficit <= 0) {
    // Sufficient spot
    html = `<div class="drive-card-sub" style="margin-top:.5rem;padding:.75rem;border:1px solid var(--accent,#4fc3f7);border-radius:.5rem;">
      <div style="font-weight:600;margin-bottom:.5rem;">確認底倉</div>
      <div style="margin-bottom:.5rem;">你目前持有 <strong>${fmtQty(currentSpot)} ${sanitize(assetSymbol)}</strong>，足夠作為賣單底倉（需 ${fmtQty(spotNeeded)} ${sanitize(assetSymbol)}）。</div>
      <div style="margin-bottom:.75rem;color:var(--muted);">直接建立網格，使用現有現貨作為底倉。</div>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
        <button class="btn btn-primary btn-sm" data-grid-spot-action="proceed">確認建立網格</button>
        <button class="btn btn-sm" data-grid-spot-action="cancel">取消</button>
      </div>
    </div>`;
  } else {
    // Deficit — need to buy
    const buyCostPoints = deficit * currentPrice;
    const buyFeePoints = buyCostPoints * (feeRatePct / 100);
    const totalCostPoints = Math.ceil(buyCostPoints + buyFeePoints);
    const hasPartial = currentSpot > 0;
    const desc = hasPartial
      ? `目前持有 <strong>${fmtQty(currentSpot)} ${sanitize(assetSymbol)}</strong>，尚缺 <strong>${fmtQty(deficit)} ${sanitize(assetSymbol)}</strong>`
      : `賣單需 <strong>${fmtQty(spotNeeded)} ${sanitize(assetSymbol)}</strong> 底倉，目前持有 0`;
    html = `<div class="drive-card-sub" style="margin-top:.5rem;padding:.75rem;border:1px solid var(--accent,#4fc3f7);border-radius:.5rem;">
      <div style="font-weight:600;margin-bottom:.5rem;">底倉不足</div>
      <div style="margin-bottom:.5rem;">${desc}。</div>
      <div style="margin-bottom:.5rem;">以現價 <strong>${formatTradingPointsValue(currentPrice)} 點</strong> 買入 <strong>${fmtQty(deficit)} ${sanitize(assetSymbol)}</strong>，預估花費約 <strong>${formatTradingPointsValue(totalCostPoints)} 點</strong>（含手續費）。</div>
      <div style="margin-bottom:.75rem;color:var(--muted);">若積分不足，請先儲值後再操作。</div>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
        <button class="btn btn-primary btn-sm" data-grid-spot-action="buy">買入底倉並建立</button>
        <button class="btn btn-sm" data-grid-spot-action="proceed">不買底倉直接建立</button>
        <button class="btn btn-sm" data-grid-spot-action="cancel">取消</button>
      </div>
    </div>`;
  }
  confirmDiv.innerHTML = html;
  confirmDiv.style.display = "";
  window._gridSpotPending = { situation, formData };
  confirmDiv.querySelectorAll("[data-grid-spot-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.gridSpotAction;
      if (action === "proceed") gridSpotConfirmProceed();
      else if (action === "cancel") gridSpotConfirmCancel();
      else if (action === "buy") gridSpotBuyAndCreate();
    });
  });
}

function gridSpotConfirmCancel() {
  const confirmDiv = $("trading-grid-spot-confirm");
  if (confirmDiv) { confirmDiv.innerHTML = ""; confirmDiv.style.display = "none"; }
  window._gridSpotPending = null;
  const btn = $("trading-grid-bot-create-btn");
  if (btn) btn.disabled = false;
  tradingSetMsg("已取消建立網格");
}

function gridSpotConfirmProceed() {
  const confirmDiv = $("trading-grid-spot-confirm");
  if (confirmDiv) { confirmDiv.innerHTML = ""; confirmDiv.style.display = "none"; }
  const pending = window._gridSpotPending;
  window._gridSpotPending = null;
  if (pending) doCreateGridBot(pending.formData);
}

async function gridSpotBuyAndCreate() {
  const confirmDiv = $("trading-grid-spot-confirm");
  if (confirmDiv) { confirmDiv.innerHTML = ""; confirmDiv.style.display = "none"; }
  const pending = window._gridSpotPending;
  window._gridSpotPending = null;
  if (!pending) return;
  const { situation, formData } = pending;
  const btn = $("trading-grid-bot-create-btn");
  tradingSetMsg("正在買入底倉...");
  try {
    const csrf = await tradingFreshCsrfToken();
    const res = await apiFetch(`${API}/trading/orders`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify({ market_symbol: formData.market_symbol, side: "buy", order_type: "market", quantity: situation.deficit.toFixed(8) }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) { tradingSetMsg(tradingFriendlyErrorText(json.msg || "買入底倉失敗"), false); if (btn) btn.disabled = false; return; }
    tradingSetMsg("底倉買入成功，正在建立網格機器人...");
    await loadTradingDashboard();
  } catch (e) { tradingSetMsg(e.message || "買入底倉失敗", false); if (btn) btn.disabled = false; return; }
  await doCreateGridBot(formData);
}

async function doCreateGridBot(formData) {
  const btn = $("trading-grid-bot-create-btn");
  tradingSetMsg("正在建立網格機器人並掛單...");
  try {
    const csrf = await tradingFreshCsrfToken();
    const res = await apiFetch(`${API}/trading/grid-bots`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(formData),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) { tradingSetMsg(tradingFriendlyErrorText(json.msg || "網格建立失敗"), false); return; }
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

async function createGridBot() {
  const name = $("trading-grid-bot-name")?.value?.trim() || "";
  const marketSymbol = $("trading-grid-bot-market")?.value || "";
  const market = (tradingState.markets || []).find((row) => row.symbol === marketSymbol);
  const upper = Number($("trading-grid-upper-price")?.value || 0);
  const lower = Number($("trading-grid-lower-price")?.value || 0);
  const count = Number($("trading-grid-count")?.value || 10);
  const amount = Number($("trading-grid-order-amount")?.value || 0);
  const spacingMode = $("trading-grid-spacing-mode")?.value || "arithmetic";
  const stopLossPercent = tradingOptionalPercentValue("trading-grid-stop-loss-percent");
  const takeProfitPercent = tradingOptionalPercentValue("trading-grid-take-profit-percent");
  if (!name) { tradingSetMsg("請填寫機器人名稱", false); return; }
  if (!marketSymbol) { tradingSetMsg("請選擇交易市場", false); return; }
  if (market && market.allow_bots === false) {
    tradingSetMsg("這個市場目前未開放網格機器人，請改選其他市場或請 root 開啟 allow_bots。", false);
    return;
  }
  if (!upper || !lower || upper <= lower) { tradingSetMsg("上限價格必須大於下限價格", false); return; }
  if (count < 2) { tradingSetMsg("網格數量至少為 2", false); return; }
  if (amount < 1) { tradingSetMsg("每格金額必須大於 0", false); return; }
  const preview = await renderGridBotPreview({ quiet: false });
  if (!preview || !preview.ok) return;
  const risk = preview.risk || {};
  if (risk.blocked || risk.status === "red") {
    tradingSetMsg(risk.message || "目前網格設定扣費後預期虧損，請加大間距或減少網格數", false);
    return;
  }
  let confirmThinProfit = false;
  if (risk.requires_confirmation) {
    const ok = confirm(`${risk.message || "此網格利潤過薄。"}\n\n若仍要建立，請確認你接受可能被滑價吃掉的風險。`);
    if (!ok) {
      tradingSetMsg("已取消建立網格", false);
      return;
    }
    confirmThinProfit = true;
  }
  const btn = $("trading-grid-bot-create-btn");
  if (btn) btn.disabled = true;
  const formData = {
    name,
    market_symbol: marketSymbol,
    upper_price_points: upper,
    lower_price_points: lower,
	    grid_count: count,
	    order_amount_points: amount,
	    stop_loss_percent: stopLossPercent,
	    take_profit_percent: takeProfitPercent,
	    spacing_mode: spacingMode,
	    share_parameters: !!$("trading-grid-share-parameters")?.checked,
	    confirm_thin_profit: confirmThinProfit,
	  };
  const situation = computeGridSpotSituation(marketSymbol, lower, upper, count, amount, spacingMode);
  if (situation) {
    showGridSpotConfirm(situation, formData);
  } else {
    await doCreateGridBot(formData);
  }
}

async function scanGridBots() {
  tradingSetMsg("掃描網格機器人中...");
  const btn = $("trading-grid-scan-btn");
  if (btn) btn.disabled = true;
  try {
    const csrf = await tradingFreshCsrfToken();
    const res = await apiFetch(`${API}/trading/grid-bots/scan`, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" },
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) { tradingSetMsg(tradingFriendlyErrorText(json.msg || "掃描失敗"), false); return; }
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
  const state = payload.state || tradingState.state || {};
  const marginSummary = tradingDisplayedMarginSummary(payload.margin_summary, marginPositions);
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
      ? "目前部位價值採 reference price；未實現盈虧採 risk-grade price"
      : "各交易對分開計算";
  }
  const activeMarginPositions = marginPositions.filter((row) => row.status === "open");
  if ($("economy-margin-position-count")) $("economy-margin-position-count").textContent = String(activeMarginPositions.length);
  if ($("economy-margin-position-summary")) {
    $("economy-margin-position-summary").textContent = activeMarginPositions.length
      ? `整戶維持率 ${marginSummary.maintenance_ratio_percent == null ? "無法計算" : `${formatTradingPointsValue(marginSummary.maintenance_ratio_percent)}%`} · 全部使用 risk-grade price · ${marginSummary.reason || "風險正常"}`
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
    const marginValue = rootVirtualMarginPositionEquity(marginSummary, activeMarginPositions);
    const available = Number(funding.available_points || 0);
    const locked = Number(funding.locked_points || 0);
    const total = available + spotValue + marginValue;
    if ($("economy-root-virtual-total")) $("economy-root-virtual-total").textContent = `${formatTradingPointsValue(total)} 點`;
    if ($("economy-root-virtual-available")) $("economy-root-virtual-available").textContent = `${formatTradingPointsValue(available)} 點`;
    if ($("economy-root-virtual-locked")) $("economy-root-virtual-locked").textContent = `鎖定 ${formatTradingPointsValue(locked)} 點`;
    if ($("economy-root-virtual-spot-value")) $("economy-root-virtual-spot-value").textContent = `${formatTradingPointsValue(spotValue)} 點`;
    if ($("economy-root-virtual-margin-value")) $("economy-root-virtual-margin-value").textContent = `${formatTradingPointsValue(marginValue)} 點`;
    if ($("economy-root-virtual-margin-summary")) {
      $("economy-root-virtual-margin-summary").textContent = activeMarginPositions.length
        ? `開倉 ${activeMarginPositions.length} 筆，僅加總倉位權益，不重複計入剩餘保證金`
        : "尚無借貸倉位";
    }
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
  if ($("trading-risk-flags")) {
    const degradePauses = [];
    if (settings.price_degrade_pause_market_orders) degradePauses.push("市價");
    if (settings.price_degrade_pause_bots) degradePauses.push("bot");
    if (settings.price_degrade_pause_borrowing) degradePauses.push("借貸");
    $("trading-risk-flags").textContent = `borrow=${settings.borrowing_enabled ? "true" : "false"} / liquidation=${settings.margin_liquidation_enabled ? "true" : "false"} / futures=${settings.futures_enabled ? "true" : "false"} / pvp=${settings.pvp_matching_enabled ? "true" : "false"} / degrade_pause=${degradePauses.join("+") || "off"}`;
  }
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
  ensureTradingAccountScope();
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
    const json = await fetchTradingJson(`/trading/dashboard${tradingSourceWalletQuery()}`);
    const payload = json.trading || {};
    tradingState.funding = payload.funding || null;
    tradingState.fundingPool = payload.funding_pool || null;
    tradingState.wallets = payload.wallets || [];
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
    tradingState.state = state;
    const status = $("trading-safe-mode");
    if (status) {
      status.textContent = state.safe_mode ? `交易 safe mode：${state.reason || "已啟用"}` : "交易引擎正常";
      status.style.color = state.safe_mode ? "#ffb74d" : "var(--muted)";
    }
    renderTradingPaymentWalletOptions(tradingState.wallets, tradingState.funding?.selected_wallet_address || tradingState.funding?.active_wallet_address || "");
    renderTradingMarketOptions();
    loadTradingPersonalFormState();
    renderTradingSummary();
    loadTradingLivePrice().catch(() => {});
    renderTradingOrders(tradingState.orders);
	    renderTradingFills(tradingState.fills);
	    renderTradingBots(tradingState.bots, tradingState.botRuns);
	    loadGridBots().catch(() => {});
	    loadTradingBotCompetition().catch(() => {});
	    renderTradingContracts(payload.futures_positions || []);
    renderTradingMarginPositions(tradingState.marginPositions);
    const displayedMarginSummary = tradingDisplayedMarginSummary(tradingState.marginSummary);
    renderTradingMarginAccountSummary(displayedMarginSummary);
    renderTradingWalletSummary({ ...payload, margin_summary: displayedMarginSummary });
    if (typeof loadTradingAssetOverview === "function") loadTradingAssetOverview().catch(() => {});
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

async function loadTradingLivePrice() {
  if (!shouldRunTradingPolling()) return;
  const targets = tradingLivePriceTargetSymbols();
  if (!targets.length) return;
  if (tradingLivePriceAbort) tradingLivePriceAbort.abort();
  const controller = new AbortController();
  tradingLivePriceAbort = controller;
  try {
    const liveMeta = tradingState.livePriceMeta || (tradingState.livePriceMeta = {});
    let selectedMeta = null;
    let updated = false;
    const selectedSymbol = selectedTradingMarket()?.symbol || "";
    for (const symbol of targets) {
      if (controller.signal.aborted || !shouldRunTradingPolling()) return;
      try {
        const json = await fetchTradingJson(`/trading/live-price?market=${encodeURIComponent(symbol)}`, {
          forceCsrf: false,
          signal: controller.signal,
        });
        if (controller.signal.aborted || !shouldRunTradingPolling()) return;
        const nextMarket = json.market || null;
        if (!nextMarket?.symbol) continue;
        const index = tradingState.markets.findIndex((row) => row.symbol === nextMarket.symbol);
        const previousMarket = index >= 0 ? tradingState.markets[index] : null;
        const mergedMarket = tradingMergeLiveMarket(previousMarket, nextMarket);
        if (index >= 0) {
          tradingState.markets[index] = mergedMarket;
        } else {
          tradingState.markets.unshift(mergedMarket);
        }
        const previousMeta = liveMeta[nextMarket.symbol] || {};
        const referencePriceContext = tradingMergeLivePriceContext(
          previousMeta.reference_price_context || previousMarket?.reference_price_context,
          json.reference_price_context,
        );
        const riskGradePriceContext = tradingMergeLivePriceContext(
          previousMeta.risk_grade_price_context || previousMarket?.risk_grade_price_context,
          json.risk_grade_price_context,
        );
        liveMeta[nextMarket.symbol] = {
          price_type: json.price_type || "reference",
          source: json.source || nextMarket.price_source || "",
          confidence: json.confidence || "",
          stale: !!json.stale,
          degraded: !!json.degraded,
          conservative_mode: json.price_health === "conservative" || !!json.conservative_mode,
          provider_count: Number.isFinite(Number(json.provider_count)) ? Number(json.provider_count) : null,
          minimum_provider_count: Number.isFinite(Number(json.minimum_provider_count)) ? Number(json.minimum_provider_count) : null,
          connected: !!json.connected,
          fallback: !!json.fallback,
          last_update_at: json.last_update_at || "",
          exclusion_reason: json.exclusion_reason || "",
          price_health: json.price_health || "healthy",
          fallback_reason: json.fallback_reason || "",
          excluded_sources: Array.isArray(json.excluded_sources) ? json.excluded_sources : [],
          warnings: Array.isArray(json.warnings) ? json.warnings : [],
          high_risk_blocked: !!json.high_risk_blocked,
          high_risk_block_reason: json.high_risk_block_reason || "",
          defaulted_market: !!json.defaulted_market,
          reference_price_context: referencePriceContext,
          risk_grade_price_context: riskGradePriceContext,
          transport_state: json.transport_state && typeof json.transport_state === "object" ? json.transport_state : null,
        };
        if (nextMarket.symbol === selectedSymbol) selectedMeta = liveMeta[nextMarket.symbol];
        updated = true;
      } catch (_) {
        // Keep the last visible price for this market; partial failure should not stop other wallet markets.
      }
    }
    if (!updated || controller.signal.aborted || !shouldRunTradingPolling()) return;
    const selected = selectedTradingMarket();
    if (currentModuleTab === "trading" && selected) {
      renderTradingCurrentPrice(selected, {
        animate: true,
        priceHealth: selectedMeta?.price_health,
        fallbackReason: selectedMeta?.fallback_reason,
        excludedSources: selectedMeta?.excluded_sources,
        defaultedMarket: !!selectedMeta?.defaulted_market,
        transportState: selectedMeta?.transport_state,
      });
      updateTradingOrderEstimate();
      updateTradingMarginEstimate();
      renderTradingRiskDashboard();
      const limit = $("trading-limit-price");
      if (limit) {
        limit.placeholder = `目前 ${formatTradingPointsValue(tradingMarketPricePoints(selected, "reference"))}`;
      }
    }
    refreshTradingWalletLiveMetrics();
  } catch (_) {
    // Keep the last visible price; the 5s dashboard refresh handles surfaced errors.
  } finally {
    if (tradingLivePriceAbort === controller) tradingLivePriceAbort = null;
  }
}

async function loadTradingRootReport() {
  if (currentUser !== "root") {
    tradingSetMsg("只有 root 可以讀取交易管理報告", false);
    return;
  }
  try {
    const json = await fetchTradingJson("/admin/trading/report", { allowMissingSnapshot: true });
    if (json?.snapshot?.missing) {
      tradingState.rootReport = {};
      renderTradingRootReport(tradingState.rootReport);
      renderTradingRiskDashboard();
      const queued = typeof enqueueTradingSnapshotRefreshOnce === "function"
        ? await enqueueTradingSnapshotRefreshOnce("root_trading_report_missing_snapshot")
        : { ok: false, msg: "背景刷新 helper 尚未載入" };
      tradingSetMsg(
        queued?.ok
          ? "交易報表第一次開啟正在建立快照；已排入 sitewide_metrics_refresh，背景完成後會自動帶出報表。"
          : `交易報表快照正在等待背景刷新；排程失敗：${queued?.msg || "請到 root 背景引擎檢查 worker"}`,
        queued?.ok !== false,
      );
      return;
    }
    tradingState.rootReport = json.report || {};
    renderTradingRootReport(tradingState.rootReport);
    renderTradingRiskDashboard();
  } catch (err) {
    tradingSetMsg(tradingFriendlyErrorText(err.message || "交易報告讀取失敗"), false);
  }
}

async function submitTradingOrder() {
  ensureTradingAccountScope();
  saveTradingPersonalFormState();
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
    source_wallet_address: tradingDefaultSpendWalletAddress(),
    stop_loss_percent: tradingOptionalPercentValue("trading-stop-loss-percent"),
    take_profit_percent: tradingOptionalPercentValue("trading-take-profit-percent"),
  };
  if (orderType === "limit") payload.limit_price_points = Number($("trading-limit-price")?.value || 0);
  try {
    const json = await fetchTradingJson("/trading/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applyTradingOrderResult(json.order || null);
    tradingSetMsg(json.executed ? "訂單已成交，正在背景更新錢包與成交明細" : "限價單已掛出，正在背景更新錢包與訂單列表");
    scheduleTradingMutationRefresh();
  } catch (err) {
    tradingSetMsg(tradingFriendlyErrorText(err.message || "下單失敗"), false);
  }
}

async function saveTradingBot() {
  const marketSymbol = $("trading-auto-bot-market")?.value || selectedTradingMarket()?.symbol || "";
  if (!marketSymbol) {
    tradingSetMsg("請先選擇自動化機器人市場", false);
    return;
  }
  const market = (tradingState.markets || []).find((row) => row.symbol === marketSymbol);
  if (market && market.allow_bots === false) {
    tradingSetMsg("這個市場目前未開放 Workflow / 自動化機器人，請改選其他市場或請 root 開啟 allow_bots。", false);
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
    budget_points: Number($("trading-auto-bot-budget-points")?.value || 0),
    workflow_json: workflow,
    strategy_mode: $("trading-auto-strategy-mode")?.value || "and",
    max_daily_runs: Number($("trading-auto-daily-runs")?.value || 5),
    max_runs: Number($("trading-auto-bot-max-runs")?.value || 1),
    cooldown_seconds: Number($("trading-auto-bot-cooldown")?.value || 300),
	    share_parameters: !!$("trading-auto-share-parameters")?.checked,
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
    tradingSetMsg(`自動化機器人新增失敗：${tradingFriendlyErrorText(err.message || "後端未提供錯誤原因")}`, false);
  }
}

async function saveTradingDcaBot() {
  const marketSymbol = $("trading-dca-bot-market")?.value || selectedTradingMarket()?.symbol || "";
  if (!marketSymbol) {
    tradingSetMsg("請先選擇定投市場", false);
    return;
  }
  const market = (tradingState.markets || []).find((row) => row.symbol === marketSymbol);
  if (market && market.allow_bots === false) {
    tradingSetMsg("這個市場目前未開放定投 / 機器人，請改選其他市場或請 root 開啟 allow_bots。", false);
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
	    stop_loss_percent: tradingOptionalPercentValue("trading-dca-stop-loss-percent"),
	    take_profit_percent: tradingOptionalPercentValue("trading-dca-take-profit-percent"),
	    share_parameters: !!$("trading-dca-share-parameters")?.checked,
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
    tradingSetMsg(`定投機器人新增失敗：${tradingFriendlyErrorText(err.message || "後端未提供錯誤原因")}`, false);
  }
}

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

function tradingCandlesCoverRange(candles, startTime = "", endTime = "") {
  const rows = Array.isArray(candles) ? candles : [];
  if (rows.length < 2) return false;
  if (!startTime && !endTime) return true;
  const first = String(rows[0]?.time_iso || rows[0]?.time || "");
  const last = String(rows[rows.length - 1]?.time_iso || rows[rows.length - 1]?.time || "");
  if (startTime && first && startTime < first) return false;
  if (endTime && last && endTime > last) return false;
  return true;
}

function tradingOptionalPercentValue(target) {
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return null;
  const raw = String(el.value || "").trim();
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function tradingRiskTargetText(stopLossPercent, takeProfitPercent) {
  const parts = [];
  if (Number(stopLossPercent || 0) > 0) parts.push(`停損 ${formatTradingPointsValue(stopLossPercent)}%`);
  if (Number(takeProfitPercent || 0) > 0) parts.push(`停利 ${formatTradingPointsValue(takeProfitPercent)}%`);
  return parts.length ? parts.join(" · ") : "未設定停損 / 停利";
}

async function backtestTradingBot(contextKey = "dca") {
  const cfg = tradingBacktestConfig(contextKey);
  const result = tradingBacktestEl(contextKey, "result");
  const marketSymbol = tradingBacktestEl(contextKey, "market")?.value || selectedTradingMarket()?.symbol || "";
  const botUuid = tradingBacktestEl(contextKey, "bot-select")?.value || "";
  const selectedGridBot = contextKey === "grid" && botUuid ? (tradingGridBots || []).find((g) => g.bot_uuid === botUuid) : null;
  const selectedBot = contextKey !== "grid" && botUuid ? (tradingState.bots || []).find((row) => row.bot_uuid === botUuid) : null;
  const botType = cfg.botType;
  let allCandles = tradingState.referencePrices?.candles || tradingState.referencePrices?.points || [];
  if (!marketSymbol) {
    tradingSetMsg("請先選擇回測市場", false);
    return;
  }

  let gridParams = {};
  if (botType === "grid") {
    const src = selectedGridBot || {};
    gridParams = {
      lower_price_points: Number(tradingBacktestEl(contextKey, "grid-lower")?.value || src.lower_price_points || 0),
      upper_price_points: Number(tradingBacktestEl(contextKey, "grid-upper")?.value || src.upper_price_points || 0),
      grid_count: Number(tradingBacktestEl(contextKey, "grid-count")?.value || src.grid_count || 10),
      order_amount_points: Number(tradingBacktestEl(contextKey, "grid-amount")?.value || src.order_amount_points || 100),
      spacing_mode: tradingBacktestEl(contextKey, "grid-spacing")?.value || src.spacing_mode || "arithmetic",
    };
    if (!gridParams.lower_price_points || !gridParams.upper_price_points || gridParams.upper_price_points <= gridParams.lower_price_points) {
      tradingSetMsg("請填寫正確的網格上下限價格（下限 < 上限）", false);
      return;
    }
  }

  let workflow = null;
  if (botType === "workflow") {
    try {
      workflow = selectedBot?.workflow || parseTradingWorkflowInput();
    } catch (err) {
      tradingSetMsg(err.message || "Workflow JSON 格式錯誤", false);
      return;
    }
  }

  const orderPoints = botType === "grid"
    ? 0
    : Number(tradingBacktestEl(contextKey, "order-points")?.value || 100);
  const intervalCandles = botType === "dca"
    ? Math.max(1, Number(tradingBacktestEl(contextKey, "interval-candles")?.value || 1))
    : 1;
  const riskTargetPayload = botType === "workflow" ? {} : {
    stop_loss_percent: tradingOptionalPercentValue(tradingBacktestEl(contextKey, "stop-loss-percent")),
    take_profit_percent: tradingOptionalPercentValue(tradingBacktestEl(contextKey, "take-profit-percent")),
  };
  const basePayload = {
    market_symbol: marketSymbol,
    strategy: botType,
    workflow_json: workflow,
    initial_cash_points: Number(tradingBacktestEl(contextKey, "initial-cash")?.value || 10000),
    order_points: orderPoints,
    interval_candles: intervalCandles,
    timeframe: tradingBacktestEl(contextKey, "timeframe")?.value || "15m",
    start_time: tradingBacktestEl(contextKey, "start")?.value || "",
    end_time: tradingBacktestEl(contextKey, "end")?.value || "",
    slippage_percent: Number(tradingBacktestEl(contextKey, "slippage-percent")?.value || 0),
    ...riskTargetPayload,
    ...gridParams,
  };
  const hasCandleData = Array.isArray(allCandles) && allCandles.length >= 2;
  const localRangeCovered = hasCandleData && tradingCandlesCoverRange(allCandles, basePayload.start_time, basePayload.end_time);
  if (!hasCandleData || !localRangeCovered) {
    const estimatedCandles = estimateBacktestRequestedCandles(basePayload.start_time, basePayload.end_time, basePayload.timeframe);
    if (estimatedCandles > BACKTEST_TOTAL_CANDLE_LIMIT) {
      tradingSetMsg(`回測區間約需 ${estimatedCandles.toLocaleString()} 根 K 線，超過單次上限 ${BACKTEST_TOTAL_CANDLE_LIMIT.toLocaleString()} 根。請縮小區間或改大時間週期。`, false);
      return;
    }
    basePayload.auto_fetch_reference_candles = true;
    basePayload.candle_limit = estimatedCandles || 500;
    tradingSetMsg(
      estimatedCandles
        ? `${hasCandleData ? "目前圖表不涵蓋你選的回測區間，" : "未載入圖表，"}正在由後端分批下載約 ${estimatedCandles.toLocaleString()} 根歷史 K 線後回測...`
        : `${hasCandleData ? "目前圖表不涵蓋你選的回測區間，" : "未載入圖表，"}正在由後端下載歷史 K 線後回測...`
    );
  } else {
    if (allCandles.length > BACKTEST_TOTAL_CANDLE_LIMIT) {
      tradingSetMsg(`目前單次回測最多 ${BACKTEST_TOTAL_CANDLE_LIMIT.toLocaleString()} 根 K 線；你目前載入了 ${allCandles.length.toLocaleString()} 根。請縮小圖表區間或改大時間週期。`, false);
      return;
    }
    basePayload.data_source = tradingState.referencePrices?.source || "browser_loaded_chart";
    basePayload.provider_symbol = tradingState.referencePrices?.symbol || "";
  }
  try {
    if (hasCandleData) basePayload.candles = allCandles;
    if (result) result.textContent = "回測中…";
    const combinedJson = await fetchTradingJson("/trading/bots/backtest", { method: "POST", body: JSON.stringify(basePayload) });
    const sourceText = combinedJson.data_source ? `，資料 ${sanitize(combinedJson.data_source)} ${Number(combinedJson.candle_count || 0)} 根` : "";
    const batchNote = combinedJson.segmented_backtest
      ? `（後端自動分 ${Number(combinedJson.segmented_backtest_batches || 0)} 批）`
      : "";
    const text = `回測完成${batchNote}：交易 ${Number(combinedJson.trade_count || 0)} 次，期末 ${formatTradingPointsValue(combinedJson.final_value_points)} 點，損益 ${Number(combinedJson.pnl_points || 0) >= 0 ? "+" : ""}${formatTradingPointsValue(combinedJson.pnl_points)} 點，報酬 ${formatTradingPointsValue(combinedJson.return_percent)}%${sourceText}`;
    if (result) result.textContent = text;
    renderTradingBacktestResult(combinedJson, contextKey);
    tradingSetMsg(text, Number(combinedJson.pnl_points || 0) >= 0);
  } catch (err) {
    const text = tradingFriendlyErrorText(err.message || "回測失敗");
    if (result) result.textContent = text;
    tradingSetMsg(text, false);
  }
}

function renderTradingBacktestResult(json, contextKey = "dca") {
  const metrics = tradingBacktestEl(contextKey, "metrics");
  const trades = tradingBacktestEl(contextKey, "trades");
  const warnings = tradingBacktestEl(contextKey, "warnings");
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
      <div><span class="drive-card-sub">回測上限</span><strong>${Number(json.max_backtest_candles || 0).toLocaleString()} 根</strong><small>單批最多 ${Number(json.max_backtest_candles_per_batch || json.max_backtest_candles || 0).toLocaleString()} 根 · 已使用 ${Number(json.candle_count || 0).toLocaleString()} 根</small></div>
    `;
  }
  if (trades) {
    const rows = Array.isArray(json.trades) ? json.trades : [];
    const dlBtn = rows.length ? `<button class="btn btn-sm" type="button" data-backtest-download="${sanitize(contextKey)}" style="margin-bottom:.5rem;">下載成交記錄 CSV（${rows.length} 筆）</button>` : "";
    trades.innerHTML = dlBtn + (rows.length ? rows.map((row) => `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.time || "-")}</strong>
          <div class="drive-card-sub">${sanitize(row.side === "sell" ? "賣出" : "買入")} ${sanitize(row.quantity || "0")} · 價格 ${formatTradingPointsValue(row.price_points)} · 金額 ${formatTradingPointsValue(row.spend_points)} · 手續費 ${formatTradingPointsValue(row.fee_points)}</div>
        </div>
      </div>
    `).join("") : `<div class="drive-empty">回測期間沒有交易</div>`);
    if (rows.length) {
      const dlBtnEl = trades.querySelector(`[data-backtest-download="${CSS.escape(contextKey)}"]`);
      if (dlBtnEl) dlBtnEl.addEventListener("click", () => downloadBacktestTrades(rows, json.market_symbol));
    }
  }
}

function refreshBacktestBotSelect() {
  refreshBacktestBotSelects();
}

function refreshBacktestBotSelects() {
  const optionsByContext = {
    dca: (tradingState.bots || []).filter((row) => row.bot_type === "dca").map((row) =>
      `<option value="${sanitize(row.bot_uuid || "")}">${sanitize(`定投 · ${row.name || row.market_symbol || ""}`)}</option>`
    ).join(""),
    workflow: (tradingState.bots || []).filter((row) => row.bot_type !== "dca").map((row) =>
      `<option value="${sanitize(row.bot_uuid || "")}">${sanitize(`Workflow · ${row.name || row.market_symbol || ""}`)}</option>`
    ).join(""),
    grid: (tradingGridBots || []).map((bot) =>
      `<option value="${sanitize(bot.bot_uuid || "")}">${sanitize(`網格 · ${bot.name || bot.market_symbol || ""}`)}</option>`
    ).join(""),
  };
  Object.keys(TRADING_BACKTEST_CONTEXTS).forEach((contextKey) => {
    const sel = tradingBacktestEl(contextKey, "bot-select");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = `<option value="">使用目前表單設定</option>${optionsByContext[contextKey] || ""}`;
    if (prev && Array.from(sel.options).some((o) => o.value === prev)) sel.value = prev;
  });
}

function prepareTradingBacktestFromBot(botUuid) {
  const gridBot = (tradingGridBots || []).find((g) => g.bot_uuid === botUuid);
  if (gridBot) {
    switchTradingBotTab("grid");
    if (tradingBacktestEl("grid", "bot-select")) tradingBacktestEl("grid", "bot-select").value = botUuid;
    if (tradingBacktestEl("grid", "market")) tradingBacktestEl("grid", "market").value = gridBot.market_symbol || "";
    if (tradingBacktestEl("grid", "grid-lower")) tradingBacktestEl("grid", "grid-lower").value = gridBot.lower_price_points || "";
    if (tradingBacktestEl("grid", "grid-upper")) tradingBacktestEl("grid", "grid-upper").value = gridBot.upper_price_points || "";
    if (tradingBacktestEl("grid", "grid-count")) tradingBacktestEl("grid", "grid-count").value = gridBot.grid_count || 10;
    if (tradingBacktestEl("grid", "grid-amount")) tradingBacktestEl("grid", "grid-amount").value = gridBot.order_amount_points || 100;
    if (tradingBacktestEl("grid", "grid-spacing")) tradingBacktestEl("grid", "grid-spacing").value = gridBot.spacing_mode || "arithmetic";
    if (tradingBacktestEl("grid", "stop-loss-percent")) tradingBacktestEl("grid", "stop-loss-percent").value = gridBot.stop_loss_percent || "";
    if (tradingBacktestEl("grid", "take-profit-percent")) tradingBacktestEl("grid", "take-profit-percent").value = gridBot.take_profit_percent || "";
    updateBacktestDateRangeGuidance("grid");
    tradingSetMsg("已帶入網格機器人回測設定，請確認時間範圍後執行回測");
    return;
  }
  const bot = (tradingState.bots || []).find((row) => row.bot_uuid === botUuid);
  if (!bot) {
    tradingSetMsg("找不到要回測的交易機器人", false);
    return;
  }
  const contextKey = bot.bot_type === "dca" ? "dca" : "workflow";
  switchTradingBotTab(tradingBacktestConfig(contextKey).tab);
  if (tradingBacktestEl(contextKey, "bot-select")) tradingBacktestEl(contextKey, "bot-select").value = botUuid;
  if (tradingBacktestEl(contextKey, "market")) tradingBacktestEl(contextKey, "market").value = bot.market_symbol || "";
  if (contextKey === "dca") {
    if (tradingBacktestEl("dca", "order-points")) tradingBacktestEl("dca", "order-points").value = bot.budget_points || 100;
    if (tradingBacktestEl("dca", "stop-loss-percent")) tradingBacktestEl("dca", "stop-loss-percent").value = bot.stop_loss_percent || "";
    if (tradingBacktestEl("dca", "take-profit-percent")) tradingBacktestEl("dca", "take-profit-percent").value = bot.take_profit_percent || "";
    const timeframe = tradingBacktestEl("dca", "timeframe")?.value || "15m";
    const hoursPerCandle = tradingTimeframeMinutes(timeframe) / 60;
    if (tradingBacktestEl("dca", "interval-candles")) {
      tradingBacktestEl("dca", "interval-candles").value = Math.max(1, Math.ceil(Number(bot.interval_hours || 1) / Math.max(hoursPerCandle, 1 / 12)));
    }
    updateBacktestDateRangeGuidance("dca");
  } else {
    if (Number(bot.budget_points || 0) > 0 && tradingBacktestEl("workflow", "order-points")) {
      tradingBacktestEl("workflow", "order-points").value = bot.budget_points || 100;
    }
    updateBacktestDateRangeGuidance("workflow");
  }
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

async function setTradingBotParameterShare(botUuid, shareParameters) {
  if (!botUuid) {
    tradingSetMsg("找不到要更新的交易機器人", false);
    return;
  }
  await fetchTradingJson(`/trading/bots/${encodeURIComponent(botUuid)}/share`, {
    method: "POST",
    body: JSON.stringify({ share_parameters: !!shareParameters }),
  });
  tradingSetMsg(shareParameters ? "已在競賽中分享參數" : "已停止分享參數");
  await loadTradingDashboard();
  await loadTradingBotCompetition();
}

async function setGridBotParameterShare(botUuid, shareParameters) {
  if (!botUuid) {
    tradingSetMsg("找不到要更新的網格機器人", false);
    return;
  }
  await fetchTradingJson(`/trading/grid-bots/${encodeURIComponent(botUuid)}/share`, {
    method: "POST",
    body: JSON.stringify({ share_parameters: !!shareParameters }),
  });
  tradingSetMsg(shareParameters ? "已在競賽中分享網格參數" : "已停止分享網格參數");
  await loadGridBots();
  await loadTradingBotCompetition();
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
	    max_runs: Number(bot.max_runs ?? 1),
	    cooldown_seconds: Number(bot.cooldown_seconds || 0),
	    stop_loss_percent: bot.stop_loss_percent ?? null,
	    take_profit_percent: bot.take_profit_percent ?? null,
	    share_parameters: !!bot.share_parameters,
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

async function increaseTradingBotMaxRuns(botUuid) {
  const bot = (tradingState.bots || []).find((row) => row.bot_uuid === botUuid);
  if (!bot) {
    tradingSetMsg("找不到要增加次數的交易機器人", false);
    return;
  }
  if (tradingBotMaxRunsValue(bot) === -1) {
    tradingSetMsg("這個定投機器人目前是不限制執行次數，不需要再增加上限");
    return;
  }
  const raw = window.prompt(`目前 ${Number(bot.run_count || 0)} / ${tradingBotMaxRunsLabel(bot)} 次。\n要再增加幾次？`, "1");
  if (raw == null) {
    tradingSetMsg("已取消增加機器人次數");
    return;
  }
  const delta = Number(raw);
  if (!Number.isInteger(delta) || delta <= 0) {
    tradingSetMsg("請輸入大於 0 的整數次數", false);
    return;
  }
  const json = await fetchTradingJson(`/trading/bots/${encodeURIComponent(botUuid)}/increase-runs`, {
    method: "POST",
    body: JSON.stringify({ delta }),
  });
  const nextLimitLabel = tradingBotMaxRunsLabel(json?.bot || {});
  tradingSetMsg(`已增加 ${delta} 次，新的最大交易次數為 ${nextLimitLabel === "不限制" ? "不限制" : `${nextLimitLabel} 次`}`);
  await loadTradingDashboard();
}

async function adjustTradingBotBudget(botUuid) {
  const bot = (tradingState.bots || []).find((row) => row.bot_uuid === botUuid);
  if (!bot) {
    tradingSetMsg("找不到要調整可用上限的交易機器人", false);
    return;
  }
  const current = Number(bot.budget_points || 0);
  const floor = Number(bot.minimum_budget_points || bot.open_order_frozen_points || 0);
  const raw = window.prompt(
    `目前 ${tradingBotBudgetText(bot)}。\n請輸入新的可用上限點數；0 代表不設上限。若設定上限，最低不能低於已掛單凍結 ${formatTradingPointsValue(floor)} 點。`,
    String(current)
  );
  if (raw == null) {
    tradingSetMsg("已取消調整機器人可用上限");
    return;
  }
  const budgetPoints = Number(raw);
  if (!Number.isInteger(budgetPoints) || budgetPoints < 0) {
    tradingSetMsg("請輸入 0 或大於 0 的整數點數", false);
    return;
  }
  if (budgetPoints !== 0 && budgetPoints < floor) {
    tradingSetMsg(`可用上限不能低於已掛單凍結 ${formatTradingPointsValue(floor)} 點；若要取消上限請填 0`, false);
    return;
  }
  const json = await fetchTradingJson(`/trading/bots/${encodeURIComponent(botUuid)}/budget`, {
    method: "POST",
    body: JSON.stringify({ budget_points: budgetPoints }),
  });
  tradingSetMsg(`已更新機器人可用上限：${tradingBotBudgetText(json?.bot || { budget_points: budgetPoints })}`);
  await loadTradingDashboard();
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
  ensureTradingAccountScope();
  saveTradingPersonalFormState();
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
        stop_loss_percent: tradingOptionalPercentValue("trading-margin-stop-loss-percent"),
        take_profit_percent: tradingOptionalPercentValue("trading-margin-take-profit-percent"),
        idempotency_key: tradingRequestId("margin-open"),
      }),
    });
    if (json.funding) tradingState.funding = json.funding;
    tradingSetMsg("進階交易倉位已建立");
    await loadTradingDashboard();
  } catch (err) {
    const detail = tradingFriendlyErrorText(err.message || "後端未提供錯誤原因");
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

async function withdrawTradingMarginCollateral(positionUuid, scope = "trading") {
  if (!positionUuid) {
    tradingSetMsg("找不到要抽出保證金的進階交易倉位", false);
    return;
  }
  const selector = scope === "economy"
    ? `[data-economy-margin-withdraw-collateral-amount="${CSS.escape(positionUuid)}"]`
    : `[data-margin-withdraw-collateral-amount="${CSS.escape(positionUuid)}"]`;
  const input = document.querySelector(selector);
  const amount = Number(input?.value || 0);
  if (!amount || amount <= 0) {
    tradingSetMsg("請輸入要抽出的保證金點數", false);
    return;
  }
  const position = tradingMarginPositionByUuid(positionUuid);
  const withdrawEstimate = position ? tradingMarginWithdrawEstimate(position) : null;
  if (withdrawEstimate && amount > withdrawEstimate.maxWithdrawable) {
    tradingSetMsg(`預估可抽出保證金上限為 ${formatTradingPointsValue(withdrawEstimate.maxWithdrawable)} 點；${withdrawEstimate.reason}`, false);
    return;
  }
  if (!confirm("抽出保證金會降低維持率，價格反向波動時更容易接近強平線。確定要抽出？")) {
    tradingSetMsg("已取消抽出保證金");
    return;
  }
  try {
    const idempotencyKey = `margin-collateral-withdraw:${positionUuid}:${amount}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    const json = await fetchTradingJson(`/trading/margin/${encodeURIComponent(positionUuid)}/collateral/withdraw`, {
      method: "POST",
      body: JSON.stringify({ amount_points: amount, idempotency_key: idempotencyKey }),
    });
    if (json.funding) tradingState.funding = json.funding;
    const beforeRatio = json.risk_before?.maintenance_ratio_percent;
    const afterRatio = json.risk_after?.maintenance_ratio_percent;
    const ratioText = beforeRatio != null && afterRatio != null
      ? `，維持率 ${formatTradingPointsValue(beforeRatio)}% → ${formatTradingPointsValue(afterRatio)}%`
      : "";
    tradingSetMsg(`已抽出 ${formatTradingPointsValue(amount)} 點保證金${ratioText}。請留意強平風險。`);
    await loadTradingDashboard();
    if (typeof loadEconomyDashboard === "function") await loadEconomyDashboard();
  } catch (err) {
    tradingSetMsg(`抽出保證金失敗：${err.message || "後端未提供錯誤原因"}`, false);
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
  ensureTradingAccountScope({ force: true });
  bindTradingPersonalFormPersistence();
  document.addEventListener("hackme:account-context-changed", () => {
    ensureTradingAccountScope({ force: true });
  });
  window.addEventListener("economy:default-spend-wallet-changed", () => {
    if (!shouldRunTradingPolling()) return;
    loadTradingDashboard().catch((err) => tradingSetMsg(tradingFriendlyErrorText(err.message || "交易錢包餘額更新失敗"), false));
  });
  const paymentWallet = $("trading-payment-wallet");
  if (paymentWallet && paymentWallet.dataset.tradingPaymentWalletBound !== "1") {
    paymentWallet.dataset.tradingPaymentWalletBound = "1";
    paymentWallet.addEventListener("change", () => {
      if (typeof writeEconomyDefaultSpendWalletAddress === "function") {
        writeEconomyDefaultSpendWalletAddress(paymentWallet.value || "");
      }
      loadTradingDashboard().catch((err) => tradingSetMsg(tradingFriendlyErrorText(err.message || "交易錢包餘額更新失敗"), false));
    });
  }
  const bindings = [
    ["trading-refresh-btn", loadTradingDashboard, "正在重新整理交易資料...", "交易資料重新整理失敗"],
    ["trading-submit-order-btn", submitTradingOrder, "正在送出訂單...", "下單失敗"],
    ["trading-auto-bot-save-btn", saveTradingBot, "正在新增自動化機器人...", "自動化機器人新增失敗"],
    ["trading-dca-bot-save-btn", saveTradingDcaBot, "正在新增定投機器人...", "定投機器人新增失敗"],
    ["trading-bot-scan-btn", scanTradingBots, "正在掃描已啟用交易機器人...", "交易機器人掃描失敗"],
    ["trading-dca-backtest-run-btn", () => backtestTradingBot("dca"), "正在執行定投回測...", "定投回測失敗"],
    ["trading-grid-backtest-run-btn", () => backtestTradingBot("grid"), "正在執行網格回測...", "網格回測失敗"],
    ["trading-workflow-backtest-run-btn", () => backtestTradingBot("workflow"), "正在執行 Workflow 回測...", "Workflow 回測失敗"],
    ["trading-workflow-load-btn", loadTradingWorkflowFromEditor, "正在載入 Workflow 編輯器結果...", "Workflow 載入失敗"],
	    ["trading-workflow-template-apply-btn", applyTradingWorkflowTemplate, "正在套用 Workflow 基礎模板...", "Workflow 模板套用失敗"],
	    ["trading-workflow-custom-save-btn", saveTradingWorkflowCustomTemplate, "正在儲存 Workflow 自訂模板...", "Workflow 自訂模板儲存失敗"],
	    ["trading-bot-competition-refresh-btn", loadTradingBotCompetition, "正在讀取機器人競賽排行...", "競賽排行讀取失敗"],
	    ["trading-bot-competition-award-btn", awardTradingBotCompetition, "正在發放機器人週賽獎勵...", "週賽獎勵發放失敗"],
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
  Object.keys(TRADING_BACKTEST_CONTEXTS).forEach((contextKey) => {
    ["timeframe", "start", "end"].forEach((suffix) => {
      const el = tradingBacktestEl(contextKey, suffix);
      if (!el) return;
      el.addEventListener("change", () => updateBacktestDateRangeGuidance(contextKey));
      el.addEventListener("input", () => updateBacktestDateRangeGuidance(contextKey));
    });
    const botSelect = tradingBacktestEl(contextKey, "bot-select");
    if (botSelect) {
      botSelect.addEventListener("change", () => {
        if (botSelect.value) prepareTradingBacktestFromBot(botSelect.value);
        else tradingSetMsg("已切換為使用目前表單設定回測");
      });
    }
  });
  Object.keys(TRADING_BACKTEST_CONTEXTS).forEach((contextKey) => updateBacktestDateRangeGuidance(contextKey));
  // Grid bot wiring
  const gridCreateBtn = $("trading-grid-bot-create-btn");
  if (gridCreateBtn) bindTradingActionButton(gridCreateBtn, createGridBot, "正在建立網格機器人...", "網格機器人建立失敗");
  const gridScanBtn = $("trading-grid-scan-btn");
  if (gridScanBtn) bindTradingActionButton(gridScanBtn, scanGridBots, "掃描網格機器人中...", "網格掃描失敗");
  const clearOverlayBtn = $("trading-chart-clear-overlay-btn");
  if (clearOverlayBtn) clearOverlayBtn.addEventListener("click", clearBotChartOverlay);
  ["trading-grid-upper-price", "trading-grid-lower-price", "trading-grid-count", "trading-grid-order-amount"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("input", scheduleGridBotPreview);
  });
  const gridSpacingMode = $("trading-grid-spacing-mode");
  if (gridSpacingMode) gridSpacingMode.addEventListener("change", scheduleGridBotPreview);
  const gridMarketSelect = $("trading-grid-bot-market");
  if (gridMarketSelect) {
    gridMarketSelect.addEventListener("change", () => {
      if ($("trading-grid-preset")?.value) applyGridPreset({ quiet: true });
      else scheduleGridBotPreview();
    });
  }
  const gridPresetSelect = $("trading-grid-preset");
  if (gridPresetSelect) gridPresetSelect.addEventListener("change", applyGridPreset);
  document.querySelectorAll("[data-trading-bot-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchTradingBotTab(btn.dataset.tradingBotTab || "dca");
      tradingSetMsg(`已切換到${btn.textContent?.trim() || "交易機器人"}分頁`);
    });
  });
  const dcaPreset = $("trading-dca-bot-interval-preset");
  if (dcaPreset) {
    syncTradingDcaIntervalMode();
    dcaPreset.addEventListener("change", () => {
      const custom = syncTradingDcaIntervalMode();
      saveTradingPersonalFormState();
      tradingSetMsg(custom ? "已切換為自訂定投間隔" : `已選擇每 ${dcaPreset.value} 小時定投`);
    });
  }
  const marketSelect = $("trading-market-select");
  if (marketSelect) {
    marketSelect.addEventListener("change", () => {
      renderTradingSummary();
      loadTradingLivePrice().catch(() => {});
    });
  }
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
    "trading-indicator-ma10",
    "trading-indicator-ma20",
    "trading-indicator-ma30",
    "trading-indicator-ma60",
    "trading-indicator-ema12",
    "trading-indicator-ema26",
    "trading-indicator-ema50",
    "trading-indicator-bollinger",
    "trading-indicator-rsi14",
    "trading-indicator-kd",
  ].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("change", () => renderTradingReferenceChart(tradingState.referencePrices));
  });
  const referenceChart = $("trading-reference-chart");
  if (referenceChart) {
    referenceChart.addEventListener("mousemove", updateTradingReferenceTooltip);
    referenceChart.addEventListener("mouseleave", hideTradingReferenceTooltip);
    referenceChart.addEventListener("pointermove", updateTradingReferenceTooltip);
    referenceChart.addEventListener("pointerleave", hideTradingReferenceTooltip);
    referenceChart.addEventListener("pointercancel", hideTradingReferenceTooltip);
    referenceChart.addEventListener("touchstart", updateTradingReferenceTooltipFromTouch, { passive: true });
    referenceChart.addEventListener("touchmove", updateTradingReferenceTooltipFromTouch, { passive: true });
    referenceChart.addEventListener("touchend", hideTradingReferenceTooltip);
    referenceChart.addEventListener("touchcancel", hideTradingReferenceTooltip);
  }
  const rootMarketSelect = $("trading-root-market-select");
  if (rootMarketSelect) rootMarketSelect.addEventListener("change", populateTradingRootMarketForm);
  document.addEventListener("hackme:module-changed", syncTradingModuleTimerLifecycle);
  document.addEventListener("visibilitychange", syncTradingModuleTimerLifecycle);
  syncTradingModuleTimerLifecycle();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindTradingEvents);
} else {
  bindTradingEvents();
}
