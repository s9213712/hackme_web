let economyLedgerOffset = 0;
let economyLedgerCache = [];
let economyBlockCountdownTimer = null;
let economyBlockSchedule = null;
let economyInlineEventsBound = false;
let economyDocumentEventsBound = false;
let economyAutoRefreshTimer = null;
let economyAutoRefreshBusy = false;
let economyColdWalletDraft = null;
let economyColdWalletBindCandidate = null;
let economyWalletOnboardingState = {};
let economyCurrentChainBranch = "main";
let economyCatalogCache = [];
let economyExplorerLastQuery = "";
let economyExplorerCountdownTimer = null;
let economyFundAddressCache = {};
let economyGovernanceProposalCache = new Map();
let economyTreasurySignerCenterCache = null;
let economyGovernanceCategory = "all";
let economyGovernanceStatusFilter = "review";
let economySelectedDisputeUuid = "";
let economySelectedDisputeProposalUuids = new Set();
let economyTransactionDisputeCache = [];
let economyExpandedGovernanceProposalUuids = new Set();
let economyOfficialHotWalletLabels = {};
const ECONOMY_PAGE_STORAGE_KEY = "hackme_web:economy:active_page";
const ECONOMY_SPEND_WALLET_STORAGE_KEY = "hackme_web:economy:default_spend_wallet";
const ECONOMY_COLD_BACKUP_PREFIX = "pcw1.p256";
const ECONOMY_GOV_RATE_UNIT_SUFFIX = "b" + "ps";
const ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS = 12;

function economyPageStorageKey() {
  return typeof accountScopedStorageKey === "function" ? accountScopedStorageKey(ECONOMY_PAGE_STORAGE_KEY) : ECONOMY_PAGE_STORAGE_KEY;
}

function economySpendWalletStorageKey() {
  return typeof accountScopedStorageKey === "function" ? accountScopedStorageKey(ECONOMY_SPEND_WALLET_STORAGE_KEY) : ECONOMY_SPEND_WALLET_STORAGE_KEY;
}

function readEconomyActivePage() {
  try {
    return localStorage.getItem(economyPageStorageKey()) || "balance";
  } catch (_) {
    return "balance";
  }
}

function readEconomySpendWalletAddress() {
  try {
    return localStorage.getItem(economySpendWalletStorageKey()) || "";
  } catch (_) {
    return "";
  }
}

function readEconomyDefaultSpendWalletAddress() {
  return readEconomySpendWalletAddress();
}

function writeEconomySpendWalletAddress(address) {
  try {
    const key = economySpendWalletStorageKey();
    const normalized = String(address || "").trim().toLowerCase();
    const previous = localStorage.getItem(key) || "";
    localStorage.setItem(key, normalized);
    if (previous !== normalized && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("economy:default-spend-wallet-changed", {
        detail: { address: normalized },
      }));
    }
  } catch (_) {}
}

function writeEconomyDefaultSpendWalletAddress(address) {
  writeEconomySpendWalletAddress(address);
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

function economyInlineMsg(targetId, text, ok = true, fallbackLabel = "PointsChain") {
  const el = $(targetId);
  if (!el) {
    const message = String(text || "").trim();
    if (message && typeof showAppToast === "function") {
      showAppToast(`${fallbackLabel}：${message}`, ok, { duration: ok ? 3600 : 6200 });
    }
    if (message && window.console) {
      const logger = ok ? console.info : console.error;
      logger.call(console, `[economy] missing message target #${targetId}: ${message}`);
    }
    return;
  }
  el.textContent = text || "";
  el.classList.toggle("show", Boolean(text));
  el.classList.toggle("ok", Boolean(text) && Boolean(ok));
  el.classList.toggle("err", Boolean(text) && !ok);
  el.classList.remove("info");
  el.setAttribute("role", ok ? "status" : "alert");
  el.setAttribute("aria-live", ok ? "polite" : "assertive");
  el.setAttribute("aria-atomic", "true");
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
  scheduleInlineMessageClear(el, text, ok);
}

function economySetMsg(text, ok = true) {
  economyInlineMsg("economy-msg", text, ok, "PointsChain");
}

function auditChainActionMsg(text, ok = true) {
  economyInlineMsg("audit-chain-action-status", text, ok, "審計鏈");
}

function economyRecoveryActionMsg(text, ok = true) {
  economyInlineMsg("economy-recovery-action-status", text, ok, "PointsChain 恢復");
}

function economyRequestId(prefix = "economy") {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `${prefix}:${window.crypto.randomUUID()}`;
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function economyWalletMsg(text, ok = true) {
  economyInlineMsg("economy-wallet-onboarding-msg", text, ok, "錢包管理");
}

function economyExplorerMsg(text, ok = true) {
  economyInlineMsg("economy-explorer-msg", text, ok, "鏈上瀏覽器");
}

function economyGovernanceMsg(text, ok = true) {
  economyInlineMsg("economy-governance-msg", text, ok, "PointsChain 治理");
}

function economyTransactionMsg(text, ok = true) {
  economyInlineMsg("economy-transactions-msg", text, ok, "交易管理");
}

function economyTransferMsg(text, ok = true) {
  economyInlineMsg("economy-transfer-msg", text, ok, "鏈上送單");
}

function economyFailureMessage(err, fallback) {
  const message = String(err?.message || "").trim();
  if (message) return message;
  return fallback || "操作失敗";
}

function economyNotifyFailure(err, { msgFn = economySetMsg, label = "PointsChain", fallback = "操作失敗" } = {}) {
  const message = economyFailureMessage(err, fallback);
  if (typeof msgFn === "function") msgFn(message, false);
  if (msgFn !== economySetMsg) economySetMsg(message, false);
  if (message && typeof showAppToast === "function") {
    showAppToast(`${label}：${message}`, false, { duration: 8200 });
  }
  return message;
}

function economyNotifySuccess(text, { msgFn = economySetMsg, label = "PointsChain", toast = true } = {}) {
  const message = String(text || "").trim();
  if (!message) return "";
  if (typeof msgFn === "function") msgFn(message, true);
  if (msgFn !== economySetMsg) economySetMsg(message, true);
  if (toast && typeof showAppToast === "function") {
    showAppToast(`${label}：${message}`, true, { duration: 4200 });
  }
  return message;
}

function economyAddressDisputeStatementLength(text) {
  return Array.from(String(text || "").trim()).length;
}

function economyPromptAddressDisputeStatement({ promptText, cancelText, shortText, msgFn }) {
  while (true) {
    const statement = prompt(promptText, "");
    if (statement === null) {
      msgFn(cancelText, false);
      return null;
    }
    const normalized = String(statement || "").trim();
    const length = economyAddressDisputeStatementLength(normalized);
    if (length >= ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS) return normalized;
    msgFn(`${shortText}（目前 ${length}/${ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS} 字），請補充原因與佐證後再送出。`, false);
  }
}

function economyWarningSuffix(json) {
  const warnings = Array.isArray(json?.warnings) ? json.warnings.filter(Boolean) : [];
  if (!warnings.length) return "";
  if (warnings.includes("notification_delivery_failed")) return "；部分通知送出失敗，請到交易管理確認交易狀態。";
  return `；警告：${warnings.map((item) => String(item)).join("、")}`;
}

function destroyEconomyColdWalletSecrets({ hideGenerated = true } = {}) {
  economyColdWalletDraft = null;
  economyColdWalletBindCandidate = null;
  ["economy-wallet-generated-address", "economy-wallet-generated-private-key", "economy-wallet-private-key"].forEach((id) => {
    const el = $(id);
    if (el && "value" in el) el.value = "";
  });
  const confirmed = $("economy-wallet-private-key-confirmed");
  if (confirmed) confirmed.checked = false;
  const selectionStatus = $("economy-wallet-generated-selection-status");
  if (selectionStatus) selectionStatus.textContent = "尚未選用";
  const useBtn = $("economy-wallet-use-generated-cold-btn");
  if (useBtn) {
    useBtn.disabled = false;
    useBtn.textContent = "選用此冷錢包";
  }
  const panel = $("economy-wallet-generated-panel");
  if (panel && hideGenerated) panel.style.display = "none";
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

function economyCompactColdWalletBackup(privateJwk) {
  const jwk = privateJwk || {};
  const x = String(jwk.x || "").trim();
  const y = String(jwk.y || "").trim();
  const d = String(jwk.d || "").trim();
  if (!x || !y || !d) throw new Error("冷錢包備份碼格式不完整");
  return `${ECONOMY_COLD_BACKUP_PREFIX}.${x}.${y}.${d}`;
}

function economyParseColdWalletBackup(raw) {
  const text = String(raw || "").trim();
  if (!text) throw new Error("請貼上冷錢包備份碼");
  if (text.startsWith(`${ECONOMY_COLD_BACKUP_PREFIX}.`)) {
    const parts = text.split(".");
    if (parts.length !== 5 || parts[0] !== "pcw1" || parts[1] !== "p256" || !parts[2] || !parts[3] || !parts[4]) {
      throw new Error("冷錢包備份碼格式不正確");
    }
    return {
      kty: "EC",
      crv: "P-256",
      x: parts[2],
      y: parts[3],
      d: parts[4],
      ext: true,
      key_ops: ["sign"],
    };
  }
  let jwk = null;
  try {
    jwk = JSON.parse(text);
  } catch (_) {
    throw new Error("請貼上 pcw1 私鑰備份碼或舊版 JWK JSON");
  }
  if (!jwk?.d || !jwk?.x || !jwk?.y) throw new Error("請貼上含 x、y、d 欄位的冷錢包備份資料");
  return {
    ...jwk,
    kty: jwk.kty || "EC",
    crv: jwk.crv || "P-256",
    ext: jwk.ext !== false,
    key_ops: Array.isArray(jwk.key_ops) && jwk.key_ops.length ? jwk.key_ops : ["sign"],
  };
}

async function economyLoadColdWalletBackup(raw, { imported = true } = {}) {
  const privateJwk = economyParseColdWalletBackup(raw);
  const publicJwk = economyCanonicalPublicJwk(privateJwk);
  const { address } = await economyWalletAddressFromPublicJwk(publicJwk);
  const privateKey = await crypto.subtle.importKey(
    "jwk",
    privateJwk,
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign"]
  );
  privateJwk.d = "";
  return {
    address,
    privateKey,
    publicJwk,
    imported,
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

function economyWalletSignerKeyId(address) {
  const wallet = economyWalletByAddress(address);
  return String(wallet?.public_key_hash || "").trim();
}

function economyWalletTransferPayload({ source, destination, amount, fee, memo, requestUuid, chainBranch = "", actionType = "points_wallet_transfer", proposalId = "", payloadHash = "", signerKeyId = "" }) {
  return JSON.stringify({
    action: String(actionType || "points_wallet_transfer").trim() || "points_wallet_transfer",
    amount_points: Number(amount),
    chain_branch: String(chainBranch || economyCurrentChainBranch || "main").trim() || "main",
    destination_wallet_address: String(destination || "").trim().toLowerCase(),
    fee_points: Number(fee),
    memo: String(memo || "").slice(0, 240),
    payload_hash: String(payloadHash || "").trim(),
    proposal_id: String(proposalId || "").slice(0, 120),
    request_uuid: String(requestUuid || "").slice(0, 120),
    signer_key_id: String(signerKeyId || economyWalletSignerKeyId(source) || "").slice(0, 120),
    source_wallet_address: String(source || "").trim().toLowerCase(),
    user_id: Number(currentUserId || 0),
  });
}

function economyWalletServiceFeePayload({ source, itemKey, quantity, amount, requestUuid, referenceType, referenceId, chainBranch = "", actionType = "points_service_fee_reserve", proposalId = "", payloadHash = "", signerKeyId = "" }) {
  return JSON.stringify({
    action: String(actionType || "points_service_fee_reserve").trim() || "points_service_fee_reserve",
    amount_points: Number(amount),
    chain_branch: String(chainBranch || economyCurrentChainBranch || "main").trim() || "main",
    item_key: String(itemKey || "").trim(),
    payload_hash: String(payloadHash || "").trim(),
    proposal_id: String(proposalId || "").slice(0, 120),
    quantity: Number(quantity || 1),
    reference_id: String(referenceId || "").slice(0, 240),
    reference_type: String(referenceType || "").slice(0, 120),
    request_uuid: String(requestUuid || "").slice(0, 120),
    signer_key_id: String(signerKeyId || economyWalletSignerKeyId(source) || "").slice(0, 120),
    source_wallet_address: String(source || "").trim().toLowerCase(),
    user_id: Number(currentUserId || 0),
  });
}

function economyAddressDisputeRuntimeMode() {
  return String(siteConfig?.server_mode || "unknown").trim() || "unknown";
}

function economyAddressDisputePayload({ purpose, txHash, from, to, amount, statementHash, evidenceHash, nonce, chainBranch, runtimeMode }) {
  return JSON.stringify({
    amount: Number(amount || 0),
    amount_points: Number(amount || 0),
    chain_branch: String(chainBranch || economyCurrentChainBranch || "main").trim() || "main",
    evidence_hash: String(evidenceHash || "").trim(),
    from: String(from || "").trim().toLowerCase(),
    from_wallet_address: String(from || "").trim().toLowerCase(),
    nonce: String(nonce || "").trim(),
    purpose: String(purpose || "").trim(),
    runtime_mode: String(runtimeMode || economyAddressDisputeRuntimeMode()).trim() || "unknown",
    statement_hash: String(statementHash || "").trim(),
    to: String(to || "").trim().toLowerCase(),
    to_wallet_address: String(to || "").trim().toLowerCase(),
    tx_hash: String(txHash || "").trim(),
  });
}

function economyNormalizeEvidenceInput(raw) {
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 20).map((item) => item.slice(0, 240));
  }
  return String(raw || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 20)
    .map((item) => item.slice(0, 240));
}

async function economyBuildAddressDisputeProof({ purpose, signerAddress, txHash, from, to, amount, statement, evidence, chainBranch, runtimeMode }) {
  if (!window.crypto?.subtle) throw new Error("此瀏覽器不支援 WebCrypto，無法本機簽署地址證明");
  const raw = window.prompt("請貼上目標地址的冷錢包備份碼在本機簽署地址證明；私鑰不會送到伺服器。", "");
  if (raw === null) {
    const err = new Error("已取消地址證明簽署，疑義案件未送出");
    err.cancelled = true;
    throw err;
  }
  let loaded = null;
  try {
    loaded = await economyLoadColdWalletBackup(raw, { imported: true });
    if (String(loaded.address || "").trim().toLowerCase() !== String(signerAddress || "").trim().toLowerCase()) {
      throw new Error("備份碼地址與本次需證明的地址不一致");
    }
    const statementHash = await economySha256Hex(String(statement || ""));
    const evidenceHash = await economySha256Hex(JSON.stringify(economyNormalizeEvidenceInput(evidence)));
    const nonce = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    const signatureRuntimeMode = String(runtimeMode || economyAddressDisputeRuntimeMode()).trim() || "unknown";
    const payload = economyAddressDisputePayload({
      purpose,
      txHash,
      from,
      to,
      amount,
      statementHash,
      evidenceHash,
      nonce,
      chainBranch,
      runtimeMode: signatureRuntimeMode,
    });
    return {
      public_key_jwk: economyCanonicalPublicJwk(loaded.publicJwk),
      signature: await economySignWalletBinding(loaded.privateKey, payload),
      signature_nonce: nonce,
      signature_runtime_mode: signatureRuntimeMode,
      statement_hash: statementHash,
      evidence_hash: evidenceHash,
    };
  } finally {
    loaded = null;
  }
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

function economyWalletByAddress(address) {
  const needle = String(address || "").trim().toLowerCase();
  if (!needle) return null;
  return economyVisibleWallets(economyWalletOnboardingState).find((wallet) => String(wallet.address || "").trim().toLowerCase() === needle) || null;
}

function economyWalletRequiresSignature(wallet) {
  const type = String(wallet?.wallet_type || "");
  const mode = String(wallet?.custody_mode || "");
  return mode === "self_custody" || ["self_custody_cold", "imported_cold"].includes(type);
}

function economyWalletSupportsAccountBoundDisputeProof(wallet) {
  return String(wallet?.wallet_type || "") === "official_hot"
    && String(wallet?.custody_mode || "") === "server_hot";
}

async function economyBuildTransferSignature({ source, destination, amount, fee, memo, requestUuid }) {
  const wallet = economyWalletByAddress(source);
  if (!economyWalletRequiresSignature(wallet)) return "";
  if (!window.crypto?.subtle) throw new Error("此瀏覽器不支援 WebCrypto，無法簽署冷錢包交易");
  const raw = window.prompt("請貼上本次付款錢包私鑰備份碼以本機簽署交易；只在可信裝置使用，不會送到伺服器。", "");
  if (raw === null) {
    const err = new Error("已取消冷錢包簽署，交易未送出");
    err.cancelled = true;
    throw err;
  }
  let loaded = null;
  try {
    loaded = await economyLoadColdWalletBackup(raw, { imported: true });
    if (String(loaded.address || "").trim().toLowerCase() !== String(source || "").trim().toLowerCase()) {
      throw new Error("私鑰備份碼地址與付款錢包不一致，交易未送出");
    }
    const payload = economyWalletTransferPayload({ source, destination, amount, fee, memo, requestUuid });
    return economySignWalletBinding(loaded.privateKey, payload);
  } finally {
    loaded = null;
  }
}

async function economyBuildGovernanceMultisigSignature({ signer, destination, amount, payloadHash, requestUuid, custodyMode = "", walletType = "" }) {
  const wallet = economyWalletByAddress(signer);
  const needsSignature = economyWalletRequiresSignature(wallet)
    || String(custodyMode || "").trim() === "self_custody"
    || ["self_custody_cold", "imported_cold"].includes(String(walletType || "").trim());
  if (!needsSignature) return "";
  if (!window.crypto?.subtle) throw new Error("此瀏覽器不支援 WebCrypto，無法簽署官方多簽");
  const raw = window.prompt("請貼上本次官方多簽 signer 錢包私鑰備份碼以本機簽署；只在可信裝置使用，不會送到伺服器。", "");
  if (raw === null) {
    const err = new Error("已取消官方多簽簽署，提案尚未授權");
    err.cancelled = true;
    throw err;
  }
  let loaded = null;
  try {
    loaded = await economyLoadColdWalletBackup(raw, { imported: true });
    if (String(loaded.address || "").trim().toLowerCase() !== String(signer || "").trim().toLowerCase()) {
      throw new Error("私鑰備份碼地址與 signer 錢包不一致，多簽未送出");
    }
    const payload = economyWalletTransferPayload({
      source: signer,
      destination: destination || signer,
      amount: Math.max(1, Math.floor(Number(amount || 1))),
      fee: 0,
      memo: payloadHash,
      requestUuid,
      actionType: "points_governance_multisig_sign",
      proposalId: requestUuid,
      payloadHash,
      signerKeyId: economyWalletSignerKeyId(signer),
    });
    return economySignWalletBinding(loaded.privateKey, payload);
  } finally {
    loaded = null;
  }
}

async function economyBuildServiceFeeSignature({ source, itemKey, quantity, amount, requestUuid, referenceType, referenceId }) {
  const wallet = economyWalletByAddress(source);
  if (!economyWalletRequiresSignature(wallet)) return "";
  if (!window.crypto?.subtle) throw new Error("此瀏覽器不支援 WebCrypto，無法簽署冷錢包服務費");
  const raw = window.prompt("請貼上本次付款錢包私鑰備份碼以本機簽署服務費；只在可信裝置使用，不會送到伺服器。", "");
  if (raw === null) {
    const err = new Error("已取消冷錢包簽署，服務費未送出");
    err.cancelled = true;
    throw err;
  }
  let loaded = null;
  try {
    loaded = await economyLoadColdWalletBackup(raw, { imported: true });
    if (String(loaded.address || "").trim().toLowerCase() !== String(source || "").trim().toLowerCase()) {
      throw new Error("私鑰備份碼地址與付款錢包不一致，服務費未送出");
    }
    const payload = economyWalletServiceFeePayload({ source, itemKey, quantity, amount, requestUuid, referenceType, referenceId });
    return economySignWalletBinding(loaded.privateKey, payload);
  } finally {
    loaded = null;
  }
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
    official_wallet_grant: "官方 Treasury 撥款",
    user_initial_grant: "會員初始配點",
    chain_acceleration_fee: "鏈上加速費用",
    wallet_transfer: "鏈上轉帳",
    wallet_transfer_out: "鏈上轉帳",
    wallet_transfer_in: "鏈上轉帳入帳",
    wallet_transfer_fee: "鏈上手續費",
    service_fee_batch_unfreeze: "站內服務費批次解凍",
    service_fee_batch_debit: "站內服務費批次扣款",
  };
  if (labels[action]) return labels[action];
  if (action.startsWith("service_fee_reserve:")) return "站內服務費凍結";
  if (action.startsWith("compensation:")) return `補償交易：${formatEconomyLedgerAction(action.slice("compensation:".length))}`;
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

function economyCanSeeOfficialHotWalletLabels() {
  return currentUser === "root" || currentRole === "manager" || currentRole === "super_admin";
}

function updateEconomyOfficialHotWalletLabels(labels = {}) {
  if (!economyCanSeeOfficialHotWalletLabels()) {
    economyOfficialHotWalletLabels = {};
    return;
  }
  if (!labels || typeof labels !== "object") return;
  Object.entries(labels).forEach(([address, label]) => {
    const key = String(address || "").trim().toLowerCase();
    const value = String(label || "").trim();
    if (key && value) economyOfficialHotWalletLabels[key] = value;
  });
}

function formatEconomyWalletAddressWithManagerLabel(address, { short = true } = {}) {
  const raw = String(address || "").trim();
  if (!raw || raw === "-") return "-";
  const base = short ? shortEconomyWalletAddress(raw) : raw;
  if (!economyCanSeeOfficialHotWalletLabels()) return base;
  const label = economyOfficialHotWalletLabels[String(raw).trim().toLowerCase()] || "";
  return label ? `${base}（${label}）` : base;
}

function formatEconomyLedgerWalletFlow(row) {
  const flow = row?.wallet_flow && typeof row.wallet_flow === "object" ? row.wallet_flow : null;
  if (!flow?.source_wallet_address && !flow?.destination_wallet_address) return "";
  const sourceLabel = flow.source_label || "來源地址";
  const destLabel = flow.destination_label || "目的地址";
  const source = formatEconomyWalletAddressWithManagerLabel(flow.source_wallet_address);
  const dest = formatEconomyWalletAddressWithManagerLabel(flow.destination_wallet_address);
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

function economyChainEnabled() {
  return !siteConfig || siteConfig.feature_points_chain_enabled !== false;
}

function canManageEconomyPoints() {
  return currentUser === "root" && economyChainEnabled();
}

function economyPositionsAvailable() {
  return economyChainEnabled() && (!siteConfig || siteConfig.feature_trading_enabled !== false);
}

function setEconomyActivePage(page, options = {}) {
  const rootMode = currentUser === "root";
  const chainFeatureOn = economyChainEnabled();
  const chainAllowed = canManageEconomyPoints();
  const positionsAvailable = false;
  const rootTradingAllowed = false;
  const requestedPage = ["chain", "transactions", "explorer", "governance", "positions", "funding-pools", "all-positions"].includes(page) ? page : "balance";
  const nextPage =
    requestedPage === "chain" && chainAllowed
      ? "chain"
      : requestedPage === "transactions" && chainFeatureOn
        ? "transactions"
      : requestedPage === "explorer" && chainFeatureOn
        ? "explorer"
      : requestedPage === "governance" && chainFeatureOn
        ? "governance"
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
  const transactionsPage = $("economy-transactions-page");
  const positionsPage = $("economy-positions-page");
  const explorerPage = $("economy-explorer-page");
  const governancePage = $("economy-governance-page");
  const fundingPoolsPage = $("economy-funding-pools-page");
  const allPositionsPage = $("economy-all-positions-page");
  const chainPage = $("economy-chain-page");
  if (balancePage) balancePage.classList.toggle("active", nextPage === "balance");
  if (transactionsPage) transactionsPage.classList.toggle("active", nextPage === "transactions");
  if (explorerPage) explorerPage.classList.toggle("active", nextPage === "explorer");
  if (governancePage) governancePage.classList.toggle("active", nextPage === "governance");
  if (positionsPage) positionsPage.classList.toggle("active", positionsAvailable && nextPage === "positions");
  if (fundingPoolsPage) fundingPoolsPage.classList.toggle("active", rootTradingAllowed && nextPage === "funding-pools");
  if (allPositionsPage) allPositionsPage.classList.toggle("active", rootTradingAllowed && nextPage === "all-positions");
  if (chainPage) chainPage.classList.toggle("active", chainAllowed && nextPage === "chain");
  const balanceTab = $("tab-economy-balance");
  const transactionsTab = $("tab-economy-transactions");
  const explorerTab = $("tab-economy-explorer");
  const governanceTab = $("tab-economy-governance");
  const positionsTab = $("tab-economy-positions");
  const fundingPoolsTab = $("tab-economy-funding-pools");
  const allPositionsTab = $("tab-economy-all-positions");
  const chainTab = $("tab-economy-chain");
  if (balanceTab) {
    balanceTab.textContent = rootMode ? "錢包管理" : "積分餘額";
    balanceTab.classList.toggle("active", nextPage === "balance");
    balanceTab.setAttribute("aria-selected", nextPage === "balance" ? "true" : "false");
  }
  if (transactionsTab) {
    transactionsTab.style.display = chainFeatureOn ? "" : "none";
    transactionsTab.classList.toggle("active", nextPage === "transactions");
    transactionsTab.setAttribute("aria-selected", nextPage === "transactions" ? "true" : "false");
  }
  if (explorerTab) {
    explorerTab.style.display = chainFeatureOn ? "" : "none";
    explorerTab.classList.toggle("active", nextPage === "explorer");
    explorerTab.setAttribute("aria-selected", nextPage === "explorer" ? "true" : "false");
  }
  if (governanceTab) {
    governanceTab.style.display = chainFeatureOn ? "" : "none";
    governanceTab.classList.toggle("active", nextPage === "governance");
    governanceTab.setAttribute("aria-selected", nextPage === "governance" ? "true" : "false");
  }
  if (fundingPoolsTab) {
    fundingPoolsTab.style.display = "none";
    fundingPoolsTab.classList.toggle("active", rootTradingAllowed && nextPage === "funding-pools");
    fundingPoolsTab.setAttribute("aria-selected", rootTradingAllowed && nextPage === "funding-pools" ? "true" : "false");
  }
  if (allPositionsTab) {
    allPositionsTab.style.display = "none";
    allPositionsTab.classList.toggle("active", rootTradingAllowed && nextPage === "all-positions");
    allPositionsTab.setAttribute("aria-selected", rootTradingAllowed && nextPage === "all-positions" ? "true" : "false");
  }
  if (positionsTab) {
    positionsTab.style.display = "none";
    positionsTab.classList.toggle("active", positionsAvailable && nextPage === "positions");
    positionsTab.setAttribute("aria-selected", positionsAvailable && nextPage === "positions" ? "true" : "false");
  }
  if (chainTab) {
    chainTab.style.display = chainAllowed ? "" : "none";
    chainTab.textContent = rootMode ? "積分私有鏈" : "積分管理";
    chainTab.classList.toggle("active", chainAllowed && nextPage === "chain");
    chainTab.setAttribute("aria-selected", chainAllowed && nextPage === "chain" ? "true" : "false");
  }
  const title = $("economy-page-title");
  if (title) {
    if (nextPage === "positions") title.textContent = "倉位管理";
    else if (nextPage === "transactions") title.textContent = "交易管理";
    else if (nextPage === "explorer") title.textContent = "鏈上瀏覽器";
    else if (nextPage === "governance") title.textContent = "公共投票與疑義事件";
    else if (nextPage === "funding-pools") title.textContent = "資金池管理";
    else if (nextPage === "all-positions") title.textContent = "全用戶倉位管理";
    else if (!rootMode) title.textContent = nextPage === "chain" ? "積分管理" : "積分錢包";
    else title.textContent = nextPage === "chain" ? "積分私有鏈" : "錢包管理";
  }
  if (options.loadRootTrading !== false && rootTradingAllowed && ["funding-pools", "all-positions"].includes(nextPage)) {
    loadEconomyRootTradingReadOnly({ refreshSnapshot: true });
  }
  if (nextPage === "governance") {
    loadEconomyGovernance({ silent: true });
    loadEconomyTransactionDisputes({ silent: true });
  }
}

function syncEconomySubpages(rootMode) {
  if (!canManageEconomyPoints() && economyActivePage === "chain") economyActivePage = "balance";
  if (!economyChainEnabled() && ["transactions", "explorer", "governance", "chain"].includes(economyActivePage)) economyActivePage = "balance";
  if (!economyPositionsAvailable() && economyActivePage === "positions") economyActivePage = "balance";
  if ((!rootMode || !economyPositionsAvailable()) && ["funding-pools", "all-positions"].includes(economyActivePage)) economyActivePage = "balance";
  setEconomyActivePage(economyActivePage, { persist: false, loadRootTrading: false });
}

function setEconomyRootLayout(rootMode) {
  const chainFeatureOn = economyChainEnabled();
  const rootWalletManagementCard = $("economy-root-wallet-management-card");
  if (rootWalletManagementCard) rootWalletManagementCard.style.display = rootMode && chainFeatureOn ? "" : "none";
  const rootVirtualCard = $("economy-root-virtual-card");
  if (rootVirtualCard) rootVirtualCard.style.display = rootMode && economyPositionsAvailable() ? "" : "none";
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
  economyCurrentChainBranch = String(wallet.chain_branch || wallet.branch?.branch_uuid || economyCurrentChainBranch || "main").trim() || "main";
  const pointsBalance = wallet.account_points_balance !== undefined
    ? Number(wallet.account_points_balance || 0)
    : wallet.points_balance !== undefined
    ? Number(wallet.points_balance || 0)
    : Number(wallet.soft_balance || 0) + Number(wallet.hard_balance || 0);
  const pointsFrozen = wallet.account_points_frozen !== undefined
    ? Number(wallet.account_points_frozen || 0)
    : wallet.points_frozen !== undefined
    ? Number(wallet.points_frozen || 0)
    : Number(wallet.soft_frozen || 0) + Number(wallet.hard_frozen || 0);
  const pointsEarned = wallet.total_points_earned !== undefined
    ? Number(wallet.total_points_earned || 0)
    : Number(wallet.total_soft_earned || 0) + Number(wallet.total_hard_earned || 0);
  const pointsSpent = wallet.total_points_spent !== undefined
    ? Number(wallet.total_points_spent || 0)
    : Number(wallet.total_soft_spent || 0) + Number(wallet.total_hard_spent || 0);
  if ($("economy-points-balance")) $("economy-points-balance").textContent = String(pointsBalance);
  if ($("economy-points-frozen")) $("economy-points-frozen").textContent = `金額凍結 ${pointsFrozen}`;
  if ($("economy-points-earned")) $("economy-points-earned").textContent = `收入 ${pointsEarned}`;
  if ($("economy-points-spent")) $("economy-points-spent").textContent = `支出 ${pointsSpent}`;
  if ($("economy-soft-balance")) $("economy-soft-balance").textContent = String(pointsBalance);
  if ($("economy-hard-balance")) $("economy-hard-balance").textContent = "0";
  if ($("economy-soft-frozen")) $("economy-soft-frozen").textContent = `金額凍結 ${pointsFrozen}`;
  if ($("economy-hard-frozen")) $("economy-hard-frozen").textContent = "金額凍結 0";
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
    user_multisig_preview: "多簽錢包（觀察/收款）",
    official_treasury_multisig: "官方財庫多簽",
    mint: "Mint 錢包",
    burn: "Burn 錢包",
  };
  return labels[String(type || "")] || String(type || "-");
}

function renderEconomyWalletOnboarding(onboarding) {
  const card = $("economy-wallet-onboarding-card");
  if (!card) return;
  economyWalletOnboardingState = onboarding || {};
  const rootMode = currentUser === "root";
  const chainFeatureOn = economyChainEnabled();
  const createCard = $("economy-wallet-create-card");
  const transferCard = $("economy-wallet-transfer-card");
  if (!chainFeatureOn) {
    card.style.display = "none";
    if (createCard) createCard.style.display = "none";
    if (transferCard) transferCard.style.display = "none";
    return;
  }
  card.style.display = rootMode ? "none" : "";
  if (createCard) createCard.style.display = rootMode ? "none" : "";
  if (rootMode) {
    if (createCard) createCard.style.display = "none";
    if (transferCard) transferCard.style.display = "none";
    return;
  }
  const wallet = onboarding?.wallet || null;
  const initialGrant = onboarding?.initial_grant && typeof onboarding.initial_grant === "object" ? onboarding.initial_grant : {};
  const onboardingWarnings = Array.isArray(onboarding?.warnings) ? onboarding.warnings : [];
  renderEconomyTransferWalletOptions(onboarding);
  renderEconomyWalletCreationFeeOptions(onboarding);
  renderEconomyWalletIdentityList(onboarding);
  const actions = $("economy-wallet-onboarding-actions");
  const boundActions = $("economy-wallet-bound-actions");
  const visibleWallets = economyVisibleWallets(onboarding);
  if (actions) actions.style.display = "";
  if (boundActions) boundActions.style.display = "none";
  if ($("economy-wallet-onboarding-status")) {
    $("economy-wallet-onboarding-status").textContent = wallet
      ? "已綁定模擬鏈錢包；伺服器未保存用戶冷錢包備份碼。"
      : "尚未綁定模擬鏈錢包；完成後才發放註冊禮。";
  }
  if ($("economy-wallet-count")) $("economy-wallet-count").textContent = String(visibleWallets.length || 0);
  if ($("economy-wallet-primary-note")) {
    $("economy-wallet-primary-note").textContent = wallet
      ? `${formatEconomyWalletIdentityType(wallet.wallet_type)} · ${wallet.custody_mode || "-"}`
      : "尚未綁定";
  }
  if ($("economy-wallet-identity-address")) {
    $("economy-wallet-identity-address").textContent = wallet?.address || "-";
    $("economy-wallet-identity-address").title = wallet?.address || "";
  }
  if ($("economy-wallet-identity-status")) $("economy-wallet-identity-status").textContent = wallet?.status || "-";
  if ($("economy-wallet-initial-grant")) {
    const amount = Number(initialGrant.amount || 0);
    $("economy-wallet-initial-grant").textContent = !initialGrant.action_type
      ? "不適用"
      : initialGrant.granted
        ? "已入帳"
        : `${formatEconomyPointsValue(amount)} 點待匯入`;
  }
  if ($("economy-wallet-initial-grant-note")) {
    $("economy-wallet-initial-grant-note").textContent = !initialGrant.action_type
      ? "此帳號無初始配點"
      : initialGrant.granted
        ? `tx ${shortEconomyWalletAddress(initialGrant.ledger_hash || initialGrant.ledger_uuid || "")}`
        : initialGrant.deferred_until_wallet
          ? "綁定錢包後由官方基金匯入"
          : "等待鏈上入帳";
  }
  if ($("economy-wallet-signup-bonus")) {
    $("economy-wallet-signup-bonus").textContent = onboarding?.signup_bonus_granted ? "已領取" : "待領取";
  }
  if (onboardingWarnings.length) {
    const labels = onboardingWarnings.map((item) => item?.code || item?.message || String(item)).filter(Boolean);
    economyWalletMsg(`錢包資料部分讀取失敗：${labels.join("、")}`, false);
  }
}

function economyWalletOptionLabel(wallet) {
  const primary = wallet.is_primary ? " · primary" : "";
  const balance = wallet.points_balance !== undefined ? ` · ${formatEconomyPointsValue(wallet.points_balance)} 點` : "";
  return `${formatEconomyWalletIdentityType(wallet.wallet_type)}${primary} · ${shortEconomyWalletAddress(wallet.address)}${balance}`;
}

function economyVisibleWallets(onboarding = {}) {
  const walletMap = new Map();
  const addWallet = (wallet) => {
    if (!wallet || typeof wallet !== "object" || !wallet.address) return;
    if (!walletMap.has(wallet.address)) walletMap.set(wallet.address, wallet);
  };
  if (Array.isArray(onboarding.wallets)) onboarding.wallets.forEach(addWallet);
  addWallet(onboarding.wallet);
  return Array.from(walletMap.values())
    .filter((wallet) => {
      const status = String(wallet.status || "");
      return ["pending_backup", "active"].includes(status) && wallet.address;
    });
}

function economyColdWallets(onboarding = {}) {
  return economyVisibleWallets(onboarding).filter((wallet) => {
    const type = String(wallet.wallet_type || "");
    const mode = String(wallet.custody_mode || "");
    return ["self_custody_cold", "imported_cold"].includes(type) && mode !== "system";
  });
}

function economySpendableWallets(onboarding = {}) {
  return economyVisibleWallets(onboarding)
    .filter((wallet) => {
      const status = String(wallet.status || "");
      const mode = String(wallet.custody_mode || "");
      const type = String(wallet.wallet_type || "");
      const spend = String(wallet.spend_capability || "enabled");
      return status === "active" && spend === "enabled" && mode !== "system" && mode !== "multisig" && !["mint", "burn", "user_multisig_preview"].includes(type) && wallet.address;
    });
}

function economyWalletCreationFeeQuote(onboarding = economyWalletOnboardingState) {
  const quote = onboarding?.wallet_creation_fee;
  return quote && typeof quote === "object" ? quote : {};
}

function renderEconomyWalletCreationFeeOptions(onboarding = {}) {
  const panel = $("economy-wallet-creation-fee-panel");
  const select = $("economy-wallet-creation-fee-source");
  const note = $("economy-wallet-creation-fee-note");
  if (!panel || !select) return;
  const quote = economyWalletCreationFeeQuote(onboarding);
  const amount = Number(quote.amount_points || quote.amount || 0);
  const wallets = economySpendableWallets(onboarding);
  if (amount <= 0) {
    panel.style.display = "none";
    select.innerHTML = `<option value="">第一個錢包免費</option>`;
    select.disabled = true;
    if (note) note.textContent = "第一個錢包免費；第二個以上依數量指數加價，收入進官方 Treasury。";
    return;
  }
  panel.style.display = "";
  select.disabled = !wallets.length;
  const previous = select.value;
  select.innerHTML = wallets.length
    ? wallets.map((wallet) => `<option value="${sanitize(wallet.address)}">${sanitize(economyWalletOptionLabel(wallet))}</option>`).join("")
    : `<option value="">沒有可支付建立費的錢包</option>`;
  if (previous && wallets.some((wallet) => wallet.address === previous)) select.value = previous;
  else if (wallets.some((wallet) => wallet.is_primary)) select.value = wallets.find((wallet) => wallet.is_primary).address;
  if (note) {
    const next = Number(quote.next_wallet_number || 0);
    note.textContent = `第 ${next || wallets.length + 1} 個錢包建立費 ${formatEconomyPointsValue(amount)} 點，收入進官方 Treasury；冷錢包付款會要求本機簽署。`;
  }
}

async function economyWalletCreationFeePayload(mode) {
  const quote = economyWalletCreationFeeQuote();
  const amount = Math.floor(Number(quote.amount_points || quote.amount || 0));
  if (!Number.isFinite(amount) || amount <= 0) return {};
  const source = String($("economy-wallet-creation-fee-source")?.value || "").trim().toLowerCase();
  if (!source) throw new Error("建立第二個以上錢包需選擇既有錢包支付建立費");
  const requestUuid = economyRequestId("wallet_creation_fee");
  const itemKey = String(quote.item_key || "wallet_creation_fee");
  const referenceType = String(quote.reference_type || "wallet_identity");
  const referenceId = String(quote.reference_id || `wallet_identity:create:${String(mode || "wallet")}:${quote.next_wallet_number || ""}`);
  economyWalletMsg("等待付款錢包本機簽署建立費；私鑰備份碼不會送到伺服器。");
  const signature = await economyBuildServiceFeeSignature({
    source,
    itemKey,
    quantity: 1,
    amount,
    requestUuid,
    referenceType,
    referenceId,
  });
  return {
    fee_source_wallet_address: source,
    fee_request_uuid: requestUuid,
    fee_signature: signature,
    fee_quote_amount: amount,
  };
}

function renderEconomyTransferWalletOptions(onboarding = {}) {
  const card = $("economy-wallet-transfer-card");
  const select = $("economy-transfer-source-wallet");
  if (!card || !select) return;
  const wallets = economySpendableWallets(onboarding);
  card.style.display = wallets.length ? "" : "none";
  if (!wallets.length) {
    select.innerHTML = `<option value="">尚無可用錢包</option>`;
    return;
  }
  const previous = select.value;
  select.innerHTML = wallets.map((wallet) => {
    return `<option value="${sanitize(wallet.address)}">${sanitize(economyWalletOptionLabel(wallet))}</option>`;
  }).join("");
  if (previous && wallets.some((wallet) => wallet.address === previous)) select.value = previous;
}

function renderEconomyWalletIdentityList(onboarding = {}) {
  const list = $("economy-wallet-identity-list");
  if (!list) return;
  const wallets = economyVisibleWallets(onboarding);
  if (!wallets.length) {
    list.innerHTML = `<div class="drive-empty">尚無錢包</div>`;
    return;
  }
  list.innerHTML = wallets.map((wallet) => {
    const address = String(wallet.address || "").trim().toLowerCase();
    const risk = wallet.risk_label && typeof wallet.risk_label === "object" ? wallet.risk_label : null;
    const freeze = wallet.governance_freeze && typeof wallet.governance_freeze === "object" ? wallet.governance_freeze : null;
    const walletType = String(wallet.wallet_type || "");
    const coldWallet = ["self_custody_cold", "imported_cold"].includes(walletType);
    const defaultWallet = readEconomyDefaultSpendWalletAddress();
    const isDefaultSpend = address && address === String(defaultWallet || "").trim().toLowerCase();
    const riskLine = risk
      ? `<div class="drive-card-sub" style="color:#ff4f6d;">治理標記：${sanitize(risk.risk_level || risk.label || "risk")} · ${sanitize(risk.reason || "")}</div>`
      : "";
    const freezeLine = freeze
      ? `<div class="drive-card-sub" style="color:#ff4f6d;">${freeze.freeze_type === "provisional" ? "短期審核凍結" : "治理凍結"}：禁止轉出${freeze.expires_at ? ` · 到期 ${sanitize(freeze.expires_at)}` : ""}</div>`
      : "";
    const capability = String(wallet.spend_capability || "enabled");
    const capabilityLine = capability !== "enabled"
      ? `<div class="drive-card-sub" style="color:#f6c56b;">${capability === "receive_only" ? "觀察/收款模式，轉出暫不支援" : "此錢包已停用轉出"}</div>`
      : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(formatEconomyWalletIdentityType(wallet.wallet_type))}${wallet.is_primary ? " · primary" : ""}</strong>
          <div class="drive-card-sub">${sanitize(wallet.status || "-")} · ${sanitize(wallet.wallet_scope || "user")} · ${sanitize(wallet.custody_mode || "-")} · ${sanitize(capability)}${isDefaultSpend ? " · 交易所預設付款" : ""} · ${formatEconomyPointsValue(wallet.points_balance || 0)} 點 · 金額凍結 ${formatEconomyPointsValue(wallet.points_frozen || 0)} 點</div>
          ${capabilityLine}
          ${riskLine}
          ${freezeLine}
          <button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(wallet.address || "")}">${sanitize(wallet.address || "-")}</button>
        </div>
        <div class="drive-file-actions">
          <button class="btn btn-sm" type="button" data-wallet-transfer-to="${sanitize(address)}">交易</button>
          <button class="btn btn-sm" type="button" data-wallet-default="${sanitize(address)}"${capability === "enabled" ? "" : " disabled"}>${isDefaultSpend ? "已預設" : "設為預設"}</button>
          ${coldWallet ? `<button class="btn btn-sm" type="button" data-wallet-secret-check="${sanitize(address)}">密鑰驗證</button>` : ""}
          ${coldWallet ? `<button class="btn btn-danger btn-sm" type="button" data-wallet-delete-cold="${sanitize(address)}">刪除</button>` : ""}
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    if (btn.dataset.explorerBound === "1") return;
    btn.dataset.explorerBound = "1";
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      setEconomyActivePage("explorer");
      searchEconomyExplorer(query);
    });
  });
  list.querySelectorAll("[data-dispute-tx]").forEach((btn) => {
    if (btn.dataset.disputeBound === "1") return;
    btn.dataset.disputeBound = "1";
    btn.addEventListener("click", () => createEconomyTransactionDispute({
      txHash: btn.dataset.disputeTx || "",
      from: btn.dataset.disputeFrom || "",
      to: btn.dataset.disputeTo || "",
      amount: btn.dataset.disputeAmount || "0",
      chainBranch: btn.dataset.disputeBranch || "",
    }));
  });
  list.querySelectorAll("[data-wallet-transfer-to]").forEach((btn) => {
    if (btn.dataset.walletActionBound === "1") return;
    btn.dataset.walletActionBound = "1";
    btn.addEventListener("click", () => openEconomyWalletTransferTo(btn.dataset.walletTransferTo || ""));
  });
  list.querySelectorAll("[data-wallet-default]").forEach((btn) => {
    if (btn.dataset.walletActionBound === "1") return;
    btn.dataset.walletActionBound = "1";
    btn.addEventListener("click", () => setEconomyDefaultWalletFromCard(btn.dataset.walletDefault || ""));
  });
  list.querySelectorAll("[data-wallet-secret-check]").forEach((btn) => {
    if (btn.dataset.walletActionBound === "1") return;
    btn.dataset.walletActionBound = "1";
    btn.addEventListener("click", () => verifyEconomyColdWalletBackupForAddress(btn.dataset.walletSecretCheck || ""));
  });
  list.querySelectorAll("[data-wallet-delete-cold]").forEach((btn) => {
    if (btn.dataset.walletActionBound === "1") return;
    btn.dataset.walletActionBound = "1";
    btn.addEventListener("click", () => deleteEconomyColdWallet(btn.dataset.walletDeleteCold || ""));
  });
}

function economyTransactionDirectionLabel(direction) {
  const value = String(direction || "");
  if (value === "incoming") return "轉入";
  if (value === "outgoing") return "轉出";
  if (value === "self") return "錢包間轉帳";
  if (value === "official_outgoing") return "官方撥款";
  if (value === "official_fund_transfer") return "官方基金調撥";
  if (value === "observed") return "鏈上交易";
  return "交易";
}

function economyTransactionStatusLabel(status) {
  const value = String(status || "");
  if (value === "pending") return "Pending";
  if (value === "confirmed") return "Confirmed";
  if (value.startsWith("failed")) return "Failed";
  return value || "-";
}

function renderEconomyTransferLastResult(txHash, transaction = {}) {
  const wrap = $("economy-transfer-last-result");
  if (!wrap) return;
  if (!txHash) {
    wrap.innerHTML = "";
    return;
  }
  const finality = transaction.finality && typeof transaction.finality === "object" ? transaction.finality : {};
  const eta = economyExplorerSecondsText(finality.eta_seconds || finality.settlement_seconds || 0);
  wrap.innerHTML = `
    <span>Transaction Hash</span>
    <button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(txHash)}">${sanitize(txHash)}</button>
    <span>${Number(finality.proved_count || 0)}/${Number(finality.target_proved_count || 20)} Proved · ETA ${sanitize(eta)} · ${sanitize(economyTransactionStatusLabel(transaction.status || "pending"))}</span>
  `;
  wrap.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      setEconomyActivePage("explorer");
      searchEconomyExplorer(query);
    });
  });
}

function bindEconomyTransactionListEvents() {
  const list = $("economy-transactions-list");
  if (!list) return;
  list.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    if (btn.dataset.explorerBound === "1") return;
    btn.dataset.explorerBound = "1";
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      setEconomyActivePage("explorer");
      searchEconomyExplorer(query);
    });
  });
  list.querySelectorAll("[data-dispute-tx]").forEach((btn) => {
    if (btn.dataset.disputeBound === "1") return;
    btn.dataset.disputeBound = "1";
    btn.addEventListener("click", () => createEconomyTransactionDispute({
      txHash: btn.dataset.disputeTx || "",
      from: btn.dataset.disputeFrom || "",
      to: btn.dataset.disputeTo || "",
      amount: btn.dataset.disputeAmount || "0",
      chainBranch: btn.dataset.disputeBranch || "",
    }));
  });
}

function renderEconomyTransactions(payload = {}) {
  updateEconomyOfficialHotWalletLabels(payload.official_hot_wallet_labels);
  const summary = payload.summary && typeof payload.summary === "object" ? payload.summary : {};
  const rows = Array.isArray(payload.transactions) ? payload.transactions : [];
  setEconomyText("economy-transactions-pending-count", String(Number(summary.pending_count || 0)));
  setEconomyText("economy-transactions-confirmed-count", String(Number(summary.confirmed_count || 0)));
  setEconomyText("economy-transactions-failed-count", String(Number(summary.failed_count || 0)));
  const pendingPoints = Number(summary.pending_incoming_points || 0) + Number(summary.pending_outgoing_points || 0);
  setEconomyText("economy-transactions-pending-points", `待確認 ${formatEconomyPointsValue(pendingPoints)} 點`);
  setEconomyText("economy-transactions-finalized-count", `本次成交 ${Number(summary.finalized_count || 0)}`);
  renderEconomyRootList(rows, "economy-transactions-list", "尚無轉帳交易", (tx) => {
    const finality = tx.finality && typeof tx.finality === "object" ? tx.finality : {};
    const proved = `${Number(finality.proved_count || 0)}/${Number(finality.target_proved_count || 20)} Proved`;
    const status = economyTransactionStatusLabel(tx.status);
    const pendingNote = String(tx.status || "") === "pending"
      ? " · Pending 不會讓收款錢包入帳"
      : "";
    const unownedNote = tx.wallet_flow?.destination_unowned || tx.destination_unowned
      ? " · 未綁定地址"
      : "";
    const direction = economyTransactionDirectionLabel(tx.direction);
    const amountText = tx.direction === "incoming"
      ? `+${formatEconomyPointsValue(tx.amount_points)}`
      : tx.direction === "outgoing" || tx.direction === "official_outgoing" || tx.direction === "official_fund_transfer"
        ? `-${formatEconomyPointsValue(Number(tx.amount_points || 0) + Number(tx.fee_points || 0))}`
        : formatEconomyPointsValue(tx.amount_points);
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(direction)} · ${sanitize(status)} · ${sanitize(proved)} · ${sanitize(amountText)} 點</strong>
          <div class="drive-card-sub">${sanitize(tx.created_at || "")}${pendingNote}${unownedNote}</div>
          <div class="drive-card-sub">From ${sanitize(formatEconomyWalletAddressWithManagerLabel(tx.source_wallet_address || ""))} → To ${sanitize(formatEconomyWalletAddressWithManagerLabel(tx.destination_wallet_address || ""))} · Fee ${formatEconomyPointsValue(tx.fee_points || 0)} 點</div>
          <button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(tx.transaction_hash || tx.tx_group_hash || "")}">${sanitize(tx.transaction_hash || tx.tx_group_hash || "-")}</button>
        </div>
        <div class="drive-file-actions">
          <button class="btn btn-sm" type="button" data-explorer-query="${sanitize(tx.transaction_hash || tx.tx_group_hash || "")}">查看</button>
          <button class="btn btn-sm" type="button"
            data-dispute-tx="${sanitize(tx.transaction_hash || tx.tx_group_hash || "")}"
            data-dispute-from="${sanitize(tx.source_wallet_address || tx.wallet_flow?.source_wallet_address || "")}"
            data-dispute-to="${sanitize(tx.destination_wallet_address || tx.wallet_flow?.destination_wallet_address || "")}"
            data-dispute-amount="${sanitize(String(tx.amount_points || tx.amount || 0))}"
            data-dispute-branch="${sanitize(tx.chain_branch || tx.wallet_flow?.chain_branch || economyCurrentChainBranch || "main")}">疑義交易</button>
        </div>
      </div>
    `;
  });
  bindEconomyTransactionListEvents();
}

async function loadEconomyTransactions() {
  if (!currentUser || !economyChainEnabled()) {
    renderEconomyTransactions({ transactions: [], summary: {} });
    return null;
  }
  try {
    const json = await fetchEconomyJson("/points/transactions?limit=50");
    renderEconomyTransactions(json);
    return json;
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyTransactionMsg, label: "交易管理", fallback: "交易紀錄讀取失敗" });
    renderEconomyTransactions({ transactions: [], summary: {} });
    return null;
  }
}

async function createEconomyTransactionDispute(input = {}) {
  const data = typeof input === "string" ? { txHash: input } : (input || {});
  const hash = String(data.txHash || "").trim();
  economyTransactionMsg(hash ? `開始申報疑義交易 ${shortEconomyWalletAddress(hash)}；下一步會檢查 From 地址持有證明。` : "開始申報疑義交易。");
  if (!hash) {
    economyTransactionMsg("找不到交易 hash，無法申報疑義。", false);
    return;
  }
  if (currentUser === "root") {
    economyNotifyFailure(new Error("root 帳號不使用匿名地址疑義流程；官方錢包或官方地址事故請改走官方治理、內部帳務治理或緊急安全治理。"), {
      msgFn: economyTransactionMsg,
      label: "交易管理",
      fallback: "疑義交易申報失敗",
    });
    return;
  }
  const fromAddress = String(data.from || prompt("From 地址（冷錢包需用此地址備份碼本機簽署；官方熱錢包使用登入帳號綁定證明）", "") || "").trim().toLowerCase();
  const toAddress = String(data.to || prompt("To 地址（系統會先短期限制此地址轉出）", "") || "").trim().toLowerCase();
  const amount = Math.max(0, Math.floor(Number(data.amount || prompt("交易點數", "0") || 0)));
  const chainBranch = String(data.chainBranch || economyCurrentChainBranch || "main").trim() || "main";
  if (!fromAddress || !toAddress || !amount) {
    economyTransactionMsg("疑義交易需要 From、To 與交易點數才能建立地址簽章。", false);
    return;
  }
  const statement = economyPromptAddressDisputeStatement({
    promptText: `請描述疑義交易原因、你主張的事實與佐證，至少 ${ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS} 字。此內容會提供 root 程序審查；請勿填入帳號、暱稱、email。`,
    cancelText: "已取消疑義交易申報。",
    shortText: "疑義交易說明太短",
    msgFn: economyTransactionMsg,
  });
  if (statement === null) return;
  const lossCause = prompt("損失原因：private_key_leak / user_phishing / protocol_fault / exchange_bug / unknown", "private_key_leak") || "unknown";
  const evidence = prompt("證據 refs，每行一個 tx hash、截圖編號或案件號（可留空）", "") || "";
  try {
    const fromWallet = economyWalletByAddress(fromAddress);
    const accountBoundProof = economyWalletSupportsAccountBoundDisputeProof(fromWallet);
    const hasLocalSignaturePath = economyWalletRequiresSignature(fromWallet);
    if (!accountBoundProof && fromWallet && !hasLocalSignaturePath) {
      economyNotifyFailure(new Error("此 From 錢包沒有可用的本機簽章能力，不能用地址證明疑義流程申報。"), {
        msgFn: economyTransactionMsg,
        label: "交易管理",
        fallback: "疑義交易申報失敗",
      });
      return;
    }
    let proof = {
      account_bound_proof: accountBoundProof,
      signature_nonce: economyRequestId("address_dispute_account_bound"),
      signature_runtime_mode: economyAddressDisputeRuntimeMode(),
    };
    if (accountBoundProof) {
      economyTransactionMsg("From 是目前登入帳號綁定的官方熱錢包，使用帳號持有狀態建立疑義，不要求私鑰。");
    } else {
      economyTransactionMsg("等待 From 地址本機簽署疑義交易；私鑰不會送到伺服器。若此地址是他人的官方熱錢包，只有該帳號可直接申報。");
      proof = await economyBuildAddressDisputeProof({
        purpose: "address_dispute_open",
        signerAddress: fromAddress,
        txHash: hash,
        from: fromAddress,
        to: toAddress,
        amount,
        statement,
        evidence,
        chainBranch,
        runtimeMode: economyAddressDisputeRuntimeMode(),
      });
    }
    const json = await fetchEconomyJson("/points/transactions/disputes", {
      method: "POST",
      body: JSON.stringify({
        tx_hash: hash,
        from_wallet_address: fromAddress,
        to_wallet_address: toAddress,
        chain_branch: chainBranch,
        statement,
        victim_wallet_address: fromAddress,
        claimed_amount_points: amount,
        loss_cause: lossCause,
        evidence,
        public_key_jwk: proof.public_key_jwk,
        signature: proof.signature,
        signature_nonce: proof.signature_nonce,
        signature_runtime_mode: proof.signature_runtime_mode,
        account_bound_proof: !!proof.account_bound_proof,
      }),
    });
    economyNotifySuccess(`疑義交易已送出：${json.dispute?.dispute_uuid || ""}；To 地址已短期限制轉出，此申報只建立 case，不代表一定補償或 rollback。`, {
      msgFn: economyTransactionMsg,
      label: "交易管理",
    });
    await loadEconomyTransactionDisputes({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, {
      msgFn: economyTransactionMsg,
      label: "交易管理",
      fallback: "疑義交易申報失敗",
    });
  }
}

function updateEconomyGovernanceOverviewCounts(proposals = null) {
  const rows = Array.isArray(proposals) ? proposals : Array.from(economyGovernanceProposalCache.values());
  const publicRows = rows.filter((item) => economyGovernanceCategoryForProposal(item) === "public");
  const publicVoting = publicRows.filter((item) => economyGovernanceStatusBucket(item) === "voting").length;
  const disputeRows = Array.isArray(economyTransactionDisputeCache) ? economyTransactionDisputeCache : [];
  const activeDisputes = disputeRows.filter((item) => {
    const status = String(item.status || "").trim().toLowerCase();
    return !["rejected", "cancelled", "expired", "closed", "resolved"].includes(status);
  }).length;
  const disputeWithProposal = disputeRows.filter((item) => economyProposalUuidsForDispute(item).length > 0).length;
  setEconomyText("economy-governance-public-count", String(publicRows.length));
  setEconomyText("economy-governance-public-status", `目前可投 ${publicVoting}`);
  setEconomyText("economy-governance-dispute-count", String(disputeRows.length));
  setEconomyText("economy-governance-dispute-status", `待處理 ${activeDisputes} · 已提案 ${disputeWithProposal}`);
}

function renderEconomyTransactionDisputes(payload = {}) {
  updateEconomyOfficialHotWalletLabels(payload.official_hot_wallet_labels);
  const rows = Array.isArray(payload.disputes) ? payload.disputes : [];
  economyTransactionDisputeCache = rows;
  updateEconomyGovernanceOverviewCounts();
  const list = $("economy-disputes-list");
  if (!list) return;
  if (!rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無疑義交易案件</div>`;
    return;
  }
  const availableSelected = rows.some((row) => String(row.dispute_uuid || "") === economySelectedDisputeUuid);
  if (economySelectedDisputeUuid && !availableSelected) {
    economySelectedDisputeUuid = "";
    economySelectedDisputeProposalUuids = new Set();
  }
  list.innerHTML = rows.map((row) => {
    const proposalUuids = economyProposalUuidsForDispute(row);
    const selected = String(row.dispute_uuid || "") === economySelectedDisputeUuid;
    const proposalRows = proposalUuids.map((uuid) => economyGovernanceProposalCache.get(String(uuid || ""))).filter(Boolean);
    const inlineGovernance = selected
      ? `
        <div class="economy-dispute-governance-panel" data-dispute-governance-panel="${sanitize(row.dispute_uuid || "")}" style="margin:.35rem 0 .9rem 1rem;padding:.75rem;border-left:3px solid rgba(80,180,255,.55);background:rgba(80,180,255,.06);">
          <div class="drive-card-sub" style="margin-bottom:.45rem;">此案件的治理提案 / 投票</div>
          <div class="drive-file-list">
            ${proposalRows.length
              ? proposalRows.map((proposal) => economyRenderGovernanceProposalCard(proposal, { nested: true })).join("")
              : proposalUuids.length
                ? `<div class="drive-empty">治理提案資料載入中，請按更新治理。</div>`
                : `<div class="drive-empty">此案件尚未建立治理提案。manager+ 核准並提案後，投票會顯示在這裡。</div>`}
          </div>
        </div>
      `
      : "";
    const managerActions = economyGovernanceCanManage() && ["pending_review", "approved"].includes(String(row.status || ""))
      ? `
        <button class="btn btn-sm" type="button" data-dispute-review="approved" data-dispute-uuid="${sanitize(row.dispute_uuid || "")}">核准</button>
        <button class="btn btn-sm" type="button" data-dispute-review="rejected" data-dispute-uuid="${sanitize(row.dispute_uuid || "")}">駁回</button>
        <button class="btn btn-danger btn-sm" type="button" data-dispute-review-proposal="${sanitize(row.dispute_uuid || "")}">核准並提案</button>
      `
      : "";
    const replyAction = ["pending_review", "approved", "proposal_created"].includes(String(row.status || ""))
      ? `<button class="btn btn-sm" type="button"
          data-dispute-reply="${sanitize(row.dispute_uuid || "")}"
          data-dispute-tx="${sanitize(row.tx_hash || "")}"
          data-dispute-from="${sanitize(row.from_wallet_address || row.victim_wallet_address || "")}"
          data-dispute-to="${sanitize(row.to_wallet_address || row.suspect_wallet_address || "")}"
          data-dispute-amount="${sanitize(String(row.claimed_amount_points || 0))}"
          data-dispute-branch="${sanitize(row.chain_branch || economyCurrentChainBranch || "main")}"
          data-dispute-runtime-mode="${sanitize(row.signature_runtime_mode || economyAddressDisputeRuntimeMode())}">To 地址回覆</button>`
      : "";
    return `
      <div class="drive-file-row${selected ? " active" : ""}" style="${selected ? "border-color:rgba(80,180,255,.55);" : ""}">
        <div>
          <strong>${sanitize(row.status || "-")} · ${sanitize(row.loss_cause || "-")} · ${formatEconomyPointsValue(row.claimed_amount_points || 0)} 點</strong>
          <div class="drive-card-sub">address-proven anonymous · ${sanitize(row.created_at || "")}</div>
          <div class="drive-card-sub">${sanitize(row.statement || "")}</div>
          <button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(row.tx_hash || "")}">${sanitize(row.tx_hash || "")}</button>
          <div class="drive-card-sub">From ${sanitize(formatEconomyWalletAddressWithManagerLabel(row.from_wallet_address || row.victim_wallet_address || ""))} → To ${sanitize(formatEconomyWalletAddressWithManagerLabel(row.to_wallet_address || row.suspect_wallet_address || ""))} · from proof ${row.from_signature_verified ? "ok" : "missing"} · to reply ${row.reply_signature_verified ? "ok" : "none"}</div>
          ${row.initial_freeze_expires_at ? `<div class="drive-card-sub">初始短期凍結至 ${sanitize(row.initial_freeze_expires_at)}${row.escalated_freeze_expires_at ? ` · 治理延長至 ${sanitize(row.escalated_freeze_expires_at)}` : ""}</div>` : ""}
          ${row.reply_statement ? `<div class="drive-card-sub">To 回覆：${sanitize(row.reply_statement || "")}</div>` : ""}
          <div class="drive-card-sub">proposal ${sanitize(row.governance_proposal_uuid || "-")}</div>
        </div>
        <div class="drive-file-actions">
          <button class="btn btn-sm" type="button"
            data-dispute-select="${sanitize(row.dispute_uuid || "")}"
            data-dispute-proposals="${sanitize(proposalUuids.join(","))}">${selected ? "收合提案" : (proposalUuids.length ? "展開提案/投票" : "選取案件")}</button>
          ${replyAction}${managerActions}
        </div>
      </div>
      ${inlineGovernance}
    `;
  }).join("");
  bindEconomyDisputeEvents();
}

async function replyEconomyTransactionDispute(input = {}) {
  const disputeUuid = String(input.disputeUuid || "").trim();
  const txHash = String(input.txHash || "").trim();
  const fromAddress = String(input.from || "").trim().toLowerCase();
  const toAddress = String(input.to || "").trim().toLowerCase();
  const amount = Math.max(0, Math.floor(Number(input.amount || 0)));
  const chainBranch = String(input.chainBranch || economyCurrentChainBranch || "main").trim() || "main";
  const runtimeMode = String(input.runtimeMode || economyAddressDisputeRuntimeMode()).trim() || "unknown";
  if (!disputeUuid || !txHash || !fromAddress || !toAddress || !amount) {
    economyGovernanceMsg("缺少疑義交易回覆所需的地址或交易資料。", false);
    return;
  }
  const statement = economyPromptAddressDisputeStatement({
    promptText: `To 地址持有人回覆，至少 ${ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS} 字。只能寫地址層證據與事實，請勿填入 user id、用戶名、暱稱、email 或帳號資訊。`,
    cancelText: "已取消 To 地址回覆。",
    shortText: "To 地址回覆太短",
    msgFn: economyGovernanceMsg,
  });
  if (statement === null) return;
  const evidence = prompt("To 地址證據 refs，每行一個 tx hash、截圖編號或案件號（可留空）", "") || "";
  try {
    const toWallet = economyWalletByAddress(toAddress);
    const accountBoundProof = economyWalletSupportsAccountBoundDisputeProof(toWallet);
    let proof = {
      account_bound_proof: accountBoundProof,
      signature_nonce: economyRequestId("address_dispute_reply_account_bound"),
      signature_runtime_mode: runtimeMode,
    };
    if (accountBoundProof) {
      economyGovernanceMsg("To 是目前登入帳號綁定的官方熱錢包，使用帳號持有狀態回覆，不要求私鑰。");
    } else {
      economyGovernanceMsg("等待 To 地址本機簽署回覆；私鑰不會送到伺服器。若此地址是他人的官方熱錢包，只有該帳號可直接回覆。");
      proof = await economyBuildAddressDisputeProof({
        purpose: "address_dispute_reply",
        signerAddress: toAddress,
        txHash,
        from: fromAddress,
        to: toAddress,
        amount,
        statement,
        evidence,
        chainBranch,
        runtimeMode,
      });
    }
    await fetchEconomyJson(`/points/transactions/disputes/${encodeURIComponent(disputeUuid)}/reply`, {
      method: "POST",
      body: JSON.stringify({
        statement,
        evidence,
        public_key_jwk: proof.public_key_jwk,
        signature: proof.signature,
        signature_nonce: proof.signature_nonce,
        signature_runtime_mode: proof.signature_runtime_mode,
        account_bound_proof: !!proof.account_bound_proof,
      }),
    });
    economyNotifySuccess("To 地址回覆已送出。", { msgFn: economyGovernanceMsg, label: "疑義交易" });
    await loadEconomyTransactionDisputes({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "疑義交易", fallback: "疑義交易回覆失敗" });
  }
}

async function loadEconomyTransactionDisputes({ silent = false } = {}) {
  if (!currentUser || !economyChainEnabled()) {
    renderEconomyTransactionDisputes({ disputes: [] });
    return false;
  }
  try {
    const json = await fetchEconomyJson("/points/transactions/disputes?limit=50");
    renderEconomyTransactionDisputes(json);
    if (!silent) economyGovernanceMsg("疑義交易案件已更新。");
    return true;
  } catch (err) {
    if (!silent) economyGovernanceMsg(err.message || "疑義交易案件讀取失敗", false);
    return false;
  }
}

async function reviewEconomyTransactionDispute(disputeUuid, status, createProposal = false) {
  const strategy = createProposal
    ? (prompt("Recovery 方案：tainted_remainder_return / treasury_compensation / exclude_tainted_descendants", "tainted_remainder_return") || "tainted_remainder_return")
    : "tainted_remainder_return";
  const note = prompt(createProposal ? "審核意見，會附在治理提案中" : "審核意見", "") || "";
  try {
    const json = await fetchEconomyJson(`/admin/points/transactions/disputes/${encodeURIComponent(disputeUuid)}/review`, {
      method: "POST",
      body: JSON.stringify({
        status,
        review_note: note,
        recommended_strategy: strategy,
        create_proposal: createProposal,
      }),
    });
    const linked = [
      json.proposal?.proposal_uuid ? `recovery ${json.proposal.proposal_uuid}` : "",
      json.address_risk_proposal?.proposal_uuid ? `標記 ${json.address_risk_proposal.proposal_uuid}` : "",
      json.address_freeze_proposal?.proposal_uuid ? `凍結 ${json.address_freeze_proposal.proposal_uuid}` : "",
    ].filter(Boolean).join("，");
    if (createProposal) {
      const proposalUuids = [
        json.proposal?.proposal_uuid,
        json.address_risk_proposal?.proposal_uuid,
        json.address_freeze_proposal?.proposal_uuid,
      ].map((item) => String(item || "").trim()).filter(Boolean);
      economySelectedDisputeUuid = String(disputeUuid || "").trim();
      economySelectedDisputeProposalUuids = new Set(proposalUuids);
    }
    economyNotifySuccess(`疑義交易已更新${linked ? `，已建立治理案：${linked}` : ""}`, {
      msgFn: economyGovernanceMsg,
      label: "治理提案",
    });
    await Promise.all([loadEconomyTransactionDisputes({ silent: true }), loadEconomyGovernance({ silent: true })]);
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "疑義交易審核失敗" });
  }
}

function bindEconomyDisputeEvents() {
  const list = $("economy-disputes-list");
  if (!list) return;
  list.querySelectorAll("[data-dispute-select]").forEach((btn) => {
    if (btn.dataset.disputeBound === "1") return;
    btn.dataset.disputeBound = "1";
    btn.addEventListener("click", async () => {
      const nextUuid = String(btn.dataset.disputeSelect || "").trim();
      const sameSelection = nextUuid && nextUuid === economySelectedDisputeUuid;
      economySelectedDisputeUuid = sameSelection ? "" : nextUuid;
      economySelectedDisputeProposalUuids = sameSelection
        ? new Set()
        : new Set(String(btn.dataset.disputeProposals || "").split(",").map((item) => item.trim()).filter(Boolean));
      economyGovernanceMsg(!economySelectedDisputeUuid
        ? "已收合疑義案件提案。"
        : economySelectedDisputeProposalUuids.size
          ? `已展開疑義案件 ${shortEconomyWalletAddress(economySelectedDisputeUuid)} 的治理提案 / 投票。`
          : `已選取疑義案件 ${shortEconomyWalletAddress(economySelectedDisputeUuid)}；此案件尚未建立治理提案。`);
      await loadEconomyGovernance({ silent: true });
      renderEconomyTransactionDisputes({ disputes: economyTransactionDisputeCache });
    });
  });
  list.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    if (btn.dataset.explorerBound === "1") return;
    btn.dataset.explorerBound = "1";
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      setEconomyActivePage("explorer");
      searchEconomyExplorer(query);
    });
  });
  list.querySelectorAll("[data-dispute-review]").forEach((btn) => {
    if (btn.dataset.disputeBound === "1") return;
    btn.dataset.disputeBound = "1";
    btn.addEventListener("click", () => reviewEconomyTransactionDispute(btn.dataset.disputeUuid || "", btn.dataset.disputeReview || "", false));
  });
  list.querySelectorAll("[data-dispute-review-proposal]").forEach((btn) => {
    if (btn.dataset.disputeBound === "1") return;
    btn.dataset.disputeBound = "1";
    btn.addEventListener("click", () => reviewEconomyTransactionDispute(btn.dataset.disputeReviewProposal || "", "approved", true));
  });
  list.querySelectorAll("[data-dispute-reply]").forEach((btn) => {
    if (btn.dataset.disputeBound === "1") return;
    btn.dataset.disputeBound = "1";
    btn.addEventListener("click", () => replyEconomyTransactionDispute({
      disputeUuid: btn.dataset.disputeReply || "",
      txHash: btn.dataset.disputeTx || "",
      from: btn.dataset.disputeFrom || "",
      to: btn.dataset.disputeTo || "",
      amount: btn.dataset.disputeAmount || "0",
      chainBranch: btn.dataset.disputeBranch || "",
      runtimeMode: btn.dataset.disputeRuntimeMode || "",
    }));
  });
  bindEconomyGovernanceEvents(list);
}

async function submitEconomyWalletTransfer() {
  if (!economyChainEnabled()) {
    economyTransferMsg("PointsChain 私有鏈已停用，鏈上轉帳不可用；基本積分帳本仍可使用。", false);
    return;
  }
  const btn = $("economy-transfer-submit-btn");
  const source = String($("economy-transfer-source-wallet")?.value || "").trim();
  const destination = String($("economy-transfer-destination-wallet")?.value || "").trim();
  const amount = Math.floor(Number($("economy-transfer-amount")?.value || 0));
  const fee = Math.floor(Number($("economy-transfer-fee")?.value || 0));
  const memo = String($("economy-transfer-memo")?.value || "").trim();
  if (!source || !destination || !Number.isFinite(amount) || amount <= 0 || !Number.isFinite(fee) || fee < 0) {
    economyTransferMsg("請確認 From、To、Value 與 Transaction Fee", false);
    return;
  }
  const requestUuid = economyRequestId("points_chain_transfer");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "簽署中...";
    }
    economyTransferMsg("等待冷錢包本機簽署，請確認私鑰備份碼只在可信裝置使用。");
    const signature = await economyBuildTransferSignature({ source, destination, amount, fee, memo, requestUuid });
    if (btn) btn.textContent = "送單中...";
    const json = await fetchEconomyJson("/points/transactions/submit", {
      method: "POST",
      body: JSON.stringify({
        source_wallet_address: source,
        destination_wallet_address: destination,
        amount_points: amount,
        fee_points: fee,
        memo,
        request_uuid: requestUuid,
        signature,
      }),
    });
    const txHash = json.transaction_hash || json.tx_group_hash || json.transaction?.transaction_hash || "";
    const finality = json.transaction?.finality || {};
    const eta = economyExplorerSecondsText(finality.eta_seconds || finality.settlement_seconds || 0);
    const warningSuffix = economyWarningSuffix(json);
    const successMessage = txHash
      ? `交易已送出：${txHash}，等待 20/20 Proved，ETA ${eta}；成交前收款方不會入帳。`
      : `交易已送出，等待 20/20 Proved，ETA ${eta}；成交前收款方不會入帳。`;
    const visibleMessage = `${successMessage}${warningSuffix}`;
    economyTransferMsg(visibleMessage, !warningSuffix);
    renderEconomyTransferLastResult(txHash, json.transaction || {});
    if (txHash) {
      if ($("economy-explorer-query")) $("economy-explorer-query").value = txHash;
    }
    setEconomyActivePage("transactions");
    await loadEconomyDashboard();
    await loadEconomyTransactions();
    economySetMsg(visibleMessage, !warningSuffix);
  } catch (err) {
    economyNotifyFailure(err, {
      msgFn: economyTransferMsg,
      label: "鏈上送單",
      fallback: "冷錢包本機簽署或鏈上送單失敗，交易未送出",
    });
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "送出交易";
    }
  }
}

async function postEconomyWalletOnboarding(payload) {
  await fetchCsrfToken({ force: true });
  const json = await fetchEconomyJson("/points/wallet/onboarding", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderEconomyWalletOnboarding(json.onboarding || {});
  const createdMessages = [];
  if (Number(json.initial_grants?.created_count || 0) > 0) createdMessages.push("初始配點已入帳");
  if (json.signup_bonus?.created) createdMessages.push("註冊禮已入帳");
  if (json.creation_fee?.charged) createdMessages.push(`建立費 ${formatEconomyPointsValue(json.creation_fee.amount_points || 0)} 點已入官方 Treasury`);
  economyWalletMsg(createdMessages.length ? `錢包已綁定，${createdMessages.join("，")}。` : "錢包已綁定。");
  await loadEconomyDashboard();
}

async function useOfficialHotWallet() {
  try {
    const feePayload = await economyWalletCreationFeePayload("official_hot");
    await postEconomyWalletOnboarding({ mode: "official_hot", ...feePayload });
    destroyEconomyColdWalletSecrets();
  } catch (err) {
    economyWalletMsg(err.message || "官方熱錢包建立失敗", false);
  }
}

function openEconomyWalletTransferTo(address) {
  const target = String(address || "").trim().toLowerCase();
  if (!target) {
    economyWalletMsg("找不到目標錢包地址", false);
    return;
  }
  if ($("economy-transfer-destination-wallet")) $("economy-transfer-destination-wallet").value = target;
  const source = $("economy-transfer-source-wallet");
  const defaultWallet = readEconomyDefaultSpendWalletAddress();
  if (source && defaultWallet && Array.from(source.options || []).some((option) => option.value === defaultWallet)) {
    source.value = defaultWallet;
  }
  setEconomyActivePage("balance");
  $("economy-wallet-transfer-card")?.scrollIntoView({ block: "start", behavior: "smooth" });
  economyTransferMsg(`To 已帶入 ${shortEconomyWalletAddress(target)}，請選 From、Value 與 Fee 後送出。`);
}

function setEconomyDefaultWalletFromCard(address) {
  const target = String(address || "").trim().toLowerCase();
  if (!target) {
    economyWalletMsg("找不到要設為預設的錢包地址", false);
    return;
  }
  writeEconomyDefaultSpendWalletAddress(target);
  renderEconomyWalletIdentityList(economyWalletOnboardingState);
  economyWalletMsg(`已設為交易所預設付款錢包：${shortEconomyWalletAddress(target)}。`);
}

async function verifyEconomyColdWalletBackupForAddress(address) {
  const target = String(address || "").trim().toLowerCase();
  if (!target) {
    economyWalletMsg("找不到要驗證的冷錢包地址", false);
    return;
  }
  const raw = window.prompt("本站不保存冷錢包私鑰，無法用帳密重新顯示；請貼上你保存的私鑰備份碼，本機驗證是否對應此地址。", "");
  if (raw === null) {
    economyWalletMsg("已取消冷錢包密鑰驗證。", false);
    return;
  }
  try {
    const loaded = await economyLoadColdWalletBackup(raw, { imported: true });
    if (String(loaded.address || "").trim().toLowerCase() !== target) {
      throw new Error("備份碼地址與此冷錢包不一致");
    }
    economyWalletMsg(`備份碼可控制此地址：${shortEconomyWalletAddress(target)}。私鑰未送到伺服器，也不會被保存。`);
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包密鑰驗證失敗", false);
  }
}

async function deleteEconomyColdWallet(addressOverride = "") {
  try {
    const address = String(addressOverride || "").trim();
    if (!address) {
      economyWalletMsg("請先選擇要刪除的冷錢包", false);
      return;
    }
    if (!confirm("刪除冷錢包不會刪除帳本，但之後必須提供該備份碼才能恢復同一地址。確定刪除？")) return;
    const json = await fetchEconomyJson("/points/wallet/onboarding", {
      method: "DELETE",
      body: JSON.stringify({ address, reason: "user_deleted_cold_wallet" }),
    });
    renderEconomyWalletOnboarding(json.onboarding || {});
    destroyEconomyColdWalletSecrets();
    economyWalletMsg("冷錢包已移除，且不再列入帳戶總額；若要恢復同一地址，請貼上該備份碼並匯入。");
    await loadEconomyDashboard();
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包刪除失敗", false);
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
    const { address } = await economyWalletAddressFromPublicJwk(publicJwk);
    const backupCode = economyCompactColdWalletBackup(privateJwk);
    destroyEconomyColdWalletSecrets({ hideGenerated: false });
    economyColdWalletDraft = { address };
    if ($("economy-wallet-generated-panel")) $("economy-wallet-generated-panel").style.display = "";
    if ($("economy-wallet-generated-address")) $("economy-wallet-generated-address").value = address;
    if ($("economy-wallet-generated-private-key")) $("economy-wallet-generated-private-key").value = backupCode;
    if ($("economy-wallet-generated-selection-status")) $("economy-wallet-generated-selection-status").textContent = "尚未選用";
    if ($("economy-wallet-use-generated-cold-btn")) {
      $("economy-wallet-use-generated-cold-btn").disabled = false;
      $("economy-wallet-use-generated-cold-btn").textContent = "選用此冷錢包";
    }
    economyWalletMsg("冷錢包只建立草稿，尚未匯入或綁定；要用此地址時請按選用此冷錢包。");
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包建立失敗", false);
  }
}

async function selectGeneratedColdWalletForImport() {
  if (!economyColdWalletDraft) {
    economyWalletMsg("目前沒有新建冷錢包草稿", false);
    return;
  }
  try {
    const raw = $("economy-wallet-generated-private-key")?.value || "";
    economyColdWalletBindCandidate = await economyLoadColdWalletBackup(raw, { imported: false });
    if (String(economyColdWalletBindCandidate.address || "").toLowerCase() !== String(economyColdWalletDraft.address || "").toLowerCase()) {
      throw new Error("冷錢包備份碼與草稿地址不一致");
    }
    if ($("economy-wallet-private-key")) $("economy-wallet-private-key").value = "";
    if ($("economy-wallet-private-key-confirmed")) $("economy-wallet-private-key-confirmed").checked = false;
    if ($("economy-wallet-generated-selection-status")) {
      $("economy-wallet-generated-selection-status").textContent = `已選用 ${shortEconomyWalletAddress(economyColdWalletDraft.address)}`;
    }
    if ($("economy-wallet-use-generated-cold-btn")) {
      $("economy-wallet-use-generated-cold-btn").textContent = "已選用";
      $("economy-wallet-use-generated-cold-btn").disabled = true;
    }
    $("economy-wallet-private-key-confirmed")?.focus();
    economyWalletMsg(`已選用此冷錢包 ${shortEconomyWalletAddress(economyColdWalletDraft.address)}；確認已保存備份碼後才會綁定。`);
  } catch (err) {
    economyColdWalletBindCandidate = null;
    if ($("economy-wallet-generated-selection-status")) $("economy-wallet-generated-selection-status").textContent = "選用失敗";
    economyWalletMsg(err.message || "選用冷錢包失敗", false);
  }
}

async function importColdWalletFromText() {
  if (!window.crypto?.subtle) {
    economyWalletMsg("此瀏覽器不支援 WebCrypto，無法匯入冷錢包", false);
    return;
  }
  try {
    const raw = $("economy-wallet-private-key")?.value || "";
    if (!String(raw || "").trim()) {
      economyWalletMsg("請先貼上冷錢包備份碼，再按確認並綁定。", false);
      $("economy-wallet-private-key")?.focus();
      return;
    }
    economyColdWalletBindCandidate = null;
    economyColdWalletBindCandidate = await economyLoadColdWalletBackup(raw, { imported: true });
    if ($("economy-wallet-private-key-confirmed")) $("economy-wallet-private-key-confirmed").checked = false;
    if ($("economy-wallet-generated-selection-status")) $("economy-wallet-generated-selection-status").textContent = "已改用匯入備份碼";
    economyWalletMsg("冷錢包已匯入瀏覽器。確認已保存備份碼後即可綁定。");
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包匯入失敗", false);
  }
}

async function startColdWalletImport() {
  const createCard = $("economy-wallet-create-card");
  if (createCard && "open" in createCard) createCard.open = true;
  economyColdWalletBindCandidate = null;
  if ($("economy-wallet-private-key-confirmed")) $("economy-wallet-private-key-confirmed").checked = false;
  const field = $("economy-wallet-private-key");
  if (field && !String(field.value || "").trim()) {
    field.focus();
    economyWalletMsg("請貼上要匯入或恢復的冷錢包備份碼；確認保存後再綁定。");
    return;
  }
  await importColdWalletFromText();
}

async function confirmColdWalletBinding() {
  let scrubSecrets = false;
  try {
    if (!$("economy-wallet-private-key-confirmed")?.checked) {
      economyWalletMsg("請先確認已保存備份碼", false);
      return;
    }
    const raw = String($("economy-wallet-private-key")?.value || "").trim();
    if (raw) {
      economyColdWalletBindCandidate = null;
      economyColdWalletBindCandidate = await economyLoadColdWalletBackup(raw, { imported: true });
    }
    if (!economyColdWalletBindCandidate) {
      economyWalletMsg("請先匯入備份碼或選用新冷錢包", false);
      return;
    }
    const walletType = economyColdWalletBindCandidate.imported ? "imported_cold" : "self_custody_cold";
    const payload = await economyBuildWalletBindPayload({
      privateKey: economyColdWalletBindCandidate.privateKey,
      publicJwk: economyColdWalletBindCandidate.publicJwk,
      walletType,
    });
    const feePayload = await economyWalletCreationFeePayload(walletType);
    scrubSecrets = true;
    await postEconomyWalletOnboarding({ ...payload, ...feePayload });
  } catch (err) {
    economyWalletMsg(err.message || "冷錢包綁定失敗", false);
  } finally {
    if (scrubSecrets) destroyEconomyColdWalletSecrets();
  }
}

function renderEconomyCatalog(items) {
  economyCatalogCache = Array.isArray(items) ? items : [];
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
    const proofButton = economyChainEnabled()
      ? `<button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>`
      : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(formatEconomyLedgerAmount(row))}</strong>
          <div class="drive-card-sub">${sanitize(formatEconomyLedgerAction(row.action_type))} · ${sanitize(row.created_at || "")}</div>
          ${walletFlow ? `<div class="drive-card-sub economy-ledger-wallet-flow">${sanitize(walletFlow)}</div>` : ""}
          ${source ? `<div class="drive-card-sub">${sanitize(source)}</div>` : ""}
          <div class="economy-ledger-hash">Ledger UUID：${sanitize(row.ledger_uuid || row.ledger_hash || "")}</div>
        </div>
        ${proofButton}
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
  const safeRows = Array.isArray(rows) ? rows.filter((row) => row !== null && row !== undefined) : [];
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

function economyFormulaCard(label, value, tone = "") {
  const toneClass = tone ? ` ${tone}` : "";
  return `
    <div class="economy-formula-card${toneClass}">
      <span>${sanitize(label)}</span>
      <strong>${sanitize(value)}</strong>
    </div>
  `;
}

function economyFormulaOperator(symbol) {
  return `<div class="economy-formula-operator" aria-hidden="true">${sanitize(symbol)}</div>`;
}

function renderEconomyLayerSummary(report) {
  const stats = report?.stats && typeof report.stats === "object" ? report.stats : {};
  const layer = stats.economy_layer && typeof stats.economy_layer === "object" ? stats.economy_layer : {};
  const supply = layer.supply && typeof layer.supply === "object" ? layer.supply : {};
  const funds = layer.funds && typeof layer.funds === "object" ? layer.funds : {};
  const health = layer.health && typeof layer.health === "object" ? layer.health : {};
  const replay = layer.replay && typeof layer.replay === "object" ? layer.replay : {};
  const bridge = layer.supply_equation && typeof layer.supply_equation === "object"
    ? layer.supply_equation
    : (layer.legacy_bridge && typeof layer.legacy_bridge === "object" ? layer.legacy_bridge : {});
  const snapshot = replay.snapshot && typeof replay.snapshot === "object" ? replay.snapshot : {};
  const derivedVerify = replay.derived_verify && typeof replay.derived_verify === "object" ? replay.derived_verify : {};
  const fund = (key) => funds[key] && typeof funds[key] === "object" ? funds[key] : {};
  const fundStatus = (key) => {
    const item = fund(key);
    const custody = item.custody_mode || "system";
    const status = item.wallet_status || item.status || "active";
    const cache = item.derived_cache ? "derived cache" : "ledger replay";
    return `${status} · ${custody} · ${cache}`;
  };
  const fundAddress = (key) => {
    const item = fund(key);
    return item.address || item.wallet_address || item.public_address || item.account_address || "-";
  };
  economyFundAddressCache = {
    mint: fundAddress("mint"),
    official_treasury: fundAddress("official_treasury"),
    promo_fund: fundAddress("promo_fund"),
    exchange_fund: fundAddress("exchange_fund"),
    burn: fundAddress("burn"),
  };
  syncGovernanceTreasuryDestination();
  setEconomyText("economy-layer-health", String(health.status || "-").toUpperCase());
  setEconomyText("economy-layer-health-detail", `原因 ${Array.isArray(health.reasons) ? health.reasons.join(", ") : "ok"}`);
  setEconomyText("economy-layer-max-supply", formatEconomyPointsValue(supply.max_supply || 0));
  setEconomyText("economy-layer-minted-total", `已 Mint ${formatEconomyPointsValue(supply.minted_total || 0)}`);
  setEconomyText("economy-layer-mint-remaining", formatEconomyPointsValue(supply.mint_remaining || 0));
  setEconomyText("economy-layer-releasable-supply", `可釋出上限 ${formatEconomyPointsValue(supply.releasable_supply || 0)}`);
  setEconomyText("economy-layer-releasable-remaining", formatEconomyPointsValue(supply.releasable_remaining || 0));
  setEconomyText("economy-layer-reserved-locked", `保留鎖定 ${formatEconomyPointsValue(supply.reserved_locked || 0)}`);
  setEconomyText("economy-layer-active-supply", formatEconomyPointsValue(supply.active_supply || 0));
  setEconomyText("economy-layer-circulating-supply", `流通 ${formatEconomyPointsValue(supply.circulating_supply || 0)} · fund ${formatEconomyPointsValue(supply.fund_supply || 0)}`);
  setEconomyText("economy-root-wallet-mint-balance", `未發放 ${formatEconomyPointsValue(supply.mint_remaining || 0)}`);
  setEconomyText("economy-root-wallet-mint-status", fundStatus("mint"));
  setEconomyText("economy-root-wallet-mint-address", fundAddress("mint"));
  setEconomyText("economy-root-wallet-official-balance", formatEconomyPointsValue(fund("official_treasury").balance || 0));
  setEconomyText("economy-root-wallet-official-status", fundStatus("official_treasury"));
  setEconomyText("economy-root-wallet-official-address", fundAddress("official_treasury"));
  setEconomyText("economy-root-wallet-promo-balance", formatEconomyPointsValue(fund("promo_fund").balance || 0));
  setEconomyText("economy-root-wallet-promo-status", fundStatus("promo_fund"));
  setEconomyText("economy-root-wallet-promo-address", fundAddress("promo_fund"));
  setEconomyText("economy-root-wallet-exchange-balance", formatEconomyPointsValue(fund("exchange_fund").balance || 0));
  setEconomyText(
    "economy-root-wallet-exchange-status",
    `${fundStatus("exchange_fund")} · 資產 ${formatEconomyPointsValue(supply.exchange_total_assets || fund("exchange_fund").balance || 0)} · 應收 ${formatEconomyPointsValue(supply.exchange_receivable_principal || 0)}`,
  );
  setEconomyText("economy-root-wallet-exchange-address", fundAddress("exchange_fund"));
  setEconomyText("economy-root-wallet-burn-balance", formatEconomyPointsValue(supply.burned_total || fund("burn").balance || 0));
  setEconomyText("economy-root-wallet-burn-status", fundStatus("burn"));
  setEconomyText("economy-root-wallet-burn-address", fundAddress("burn"));
  const formulaEl = $("economy-layer-supply-formula");
  if (formulaEl) {
    const burned = Number(bridge.burned_total ?? supply.burned_total ?? 0);
    const official = Number(bridge.official_treasury_balance ?? fund("official_treasury").balance ?? 0);
    const outside = Number(
      bridge.economy_external_circulating_points
        ?? supply.external_supply
        ?? supply.circulating_supply
        ?? bridge.total_legacy_outstanding_points
        ?? 0
    );
    const mintRemaining = Number(bridge.mint_remaining ?? supply.mint_remaining ?? 0);
    const exchange = Number(bridge.exchange_fund_balance ?? fund("exchange_fund").balance ?? 0);
    const promo = Number(bridge.promo_fund_balance ?? fund("promo_fund").balance ?? 0);
    const total = Number(bridge.actual_supply_equation_total ?? (burned + official + outside + mintRemaining + exchange + promo));
    const maxSupply = Number(bridge.max_supply ?? supply.max_supply ?? 0);
    const gap = Number(bridge.actual_supply_equation_gap_points ?? (total - maxSupply));
    const gapTone = gap === 0 ? "total" : "warning";
    formulaEl.innerHTML = `
      <div class="economy-supply-title">閉環公式</div>
      <div class="economy-supply-equation-ui">
        ${economyFormulaCard("總上限", formatEconomyPointsValue(maxSupply), "total")}
        ${economyFormulaOperator("=")}
        ${economyFormulaCard("已 burn", formatEconomyPointsValue(burned))}
        ${economyFormulaOperator("+")}
        ${economyFormulaCard("官方錢包", formatEconomyPointsValue(official))}
        ${economyFormulaOperator("+")}
        ${economyFormulaCard("鏈上在外流通", formatEconomyPointsValue(outside))}
        ${economyFormulaOperator("+")}
        ${economyFormulaCard("未發放 mint 量", formatEconomyPointsValue(mintRemaining))}
        ${economyFormulaOperator("+")}
        ${economyFormulaCard("交易所基金", formatEconomyPointsValue(exchange))}
        ${economyFormulaOperator("+")}
        ${economyFormulaCard("PROMO 基金", formatEconomyPointsValue(promo))}
        ${economyFormulaOperator("=")}
        ${economyFormulaCard("公式總和", formatEconomyPointsValue(total), gapTone)}
        ${economyFormulaCard("差額", `${formatEconomyPointsValue(gap)} · ${gap === 0 ? "閉環正常" : "需查帳"}`, gapTone)}
      </div>
    `;
  }
  setEconomyText("economy-layer-replay-height", formatEconomyPointsValue(replay.height || 0));
  setEconomyText("economy-layer-replay-hash", `derived cache · ${shortEconomyWalletAddress(replay.wallet_root_hash || "")}`);
  setEconomyText("economy-layer-snapshot-height", formatEconomyPointsValue(snapshot.snapshot_height ?? replay.height ?? 0));
  setEconomyText("economy-layer-derived-verify", `${derivedVerify.ok === true ? "verify ok" : "verify failed"} · ${shortEconomyWalletAddress(snapshot.wallet_root_hash || replay.wallet_root_hash || "")}`);
}

function renderEconomyRootFundingPools(payload) {
  const safe = payload && typeof payload === "object" ? payload : {};
  const reserve = safe.reserve_pool && typeof safe.reserve_pool === "object" ? safe.reserve_pool : {};
  const funding = safe.funding_pool && typeof safe.funding_pool === "object" ? safe.funding_pool : {};
  const lending = safe.lending_summary && typeof safe.lending_summary === "object" ? safe.lending_summary : {};
  const margin = safe.open_margin_summary && typeof safe.open_margin_summary === "object" ? safe.open_margin_summary : {};
  const fees = safe.fee_summary && typeof safe.fee_summary === "object" ? safe.fee_summary : {};
  const chainExchange = safe.pointschain_exchange_fund && typeof safe.pointschain_exchange_fund === "object" ? safe.pointschain_exchange_fund : {};
  const reserveBalance = Number(reserve.balance_points || 0);
  const chainExchangeBalance = Number(chainExchange.balance_points ?? reserveBalance);
  const reserveDiff = reserveBalance - chainExchangeBalance;
  setEconomyText("economy-root-reserve-balance", formatEconomyPointsValue(reserve.balance_points || 0));
  setEconomyText(
    "economy-root-reserve-updated",
    `更新 ${reserve.updated_at || "-"} · PointsChain EXCHANGE ${formatEconomyPointsValue(chainExchangeBalance)}${reserveDiff ? ` · 差額 ${formatEconomyPointsValue(reserveDiff)}` : " · 已對齊"}`,
  );
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
  setEconomyText("economy-root-position-spot-count", formatEconomyPointsValue(summary.spot_position_count || 0));
  setEconomyText("economy-root-position-margin-count", formatEconomyPointsValue(summary.margin_position_count || 0));
  setEconomyText("economy-root-position-margin-detail", `開倉 ${formatEconomyPointsValue(summary.margin_position_count || 0)}`);
  setEconomyText("economy-root-position-orders", formatEconomyPointsValue(summary.open_order_count || 0));
  setEconomyText("economy-root-position-orders-detail", `凍結 ${formatEconomyPointsValue(summary.frozen_order_points || 0)}`);
  setEconomyText("economy-root-position-bots", formatEconomyPointsValue(summary.total_bot_count || 0));
  setEconomyText("economy-root-position-bots-detail", `啟用 ${formatEconomyPointsValue(summary.total_enabled_bot_count || 0)} · 網格 ${formatEconomyPointsValue(summary.grid_bot_count || 0)}`);
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

function economyGovernanceIncidentRows(governance = {}) {
  const safe = governance && typeof governance === "object" ? governance : {};
  const rows = [];
  const push = (kind, severity, title, detail, meta = {}) => {
    rows.push({ kind, severity, title, detail, meta });
  };
  const riskLabels = Array.isArray(safe.active_risk_labels) ? safe.active_risk_labels.filter((item) => item && typeof item === "object") : [];
  riskLabels.forEach((item) => {
    push(
      "risk_label",
      "high",
      `詐騙 / 風險標記：${shortEconomyWalletAddress(item.wallet_address || "")}`,
      `${item.risk_level || item.label || "risk"} · ${item.reason || ""}`,
      { address: item.wallet_address || "", proposal_uuid: item.proposal_uuid || "", created_at: item.updated_at || item.created_at || "" },
    );
  });
  const freezes = Array.isArray(safe.active_freezes) ? safe.active_freezes.filter((item) => item && typeof item === "object") : [];
  freezes.forEach((item) => {
    push(
      "governance_freeze",
      "critical",
      `治理凍結：${shortEconomyWalletAddress(item.wallet_address || "")}`,
      `禁止轉出 · ${item.reason || ""}`,
      { address: item.wallet_address || "", proposal_uuid: item.freeze_proposal_uuid || "", created_at: item.updated_at || item.created_at || "" },
    );
  });
  const provisional = Array.isArray(safe.active_provisional_freezes) ? safe.active_provisional_freezes.filter((item) => item && typeof item === "object") : [];
  provisional.forEach((item) => {
    push(
      "provisional_freeze",
      "warning",
      `短期審核凍結：${shortEconomyWalletAddress(item.wallet_address || "")}`,
      `禁止轉出 · 到期 ${item.expires_at || "-"} · ${item.reason || ""}`,
      { address: item.wallet_address || "", proposal_uuid: item.linked_proposal_uuid || "", created_at: item.updated_at || item.created_at || "" },
    );
  });
  const branches = Array.isArray(safe.branches) ? safe.branches.filter((item) => item && typeof item === "object") : [];
  branches.forEach((item) => {
    const canonical = Boolean(item.is_canonical);
    const writeEnabled = Boolean(item.write_enabled);
    const status = String(item.status || "");
    if (!canonical || status.includes("recovery") || !writeEnabled) {
      push(
        "branch",
        canonical ? "warning" : "info",
        `${canonical ? "目前 canonical recovery branch" : "非 canonical 舊分支"}：${shortEconomyWalletAddress(item.branch_uuid || "")}`,
        `${status || "-"} · parent ${shortEconomyWalletAddress(item.parent_branch_uuid || "")} · write ${writeEnabled ? "enabled" : "disabled"}`,
        { branch_uuid: item.branch_uuid || "", proposal_uuid: item.proposal_uuid || "", created_at: item.activated_at || item.created_at || "" },
      );
    }
  });
  const auditVerify = safe.audit_verify && typeof safe.audit_verify === "object" ? safe.audit_verify : {};
  if (auditVerify.ok === false) {
    push(
      "governance_audit",
      "critical",
      "治理 audit hash chain 異常",
      `${Number((auditVerify.errors || []).length || 0)} 個 audit verify error`,
      { created_at: "" },
    );
  }
  rows.sort((a, b) => String(b.meta?.created_at || "").localeCompare(String(a.meta?.created_at || "")));
  return rows;
}

function renderEconomyGovernanceIncidents(governance = {}) {
  const rows = economyGovernanceIncidentRows(governance);
  const summary = $("economy-governance-incident-summary");
  if (summary) {
    const riskCount = Array.isArray(governance.active_risk_labels) ? governance.active_risk_labels.length : 0;
    const freezeCount = Array.isArray(governance.active_freezes) ? governance.active_freezes.length : 0;
    const provisionalCount = Array.isArray(governance.active_provisional_freezes) ? governance.active_provisional_freezes.length : 0;
    const branchCount = Array.isArray(governance.branches)
      ? governance.branches.filter((item) => item && (item.is_canonical || item.status !== "main")).length
      : 0;
    summary.textContent = rows.length
      ? `風險標記 ${riskCount} · 治理凍結 ${freezeCount} · 短期凍結 ${provisionalCount} · 分支事件 ${branchCount}`
      : "目前沒有 active 治理風險事件";
    summary.style.color = rows.length ? "#ffb74d" : "var(--muted)";
  }
  renderEconomyRootList(rows, "economy-governance-incident-list", "目前沒有 active 治理風險事件", (row) => {
    const tone = row.severity === "critical" ? "negative" : (row.severity === "warning" || row.severity === "high" ? "warning" : "");
    const address = row.meta?.address || "";
    const branch = row.meta?.branch_uuid || "";
    const query = address || branch || row.meta?.proposal_uuid || "";
    return `
      <div class="drive-file-row">
        <div>
          <strong class="${tone}">${sanitize(row.title || "-")}</strong>
          <div class="drive-card-sub">${sanitize(row.detail || "")}</div>
          <div class="drive-card-sub">${sanitize(row.kind || "-")} · ${sanitize(row.meta?.created_at || "-")} · proposal ${sanitize(shortEconomyWalletAddress(row.meta?.proposal_uuid || ""))}</div>
          ${query ? `<button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(query)}">${sanitize(query)}</button>` : ""}
        </div>
      </div>
    `;
  });
  const list = $("economy-governance-incident-list");
  if (list) {
    list.querySelectorAll("[data-explorer-query]").forEach((btn) => {
      if (btn.dataset.explorerBound === "1") return;
      btn.dataset.explorerBound = "1";
      btn.addEventListener("click", () => {
        const query = btn.dataset.explorerQuery || "";
        if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
        setEconomyActivePage("explorer");
        searchEconomyExplorer(query);
      });
    });
  }
}

function renderEconomyBranchTree(governance = {}) {
  const tree = governance.branch_tree && typeof governance.branch_tree === "object" ? governance.branch_tree : {};
  const nodes = Array.isArray(tree.nodes) ? tree.nodes.filter((item) => item && typeof item === "object") : [];
  const summary = $("economy-branch-tree-summary");
  const list = $("economy-branch-tree-list");
  const canonical = tree.canonical_branch_uuid || "main";
  if (summary) {
    summary.textContent = nodes.length
      ? `canonical ${shortEconomyWalletAddress(canonical)} · 分支 ${Number(tree.node_count || nodes.length)} · archived ${Number(tree.archived_count || 0)} · write-enabled ${Number(tree.write_enabled_count || 0)}`
      : "尚無分支資料，main 為目前 canonical";
  }
  if (!list) return;
  if (!nodes.length) {
    list.innerHTML = `<div class="drive-empty">尚無 recovery branch；main 分支正常運作</div>`;
    return;
  }
  list.innerHTML = nodes.map((node) => {
    const branchUuid = String(node.branch_uuid || "main");
    const parent = String(node.parent_branch_uuid || "");
    const isCanonical = Boolean(node.is_canonical);
    const writeEnabled = Boolean(node.write_enabled);
    const archived = !isCanonical;
    const depth = Math.min(8, Math.max(0, Number(node.depth || 0)));
    const status = String(node.status || node.node_state || "-");
    const openAttr = isCanonical || (!node.auto_collapsed && !archived) ? " open" : "";
    const badgeClass = isCanonical ? "canonical" : (archived ? "archived" : "");
    const label = isCanonical ? "CANONICAL" : (writeEnabled ? "WRITE" : "READ ONLY");
    const incident = node.incident_tx_hash || "";
    const proposal = node.proposal_uuid || "";
    return `
      <details class="economy-branch-node" style="margin-left:${depth * 18}px"${openAttr}>
        <summary>
          <span class="economy-branch-title">
            <span class="economy-branch-badge ${badgeClass}">${sanitize(label)}</span>
            <strong>${sanitize(shortEconomyWalletAddress(branchUuid))}</strong>
            <span class="drive-card-sub">${sanitize(status)}</span>
          </span>
        </summary>
        <div class="economy-branch-meta">
          <div>branch ${sanitize(branchUuid)}</div>
          <div>parent ${sanitize(parent || "-")} · children ${Number(node.children_count || 0)}</div>
          <div>ledger ${Number(node.ledger_count || 0)} · blocks ${Number(node.sealed_block_count || 0)} · unsealed ${Number(node.unsealed_ledger_count || 0)} · economy events ${Number(node.economy_event_count || 0)}</div>
          <div>recovery ${sanitize(node.recovery_type || "-")} · activated ${sanitize(node.activated_at || node.created_at || "-")}</div>
          ${incident ? `<button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(incident)}">incident ${sanitize(shortEconomyWalletAddress(incident))}</button>` : ""}
          ${proposal ? `<div>proposal ${sanitize(shortEconomyWalletAddress(proposal))}</div>` : ""}
        </div>
      </details>
    `;
  }).join("");
  list.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    if (btn.dataset.explorerBound === "1") return;
    btn.dataset.explorerBound = "1";
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      setEconomyActivePage("explorer");
      searchEconomyExplorer(query);
    });
  });
}

function renderEconomyRootReport(report) {
  const safeReport = report && typeof report === "object" ? report : {};
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
  renderEconomyGovernanceIncidents(safeReport.governance || {});
  renderEconomyBranchTree(safeReport.governance || {});
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
        <div class="drive-card-sub">ledger #${Number(row.id || 0)} · ${sanitize(row.public_account_id || "-")} · ${sanitize(formatEconomyLedgerAction(row.action_type))} · risk=${sanitize(row.risk_flag || "none")}</div>
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
  renderEconomyRootList(safeReport.unsealed_transactions, "economy-unsealed-transaction-list", "目前沒有未封交易", (row) => {
    const hash = row.transaction_hash || row.ledger_hash || row.ledger_uuid || "";
    const finality = row.finality && typeof row.finality === "object" ? row.finality : {};
    const proved = `${Number(finality.proved_count || 0)}/${Number(finality.target_proved_count || 20)} Proved`;
    const status = finality.finality_status || row.status || "unsealed";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(formatEconomyLedgerAction(row.action_type || "wallet_transfer"))} · ${sanitize(status)} · ${sanitize(proved)}</strong>
          <div class="drive-card-sub">${sanitize(row.source || "unsealed")} · ${sanitize(row.created_at || "")} · Value ${formatEconomyPointsValue(row.amount || 0)} 點</div>
          <button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(hash)}">${sanitize(hash || "-")}</button>
        </div>
      </div>
    `;
  });
  const unsealedList = $("economy-unsealed-transaction-list");
  if (unsealedList) {
    unsealedList.querySelectorAll("[data-explorer-query]").forEach((btn) => {
      if (btn.dataset.explorerBound === "1") return;
      btn.dataset.explorerBound = "1";
      btn.addEventListener("click", () => {
        const query = btn.dataset.explorerQuery || "";
        if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
        setEconomyActivePage("explorer");
        searchEconomyExplorer(query);
      });
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

async function fetchEconomyJson(url, options = {}) {
  const { allowMissingSnapshot = false, ...requestOptions } = options || {};
  await fetchCsrfToken({ force: true });
  const headers = { ...(requestOptions.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (requestOptions.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await apiFetch(API + url, { credentials: "same-origin", ...requestOptions, headers });
  const json = await res.json().catch(() => ({}));
  if (allowMissingSnapshot && json?.snapshot?.missing) return json;
  if (!res.ok || !json.ok) throw new Error(json.msg || json.message || json.error || `HTTP ${res.status}`);
  return json;
}

async function loadEconomyDashboard() {
  if (!currentUser) return;
  try {
    const rootMode = currentUser === "root";
    const chainFeatureOn = economyChainEnabled();
    syncEconomySubpages(rootMode);
    if ($("economy-user-summary-grid")) $("economy-user-summary-grid").style.display = rootMode ? "none" : "";
    if ($("economy-user-ledger-card")) $("economy-user-ledger-card").style.display = rootMode ? "none" : "";
    setEconomyRootLayout(rootMode);
    if (rootMode) {
      if ($("economy-chain-ok")) $("economy-chain-ok").textContent = chainFeatureOn ? "讀取中" : "已停用";
      if ($("economy-chain-countdown")) $("economy-chain-countdown").textContent = chainFeatureOn ? "封塊進度：讀取中..." : "封塊進度：PointsChain 私有鏈已停用";
      const sidebarPoints = $("sidebar-points");
      if (sidebarPoints) {
        sidebarPoints.dataset.points = "root: server resources";
        updateSidebarIdentity();
      }
      if (chainFeatureOn) {
        const [transactions, onboarding] = await Promise.all([
          fetchEconomyJson("/points/transactions?limit=50"),
          fetchEconomyJson("/points/wallet/onboarding"),
        ]);
        renderEconomyWalletOnboarding(onboarding.onboarding || {});
        renderEconomyTransactions(transactions || {});
      } else {
        stopEconomyBlockCountdown();
        renderEconomyTransactions({ transactions: [], summary: {} });
        setEconomyChainStatus("基本積分模式：PointsChain 私有鏈已停用，錢包地址、Explorer、交易管理與封塊不會載入。");
      }
    } else {
      stopEconomyBlockCountdown();
      const baseRequests = [
        fetchEconomyJson("/points/wallet"),
        fetchEconomyJson(`/points/ledger?limit=50&offset=${economyLedgerOffset}`),
        fetchEconomyJson("/points/catalog"),
      ];
      const [wallet, ledger, catalog] = await Promise.all(baseRequests);
      const [onboarding, transactions] = chainFeatureOn
        ? await Promise.all([
            fetchEconomyJson("/points/wallet/onboarding"),
            fetchEconomyJson("/points/transactions?limit=50"),
          ])
        : [{ onboarding: {} }, { transactions: [], summary: {} }];
      renderEconomyWallet(wallet.wallet);
      renderEconomyWalletOnboarding(onboarding.onboarding || {});
      renderEconomyLedger(ledger.ledger || []);
      renderEconomyCatalog(catalog.catalog || []);
      renderEconomyTransactions(transactions || {});
    }
    const rootCard = $("economy-root-card");
    if (rootCard) rootCard.style.display = currentUser === "root" ? "" : "none";
    const rootReportOk = rootMode && chainFeatureOn ? await loadEconomyRootReport() : true;
    const shouldLoadRootTrading = rootMode && chainFeatureOn && ["funding-pools", "all-positions"].includes(economyActivePage);
    const rootTradingOk = shouldLoadRootTrading
      ? await loadEconomyRootTradingReadOnly({ refreshSnapshot: true, silent: true })
      : true;
    if (typeof loadTradingDashboard === "function") {
      await loadTradingDashboard();
    }
    if (rootReportOk !== false && rootTradingOk !== false) {
      economySetMsg(chainFeatureOn ? "" : "基本積分模式：PointsChain 私有鏈已停用；帳本與服務扣點仍可使用。");
    }
    if (chainFeatureOn) {
      await loadEconomyGovernance({ silent: true });
      if (economyActivePage === "governance") await loadEconomyTransactionDisputes({ silent: true });
    }
  } catch (err) {
    economySetMsg(err.message || "PointsChain 讀取失敗", false);
  }
}

async function loadEconomyRootReport() {
  if (currentUser !== "root") return true;
  if (!economyChainEnabled()) {
    stopEconomyBlockCountdown();
    if ($("economy-chain-ok")) $("economy-chain-ok").textContent = "已停用";
    if ($("economy-chain-countdown")) $("economy-chain-countdown").textContent = "封塊進度：PointsChain 私有鏈已停用";
    setEconomyChainStatus("基本積分模式：PointsChain 私有鏈已停用。");
    return true;
  }
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

async function refreshEconomyRootTradingSnapshots(reason = "root_economy_manual_refresh") {
  if (currentUser !== "root") return { ok: false, skipped: true };
  return fetchEconomyJson("/root/trading/sitewide/refresh", {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

async function loadEconomyRootTradingReadOnly(options = {}) {
  if (currentUser !== "root" || !economyPositionsAvailable()) return true;
  const refreshSnapshot = !!(options && options.refreshSnapshot);
  const silent = !!(options && options.silent);
  try {
    if (refreshSnapshot) {
      await refreshEconomyRootTradingSnapshots(
        economyActivePage === "all-positions"
          ? "root_all_positions_open_or_refresh"
          : "root_funding_pools_open_or_refresh",
      );
    }
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
    if (refreshSnapshot && !silent) economySetMsg("交易資金池與全用戶倉位快照已更新。");
    return true;
  } catch (err) {
    economySetMsg(err.message || "root 交易資金池與倉位資料讀取失敗", false);
    return false;
  }
}

async function spendEconomyItem(itemKey) {
  if (!itemKey) return;
  const item = economyCatalogCache.find((entry) => String(entry.item_key || "") === String(itemKey));
  const quantity = 1;
  const amount = Math.floor(Number(item?.base_price || 0)) * quantity;
  const chainFeatureOn = economyChainEnabled();
  let sourceWallet = "";
  if (chainFeatureOn) {
    const defaultWallet = readEconomyDefaultSpendWalletAddress();
    sourceWallet = window.prompt("請確認本次付款錢包地址；可改用其他錢包。", defaultWallet || "");
    if (sourceWallet === null) {
      economySetMsg("已取消付款");
      return;
    }
  }
  if (!Number.isFinite(amount) || amount <= 0) {
    economySetMsg("找不到服務價格，付款未送出", false);
    return;
  }
  const requestUuid = economyRequestId("points_service_fee");
  const referenceType = "price_catalog";
  const referenceId = `catalog:${itemKey}`;
  try {
    if (chainFeatureOn) economySetMsg("等待冷錢包本機簽署服務費，請確認私鑰備份碼只在可信裝置使用。");
    const signature = chainFeatureOn
      ? await economyBuildServiceFeeSignature({
          source: sourceWallet,
          itemKey,
          quantity,
          amount,
          requestUuid,
          referenceType,
          referenceId,
        })
      : "";
    const json = await fetchEconomyJson("/points/spend", {
      method: "POST",
      body: JSON.stringify({
        item_key: itemKey,
        quantity,
        request_uuid: requestUuid,
        signature,
        source_wallet_address: sourceWallet,
      }),
    });
    renderEconomyWallet(json.wallet);
    await loadEconomyDashboard();
    const charge = json.charge || {};
    const settlement = json.settlement || {};
    const threshold = Number(json.batch_threshold_points || settlement.threshold_points || 0);
    const reserved = Number(settlement.reserved_total_points || 0);
    const msg = settlement.created
      ? `服務費已凍結並批次結算：${formatEconomyPointsValue(settlement.settled_amount_points || amount)} 點 · batch ${shortEconomyWalletAddress(settlement.batch_uuid || "")}`
      : chainFeatureOn
        ? `服務費已凍結：${formatEconomyPointsValue(charge.amount_points || amount)} 點 · 累積 ${formatEconomyPointsValue(reserved)}/${formatEconomyPointsValue(threshold)} 點後批次鏈上扣款`
        : `服務費已凍結：${formatEconomyPointsValue(charge.amount_points || amount)} 點 · 基本積分模式下累積 ${formatEconomyPointsValue(reserved)}/${formatEconomyPointsValue(threshold)} 點後批次扣款`;
    economySetMsg(msg);
  } catch (err) {
    economyNotifyFailure(err, {
      msgFn: economySetMsg,
      label: "服務費付款",
      fallback: "冷錢包本機簽署或服務費付款失敗，服務費未送出",
    });
  }
}

function economyRootOfficialGrantMsg(text, ok = true) {
  economyInlineMsg("economy-root-official-grant-msg", text, ok, "官方 Treasury 撥款提案");
}

function economyGovernanceStatusLabel(status) {
  const labels = {
    voting: "投票中",
    passed: "已通過",
    rejected: "已否決",
    expired: "已過期",
    executed: "已執行",
    cancelled: "已取消",
  };
  return labels[String(status || "")] || String(status || "-");
}

function economyGovernanceTypeLabel(type) {
  if (type === "scam_address_label") return "詐騙地址標記";
  if (type === "freeze_wallet_address") return "治理凍結地址";
  if (type === "unfreeze_wallet_address") return "治理解除凍結";
  if (type === "emergency_recovery_branch") return "緊急 recovery branch";
  return String(type || "-");
}

function economyGovernanceActionLabel(action) {
  const labels = {
    MARK_SCAM: "標記詐騙",
    FREEZE_ADDRESS: "凍結地址",
    UNFREEZE_ADDRESS: "解除凍結",
    ROLLBACK_BRANCH: "Rollback 分支",
    EMERGENCY_LOCKDOWN: "緊急鎖定",
    AUTO_BURN_POLICY: "自動銷毀政策",
    MINT_REQUEST: "Mint 申請",
    TREASURY_TRANSFER: "官方撥款",
    EXCHANGE_FUND_REPLENISH: "撥補交易所基金",
    CONTEST_REWARD_PAYOUT: "競賽獎金",
    TREASURY_SIGNER_CHANGE: "官方簽署者變更",
    PARAMETER_CHANGE: "參數變更",
    SUPPLY_EXPANSION_REQUEST: "憲法級增發條款",
    FEATURE_ACTIVATION: "功能啟用",
    HARD_FORK_ACCEPTANCE: "Hard fork 接受",
  };
  return labels[String(action || "").toUpperCase()] || economyGovernanceTypeLabel(action);
}

function economyGovernanceCanManage() {
  return currentUser === "root" || (typeof clientRoleRank === "function" && clientRoleRank(currentRole || "user") >= clientRoleRank("manager"));
}

function economyCurrentMemberLevel() {
  const effective = $("sidebar-effective-level")?.dataset?.effectiveLevel || "";
  const level = $("sidebar-current-level")?.dataset?.memberLevel || "";
  const raw = String(effective || level || "").split("/")[0].trim().toLowerCase();
  if (["newbie", "normal", "trusted", "vip", "restricted", "suspended"].includes(raw)) return raw;
  return "";
}

function economyGovernanceCanProposePublic() {
  if (economyGovernanceCanManage()) return true;
  const rank = { suspended: -2, restricted: -1, newbie: 0, normal: 1, trusted: 2, vip: 3 };
  const level = economyCurrentMemberLevel() || "normal";
  return (rank[level] || 0) >= rank.trusted;
}

function economyGovernanceCategoryForProposal(proposal = {}) {
  if (String(proposal.reference || "").startsWith("transaction_dispute:")) return "dispute";
  const domain = String(proposal.governance_domain || "").toUpperCase();
  const action = String(proposal.action_type || proposal.proposal_type || "").toUpperCase();
  if (action === "MINT_REQUEST") return "mint";
  if (domain === "OFFICIAL_TREASURY" || ["TREASURY_TRANSFER", "EXCHANGE_FUND_REPLENISH", "CONTEST_REWARD_PAYOUT"].includes(action)) return "treasury";
  if (domain === "EMERGENCY_SECURITY" || ["ROLLBACK_BRANCH", "EMERGENCY_LOCKDOWN"].includes(action)) return "emergency";
  if (String(proposal?.payload?.proposal_type || "").toUpperCase() === "SUPPLY_EXPANSION_REQUEST") return "policy";
  if (domain === "PROTOCOL_PARAMETER" || domain === "ADMIN_POLICY" || ["PARAMETER_CHANGE", "SUPPLY_EXPANSION_REQUEST", "FEATURE_ACTIVATION", "AUTO_BURN_POLICY", "TREASURY_SIGNER_CHANGE", "HARD_FORK_ACCEPTANCE"].includes(action)) return "policy";
  return "public";
}

function economyProposalUuidsForDispute(row = {}) {
  return [
    row.governance_proposal_uuid,
    row.address_risk_proposal_uuid,
    row.address_freeze_proposal_uuid,
  ].map((item) => String(item || "").trim()).filter(Boolean);
}

function setEconomyGovernanceCategory(category) {
  const next = ["all", "dispute", "public", "emergency", "treasury", "mint", "policy"].includes(String(category || ""))
    ? String(category || "")
    : "all";
  economyGovernanceCategory = next;
  const select = $("economy-governance-category-select");
  if (select && select.value !== next) select.value = next;
}

function setEconomyGovernanceStatusFilter(status) {
  const next = ["review", "voting", "closed"].includes(String(status || ""))
    ? String(status || "")
    : "review";
  economyGovernanceStatusFilter = next;
  document.querySelectorAll("[data-governance-status-filter]").forEach((btn) => {
    const active = String(btn.dataset.governanceStatusFilter || "") === next;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function economyGovernanceStatusBucket(proposal = {}) {
  const rawStatus = String(proposal.status || "").trim().toLowerCase();
  const lifecycle = String(proposal.lifecycle_status || "").trim().toUpperCase();
  if (rawStatus === "voting" || lifecycle === "VOTING") return "voting";
  if (
    ["executed", "failed", "rejected", "vetoed", "expired", "cancelled", "canceled"].includes(rawStatus)
    || ["EXECUTED", "FAILED", "REJECTED", "VETOED", "EXPIRED", "CANCELLED", "CANCELED"].includes(lifecycle)
  ) {
    return "closed";
  }
  return "review";
}

function economyGovernanceStatusFilterLabel(status) {
  if (status === "voting") return "投票中";
  if (status === "closed") return "已結案";
  return "審核中";
}

function economyGovernanceSignerAddress(proposal = {}) {
  const policy = proposal.multisig?.policy || {};
  if (policy.current_signer_wallet_address) return String(policy.current_signer_wallet_address || "").trim().toLowerCase();
  const signers = Array.isArray(policy.signers) ? policy.signers : [];
  const signer = signers.find((item) => Number(item.user_id || 0) === Number(currentUserId || 0));
  return String(signer?.wallet_address || "").trim().toLowerCase();
}

function economyGovernanceProgress(proposal = {}) {
  const yes = Number(proposal.yes_count || 0);
  const no = Number(proposal.no_count || 0);
  const abstain = Number(proposal.abstain_count || 0);
  const quorum = Number(proposal.quorum_count || 0);
  const eligible = Number(proposal.eligible_voter_count || 0);
  const approval = (Number(proposal[`approval_${ECONOMY_GOV_RATE_UNIT_SUFFIX}`] || 0) / 100).toFixed(2);
  return `YES ${yes} / NO ${no} / ABSTAIN ${abstain} · quorum ${yes + no + abstain}/${quorum} of ${eligible} · approval ${approval}%`;
}

function economyGovernanceTimeline(proposal = {}) {
  const domain = String(proposal.governance_domain || "");
  const status = String(proposal.lifecycle_status || proposal.status || "").toUpperCase();
  const steps = ["REVIEW", "VOTING", "PASSED", "TIMELOCK", domain === "OFFICIAL_TREASURY" ? "MULTISIG" : "EXECUTE", "EXECUTED"];
  return steps.map((step) => step === status || (status === "QUEUED" && step === "TIMELOCK") ? `[${step}]` : step).join(" -> ");
}

function economyGovernanceReadiness(proposal = {}) {
  const readiness = proposal.execution_readiness && typeof proposal.execution_readiness === "object" ? proposal.execution_readiness : {};
  const marks = [
    ["quorum", readiness.quorum_reached],
    ["vote", readiness.vote_succeeded],
    ["timelock", readiness.timelock_finished],
    ["payload", readiness.payload_verified],
    ["multisig", readiness.multisig_ready],
  ];
  return marks.map(([label, ok]) => `${ok ? "OK" : "WAIT"} ${label}`).join(" · ");
}

function economyRenderEvidenceRefs(refs = []) {
  const list = Array.isArray(refs) ? refs : [];
  if (!list.length) return "<span class=\"drive-card-sub\">未提供佐證 refs。</span>";
  return `<ul class="drive-card-sub" style="margin:.25rem 0 .35rem 1.1rem;">${list.map((item) => `<li>${sanitize(item)}</li>`).join("")}</ul>`;
}

function economyRenderDisputeGovernanceMaterials(payload = {}) {
  const victimStatement = String(payload.victim_statement || "").trim();
  const victimEvidence = Array.isArray(payload.victim_evidence_refs) ? payload.victim_evidence_refs : [];
  const claims = Array.isArray(payload.victim_claims) ? payload.victim_claims : [];
  const reply = payload.counterparty_reply && typeof payload.counterparty_reply === "object" ? payload.counterparty_reply : {};
  const hasReply = Boolean(String(reply.statement || "").trim());
  if (!victimStatement && !victimEvidence.length && !claims.length && !hasReply) return "";
  const claimRows = claims.map((claim) => `
    <div class="drive-card-sub">
      From claim ${sanitize(formatEconomyWalletAddressWithManagerLabel(claim.wallet_address || ""))} · ${formatEconomyPointsValue(claim.claim_amount_points || 0)} 點 · proof ${claim.address_signature_verified ? "ok" : "missing"}
    </div>
  `).join("");
  return `
    <div class="economy-dispute-governance-materials" style="margin:.45rem 0;padding:.55rem;border:1px solid rgba(255,255,255,.12);border-radius:8px;background:rgba(0,0,0,.12);">
      <div class="drive-card-sub" style="font-weight:700;color:var(--text);">疑義交易雙方材料</div>
      ${victimStatement ? `<div class="drive-card-sub">From 主張：${sanitize(victimStatement)}</div>` : ""}
      ${claimRows}
      <div class="drive-card-sub">From 佐證：</div>
      ${economyRenderEvidenceRefs(victimEvidence)}
      ${hasReply ? `
        <div class="drive-card-sub">To 回覆：${sanitize(reply.statement || "")}</div>
        <div class="drive-card-sub">To 地址 ${sanitize(formatEconomyWalletAddressWithManagerLabel(reply.wallet_address || ""))} · proof ${reply.address_signature_verified ? "ok" : "missing"} · ${sanitize(reply.reply_created_at || "")}</div>
        <div class="drive-card-sub">To 佐證：</div>
        ${economyRenderEvidenceRefs(reply.evidence_refs || [])}
      ` : `<div class="drive-card-sub">To 尚未回覆；投票者應將未回覆狀態納入判斷。</div>`}
    </div>
  `;
}

function renderEconomyGovernanceFromCache() {
  renderEconomyGovernance({ proposals: Array.from(economyGovernanceProposalCache.values()) });
}

function toggleEconomyGovernanceProposal(proposalUuid) {
  const uuid = String(proposalUuid || "").trim();
  if (!uuid) return;
  if (economyExpandedGovernanceProposalUuids.has(uuid)) {
    economyExpandedGovernanceProposalUuids.delete(uuid);
  } else {
    economyExpandedGovernanceProposalUuids.add(uuid);
  }
  renderEconomyGovernanceFromCache();
}

function economyRenderGovernanceProposalCard(proposal = {}, { nested = false } = {}) {
  const proposalUuid = String(proposal.proposal_uuid || "").trim();
  const status = String(proposal.status || "");
  const target = proposal.target_wallet_address || proposal.incident_tx_hash || "";
  const targetDisplay = String(target || "").startsWith("pc1")
    ? formatEconomyWalletAddressWithManagerLabel(target, { short: false })
    : target;
  const vote = proposal.user_vote?.vote ? `你已投 ${proposal.user_vote.vote}` : "尚未投票";
  const expanded = proposalUuid && economyExpandedGovernanceProposalUuids.has(proposalUuid);
  const multisig = proposal.multisig && typeof proposal.multisig === "object" ? proposal.multisig : {};
  const multisigText = multisig.required
    ? `multisig ${Number(multisig.signature_count || 0)}/${Number(multisig.threshold || 0)} · weight ${Number(multisig.signature_weight || 0)}/${Number(multisig.threshold_weight || 0)}${multisig.ready ? " ready" : ""}`
    : "multisig not required";
  const signerAddress = economyGovernanceSignerAddress(proposal);
  const signerMeta = Array.isArray(multisig.policy?.signers)
    ? multisig.policy.signers.find((item) => String(item.wallet_address || "").trim().toLowerCase() === signerAddress)
    : null;
  const rootVeto = currentUser === "root" && proposal.root_veto_allowed && !proposal.root_veto_used && !["executed", "cancelled", "expired"].includes(status)
    ? `<button class="btn btn-danger btn-sm" type="button" data-governance-veto="${sanitize(proposal.proposal_uuid || "")}">VETO</button>`
    : "";
  const sponsor = economyGovernanceCanManage() && proposal.lifecycle_status === "REVIEW"
    ? `<button class="btn btn-sm" type="button" data-governance-sponsor="${sanitize(proposal.proposal_uuid || "")}">Sponsor</button>`
    : "";
  const cancel = economyGovernanceCanManage() && !["executed", "cancelled", "expired"].includes(status)
    ? `<button class="btn btn-sm" type="button" data-governance-cancel="${sanitize(proposal.proposal_uuid || "")}">取消</button>`
    : "";
  const multisigSign = economyGovernanceCanManage() && multisig.required && !multisig.ready && signerAddress && status === "passed"
    ? `<button class="btn btn-sm" type="button" data-governance-multisig-sign="${sanitize(proposal.proposal_uuid || "")}" data-signer-wallet="${sanitize(signerAddress)}" data-target-wallet="${sanitize(proposal.target_wallet_address || signerAddress)}" data-requested-amount="${Number(proposal.requested_amount || 1)}" data-payload-hash="${sanitize(proposal.execution_payload_hash || "")}" data-custody-mode="${sanitize(signerMeta?.custody_mode || "")}" data-wallet-type="${sanitize(signerMeta?.wallet_type || "")}">簽署多簽</button>`
    : "";
  const rootExecute = economyGovernanceCanManage() && proposal.executable
    ? `<button class="btn btn-danger btn-sm" type="button" data-governance-execute="${sanitize(proposal.proposal_uuid || "")}">執行</button>`
    : "";
  const votingButtons = status === "voting" && proposal.lifecycle_status === "VOTING"
    ? `
      <button class="btn btn-sm" type="button" data-governance-vote="yes" data-proposal-uuid="${sanitize(proposal.proposal_uuid || "")}">YES</button>
      <button class="btn btn-sm" type="button" data-governance-vote="no" data-proposal-uuid="${sanitize(proposal.proposal_uuid || "")}">NO</button>
      <button class="btn btn-sm" type="button" data-governance-vote="abstain" data-proposal-uuid="${sanitize(proposal.proposal_uuid || "")}">ABSTAIN</button>
    `
    : "";
  const proposalPayload = proposal.payload && typeof proposal.payload === "object" ? proposal.payload : {};
  const recoveryOptions = proposalPayload.recovery_options && typeof proposalPayload.recovery_options === "object"
    ? Object.keys(proposalPayload.recovery_options).join(" / ")
    : "";
  const claims = Array.isArray(proposalPayload.victim_claims) ? proposalPayload.victim_claims : [];
  const disputeMaterials = economyRenderDisputeGovernanceMaterials(proposalPayload);
  const recoveryDetail = String(proposal.action_type || "").toUpperCase() === "ROLLBACK_BRANCH"
    ? `<div class="drive-card-sub">recovery ${sanitize(proposalPayload.recovery_strategy || proposalPayload.selected_recovery_strategy || "-")} · options ${sanitize(recoveryOptions || "-")} · claims ${claims.length}</div>`
    : "";
  const actionLabel = String(proposalPayload.proposal_type || "").toUpperCase() === "SUPPLY_EXPANSION_REQUEST"
    ? economyGovernanceActionLabel("SUPPLY_EXPANSION_REQUEST")
    : economyGovernanceActionLabel(proposal.action_type || proposal.proposal_type);
  const actionPanel = [votingButtons, sponsor, multisigSign, rootVeto, cancel, rootExecute].filter(Boolean).join("");
  return `
    <div class="economy-governance-proposal-card${nested ? " economy-governance-inline-proposal" : ""}">
      <div class="drive-file-row economy-governance-proposal-toggle" role="button" tabindex="0" aria-expanded="${expanded ? "true" : "false"}" data-governance-toggle-proposal="${sanitize(proposalUuid)}">
        <div>
          <strong>${sanitize(actionLabel)} · ${sanitize(proposal.governance_domain || "-")} · ${sanitize(proposal.lifecycle_status || economyGovernanceStatusLabel(status))}</strong>
          <div class="drive-card-sub">${sanitize(proposal.reason || "")}</div>
          <div class="drive-card-sub">${sanitize(economyGovernanceProgress(proposal))}</div>
          <div class="drive-card-sub">timeline ${sanitize(economyGovernanceTimeline(proposal))}</div>
          <div class="drive-card-sub">readiness ${sanitize(economyGovernanceReadiness(proposal))}</div>
          ${recoveryDetail}
          <div class="drive-card-sub">severity ${sanitize(proposal.proposal_severity || "NORMAL")} · ${sanitize(multisigText)} · veto ${proposal.root_veto_allowed ? "root allowed" : "not allowed"}</div>
          ${proposal.execution_payload_hash ? `<div class="drive-card-sub">payload hash <span class="economy-ledger-hash">${sanitize(proposal.execution_payload_hash)}</span></div>` : ""}
          <div class="drive-card-sub">${sanitize(proposal.impact_scope || "")}${proposal.risk_summary ? " · " + sanitize(proposal.risk_summary) : ""}</div>
          <div class="economy-ledger-hash">${sanitize(targetDisplay || proposal.proposal_uuid || "")}</div>
          <div class="drive-card-sub">timelock ${sanitize(proposal.timelock_until || "-")} · expires ${sanitize(proposal.expires_at || "-")} · ${sanitize(vote)}</div>
        </div>
        <div class="drive-file-actions">
          <span class="btn btn-sm" aria-hidden="true">${expanded ? "收合操作" : "展開投票/操作"}</span>
        </div>
      </div>
      ${expanded ? `
        <div class="economy-governance-proposal-action-panel" style="margin:.35rem 0 .85rem 1rem;padding:.65rem;border-left:3px solid rgba(255,255,255,.18);background:rgba(255,255,255,.04);">
          <div class="drive-card-sub" style="margin-bottom:.45rem;">提案投票 / 執行操作</div>
          ${disputeMaterials}
          <div class="drive-file-actions" style="justify-content:flex-start;gap:.45rem;flex-wrap:wrap;">
            ${actionPanel || `<span class="drive-card-sub">目前沒有可執行操作。</span>`}
          </div>
        </div>
      ` : ""}
    </div>
  `;
}

function parseEconomyGovernanceLines(value) {
  return String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function parseEconomyGovernanceClaims(value) {
  const raw = String(value || "").trim();
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) throw new Error("claims JSON must be an array");
    return parsed;
  } catch (err) {
    throw new Error(`Claims JSON 格式錯誤：${err.message || err}`);
  }
}

function syncGovernanceTreasuryDestination() {
  const action = String($("economy-governance-treasury-action")?.value || "").trim().toUpperCase();
  const input = $("economy-governance-treasury-destination");
  if (!input) return;
  if (action === "EXCHANGE_FUND_REPLENISH") {
    const address = economyFundAddressCache.exchange_fund || "";
    if (address && address !== "-") input.value = address;
    input.readOnly = true;
    input.placeholder = "EXCHANGE Fund system address";
  } else {
    input.readOnly = false;
    input.placeholder = "pc1...";
  }
}

function renderEconomyTreasuryAnalysis(payload) {
  const analysis = payload && typeof payload === "object" ? payload : {};
  const summary = analysis.summary && typeof analysis.summary === "object" ? analysis.summary : {};
  const settlement = analysis.settlement_policy && typeof analysis.settlement_policy === "object" ? analysis.settlement_policy : {};
  setEconomyText("economy-treasury-analysis-updated-at", analysis.generated_at ? `最後更新 ${analysis.generated_at}` : "等待即時資料");
  const summaryEl = $("economy-treasury-analysis-summary");
  if (summaryEl) {
    const tone = analysis.status === "red" ? "bad" : (analysis.status === "yellow" ? "warn" : "good");
    summaryEl.innerHTML = [
      economyFormulaCard("收支狀態", String(analysis.status || "unknown").toUpperCase(), tone),
      economyFormulaCard("官方錢包", `${formatEconomyPointsValue(summary.official_wallet_balance_points || 0)} 點`),
      economyFormulaCard("收入 / 支出", `${formatEconomyPointsValue(summary.income_total_points || 0)} / ${formatEconomyPointsValue(summary.expense_total_points || 0)} 點`),
      economyFormulaCard("站內服務待結算", `${formatEconomyPointsValue(summary.pending_service_fee_points || 0)} 點`),
      economyFormulaCard("已批次結算", `${formatEconomyPointsValue(summary.settled_service_fee_points || 0)} 點`),
      economyFormulaCard("下一次批次差額", `${formatEconomyPointsValue(summary.next_service_fee_settlement_remaining_points || 0)} 點`),
    ].join("");
  }
  const serviceList = $("economy-treasury-service-fee-list");
  if (serviceList) {
    const items = Array.isArray(analysis.service_fee_items) ? analysis.service_fee_items : [];
    const recent = Array.isArray(analysis.recent_service_fee_settlements) ? analysis.recent_service_fee_settlements : [];
    const rows = [`
      <div class="drive-file-row">
        <div>
          <strong>站內服務費結算</strong>
          <div class="drive-card-sub">策略 ${sanitize(settlement.service_fee_layer || "-")} · 滿 ${formatEconomyPointsValue(settlement.threshold_points || 0)} 點批次 ${sanitize(settlement.actual_chain_transfer_action || "-")} → ${sanitize(settlement.actual_chain_transfer_destination_fund_key || "-")}</div>
          <div class="drive-card-sub">${sanitize(settlement.note || "")}</div>
        </div>
      </div>
    `];
    rows.push(...items.slice(0, 12).map((item) => `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(item.item_name || item.item_key || "-")}</strong>
          <div class="drive-card-sub">${sanitize(item.item_key || "")} · 已結算 ${formatEconomyPointsValue(item.settled_points || 0)} 點 · 待結算 ${formatEconomyPointsValue(item.reserved_points || 0)} 點 · ${Number(item.charge_count || 0)} 筆</div>
          <div class="drive-card-sub">最近活動 ${sanitize(item.last_activity_at || "-")}</div>
        </div>
      </div>
    `));
    if (recent.length) {
      rows.push(`
        <div class="drive-file-row">
          <div>
            <strong>最近實際鏈上批次轉帳</strong>
            <div class="drive-card-sub">${recent.slice(0, 4).map((row) => `${formatEconomyPointsValue(row.amount_points || 0)} 點 · ${shortEconomyWalletAddress(row.ledger_uuid || "")} · ${row.created_at || "-"}`).join("<br>")}</div>
          </div>
        </div>
      `);
    }
    serviceList.innerHTML = rows.join("") || `<div class="drive-empty">尚無站內服務費資料。</div>`;
  }
  const renderCategoryList = (id, title, rows, emptyText) => {
    const list = $(id);
    if (!list) return;
    const items = Array.isArray(rows) ? rows : [];
    list.innerHTML = items.length
      ? `<div class="drive-file-row"><div><strong>${sanitize(title)}</strong><div class="drive-card-sub">依官方 Treasury fund ledger 分類。</div></div></div>` + items.slice(0, 12).map((item) => `
          <div class="drive-file-row">
            <div>
              <strong>${sanitize(item.label || item.transaction_type || "-")} · ${formatEconomyPointsValue(item.amount_points || 0)} 點</strong>
              <div class="drive-card-sub">${sanitize(item.transaction_type || "-")} · ${Number(item.count || 0)} 筆 · ${sanitize(item.latest_at || "-")}${item.ledger_only ? " · legacy ledger 補列" : ""}</div>
            </div>
          </div>
        `).join("")
      : `<div class="drive-empty">${sanitize(emptyText)}</div>`;
  };
  renderCategoryList("economy-treasury-income-list", "官方 Treasury 收入", analysis.income_categories, "目前沒有可見官方 Treasury 收入。");
  renderCategoryList("economy-treasury-expense-list", "官方 Treasury 支出", analysis.expense_categories, "目前沒有可見官方 Treasury 支出。");
  const pricingList = $("economy-treasury-pricing-fit-list");
  if (pricingList) {
    const fit = Array.isArray(analysis.pricing_fit) ? analysis.pricing_fit : [];
    const manager = analysis.perspectives?.manager || {};
    pricingList.innerHTML = `
      <div class="drive-file-row">
        <div>
          <strong>服務費定價擬合</strong>
          <div class="drive-card-sub">${sanitize(manager.summary || "以低額高頻服務費、投幣抽成、曝光型功能費支撐官方 Treasury；支出仍走治理與多簽。")}</div>
        </div>
      </div>
      ${fit.slice(0, 10).map((item) => {
        const delta = item.delta_points === null || item.delta_points === undefined ? "尚未建立" : `${Number(item.delta_points || 0) >= 0 ? "+" : ""}${Number(item.delta_points || 0)} 點`;
        return `<div class="drive-file-row">
          <div>
            <strong>${sanitize(item.item_name || item.item_key || "-")} · 建議 ${formatEconomyPointsValue(item.recommended_points || 0)} 點</strong>
            <div class="drive-card-sub">${sanitize(item.item_key || "")} · 目前 ${item.current_points === null || item.current_points === undefined ? "未設定" : `${formatEconomyPointsValue(item.current_points)} 點`} · 差額 ${sanitize(delta)}</div>
            <div class="drive-card-sub">${sanitize(item.rationale || "")}</div>
          </div>
        </div>`;
      }).join("")}
    `;
  }
}

function renderEconomyTreasurySignerCenter(payload = null) {
  const card = $("economy-treasury-signer-center-card");
  if (!card) return;
  if (!economyGovernanceCanManage()) {
    card.style.display = "none";
    return;
  }
  const data = payload && typeof payload === "object" ? payload : {};
  const wallet = data.official_wallet && typeof data.official_wallet === "object" ? data.official_wallet : {};
  const fundAddresses = data.fund_addresses && typeof data.fund_addresses === "object" ? data.fund_addresses : {};
  if (Object.keys(fundAddresses).length) {
    economyFundAddressCache = {
      ...economyFundAddressCache,
      ...Object.fromEntries(Object.entries(fundAddresses).map(([key, value]) => [key, String(value || "").trim()])),
    };
    syncGovernanceTreasuryDestination();
  }
  const policy = data.policy && typeof data.policy === "object" ? data.policy : {};
  const signers = Array.isArray(policy.signers) ? policy.signers : [];
  const proposals = Array.isArray(data.pending_proposals) ? data.pending_proposals : [];
  const signable = Array.isArray(data.signable) ? data.signable : [];
  card.style.display = "";
  setEconomyText("economy-treasury-signer-center-status", data.policy_error ? `多簽政策異常：${data.policy_error}` : "官方財庫由 manager+ signer threshold 共同控制；root 只在官方財庫案具 veto。");
  setEconomyText("economy-treasury-signer-official-balance", `${formatEconomyPointsValue(wallet.balance || 0)} 點`);
  setEconomyText("economy-treasury-signer-official-address", wallet.address || "-");
  setEconomyText("economy-treasury-signer-threshold", `${Number(policy.threshold || 0)}/${Number(policy.signer_count || signers.length || 0)} · weight ${Number(policy.threshold_weight || 0)}/${Number(policy.total_weight || 0)}`);
  setEconomyText("economy-treasury-signer-policy", `${sanitize(policy.wallet_type || "official_treasury_multisig")} · ${sanitize(policy.policy_version || "-")}`);
  setEconomyText("economy-treasury-signer-pending-count", `${signable.length} / ${proposals.length}`);
  setEconomyText("economy-treasury-signer-branch", `branch ${data.canonical_branch || "-"}`);
  renderEconomyTreasuryAnalysis(data.treasury_analysis || null);
  const signerList = $("economy-treasury-signer-list");
  if (signerList) {
    signerList.innerHTML = signers.length
      ? signers.map((signer) => `
          <div class="drive-file-row">
            <div>
              <strong>${sanitize(signer.role || "-")} · weight ${Number(signer.weight || 0)}</strong>
              <div class="drive-card-sub">${sanitize(signer.wallet_type || "")} · ${sanitize(signer.custody_mode || "")} · ${sanitize(signer.device_id || "")}</div>
              <button class="economy-ledger-hash economy-explorer-address" type="button" data-explorer-query="${sanitize(signer.wallet_address || "")}">${sanitize(signer.wallet_address || "-")}</button>
            </div>
          </div>
        `).join("")
      : `<div class="drive-empty">尚無可用官方 signer；至少需要兩個 manager+ signer wallet。</div>`;
  }
  const pendingList = $("economy-treasury-signer-pending-list");
  if (pendingList) {
    pendingList.innerHTML = signable.length
      ? signable.map((item) => `
          <div class="drive-file-row">
            <div>
              <strong>${sanitize(economyGovernanceActionLabel(item.action_type))} · ${Number(item.signature_count || 0)}/${Number(item.threshold || 0)} · weight ${Number(item.signature_weight || 0)}/${Number(item.threshold_weight || 0)}</strong>
              <div class="drive-card-sub">timelock ${sanitize(item.timelock_until || "-")} · ${sanitize(shortEconomyWalletAddress(item.target_wallet_address || ""))} · ${formatEconomyPointsValue(item.requested_amount || 0)} 點</div>
              <div class="drive-card-sub">signing hash ${sanitize(item.signing_payload_hash || "-")} · payload ${sanitize(item.execution_payload_hash || "-")}</div>
              <div class="economy-ledger-hash">${sanitize(item.proposal_uuid || "")}</div>
            </div>
          </div>
        `).join("")
      : `<div class="drive-empty">目前沒有需要你簽署的官方財庫提案。</div>`;
  }
  card.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    if (btn.dataset.explorerBound === "1") return;
    btn.dataset.explorerBound = "1";
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      setEconomyActivePage("explorer");
      searchEconomyExplorer(query);
    });
  });
}

async function loadEconomyTreasurySignerCenter({ silent = false } = {}) {
  if (!currentUser || !economyChainEnabled() || !economyGovernanceCanManage()) {
    renderEconomyTreasurySignerCenter(null);
    return false;
  }
  try {
    const json = await fetchEconomyJson("/admin/points/governance/treasury-signer-center?limit=50");
    economyTreasurySignerCenterCache = json;
    renderEconomyTreasurySignerCenter(json);
    return true;
  } catch (err) {
    economyTreasurySignerCenterCache = null;
    renderEconomyTreasurySignerCenter({ policy_error: err.message || "官方財庫多簽讀取失敗" });
    if (!silent) economyGovernanceMsg(err.message || "官方財庫多簽讀取失敗", false);
    return false;
  }
}

function renderEconomyGovernance(payload = {}) {
  updateEconomyOfficialHotWalletLabels(payload.official_hot_wallet_labels);
  const proposals = Array.isArray(payload.proposals) ? payload.proposals : [];
  economyGovernanceProposalCache = new Map(proposals.map((proposal) => [String(proposal.proposal_uuid || ""), proposal]));
  setEconomyGovernanceCategory(economyGovernanceCategory);
  setEconomyGovernanceStatusFilter(economyGovernanceStatusFilter);
  const selectedCase = $("economy-governance-selected-case");
  if (selectedCase) {
    selectedCase.textContent = economySelectedDisputeUuid
      ? `已選取疑義案件 ${shortEconomyWalletAddress(economySelectedDisputeUuid)}；提案/投票會直接折疊顯示在該案件下方。`
      : "未選取疑義交易案件；點選上方案件後，該案件的治理提案會直接展開在案件下方。";
  }
  const showCreateGroup = (category) => economyGovernanceCategory === "all" || economyGovernanceCategory === category;
  const publicTools = $("economy-public-governance-create-details");
  if (publicTools) publicTools.style.display = economyGovernanceCanProposePublic() && showCreateGroup("public") ? "" : "none";
  const publicHint = $("economy-public-governance-hint");
  if (publicHint) {
    publicHint.textContent = economyGovernanceCanManage()
      ? "manager+ 可直接建立公共治理提案；root 沒有公共案 veto。"
      : "trusted 以上會員可送出公共提案；一般會員需先提升信任等級。一般用戶提案會進 REVIEW，需 manager+ sponsor 才開放投票。";
  }
  const treasuryTools = $("economy-governance-treasury-create-details");
  if (treasuryTools) treasuryTools.style.display = economyGovernanceCanManage() && showCreateGroup("treasury") ? "" : "none";
  const mintTools = $("economy-governance-mint-create-details");
  if (mintTools) mintTools.style.display = economyGovernanceCanManage() && showCreateGroup("mint") ? "" : "none";
  const policyTools = $("economy-governance-policy-create-details");
  if (policyTools) policyTools.style.display = (economyGovernanceCanManage() || economyGovernanceCanProposePublic()) && showCreateGroup("policy") ? "" : "none";
  const emergencyTools = $("economy-governance-emergency-create-details");
  if (emergencyTools) emergencyTools.style.display = economyGovernanceCanManage() && showCreateGroup("emergency") ? "" : "none";
  syncGovernanceTreasuryDestination();
  setEconomyText("economy-governance-proposal-count", String(proposals.length));
  const reviewCount = proposals.filter((item) => economyGovernanceStatusBucket(item) === "review").length;
  const votingCount = proposals.filter((item) => economyGovernanceStatusBucket(item) === "voting").length;
  const closedCount = proposals.filter((item) => economyGovernanceStatusBucket(item) === "closed").length;
  setEconomyText("economy-governance-open-count", String({ review: reviewCount, voting: votingCount, closed: closedCount }[economyGovernanceStatusFilter] || 0));
  const statusSmall = $("economy-governance-open-count")?.nextElementSibling;
  if (statusSmall) statusSmall.textContent = `${economyGovernanceStatusFilterLabel(economyGovernanceStatusFilter)} · 審核 ${reviewCount} / 投票 ${votingCount} / 結案 ${closedCount}`;
  updateEconomyGovernanceOverviewCounts(proposals);
  const list = $("economy-governance-list");
  if (!list) return;
  const filteredProposals = proposals.filter((proposal) => {
    if (economyGovernanceStatusBucket(proposal) !== economyGovernanceStatusFilter) return false;
    if (String(proposal.reference || "").startsWith("transaction_dispute:") && economyGovernanceCategory !== "dispute") return false;
    if (economyGovernanceCategory === "all") return true;
    if (economyGovernanceCategory === "dispute") {
      return economySelectedDisputeProposalUuids.has(String(proposal.proposal_uuid || ""));
    }
    return economyGovernanceCategoryForProposal(proposal) === economyGovernanceCategory;
  });
  if (!filteredProposals.length) {
    if (economyGovernanceCategory === "dispute") {
      list.innerHTML = economySelectedDisputeUuid
        ? `<div class="drive-empty">此疑義案件在「${economyGovernanceStatusFilterLabel(economyGovernanceStatusFilter)}」沒有治理提案；案件卡片下方會顯示該案件全部提案。</div>`
        : `<div class="drive-empty">請先在疑義交易案件列表點選案件，再查看該案件的治理提案 / 投票。</div>`;
    } else {
      list.innerHTML = `<div class="drive-empty">目前「${economyGovernanceStatusFilterLabel(economyGovernanceStatusFilter)}」沒有此分類的 PointsChain governance proposal</div>`;
    }
    if (economyTransactionDisputeCache.length) renderEconomyTransactionDisputes({ disputes: economyTransactionDisputeCache });
    return;
  }
  list.innerHTML = filteredProposals.map((proposal) => economyRenderGovernanceProposalCard(proposal)).join("");
  bindEconomyGovernanceEvents(list);
  if (economyTransactionDisputeCache.length) renderEconomyTransactionDisputes({ disputes: economyTransactionDisputeCache });
}

async function loadEconomyGovernance({ silent = false } = {}) {
  if (!currentUser || !economyChainEnabled()) {
    renderEconomyGovernance({ proposals: [] });
    renderEconomyTreasurySignerCenter(null);
    return false;
  }
  try {
    const json = await fetchEconomyJson("/points/governance/proposals?limit=50");
    renderEconomyGovernance(json);
    if (economyGovernanceCanManage()) await loadEconomyTreasurySignerCenter({ silent: true });
    else renderEconomyTreasurySignerCenter(null);
    if (!silent) economyGovernanceMsg("治理提案已更新。");
    return true;
  } catch (err) {
    if (!silent) economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "治理提案讀取失敗" });
    return false;
  }
}

async function createGovernanceAddressRiskProposal() {
  const address = String($("economy-governance-scam-address")?.value || "").trim();
  const reason = String($("economy-governance-scam-reason")?.value || "").trim();
  const evidence = String($("economy-governance-scam-evidence")?.value || "").trim();
  try {
    const json = await fetchEconomyJson("/points/governance/address-risk", {
      method: "POST",
      body: JSON.stringify({ wallet_address: address, reason, evidence }),
    });
    economyNotifySuccess(`已建立詐騙地址標記提案：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "詐騙地址標記提案失敗" });
  }
}

async function createGovernanceRecoveryBranchProposal() {
  const incident = String($("economy-governance-branch-incident")?.value || "").trim();
  const incidentRefs = String($("economy-governance-branch-incident-refs")?.value || "").trim();
  const baseBlock = String($("economy-governance-branch-base-block")?.value || "").trim();
  const recoveryStrategy = String($("economy-governance-branch-strategy")?.value || "tainted_remainder_return").trim();
  const lossCause = String($("economy-governance-branch-loss-cause")?.value || "unknown").trim();
  const reason = String($("economy-governance-branch-reason")?.value || "").trim();
  const excluded = String($("economy-governance-branch-excluded")?.value || "").trim();
  const victimStatement = String($("economy-governance-branch-victim-statement")?.value || "").trim();
  const victimEvidence = String($("economy-governance-branch-victim-evidence")?.value || "").trim();
  let victimClaims = [];
  try {
    victimClaims = parseEconomyGovernanceClaims($("economy-governance-branch-claims")?.value || "");
  } catch (err) {
    economyGovernanceMsg(err.message || "Claims JSON 格式錯誤", false);
    return;
  }
  try {
    const json = await fetchEconomyJson("/admin/points/governance/recovery-branch", {
      method: "POST",
      body: JSON.stringify({
        incident_tx_hash: incident,
        incident_tx_hashes: parseEconomyGovernanceLines(incidentRefs),
        base_block_number: baseBlock || null,
        reason,
        excluded_tx_hashes: excluded,
        recovery_strategy: recoveryStrategy,
        loss_cause: lossCause,
        victim_statement: victimStatement,
        victim_evidence_refs: parseEconomyGovernanceLines(victimEvidence),
        victim_claims: victimClaims,
      }),
    });
    economyNotifySuccess(`已建立緊急 recovery branch 提案：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "緊急 recovery branch 提案失敗" });
  }
}

async function createGovernanceEmergencyLockdownProposal() {
  const scope = String($("economy-governance-lockdown-scope")?.value || "").trim();
  const reason = String($("economy-governance-lockdown-reason")?.value || "").trim();
  try {
    const json = await fetchEconomyJson("/admin/points/governance/policy", {
      method: "POST",
      body: JSON.stringify({
        action_type: "EMERGENCY_LOCKDOWN",
        title: "緊急鎖定提案",
        reason,
        proposal_severity: "CRITICAL",
        impact_scope: scope,
        risk_summary: "Temporarily pauses high-risk operations while incident review proceeds.",
        payload: { lockdown_scope: scope, description: reason },
        reference: economyRequestId("emergency_lockdown"),
      }),
    });
    economyNotifySuccess(`已建立緊急鎖定提案：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "緊急鎖定提案失敗" });
  }
}

async function createGovernanceWalletFreezeProposal() {
  const address = String($("economy-governance-freeze-address")?.value || "").trim();
  const action = String($("economy-governance-freeze-action")?.value || "freeze").trim();
  const reason = String($("economy-governance-freeze-reason")?.value || "").trim();
  const evidence = String($("economy-governance-freeze-evidence")?.value || "").trim();
  try {
    const json = await fetchEconomyJson("/points/governance/wallet-freeze", {
      method: "POST",
      body: JSON.stringify({ wallet_address: address, action, reason, evidence }),
    });
    economyNotifySuccess(`已建立${action === "unfreeze" ? "解凍" : "凍結"}提案：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "錢包凍結治理提案失敗" });
  }
}

async function createGovernanceTreasuryProposal() {
  const actionType = String($("economy-governance-treasury-action")?.value || "TREASURY_TRANSFER").trim();
  syncGovernanceTreasuryDestination();
  if (actionType === "EXCHANGE_FUND_REPLENISH" && !String(economyFundAddressCache.exchange_fund || "").trim()) {
    await loadEconomyTreasurySignerCenter({ silent: true });
    syncGovernanceTreasuryDestination();
  }
  const destination = actionType === "EXCHANGE_FUND_REPLENISH"
    ? String(economyFundAddressCache.exchange_fund || $("economy-governance-treasury-destination")?.value || "").trim()
    : String($("economy-governance-treasury-destination")?.value || "").trim();
  const amount = Math.floor(Number($("economy-governance-treasury-amount")?.value || 0));
  const reason = String($("economy-governance-treasury-reason")?.value || "").trim();
  if (!destination || !Number.isFinite(amount) || amount <= 0) {
    economyGovernanceMsg("請確認官方財庫提案的 To 錢包地址與 Value", false);
    return;
  }
  try {
    const json = await fetchEconomyJson("/admin/points/governance/treasury-transfer", {
      method: "POST",
      body: JSON.stringify({
        action_type: actionType,
        destination_wallet_address: destination,
        amount,
        reason,
        reference: economyRequestId("official_treasury_proposal"),
      }),
    });
    const proposalUuid = json.proposal?.proposal_uuid || json.proposal_uuid || "";
    economyNotifySuccess(`官方財庫提案已送出：${proposalUuid || actionType}；治理通過、timelock 與官方多簽簽合後才會執行。`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "官方財庫提案送出失敗" });
  }
}

async function createGovernanceMintRequestProposal() {
  const destination = String($("economy-governance-mint-destination")?.value || "official_treasury").trim();
  const amount = Math.floor(Number($("economy-governance-mint-amount")?.value || 0));
  const reason = String($("economy-governance-mint-reason")?.value || "").trim();
  if (!Number.isFinite(amount) || amount <= 0 || !reason) {
    economyGovernanceMsg("Mint 申請需要正數 Value 與 Reason。", false);
    return;
  }
  try {
    const json = await fetchEconomyJson("/admin/points/governance/mint-request", {
      method: "POST",
      body: JSON.stringify({
        destination_fund_key: destination,
        amount,
        reason,
        reference: economyRequestId("mint_request"),
      }),
    });
    economyNotifySuccess(`Mint 申請已送出：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "Mint 申請失敗" });
  }
}

async function createGovernancePolicyProposal() {
  const actionType = String($("economy-governance-policy-action")?.value || "PARAMETER_CHANGE").trim().toUpperCase();
  const key = String($("economy-governance-policy-key")?.value || "").trim();
  const value = String($("economy-governance-policy-value")?.value || "").trim();
  const reason = String($("economy-governance-policy-reason")?.value || "").trim();
  if (!key || !reason) {
    economyGovernanceMsg("政策提案需要 Key / Feature 與 Reason。", false);
    return;
  }
  if (actionType === "SUPPLY_EXPANSION_REQUEST") {
    const requestedDelta = Math.floor(Number(value || 0));
    if (!Number.isFinite(requestedDelta) || requestedDelta <= 0) {
      economyGovernanceMsg("憲法級增發條款需要在 Value 填入正數增發額。", false);
      return;
    }
    try {
      const json = await fetchEconomyJson("/admin/points/governance/supply-expansion", {
        method: "POST",
        body: JSON.stringify({
          destination_fund_key: key,
          requested_delta: requestedDelta,
          reason,
          financial_report: reason,
          risk_disclosure: "Monetary policy amendment dilutes all holders and only changes max_supply.",
          reference: economyRequestId("supply_expansion"),
        }),
      });
      economyNotifySuccess(`憲法級增發條款已送出：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
      await loadEconomyGovernance({ silent: true });
    } catch (err) {
      economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "憲法級增發條款送出失敗" });
    }
    return;
  }
  try {
    const json = await fetchEconomyJson("/admin/points/governance/policy", {
      method: "POST",
      body: JSON.stringify({
        action_type: actionType,
        title: economyGovernanceActionLabel(actionType),
        reason,
        payload: {
          parameter_key: actionType === "PARAMETER_CHANGE" ? key : "",
          parameter_value: actionType === "PARAMETER_CHANGE" ? value : "",
          feature_key: actionType === "FEATURE_ACTIVATION" ? key : "",
          burn_policy: actionType === "AUTO_BURN_POLICY" ? value : "",
          signer_change: actionType === "TREASURY_SIGNER_CHANGE" ? key : "",
          signer_change_value: actionType === "TREASURY_SIGNER_CHANGE" ? value : "",
          description: `${key}: ${value}`,
        },
        parameter_key: actionType === "PARAMETER_CHANGE" ? key : "",
        parameter_value: actionType === "PARAMETER_CHANGE" ? value : "",
        feature_key: actionType === "FEATURE_ACTIVATION" ? key : "",
        burn_policy: actionType === "AUTO_BURN_POLICY" ? value : "",
        description: `${key}: ${value}`,
        proposal_severity: actionType === "AUTO_BURN_POLICY" || actionType === "TREASURY_SIGNER_CHANGE" ? "HIGH" : "NORMAL",
        impact_scope: key,
        risk_summary: value,
        reference: economyRequestId("policy_proposal"),
      }),
    });
    economyNotifySuccess(`政策提案已送出：${json.proposal?.proposal_uuid || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "政策提案送出失敗" });
  }
}

async function voteEconomyGovernanceProposal(proposalUuid, vote) {
  const proposal = economyGovernanceProposalCache.get(String(proposalUuid || "")) || {};
  let recoveryChoice = "";
  if (String(proposal.action_type || "").toUpperCase() === "ROLLBACK_BRANCH" && vote === "yes") {
    const payload = proposal.payload && typeof proposal.payload === "object" ? proposal.payload : {};
    const options = payload.recovery_options && typeof payload.recovery_options === "object"
      ? Object.keys(payload.recovery_options)
      : ["tainted_remainder_return", "treasury_compensation", "exclude_tainted_descendants"];
    recoveryChoice = prompt(`請選擇本次 rollback 分支方案：${options.join(" / ")}`, payload.recovery_strategy || "tainted_remainder_return") || "";
    if (!recoveryChoice) return;
  }
  try {
    await fetchEconomyJson(`/points/governance/proposals/${encodeURIComponent(proposalUuid)}/vote`, {
      method: "POST",
      body: JSON.stringify({ vote, recovery_choice: recoveryChoice }),
    });
    economyNotifySuccess(`已投票 ${vote.toUpperCase()}。`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "治理投票失敗" });
  }
}

async function executeEconomyGovernanceProposal(proposalUuid) {
  if (!confirm("確認執行已通過的 PointsChain governance proposal？此操作只會套用治理結果，不會刪改舊 ledger。")) return;
  try {
    const json = await fetchEconomyJson(`/admin/points/governance/proposals/${encodeURIComponent(proposalUuid)}/execute`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    economyNotifySuccess(`治理提案已執行：${json.result?.action || ""}`, { msgFn: economyGovernanceMsg, label: "治理提案" });
    await Promise.all([loadEconomyGovernance({ silent: true }), loadEconomyRootReport()]);
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "治理提案執行失敗" });
  }
}

async function sponsorEconomyGovernanceProposal(proposalUuid) {
  try {
    await fetchEconomyJson(`/admin/points/governance/proposals/${encodeURIComponent(proposalUuid)}/sponsor`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    economyNotifySuccess("治理提案已 sponsor。", { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "治理 sponsor 失敗" });
  }
}

async function cancelEconomyGovernanceProposal(proposalUuid) {
  const reason = prompt("取消 / 作廢提案理由");
  if (reason === null) return;
  try {
    await fetchEconomyJson(`/admin/points/governance/proposals/${encodeURIComponent(proposalUuid)}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    economyNotifySuccess("治理提案已取消。", { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "治理提案取消失敗" });
  }
}

async function vetoEconomyGovernanceProposal(proposalUuid) {
  const reason = prompt("Root veto 理由");
  if (reason === null) return;
  try {
    await fetchEconomyJson(`/root/points/governance/proposals/${encodeURIComponent(proposalUuid)}/veto`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    economyNotifySuccess("治理提案已 veto。", { msgFn: economyGovernanceMsg, label: "治理提案" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "治理提案", fallback: "root veto 失敗" });
  }
}

async function signEconomyGovernanceMultisig(proposalUuid, signerWalletAddress, targetWalletAddress = "", amountPoints = 1, payloadHash = "", custodyMode = "", walletType = "") {
  try {
    const signature = await economyBuildGovernanceMultisigSignature({
      signer: signerWalletAddress,
      destination: targetWalletAddress || signerWalletAddress,
      amount: amountPoints,
      payloadHash: payloadHash || proposalUuid,
      requestUuid: proposalUuid,
      custodyMode,
      walletType,
    });
    const json = await fetchEconomyJson(`/admin/points/governance/proposals/${encodeURIComponent(proposalUuid)}/multisig-sign`, {
      method: "POST",
      body: JSON.stringify({ signer_wallet_address: signerWalletAddress, signature }),
    });
    economyNotifySuccess(`多簽已簽署：${json.multisig?.signature_count || 0}/${json.multisig?.threshold || 0}`, { msgFn: economyGovernanceMsg, label: "官方多簽" });
    await loadEconomyGovernance({ silent: true });
  } catch (err) {
    economyNotifyFailure(err, { msgFn: economyGovernanceMsg, label: "官方多簽", fallback: "多簽簽署失敗" });
  }
}

function bindEconomyGovernanceEvents(root = null) {
  const list = root || $("economy-governance-list");
  if (!list) return;
  list.querySelectorAll("[data-governance-toggle-proposal]").forEach((row) => {
    if (row.dataset.governanceToggleBound === "1") return;
    row.dataset.governanceToggleBound = "1";
    const toggle = () => toggleEconomyGovernanceProposal(row.dataset.governanceToggleProposal || "");
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggle();
    });
  });
  list.querySelectorAll("[data-governance-vote]").forEach((btn) => {
    if (btn.dataset.governanceBound === "1") return;
    btn.dataset.governanceBound = "1";
    btn.addEventListener("click", () => voteEconomyGovernanceProposal(btn.dataset.proposalUuid || "", btn.dataset.governanceVote || ""));
  });
  list.querySelectorAll("[data-governance-execute]").forEach((btn) => {
    if (btn.dataset.governanceBound === "1") return;
    btn.dataset.governanceBound = "1";
    btn.addEventListener("click", () => executeEconomyGovernanceProposal(btn.dataset.governanceExecute || ""));
  });
  list.querySelectorAll("[data-governance-sponsor]").forEach((btn) => {
    if (btn.dataset.governanceBound === "1") return;
    btn.dataset.governanceBound = "1";
    btn.addEventListener("click", () => sponsorEconomyGovernanceProposal(btn.dataset.governanceSponsor || ""));
  });
  list.querySelectorAll("[data-governance-cancel]").forEach((btn) => {
    if (btn.dataset.governanceBound === "1") return;
    btn.dataset.governanceBound = "1";
    btn.addEventListener("click", () => cancelEconomyGovernanceProposal(btn.dataset.governanceCancel || ""));
  });
  list.querySelectorAll("[data-governance-veto]").forEach((btn) => {
    if (btn.dataset.governanceBound === "1") return;
    btn.dataset.governanceBound = "1";
    btn.addEventListener("click", () => vetoEconomyGovernanceProposal(btn.dataset.governanceVeto || ""));
  });
  list.querySelectorAll("[data-governance-multisig-sign]").forEach((btn) => {
    if (btn.dataset.governanceBound === "1") return;
    btn.dataset.governanceBound = "1";
    btn.addEventListener("click", () => signEconomyGovernanceMultisig(
      btn.dataset.governanceMultisigSign || "",
      btn.dataset.signerWallet || "",
      btn.dataset.targetWallet || "",
      btn.dataset.requestedAmount || "1",
      btn.dataset.payloadHash || "",
      btn.dataset.custodyMode || "",
      btn.dataset.walletType || "",
    ));
  });
}

async function sendEconomyRootOfficialGrant() {
  if (!economyChainEnabled()) {
    economyRootOfficialGrantMsg("PointsChain 私有鏈已停用，官方 Treasury 撥款提案不可用。", false);
    return;
  }
  const btn = $("economy-root-official-grant-btn");
  const destination = String($("economy-root-official-grant-destination")?.value || "").trim();
  const amount = Math.floor(Number($("economy-root-official-grant-amount")?.value || 0));
  const reason = String($("economy-root-official-grant-reason")?.value || "").trim();
  if (!destination || !Number.isFinite(amount) || amount <= 0) {
    economyRootOfficialGrantMsg("請確認 To 錢包地址與 Value", false);
    return;
  }
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "送出中...";
    }
    const json = await fetchEconomyJson("/root/points/official-wallet/grant", {
      method: "POST",
      body: JSON.stringify({
        destination_wallet_address: destination,
        amount,
        reason,
        request_uuid: economyRequestId("official_wallet_grant"),
      }),
    });
    const proposalUuid = json.proposal?.proposal_uuid || json.proposal_uuid || "";
    const warningSuffix = economyWarningSuffix(json);
    const successMessage = proposalUuid
      ? `官方 Treasury 撥款提案已送出：${proposalUuid}；需 manager+ 投票、root veto 檢查、timelock 與官方多簽簽合後才會送出鏈上交易。`
      : "官方 Treasury 撥款提案已送出；需治理通過與官方多簽簽合後才會送出鏈上交易。";
    const visibleMessage = `${successMessage}${warningSuffix}`;
    economyRootOfficialGrantMsg(visibleMessage, !warningSuffix);
    setEconomyActivePage("explorer");
    await loadEconomyDashboard();
    await loadEconomyGovernance({ silent: true });
    economySetMsg(visibleMessage, !warningSuffix);
  } catch (err) {
    const message = err.message || "官方 Treasury 撥款提案送出失敗";
    economyRootOfficialGrantMsg(message, false);
    economySetMsg(message, false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "提出撥款提案";
    }
  }
}

async function sealPointsChainBlock() {
  if (!economyChainEnabled()) {
    economySetMsg("PointsChain 私有鏈已停用，無法封塊。", false);
    return;
  }
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
  if (!economyChainEnabled()) {
    setEconomyChainStatus("PointsChain 私有鏈已停用。");
    return;
  }
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
  if (!economyChainEnabled()) {
    economySetMsg("PointsChain 私有鏈已停用，無法建立鏈備份。", false);
    return;
  }
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
  if (!economyChainEnabled()) {
    economySetMsg("PointsChain 私有鏈已停用，無法執行鏈恢復。", false);
    return;
  }
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
  if (!economyChainEnabled()) {
    economySetMsg("PointsChain 私有鏈已停用，無法處理鏈異常。", false);
    return;
  }
  if (!confirm("系統會先驗證 PointsChain；若已進入 safe mode 且有建議健康備份，才會套用該備份並由 ledger 重建 wallet。此流程不會直接修改單筆餘額。是否繼續？")) return;
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
      btn.textContent = oldText || "檢查異常處理方案";
    }
  }
}

function economyExplorerSecondsText(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  if (value <= 0) return "已達成";
  if (value < 60) return `${value} 秒`;
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
}

function economyExplorerSecondsRangeText(minSeconds, maxSeconds) {
  const min = Math.max(0, Math.round(Number(minSeconds || 0)));
  const max = Math.max(min, Math.round(Number(maxSeconds || min)));
  if (min === max) return economyExplorerSecondsText(min);
  return `${economyExplorerSecondsText(min)}-${economyExplorerSecondsText(max)}`;
}

function economyExplorerFeeEstimateFromDataset(root, extraFeePoints = 0) {
  if (!root) return null;
  const baseMin = Number(root.dataset.baseSecondsMin || 120);
  const baseMax = Number(root.dataset.baseSecondsMax || 180);
  const floorMin = Number(root.dataset.minimumSecondsMin || 30);
  const floorMax = Number(root.dataset.minimumSecondsMax || 45);
  const reference = Math.max(1, Number(root.dataset.feeReferencePoints || 20));
  const currentFee = Math.max(0, Number(root.dataset.currentFeePoints || 0));
  const fee = Math.max(0, currentFee + Math.floor(Number(extraFeePoints || 0)));
  const ratio = fee > 0 ? fee / (fee + reference) : 0;
  const min = Math.round(baseMin - (baseMin - floorMin) * ratio);
  const max = Math.round(baseMax - (baseMax - floorMax) * ratio);
  return {
    fee,
    min,
    max: Math.max(max, min + 15),
    ratio,
  };
}

function updateEconomyExplorerAccelerateEstimate() {
  const root = document.querySelector("#economy-explorer-result .economy-explorer-accelerate");
  const input = $("economy-explorer-accelerate-fee");
  const target = $("economy-explorer-accelerate-estimate");
  if (!root || !input || !target) return;
  const extraFee = Number(input.value || 0);
  if (!Number.isFinite(extraFee) || extraFee <= 0) {
    target.textContent = "輸入鏈上費用後顯示預估 Proved 時間";
    return;
  }
  const current = economyExplorerFeeEstimateFromDataset(root, 0);
  const next = economyExplorerFeeEstimateFromDataset(root, extraFee);
  if (!current || !next) return;
  target.textContent = `預估 Proved ${economyExplorerSecondsRangeText(next.min, next.max)}；目前 ${economyExplorerSecondsRangeText(current.min, current.max)}；總費用 ${formatEconomyPointsValue(next.fee)} 點`;
}

let economyTransferFeeEstimateTimer = null;

function scheduleEconomyTransferFeeEstimate() {
  if (economyTransferFeeEstimateTimer) clearTimeout(economyTransferFeeEstimateTimer);
  economyTransferFeeEstimateTimer = setTimeout(loadEconomyTransferFeeEstimate, 250);
}

async function loadEconomyTransferFeeEstimate() {
  const target = $("economy-transfer-fee-estimate");
  if (!target) return;
  if (!economyChainEnabled()) {
    target.textContent = "PointsChain 私有鏈已停用";
    return;
  }
  const fee = Math.max(0, Math.floor(Number($("economy-transfer-fee")?.value || 0)));
  if (!Number.isFinite(fee)) {
    target.textContent = "請輸入鏈上費用以估算 Proved 時間";
    return;
  }
  try {
    const json = await fetchEconomyJson(`/points/explorer/fee-estimate?fee_points=${encodeURIComponent(String(fee))}`);
    const estimate = json.estimate || {};
    const network = estimate.network_fee_state || {};
    const label = network.congestion_label || "idle";
    const suggested = Number(network.suggested_total_fee_points || 0);
    target.textContent = `預估 Proved ${economyExplorerSecondsRangeText(estimate.estimated_seconds_min, estimate.estimated_seconds_max)} · 鏈上 ${label} · 建議費用 ${formatEconomyPointsValue(suggested)} 點`;
  } catch (err) {
    target.textContent = err.message || "預估 Proved 時間讀取失敗";
  }
}

function stopEconomyExplorerCountdown() {
  if (economyExplorerCountdownTimer) {
    clearInterval(economyExplorerCountdownTimer);
    economyExplorerCountdownTimer = null;
  }
}

function startEconomyExplorerCountdown() {
  stopEconomyExplorerCountdown();
  const card = document.querySelector("#economy-explorer-result .economy-explorer-finality");
  if (!card) return;
  const status = String(card.dataset.finalityStatus || "");
  if (status !== "pending") return;
  let eta = Math.max(0, Number(card.dataset.etaSeconds || 0));
  let next = Math.max(0, Number(card.dataset.nextProofEtaSeconds || 0));
  const etaEl = card.querySelector("[data-finality-eta-text]");
  const nextEl = card.querySelector("[data-finality-next-text]");
  const query = economyExplorerLastQuery || $("economy-explorer-query")?.value || "";
  economyExplorerCountdownTimer = setInterval(() => {
    eta = Math.max(0, eta - 1);
    next = Math.max(0, next - 1);
    if (etaEl) etaEl.textContent = economyExplorerSecondsText(eta);
    if (nextEl) nextEl.textContent = economyExplorerSecondsText(next);
    if (next <= 0 || eta <= 0) {
      stopEconomyExplorerCountdown();
      if (query) searchEconomyExplorer(query);
    }
  }, 1000);
}

function economyExplorerFinalityCard(finality = {}) {
  const target = Number(finality.target_proved_count || 20);
  const proved = Math.max(0, Math.min(target, Number(finality.proved_count || 0)));
  const percent = target > 0 ? Math.round((proved / target) * 100) : 0;
  const feePolicy = finality.chain_fee_policy && typeof finality.chain_fee_policy === "object" ? finality.chain_fee_policy : {};
  const network = finality.network_fee_state && typeof finality.network_fee_state === "object" ? finality.network_fee_state : {};
  const status = finality.finality_status === "failed"
    ? "未成交"
    : finality.finality_status === "sealed"
    ? "已封塊"
    : finality.finality_status === "proved"
      ? "已成交"
      : "等待 Proved";
  const eta = economyExplorerSecondsText(finality.eta_seconds || 0);
  const pending = String(finality.finality_status || "") === "pending";
  const nextProofEta = pending
    ? ` · 下一個 Proved 約 <span data-finality-next-text>${sanitize(economyExplorerSecondsText(finality.next_proof_eta_seconds || 0))}</span>`
    : "";
  const accelerated = finality.acceleration_fee_paid_points
    ? ` · 加速費 ${formatEconomyPointsValue(finality.acceleration_fee_paid_points)} 點 → ${finality.acceleration_fee_destination_label || "BURN 銷毀錢包"}`
    : "";
  const baseFee = finality.base_transaction_fee_points !== undefined
    ? ` · 原始費用 ${formatEconomyPointsValue(finality.base_transaction_fee_points)} 點`
    : "";
  const feeNote = feePolicy.base_fee_exempt
    ? ` · ${feePolicy.exemption_reason || "設定自動發放交易免鏈上費用"}`
    : "";
  const networkNote = network.congestion_label
    ? ` · 鏈上 ${network.congestion_label} · 建議費用 ${formatEconomyPointsValue(network.suggested_total_fee_points || 0)} 點`
    : "";
  return `
    <div class="economy-explorer-finality" data-finality-status="${sanitize(finality.finality_status || "")}" data-eta-seconds="${Number(finality.eta_seconds || 0)}" data-next-proof-eta-seconds="${Number(finality.next_proof_eta_seconds || 0)}">
      <div class="drive-card-heading">
        <div>
          <div class="drive-card-title">${sanitize(status)} · ${proved}/${target} Proved</div>
          <div class="drive-card-sub">${sanitize(finality.human_rule || "20 Proved；ETA 依鏈上忙碌度與 priority fee 動態估算")} · ETA <span data-finality-eta-text>${sanitize(eta)}</span>${nextProofEta}${sanitize(feeNote)}${sanitize(networkNote)}${sanitize(baseFee)}${sanitize(accelerated)}</div>
        </div>
        <span class="economy-explorer-badge">${sanitize(finality.block_status || "unsealed")}</span>
      </div>
      <div class="economy-explorer-progress"><span style="width:${Math.max(0, Math.min(100, percent))}%;"></span></div>
    </div>
  `;
}

function economyExplorerFlowHtml(tx = {}) {
  const flow = tx.wallet_flow && typeof tx.wallet_flow === "object" ? tx.wallet_flow : {};
  const source = flow.source_wallet_address || "";
  const dest = flow.destination_wallet_address || "";
  const addressNode = (label, address) => address
    ? `<button class="economy-explorer-address" type="button" data-explorer-query="${sanitize(address)}">${sanitize(label)}<strong>${sanitize(shortEconomyWalletAddress(address))}</strong></button>`
    : `<span class="economy-explorer-address">${sanitize(label)}<strong>-</strong></span>`;
  return `
    <div class="economy-explorer-flow">
      ${addressNode(flow.source_label || "來源", source)}
      <span>→</span>
      ${addressNode(flow.destination_label || "目的", dest)}
    </div>
  `;
}

function economyExplorerTxCard(tx = {}) {
  const block = tx.block || null;
  const finality = tx.finality || {};
  const feePolicy = finality.chain_fee_policy && typeof finality.chain_fee_policy === "object" ? finality.chain_fee_policy : {};
  const pending = !["sealed", "proved"].includes(String(finality.finality_status || ""));
  const canAccelerate = pending && feePolicy.acceleration_allowed !== false;
  const flow = tx.wallet_flow && typeof tx.wallet_flow === "object" ? tx.wallet_flow : {};
  const feeText = feePolicy.base_fee_exempt
    ? "免除"
    : `${formatEconomyPointsValue(finality.transaction_fee_points || finality.acceleration_fee_paid_points || 0)} 點`;
  const gasPriceText = feePolicy.base_fee_exempt
    ? "0 points/proved"
    : `${finality.gas_price_points_per_proved || 0} points/proved`;
  const network = finality.network_fee_state && typeof finality.network_fee_state === "object" ? finality.network_fee_state : {};
  const currentFeePoints = Number(finality.fee_points ?? finality.transaction_fee_points ?? finality.acceleration_fee_paid_points ?? 0);
  return `
    <div class="drive-card economy-explorer-card">
      <div class="drive-card-heading">
        <div>
          <div class="drive-card-title">交易 ${sanitize(shortEconomyWalletAddress(tx.ledger_hash || tx.ledger_uuid || ""))}</div>
          <div class="drive-card-sub">${sanitize(formatEconomyLedgerAction(tx.action_type))} · ${sanitize(tx.created_at || "")}</div>
        </div>
        <strong>${sanitize(formatEconomyLedgerAmount(tx))}</strong>
      </div>
      <div class="economy-explorer-kv">
        <span>Transaction Hash</span><code>${sanitize(tx.ledger_hash || "-")}</code>
        <span>Status</span><code>${sanitize(finality.finality_status || tx.status || "-")} · ${Number(finality.proved_count || 0)}/${Number(finality.target_proved_count || 20)} Proved</code>
        <span>Block</span>${block ? `<button type="button" data-explorer-query="${sanitize(String(block.block_number || ""))}">#${Number(block.block_number || 0)} · ${sanitize(shortEconomyWalletAddress(block.block_hash || ""))}</button>` : `<code>Pending / Unsealed</code>`}
        <span>Timestamp</span><code>${sanitize(tx.created_at || "-")}</code>
        <span>From</span>${flow.source_wallet_address ? `<button type="button" data-explorer-query="${sanitize(flow.source_wallet_address)}">${sanitize(flow.source_wallet_address)}</button>` : `<code>-</code>`}
        <span>To</span>${flow.destination_wallet_address ? `<button type="button" data-explorer-query="${sanitize(flow.destination_wallet_address)}">${sanitize(flow.destination_wallet_address)}</button>` : `<code>-</code>`}
        <span>Value</span><code>${sanitize(formatEconomyLedgerAmount(tx))}</code>
        <span>Transaction Fee</span><code>${sanitize(feeText)}</code>
        ${finality.acceleration_fee_paid_points ? `<span>Acceleration</span><code>${formatEconomyPointsValue(finality.acceleration_fee_paid_points)} 點 → ${sanitize(finality.acceleration_fee_destination_label || "BURN 銷毀錢包")}</code>` : ""}
        <span>Gas Price</span><code>${sanitize(gasPriceText)}</code>
        <span>Input Data</span><code>${sanitize(JSON.stringify(tx.input_data || {}))}</code>
        <span>Ledger UUID</span><button type="button" data-explorer-query="${sanitize(tx.ledger_uuid || "")}">${sanitize(tx.ledger_uuid || "-")}</button>
        <span>Previous</span><code>${sanitize(tx.previous_ledger_hash || "-")}</code>
      </div>
      ${economyExplorerFlowHtml(tx)}
      ${economyExplorerFinalityCard(finality)}
      ${canAccelerate ? `
        <div class="economy-explorer-accelerate" data-base-seconds-min="${Number(finality.network_base_seconds_min || finality.base_seconds_min || 120)}" data-base-seconds-max="${Number(finality.network_base_seconds_max || finality.base_seconds_max || 180)}" data-minimum-seconds-min="${Number(finality.minimum_seconds_min || 30)}" data-minimum-seconds-max="${Number(finality.minimum_seconds_max || 45)}" data-fee-reference-points="${Number(finality.fee_reference_points || network.suggested_priority_fee_points || 20)}" data-current-fee-points="${Number(currentFeePoints || 0)}">
          <div class="field"><label>鏈上費用</label><input type="number" id="economy-explorer-accelerate-fee" min="1" max="10000" value="${Number(network.suggested_priority_fee_points || 20)}" /><small id="economy-explorer-accelerate-estimate" class="drive-card-sub">輸入鏈上費用後顯示預估 Proved 時間</small></div>
          <button class="btn" id="economy-explorer-accelerate-btn" type="button" data-ledger-ref="${sanitize(tx.ledger_uuid || tx.ledger_hash || "")}">提高費用並加速</button>
        </div>
      ` : pending && feePolicy.base_fee_exempt ? `<div class="drive-card-sub economy-explorer-fee-note">${sanitize(feePolicy.exemption_reason || "設定自動發放交易免鏈上費用")}</div>` : ""}
    </div>
  `;
}

function economyExplorerWalletCard(wallet = {}) {
  const rows = Array.isArray(wallet.recent_transactions) ? wallet.recent_transactions : [];
  const addressType = String(wallet.address_type || "");
  const legacyAccount = Boolean(wallet.legacy_account) || addressType === "legacy_account";
  const systemFund = addressType === "system_fund" || Boolean(wallet.fund_key);
  const risk = wallet.risk_label && typeof wallet.risk_label === "object" ? wallet.risk_label : null;
  const freeze = wallet.governance_freeze && typeof wallet.governance_freeze === "object" ? wallet.governance_freeze : null;
  const riskHtml = risk
    ? `<div class="drive-card-sub" style="color:#ff4f6d;margin-top:.45rem;">治理標記：${sanitize(risk.risk_level || risk.label || "risk")} · ${sanitize(risk.reason || "")}</div>`
    : "";
  const freezeHtml = freeze
    ? `<div class="drive-card-sub" style="color:#ff4f6d;margin-top:.35rem;">${freeze.freeze_type === "provisional" ? "短期審核凍結" : "治理凍結"}：禁止轉出${freeze.expires_at ? ` · 到期 ${sanitize(freeze.expires_at)}` : ""} · ${sanitize(freeze.reason || "")}</div>`
    : "";
  const titlePrefix = legacyAccount ? "Legacy 帳本身份" : (systemFund ? "系統基金錢包" : "錢包");
  const identityLabel = legacyAccount ? "Legacy 帳本 ID" : "地址";
  const typeText = legacyAccount
    ? "legacy_account · 舊帳本公開識別碼"
    : `${sanitize(wallet.wallet_type || "-")} · ${sanitize(wallet.status || "-")}${wallet.fund_key ? ` · ${sanitize(wallet.fund_key)}` : ""}`;
  return `
    <div class="drive-card economy-explorer-card">
      <div class="drive-card-heading">
        <div>
          <div class="drive-card-title">${sanitize(titlePrefix)} ${sanitize(shortEconomyWalletAddress(wallet.address || ""))}</div>
          <div class="drive-card-sub">${typeText}</div>
          ${riskHtml}
          ${freezeHtml}
        </div>
        <strong>${formatEconomyPointsValue(wallet.points_balance || 0)} 點</strong>
      </div>
      <div class="economy-explorer-kv">
        <span>${sanitize(identityLabel)}</span><code>${sanitize(wallet.address || "-")}</code>
        <span>金額凍結</span><code>${formatEconomyPointsValue(wallet.points_frozen || 0)} 點</code>
        <span>治理凍結</span><code>${freeze ? (freeze.freeze_type === "provisional" ? "短期禁止轉出" : "禁止轉出") : "無"}</code>
        <span>風險標記</span><code>${risk ? sanitize(risk.risk_level || risk.label || "risk") : "無"}</code>
        <span>交易數</span><code>${Number(wallet.transaction_count || 0)}</code>
        <span>成交條件</span><code>${sanitize(wallet.human_rule || "20 Proved；ETA 依鏈上忙碌度與 priority fee 動態估算")}</code>
      </div>
      <div class="drive-file-list economy-explorer-tx-list">
        ${rows.length ? rows.map((tx) => `
          <div class="drive-file-row">
            <div>
              <strong>${sanitize(formatEconomyLedgerAmount(tx))} · ${sanitize(formatEconomyLedgerAction(tx.action_type))}</strong>
              <div class="drive-card-sub">${sanitize(tx.created_at || "")} · ${sanitize(shortEconomyWalletAddress(tx.ledger_hash || ""))}</div>
            </div>
            <button class="btn btn-sm" type="button" data-explorer-query="${sanitize(tx.ledger_uuid || tx.ledger_hash || "")}">查看</button>
          </div>
        `).join("") : `<div class="drive-empty">沒有可顯示的鏈上交易</div>`}
      </div>
    </div>
  `;
}

function economyExplorerBlockCard(block = {}) {
  const txs = Array.isArray(block.transactions) ? block.transactions : [];
  return `
    <div class="drive-card economy-explorer-card">
      <div class="drive-card-heading">
        <div>
          <div class="drive-card-title">區塊 #${Number(block.block_number || 0)}</div>
          <div class="drive-card-sub">${sanitize(block.seal_status || "-")} · ${sanitize(block.sealed_at || "")}</div>
        </div>
        <strong>${Number(block.ledger_count || 0)} tx</strong>
      </div>
      <div class="economy-explorer-kv">
        <span>Block Hash</span><code>${sanitize(block.block_hash || "-")}</code>
        <span>Previous</span><code>${sanitize(block.previous_block_hash || "-")}</code>
        <span>Merkle Root</span><code>${sanitize(block.merkle_root || "-")}</code>
        <span>Anchor</span><code>${sanitize(block.anchor_status || "-")}</code>
      </div>
      <div class="drive-file-list economy-explorer-tx-list">
        ${txs.length ? txs.map((tx) => `
          <div class="drive-file-row">
            <div>
              <strong>${sanitize(formatEconomyLedgerAmount(tx))} · ${sanitize(formatEconomyLedgerAction(tx.action_type))}</strong>
              <div class="drive-card-sub">${sanitize(tx.created_at || "")} · ${sanitize(shortEconomyWalletAddress(tx.ledger_hash || ""))}</div>
            </div>
            <button class="btn btn-sm" type="button" data-explorer-query="${sanitize(tx.ledger_uuid || tx.ledger_hash || "")}">查看</button>
          </div>
        `).join("") : `<div class="drive-empty">此區塊沒有交易</div>`}
      </div>
    </div>
  `;
}

function bindEconomyExplorerResultEvents() {
  const root = $("economy-explorer-result");
  if (!root) return;
  root.querySelectorAll("[data-explorer-query]").forEach((btn) => {
    if (btn.dataset.explorerBound === "1") return;
    btn.dataset.explorerBound = "1";
    btn.addEventListener("click", () => {
      const query = btn.dataset.explorerQuery || "";
      if ($("economy-explorer-query")) $("economy-explorer-query").value = query;
      searchEconomyExplorer(query);
    });
  });
  const accelerateBtn = $("economy-explorer-accelerate-btn");
  if (accelerateBtn && accelerateBtn.dataset.explorerBound !== "1") {
    accelerateBtn.dataset.explorerBound = "1";
    accelerateBtn.addEventListener("click", accelerateEconomyExplorerTx);
  }
  const accelerateFeeInput = $("economy-explorer-accelerate-fee");
  if (accelerateFeeInput && accelerateFeeInput.dataset.explorerEstimateBound !== "1") {
    accelerateFeeInput.dataset.explorerEstimateBound = "1";
    accelerateFeeInput.addEventListener("input", updateEconomyExplorerAccelerateEstimate);
    accelerateFeeInput.addEventListener("change", updateEconomyExplorerAccelerateEstimate);
    updateEconomyExplorerAccelerateEstimate();
  }
}

function renderEconomyExplorerResult(result) {
  const wrap = $("economy-explorer-result");
  if (!wrap) return;
  stopEconomyExplorerCountdown();
  if (!result) {
    wrap.innerHTML = `<div class="drive-empty">查無鏈上資料</div>`;
    return;
  }
  if (result.kind === "transaction") wrap.innerHTML = economyExplorerTxCard(result.transaction || {});
  else if (result.kind === "wallet") wrap.innerHTML = economyExplorerWalletCard(result.wallet || {});
  else if (result.kind === "block") wrap.innerHTML = economyExplorerBlockCard(result.block || {});
  else wrap.innerHTML = `<div class="drive-empty">不支援的查詢結果</div>`;
  bindEconomyExplorerResultEvents();
  startEconomyExplorerCountdown();
}

async function searchEconomyExplorer(query = null) {
  if (!economyChainEnabled()) {
    economyExplorerMsg("PointsChain 私有鏈已停用，Explorer 不可用。", false);
    return;
  }
  const input = $("economy-explorer-query");
  const value = String(query ?? input?.value ?? "").trim();
  if (!value) {
    economyExplorerMsg("請輸入交易 hash、Ledger UUID、錢包地址或區塊", false);
    return;
  }
  economyExplorerLastQuery = value;
  if (input) input.value = value;
  const btn = $("economy-explorer-search-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "查詢中...";
    }
    const json = await fetchEconomyJson(`/points/explorer/search?q=${encodeURIComponent(value)}&limit=25`);
    renderEconomyExplorerResult(json.result);
    economyExplorerMsg("已更新鏈上資料");
  } catch (err) {
    renderEconomyExplorerResult(null);
    economyExplorerMsg(err.message || "鏈上查詢失敗", false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "查詢";
    }
  }
}

async function accelerateEconomyExplorerTx() {
  if (!economyChainEnabled()) {
    economyExplorerMsg("PointsChain 私有鏈已停用，無法加速交易。", false);
    return;
  }
  const btn = $("economy-explorer-accelerate-btn");
  const ledgerRef = btn?.dataset?.ledgerRef || economyExplorerLastQuery;
  const fee = Number($("economy-explorer-accelerate-fee")?.value || 0);
  if (!ledgerRef || !Number.isFinite(fee) || fee <= 0) {
    economyExplorerMsg("請輸入有效鏈上費用", false);
    return;
  }
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "送出中...";
    }
    const json = await fetchEconomyJson("/points/explorer/accelerate", {
      method: "POST",
      body: JSON.stringify({
        ledger_ref: ledgerRef,
        fee_points: Math.floor(fee),
        request_uuid: economyRequestId("points_chain_acceleration"),
      }),
    });
    renderEconomyExplorerResult(json.result);
    const tx = json.result?.transaction || {};
    const finality = tx.finality || {};
    const eta = Number(finality.eta_seconds || 0);
    const proved = `${Number(finality.proved_count || 0)}/${Number(finality.target_proved_count || 20)}`;
    economyExplorerMsg(`已送出鏈上加速費用，Proved ${proved}，ETA ${economyExplorerSecondsText(eta)}`);
    await loadEconomyDashboard();
  } catch (err) {
    economyExplorerMsg(err.message || "加速失敗", false);
  } finally {
    if (btn) {
      btn.disabled = false;
        btn.textContent = oldText || "提高費用並加速";
    }
  }
}

function bindEconomyInlineEvents() {
  const bindings = [
    ["economy-refresh-btn", loadEconomyDashboard],
    ["economy-wallet-onboarding-refresh-btn", loadEconomyDashboard],
    ["economy-wallet-download-btn", downloadEconomyWalletCsv],
    ["economy-wallet-official-hot-btn", useOfficialHotWallet],
    ["economy-wallet-create-cold-btn", createColdWalletDraft],
    ["economy-wallet-use-generated-cold-btn", selectGeneratedColdWalletForImport],
    ["economy-wallet-import-cold-btn", startColdWalletImport],
    ["economy-wallet-confirm-cold-btn", confirmColdWalletBinding],
    ["economy-transfer-submit-btn", submitEconomyWalletTransfer],
    ["economy-transactions-refresh-btn", loadEconomyTransactions],
    ["economy-disputes-refresh-btn", () => loadEconomyTransactionDisputes()],
    ["economy-explorer-search-btn", () => searchEconomyExplorer()],
    ["economy-explorer-refresh-btn", () => searchEconomyExplorer(economyExplorerLastQuery || $("economy-explorer-query")?.value || "")],
    ["economy-governance-refresh-btn", () => loadEconomyGovernance()],
    ["economy-governance-scam-create-btn", createGovernanceAddressRiskProposal],
    ["economy-governance-freeze-create-btn", createGovernanceWalletFreezeProposal],
    ["economy-governance-branch-create-btn", createGovernanceRecoveryBranchProposal],
    ["economy-governance-lockdown-create-btn", createGovernanceEmergencyLockdownProposal],
    ["economy-governance-treasury-create-btn", createGovernanceTreasuryProposal],
    ["economy-governance-mint-create-btn", createGovernanceMintRequestProposal],
    ["economy-governance-policy-create-btn", createGovernancePolicyProposal],
    ["economy-treasury-analysis-refresh-btn", () => loadEconomyTreasurySignerCenter()],
    ["economy-trading-export-btn", downloadEconomyTradingCsv],
    ["economy-ledger-export-btn", exportEconomyLedgerCsv],
    ["economy-root-funding-refresh-btn", () => loadEconomyRootTradingReadOnly({ refreshSnapshot: true })],
    ["economy-root-positions-refresh-btn", () => loadEconomyRootTradingReadOnly({ refreshSnapshot: true })],
    ["economy-root-wallet-refresh-btn", loadEconomyRootReport],
    ["economy-root-official-grant-btn", sendEconomyRootOfficialGrant],
    ["economy-root-report-btn", loadEconomyRootReport],
    ["economy-backup-btn", createPointsChainBackup],
    ["economy-recovery-auto-handle-btn", autoHandlePointsChainRecovery],
    ["economy-recovery-approve-btn", approvePointsChainRecovery],
    ["economy-seal-btn", sealPointsChainBlock],
    ["economy-verify-btn", verifyPointsChain],
  ];
  bindings.forEach(([id, handler]) => {
    const el = $(id);
    if (!el || el.dataset.economyInlineBound === "1") return;
    el.dataset.economyInlineBound = "1";
    el.addEventListener("click", handler);
  });
  economyInlineEventsBound = true;
  document.querySelectorAll("[data-economy-page]").forEach((tab) => {
    if (tab.dataset.economyPageBound === "1") return;
    tab.dataset.economyPageBound = "1";
    tab.addEventListener("click", () => setEconomyActivePage(tab.dataset.economyPage || "balance"));
  });
  const explorerInput = $("economy-explorer-query");
  if (explorerInput && explorerInput.dataset.economyInlineBound !== "1") {
    explorerInput.dataset.economyInlineBound = "1";
    explorerInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") searchEconomyExplorer();
    });
  }
  const transferFeeInput = $("economy-transfer-fee");
  if (transferFeeInput && transferFeeInput.dataset.economyEstimateBound !== "1") {
    transferFeeInput.dataset.economyEstimateBound = "1";
    transferFeeInput.addEventListener("input", scheduleEconomyTransferFeeEstimate);
    transferFeeInput.addEventListener("change", scheduleEconomyTransferFeeEstimate);
    scheduleEconomyTransferFeeEstimate();
  }
  const treasuryAction = $("economy-governance-treasury-action");
  if (treasuryAction && treasuryAction.dataset.economyTreasuryBound !== "1") {
    treasuryAction.dataset.economyTreasuryBound = "1";
    treasuryAction.addEventListener("change", () => {
      syncGovernanceTreasuryDestination();
      if (String(treasuryAction.value || "").trim().toUpperCase() === "EXCHANGE_FUND_REPLENISH" && !String(economyFundAddressCache.exchange_fund || "").trim()) {
        loadEconomyTreasurySignerCenter({ silent: true });
      }
    });
    syncGovernanceTreasuryDestination();
  }
  const governanceCategory = $("economy-governance-category-select");
  if (governanceCategory && governanceCategory.dataset.economyGovernanceCategoryBound !== "1") {
    governanceCategory.dataset.economyGovernanceCategoryBound = "1";
    governanceCategory.addEventListener("change", () => {
      setEconomyGovernanceCategory(governanceCategory.value || "all");
      renderEconomyGovernance({ proposals: Array.from(economyGovernanceProposalCache.values()) });
    });
  }
  document.querySelectorAll("[data-governance-status-filter]").forEach((btn) => {
    if (btn.dataset.economyGovernanceStatusBound === "1") return;
    btn.dataset.economyGovernanceStatusBound = "1";
    btn.addEventListener("click", () => {
      setEconomyGovernanceStatusFilter(btn.dataset.governanceStatusFilter || "review");
      renderEconomyGovernance({ proposals: Array.from(economyGovernanceProposalCache.values()) });
    });
  });
  setEconomyGovernanceStatusFilter(economyGovernanceStatusFilter);
  if (economyDocumentEventsBound) {
    syncEconomySubpages(currentUser === "root");
    syncEconomyAutoRefreshLifecycle();
    return;
  }
  economyDocumentEventsBound = true;
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
