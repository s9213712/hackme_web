let economyLedgerOffset = 0;
let economyLedgerCache = [];
let economyBlockCountdownTimer = null;
let economyBlockSchedule = null;
let economyInlineEventsBound = false;
let economyAutoRefreshTimer = null;
let economyAutoRefreshBusy = false;
let economyGeneratedColdWallet = null;
const ECONOMY_PAGE_STORAGE_KEY = "hackme_web:economy:active_page";

function economyPageStorageKey() {
  return typeof accountScopedStorageKey === "function" ? accountScopedStorageKey(ECONOMY_PAGE_STORAGE_KEY) : ECONOMY_PAGE_STORAGE_KEY;
}

function readEconomyActivePage() {
  try {
    return localStorage.getItem(economyPageStorageKey()) || "balance";
  } catch (_) {
    return "balance";
  }
}

let economyActivePage = readEconomyActivePage();

function shouldRunEconomyAutoRefresh() {
  if (!currentUser || document.hidden || currentModuleTab !== "economy") return false;
  return true;
}

function economyDashboardRefreshMs() {
  const seconds = Number(siteConfig?.economy_dashboard_refresh_seconds || 30);
  return Math.max(5, Math.min(600, Number.isFinite(seconds) ? seconds : 30)) * 1000;
}

function stopEconomyAutoRefresh() {
  if (economyAutoRefreshTimer) {
    clearInterval(economyAutoRefreshTimer);
    economyAutoRefreshTimer = null;
  }
}

function startEconomyAutoRefresh() {
  if (!shouldRunEconomyAutoRefresh() || economyAutoRefreshTimer) return;
  economyAutoRefreshTimer = setInterval(async () => {
    if (!shouldRunEconomyAutoRefresh() || economyAutoRefreshBusy) return;
    economyAutoRefreshBusy = true;
    try {
      await loadEconomyDashboard();
    } finally {
      economyAutoRefreshBusy = false;
    }
  }, economyDashboardRefreshMs());
}

function syncEconomyAutoRefreshLifecycle() {
  if (shouldRunEconomyAutoRefresh()) startEconomyAutoRefresh();
  else stopEconomyAutoRefresh();
}

function toggleWalletCard(bodyId, btn) {
  const body = $(bodyId);
  if (!body) return;
  const hidden = body.style.display === "none";
  body.style.display = hidden ? "" : "none";
  if (btn) {
    btn.textContent = hidden ? "▾" : "▸";
    btn.setAttribute("aria-expanded", hidden ? "true" : "false");
  }
}

function economySetMsg(text, ok = true) {
  const el = $("economy-msg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
  scheduleInlineMessageClear(el, text, ok);
}

function auditChainActionMsg(text, ok = true) {
  const el = $("audit-chain-action-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
  scheduleInlineMessageClear(el, text, ok);
}

function economyRecoveryActionMsg(text, ok = true) {
  const el = $("economy-recovery-action-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
  scheduleInlineMessageClear(el, text, ok);
}

function economyRequestId(prefix = "economy") {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `${prefix}:${window.crypto.randomUUID()}`;
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function economyWalletMsg(text, ok = true) {
  const el = $("economy-wallet-onboarding-msg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
  scheduleInlineMessageClear(el, text, ok);
}

function economyBase64UrlFromBytes(bytes) {
  let binary = "";
  new Uint8Array(bytes).forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function economyCanonicalPublicJwk(jwk) {
  return {
    crv: String(jwk?.crv || ""),
    kty: String(jwk?.kty || ""),
    x: String(jwk?.x || ""),
    y: String(jwk?.y || ""),
  };
}

async function economySha256Hex(text) {
  const data = new TextEncoder().encode(String(text || ""));
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function economyWalletAddressFromPublicJwk(publicJwk) {
  const canonical = JSON.stringify(economyCanonicalPublicJwk(publicJwk));
  const publicKeyHash = await economySha256Hex(canonical);
  const addressHash = await economySha256Hex(publicKeyHash);
  return { address: `pc1${addressHash.slice(0, 48)}`, publicKeyHash };
}

function economyWalletBindingPayload({ address, publicKeyHash, walletType }) {
  return JSON.stringify({
    action: "points_wallet_bind",
    address,
    key_algorithm: "ECDSA_P256_SHA256",
    public_key_hash: publicKeyHash,
    user_id: Number(currentUserId || 0),
    wallet_type: walletType,
  });
}

async function economySignWalletBinding(privateKey, payload) {
  const signature = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    privateKey,
    new TextEncoder().encode(payload)
  );
  return economyBase64UrlFromBytes(signature);
}

async function economyBuildWalletBindPayload({ privateKey, publicJwk, walletType }) {
  const { address, publicKeyHash } = await economyWalletAddressFromPublicJwk(publicJwk);
  const payload = economyWalletBindingPayload({ address, publicKeyHash, walletType });
  const signature = await economySignWalletBinding(privateKey, payload);
  return {
    mode: walletType,
    address,
    public_key_jwk: economyCanonicalPublicJwk(publicJwk),
    signature,
    backup_confirmed: true,
  };
}

function formatPointsCurrency(currency) {
  return "點";
}

function formatEconomyPointsValue(value) {
  if (typeof formatTradingPointsValue === "function") return formatTradingPointsValue(value);
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatEconomyPercentValue(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  return `${number.toLocaleString(undefined, { maximumFractionDigits: 4 })}%`;
}

function economyDisplayMarketSymbol(symbol) {
  if (typeof tradingDisplaySymbol === "function") return tradingDisplaySymbol(symbol);
  return String(symbol || "").toUpperCase().replace("/POINTS", "/USDT");
}

function formatEconomyQuantityValue(value) {
  if (typeof formatTradingQuantityValue === "function") return formatTradingQuantityValue(value);
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

function formatEconomyLedgerAction(actionType) {
  const action = String(actionType || "");
  const labels = {
    admin_adjust_credit: "管理員加點",
    admin_adjust_debit: "管理員扣點",
    admin_initial_grant: "管理員初始配點",
    admin_weekly_salary: "管理員週薪",
    game_daily_challenge_reward: "遊戲每日任務獎勵",
    game_weekly_leaderboard_reward: "遊戲週排行榜獎勵",
    trading_bot_weekly_competition_reward: "交易機器人週賽獎勵",
    new_user_signup_bonus: "註冊獎勵",
    birthday_gift: "生日禮金",
    user_initial_grant: "會員初始配點",
  };
  if (labels[action]) return labels[action];
  if (action.startsWith("rollback:")) return `Rollback：${formatEconomyLedgerAction(action.slice("rollback:".length))}`;
  return action || "-";
}

function formatEconomyLedgerAmount(row) {
  const direction = String(row?.direction || "");
  const amount = Number(row?.amount || 0);
  const currency = formatPointsCurrency(row?.currency_type);
  if (direction === "credit" || direction === "transfer_in") return `收入 +${amount} ${currency}`;
  if (direction === "debit" || direction === "transfer_out" || direction === "reverse") return `支出 -${amount} ${currency}`;
  if (direction === "freeze") return `凍結 ${amount} ${currency}`;
  if (direction === "unfreeze") return `解凍 ${amount} ${currency}`;
  return `${direction || "異動"} ${amount} ${currency}`;
}

function formatEconomyLedgerSource(row) {
  const meta = row?.public_metadata && typeof row.public_metadata === "object" ? row.public_metadata : {};
  const parts = [];
  if (row?.reason) parts.push(row.reason);
  if (meta.game_key) parts.push(`遊戲：${meta.game_key}`);
  if (meta.difficulty) parts.push(`難度：${meta.difficulty}`);
  if (meta.score !== undefined && meta.score !== null && meta.score !== "") parts.push(`分數：${meta.score}`);
  if (row?.reference_id) parts.push(`參照：${row.reference_id}`);
  return parts.join(" · ");
}

function shortEconomyWalletAddress(value) {
  const text = String(value || "").trim();
  if (!text || text === "-") return "-";
  if (text.length <= 24) return text;
  return `${text.slice(0, 12)}…${text.slice(-8)}`;
}

function formatEconomyLedgerWalletFlow(row) {
  const flow = row?.wallet_flow && typeof row.wallet_flow === "object" ? row.wallet_flow : null;
  if (!flow?.source_wallet_address && !flow?.destination_wallet_address) return "";
  const sourceLabel = flow.source_label || "來源地址";
  const destLabel = flow.destination_label || "目的地址";
  const source = shortEconomyWalletAddress(flow.source_wallet_address);
  const dest = shortEconomyWalletAddress(flow.destination_wallet_address);
  if (flow.internal_movement) return `地址流：${sourceLabel} ${source} 內部異動`;
  return `地址流：${sourceLabel} ${source} → ${destLabel} ${dest}`;
}

function formatEconomyCountdown(seconds) {
  const safe = Math.max(0, Number(seconds || 0));
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function stopEconomyBlockCountdown() {
  if (economyBlockCountdownTimer) {
    clearInterval(economyBlockCountdownTimer);
    economyBlockCountdownTimer = null;
  }
}

function canManageEconomyPoints() {
  return currentUser === "root" || currentRole === "manager" || currentRole === "super_admin";
}

function economyPositionsAvailable() {
  return !siteConfig || siteConfig.feature_trading_enabled !== false;
}

function setEconomyActivePage(page, options = {}) {
  const rootMode = currentUser === "root";
  const chainAllowed = canManageEconomyPoints();
  const positionsAvailable = economyPositionsAvailable();
  const rootTradingAllowed = rootMode && positionsAvailable;
  const requestedPage = ["chain", "positions", "funding-pools", "all-positions"].includes(page) ? page : "balance";
  const nextPage =
    requestedPage === "chain" && chainAllowed
      ? "chain"
      : requestedPage === "funding-pools" && rootTradingAllowed
        ? "funding-pools"
        : requestedPage === "all-positions" && rootTradingAllowed
          ? "all-positions"
      : requestedPage === "positions" && positionsAvailable
        ? "positions"
        : "balance";
  economyActivePage = nextPage;
  if (options.persist !== false) {
    try {
      localStorage.setItem(economyPageStorageKey(), nextPage);
    } catch (_) {}
  }
  const balancePage = $("economy-balance-page");
  const positionsPage = $("economy-positions-page");
  const fundingPoolsPage = $("economy-funding-pools-page");
  const allPositionsPage = $("economy-all-positions-page");
  const chainPage = $("economy-chain-page");
  if (balancePage) balancePage.classList.toggle("active", nextPage === "balance");
  if (positionsPage) positionsPage.classList.toggle("active", positionsAvailable && nextPage === "positions");
  if (fundingPoolsPage) fundingPoolsPage.classList.toggle("active", rootTradingAllowed && nextPage === "funding-pools");
  if (allPositionsPage) allPositionsPage.classList.toggle("active", rootTradingAllowed && nextPage === "all-positions");
  if (chainPage) chainPage.classList.toggle("active", chainAllowed && nextPage === "chain");
  const balanceTab = $("tab-economy-balance");
  const positionsTab = $("tab-economy-positions");
  const fundingPoolsTab = $("tab-economy-funding-pools");
  const allPositionsTab = $("tab-economy-all-positions");
  const chainTab = $("tab-economy-chain");
  if (balanceTab) {
    balanceTab.classList.toggle("active", nextPage === "balance");
    balanceTab.setAttribute("aria-selected", nextPage === "balance" ? "true" : "false");
  }
  if (fundingPoolsTab) {
    fundingPoolsTab.style.display = rootTradingAllowed ? "" : "none";
    fundingPoolsTab.classList.toggle("active", rootTradingAllowed && nextPage === "funding-pools");
    fundingPoolsTab.setAttribute("aria-selected", rootTradingAllowed && nextPage === "funding-pools" ? "true" : "false");
  }
  if (allPositionsTab) {
    allPositionsTab.style.display = rootTradingAllowed ? "" : "none";
    allPositionsTab.classList.toggle("active", rootTradingAllowed && nextPage === "all-positions");
    allPositionsTab.setAttribute("aria-selected", rootTradingAllowed && nextPage === "all-positions" ? "true" : "false");
  }
  if (positionsTab) {
    positionsTab.style.display = positionsAvailable ? "" : "none";
    positionsTab.classList.toggle("active", positionsAvailable && nextPage === "positions");
    positionsTab.setAttribute("aria-selected", positionsAvailable && nextPage === "positions" ? "true" : "false");
  }
  if (chainTab) {
    chainTab.style.display = chainAllowed ? "" : "none";
    chainTab.textContent = rootMode ? "積分私有鏈" : "審核";
    chainTab.classList.toggle("active", chainAllowed && nextPage === "chain");
    chainTab.setAttribute("aria-selected", chainAllowed && nextPage === "chain" ? "true" : "false");
  }
  const title = $("economy-page-title");
  if (title) {
    if (nextPage === "positions") title.textContent = "倉位管理";
    else if (nextPage === "funding-pools") title.textContent = "資金池管理";
    else if (nextPage === "all-positions") title.textContent = "全用戶倉位管理";
    else if (!rootMode) title.textContent = nextPage === "chain" ? "積分審核" : "積分錢包";
    else title.textContent = nextPage === "chain" ? "積分私有鏈" : "積分餘額";
  }
  if (options.loadRootTrading !== false && rootTradingAllowed && ["funding-pools", "all-positions"].includes(nextPage)) {
    loadEconomyRootTradingReadOnly();
  }
}

function syncEconomySubpages(rootMode) {
  if (!canManageEconomyPoints() && economyActivePage === "chain") economyActivePage = "balance";
  if (!economyPositionsAvailable() && economyActivePage === "positions") economyActivePage = "balance";
  if ((!rootMode || !economyPositionsAvailable()) && ["funding-pools", "all-positions"].includes(economyActivePage)) economyActivePage = "balance";
  setEconomyActivePage(economyActivePage, { persist: false, loadRootTrading: false });
}

function setEconomyRootLayout(rootMode) {
  const rootBalanceCard = $("economy-root-balance-card");
  if (rootBalanceCard) rootBalanceCard.style.display = rootMode ? "" : "none";
  const rootVirtualCard = $("economy-root-virtual-card");
  if (rootVirtualCard) rootVirtualCard.style.display = rootMode ? "" : "none";
  const manualAdjustDetails = $("economy-manual-adjust-details");
  if (manualAdjustDetails) {
    manualAdjustDetails.style.display = rootMode ? "" : "none";
    if (manualAdjustDetails.dataset.economyFoldInitialized !== "1") {
      if (rootMode) manualAdjustDetails.removeAttribute("open");
      else manualAdjustDetails.setAttribute("open", "");
      manualAdjustDetails.dataset.economyFoldInitialized = "1";
    }
  }
}

function updateEconomyBlockCountdown() {
  const el = $("economy-chain-countdown");
  if (!el || !economyBlockSchedule) return;
  const unsealed = Number(economyBlockSchedule.unsealed_entries || 0);
  const threshold = Number(economyBlockSchedule.ledger_threshold || 10);
  if (economyBlockSchedule.mode === "hybrid" || economyBlockSchedule.mode === "ledger_count") {
    const remainingEntries = Math.max(0, threshold - unsealed);
    const target = economyBlockSchedule.nextSealAtMs || 0;
    const remainingSeconds = target ? Math.max(0, Math.ceil((target - Date.now()) / 1000)) : null;
    if (!unsealed) {
      el.textContent = `封塊進度：目前沒有未封 ledger；累積 ${threshold} 筆或最長等待 ${economyBlockSchedule.max_interval_minutes || "-"} 分鐘自動封塊`;
    } else if (remainingEntries) {
      const timeText = remainingSeconds === null ? "" : `，時間還剩 ${formatEconomyCountdown(remainingSeconds)}`;
      el.textContent = `封塊進度：${unsealed}/${threshold} 筆，還差 ${remainingEntries} 筆${timeText}`;
    } else {
      el.textContent = `封塊進度：${unsealed}/${threshold} 筆，可自動封塊`;
    }
    return;
  }
  const interval = Number(economyBlockSchedule.interval_minutes || 0);
  if (!unsealed) {
    el.textContent = `封塊倒數：目前沒有未封 ledger；設定為每 ${interval || "-"} 分鐘封塊一次`;
    return;
  }
  const target = economyBlockSchedule.nextSealAtMs || 0;
  const remaining = Math.max(0, Math.ceil((target - Date.now()) / 1000));
  el.textContent = remaining
    ? `封塊倒數：${formatEconomyCountdown(remaining)}（每 ${interval || "-"} 分鐘封塊一次）`
    : `封塊倒數：可封塊（每 ${interval || "-"} 分鐘封塊一次）`;
}

function startEconomyBlockCountdown(schedule) {
  stopEconomyBlockCountdown();
  economyBlockSchedule = null;
  if (!schedule) {
    const el = $("economy-chain-countdown");
    if (el) el.textContent = "封塊進度：-";
    return;
  }
  const nextMs = schedule.next_seal_at ? Date.parse(schedule.next_seal_at) : 0;
  economyBlockSchedule = { ...schedule, nextSealAtMs: Number.isFinite(nextMs) ? nextMs : 0 };
  updateEconomyBlockCountdown();
  economyBlockCountdownTimer = setInterval(updateEconomyBlockCountdown, 1000);
}

function renderEconomyWallet(wallet) {
  if (!wallet) return;
  const pointsBalance = wallet.points_balance !== undefined
    ? Number(wallet.points_balance || 0)
    : Number(wallet.soft_balance || 0) + Number(wallet.hard_balance || 0);
  const pointsFrozen = wallet.points_frozen !== undefined
    ? Number(wallet.points_frozen || 0)
    : Number(wallet.soft_frozen || 0) + Number(wallet.hard_frozen || 0);
  const pointsEarned = wallet.total_points_earned !== undefined
    ? Number(wallet.total_points_earned || 0)
    : Number(wallet.total_soft_earned || 0) + Number(wallet.total_hard_earned || 0);
  const pointsSpent = wallet.total_points_spent !== undefined
    ? Number(wallet.total_points_spent || 0)
    : Number(wallet.total_soft_spent || 0) + Number(wallet.total_hard_spent || 0);
  if ($("economy-points-balance")) $("economy-points-balance").textContent = String(pointsBalance);
  if ($("economy-points-frozen")) $("economy-points-frozen").textContent = `凍結 ${pointsFrozen}`;
  if ($("economy-points-earned")) $("economy-points-earned").textContent = `收入 ${pointsEarned}`;
  if ($("economy-points-spent")) $("economy-points-spent").textContent = `支出 ${pointsSpent}`;
  if ($("economy-soft-balance")) $("economy-soft-balance").textContent = String(pointsBalance);
  if ($("economy-hard-balance")) $("economy-hard-balance").textContent = "0";
  if ($("economy-soft-frozen")) $("economy-soft-frozen").textContent = `凍結 ${pointsFrozen}`;
  if ($("economy-hard-frozen")) $("economy-hard-frozen").textContent = "凍結 0";
  if ($("economy-wallet-status")) $("economy-wallet-status").textContent = wallet.wallet_status || "-";
  if ($("economy-public-account")) {
    const accountId = wallet.public_account_id || "";
    $("economy-public-account").textContent = accountId ? `Legacy 帳本 ID：${shortEconomyWalletAddress(accountId)}` : "Legacy 帳本 ID：-";
    $("economy-public-account").title = accountId;
  }
  const sidebarPoints = $("sidebar-points");
  if (sidebarPoints) {
    sidebarPoints.dataset.points = String(pointsBalance);
    updateSidebarIdentity();
  }
}

function formatEconomyWalletIdentityType(type) {
  const labels = {
    official_hot: "官方熱錢包",
    self_custody_cold: "自管冷錢包",
    imported_cold: "匯入冷錢包",
    multisig: "多簽錢包",
    mint: "Mint 錢包",
    burn: "Burn 錢包",
  };
  return labels[String(type || "")] || String(type || "-");
}

function renderEconomyWalletOnboarding(onboarding) {
  const card = $("economy-wallet-onboarding-card");
  if (!card) return;
  const rootMode = currentUser === "root";
  card.style.display = rootMode ? "none" : "";
  if (rootMode) return;
  const wallet = onboarding?.wallet || null;
  const required = !!onboarding?.required;
  const actions = $("economy-wallet-onboarding-actions");
  if (actions) actions.style.display = required ? "" : "none";
  if ($("economy-wallet-onboarding-status")) {
    $("economy-wallet-onboarding-status").textContent = wallet
      ? "已綁定模擬鏈錢包；伺服器未保存用戶冷錢包私鑰。"
      : "尚未綁定模擬鏈錢包；完成後才發放註冊禮。";
  }
  if ($("economy-wallet-identity-type")) $("economy-wallet-identity-type").textContent = formatEconomyWalletIdentityType(wallet?.wallet_type);
  if ($("economy-wallet-identity-custody")) $("economy-wallet-identity-custody").textContent = wallet?.custody_mode || "-";
  if ($("economy-wallet-identity-address")) {
    $("economy-wallet-identity-address").textContent = wallet?.address || "-";
    $("economy-wallet-identity-address").title = wallet?.address || "";
  }
  if ($("economy-wallet-identity-status")) $("economy-wallet-identity-status").textContent = wallet?.status || "-";
  if ($("economy-wallet-signup-bonus")) {
    $("economy-wallet-signup-bonus").textContent = onboarding?.signup_bonus_granted ? "已領取" : "待領取";
  }
}

async function postEconomyWalletOnboarding(payload) {
  await fetchCsrfToken({ force: true });
  const json = await fetchEconomyJson("/points/wallet/onboarding", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderEconomyWalletOnboarding(json.onboarding || {});
  if (json.signup_bonus?.created) economyWalletMsg("錢包已綁定，註冊禮已入帳。");
  else economyWalletMsg("錢包已綁定。");
  await loadEconomyDashboard();
}

async function useOfficialHotWallet() {
  try {
    await postEconomyWalletOnboarding({ mode: "official_hot" });
  } catch (err) {
    economyWalletMsg(err.message || "官方熱錢包建立失敗", false);
  }
}

async function createColdWalletDraft() {
  if (!window.crypto?.subtle) {
    economyWalletMsg("此瀏覽器不支援 WebCrypto，無法建立冷錢包", false);
    return;
  }
  try {
    const keyPair = await crypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-256" },
      true,
      ["sign", "verify"]
    );
    const privateJwk = await crypto.subtle.exportKey("jwk", keyPair.privateKey);
    const publicJwk = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
    economyGeneratedColdWallet = { privateKey: keyPair.privateKey, publicJwk, privateJwk };
    if ($("economy-wallet-private-key")) $("economy-wallet-private-key").value = JSON.stringify(privateJwk, null, 2);
    if ($("economy-wallet-private-key-confirmed")) $("economy-wallet-private-key-confirmed").checked = false;
    economyWalletMsg("冷錢包已在瀏覽器產生。請保存私鑰後再確認綁定。");
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包建立失敗", false);
  }
}

async function importColdWalletFromText() {
  if (!window.crypto?.subtle) {
    economyWalletMsg("此瀏覽器不支援 WebCrypto，無法匯入冷錢包", false);
    return;
  }
  try {
    const raw = $("economy-wallet-private-key")?.value || "";
    const privateJwk = JSON.parse(raw);
    if (!privateJwk?.d) throw new Error("請貼上含 private d 欄位的 JWK 私鑰");
    const privateKey = await crypto.subtle.importKey(
      "jwk",
      privateJwk,
      { name: "ECDSA", namedCurve: "P-256" },
      true,
      ["sign"]
    );
    const publicJwk = economyCanonicalPublicJwk(privateJwk);
    economyGeneratedColdWallet = { privateKey, publicJwk, privateJwk, imported: true };
    if ($("economy-wallet-private-key-confirmed")) $("economy-wallet-private-key-confirmed").checked = false;
    economyWalletMsg("冷錢包已匯入瀏覽器。確認已保存後即可綁定。");
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包匯入失敗", false);
  }
}

async function confirmColdWalletBinding() {
  try {
    if (!$("economy-wallet-private-key-confirmed")?.checked) {
      economyWalletMsg("請先確認已保存私鑰", false);
      return;
    }
    if (!economyGeneratedColdWallet) {
      await importColdWalletFromText();
      if (!economyGeneratedColdWallet) return;
    }
    const walletType = economyGeneratedColdWallet.imported ? "imported_cold" : "self_custody_cold";
    const payload = await economyBuildWalletBindPayload({
      privateKey: economyGeneratedColdWallet.privateKey,
      publicJwk: economyGeneratedColdWallet.publicJwk,
      walletType,
    });
    await postEconomyWalletOnboarding(payload);
    economyGeneratedColdWallet = null;
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包綁定失敗", false);
  }
}

async function createMultisigWallet() {
  try {
    const signers = String($("economy-wallet-multisig-signers")?.value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const threshold = Number($("economy-wallet-multisig-threshold")?.value || 2);
    await postEconomyWalletOnboarding({ mode: "multisig", signer_addresses: signers, threshold });
  } catch (err) {
    economyWalletMsg(err.message || "多簽錢包建立失敗", false);
  }
}

function renderEconomyCatalog(items) {
  const list = $("economy-catalog-list");
  if (!list) return;
  if (!items || !items.length) {
    list.innerHTML = `<div class="drive-empty">尚無服務價格</div>`;
    return;
  }
  list.innerHTML = items.map((item) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(item.item_name || item.item_key)}</strong>
        <div class="drive-card-sub">${sanitize(item.category || "-")} · ${Number(item.base_price || 0)} ${formatPointsCurrency(item.currency_type)}</div>
      </div>
      <button class="btn" type="button" data-economy-spend="${sanitize(item.item_key)}">試扣</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-economy-spend]").forEach((btn) => {
    btn.addEventListener("click", () => spendEconomyItem(btn.dataset.economySpend || ""));
  });
}

function exportEconomyLedgerCsv() {
  const rows = economyLedgerCache;
  if (!rows || !rows.length) { economySetMsg("尚無帳本資料可匯出", false); return; }
  const header = ["時間", "方向", "金額", "幣種", "類型", "Ledger UUID", "Ledger Hash"];
  const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [header.map(escape).join(",")];
  for (const row of rows) {
    lines.push([
      row.created_at || "",
      row.direction || "",
      row.amount ?? "",
      row.currency_type || "",
      row.action_type || "",
      row.ledger_uuid || "",
      row.ledger_hash || "",
    ].map(escape).join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `ledger_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadCsvEndpoint(path, label) {
  try {
    const res = await apiFetch(API + path, { credentials: "same-origin" });
    if (!res.ok) {
      const json = await res.clone().json().catch(() => ({}));
      throw new Error(json.msg || json.message || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : `${label.replace(/\s+/g, "_")}_${new Date().toISOString().slice(0, 10)}.csv`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    economySetMsg(`${label} 下載已開始`, true);
  } catch (err) {
    economySetMsg(err.message || `${label} 下載失敗`, false);
  }
}

function downloadEconomyWalletCsv() {
  downloadCsvEndpoint("/points/wallet/export.csv", "積分錢包 CSV");
}

function downloadEconomyTradingCsv() {
  downloadCsvEndpoint("/trading/history/export.csv", "交易紀錄 CSV");
}

function renderEconomyLedger(rows, targetId = "economy-ledger-list") {
  if (targetId === "economy-ledger-list") economyLedgerCache = Array.isArray(rows) ? rows : [];
  const list = $(targetId);
  if (!list) return;
  if (!rows || !rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無帳本紀錄</div>`;
    return;
  }
  list.innerHTML = rows.map((row) => {
    const source = formatEconomyLedgerSource(row);
    const walletFlow = formatEconomyLedgerWalletFlow(row);
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(formatEconomyLedgerAmount(row))}</strong>
          <div class="drive-card-sub">${sanitize(formatEconomyLedgerAction(row.action_type))} · ${sanitize(row.created_at || "")}</div>
          ${walletFlow ? `<div class="drive-card-sub economy-ledger-wallet-flow">${sanitize(walletFlow)}</div>` : ""}
          ${source ? `<div class="drive-card-sub">${sanitize(source)}</div>` : ""}
          <div class="economy-ledger-hash">Ledger UUID：${sanitize(row.ledger_uuid || row.ledger_hash || "")}</div>
        </div>
        <button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-economy-proof]").forEach((btn) => {
    btn.addEventListener("click", () => loadEconomyProof(btn.dataset.economyProof || ""));
  });
}

function renderEconomyRootList(rows, targetId, emptyText, renderRow) {
  const list = $(targetId);
  if (!list) return;
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) {
    list.innerHTML = `<div class="drive-empty">${sanitize(emptyText)}</div>`;
    return;
  }
  list.innerHTML = safeRows.map(renderRow).join("");
}

function setEconomyChainStatus(text, ok = true) {
  const status = $("economy-chain-status");
  if (!status) return;
  status.textContent = text || "";
  status.className = ok ? "drive-card-sub economy-chain-status ok" : "drive-card-sub economy-chain-status err";
}

function formatEconomyVerificationSummary(verification) {
  const safe = verification && typeof verification === "object" ? verification : {};
  const counts = safe.counts && typeof safe.counts === "object" ? safe.counts : {};
  const state = safe.ok === true ? "全鏈驗證正常" : (safe.ok === false ? "全鏈驗證異常" : "全鏈狀態未知");
  return `${state}：${Number(counts.ledger_entries || 0)} 筆 ledger，${Number(counts.sealed_blocks || 0)} 個封塊，${Number(counts.unsealed_entries || 0)} 筆未封，${Number(counts.audit_events || 0)} 筆審計事件`;
}

function formatEconomyRecoveryResult(result) {
  const safe = result && typeof result === "object" ? result : {};
  const rebuild = safe.wallet_rebuild && typeof safe.wallet_rebuild === "object" ? safe.wallet_rebuild : {};
  const verification = safe.verification && typeof safe.verification === "object" ? safe.verification : {};
  const counts = verification.counts && typeof verification.counts === "object" ? verification.counts : {};
  if (safe.ok !== true) return safe.msg || "PointsChain 恢復失敗";
  return [
    "PointsChain 已恢復並完成驗證",
    `備份：${safe.backup_id || "-"}`,
    `錢包重建：${Number(rebuild.wallets_rebuilt || 0)} 個`,
    `ledger：${Number(counts.ledger_entries || 0)} 筆`,
    `封塊：${Number(counts.sealed_blocks || 0)} 個`,
    `safe mode：${(safe.recovery || {}).safe_mode ? "仍啟用" : "已解除"}`,
  ].join("；");
}

function setEconomyText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function renderEconomyRootBalanceSummary(report) {
  const stats = report?.stats && typeof report.stats === "object" ? report.stats : {};
  const circulation = stats.circulation && typeof stats.circulation === "object" ? stats.circulation : {};
  const memberOutstanding = Number(circulation.member_outstanding_points ?? circulation.outstanding_points ?? 0);
  const memberLedgerNet = Number(circulation.member_ledger_net_points ?? circulation.ledger_net_points ?? 0);
  const memberGap = Number(circulation.member_supply_gap_points ?? circulation.supply_gap_points ?? 0);
  const memberFrozen = Number(circulation.member_frozen_points ?? circulation.frozen_points ?? 0);
  setEconomyText("economy-root-outstanding-points", formatEconomyPointsValue(memberOutstanding));
  setEconomyText(
    "economy-root-outstanding-detail",
    `可用 ${formatEconomyPointsValue(circulation.member_available_points ?? circulation.available_points ?? 0)} · root ${formatEconomyPointsValue(circulation.root_outstanding_points || 0)}`,
  );
  setEconomyText("economy-root-ledger-net-points", formatEconomyPointsValue(memberLedgerNet));
  setEconomyText("economy-root-supply-gap", `差額 ${formatEconomyPointsValue(memberGap)}`);
  setEconomyText("economy-root-wallet-count", formatEconomyPointsValue(circulation.member_wallet_count ?? circulation.wallet_count ?? 0));
  setEconomyText("economy-root-wallet-detail", `凍結 ${formatEconomyPointsValue(memberFrozen)} · root 錢包 ${formatEconomyPointsValue(circulation.root_wallet_count || 0)}`);
  setEconomyText("economy-root-chain-coverage", formatEconomyPercentValue(circulation.sealed_coverage_percent || 0));
  setEconomyText(
    "economy-root-chain-coverage-detail",
    `未封 ${formatEconomyPointsValue(circulation.unsealed_ledger_entries || 0)} / ledger ${formatEconomyPointsValue(circulation.confirmed_ledger_entries || 0)}`,
  );
}

function renderEconomyLayerSummary(report) {
  const stats = report?.stats && typeof report.stats === "object" ? report.stats : {};
  const layer = stats.economy_layer && typeof stats.economy_layer === "object" ? stats.economy_layer : {};
  const supply = layer.supply && typeof layer.supply === "object" ? layer.supply : {};
  const funds = layer.funds && typeof layer.funds === "object" ? layer.funds : {};
  const health = layer.health && typeof layer.health === "object" ? layer.health : {};
  const replay = layer.replay && typeof layer.replay === "object" ? layer.replay : {};
  const fund = (key) => funds[key] && typeof funds[key] === "object" ? funds[key] : {};
  const address = (key) => shortEconomyWalletAddress(fund(key).address || "");
  setEconomyText("economy-layer-health", String(health.status || "-").toUpperCase());
  setEconomyText("economy-layer-health-detail", `原因 ${Array.isArray(health.reasons) ? health.reasons.join(", ") : "ok"}`);
  setEconomyText("economy-layer-max-supply", formatEconomyPointsValue(supply.max_supply || 0));
  setEconomyText("economy-layer-minted-total", `已 Mint ${formatEconomyPointsValue(supply.minted_total || 0)}`);
  setEconomyText("economy-layer-releasable-remaining", formatEconomyPointsValue(supply.releasable_remaining || 0));
  setEconomyText("economy-layer-reserved-locked", `保留鎖定 ${formatEconomyPointsValue(supply.reserved_locked || 0)}`);
  setEconomyText("economy-layer-official-balance", formatEconomyPointsValue(fund("official_treasury").balance || 0));
  setEconomyText("economy-layer-official-address", address("official_treasury"));
  setEconomyText("economy-layer-promo-balance", formatEconomyPointsValue(fund("promo_fund").balance || 0));
  setEconomyText("economy-layer-promo-address", address("promo_fund"));
  setEconomyText("economy-layer-exchange-balance", formatEconomyPointsValue(fund("exchange_fund").balance || 0));
  setEconomyText("economy-layer-exchange-address", address("exchange_fund"));
  setEconomyText("economy-layer-burned-total", formatEconomyPointsValue(supply.burned_total || 0));
  setEconomyText("economy-layer-burn-address", address("burn"));
  setEconomyText("economy-layer-replay-height", formatEconomyPointsValue(replay.height || 0));
  setEconomyText("economy-layer-replay-hash", `derived cache · ${shortEconomyWalletAddress(replay.wallet_root_hash || "")}`);
}

function renderEconomyRootFundingPools(payload) {
  const safe = payload && typeof payload === "object" ? payload : {};
  const reserve = safe.reserve_pool && typeof safe.reserve_pool === "object" ? safe.reserve_pool : {};
  const funding = safe.funding_pool && typeof safe.funding_pool === "object" ? safe.funding_pool : {};
  const lending = safe.lending_summary && typeof safe.lending_summary === "object" ? safe.lending_summary : {};
  const margin = safe.open_margin_summary && typeof safe.open_margin_summary === "object" ? safe.open_margin_summary : {};
  const fees = safe.fee_summary && typeof safe.fee_summary === "object" ? safe.fee_summary : {};
  setEconomyText("economy-root-reserve-balance", formatEconomyPointsValue(reserve.balance_points || 0));
  setEconomyText("economy-root-reserve-updated", `更新 ${reserve.updated_at || "-"}`);
  setEconomyText("economy-root-funding-available", formatEconomyPointsValue(funding.available_points || 0));
  setEconomyText("economy-root-funding-outstanding", `貸出 ${formatEconomyPointsValue(funding.outstanding_principal_points || 0)}`);
  setEconomyText("economy-root-funding-utilization", formatEconomyPercentValue(funding.utilization_percent || 0));
  setEconomyText("economy-root-funding-apr", `APR ${formatEconomyPercentValue(funding.effective_interest_apr_percent || 0)} · ${funding.borrowed_asset_symbol || "POINTS"}`);
  const retainedIncome = Number(lending.fee_retained_points || 0) + Number(lending.interest_retained_points || 0);
  setEconomyText("economy-root-pool-income", formatEconomyPointsValue(retainedIncome));
  setEconomyText(
    "economy-root-pool-income-detail",
    `fee ${formatEconomyPointsValue(lending.fee_retained_points || fees.total_fee_points || 0)} / interest ${formatEconomyPointsValue(lending.interest_retained_points || 0)}`,
  );
  renderEconomyRootList([
    {
      title: "借貸池",
      value: `可用 ${formatEconomyPointsValue(funding.available_points || 0)} · 貸出 ${formatEconomyPointsValue(funding.outstanding_principal_points || 0)}`,
      detail: `容量 ${formatEconomyPointsValue(funding.capacity_points || 0)} · 使用率 ${formatEconomyPercentValue(funding.utilization_percent || 0)}`,
    },
    {
      title: "本金與回收",
      value: `貸出 ${formatEconomyPointsValue(lending.lent_out_points || 0)} · 回收 ${formatEconomyPointsValue(lending.repaid_points || 0)}`,
      detail: `開放倉位 ${formatEconomyPointsValue(margin.open_margin_positions || 0)} · 本金 ${formatEconomyPointsValue(margin.open_principal_points || 0)}`,
    },
    {
      title: "利息與 carry",
      value: `應收 ${formatEconomyPointsValue(margin.open_interest_due_points || 0)} · 已保留 ${formatEconomyPointsValue(lending.interest_retained_points || 0)}`,
      detail: `micropoints carry ${formatEconomyPointsValue(margin.interest_carry_micropoints || 0)} · 最近事件 ${lending.latest_reserve_event_at || "-"}`,
    },
  ], "economy-root-lending-pool-list", "尚無借貸池資料", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.title)}</strong>
        <div class="drive-card-sub">${sanitize(row.value)}</div>
        <div class="drive-card-sub">${sanitize(row.detail)}</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safe.reserve_events || [], "economy-root-reserve-events-list", "尚無資金池事件", (row) => {
    const delta = Number(row.delta_points || 0);
    const signed = delta >= 0 ? `+${formatEconomyPointsValue(delta)}` : `-${formatEconomyPointsValue(Math.abs(delta))}`;
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.event_type || "-")} · ${sanitize(signed)} 點</strong>
          <div class="drive-card-sub">${sanitize(row.created_at || "")} · balance ${sanitize(formatEconomyPointsValue(row.balance_after || 0))}</div>
          <div class="drive-card-sub">${sanitize(row.reason || "-")} · source ${sanitize(row.source_username || row.source_user_id || "-")}</div>
        </div>
      </div>
    `;
  });
}

function renderEconomyRootAllPositions(payload) {
  const safe = payload && typeof payload === "object" ? payload : {};
  const summary = safe.summary && typeof safe.summary === "object" ? safe.summary : {};
  setEconomyText("economy-root-position-users", formatEconomyPointsValue(summary.user_count || 0));
  setEconomyText("economy-root-position-wallet-total", `在外 ${formatEconomyPointsValue(summary.total_outstanding_points || 0)}`);
  setEconomyText("economy-root-position-spot-count", formatEconomyPointsValue(summary.spot_position_count || 0));
  setEconomyText("economy-root-position-margin-count", formatEconomyPointsValue(summary.margin_position_count || 0));
  setEconomyText("economy-root-position-margin-detail", `開倉 ${formatEconomyPointsValue(summary.margin_position_count || 0)}`);
  setEconomyText("economy-root-position-orders", formatEconomyPointsValue(summary.open_order_count || 0));
  setEconomyText("economy-root-position-orders-detail", `凍結 ${formatEconomyPointsValue(summary.frozen_order_points || 0)}`);
  setEconomyText("economy-root-position-bots", formatEconomyPointsValue(summary.total_bot_count || 0));
  setEconomyText("economy-root-position-bots-detail", `啟用 ${formatEconomyPointsValue(summary.total_enabled_bot_count || 0)} · 網格 ${formatEconomyPointsValue(summary.grid_bot_count || 0)}`);
  renderEconomyRootList(safe.wallets || [], "economy-root-wallet-position-list", "尚無會員錢包", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.username || `user:${row.user_id || "-"}`)} · ${sanitize(formatEconomyPointsValue(row.outstanding_points || 0))} 點</strong>
        <div class="drive-card-sub">可用 ${sanitize(formatEconomyPointsValue(row.points_balance || 0))} · 凍結 ${sanitize(formatEconomyPointsValue(row.points_frozen || 0))}</div>
        <div class="drive-card-sub">wallet ${sanitize(row.wallet_status || "-")} · risk ${sanitize(row.risk_level || "-")} · ${sanitize(row.wallet_updated_at || "-")}</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safe.spot_positions || [], "economy-root-spot-position-list", "尚無現貨倉位", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.username || `user:${row.user_id || "-"}`)} · ${sanitize(economyDisplayMarketSymbol(row.market_symbol))}</strong>
        <div class="drive-card-sub">數量 ${sanitize(formatEconomyQuantityValue(row.quantity))} · 鎖定 ${sanitize(formatEconomyQuantityValue(row.locked_quantity))}</div>
        <div class="drive-card-sub">均價 ${sanitize(formatEconomyPointsValue(row.avg_cost_points || 0))} · TP ${sanitize(row.take_profit_percent ?? "-")}% · SL ${sanitize(row.stop_loss_percent ?? "-")}%</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safe.margin_positions || [], "economy-root-margin-position-list", "尚無借貸倉位", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.username || `user:${row.user_id || "-"}`)} · ${sanitize(economyDisplayMarketSymbol(row.market_symbol))} · ${sanitize(row.position_type || "-")}</strong>
        <div class="drive-card-sub">數量 ${sanitize(formatEconomyQuantityValue(row.quantity))} · 入場 ${sanitize(formatEconomyPointsValue(row.entry_price_points || 0))}</div>
        <div class="drive-card-sub">本金 ${sanitize(formatEconomyPointsValue(row.principal_points || 0))} · 擔保 ${sanitize(formatEconomyPointsValue(row.collateral_points || 0))} · 利息 ${sanitize(formatEconomyPointsValue(row.interest_due_points || 0))}</div>
        <div class="economy-ledger-hash">${sanitize(row.position_uuid || "")}</div>
      </div>
    </div>
  `);
  const botRows = [
    ...(Array.isArray(safe.bots) ? safe.bots.map((row) => ({ ...row, family: "bot" })) : []),
    ...(Array.isArray(safe.grid_bots) ? safe.grid_bots.map((row) => ({ ...row, family: "grid" })) : []),
  ];
  renderEconomyRootList(botRows, "economy-root-bot-position-list", "尚無交易機器人", (row) => {
    const isGrid = row.family === "grid";
    const status = row.enabled ? "啟用" : "暫停";
    const subtitle = isGrid
      ? `格數 ${formatEconomyPointsValue(row.grid_count || 0)} · 每格 ${formatEconomyPointsValue(row.order_amount_points || 0)} 點 · 掛單 ${formatEconomyPointsValue(row.open_grid_orders || 0)}`
      : `${sanitize(row.side || "-")} ${sanitize(row.order_type || "-")} · 執行 ${formatEconomyPointsValue(row.run_count || 0)} / ${formatEconomyPointsValue(row.max_runs || 0)}`;
    const timing = isGrid
      ? `掃描 ${sanitize(row.last_scan_at || "-")} · 成交 ${formatEconomyPointsValue(row.total_trades || 0)} · 利潤 ${formatEconomyPointsValue(row.total_profit_points || 0)}`
      : `觸發 ${sanitize(row.trigger_type || "-")} ${sanitize(row.trigger_price_points ?? "-")} · 最近 ${sanitize(row.last_run_at || "-")}`;
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.username || `user:${row.user_id || "-"}`)} · ${sanitize(row.name || row.bot_uuid || "-")} · ${sanitize(isGrid ? "網格" : row.bot_type || "bot")} · ${sanitize(status)}</strong>
          <div class="drive-card-sub">${sanitize(economyDisplayMarketSymbol(row.market_symbol))} · ${subtitle}</div>
          <div class="drive-card-sub">${timing}</div>
          ${row.last_error ? `<div class="drive-card-sub negative">錯誤 ${sanitize(row.last_error)}</div>` : ""}
        </div>
      </div>
    `;
  });
}

function renderEconomyRootReport(report) {
  const safeReport = report && typeof report === "object" ? report : {};
  renderEconomyRootBalanceSummary(safeReport);
  renderEconomyLayerSummary(safeReport);
  const verification = safeReport.verification && typeof safeReport.verification === "object" ? safeReport.verification : {};
  const counts = verification.counts && typeof verification.counts === "object" ? verification.counts : {};
  if ($("economy-chain-ok")) {
    $("economy-chain-ok").textContent = verification.ok === true ? "完整" : (verification.ok === false ? "異常" : "未知");
  }
  if ($("economy-chain-counts")) $("economy-chain-counts").textContent = `${Number(counts.ledger_entries || 0)} 筆 ledger`;
  if ($("economy-chain-blocks")) $("economy-chain-blocks").textContent = String(counts.sealed_blocks || 0);
  if ($("economy-chain-unsealed")) $("economy-chain-unsealed").textContent = `未封 ${Number(counts.unsealed_entries || 0)}`;
  if ($("economy-chain-audit-count")) $("economy-chain-audit-count").textContent = String(counts.audit_events || 0);
  startEconomyBlockCountdown(safeReport.block_schedule || null);
  renderEconomyRecovery(safeReport.recovery || {}, safeReport.ledger_backups || []);
  renderEconomyRootList(safeReport.blocks, "economy-block-list", "尚無封塊", (block) => `
    <div class="drive-file-row">
      <div>
        <strong>#${Number(block.block_number || 0)} · ${Number(block.ledger_count || 0)} 筆</strong>
        <div class="drive-card-sub">${sanitize(block.sealed_at || "")} · ${sanitize(block.anchor_status || "local_only")} · ${sanitize(block.signature_algorithm || "unsigned")}</div>
        <div class="economy-ledger-hash">${sanitize(block.block_hash || "")}</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safeReport.audit_logs, "economy-audit-list", "尚無審計事件", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.event_type || "-")} · ${sanitize(row.severity || "-")}</strong>
        <div class="drive-card-sub">${sanitize(row.created_at || "")} · actor=${sanitize(row.actor_user_id || "-")} · target=${sanitize(row.target_user_id || "-")}</div>
        <div class="drive-card-sub">${sanitize(row.message || "")}</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safeReport.high_risk_ledger, "economy-risk-ledger-list", "尚無異常帳本", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.verification_status || row.status || "-")} · ${sanitize(formatEconomyLedgerAmount(row))}</strong>
        <div class="drive-card-sub">ledger #${Number(row.id || 0)} · user ${Number(row.user_id || 0)} · ${sanitize(formatEconomyLedgerAction(row.action_type))} · risk=${sanitize(row.risk_flag || "none")}</div>
        ${(Array.isArray(row.verification_errors) ? row.verification_errors : []).map((issue) => `
          <div class="drive-card-sub">
            驗證異常：${sanitize(issue.type || "-")} · ${sanitize(issue.message || "")}
          </div>
          ${issue.expected_ledger_hash || issue.actual_ledger_hash ? `<div class="economy-ledger-hash">expected=${sanitize(issue.expected_ledger_hash || "-")} · actual=${sanitize(issue.actual_ledger_hash || "-")}</div>` : ""}
          ${issue.expected_previous_ledger_hash || issue.actual_previous_ledger_hash ? `<div class="economy-ledger-hash">prev expected=${sanitize(issue.expected_previous_ledger_hash || "-")} · prev actual=${sanitize(issue.actual_previous_ledger_hash || "-")}</div>` : ""}
        `).join("")}
        <div class="economy-ledger-hash">${sanitize(row.ledger_uuid || "")}</div>
      </div>
      <button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>
    </div>
  `);
  const riskList = $("economy-risk-ledger-list");
  if (riskList) {
    riskList.querySelectorAll("[data-economy-proof]").forEach((btn) => {
      btn.addEventListener("click", () => loadEconomyProof(btn.dataset.economyProof || ""));
    });
  }
  renderEconomyRootList(safeReport.adjustments, "economy-adjustment-list", "尚無收入 / 加減分明細", (row) => {
    const signed = Number(row.signed_amount || 0);
    const directionText = signed >= 0 ? `+${signed}` : String(signed);
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.actor_username || "system")} → ${sanitize(row.target_username || `user:${row.user_id || "-"}`)} · ${directionText} ${formatPointsCurrency(row.currency_type)}</strong>
          <div class="drive-card-sub">原因：${sanitize(row.reason || "-")} · ${sanitize(row.created_at || "")}</div>
          <div class="drive-card-sub">動作：${sanitize(formatEconomyLedgerAction(row.action_type))} · 狀態：${sanitize(row.status || "-")}</div>
          <div class="economy-ledger-hash">${sanitize(row.ledger_uuid || "")}</div>
        </div>
        <button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>
      </div>
    `;
  });
  const adjustmentList = $("economy-adjustment-list");
  if (adjustmentList) {
    adjustmentList.querySelectorAll("[data-economy-proof]").forEach((btn) => {
      btn.addEventListener("click", () => loadEconomyProof(btn.dataset.economyProof || ""));
    });
  }
  const loadedAt = new Date().toLocaleTimeString("zh-TW", { hour12: false });
  if ($("economy-chain-loaded-at")) $("economy-chain-loaded-at").textContent = `最後更新 ${loadedAt}`;
  setEconomyChainStatus(formatEconomyVerificationSummary(verification), verification.ok !== false);
}

function renderEconomyRecovery(recovery, backups) {
  const safe = recovery && typeof recovery === "object" ? recovery : {};
  const plan = safe.restore_plan && typeof safe.restore_plan === "object" ? safe.restore_plan : {};
  const rows = Array.isArray(backups) ? backups : [];
  const status = $("economy-recovery-status");
  if (status) {
    status.textContent = safe.safe_mode
      ? `safe mode：啟用 · ${safe.reason || "-"} · forensic=${safe.forensic_bundle_id || "-"}`
      : "safe mode：未啟用";
    status.style.color = safe.safe_mode ? "#ffb74d" : "var(--muted)";
  }
  const select = $("economy-recovery-backup-id");
  if (select) {
    const recommended = plan.recommended_backup_id || "";
    select.innerHTML = rows.length
      ? rows.map((backup) => {
          const label = `${backup.backup_id} · height ${backup.chain_height || 0} · ${backup.created_at || ""}`;
          return `<option value="${sanitize(backup.backup_id || "")}" ${backup.backup_id === recommended ? "selected" : ""}>${sanitize(label)}</option>`;
        }).join("")
      : `<option value="">尚無可用備份</option>`;
  }
  renderEconomyRootList([plan], "economy-restore-plan-list", "目前沒有恢復方案", (item) => `
    <div class="drive-file-row">
      <div>
        <strong>建議備份：${sanitize(item.recommended_backup_id || "無")}</strong>
        <div class="drive-card-sub">目前 height ${Number(item.current_chain_height || 0)} → 備份 height ${Number(item.backup_chain_height || 0)}；wallet 來源：${sanitize(item.wallet_rebuild_source || "-")}</div>
        <div class="drive-card-sub">可能遺失交易：${Number((item.lost_ledger_range || {}).count || 0)} 筆（${sanitize((item.lost_ledger_range || {}).from_id || "-")} - ${sanitize((item.lost_ledger_range || {}).to_id || "-")}）</div>
      </div>
    </div>
  `);
  renderEconomyRootList(rows.slice(0, 12), "economy-backup-list", "尚無 ledger backup", (backup) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(backup.kind || "backup")} · height ${Number(backup.chain_height || 0)} · ${backup.verified ? "已驗證" : "驗證失敗"}</strong>
        <div class="drive-card-sub">${sanitize(backup.created_at || "")} · ledger ${Number(backup.ledger_row_count || 0)} · wallet snapshot ${Number(backup.wallet_count || 0)}</div>
        <div class="economy-ledger-hash">${sanitize(backup.latest_block_hash || backup.backup_id || "")}</div>
      </div>
    </div>
  `);
}

function renderEconomyAccountLookup(wallet, ledger) {
  const safeWallet = wallet && typeof wallet === "object" ? wallet : {};
  const pointsBalance = Number(safeWallet.points_balance || 0);
  const pointsFrozen = Number(safeWallet.points_frozen || 0);
  const pointsEarned = Number(safeWallet.total_points_earned || 0);
  const pointsSpent = Number(safeWallet.total_points_spent || 0);
  if ($("economy-query-points-balance")) $("economy-query-points-balance").textContent = String(pointsBalance);
  if ($("economy-query-points-frozen")) $("economy-query-points-frozen").textContent = `凍結 ${pointsFrozen}`;
  if ($("economy-query-points-earned")) $("economy-query-points-earned").textContent = `收入 ${pointsEarned}`;
  if ($("economy-query-points-spent")) $("economy-query-points-spent").textContent = `支出 ${pointsSpent}`;
  if ($("economy-query-wallet-status")) $("economy-query-wallet-status").textContent = safeWallet.wallet_status || "-";
  if ($("economy-query-public-account")) $("economy-query-public-account").textContent = safeWallet.public_account_id || "-";
  if ($("economy-wallet-sanction-status")) $("economy-wallet-sanction-status").value = safeWallet.wallet_status || "active";
  if ($("economy-wallet-sanction-risk")) $("economy-wallet-sanction-risk").value = safeWallet.risk_level || "normal";
  renderEconomyLedger(Array.isArray(ledger) ? ledger.slice(0, 12) : [], "economy-query-ledger-list");
}

async function fetchEconomyJson(url, options = {}) {
  const { allowMissingSnapshot = false, ...requestOptions } = options || {};
  await fetchCsrfToken({ force: true });
  const headers = { ...(requestOptions.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (requestOptions.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await apiFetch(API + url, { credentials: "same-origin", ...requestOptions, headers });
  const json = await res.json().catch(() => ({}));
  if (allowMissingSnapshot && json?.snapshot?.missing) return json;
  if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
  return json;
}

async function loadEconomyDashboard() {
  if (!currentUser) return;
  try {
    const rootMode = currentUser === "root";
    const canManagePoints = canManageEconomyPoints();
    const adminCard = $("economy-admin-card");
    syncEconomySubpages(rootMode);
    if ($("economy-user-summary-grid")) $("economy-user-summary-grid").style.display = rootMode ? "none" : "";
    if ($("economy-user-ledger-card")) $("economy-user-ledger-card").style.display = rootMode ? "none" : "";
    setEconomyRootLayout(rootMode);
    if (adminCard) adminCard.style.display = canManagePoints ? "" : "none";
    if (rootMode) {
      if ($("economy-chain-ok")) $("economy-chain-ok").textContent = "讀取中";
      if ($("economy-chain-countdown")) $("economy-chain-countdown").textContent = "封塊進度：讀取中...";
      const sidebarPoints = $("sidebar-points");
      if (sidebarPoints) {
        sidebarPoints.dataset.points = "root: server resources";
        updateSidebarIdentity();
      }
    } else {
      stopEconomyBlockCountdown();
      const [wallet, ledger, catalog, onboarding] = await Promise.all([
        fetchEconomyJson("/points/wallet"),
        fetchEconomyJson(`/points/ledger?limit=50&offset=${economyLedgerOffset}`),
        fetchEconomyJson("/points/catalog"),
        fetchEconomyJson("/points/wallet/onboarding"),
      ]);
      renderEconomyWallet(wallet.wallet);
      renderEconomyWalletOnboarding(onboarding.onboarding || {});
      renderEconomyLedger(ledger.ledger || []);
      renderEconomyCatalog(catalog.catalog || []);
    }
    if (canManagePoints) {
      loadEconomyAdmin();
    } else {
      if ($("economy-admin-ledger-list")) $("economy-admin-ledger-list").innerHTML = "";
      if ($("economy-pending-list")) $("economy-pending-list").innerHTML = "";
    }
    const rootCard = $("economy-root-card");
    if (rootCard) rootCard.style.display = currentUser === "root" ? "" : "none";
    const rootReportOk = rootMode ? await loadEconomyRootReport() : true;
    const shouldLoadRootTrading = rootMode && ["funding-pools", "all-positions"].includes(economyActivePage);
    const rootTradingOk = shouldLoadRootTrading ? await loadEconomyRootTradingReadOnly() : true;
    if (typeof loadTradingDashboard === "function") {
      await loadTradingDashboard();
    }
    if (rootReportOk !== false && rootTradingOk !== false) economySetMsg("");
  } catch (err) {
    economySetMsg(err.message || "PointsChain 讀取失敗", false);
  }
}

async function loadEconomyRootReport() {
  if (currentUser !== "root") return true;
  setEconomyChainStatus("讀取 PointsChain 狀態中...");
  try {
    const json = await fetchEconomyJson("/root/points/report");
    renderEconomyRootReport(json.report || {});
    economySetMsg("");
    return true;
  } catch (err) {
    stopEconomyBlockCountdown();
    if ($("economy-chain-ok")) $("economy-chain-ok").textContent = "讀取失敗";
    if ($("economy-chain-countdown")) $("economy-chain-countdown").textContent = "封塊進度：讀取失敗";
    setEconomyChainStatus(err.message || "PointsChain 狀態讀取失敗", false);
    economySetMsg(err.message || "PointsChain 狀態讀取失敗", false);
    return false;
  }
}

async function loadEconomyRootTradingReadOnly() {
  if (currentUser !== "root" || !economyPositionsAvailable()) return true;
  try {
    const [pools, positions] = await Promise.all([
      fetchEconomyJson("/root/trading/sitewide/pools", { allowMissingSnapshot: true }),
      fetchEconomyJson("/root/trading/sitewide/user-positions", { allowMissingSnapshot: true }),
    ]);
    if (pools?.snapshot?.missing || positions?.snapshot?.missing) {
      renderEconomyRootFundingPools({});
      renderEconomyRootAllPositions({});
      const queued = typeof enqueueTradingSnapshotRefreshOnce === "function"
        ? await enqueueTradingSnapshotRefreshOnce("economy_trading_readonly_missing_snapshot")
        : { ok: false, msg: "背景刷新 helper 尚未載入" };
      economySetMsg(
        queued?.ok
          ? "交易資金池與全用戶倉位快照正在建立；已排入背景刷新，完成後重新整理即可查看。"
          : `交易資金池與全用戶倉位快照尚未建立；排程失敗：${queued?.msg || "請確認背景 worker"}`,
        queued?.ok !== false,
      );
      return true;
    }
    renderEconomyRootFundingPools(pools.pools || {});
    renderEconomyRootAllPositions(positions.positions || {});
    return true;
  } catch (err) {
    economySetMsg(err.message || "root 交易資金池與倉位資料讀取失敗", false);
    return false;
  }
}

async function loadEconomyAdmin() {
  if (!canManageEconomyPoints()) return;
  try {
    const rootMode = currentUser === "root";
    const fetches = [
      fetchEconomyJson("/admin/points/ledger?limit=50"),
      fetchEconomyJson("/admin/users"),
    ];
    if (rootMode) fetches.splice(1, 0, fetchEconomyJson("/admin/points/pending-rewards?status=pending"));
    const results = await Promise.all(fetches);
    const ledger = results[0];
    const pending = rootMode ? results[1] : null;
    const userList = rootMode ? results[2] : results[1];
    renderEconomyAdjustUserOptions(userList.users || []);
    const adminTitle = $("economy-admin-card-title");
    const adminSub = $("economy-admin-card-sub");
    const adminLedgerList = $("economy-admin-ledger-list");
    const adjustPanel = $("economy-adjust-panel");
    if (adjustPanel) adjustPanel.style.display = rootMode ? "" : "none";
    setEconomyRootLayout(rootMode);
    if (adminTitle) adminTitle.textContent = "手動加減分";
    if (adminSub) {
      adminSub.textContent = rootMode
        ? "這裡只負責送出補償、扣回與審核；加減分歷史統一在下方明細查看"
        : "manager 可查看加減分紀錄；手動加減分只允許 root 操作";
    }
    if (adminLedgerList) {
      adminLedgerList.style.display = rootMode ? "none" : "";
      if (rootMode) {
        adminLedgerList.innerHTML = "";
      } else {
        renderEconomyLedger(ledger.ledger || [], "economy-admin-ledger-list");
      }
    }
    const pendingList = $("economy-pending-list");
    if (pendingList) {
      if (rootMode && pending) {
        const rows = pending.pending_rewards || [];
        pendingList.innerHTML = rows.length ? rows.map((row) => `
          <div class="drive-file-row">
            <div>
              <strong>#${Number(row.id)} · user ${Number(row.user_id)} · ${Number(row.amount)} ${formatPointsCurrency(row.currency_type)}</strong>
              <div class="drive-card-sub">${sanitize(row.action_type || "-")} · ${sanitize(row.created_at || "")}</div>
            </div>
            <div class="drive-file-actions">
              <button class="btn" type="button" data-pending-review="${Number(row.id)}" data-decision="approve">通過</button>
              <button class="btn btn-danger" type="button" data-pending-review="${Number(row.id)}" data-decision="reject">拒絕</button>
            </div>
          </div>
        `).join("") : `<div class="drive-empty">沒有待審核獎勵</div>`;
        pendingList.querySelectorAll("[data-pending-review]").forEach((btn) => {
          btn.addEventListener("click", () => reviewEconomyPendingReward(btn.dataset.pendingReview, btn.dataset.decision));
        });
      } else {
        pendingList.innerHTML = "";
        pendingList.style.display = "none";
      }
    }
  } catch (err) {
    const select = $("economy-adjust-user-id");
    if (select) select.innerHTML = `<option value="">會員讀取失敗</option>`;
    economySetMsg(err.message || "管理資料讀取失敗", false);
  }
}

function renderEconomyAdjustUserOptions(rows) {
  const members = (Array.isArray(rows) ? rows : []).filter((user) => {
    const username = String(user.username || "").toLowerCase();
    return username !== "root";
  });
  const fillSelect = (select, emptyText) => {
    if (!select) return;
    const previous = select.value;
    if (!members.length) {
      select.innerHTML = `<option value="">${sanitize(emptyText)}</option>`;
      return;
    }
    select.innerHTML = `<option value="">請選擇會員</option>` + members.map((user) => {
      const id = Number(user.id);
      const username = sanitize(user.username || `user ${id}`);
      const role = sanitize(user.role || "-");
      const status = sanitize(user.status || "-");
      return `<option value="${id}">${username}（#${id} / ${role} / ${status}）</option>`;
    }).join("");
    if (previous && Array.from(select.options).some((option) => option.value === previous)) {
      select.value = previous;
    }
  };
  fillSelect($("economy-adjust-user-id"), "沒有可調整會員");
  fillSelect($("economy-query-user-id"), "沒有可查詢會員");
  if (typeof syncTradingReserveUserOptions === "function") syncTradingReserveUserOptions();
}

async function loadEconomyAccountLookup() {
  if (currentUser !== "root") return;
  const select = $("economy-query-user-id");
  const userId = Number(select?.value || 0);
  if (!Number.isFinite(userId) || userId <= 0) {
    economySetMsg("請先選擇要查詢的會員", false);
    return;
  }
  const btn = $("economy-account-query-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "查詢中...";
    }
    const json = await fetchEconomyJson(`/admin/points/wallets/${encodeURIComponent(userId)}`);
    renderEconomyAccountLookup(json.wallet, json.ledger || []);
    economySetMsg("已更新指定帳戶積分");
  } catch (err) {
    economySetMsg(err.message || "帳戶積分查詢失敗", false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "查詢";
    }
  }
}

async function sanctionEconomyWallet() {
  if (currentUser !== "root") return;
  const select = $("economy-query-user-id");
  const userId = Number(select?.value || 0);
  if (!Number.isFinite(userId) || userId <= 0) {
    economySetMsg("請先選擇要處分的會員", false);
    return;
  }
  const reason = $("economy-wallet-sanction-reason")?.value?.trim() || "";
  if (!reason) {
    economySetMsg("請輸入錢包處分原因", false);
    return;
  }
  const btn = $("economy-wallet-sanction-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "處理中...";
    }
    await fetchEconomyJson(`/root/points/wallets/${encodeURIComponent(userId)}/sanction`, {
      method: "POST",
      body: JSON.stringify({
        wallet_status: $("economy-wallet-sanction-status")?.value || "active",
        risk_level: $("economy-wallet-sanction-risk")?.value || "normal",
        freeze_amount: Number($("economy-wallet-freeze-amount")?.value || 0),
        unfreeze_amount: Number($("economy-wallet-unfreeze-amount")?.value || 0),
        reason,
      }),
    });
    const refreshed = await fetchEconomyJson(`/admin/points/wallets/${encodeURIComponent(userId)}`);
    renderEconomyAccountLookup(refreshed.wallet, refreshed.ledger || []);
    if ($("economy-wallet-freeze-amount")) $("economy-wallet-freeze-amount").value = "0";
    if ($("economy-wallet-unfreeze-amount")) $("economy-wallet-unfreeze-amount").value = "0";
    economySetMsg("已套用錢包處分");
    await loadEconomyRootReport();
  } catch (err) {
    economySetMsg(err.message || "錢包處分失敗", false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "套用處分";
    }
  }
}

async function spendEconomyItem(itemKey) {
  if (!itemKey) return;
  try {
    const json = await fetchEconomyJson("/points/spend", {
      method: "POST",
      body: JSON.stringify({ item_key: itemKey, quantity: 1, reference_type: "manual_ui_test", reference_id: String(Date.now()) }),
    });
    renderEconomyWallet(json.wallet);
    await loadEconomyDashboard();
    economySetMsg("已依 catalog 扣點");
  } catch (err) {
    economySetMsg(err.message || "扣點失敗", false);
  }
}

async function submitEconomyAdjustment() {
  const btn = $("economy-adjust-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (currentUser !== "root") {
      economySetMsg("只有 root 可以手動調整積分", false);
      return;
    }
    const userId = Number($("economy-adjust-user-id")?.value || 0);
    if (!Number.isFinite(userId) || userId <= 0) {
      economySetMsg("請先選擇要調整的會員", false);
      return;
    }
    economySetMsg("正在送出點數調整...");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "送出中...";
    }
    const payload = {
      user_id: userId,
      direction: $("economy-adjust-direction")?.value || "credit",
      amount: Number($("economy-adjust-amount")?.value || 0),
      reason: $("economy-adjust-reason")?.value || "",
      idempotency_key: economyRequestId("admin-adjust"),
    };
    const json = await fetchEconomyJson("/admin/points/adjust", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    economySetMsg(`已寫入 ledger：${json.ledger?.ledger_uuid || ""}`);
    await loadEconomyDashboard();
    if (currentUser === "root") await loadEconomyRootReport();
    if (currentUser === "root" && String($("economy-query-user-id")?.value || "") === String(userId)) {
      await loadEconomyAccountLookup();
    }
  } catch (err) {
    const message = err.message || "調整失敗";
    economySetMsg(message, false);
    alert(message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "送出調整";
    }
  }
}

async function reviewEconomyPendingReward(id, decision) {
  try {
    await fetchEconomyJson(`/admin/points/pending-rewards/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, review_note: decision === "approve" ? "approved in economy center" : "rejected in economy center" }),
    });
    economySetMsg("待審核獎勵已處理");
    await loadEconomyAdmin();
  } catch (err) {
    economySetMsg(err.message || "審核失敗", false);
  }
}

async function sealPointsChainBlock() {
  try {
    const json = await fetchEconomyJson("/root/points/chain/seal", {
      method: "POST",
      body: JSON.stringify({ limit: 100 }),
    });
    const block = json.block || {};
    setEconomyChainStatus(json.sealed
      ? `已封存區塊 #${Number(block.block_number || 0)}，包含 ${Number(block.ledger_count || 0)} 筆 ledger`
      : (json.msg || "目前沒有未封 ledger 可封存"));
    await loadEconomyDashboard();
  } catch (err) {
    economySetMsg(err.message || "封塊失敗", false);
    setEconomyChainStatus(err.message || "封塊失敗", false);
  }
}

async function verifyPointsChain() {
  try {
    const json = await fetchEconomyJson("/root/points/chain/verify");
    setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || json), (json.verification || json).ok !== false);
    if (currentUser === "root") await loadEconomyRootReport();
  } catch (err) {
    economySetMsg(err.message || "驗證失敗", false);
    setEconomyChainStatus(err.message || "驗證失敗", false);
  }
}

async function createPointsChainBackup() {
  if (currentUser !== "root") return;
  try {
    const json = await fetchEconomyJson("/root/points/chain/backups", {
      method: "POST",
      body: JSON.stringify({}),
    });
    economySetMsg(json.ok ? `已建立 ledger backup：${json.backup_id || ""}` : "建立備份失敗", !!json.ok);
    await loadEconomyRootReport();
  } catch (err) {
    economySetMsg(err.message || "建立備份失敗", false);
  }
}

async function approvePointsChainRecovery() {
  if (currentUser !== "root") return;
  const backupId = $("economy-recovery-backup-id")?.value || "";
  const confirmText = $("economy-recovery-confirm")?.value || "";
  if (!backupId || confirmText !== "RESTORE POINTSCHAIN") {
    economySetMsg("請選擇備份，並輸入確認字串 RESTORE POINTSCHAIN", false);
    return;
  }
  if (!confirm("確認要用選定 ledger backup 恢復 PointsChain？wallet 會由 ledger 重建。")) return;
  try {
    const json = await fetchEconomyJson("/root/points/chain/recovery/approve", {
      method: "POST",
      body: JSON.stringify({ backup_id: backupId, confirm: confirmText }),
    });
    const resultMessage = formatEconomyRecoveryResult(json);
    if ($("economy-recovery-confirm")) $("economy-recovery-confirm").value = "";
    await loadEconomyDashboard();
    economySetMsg(resultMessage, !!json.ok);
    setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || {}), (json.verification || {}).ok !== false);
  } catch (err) {
    economySetMsg(err.message || "恢復失敗", false);
  }
}

async function autoHandlePointsChainRecovery() {
  if (currentUser !== "root") return;
  if (!confirm("一鍵處理會先驗證 PointsChain；若已進入 safe mode 且有建議健康備份，會自動套用該備份並由 ledger 重建 wallet。是否繼續？")) return;
  const btn = $("economy-recovery-auto-handle-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "處理中...";
    }
    economySetMsg("正在驗證 PointsChain 並準備處理異常...");
    economyRecoveryActionMsg("正在處理 PointsChain 異常...");
    const json = await fetchEconomyJson("/root/points/chain/recovery/auto-handle", {
      method: "POST",
      body: JSON.stringify({ confirm: "AUTO HANDLE POINTSCHAIN" }),
    });
    await loadEconomyDashboard();
    if (json.action === "verified_clean") {
      economySetMsg(json.msg || "PointsChain 驗證正常");
      economyRecoveryActionMsg(json.msg || "PointsChain 驗證正常");
      setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || {}), true);
      if (typeof loadAudit === "function") await loadAudit(auditPage || 0);
      return;
    }
    const resultMessage = formatEconomyRecoveryResult(json);
    economySetMsg(json.msg || resultMessage || "異常鏈處理完成", !!json.ok);
    economyRecoveryActionMsg(json.msg || resultMessage || "異常鏈處理完成", !!json.ok);
    setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || json.initial_verification || {}), !!json.ok);
    if (typeof loadAudit === "function") await loadAudit(auditPage || 0);
  } catch (err) {
    economySetMsg(err.message || "一鍵處理異常鏈失敗", false);
    economyRecoveryActionMsg(err.message || "一鍵處理異常鏈失敗", false);
    setEconomyChainStatus(err.message || "一鍵處理異常鏈失敗", false);
    await loadEconomyRootReport();
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "一鍵處理異常鏈";
    }
  }
}

async function rollbackEconomyLedger() {
  if (currentUser !== "root") return;
  const ledgerUuid = $("economy-rollback-ledger-uuid")?.value?.trim() || "";
  const reason = $("economy-rollback-reason")?.value?.trim() || "";
  if (!ledgerUuid || !reason) {
    economySetMsg("ledger UUID 與 rollback 原因都必填", false);
    return;
  }
  try {
    const json = await fetchEconomyJson(`/root/points/ledger/${encodeURIComponent(ledgerUuid)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    if ($("economy-rollback-ledger-uuid")) $("economy-rollback-ledger-uuid").value = "";
    if ($("economy-rollback-reason")) $("economy-rollback-reason").value = "";
    economySetMsg(`已建立 rollback ledger：${json.rollback_ledger?.ledger_uuid || ""}`);
    await loadEconomyRootReport();
    await loadEconomyAdmin();
  } catch (err) {
    economySetMsg(err.message || "Rollback 失敗", false);
  }
}

function bindEconomyInlineEvents() {
  if (economyInlineEventsBound) return;
  economyInlineEventsBound = true;
  const bindings = [
    ["economy-refresh-btn", loadEconomyDashboard],
    ["economy-wallet-onboarding-refresh-btn", loadEconomyDashboard],
    ["economy-wallet-download-btn", downloadEconomyWalletCsv],
    ["economy-wallet-official-hot-btn", useOfficialHotWallet],
    ["economy-wallet-create-cold-btn", createColdWalletDraft],
    ["economy-wallet-import-cold-btn", importColdWalletFromText],
    ["economy-wallet-confirm-cold-btn", confirmColdWalletBinding],
    ["economy-wallet-create-multisig-btn", createMultisigWallet],
    ["economy-trading-export-btn", downloadEconomyTradingCsv],
    ["economy-ledger-export-btn", exportEconomyLedgerCsv],
    ["economy-admin-refresh-btn", loadEconomyAdmin],
    ["economy-adjust-btn", submitEconomyAdjustment],
    ["economy-account-query-btn", loadEconomyAccountLookup],
    ["economy-wallet-sanction-btn", sanctionEconomyWallet],
    ["economy-root-balance-refresh-btn", loadEconomyRootReport],
    ["economy-root-funding-refresh-btn", loadEconomyRootTradingReadOnly],
    ["economy-root-positions-refresh-btn", loadEconomyRootTradingReadOnly],
    ["economy-root-report-btn", loadEconomyRootReport],
    ["economy-backup-btn", createPointsChainBackup],
    ["economy-recovery-auto-handle-btn", autoHandlePointsChainRecovery],
    ["economy-recovery-approve-btn", approvePointsChainRecovery],
    ["economy-rollback-btn", rollbackEconomyLedger],
    ["economy-seal-btn", sealPointsChainBlock],
    ["economy-verify-btn", verifyPointsChain],
  ];
  bindings.forEach(([id, handler]) => {
    const el = $(id);
    if (!el || el.dataset.economyInlineBound === "1") return;
    el.dataset.economyInlineBound = "1";
    el.addEventListener("click", handler);
  });
  document.querySelectorAll("[data-economy-page]").forEach((tab) => {
    if (tab.dataset.economyPageBound === "1") return;
    tab.dataset.economyPageBound = "1";
    tab.addEventListener("click", () => setEconomyActivePage(tab.dataset.economyPage || "balance"));
  });
  document.addEventListener("hackme:account-context-changed", () => {
    economyActivePage = readEconomyActivePage();
    syncEconomySubpages(currentUser === "root");
  });
  syncEconomySubpages(currentUser === "root");
  document.addEventListener("hackme:module-changed", syncEconomyAutoRefreshLifecycle);
  document.addEventListener("visibilitychange", syncEconomyAutoRefreshLifecycle);
  syncEconomyAutoRefreshLifecycle();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindEconomyInlineEvents);
} else {
  bindEconomyInlineEvents();
}

async function loadEconomyProof(ledgerUuid) {
  if (!ledgerUuid) return;
  try {
    const json = await fetchEconomyJson(`/points/ledger/${encodeURIComponent(ledgerUuid)}/proof`);
    const proof = json.proof || {};
    const text = proof.sealed
      ? `Proof 已封塊：ledger ${sanitize(ledgerUuid)} 位於區塊 #${Number(proof.block_number || 0)}，Merkle path ${Array.isArray(proof.merkle_path) ? proof.merkle_path.length : 0} 層`
      : `Proof 尚未封塊：ledger ${sanitize(ledgerUuid)} 仍在未封 ledger 中`;
    setEconomyChainStatus(text);
  } catch (err) {
    economySetMsg(err.message || "Proof 讀取失敗", false);
    setEconomyChainStatus(err.message || "Proof 讀取失敗", false);
  }
}
