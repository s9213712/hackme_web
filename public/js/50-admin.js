function adminPercentValue(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function adminInputPercent(value, fallback = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.round(number * 10000) / 10000;
}

function adminFormatPercent(value, fallback = 0) {
  const percent = adminPercentValue(value, fallback);
  return percent.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

const CLOUD_DRIVE_TRANSFER_LEVELS = [
  { key: "newbie", label: "新手" },
  { key: "normal", label: "一般" },
  { key: "trusted", label: "可信任" },
  { key: "vip", label: "VIP" },
  { key: "restricted", label: "限制中" },
  { key: "suspended", label: "停權" }
];

const DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS = {
  newbie: { upload_kb_per_sec: 256, download_kb_per_sec: 512, priority: 20 },
  normal: { upload_kb_per_sec: 512, download_kb_per_sec: 1024, priority: 40 },
  trusted: { upload_kb_per_sec: 2048, download_kb_per_sec: 4096, priority: 70 },
  vip: { upload_kb_per_sec: 8192, download_kb_per_sec: 16384, priority: 90 },
  restricted: { upload_kb_per_sec: 128, download_kb_per_sec: 256, priority: 10 },
  suspended: { upload_kb_per_sec: 0, download_kb_per_sec: 0, priority: 0 }
};

let suppressNextSettingsStatusClear = false;
let currentServerMode = "dev_ready";
let settingsStatusAutoClearTimer = null;

function parseCloudDriveTransferLimits(raw) {
  if (!raw) return { ...DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS };
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    const out = {};
    CLOUD_DRIVE_TRANSFER_LEVELS.forEach(({ key }) => {
      const value = parsed?.[key] || {};
      out[key] = {
        upload_kb_per_sec: Number.isFinite(Number(value.upload_kb_per_sec)) ? Math.max(0, parseInt(value.upload_kb_per_sec, 10)) : DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS[key].upload_kb_per_sec,
        download_kb_per_sec: Number.isFinite(Number(value.download_kb_per_sec)) ? Math.max(0, parseInt(value.download_kb_per_sec, 10)) : DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS[key].download_kb_per_sec,
        priority: Number.isFinite(Number(value.priority)) ? Math.min(100, Math.max(0, parseInt(value.priority, 10))) : DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS[key].priority
      };
    });
    return out;
  } catch (_) {
    return { ...DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS };
  }
}

function renderCloudDriveTransferLimits(raw) {
  const host = $("cloud-drive-transfer-limits-list");
  if (!host) return;
  const limits = parseCloudDriveTransferLimits(raw);
  host.innerHTML = CLOUD_DRIVE_TRANSFER_LEVELS.map(({ key, label }) => {
    const value = limits[key] || DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS[key];
    return `
      <div class="drive-transfer-limit-row" data-drive-transfer-level="${key}">
        <div class="drive-transfer-limit-level">${label}</div>
        <label>上傳 KB/s
          <input type="number" min="0" step="1" data-drive-transfer-field="upload_kb_per_sec" value="${value.upload_kb_per_sec}" />
        </label>
        <label>下載 KB/s
          <input type="number" min="0" step="1" data-drive-transfer-field="download_kb_per_sec" value="${value.download_kb_per_sec}" />
        </label>
        <label>優先序
          <input type="number" min="0" max="100" step="1" data-drive-transfer-field="priority" value="${value.priority}" />
        </label>
      </div>
    `;
  }).join("");
}

function collectCloudDriveTransferLimits() {
  const out = {};
  CLOUD_DRIVE_TRANSFER_LEVELS.forEach(({ key }) => {
    const row = document.querySelector(`[data-drive-transfer-level="${key}"]`);
    const fallback = DEFAULT_CLOUD_DRIVE_TRANSFER_LIMITS[key];
    out[key] = {};
    ["upload_kb_per_sec", "download_kb_per_sec", "priority"].forEach((field) => {
      const input = row?.querySelector(`[data-drive-transfer-field="${field}"]`);
      const max = field === "priority" ? 100 : Number.MAX_SAFE_INTEGER;
      const raw = parseInt(input?.value || `${fallback[field]}`, 10);
      out[key][field] = Math.min(max, Math.max(0, Number.isFinite(raw) ? raw : fallback[field]));
    });
  });
  return out;
}

function switchServerTab(tab) {
  currentServerTab = tab;
  if (tab !== "security") stopServerOutputPoll();
  ["security", "audit", "health", "integrity", "settings", "env"].forEach((name) => {
    const sec = $("sec-server-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-server-security", "tab-server-audit", "tab-server-health", "tab-server-integrity", "tab-server-settings", "tab-server-env"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-server-" + tab);
  });
  if (tab === "security") {
    loadSecurityCenter();
    startServerOutputPoll();
  }
  if (tab === "audit") loadAudit(0);
  if (tab === "health") { loadServerHealth(); loadPlatformStats(); }
  if (tab === "integrity") loadIntegrityGuard();
  if (tab === "settings") {
    loadSettings();
    loadServerMode();
    loadServerUpdateStatus(false);
  }
  if (tab === "env") loadServerEnv();
  if (typeof updateSidebarActiveState === "function") updateSidebarActiveState();
}

function switchSettingsSection(tab) {
  currentSettingsSection = tab;
  ["security", "features", "appearance", "system", "billing", "drive", "member-levels"].forEach((name) => {
    const sec = $("sec-settings-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-settings-security", "tab-settings-features", "tab-settings-appearance", "tab-settings-system", "tab-settings-billing", "tab-settings-drive", "tab-settings-member-levels"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-settings-" + tab);
  });
  if (tab === "drive") {
    loadCloudDriveAdminPolicy();
    loadRootStorageUsers();
  }
  if (tab === "billing") {
    loadRootEconomyCatalog();
    loadRootTradingSettings();
  }
  if (tab === "member-levels") loadEditableMemberLevelRules();
  if (typeof clearSettingsStatus === "function") {
    if (suppressNextSettingsStatusClear) suppressNextSettingsStatusClear = false;
    else clearSettingsStatus();
  }
}

function canOpenAdminTab(tab) {
  if (!currentUser) return false;
  const managerOrAbove = currentRole === "manager" || currentRole === "super_admin";
  switch (tab) {
    case "users":
    case "password-resets":
      return canAccessModule("accounts");
    case "violations":
      return canAccessModule("accounts") && (!isFeatureEnabledForUi || isFeatureEnabledForUi("feature_violation_center_enabled", false));
    case "governance":
      return managerOrAbove && (!isFeatureEnabledForUi || isFeatureEnabledForUi("feature_member_governance_enabled", false));
    case "notices":
      return managerOrAbove && (!isFeatureEnabledForUi || isFeatureEnabledForUi("feature_reports_notifications_enabled", false));
    case "appeals":
      return currentRole === "super_admin" && canAccessModule("appeals");
    case "reports":
      return currentRole === "super_admin" && (!isFeatureEnabledForUi || isFeatureEnabledForUi("feature_reports_enabled", false));
    default:
      return false;
  }
}

function firstAvailableAdminTab() {
  return ["users", "password-resets", "violations", "governance", "notices", "appeals", "reports"].find((tab) => canOpenAdminTab(tab)) || "users";
}

function switchModuleTab(tab) {
  const canAccessAccounts = canAccessModule("accounts");
  const canAccessServer = currentUser === "root";
  const canAccessAppeals = currentRole !== "super_admin" && canAccessModule("appeals");
  const canAccessCommunity = !!currentUser && canAccessModule("community");
  const canAccessAnnouncements = canAccessCommunity;
  const canAccessChat = !!currentUser && canAccessModule("chat");
  const canAccessDrive = !!currentUser && canAccessModule("privacy_uploads");
  const canAccessAlbums = canAccessDrive && (!isFeatureEnabledForUi || isFeatureEnabledForUi("feature_storage_albums_enabled", false));
  const canAccessVideos = !!currentUser && canAccessModule("videos");
  const canAccessGames = !!currentUser && canAccessModule("games");
  const canUseComfyuiTab = typeof isComfyuiAvailableForNavigation !== "function" || isComfyuiAvailableForNavigation();
  const canAccessComfyui = !!currentUser && canAccessModule("comfyui") && canUseComfyuiTab;
  const canAccessEconomy = !!currentUser && canAccessModule("economy");
  const canAccessTrading = canAccessEconomy && canAccessModule("trading");

  let normTab = tab;
  const fallbackModule = () => canAccessChat ? "chat" : (canAccessCommunity ? "community" : (canAccessDrive ? "drive" : (canAccessVideos ? "videos" : (canAccessGames ? "games" : (canAccessComfyui ? "comfyui" : (canAccessEconomy ? "economy" : (canAccessAppeals ? "appeals" : (canAccessAccounts ? "accounts" : "chat"))))))));
  if (tab === "chat" && !canAccessChat) normTab = fallbackModule();
  if (tab === "dm") normTab = fallbackModule();
  if (tab === "announcements" && !canAccessAnnouncements) normTab = fallbackModule();
  if (tab === "community" && !canAccessCommunity) normTab = fallbackModule();
  if (tab === "drive" && !canAccessDrive) normTab = fallbackModule();
  if (tab === "albums" && !canAccessAlbums) normTab = fallbackModule();
  if (tab === "videos" && !canAccessVideos) normTab = fallbackModule();
  if (tab === "games" && !canAccessGames) normTab = fallbackModule();
  if (tab === "comfyui" && !canAccessComfyui) normTab = fallbackModule();
  if (tab === "economy" && !canAccessEconomy) normTab = fallbackModule();
  if (tab === "trading" && !canAccessTrading) normTab = fallbackModule();
  if (tab === "accounts" && !canAccessAccounts) normTab = fallbackModule();
  if (tab === "server" && !canAccessServer) normTab = canAccessAccounts ? "accounts" : fallbackModule();
  if (tab === "appeals" && !canAccessAppeals) normTab = fallbackModule();

  currentModuleTab = normTab;
  const modChat = $("module-chat");
  const modAnnouncements = $("module-announcements");
  const modCommunity = $("module-community");
  const modDrive = $("module-drive");
  const modAlbums = $("module-albums");
  const modVideos = $("module-videos");
  const modGames = $("module-games");
  const modComfyui = $("module-comfyui");
  const modEconomy = $("module-economy");
  const modTrading = $("module-trading");
  const modAccounts = $("module-accounts");
  const modServer = $("module-server");
  const modAppeals = $("module-appeals");
  const mChat = $("tab-module-chat");
  const mAnnouncements = $("tab-module-announcements");
  const mCommunity = $("tab-module-community");
  const mDrive = $("tab-module-drive");
  const mAlbums = $("tab-module-albums");
  const mVideos = $("tab-module-videos");
  const mGames = $("tab-module-games");
  const mComfyui = $("tab-module-comfyui");
  const mEconomy = $("tab-module-economy");
  const mTrading = $("tab-module-trading");
  const mAccounts = $("tab-module-accounts");
  const mServer = $("tab-module-server");
  const mAppeals = $("tab-module-appeals");

  if (modChat) modChat.classList.toggle("active", normTab === "chat");
  if (modAnnouncements) modAnnouncements.classList.toggle("active", normTab === "announcements");
  if (modCommunity) modCommunity.classList.toggle("active", normTab === "community");
  if (modDrive) modDrive.classList.toggle("active", normTab === "drive");
  if (modAlbums) modAlbums.classList.toggle("active", normTab === "albums");
  if (modVideos) modVideos.classList.toggle("active", normTab === "videos");
  if (modGames) modGames.classList.toggle("active", normTab === "games");
  if (modComfyui) modComfyui.classList.toggle("active", normTab === "comfyui");
  if (modEconomy) modEconomy.classList.toggle("active", normTab === "economy");
  if (modTrading) modTrading.classList.toggle("active", normTab === "trading");
  if (modAccounts) modAccounts.classList.toggle("active", normTab === "accounts");
  if (modServer) modServer.classList.toggle("active", normTab === "server");
  if (modAppeals) modAppeals.classList.toggle("active", normTab === "appeals");
  if (mChat) mChat.classList.toggle("active", normTab === "chat");
  if (mAnnouncements) mAnnouncements.classList.toggle("active", normTab === "announcements");
  if (mCommunity) mCommunity.classList.toggle("active", normTab === "community");
  if (mDrive) mDrive.classList.toggle("active", normTab === "drive");
  if (mAlbums) mAlbums.classList.toggle("active", normTab === "albums");
  if (mVideos) mVideos.classList.toggle("active", normTab === "videos");
  if (mGames) mGames.classList.toggle("active", normTab === "games");
  if (mComfyui) mComfyui.classList.toggle("active", normTab === "comfyui");
  if (mEconomy) mEconomy.classList.toggle("active", normTab === "economy");
  if (mTrading) mTrading.classList.toggle("active", normTab === "trading");
  if (mAccounts) mAccounts.classList.toggle("active", normTab === "accounts");
  if (mServer) mServer.classList.toggle("active", normTab === "server");
  if (mAppeals) mAppeals.classList.toggle("active", normTab === "appeals");

  if (normTab === "community" && canAccessCommunity) {
    loadCommunityHome();
  }
  if (normTab === "announcements" && canAccessAnnouncements) {
    loadAnnouncements();
  }
  if (normTab !== "server") stopServerOutputPoll();
  if (normTab === "server" && canAccessServer) {
    switchServerTab(currentServerTab || "security");
  }
  if (normTab === "drive" && canAccessDrive) {
    loadDriveDashboard();
  }
  if (normTab === "albums" && canAccessAlbums) {
    loadAlbumGallery();
  }
  if (normTab === "videos" && canAccessVideos && typeof loadVideoPlatform === "function") {
    loadVideoPlatform();
  }
  if (normTab === "games" && canAccessGames && typeof loadGameZone === "function") {
    loadGameZone();
  }
  if (normTab === "comfyui" && canAccessComfyui && typeof loadComfyuiModels === "function") {
    loadComfyuiModels();
  }
  if (normTab === "economy" && canAccessEconomy && typeof loadEconomyDashboard === "function") {
    loadEconomyDashboard();
  }
  if (normTab === "trading" && canAccessTrading && typeof loadTradingDashboard === "function") {
    loadTradingDashboard();
  }
  if (normTab === "appeals" && canAccessAppeals) {
    loadUserAppeals();
  }
  if (normTab === "accounts" && canAccessAccounts) {
    const nextAdminTab = currentAdminTab && canOpenAdminTab(currentAdminTab) ? currentAdminTab : firstAvailableAdminTab();
    if (!$("sec-" + nextAdminTab)) switchAdminTab("users");
    else switchAdminTab(nextAdminTab);
  }
  if (typeof updateSidebarActiveState === "function") updateSidebarActiveState();
  if (typeof collapseSidebarAfterMobileNavigation === "function") collapseSidebarAfterMobileNavigation();
}

function switchAdminTab(tab) {
  currentAdminTab = canOpenAdminTab(tab) ? tab : firstAvailableAdminTab();
  ["users","password-resets","violations","governance","notices","appeals","reports"].forEach(t => {
    const sec = $("sec-" + t);
    if (sec) sec.classList.toggle("active", t === currentAdminTab);
  });
  ["tab-users","tab-password-resets","tab-violations","tab-governance","tab-notices","tab-appeals","tab-reports"].forEach(id => {
    const btn = $(id);
    const tabKey = id.replace(/^tab-/, "");
    if (!btn) return;
    btn.style.display = canOpenAdminTab(tabKey) ? "" : "none";
    btn.classList.toggle("active", id === "tab-" + currentAdminTab);
  });
  if (currentAdminTab === "password-resets") loadPasswordResetReviews();
  if (currentAdminTab === "violations") loadViolations(0);
  if (currentAdminTab === "governance") loadGovernanceDashboard();
  if (currentAdminTab === "notices") renderAdminNoticeTargetOptions();
  if (currentAdminTab === "appeals") loadAdminAppeals(1, adminAppealStatus);
  if (currentAdminTab === "reports") loadAdminReports(0, adminReportStatus);
  if (typeof updateSidebarActiveState === "function") updateSidebarActiveState();
}

const ADMIN_NOTICE_TEMPLATES = {
  custom: { title: "", body: "" },
  sanction: { title: "會員權益變更通知", body: "你的帳號權益已被調整，若有疑問請到申覆分頁提出申覆。" },
  points: { title: "積分異動通知", body: "你的積分已發生異動，請到積分錢包查看明細。" },
  account: { title: "帳號狀態通知", body: "你的帳號狀態已有更新，請確認個人資訊與系統通知。" },
};

function renderAdminNoticeTargetOptions() {
  const select = $("admin-notice-user-id");
  if (!select) return;
  const selectable = (Array.isArray(users) ? users : []).filter((user) => {
    if (!user || !user.id) return false;
    if (currentUser !== "root" && clientRoleRank(user.role || "user") >= clientRoleRank(currentRole || "user")) return false;
    return true;
  });
  select.innerHTML = selectable.length
    ? selectable.map((user) => `<option value="${user.id}">${sanitize(user.username || "-")}（#${user.id}）</option>`).join("")
    : `<option value="">沒有可發送通知的成員</option>`;
}

function applyAdminNoticeTemplate() {
  const key = $("admin-notice-template")?.value || "custom";
  const template = ADMIN_NOTICE_TEMPLATES[key] || ADMIN_NOTICE_TEMPLATES.custom;
  const title = $("admin-notice-title");
  const body = $("admin-notice-body");
  if (title && template.title) title.value = template.title;
  if (body && template.body) body.value = template.body;
}

async function sendAdminNotice() {
  const userId = $("admin-notice-user-id")?.value || "";
  const title = ($("admin-notice-title")?.value || "").trim();
  const body = ($("admin-notice-body")?.value || "").trim();
  const msg = $("admin-notice-msg");
  if (!userId || !title || !body) {
    flash(msg, "請選擇成員並填寫標題、內容", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/notifications/send", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ user_id: userId, title, body })
  });
  const json = await res.json().catch(() => ({}));
  flash(msg, json.msg || (json.ok ? "通知已發送" : "通知發送失敗"), !!json.ok);
  if (json.ok && $("admin-notice-body")) $("admin-notice-body").value = "";
}

// ── Audit log ───────────────────────────────────────────────
let auditPage = 0;
const AUDIT_PAGE_SIZE = 20;
let serverOutputPollTimer = null;

async function loadAudit(page) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/audit?page=" + page, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  auditPage = page;
  $("audit-total").textContent = json.total || 0;
  const integrity = json.integrity;
  const integEl = $("audit-integrity");
  if (integEl) {
    if (integrity && integrity.enabled === false) {
      integEl.textContent = "審計鏈檢查已停用";
      integEl.style.color = "var(--muted)";
    } else {
      const chainOk = integrity && integrity.ok;
      integEl.textContent = chainOk ? "🔗 鏈完整" : "⚠️ 鏈已斷！";
      integEl.style.color = chainOk ? "#4caf50" : "#ff4f6d";
    }
  }
  if (currentRole === "super_admin" && integrity && integrity.enabled !== false && integrity.ok === false && integrity.broken_at) {
    alert(`審計紀錄異常：hash chain 在 #${integrity.broken_at} 斷裂，請立即檢查。`);
  }
  const container = $("audit-entries");
  if (!container) return;
  if (!json.entries || json.entries.length === 0) {
    container.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>暫無審計記錄</p>";
    return;
  }
  container.innerHTML = json.entries.map(e => {
    const isObj = typeof e === "object";
    const ts = isObj ? e.timestamp || "" : "";
    const action = isObj ? e.action || "" : e;
    const actor = isObj ? e.actor || "" : "";
    const detail = isObj && e.details ? (typeof e.details === "string" ? e.details : JSON.stringify(e.details)) : "";
    const chain = isObj && e._chain_hash ? `<span style="color:#4caf50;">█</span>` : "·";
    const isBroken = integrity && integrity.broken_at && Number(e.id) === Number(integrity.broken_at);
    const isFailure = isObj && e.success === false;
    const rowStyle = isBroken
      ? "background:rgba(255,79,109,.22);border:1px solid rgba(255,79,109,.45);"
      : isFailure
        ? "background:rgba(255,79,109,.08);"
        : "";
    const badge = isBroken ? `<span style="color:#ff4f6d;font-weight:bold;">審計異常</span> ` : "";
    return `<div style="border-bottom:1px solid #222;padding:.35rem .25rem;word-break:break-all;${rowStyle}">
      <span style="color:#888;">${ts}</span> ${chain}
      ${badge}
      <span style="color:#e0e0e0;">${sanitize(action)}</span>
      ${actor ? `<span style="color:#82b1ff;"> by ${sanitize(actor)}</span>` : ""}
      ${detail ? `<span style="color:#888;font-size:.68rem;"> ${sanitize(detail)}</span>` : ""}
    </div>`;
  }).join("");
  $("audit-prev").disabled = page === 0;
  $("audit-next").disabled = (page + 1) * AUDIT_PAGE_SIZE >= (json.total || 0);
}

// ── Violations ──────────────────────────────────────────────
let violationsPage = 0;
const VIOLATIONS_PAGE_SIZE = 20;
let violationTargetUser = null;

async function loadViolations(page, username) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const url = username
    ? API + "/admin/violations?page=" + page + "&username=" + encodeURIComponent(username)
    : API + "/admin/violations?page=" + page;
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  violationsPage = page;
  $("violations-total").textContent = json.total || 0;
  const integEl = $("violations-integrity");
  if (integEl) {
    const chainOk = json.integrity === true || (json.integrity && json.integrity.ok === true);
    const chainBad = json.integrity === false || (json.integrity && json.integrity.ok === false);
    integEl.textContent = chainOk ? "🔗 鏈完整" : chainBad ? "⚠️ 鏈已斷！" : "";
    integEl.style.color = chainOk ? "#4caf50" : chainBad ? "#ff4f6d" : "var(--muted)";
  }

  // User pills
  const usersEl = $("violation-users");
  if (usersEl) {
    const selUser = username || violationTargetUser;
    const pillsWrap = document.createElement("div");
    pillsWrap.style.display = "flex";
    pillsWrap.style.flexWrap = "wrap";
    pillsWrap.style.gap = ".25rem";
    pillsWrap.style.alignItems = "center";

    const allBtn = document.createElement("button");
    allBtn.className = "btn";
    allBtn.style.fontSize = ".72rem";
    allBtn.style.padding = ".2rem .5rem";
    allBtn.style.margin = ".1rem";
    allBtn.textContent = "全部";
    allBtn.addEventListener("click", () => loadViolations(0, null));
    pillsWrap.appendChild(allBtn);

    (json.users || []).forEach(u => {
      const btn = document.createElement("button");
      btn.className = "btn";
      if (u.username === selUser) btn.classList.add("btn-primary");
      btn.style.fontSize = ".72rem";
      btn.style.padding = ".2rem .5rem";
      btn.style.margin = ".1rem";
      btn.textContent = `${sanitize(u.username)} (${u.violation_count})`;
      btn.addEventListener("click", () => loadViolations(0, u.username));
      pillsWrap.appendChild(btn);
    });

    usersEl.innerHTML = "";
    usersEl.appendChild(pillsWrap);
    violationTargetUser = username || null;
  }

  const container = $("violation-entries");
  if (!container) return;
  if (!json.entries || json.entries.length === 0) {
    container.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>暫無違規記錄</p>";
    return;
  }
  container.innerHTML = json.entries.map(e => {
    const isObj = typeof e === "object";
    const ts = isObj ? e.timestamp || "" : "";
    const reason = isObj ? e.reason || "" : String(e);
    const username = isObj ? e.username || "" : "";
    const actor = isObj ? e.actor || "" : "";
    const points = isObj ? e.points || 0 : 0;
    const chain = isObj && e._chain_hash ? `<span style="color:#4caf50;">█</span>` : "·";
    return `<div style="border-bottom:1px solid #222;padding:.35rem .25rem;word-break:break-all;">
      <span style="color:#888;">${ts}</span> ${chain}
      ${username ? `<span style="color:#e0e0e0;">${sanitize(username)}</span>` : ""}
      <span style="color:#ff8a80;">${sanitize(reason)}</span>
      ${points ? `<span style="color:#bbb;"> +${points}</span>` : ""}
      ${actor ? `<span style="color:#82b1ff;"> by ${sanitize(actor)}</span>` : ""}
    </div>`;
  }).join("");
  $("violations-prev").disabled = page === 0;
  $("violations-next").disabled = (page + 1) * VIOLATIONS_PAGE_SIZE >= (json.total || 0);
}

async function addViolation(userId) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const reason = prompt("輸入違規原因：");
  if (!reason) return;
  const res = await apiFetch(API + "/admin/users/" + userId + "/violation", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ reason })
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    loadViolations(0, violationTargetUser);
    loadUsers();
  } else {
    alert(json.msg || "新增違規失敗");
  }
}

async function resetViolations(userId) {
  if (!confirm("確定要歸零該用戶違規次數？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/users/" + userId + "/reset-violations", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    loadViolations(0, violationTargetUser);
    loadUsers();
  } else {
    alert(json.msg || "歸零失敗");
  }
}

// ── Governance UI ───────────────────────────────────────────
let governancePendingTargetUserId = "";
const GOVERNANCE_ACTION_VALUE_HELP = {
  warn: "可留空。系統會依提案原因替對象記一次違規警告。",
  mute: "可留空。通過後會將帳號狀態設為 muted，並使其重新登入。",
  restrict: "可留空，或填 ISO 到期時間，例如 2026-05-01T18:00。通過後會限制發文、上傳等功能。",
  suspend: "可留空，或填 ISO 到期時間，例如 2026-05-01T18:00。通過後會暫停帳號使用。",
  downgrade_level: "必填：newbie、normal、restricted 或 suspended。用來調整會員等級。",
  force_password_reset: "可留空。通過後對象下次登入必須重新設定密碼。",
  delete: "可留空。通過後帳號會被標記為 deleted，屬高風險操作。",
};
const GOVERNANCE_HIGH_RISK_ACTIONS = new Set(["suspend", "delete", "downgrade_level"]);

async function loadGovernanceDashboard() {
  await Promise.allSettled([loadUsers(), loadMemberLevelRulesSummary(), loadGovernanceProposals()]);
  renderGovernanceTargetOptions();
  updateGovernanceActionValueHelp();
}

function renderGovernanceTargetOptions(selectedValue = null) {
  const select = $("governance-target-user-id");
  if (!select) return;
  const previous = selectedValue === null
    ? String(select.value || governancePendingTargetUserId || "")
    : String(selectedValue || "");
  const rows = Array.isArray(users) ? users : [];
  if (!rows.length) {
    select.innerHTML = `<option value="">無法讀取會員清單</option>`;
    return;
  }
  const targetRows = rows.filter((user) => user.username !== "root" && String(user.id || "") !== String(currentUserId || ""));
  select.innerHTML = `<option value="">請選擇治理目標</option>` + targetRows.map((user) => {
    const id = String(user.id || "");
    const role = user.username === "root" ? "root" : (user.role || "user");
    const status = user.status || "-";
    const level = user.effective_level || user.member_level || "";
    const label = `${user.username || "unknown"} (#${id}) · ${role} · ${status}${level ? " · " + level : ""}`;
    return `<option value="${sanitize(id)}">${sanitize(label)}</option>`;
  }).join("");
  if (previous && targetRows.some((user) => String(user.id || "") === previous)) {
    select.value = previous;
    governancePendingTargetUserId = "";
  }
}

function selectedGovernanceTarget() {
  const targetId = String($("governance-target-user-id")?.value || "");
  return (Array.isArray(users) ? users : []).find((user) => String(user.id || "") === targetId) || null;
}

function governancePolicySummary(action, target) {
  const targetRole = target?.role || "user";
  const highRisk = GOVERNANCE_HIGH_RISK_ACTIONS.has(action) || targetRole === "manager" || targetRole === "super_admin";
  return highRisk
    ? "高風險：需要 root 同意，且另外需要 2 位 admin/manager 同意。通過後必須由 root 執行。"
    : "一般：需要 1 位 admin/manager 或 root 同意。";
}

function updateGovernanceActionValueHelp() {
  const action = $("governance-action-type")?.value || "warn";
  const input = $("governance-action-value");
  const help = $("governance-action-value-help");
  const policy = $("governance-vote-policy");
  const text = GOVERNANCE_ACTION_VALUE_HELP[action] || "依處理方式填寫；不需要額外參數時可留空。";
  if (help) help.textContent = text;
  if (policy) policy.textContent = governancePolicySummary(action, selectedGovernanceTarget());
  if (input) {
    input.placeholder = action === "downgrade_level"
      ? "newbie / normal / restricted / suspended"
      : action === "restrict" || action === "suspend"
        ? "可留空，或填 2026-05-01T18:00"
        : "通常可留空";
  }
}

async function loadMemberLevelRulesSummary() {
  const container = $("member-level-rules-list");
  if (!container) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/member-level-rules", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    container.innerHTML = `<div style="color:#ffb74d;">${sanitize(json.msg || "會員規則讀取失敗或功能尚未啟用")}</div>`;
    return;
  }
  const rules = Array.isArray(json.rules) ? json.rules : [];
  container.innerHTML = rules.map((r) => {
    const level = r.level || "";
    const flags = [
      r.can_post ? "發文" : "禁發文",
      r.can_comment ? "留言" : "禁留言",
      r.can_send_dm ? "私訊" : "禁私訊",
      r.can_upload_attachment ? "上傳" : "禁上傳",
      r.requires_moderation ? "需審核" : "免審"
    ].join(" · ");
    return `<div style="border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:.6rem;background:rgba(0,0,0,.2);">
      <div style="font-weight:700;color:#e0e0f0;">${sanitize(level)}</div>
      <div style="color:var(--muted);margin-top:.2rem;">${sanitize(flags)}</div>
      <div style="color:#82b1ff;margin-top:.25rem;">post ${r.daily_post_limit ?? "-"} · upload ${r.attachment_quota_mb ?? 0} MB · report weight ${r.report_weight ?? "-"}</div>
    </div>`;
  }).join("");
}

async function loadGovernanceProposals() {
  const list = $("governance-proposal-list");
  const msg = $("governance-msg");
  if (!list) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const status = $("governance-proposal-status")?.value || "";
  const url = API + "/admin/moderation/proposals" + (status ? "?status=" + encodeURIComponent(status) : "");
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    list.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "治理提案讀取失敗")}</div>`;
    if (msg) msg.textContent = "";
    return;
  }
  const proposals = Array.isArray(json.proposals) ? json.proposals : [];
  if (msg) msg.textContent = `共 ${proposals.length} 筆`;
  if (!proposals.length) {
    list.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>目前沒有治理提案</p>";
    return;
  }
  list.innerHTML = proposals.map((p) => {
    const target = p.target?.username || `#${p.target_user_id}`;
    const proposer = p.proposed_by?.username || `#${p.proposed_by_user_id}`;
    const votes = (p.votes || []).map(v => `${sanitize(v.voter_username || "")}:${sanitize(v.vote || "")}`).join(" · ") || "尚無投票";
    const policyText = p.policy_summary || (
      p.required_root_approval
        ? "高風險：需要 root 同意，且另外需要 2 位 admin/manager 同意。"
        : "一般：需要 1 位 admin/manager 或 root 同意。"
    );
    const progressText = p.required_root_approval
      ? `root ${p.root_requirement_met ? "已同意" : "未同意"} · admin/manager ${p.manager_approve_count || 0}/${p.required_manager_approvals || 2} · reject ${p.reject_count || 0}`
      : `${p.approve_count || 0}/${p.required_votes || 1} approve · ${p.reject_count || 0} reject`;
    const canVote = p.status === "pending";
    const canExecute = p.status === "approved";
    return `<div style="border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:.65rem;margin-bottom:.55rem;background:rgba(0,0,0,.22);">
      <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;">
        <strong>#${p.id}</strong>
        <span style="color:#82b1ff;">${sanitize(p.action_type || "")}</span>
        <span>target=${sanitize(target)}</span>
        <span style="color:${p.risk_level === "high" ? "#ffb74d" : "#82b1ff"};">${p.risk_level === "high" ? "高風險" : "一般"}</span>
        <span style="color:${p.status === "approved" ? "#4caf50" : p.status === "rejected" ? "#ff4f6d" : "#ffb74d"};">${sanitize(p.status || "")}</span>
        <span style="margin-left:auto;color:var(--muted);">${sanitize(progressText)}</span>
      </div>
      <div style="color:var(--muted);margin-top:.25rem;">proposer=${sanitize(proposer)} · expires=${sanitize(p.expires_at || "")}</div>
      <div style="color:#82b1ff;margin-top:.25rem;">${sanitize(policyText)}</div>
      <div style="margin-top:.35rem;white-space:pre-wrap;">${sanitize(p.reason || "")}</div>
      <div style="color:var(--muted);margin-top:.35rem;">votes: ${votes}</div>
      <div class="admin-toolbar" style="display:flex;gap:.45rem;margin-top:.5rem;">
        ${canVote ? `<button class="btn btn-primary" data-governance-vote="approve" data-proposal-id="${p.id}">同意</button><button class="btn" data-governance-vote="reject" data-proposal-id="${p.id}">否決</button>` : ""}
        ${canExecute ? `<button class="btn btn-primary" data-governance-execute="${p.id}">執行</button>` : ""}
      </div>
    </div>`;
  }).join("");
  list.querySelectorAll("button[data-governance-vote]").forEach((btn) => {
    btn.addEventListener("click", () => voteGovernanceProposal(btn.getAttribute("data-proposal-id"), btn.getAttribute("data-governance-vote")));
  });
  list.querySelectorAll("button[data-governance-execute]").forEach((btn) => {
    btn.addEventListener("click", () => executeGovernanceProposal(btn.getAttribute("data-governance-execute")));
  });
}

async function createGovernanceProposal() {
  const targetId = parseInt($("governance-target-user-id")?.value || "0", 10);
  const reason = ($("governance-reason")?.value || "").trim();
  if (!targetId || !reason) {
    alert("請選擇治理目標並填寫提案原因");
    return;
  }
  if (String(targetId) === String(currentUserId || "")) {
    alert("不能對自己建立治理提案");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    target_user_id: targetId,
    action_type: $("governance-action-type")?.value || "warn",
    action_value: ($("governance-action-value")?.value || "").trim() || null,
    ttl_hours: parseInt($("governance-ttl-hours")?.value || "72", 10),
    reason
  };
  const res = await apiFetch(API + "/admin/moderation/proposals", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "治理提案已建立" : "治理提案建立失敗"));
  if (json.ok) {
    if ($("governance-reason")) $("governance-reason").value = "";
    await loadGovernanceProposals();
  }
}

async function voteGovernanceProposal(proposalId, vote) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const comment = prompt("投票備註（可空白）") || "";
  const res = await apiFetch(API + `/admin/moderation/proposals/${proposalId}/vote`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ vote, comment })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "已完成投票" : "投票失敗"));
  await loadGovernanceProposals();
}

async function executeGovernanceProposal(proposalId) {
  if (!confirm("確定執行已通過的治理提案？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/admin/moderation/proposals/${proposalId}/execute`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "治理提案已執行" : "執行失敗"));
  await Promise.all([loadGovernanceProposals(), loadUsers()]);
}

function openGovernanceProposalForUser(userId, username) {
  if (String(userId || "") === String(currentUserId || "")) {
    alert("不能對自己建立治理提案");
    return;
  }
  switchAdminTab("governance");
  governancePendingTargetUserId = String(userId || "");
  renderGovernanceTargetOptions(userId);
  if ($("governance-target-user-id")) $("governance-target-user-id").value = userId;
  if ($("governance-reason")) $("governance-reason").value = `針對 ${username || "user #" + userId} 建立治理提案：`;
  updateGovernanceActionValueHelp();
}

function passwordResetReviewSetMsg(text, ok = true) {
  const msg = $("password-reset-review-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.style.color = ok ? "#4caf50" : "#ff4f6d";
}

async function loadPasswordResetReviews() {
  const list = $("password-reset-review-list");
  if (!list) return;
  const status = $("password-reset-review-status")?.value || "pending";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/password-reset-requests?status=" + encodeURIComponent(status), {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    list.innerHTML = "";
    passwordResetReviewSetMsg(json.msg || "密碼重設申請讀取失敗", false);
    return;
  }
  const rows = Array.isArray(json.requests) ? json.requests : [];
  if (!rows.length) {
    list.innerHTML = `<p style="color:var(--muted);">目前沒有密碼重設申請</p>`;
    passwordResetReviewSetMsg("", true);
    return;
  }
  list.innerHTML = rows.map((item) => `
    <div class="admin-card" style="margin-bottom:.65rem;">
      <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;">
        <strong>#${Number(item.id || 0)}</strong>
        <span>${sanitize(item.username || "-")}</span>
        <span style="color:var(--muted);">${sanitize(item.role || "-")} · ${sanitize(item.target_status || "-")}</span>
        <span style="color:${item.status === "pending" ? "#ffb74d" : item.status === "approved" ? "#4caf50" : "#ff4f6d"};">${sanitize(item.status || "")}</span>
        <span style="margin-left:auto;color:var(--muted);">${sanitize(item.created_at || "")}</span>
      </div>
      <div style="color:var(--muted);font-size:.78rem;margin-top:.25rem;">IP: ${sanitize(item.requested_ip || "-")} · reviewed_by: ${sanitize(item.reviewed_by || "-")}</div>
      ${item.review_note ? `<div style="margin-top:.35rem;color:var(--muted);">${sanitize(item.review_note)}</div>` : ""}
      ${item.can_review ? `
        <div class="settings-option-grid" style="margin-top:.6rem;">
          <div class="field">
            <label>臨時密碼</label>
            <input type="password" data-reset-review-pass="${Number(item.id || 0)}" autocomplete="new-password" />
          </div>
          <div class="field">
            <label>確認臨時密碼</label>
            <input type="password" data-reset-review-pass-confirm="${Number(item.id || 0)}" autocomplete="new-password" />
          </div>
          <div class="field">
            <label>審核備註</label>
            <input type="text" data-reset-review-note="${Number(item.id || 0)}" placeholder="可填處理原因或交付方式" />
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <div style="display:flex;gap:.45rem;">
              <button class="btn btn-primary" type="button" data-reset-review-approve="${Number(item.id || 0)}">通過</button>
              <button class="btn" type="button" data-reset-review-reject="${Number(item.id || 0)}">駁回</button>
            </div>
          </div>
        </div>
      ` : ""}
    </div>
  `).join("");
  list.querySelectorAll("[data-reset-review-approve]").forEach((btn) => {
    btn.addEventListener("click", () => approvePasswordResetReview(btn.getAttribute("data-reset-review-approve")));
  });
  list.querySelectorAll("[data-reset-review-reject]").forEach((btn) => {
    btn.addEventListener("click", () => rejectPasswordResetReview(btn.getAttribute("data-reset-review-reject")));
  });
}

async function approvePasswordResetReview(requestId) {
  const proposedPassword = document.querySelector(`[data-reset-review-pass="${CSS.escape(String(requestId))}"]`)?.value || "";
  const passwordConfirm = document.querySelector(`[data-reset-review-pass-confirm="${CSS.escape(String(requestId))}"]`)?.value || "";
  const note = document.querySelector(`[data-reset-review-note="${CSS.escape(String(requestId))}"]`)?.value || "";
  if (!proposedPassword || proposedPassword !== passwordConfirm) {
    passwordResetReviewSetMsg("請輸入一致的臨時密碼", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/admin/password-reset-requests/${encodeURIComponent(requestId)}/approve`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ temporary_password: proposedPassword, temporary_password_confirm: passwordConfirm, note })
  });
  const json = await res.json().catch(() => ({}));
  passwordResetReviewSetMsg(json.msg || (json.ok ? "已通過" : "處理失敗"), !!json.ok);
  if (json.ok) await loadPasswordResetReviews();
}

async function rejectPasswordResetReview(requestId) {
  const note = document.querySelector(`[data-reset-review-note="${CSS.escape(String(requestId))}"]`)?.value || "";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/admin/password-reset-requests/${encodeURIComponent(requestId)}/reject`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ note })
  });
  const json = await res.json().catch(() => ({}));
  passwordResetReviewSetMsg(json.msg || (json.ok ? "已駁回" : "處理失敗"), !!json.ok);
  if (json.ok) await loadPasswordResetReviews();
}

// ── Settings & restart ───────────────────────────────────────
const MEMBER_LEVEL_BOOL_FIELDS = [
  ["can_post", "可發文"],
  ["can_comment", "可留言"],
  ["can_send_dm", "可私訊"],
  ["can_upload_attachment", "可上傳附件"],
  ["can_report", "可檢舉"],
  ["requires_moderation", "發文需審核"],
  ["require_admin_approval", "升等需 admin 核准"],
  ["require_root_approval", "升等需 root 核准"]
];
const MEMBER_LEVEL_INT_FIELDS = [
  ["daily_post_limit", "每日發文上限"],
  ["daily_dm_limit", "每日私訊上限"],
  ["post_rate_limit_per_hour", "每小時發文限制"],
  ["comment_rate_limit_per_hour", "每小時留言限制"],
  ["dm_rate_limit_per_day", "每日私訊 rate limit"],
  ["upload_rate_limit_per_day", "每日上傳限制"],
  ["max_attachment_size_mb", "單檔上限 MB"],
  ["attachment_quota_mb", "總容量 MB"],
  ["report_weight", "檢舉權重"],
  ["min_account_age_days", "升等帳齡天數"],
  ["min_approved_content_count", "升等核准內容數"],
  ["min_points", "升等點數"],
  ["min_trust_score", "升等 trust_score"],
  ["min_reputation", "升等 reputation"],
  ["max_violation_score", "升等最大違規分"],
  ["downgrade_violation_threshold", "降級/處分建議門檻"],
  ["session_idle_timeout_minutes", "閒置登出分鐘"]
];
let editableMemberLevelRules = [];
let rootStorageUsersCache = [];
const CLOUD_DRIVE_POLICY_BOOL_FIELDS = [
  "require_scan_before_download",
  "block_unclean_downloads",
  "warn_high_risk_downloads",
  "allow_inline_preview_for_high_risk",
  "e2ee_server_scan_claim_allowed",
  "revoke_shares_on_suspension",
  "scanner_enabled",
  "fail_closed_on_scanner_error",
  "quarantine_on_infected",
  "validate_magic_mime",
  "deep_archive_scan_enabled",
  "office_macro_scan_enabled",
  "image_reencode_enabled",
  "yara_enabled"
];
const CLOUD_DRIVE_POLICY_INT_FIELDS = [
  "scanner_timeout_seconds",
  "max_archive_depth",
  "image_reencode_max_pixels",
  "max_archive_files",
  "max_archive_uncompressed_bytes",
  "max_daily_downloads"
];
const CLOUD_DRIVE_POLICY_TEXT_FIELDS = [
  "scanner_backend",
  "scanner_command",
  "yara_command",
  "yara_rules_path"
];

function cloudDrivePolicyInputId(key) {
  return "s-cd-" + key.replaceAll("_", "-");
}

async function loadCloudDriveAdminPolicy() {
  if (!currentUser || currentUser !== "root") return;
  const rootEl = $("s-cd-require-scan-before-download");
  if (!rootEl) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/cloud-drive/security-policy", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("cloud-drive-policy-msg");
  if (!json.ok) {
    if (msg) {
      msg.textContent = json.msg || "雲端硬碟安全政策讀取失敗";
      msg.style.color = "#ff4f6d";
    }
    return;
  }
  const p = json.policy || {};
  CLOUD_DRIVE_POLICY_BOOL_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) el.checked = !!p[key];
  });
  CLOUD_DRIVE_POLICY_INT_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) el.value = p[key] ?? 0;
  });
  CLOUD_DRIVE_POLICY_TEXT_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) el.value = p[key] || "";
  });
  if ($("s-cd-notes")) $("s-cd-notes").value = p.notes || "";
  if (msg) msg.textContent = "";
}

async function saveCloudDriveAdminPolicy() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {};
  CLOUD_DRIVE_POLICY_BOOL_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) payload[key] = !!el.checked;
  });
  CLOUD_DRIVE_POLICY_INT_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) payload[key] = parseInt(el.value || "0");
  });
  CLOUD_DRIVE_POLICY_TEXT_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) payload[key] = el.value || "";
  });
  payload.notes = $("s-cd-notes")?.value || "";
  const res = await apiFetch(API + "/admin/cloud-drive/security-policy", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("cloud-drive-policy-msg");
  if (msg) {
    msg.textContent = json.ok ? "雲端硬碟安全政策已儲存" : (json.msg || "儲存失敗");
    msg.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
}

function rootStorageFormatBytes(bytes) {
  if (typeof formatDriveBytes === "function") return formatDriveBytes(bytes);
  if (bytes === null || bytes === undefined) return "無上限";
  return `${Number(bytes || 0)} bytes`;
}

function rootStorageMbFromBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  return Math.round((Number(bytes || 0) / 1024 / 1024) * 100) / 100;
}

function setRootStorageMsg(text, ok = true) {
  const msg = $("root-storage-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function renderRootStorageUsers(users) {
  const list = $("root-storage-users");
  const select = $("root-storage-user-select");
  if (select) {
    const current = select.value;
    select.innerHTML = (users || []).length
      ? `<option value="">選擇要管理的帳號</option>` + users.map((user) => {
          const label = `${user.username || "user"} · ${rootStorageFormatBytes(user.used_bytes || 0)} / ${rootStorageFormatBytes(user.total_bytes)}`;
          return `<option value="${sanitize(String(user.user_id || ""))}" ${String(user.user_id || "") === current ? "selected" : ""}>${sanitize(label)}</option>`;
        }).join("")
      : `<option value="">沒有帳號資料</option>`;
  }
  if (!list) return;
  if (!users || !users.length) {
    list.innerHTML = `<div class="drive-card-sub">目前沒有可管理的帳號用量資料</div>`;
    return;
  }
  list.innerHTML = users.map((user) => {
    const override = user.override || user.root_override || {};
    const overrideText = override.enabled
      ? `root 直接設定中 · ${sanitize(override.reason || "未填原因")}`
      : "沿用角色/會員等級";
    return `<div class="drive-file-row" data-root-storage-user="${sanitize(String(user.user_id || ""))}">
      <div>
        <strong>${sanitize(user.username || `user #${user.user_id}`)}</strong>
        <div class="drive-card-sub">
          ${sanitize(user.role || "user")} · ${sanitize(user.effective_level || user.member_level || "-")} ·
          ${rootStorageFormatBytes(user.used_bytes || 0)} / ${rootStorageFormatBytes(user.total_bytes)} ·
          ${Number(user.percent_used || 0)}% · ${Number(user.file_count || 0)} 個檔案
        </div>
        <div class="drive-card-sub">${sanitize(overrideText)} · quota source=${sanitize(user.quota_source || "-")}</div>
      </div>
      <button class="btn" type="button" data-root-storage-select="${sanitize(String(user.user_id || ""))}">管理</button>
    </div>`;
  }).join("");
}

function fillRootStorageOverrideForm(userId) {
  const user = rootStorageUsersCache.find((item) => String(item.user_id) === String(userId));
  if (!user) return;
  const override = user.override || {};
  if ($("root-storage-user-select")) $("root-storage-user-select").value = String(user.user_id || "");
  if ($("root-storage-quota-mb")) $("root-storage-quota-mb").value = override.enabled ? rootStorageMbFromBytes(override.quota_bytes) : "";
  if ($("root-storage-max-file-mb")) $("root-storage-max-file-mb").value = override.enabled ? rootStorageMbFromBytes(override.max_file_size_bytes) : "";
  if ($("root-storage-daily-limit")) $("root-storage-daily-limit").value = override.enabled && override.upload_rate_limit_per_day !== null && override.upload_rate_limit_per_day !== undefined ? override.upload_rate_limit_per_day : "";
  if ($("root-storage-can-upload")) {
    const value = override.enabled ? override.can_upload_override : null;
    $("root-storage-can-upload").value = value === null || value === undefined ? "inherit" : String(!!value);
  }
  if ($("root-storage-override-reason")) $("root-storage-override-reason").value = override.enabled ? (override.reason || "") : "";
}

async function loadRootStorageUsers() {
  if (!currentUser || currentUser !== "root") return;
  if (!$("root-storage-users")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/storage/users", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    setRootStorageMsg(json.msg || "root 雲端硬碟管理資料讀取失敗", false);
    return;
  }
  rootStorageUsersCache = Array.isArray(json.users) ? json.users : [];
  renderRootStorageUsers(rootStorageUsersCache);
  const selected = $("root-storage-user-select")?.value || rootStorageUsersCache[0]?.user_id || "";
  if (selected) fillRootStorageOverrideForm(selected);
}

async function saveRootStorageOverride() {
  const userId = $("root-storage-user-select")?.value || "";
  if (!userId) {
    setRootStorageMsg("請先選擇帳號", false);
    return;
  }
  const reason = ($("root-storage-override-reason")?.value || "").trim();
  if (!reason) {
    setRootStorageMsg("請填寫覆寫原因", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    enabled: true,
    quota_mb: $("root-storage-quota-mb")?.value || "",
    max_file_size_mb: $("root-storage-max-file-mb")?.value || "",
    upload_rate_limit_per_day: $("root-storage-daily-limit")?.value || "",
    can_upload: $("root-storage-can-upload")?.value || "inherit",
    reason
  };
  const res = await apiFetch(API + `/root/storage/users/${encodeURIComponent(userId)}/quota-override`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  setRootStorageMsg(json.ok ? "root 直接設定已套用" : (json.msg || "設定失敗"), !!json.ok);
  if (json.ok) await loadRootStorageUsers();
}

async function clearRootStorageOverride() {
  const userId = $("root-storage-user-select")?.value || "";
  if (!userId) {
    setRootStorageMsg("請先選擇帳號", false);
    return;
  }
  if (!confirm("清除此帳號的 root 直接雲端硬碟設定？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/root/storage/users/${encodeURIComponent(userId)}/quota-override`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  setRootStorageMsg(json.ok ? "root 直接設定已清除" : (json.msg || "清除失敗"), !!json.ok);
  if (json.ok) await loadRootStorageUsers();
}

let rootEconomyCatalogCache = [];
let rootTradingSettingsCache = { settings: {}, markets: [] };
let rootTradingPriceFusionStatusCache = null;

function rootCatalogMsg(text, ok = true) {
  const msg = $("root-catalog-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function rootCatalogStorageGbFromBytes(bytes) {
  if (!bytes) return "";
  return Math.round((Number(bytes || 0) / 1024 / 1024 / 1024) * 100) / 100;
}

function clearRootCatalogForm() {
  if ($("root-catalog-item-key")) $("root-catalog-item-key").value = "";
  if ($("root-catalog-item-name")) $("root-catalog-item-name").value = "";
  if ($("root-catalog-category")) $("root-catalog-category").value = "comfyui";
  if ($("root-catalog-base-price")) $("root-catalog-base-price").value = "1";
  if ($("root-catalog-min-price")) $("root-catalog-min-price").value = "";
  if ($("root-catalog-max-price")) $("root-catalog-max-price").value = "";
  if ($("root-catalog-dynamic-pricing")) $("root-catalog-dynamic-pricing").checked = false;
  if ($("root-catalog-enabled")) $("root-catalog-enabled").checked = true;
  if ($("root-catalog-storage-gb")) $("root-catalog-storage-gb").value = "";
  if ($("root-catalog-duration-days")) $("root-catalog-duration-days").value = "";
  rootCatalogMsg("");
}

function fillRootCatalogForm(itemKey) {
  const item = rootEconomyCatalogCache.find((row) => row.item_key === itemKey);
  if (!item) return;
  const metadata = item.metadata || {};
  if ($("root-catalog-item-key")) $("root-catalog-item-key").value = item.item_key || "";
  if ($("root-catalog-item-name")) $("root-catalog-item-name").value = item.item_name || "";
  if ($("root-catalog-category")) $("root-catalog-category").value = item.category || "custom";
  if ($("root-catalog-base-price")) $("root-catalog-base-price").value = item.base_price ?? 1;
  if ($("root-catalog-min-price")) $("root-catalog-min-price").value = item.min_price ?? "";
  if ($("root-catalog-max-price")) $("root-catalog-max-price").value = item.max_price ?? "";
  if ($("root-catalog-dynamic-pricing")) $("root-catalog-dynamic-pricing").checked = !!item.dynamic_pricing;
  if ($("root-catalog-enabled")) $("root-catalog-enabled").checked = item.enabled !== 0 && item.enabled !== false;
  if ($("root-catalog-storage-gb")) $("root-catalog-storage-gb").value = rootCatalogStorageGbFromBytes(metadata.storage_bytes);
  if ($("root-catalog-duration-days")) $("root-catalog-duration-days").value = metadata.duration_days || "";
  rootCatalogMsg(`正在編輯 ${item.item_key}`);
}

function renderRootEconomyCatalog(items) {
  const list = $("root-catalog-list");
  if (!list) return;
  if (!items || !items.length) {
    list.innerHTML = `<div class="drive-empty">尚無計費項目</div>`;
    return;
  }
  list.innerHTML = items.map((item) => {
    const metadata = item.metadata || {};
    const enabled = item.enabled !== 0 && item.enabled !== false;
    const storageText = item.category === "cloud_drive"
      ? ` · ${rootCatalogStorageGbFromBytes(metadata.storage_bytes)} GB / ${metadata.duration_days || "-"} 天`
      : "";
    return `<div class="drive-file-row billing-catalog-row">
      <div>
        <strong>${sanitize(item.item_name || item.item_key)}</strong>
        <div class="drive-card-sub">${sanitize(item.item_key || "")}</div>
        <div class="drive-card-sub">${sanitize(item.category || "-")} · ${Number(item.base_price || 0)} 點${storageText} · ${enabled ? "啟用" : "停用"}</div>
      </div>
      <button class="btn" type="button" data-root-catalog-edit="${sanitize(item.item_key || "")}">編輯</button>
    </div>`;
  }).join("");
  list.querySelectorAll("[data-root-catalog-edit]").forEach((btn) => {
    btn.addEventListener("click", () => fillRootCatalogForm(btn.dataset.rootCatalogEdit || ""));
  });
}

async function loadRootEconomyCatalog() {
  if (currentUser !== "root" || !$("root-catalog-list")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/economy/catalog", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    rootCatalogMsg(json.msg || "計費項目讀取失敗", false);
    return;
  }
  rootEconomyCatalogCache = Array.isArray(json.catalog) ? json.catalog : [];
  renderRootEconomyCatalog(rootEconomyCatalogCache);
}

async function saveRootEconomyCatalogItem() {
  if (currentUser !== "root") return;
  const category = $("root-catalog-category")?.value || "custom";
  const metadata = {};
  if (category === "cloud_drive") {
    const gb = Number($("root-catalog-storage-gb")?.value || 0);
    const days = Number($("root-catalog-duration-days")?.value || 0);
    metadata.storage_bytes = Math.round(gb * 1024 * 1024 * 1024);
    metadata.duration_days = Math.round(days);
    metadata.label = $("root-catalog-item-name")?.value || "";
  }
  const payload = {
    item_key: ($("root-catalog-item-key")?.value || "").trim(),
    item_name: ($("root-catalog-item-name")?.value || "").trim(),
    category,
    base_price: Number($("root-catalog-base-price")?.value || 0),
    min_price: $("root-catalog-min-price")?.value || "",
    max_price: $("root-catalog-max-price")?.value || "",
    dynamic_pricing: !!$("root-catalog-dynamic-pricing")?.checked,
    enabled: !!$("root-catalog-enabled")?.checked,
    metadata,
  };
  if (!payload.item_key || !payload.item_name) {
    rootCatalogMsg("請填項目 key 與顯示名稱", false);
    return;
  }
  if (payload.category === "cloud_drive" && (!metadata.storage_bytes || !metadata.duration_days)) {
    rootCatalogMsg("雲端容量商品必須填容量 GB 與有效天數", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/economy/catalog", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  rootCatalogMsg(json.ok ? "計費項目已儲存" : (json.msg || "儲存失敗"), !!json.ok);
  if (json.ok) {
    rootEconomyCatalogCache = Array.isArray(json.catalog) ? json.catalog : [];
    renderRootEconomyCatalog(rootEconomyCatalogCache);
    if (typeof loadEconomy === "function") loadEconomy();
  }
}

function rootTradingSettingsMsg(text, ok = true) {
  const msg = $("root-trading-settings-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function rootTradingPriceFusionMsg(text, ok = true) {
  const msg = $("root-trading-price-fusion-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function renderRootTradingPriceFusionMarketOptions(payload) {
  const select = $("root-trading-price-fusion-market");
  if (!select) return;
  const settings = payload?.settings || {};
  const liveMarkets = Array.isArray(settings.price_fusion_live_markets) ? settings.price_fusion_live_markets : [];
  const labels = new Map(
    (Array.isArray(payload?.markets) ? payload.markets : [])
      .filter((market) => liveMarkets.includes(market.symbol))
      .map((market) => [market.symbol, market.display_symbol || market.symbol])
  );
  const options = liveMarkets.map((symbol) => ({ symbol, label: labels.get(symbol) || symbol.replace("/POINTS", "/USDT") }));
  const previous = select.value;
  if (!options.length) {
    select.innerHTML = `<option value="">沒有支援融合價格的市場</option>`;
    select.disabled = true;
    return;
  }
  select.disabled = false;
  select.innerHTML = options.map((item) => `
    <option value="${sanitize(item.symbol)}">${sanitize(item.label)}</option>
  `).join("");
  select.value = options.some((item) => item.symbol === previous) ? previous : options[0].symbol;
}

function renderRootTradingPriceFusionStatus(status = {}) {
  rootTradingPriceFusionStatusCache = status || {};
  const summary = $("root-trading-price-fusion-summary");
  const providers = $("root-trading-price-fusion-provider-list");
  const excluded = $("root-trading-price-fusion-excluded-list");
  if (!summary || !providers || !excluded) return;
  const state = String(status.state || "inactive");
  const resolvedSource = String(status.resolved_source || "-");
  const resolvedMode = String(status.resolved_mode || status.requested_mode || "-");
  const pricePoints = status.price_points == null ? "-" : `${Number(status.price_points || 0).toLocaleString()} POINTS`;
  const weightsSum = Number(status.weights_sum_percent || 0).toFixed(2);
  const usedRows = Array.isArray(status.providers_used) ? status.providers_used : [];
  const excludedRows = Array.isArray(status.excluded_providers) ? status.excluded_providers : [];
  const message = String(status.message || "").trim();
  const stateLabel = state === "healthy"
    ? "正常"
    : state === "conservative"
      ? "價格來源降級"
      : state === "degraded"
        ? "部分來源排除"
        : state === "unsupported"
          ? "市場不支援"
          : "未啟用融合";
  summary.innerHTML = `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(String(status.market_symbol || "-").replace("/POINTS", "/USDT"))}</strong>
        <div class="drive-card-sub">狀態 ${sanitize(stateLabel)} · 目前價格 ${sanitize(pricePoints)}</div>
        <div class="drive-card-sub">設定來源 ${sanitize(status.configured_source || "-")} · 實際來源 ${sanitize(resolvedSource)} · 模式 ${sanitize(resolvedMode)} · 權重合計 ${sanitize(weightsSum)}%</div>
        ${message ? `<div class="drive-card-sub" style="color:${state === "healthy" ? "#9ecbff" : "#ffb347"};">${sanitize(message)}</div>` : ""}
        ${status.conservative_mode ? `<div class="drive-card-sub" style="color:#ff9aa8;">已進入保守模式：目前不是正常 fused price，建議避免高風險交易。</div>` : ""}
      </div>
    </div>
  `;
  providers.innerHTML = usedRows.length
    ? usedRows.map((row) => `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.label || row.source || "-")}</strong>
          <div class="drive-card-sub">即時占比 ${Number(row.normalized_weight_percent || 0).toFixed(2)}% · 價格 ${Number(row.price_points || 0).toLocaleString()} POINTS</div>
          <div class="drive-card-sub">原始權重 ${Number(row.weight || 0).toFixed(4)} · 深度分數 ${Number(row.depth_score || 0).toFixed(4)}</div>
        </div>
      </div>
    `).join("")
    : `<div class="drive-empty">目前沒有可用的融合來源</div>`;
  excluded.innerHTML = excludedRows.length
    ? excludedRows.map((row) => {
      const reason = row.reason === "fetch_failed"
        ? `API 失效 / timeout / 格式錯誤：${row.error || "未提供細節"}`
        : row.reason === "manual_weight_zero"
          ? "手動權重為 0，因此不參與融合"
          : row.error || row.reason || "已排除";
      return `
        <div class="drive-file-row">
          <div>
            <strong>${sanitize(row.label || row.source || "-")}</strong>
            <div class="drive-card-sub">${sanitize(reason)}</div>
          </div>
        </div>
      `;
    }).join("")
    : `<div class="drive-empty">目前沒有被排除的來源</div>`;
}

async function loadRootTradingPriceFusionStatus() {
  if (currentUser !== "root" || !$("root-trading-price-fusion-summary")) return;
  const selectedMarket = $("root-trading-price-fusion-market")?.value || "";
  if (!selectedMarket) {
    renderRootTradingPriceFusionStatus({
      state: "unsupported",
      market_symbol: "",
      message: "尚無支援融合價格的市場可供檢查。",
      providers_used: [],
      excluded_providers: [],
    });
    return;
  }
  rootTradingPriceFusionMsg("正在抓取目前生效中的融合價格占比...");
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + `/root/trading/price-fusion-status?market_symbol=${encodeURIComponent(selectedMarket)}`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await parseRootTradingSettingsResponse(res);
    if (!res.ok || !json.ok) {
      rootTradingPriceFusionMsg(rootTradingSettingsHttpMessage(res, json, "融合價格診斷讀取失敗"), false);
      return;
    }
    renderRootTradingPriceFusionStatus(json.status || {});
    rootTradingPriceFusionMsg(
      json.status?.conservative_mode
        ? "已抓取融合價格占比，但目前處於價格來源降級/保守模式。"
        : "已更新目前生效中的融合價格占比。"
    );
  } catch (err) {
    rootTradingPriceFusionMsg(err.message || "融合價格診斷請求失敗", false);
  }
}

async function parseRootTradingSettingsResponse(res) {
  const json = await res.clone().json().catch(() => null);
  if (json && typeof json === "object") return json;
  const text = await res.text().catch(() => "");
  const fallback = text && text.length < 160 ? text.trim() : "";
  return {
    ok: false,
    msg: fallback || `HTTP ${res.status}`,
  };
}

function rootTradingSettingsHttpMessage(res, json, fallback) {
  if (res.status === 404) {
    return "交易所參數 API 找不到。請重新整理頁面，並確認目前啟動的是 03.Economy 版本伺服器。";
  }
  return json?.msg || fallback || `HTTP ${res.status}`;
}

function renderRootTradingFusionWeightInputs(settings = {}) {
  const container = $("root-trading-price-fusion-weights");
  if (!container) return;
  const providers = Array.isArray(settings.price_fusion_providers) && settings.price_fusion_providers.length
    ? settings.price_fusion_providers
    : ["binance_public_api", "okx_public_api", "coinbase_exchange", "kraken_public_api", "gemini_public_api", "bitstamp_public_api"];
  const labels = settings.price_fusion_provider_labels && typeof settings.price_fusion_provider_labels === "object"
    ? settings.price_fusion_provider_labels
    : {};
  const weights = settings.price_fusion_manual_weights && typeof settings.price_fusion_manual_weights === "object"
    ? settings.price_fusion_manual_weights
    : {};
  container.innerHTML = providers.map((provider) => `
    <label>
      ${sanitize(labels[provider] || provider)}
      <input type="number" min="0" max="1000" step="0.1" data-trading-price-weight="${sanitize(provider)}" value="${Number(weights[provider] ?? 1)}" />
    </label>
  `).join("");
}

function toggleRootTradingPriceFusionControls() {
  const source = $("root-trading-price-source")?.value || "fused_weighted";
  const mode = $("root-trading-price-fusion-mode")?.value || "auto_depth";
  const modeField = $("root-trading-price-fusion-mode-field");
  const weightsField = $("root-trading-price-fusion-weights-field");
  const fusionEnabled = source === "fused_weighted";
  if (modeField) modeField.hidden = !fusionEnabled;
  if (weightsField) weightsField.hidden = !(fusionEnabled && mode === "manual_weights");
}

function collectRootTradingFusionWeights() {
  const out = {};
  document.querySelectorAll("[data-trading-price-weight]").forEach((input) => {
    out[input.dataset.tradingPriceWeight || ""] = Number(input.value || 0);
  });
  return out;
}

function renderRootTradingSettings(payload) {
  const settings = payload?.settings || {};
  const markets = Array.isArray(payload?.markets) ? payload.markets : [];
  const reserve = payload?.reserve_pool || {};
  if ($("root-trading-enabled")) $("root-trading-enabled").checked = settings.enabled !== false;
  if ($("root-trading-borrowing-enabled")) $("root-trading-borrowing-enabled").checked = !!settings.borrowing_enabled;
  if ($("root-trading-borrow-interest-percent")) $("root-trading-borrow-interest-percent").value = adminPercentValue(settings.borrow_interest_percent_daily ?? 0.1, 0.1);
  if ($("root-trading-borrow-pressure-multiplier")) $("root-trading-borrow-pressure-multiplier").value = Number(settings.borrow_interest_pool_pressure_multiplier ?? 4);
  if ($("root-trading-margin-long-financing-percent")) $("root-trading-margin-long-financing-percent").value = adminPercentValue(settings.margin_long_financing_percent ?? 90, 90);
  if ($("root-trading-short-collateral-percent")) $("root-trading-short-collateral-percent").value = adminPercentValue(settings.short_collateral_percent ?? 60, 60);
  if ($("root-trading-price-source")) $("root-trading-price-source").value = settings.price_source || "fused_weighted";
  if ($("root-trading-price-fusion-mode")) $("root-trading-price-fusion-mode").value = settings.price_fusion_mode || "auto_depth";
  renderRootTradingFusionWeightInputs(settings);
  renderRootTradingPriceFusionMarketOptions(payload);
  const priceSourceSelect = $("root-trading-price-source");
  if (priceSourceSelect && !priceSourceSelect.dataset.fusionBound) {
    priceSourceSelect.addEventListener("change", toggleRootTradingPriceFusionControls);
    priceSourceSelect.dataset.fusionBound = "1";
  }
  const fusionModeSelect = $("root-trading-price-fusion-mode");
  if (fusionModeSelect && !fusionModeSelect.dataset.fusionBound) {
    fusionModeSelect.addEventListener("change", toggleRootTradingPriceFusionControls);
    fusionModeSelect.dataset.fusionBound = "1";
  }
  const fusionRefreshBtn = $("root-trading-price-fusion-refresh-btn");
  if (fusionRefreshBtn && !fusionRefreshBtn.dataset.fusionBound) {
    fusionRefreshBtn.addEventListener("click", loadRootTradingPriceFusionStatus);
    fusionRefreshBtn.dataset.fusionBound = "1";
  }
  const fusionMarketSelect = $("root-trading-price-fusion-market");
  if (fusionMarketSelect && !fusionMarketSelect.dataset.fusionBound) {
    fusionMarketSelect.addEventListener("change", loadRootTradingPriceFusionStatus);
    fusionMarketSelect.dataset.fusionBound = "1";
  }
  toggleRootTradingPriceFusionControls();
  if ($("root-trading-max-price-staleness")) $("root-trading-max-price-staleness").value = settings.max_price_staleness_seconds ?? 900;
  if ($("root-trading-liquidation-enabled")) $("root-trading-liquidation-enabled").checked = settings.margin_liquidation_enabled !== false;
  if ($("root-trading-bot-auto-enabled")) $("root-trading-bot-auto-enabled").checked = settings.bot_auto_scan_enabled !== false;
  if ($("root-trading-bot-auto-interval")) $("root-trading-bot-auto-interval").value = settings.bot_auto_scan_interval_seconds ?? 30;
  if ($("root-trading-bot-auto-limit")) $("root-trading-bot-auto-limit").value = settings.bot_auto_scan_limit ?? 50;
  if ($("root-trading-maintenance-percent")) $("root-trading-maintenance-percent").value = adminPercentValue(settings.margin_maintenance_percent ?? 15, 15);
  if ($("root-trading-futures-enabled")) $("root-trading-futures-enabled").checked = !!settings.futures_enabled;
  if ($("root-trading-pvp-enabled")) $("root-trading-pvp-enabled").checked = !!settings.pvp_matching_enabled;
  if ($("root-trading-reserve-pool")) $("root-trading-reserve-pool").textContent = `${Number(reserve.balance_points || 0)} POINTS`;
  if ($("root-trading-btc-trade-enabled")) $("root-trading-btc-trade-enabled").checked = !!settings.btc_trade_enabled;
  if ($("root-trading-btc-trade-repo")) $("root-trading-btc-trade-repo").value = settings.btc_trade_repo_url || "https://github.com/s9213712/BTC_trade.git";
  if ($("root-trading-btc-trade-branch")) $("root-trading-btc-trade-branch").value = settings.btc_trade_branch || "strategy/v15b-plus";
  if ($("root-trading-btc-trade-path")) $("root-trading-btc-trade-path").value = settings.btc_trade_project_dir || "";
  const list = $("root-trading-market-settings");
  if (!list) return;
  if (!markets.length) {
    list.innerHTML = `<div class="drive-empty">尚無交易市場</div>`;
    return;
  }
  list.innerHTML = markets.map((market) => `
    <div class="drive-file-row billing-catalog-row root-trading-market-row" data-root-trading-market="${sanitize(market.symbol || "")}">
      <div>
        <strong>${sanitize(market.display_symbol || market.symbol || "-")}</strong>
        <div class="drive-card-sub">目前手續費 ${adminFormatPercent(market.fee_rate_percent || 0)}% · 最低 ${Number(market.min_order_points || 0)} · 最高 ${Number(market.max_order_points || 0)} POINTS</div>
      </div>
      <div class="settings-option-grid billing-market-grid">
        <label><input type="checkbox" data-trading-market-field="enabled" ${market.enabled ? "checked" : ""} /> 啟用</label>
        <label>手續費百分比<input type="number" min="0" max="50" step="0.01" data-trading-market-field="fee_rate_percent" value="${adminFormatPercent(market.fee_rate_percent || 0)}" /></label>
        <label>最低交易額<input type="number" min="0" max="1000000000" step="1" data-trading-market-field="min_order_points" value="${Number(market.min_order_points || 0)}" /></label>
        <label>最高交易額<input type="number" min="1" max="1000000000000" step="1" data-trading-market-field="max_order_points" value="${Number(market.max_order_points || 0)}" /></label>
      </div>
    </div>
  `).join("");
  loadRootTradingPriceFusionStatus();
}

async function loadRootTradingSettings() {
  if (currentUser !== "root" || !$("root-trading-market-settings")) return;
  rootTradingSettingsMsg("交易所參數讀取中...");
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + "/root/trading/settings", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await parseRootTradingSettingsResponse(res);
    if (!res.ok || !json.ok) {
      rootTradingSettingsMsg(rootTradingSettingsHttpMessage(res, json, "交易所參數讀取失敗"), false);
      return;
    }
    rootTradingSettingsCache = json;
    renderRootTradingSettings(json);
    rootTradingSettingsMsg("");
  } catch (err) {
    rootTradingSettingsMsg(err.message || "交易所參數讀取請求失敗", false);
  }
}

function collectRootTradingMarketSettings() {
  return Array.from(document.querySelectorAll("[data-root-trading-market]")).map((row) => {
    const symbol = row.dataset.rootTradingMarket || "";
    const payload = { symbol };
    row.querySelectorAll("[data-trading-market-field]").forEach((input) => {
      const key = input.dataset.tradingMarketField;
      payload[key] = input.type === "checkbox" ? input.checked : (key === "fee_rate_percent" ? adminInputPercent(input.value) : Number(input.value || 0));
    });
    return payload;
  });
}

async function saveRootTradingSettings() {
  if (currentUser !== "root") return;
  const saveBtn = $("root-trading-settings-save-btn");
  const wasBtcTradeEnabled = rootTradingSettingsCache?.settings?.btc_trade_enabled === true;
  const willBtcTradeEnable = !!$("root-trading-btc-trade-enabled")?.checked;
  if (saveBtn) saveBtn.disabled = true;
  rootTradingSettingsMsg("交易所參數儲存中...");
  const payload = {
    settings: {
      enabled: !!$("root-trading-enabled")?.checked,
      borrowing_enabled: !!$("root-trading-borrowing-enabled")?.checked,
      borrow_interest_percent_daily: adminInputPercent($("root-trading-borrow-interest-percent")?.value || 0),
      borrow_interest_pool_pressure_multiplier: Number($("root-trading-borrow-pressure-multiplier")?.value || 0),
      margin_long_financing_percent: adminInputPercent($("root-trading-margin-long-financing-percent")?.value || 90, 90),
      short_collateral_percent: adminInputPercent($("root-trading-short-collateral-percent")?.value || 60, 60),
      price_source: ($("root-trading-price-source")?.value || "fused_weighted"),
      price_fusion_mode: ($("root-trading-price-fusion-mode")?.value || "auto_depth"),
      price_fusion_manual_weights: collectRootTradingFusionWeights(),
      max_price_staleness_seconds: Number($("root-trading-max-price-staleness")?.value || 0),
      margin_liquidation_enabled: !!$("root-trading-liquidation-enabled")?.checked,
      bot_auto_scan_enabled: !!$("root-trading-bot-auto-enabled")?.checked,
      bot_auto_scan_interval_seconds: Number($("root-trading-bot-auto-interval")?.value || 30),
      bot_auto_scan_limit: Number($("root-trading-bot-auto-limit")?.value || 50),
      margin_maintenance_percent: adminInputPercent($("root-trading-maintenance-percent")?.value || 0),
      futures_enabled: !!$("root-trading-futures-enabled")?.checked,
      pvp_matching_enabled: !!$("root-trading-pvp-enabled")?.checked,
      btc_trade_enabled: willBtcTradeEnable,
      btc_trade_repo_url: ($("root-trading-btc-trade-repo")?.value || "").trim(),
      btc_trade_branch: ($("root-trading-btc-trade-branch")?.value || "").trim(),
      btc_trade_project_dir: ($("root-trading-btc-trade-path")?.value || "").trim(),
    },
    markets: collectRootTradingMarketSettings(),
  };
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/root/trading/settings", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload)
    });
    const json = await parseRootTradingSettingsResponse(res);
    rootTradingSettingsMsg(
      res.ok && json.ok ? "交易所參數已儲存" : rootTradingSettingsHttpMessage(res, json, "交易所參數儲存失敗"),
      !!(res.ok && json.ok)
    );
    if (res.ok && json.ok) {
      rootTradingSettingsCache = json;
      renderRootTradingSettings(json);
      loadRootTradingPriceFusionStatus();
      if (typeof loadTradingDashboard === "function") loadTradingDashboard();
      if (willBtcTradeEnable && !wasBtcTradeEnabled) {
        await setupRootBtcTrade({ automatic: true });
      }
    }
  } catch (err) {
    rootTradingSettingsMsg(err.message || "交易所參數儲存請求失敗", false);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function checkRootBtcTradeStatus() {
  if (currentUser !== "root") return;
  const status = $("root-trading-btc-trade-status");
  const button = $("root-trading-btc-trade-check-btn");
  const projectDir = ($("root-trading-btc-trade-path")?.value || "").trim();
  if (button) button.disabled = true;
  if (status) {
    status.textContent = "BTC_trade 狀態檢查中...";
    status.style.color = "var(--muted)";
  }
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/trading/btc-trade/check", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
      body: JSON.stringify({ project_dir: projectDir }),
    });
    const json = await parseRootTradingSettingsResponse(res);
    const info = json.status || {};
    if (status) {
      const missing = Array.isArray(info.missing) && info.missing.length ? `；缺少 ${info.missing.join(", ")}` : "";
      const commands = Array.isArray(info.commands) && info.commands.length ? `；初始化：cd ${projectDir || "BTC_trade"} && ${info.commands.join(" && ")}` : "";
      status.textContent = res.ok && json.ok
        ? `${info.available ? "可用" : "不可用"}：${info.message || "-"}${missing}${info.needs_initialization ? commands : ""}`
        : (json.msg || `HTTP ${res.status}`);
      status.style.color = res.ok && json.ok && info.available ? "#4caf50" : "#ffb74d";
    }
  } catch (err) {
    if (status) {
      status.textContent = err.message || "BTC_trade 狀態檢查失敗";
      status.style.color = "#ff4f6d";
    }
  } finally {
    if (button) button.disabled = false;
  }
}

function formatBtcTradeStepResult(step) {
  if (!step || typeof step !== "object") return "";
  const label = step.label || step.command || "step";
  const state = step.ok ? "成功" : "失敗";
  const detail = step.message || step.error || (step.stderr_tail ? step.stderr_tail.split("\n").filter(Boolean).slice(-1)[0] : "");
  return `${label}${state}${detail ? `：${detail}` : ""}`;
}

async function setupRootBtcTrade(options = {}) {
  if (currentUser !== "root") return;
  const status = $("root-trading-btc-trade-status");
  const button = $("root-trading-btc-trade-setup-btn");
  const projectDir = ($("root-trading-btc-trade-path")?.value || "").trim();
  const repoUrl = ($("root-trading-btc-trade-repo")?.value || "").trim();
  const branch = ($("root-trading-btc-trade-branch")?.value || "").trim();
  if (button) button.disabled = true;
  if (status) {
    status.textContent = options.automatic ? "已啟用 BTC_trade，開始自動下載/更新並建置..." : "BTC_trade 下載/更新並建置中，可能需要數分鐘...";
    status.style.color = "var(--muted)";
  }
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/trading/btc-trade/setup", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
      body: JSON.stringify({ project_dir: projectDir, repo_url: repoUrl, branch }),
    });
    const json = await parseRootTradingSettingsResponse(res);
    const result = json.result || {};
    if (json.project_dir && $("root-trading-btc-trade-path") && !$("root-trading-btc-trade-path").value.trim()) {
      $("root-trading-btc-trade-path").value = json.project_dir;
    }
    if (status) {
      const steps = Array.isArray(result.steps) && result.steps.length
        ? `；步驟：${result.steps.map(formatBtcTradeStepResult).join(" / ")}`
        : "";
      status.textContent = res.ok && json.ok
        ? `${json.setup_ok ? "建置完成" : "建置未完成"}：${json.message || result.message || "-"}${steps}`
        : (json.msg || `HTTP ${res.status}`);
      status.style.color = res.ok && json.ok && json.setup_ok ? "#4caf50" : "#ffb74d";
    }
    if (res.ok && json.ok && json.setup_ok && typeof loadTradingDashboard === "function") {
      loadTradingDashboard();
    }
  } catch (err) {
    if (status) {
      status.textContent = err.message || "BTC_trade 建置請求失敗，請自行建置後再檢查";
      status.style.color = "#ff4f6d";
    }
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadEditableMemberLevelRules() {
  if (!currentUser || currentUser !== "root") return;
  const container = $("settings-member-level-rules");
  if (!container) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/member-level-rules", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    container.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "會員等級規則讀取失敗")}</div>`;
    return;
  }
  editableMemberLevelRules = Array.isArray(json.rules) ? json.rules : [];
  const selected = $("settings-member-level-select")?.value || editableMemberLevelRules[0]?.level || "normal";
  container.innerHTML = `
    <div class="member-level-toolbar">
      <div class="field">
        <label>會員等級</label>
        <select id="settings-member-level-select">
          ${editableMemberLevelRules.map((rule) => `<option value="${sanitize(rule.level || "")}" ${rule.level === selected ? "selected" : ""}>${sanitize(rule.level || "")}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>操作</label>
        <button class="btn btn-primary" type="button" id="member-level-rule-save-btn">儲存此等級規則</button>
      </div>
    </div>
    <div id="settings-member-level-editor"></div>
  `;
  const select = $("settings-member-level-select");
  if (select) select.addEventListener("change", () => renderSelectedMemberLevelRule(select.value));
  const saveBtn = $("member-level-rule-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", () => saveMemberLevelRule($("settings-member-level-select")?.value || ""));
  renderSelectedMemberLevelRule(selected);
}

function renderSelectedMemberLevelRule(level) {
  const editor = $("settings-member-level-editor");
  if (!editor) return;
  const rule = editableMemberLevelRules.find((item) => item.level === level) || editableMemberLevelRules[0];
  if (!rule) {
    editor.innerHTML = `<div style="color:#ff4f6d;">尚無會員等級規則</div>`;
    return;
  }
  const bools = MEMBER_LEVEL_BOOL_FIELDS.map(([key, label]) => `
      <label class="member-level-toggle" title="${sanitize(label)}">
        <input type="checkbox" data-level="${sanitize(level)}" data-rule-bool="${key}" ${rule[key] ? "checked" : ""} />
        <span>${sanitize(label)}</span>
      </label>
    `).join("");
  const ints = MEMBER_LEVEL_INT_FIELDS.map(([key, label]) => `
      <label class="member-level-number-field" title="${sanitize(label)}">
        <span>${sanitize(label)}</span>
        <input type="number" min="0" data-level="${sanitize(level)}" data-rule-int="${key}" value="${Number(rule[key] || 0)}" />
      </label>
    `).join("");
  editor.innerHTML = `<div class="member-level-editor-card">
      <div class="member-level-editor-head">
        <strong>${sanitize(rule.level || level)}</strong>
        <span>權限開關與限額門檻</span>
      </div>
      <div class="member-level-subtitle">權限開關</div>
      <div class="member-level-toggle-grid">${bools}</div>
      <div class="member-level-subtitle">限額與升降級門檻</div>
      <div class="member-level-number-grid">${ints}</div>
    </div>`;
}

async function saveMemberLevelRule(level) {
  if (!level) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const container = $("settings-member-level-rules");
  const payload = {};
  MEMBER_LEVEL_BOOL_FIELDS.forEach(([key]) => {
    const el = container?.querySelector(`[data-level="${CSS.escape(level)}"][data-rule-bool="${key}"]`);
    if (el) payload[key] = !!el.checked;
  });
  MEMBER_LEVEL_INT_FIELDS.forEach(([key]) => {
    const el = container?.querySelector(`[data-level="${CSS.escape(level)}"][data-rule-int="${key}"]`);
    if (el) payload[key] = parseInt(el.value || "0");
  });
  const res = await apiFetch(API + "/admin/member-level-rules/" + encodeURIComponent(level), {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("member-level-settings-msg");
  if (msg) {
    msg.textContent = json.ok ? `${level} 規則已儲存` : (json.msg || "會員等級規則儲存失敗");
    msg.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) loadMemberLevelRulesSummary();
}

async function loadServerMode() {
  if (!currentUser || currentUser !== "root") return;
  const status = $("server-mode-status");
  if (!$("server-mode-select")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/server-mode", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    if (status) {
      const detail = json.msg || json.error || `HTTP ${res.status}`;
      status.textContent = `伺服器模式讀取失敗：${detail}`;
      status.style.color = "#ff4f6d";
    }
    return;
  }
  const mode = json.mode || {};
  currentServerMode = String(mode.current_mode || "dev_ready").trim().toLowerCase();
  populateSecurityProfiles(json.profiles || securityProfiles, mode.current_mode || "dev_ready");
  if (status) {
    const previous = mode.previous_mode ? `，上一個模式：${mode.previous_mode}` : "";
    const snapshot = mode.active_snapshot_id ? `，active snapshot：${mode.active_snapshot_id}` : "";
    const checkpoint = mode.checkpoint_id ? `，checkpoint：${mode.checkpoint_id}` : "";
    const phrase = serverModeConfirmPhrase(mode.current_mode || "dev_ready");
    status.textContent = `目前模式：${mode.current_mode || "dev_ready"}${previous}${snapshot}${checkpoint}。切換此模式需輸入：${phrase}`;
    status.style.color = mode.current_mode === "superweak" || mode.current_mode === "incident_lockdown" ? "#ff4f6d" : "var(--muted)";
  }
  updateServerModeTokenPanels(currentServerMode);
  renderServerModeRequirements(json.production_requirements || {});
  await loadServerModeLogs();
  await loadInternalTestTokenStatus();
  await loadTesterTokens();
}

function serverModeConfirmPhrase(mode) {
  const key = String(mode || "").trim();
  return {
    production: "GO_LIVE",
    preprod: "SWITCH_TO_DEV_READY",
    dev_ready: "SWITCH_TO_DEV_READY",
    test: "SWITCH_TO_TEST",
    internal_test: "SWITCH_TO_INTERNAL_TEST",
    maintenance: "ENTER_MAINTENANCE",
    incident_lockdown: "ENTER_INCIDENT_LOCKDOWN",
    superweak: "ENABLE_SUPERWEAK"
  }[key] || "SWITCH_CUSTOM_MODE";
}

function serverModeSupportsInternalTestToken(mode) {
  return String(mode || "").trim().toLowerCase() === "internal_test";
}

function serverModeSupportsTesterToken(mode) {
  const value = String(mode || "").trim().toLowerCase();
  return value === "test" || value === "internal_test";
}

function updateServerModeTokenPanels(modeOverride = null) {
  const mode = String(modeOverride || $("server-mode-select")?.value || currentServerMode || "dev_ready").trim().toLowerCase();
  const internalPanel = $("server-mode-internal-test-panel");
  const testerPanel = $("server-mode-tester-token-panel");
  const hint = $("server-mode-token-hint");
  const showInternal = serverModeSupportsInternalTestToken(mode);
  const showTester = serverModeSupportsTesterToken(mode);
  if (internalPanel) internalPanel.style.display = showInternal ? "" : "none";
  if (testerPanel) testerPanel.style.display = showTester ? "" : "none";
  if (!hint) return;
  if (showInternal) {
    hint.textContent = "目前模式可管理內測登入 token 與 tester token。";
  } else if (showTester) {
    hint.textContent = "目前模式可管理 tester token。若要開放內測登入 token，請切到 internal_test。";
  } else {
    hint.textContent = "切到 test 或 internal_test 才會顯示 tester token；切到 internal_test 才會顯示內測登入 token。";
  }
  hint.style.color = "var(--muted)";
}

function renderServerModeRequirements(requirements) {
  const host = $("server-mode-requirements");
  if (!host) return;
  const missing = Array.isArray(requirements.missing) ? requirements.missing : [];
  const failed = Array.isArray(requirements.failed) ? requirements.failed : [];
  const required = Array.isArray(requirements.required) ? requirements.required : [];
  host.innerHTML = `
    <div><strong>Production gate</strong>：${requirements.ok ? "已通過" : "未通過"}</div>
    <div>必要報告：${required.join(", ") || "-"}</div>
    <div>缺少：${missing.join(", ") || "無"}；失敗：${failed.join(", ") || "無"}</div>
  `;
}

async function loadServerModeLogs() {
  const host = $("server-mode-logs");
  if (!host || currentUser !== "root") return;
  try {
    const res = await apiFetch(API + "/root/server-mode/logs?limit=5", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "讀取失敗");
    const logs = Array.isArray(json.logs) ? json.logs : [];
    host.innerHTML = `
      <div><strong>最近模式切換</strong></div>
      ${logs.length ? logs.map((row) => `
        <div>${row.created_at || "-"}：${row.from_mode || "-"} → ${row.to_mode || "-"} · ${row.success ? "成功" : "失敗"} · ${row.reason || ""}</div>
      `).join("") : "<div>尚無紀錄</div>"}
    `;
  } catch (err) {
    host.textContent = `模式切換紀錄讀取失敗：${err.message || "未知錯誤"}`;
  }
}

async function loadInternalTestTokenStatus() {
  if (currentUser !== "root") return;
  const status = $("internal-test-token-status");
  if (!status) return;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/admin/access-controls", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "讀取失敗");
    const access = json.access_controls || {};
    const configured = !!access.internal_test_token_configured;
    const expired = !!access.internal_test_token_expired;
    const expires = access.internal_test_token_expires_at || "-";
    status.textContent = configured ? `已設定，${expired ? "已過期" : "有效"}，到期：${expires}` : "尚未設定內測 token";
    status.style.color = configured && !expired ? "#4caf50" : "var(--muted)";
  } catch (err) {
    status.textContent = err.message || "內測 token 狀態讀取失敗";
    status.style.color = "#ff4f6d";
  }
}

function testerTokenMsg(text, ok = true) {
  const msg = $("tester-token-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function testerTokenListMarkup(tokens) {
  if (!Array.isArray(tokens) || !tokens.length) return `<div class="drive-empty">尚無 Server Mode v2 tester token</div>`;
  return tokens.map((testerEntry) => {
    const revoked = !!testerEntry.revoked_at;
    const routes = Array.isArray(testerEntry.allowed_routes) ? testerEntry.allowed_routes.join(", ") : "-";
    return `<div class="drive-file-row">
      <div>
        <strong>${sanitize(testerEntry.id || "-")}</strong>
        <div class="drive-card-sub">user #${sanitize(String(testerEntry.tester_user_id || "-"))} · 到期 ${sanitize(testerEntry.expires_at || "-")} · ${revoked ? "已撤銷" : "有效"}</div>
        <div class="drive-card-sub">routes: ${sanitize(routes || "-")} · rpm ${sanitize(String(testerEntry.max_requests_per_minute || "-"))}</div>
      </div>
      ${revoked ? "" : `<button class="btn" type="button" data-revoke-tester-entry="${sanitize(testerEntry.id || "")}">撤銷</button>`}
    </div>`;
  }).join("");
}

async function loadTesterTokens() {
  if (currentUser !== "root" || !$("tester-token-list")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/tester-token/list", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    testerTokenMsg(json.msg || "tester token 清單讀取失敗", false);
    return;
  }
  const list = $("tester-token-list");
  list.innerHTML = testerTokenListMarkup(json.tokens || []);
  list.querySelectorAll("[data-revoke-tester-entry]").forEach((btn) => {
    btn.addEventListener("click", () => revokeTesterToken(btn.dataset.revokeTesterEntry || ""));
  });
}

async function createTesterToken() {
  if (currentUser !== "root") return;
  const userId = Number($("tester-token-user-id")?.value || 0);
  const expiresAt = $("tester-token-expires-at")?.value || "";
  if (!userId || !expiresAt) {
    testerTokenMsg("請填測試員 user id 與到期時間", false);
    return;
  }
  const routes = ($("tester-token-routes")?.value || "/api/tester")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/tester-token/create", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({
      tester_user_id: userId,
      expires_at: expiresAt,
      allowed_routes: routes,
      max_requests_per_minute: Number($("tester-token-rpm")?.value || 60),
      can_modify_own_role: !!$("tester-token-can-role")?.checked,
      can_modify_own_points: !!$("tester-token-can-points")?.checked,
      can_run_security_tests: !!$("tester-token-can-security")?.checked
    })
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    testerTokenMsg(json.msg || "建立 tester token 失敗", false);
    return;
  }
  const wrap = $("tester-token-created-wrap");
  const out = $("tester-token-created");
  if (wrap) wrap.style.display = "block";
  if (out) {
    out.value = json.token || "";
    out.focus();
    out.select();
  }
  testerTokenMsg(`tester token 已建立：${json.token_id || "-"}`, true);
  await loadTesterTokens();
}

async function revokeTesterToken(tokenId) {
  if (currentUser !== "root" || !tokenId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/tester-token/revoke", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ token_id: tokenId, reason: "root revoked from UI" })
  });
  const json = await res.json().catch(() => ({}));
  testerTokenMsg(json.ok ? "tester token 已撤銷" : (json.msg || "撤銷失敗"), !!json.ok);
  await loadTesterTokens();
}

async function rotateInternalTestToken() {
  const confirmText = $("internal-test-token-confirm")?.value || "";
  const msg = $("internal-test-token-msg");
  if (confirmText !== "ROTATE_INTERNAL_TEST_TOKEN") {
    if (msg) flash(msg, "確認字串必須等於 ROTATE_INTERNAL_TEST_TOKEN", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const ttl = parseInt($("internal-test-token-ttl")?.value || "1440", 10);
  const res = await apiFetch(API + "/admin/access-controls/internal-test-token", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ confirm: confirmText, ttl_minutes: ttl })
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    if (msg) flash(msg, json.msg || "產生內測 token 失敗", false);
    return;
  }
  const outWrap = $("internal-test-token-output-wrap");
  const out = $("internal-test-token-output");
  if (outWrap) outWrap.style.display = "block";
  if (out) {
    out.value = json.token || "";
    out.focus();
    out.select();
  }
  if ($("internal-test-token-confirm")) $("internal-test-token-confirm").value = "";
  if (msg) flash(msg, `內測 token 已產生，到期：${json.expires_at || "-"}`, true);
  await loadInternalTestTokenStatus();
}

async function applyServerMode() {
  const target = $("server-mode-select")?.value || "dev_ready";
  const confirmText = $("server-mode-confirm")?.value || "";
  const notes = $("server-mode-notes")?.value || "";
  const expectedConfirm = serverModeConfirmPhrase(target);
  if (confirmText !== expectedConfirm) {
    alert(`切換到 ${target} 必須在確認欄輸入 ${expectedConfirm}`);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/server-mode/switch", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ mode: target, confirm: confirmText, notes })
  });
  const json = await res.json().catch(() => ({}));
  const status = $("server-mode-status");
  if (status) {
    status.textContent = json.ok ? "伺服器模式已更新" : (json.msg || "伺服器模式更新失敗");
    status.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) {
    if (json.profile) {
      applySecurityProfileDataToInputs(json.profile, "s");
      applySecurityProfileDataToInputs(json.profile, "sc");
    }
    if ($("server-mode-confirm")) $("server-mode-confirm").value = "";
    await loadServerMode();
    await loadSecurityCenter();
    await loadSettings();
  }
}

function updateComfyuiConnectionModeFields() {
  const mode = $("s-comfyui-connection-mode")?.value || "remote";
  const localBox = $("comfyui-local-settings");
  const remoteBox = $("comfyui-remote-settings");
  const civitaiBox = $("comfyui-civitai-settings");
  const civitaiInput = $("s-comfyui-civitai-api-key");
  if (localBox) localBox.style.display = mode === "local" ? "" : "none";
  if (remoteBox) remoteBox.style.display = mode === "remote" ? "" : "none";
  if (civitaiBox) civitaiBox.style.display = mode === "local" ? "" : "none";
  if (civitaiInput) civitaiInput.disabled = mode !== "local";
  const status = $("comfyui-test-connection-status");
  if (status && !status.dataset.userTouched) {
    status.textContent = mode === "local"
      ? "本地模式會測試本地 API；若產圖時 API 未啟動，後端會嘗試執行啟動腳本。"
      : "遠端模式只負責呼叫指定 API 生圖，無法透過 API 把模型下載回本站的本地 ComfyUI，所以會隱藏本地模型下載與 Civitai API Key。";
    status.style.color = "var(--muted)";
  }
  if (typeof updateComfyuiRootPanelVisibility === "function") updateComfyuiRootPanelVisibility(mode);
}

function updateCaptchaModeFields() {
  const mode = $("s-captcha-mode")?.value || "none";
  const wrap = $("captcha-turnstile-site-key-field");
  const input = $("s-captcha-turnstile-site-key");
  const showTurnstile = mode === "turnstile";
  if (wrap) wrap.style.display = showTurnstile ? "" : "none";
  if (input) input.disabled = !showTurnstile;
}

async function loadSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/settings", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  const s = json.settings || {};
  const bind = json.server_bind || {};
  const ssl = json.server_ssl || {};
  if ($("s-maintenance-mode")) $("s-maintenance-mode").checked = !!s.maintenance_mode;
  if ($("s-audit-chain-enabled")) $("s-audit-chain-enabled").checked = !!s.audit_chain_enabled;
  if ($("s-ip-blocking-enabled")) $("s-ip-blocking-enabled").checked = !!s.ip_blocking_enabled;
  if ($("s-login-violation-enabled")) $("s-login-violation-enabled").checked = !!s.login_violation_enabled;
  if ($("s-rate-limit-violation-enabled")) $("s-rate-limit-violation-enabled").checked = !!s.rate_limit_violation_enabled;
  if ($("s-root-ip-whitelist-enabled")) $("s-root-ip-whitelist-enabled").checked = !!s.root_ip_whitelist_enabled;
  if ($("s-root-ip-whitelist")) $("s-root-ip-whitelist").value = s.root_ip_whitelist || "";
  if ($("s-browser-only-mode-enabled")) $("s-browser-only-mode-enabled").checked = !!s.browser_only_mode_enabled;
  if ($("s-integrity-guard-enabled")) $("s-integrity-guard-enabled").checked = !!s.integrity_guard_enabled;
  if ($("s-integrity-guard-strict-mode")) $("s-integrity-guard-strict-mode").checked = !!s.integrity_guard_strict_mode;
  if ($("s-allow-register")) $("s-allow-register").checked = !!s.allow_register;
  if ($("s-require-email")) $("s-require-email").checked = !!s.require_email_verification;
  if ($("s-password-reset-mode")) $("s-password-reset-mode").value = s.password_reset_mode || "admin_review";
  if ($("s-captcha-mode")) $("s-captcha-mode").value = s.captcha_mode || "none";
  if ($("s-captcha-ttl-seconds")) $("s-captcha-ttl-seconds").value = s.captcha_ttl_seconds || 300;
  if ($("s-captcha-turnstile-site-key")) $("s-captcha-turnstile-site-key").value = s.captcha_turnstile_site_key || "";
  updateCaptchaModeFields();
  if ($("s-max-fail")) $("s-max-fail").value = s.max_login_failures || 5;
  if ($("s-block-dur")) $("s-block-dur").value = s.block_duration_minutes || 30;
  if ($("s-session-ttl")) $("s-session-ttl").value = s.session_ttl_hours || 24;
  if ($("s-session-idle-timeout")) $("s-session-idle-timeout").value = s.session_idle_timeout_minutes || 10;
  if ($("s-server-ssl-enabled")) $("s-server-ssl-enabled").checked = !!s.server_ssl_enabled;
  if ($("s-server-listen-host")) $("s-server-listen-host").value = s.server_listen_host || "";
  if ($("s-server-listen-port")) $("s-server-listen-port").value = s.server_listen_port || "";
  if ($("s-comfyui-connection-mode")) $("s-comfyui-connection-mode").value = s.comfyui_connection_mode || "remote";
  if ($("s-comfyui-remote-api-url")) $("s-comfyui-remote-api-url").value = s.comfyui_remote_api_url || "";
  if ($("s-comfyui-base-dir")) $("s-comfyui-base-dir").value = s.comfyui_base_dir || "";
  if ($("s-comfyui-local-start-script")) $("s-comfyui-local-start-script").value = s.comfyui_local_start_script || "";
  if ($("s-comfyui-api-host")) $("s-comfyui-api-host").value = s.comfyui_api_host || "localhost";
  if ($("s-comfyui-api-port")) $("s-comfyui-api-port").value = s.comfyui_api_port || 8192;
  if ($("s-comfyui-civitai-api-key")) $("s-comfyui-civitai-api-key").value = s.comfyui_civitai_api_key || "";
  updateComfyuiConnectionModeFields();
  if ($("s-comfyui-max-batch-size")) $("s-comfyui-max-batch-size").value = s.comfyui_max_batch_size || 1;
  if ($("s-comfyui-default-width")) $("s-comfyui-default-width").value = s.comfyui_default_width || 1024;
  if ($("s-comfyui-default-height")) $("s-comfyui-default-height").value = s.comfyui_default_height || 1024;
  if ($("s-cloud-drive-storage-root")) $("s-cloud-drive-storage-root").value = s.cloud_drive_storage_root || "";
  if ($("s-cloud-drive-transfer-limits-enabled")) $("s-cloud-drive-transfer-limits-enabled").checked = !!s.cloud_drive_transfer_limits_enabled;
  renderCloudDriveTransferLimits(s.cloud_drive_transfer_limits_json);
  if ($("s-storage-maintenance-auto-enabled")) $("s-storage-maintenance-auto-enabled").checked = !!s.storage_maintenance_auto_enabled;
  if ($("s-storage-maintenance-daily-time")) $("s-storage-maintenance-daily-time").value = s.storage_maintenance_daily_time || "04:00";
  if ($("s-storage-trash-retention-days")) $("s-storage-trash-retention-days").value = s.storage_trash_retention_days || 30;
  if ($("s-snapshot-daily-auto-enabled")) $("s-snapshot-daily-auto-enabled").checked = !!s.snapshot_daily_auto_enabled;
  if ($("s-snapshot-daily-time")) $("s-snapshot-daily-time").value = s.snapshot_daily_time || "03:00";
  const bindStatus = $("server-bind-status");
  if (bindStatus) {
    const restartText = bind.restart_required ? "需重啟才會套用新 listen 設定" : "目前執行中的 listen 設定已一致";
    bindStatus.textContent = `目前 ${bind.current_host || bind.host || "0.0.0.0"}:${bind.current_port || bind.port || 5000}，下次啟動 ${bind.host || "0.0.0.0"}:${bind.port || 5000}。${restartText}`;
    bindStatus.style.color = bind.restart_required ? "#ffb74d" : "var(--muted)";
  }
  const sslStatus = $("server-ssl-status");
  if (sslStatus) {
    let detail = `目前 ${ssl.current_scheme || "http"}，下次啟動 ${ssl.scheme || "http"}。`;
    if (ssl.cert_required) detail += " 已要求 HTTPS，但缺少 cert.pem 或 key.pem。";
    else if (!ssl.enabled_by_setting) detail += " root 設定為停用 HTTPS。";
    else detail += " HTTPS 憑證檢查通過。";
    if (ssl.restart_required) detail += " 需重啟才會套用。";
    sslStatus.textContent = detail;
    sslStatus.style.color = ssl.cert_required || ssl.restart_required ? "#ffb74d" : "var(--muted)";
  }
  const driveStorage = json.cloud_drive_storage || {};
  const driveStorageStatus = $("cloud-drive-storage-status");
  if (driveStorageStatus) {
    const restartText = driveStorage.restart_required ? "需重啟服務器才會切到新儲存根目錄" : "目前執行中的儲存根目錄已一致";
    driveStorageStatus.textContent = `目前 ${driveStorage.current_root || "-"}，下次啟動 ${driveStorage.effective_next_root || "-"}。${restartText}`;
    driveStorageStatus.style.color = driveStorage.restart_required ? "#ffb74d" : "var(--muted)";
  }
  if ($("s-module-chat-min-role")) $("s-module-chat-min-role").value = s.module_chat_min_role || "user";
  if ($("s-module-community-min-role")) $("s-module-community-min-role").value = s.module_community_min_role || "user";
  if ($("s-module-appeals-min-role")) $("s-module-appeals-min-role").value = s.module_appeals_min_role || "user";
  if ($("s-module-accounts-min-role")) $("s-module-accounts-min-role").value = s.module_accounts_min_role || "manager";
  if ($("s-module-comfyui-min-role")) $("s-module-comfyui-min-role").value = s.module_comfyui_min_role || "user";
  if ($("s-module-games-min-role")) $("s-module-games-min-role").value = s.module_games_min_role || "user";
  if ($("s-module-videos-min-role")) $("s-module-videos-min-role").value = s.module_videos_min_role || "user";
  if ($("s-video-tip-fee-percent")) $("s-video-tip-fee-percent").value = s.video_tip_fee_percent ?? 5;
  if ($("s-video-tip-min-points")) $("s-video-tip-min-points").value = s.video_tip_min_points ?? 1;
  if ($("s-site-bg")) $("s-site-bg").value = s.site_bg || "#0f0f1a";
  if ($("s-site-surface")) $("s-site-surface").value = s.site_surface || "#1a1a2e";
  if ($("s-site-accent")) $("s-site-accent").value = s.site_accent || "#6c63ff";
  if ($("s-site-accent2")) $("s-site-accent2").value = s.site_accent2 || "#00d4aa";
  if ($("s-site-text")) $("s-site-text").value = s.site_text || "#e0e0f0";
  if ($("s-site-muted")) $("s-site-muted").value = s.site_muted || "#8888aa";
  if ($("s-site-layout-mode")) $("s-site-layout-mode").value = s.site_layout_mode || "centered";
  if ($("s-site-density")) $("s-site-density").value = s.site_density || "comfortable";
  if ($("s-site-radius-px")) $("s-site-radius-px").value = String(s.site_radius_px || 12);
  if ($("s-site-font-scale")) $("s-site-font-scale").value = String(s.site_font_scale || 1);
  if ($("s-site-content-width")) $("s-site-content-width").value = String(s.site_content_width || 1380);
  if ($("s-site-font-family")) $("s-site-font-family").value = s.site_font_family || "system";
  if ($("s-site-background-style")) $("s-site-background-style").value = s.site_background_style || "flat";
  if ($("s-site-panel-style")) $("s-site-panel-style").value = s.site_panel_style || "glass";
  if ($("s-site-sidebar-width")) $("s-site-sidebar-width").value = s.site_sidebar_width || "standard";
  FEATURE_SETTING_KEYS.forEach((key) => {
    const el = $(featureSettingInputId(key));
    if (el) el.checked = !!s[key];
  });
  applySiteConfig(s);
  renderFeatureBundleToolbar();
  renderFeatureAdvisories();
  switchSettingsSection(currentSettingsSection || "security");
}

const FEATURE_SETTING_KEYS = [
  "feature_chat_enabled",
  "feature_community_enabled",
  "feature_accounts_enabled",
  "feature_appeals_enabled",
  "feature_audit_log_enabled",
  "feature_violation_center_enabled",
  "feature_reports_enabled",
  "feature_system_health_enabled",
  "feature_identity_governance_enabled",
  "feature_account_security_enabled",
  "feature_member_governance_enabled",
  "feature_server_modes_enabled",
  "feature_snapshot_restore_enabled",
  "feature_health_center_enabled",
  "feature_forum_core_enabled",
  "feature_ui_rebuild_enabled",
  "feature_reports_notifications_enabled",
  "feature_attachments_enabled",
  "feature_storage_albums_enabled",
  "feature_personalization_enabled",
  "feature_social_search_enabled",
  "feature_advanced_security_enabled",
  "feature_privacy_uploads_enabled",
  "feature_comfyui_enabled",
  "feature_economy_enabled",
  "feature_trading_enabled",
  "feature_games_enabled",
  "feature_videos_enabled"
];

const FEATURE_SETTING_LABELS = {
  feature_chat_enabled: "聊天室",
  feature_community_enabled: "討論區 / 公告 / 留言",
  feature_accounts_enabled: "帳號管理",
  feature_appeals_enabled: "用戶申覆",
  feature_audit_log_enabled: "Audit log 查詢",
  feature_violation_center_enabled: "違規中心",
  feature_reports_enabled: "檢舉審核",
  feature_system_health_enabled: "系統健康燈",
  feature_identity_governance_enabled: "身份治理欄位 / 會員等級",
  feature_account_security_enabled: "帳號安全強化",
  feature_member_governance_enabled: "會員治理與投票",
  feature_server_modes_enabled: "伺服器模式",
  feature_snapshot_restore_enabled: "Snapshot / Restore / Reset",
  feature_health_center_enabled: "健康監控中心新版",
  feature_forum_core_enabled: "論壇核心新版",
  feature_ui_rebuild_enabled: "UI 架構重構",
  feature_reports_notifications_enabled: "檢舉 / 申訴 / 通知新版",
  feature_attachments_enabled: "附件 / 頭像 / CAPTCHA",
  feature_storage_albums_enabled: "Storage / 相簿",
  feature_videos_enabled: "影音分享",
  feature_games_enabled: "遊戲區 / 西洋棋",
  feature_comfyui_enabled: "ComfyUI AI 產圖",
  feature_economy_enabled: "PointsChain 積分系統",
  feature_trading_enabled: "積分交易所",
  feature_personalization_enabled: "個人外觀覆寫",
  feature_social_search_enabled: "社交 / 搜尋",
  feature_advanced_security_enabled: "進階安全",
  feature_privacy_uploads_enabled: "隱私分級上傳 / E2EE",
};

const FEATURE_DEPENDENCY_RULES = {
  feature_storage_albums_enabled: {
    required: ["feature_privacy_uploads_enabled"],
    description: "Storage / 相簿需要先有雲端硬碟父功能。",
  },
  feature_trading_enabled: {
    required: ["feature_economy_enabled"],
    description: "積分交易所必須依附在 PointsChain 上。",
  },
  feature_videos_enabled: {
    recommended: ["feature_privacy_uploads_enabled", "feature_economy_enabled"],
    description: "影音若搭配雲端硬碟與 PointsChain，才有上傳、保存與打賞等完整服務。",
  },
  feature_comfyui_enabled: {
    recommended: ["feature_privacy_uploads_enabled"],
    description: "ComfyUI 若搭配雲端硬碟，可直接保存與分享產圖結果。",
  },
  feature_chat_enabled: {
    recommended: ["feature_attachments_enabled", "feature_reports_enabled", "feature_reports_notifications_enabled"],
    description: "聊天室完整體驗通常會搭配附件、檢舉與通知。",
  },
  feature_community_enabled: {
    recommended: ["feature_attachments_enabled", "feature_reports_enabled", "feature_reports_notifications_enabled"],
    description: "討論區完整體驗通常會搭配附件、檢舉與通知。",
  },
  feature_appeals_enabled: {
    recommended: ["feature_accounts_enabled", "feature_reports_notifications_enabled"],
    description: "申覆流程通常會搭配帳號管理與通知。",
  },
  feature_violation_center_enabled: {
    recommended: ["feature_accounts_enabled"],
    description: "違規中心通常和帳號管理一起使用。",
  },
  feature_reports_enabled: {
    recommended: ["feature_accounts_enabled", "feature_reports_notifications_enabled"],
    description: "檢舉審核通常會搭配帳號管理與通知。",
  },
  feature_reports_notifications_enabled: {
    recommended: ["feature_accounts_enabled"],
    description: "通知中心通常由帳號管理模組承載。",
  },
  feature_identity_governance_enabled: {
    recommended: ["feature_accounts_enabled"],
    description: "身份治理欄位通常和帳號管理一起開。",
  },
  feature_account_security_enabled: {
    recommended: ["feature_accounts_enabled"],
    description: "帳號安全強化通常和帳號管理一起開。",
  },
  feature_member_governance_enabled: {
    recommended: ["feature_accounts_enabled"],
    description: "會員治理頁面通常掛在帳號管理底下。",
  },
};

const FEATURE_SERVICE_BUNDLES = [
  {
    key: "accounts-suite",
    label: "帳號治理整套",
    description: "帳號、違規、治理、通知、申覆一起開。",
    features: [
      "feature_accounts_enabled",
      "feature_identity_governance_enabled",
      "feature_account_security_enabled",
      "feature_member_governance_enabled",
      "feature_violation_center_enabled",
      "feature_reports_notifications_enabled",
      "feature_appeals_enabled",
      "feature_reports_enabled",
    ],
  },
  {
    key: "community-suite",
    label: "社群互動整套",
    description: "聊天、討論區、附件、檢舉與通知一起開。",
    features: [
      "feature_chat_enabled",
      "feature_community_enabled",
      "feature_attachments_enabled",
      "feature_reports_enabled",
      "feature_reports_notifications_enabled",
    ],
  },
  {
    key: "drive-suite",
    label: "雲端硬碟整套",
    description: "隱私分級上傳加 Storage / 相簿一起開。",
    features: [
      "feature_privacy_uploads_enabled",
      "feature_storage_albums_enabled",
    ],
  },
  {
    key: "video-suite",
    label: "影音分享整套",
    description: "影音、雲端硬碟與 PointsChain 一起開。",
    features: [
      "feature_videos_enabled",
      "feature_privacy_uploads_enabled",
      "feature_economy_enabled",
    ],
  },
  {
    key: "ai-suite",
    label: "AI 產圖整套",
    description: "ComfyUI 加雲端硬碟保存流程一起開。",
    features: [
      "feature_comfyui_enabled",
      "feature_privacy_uploads_enabled",
    ],
  },
  {
    key: "economy-suite",
    label: "積分交易整套",
    description: "PointsChain 與積分交易所一起開。",
    features: [
      "feature_economy_enabled",
      "feature_trading_enabled",
    ],
  },
];

function featureSettingInputId(key) {
  return "s-" + key.replaceAll("_", "-");
}

function featureSettingLabel(key) {
  return FEATURE_SETTING_LABELS[key] || key;
}

function setSettingsStatus(text = "", ok = null, options = {}) {
  const el = $("settings-msg");
  if (!el) return;
  if (settingsStatusAutoClearTimer) {
    clearTimeout(settingsStatusAutoClearTimer);
    settingsStatusAutoClearTimer = null;
  }
  if (!text) {
    el.textContent = "";
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  el.textContent = text;
  el.style.color = ok === true ? "#4caf50" : ok === false ? "#ff4f6d" : "#ffb74d";
  const autoClearMs = Number(options.autoClearMs || 0);
  if (autoClearMs > 0) {
    const expectedText = text;
    settingsStatusAutoClearTimer = setTimeout(() => {
      if ($("settings-msg")?.textContent === expectedText) clearSettingsStatus();
    }, autoClearMs);
  }
}

function clearSettingsStatus() {
  if (settingsStatusAutoClearTimer) {
    clearTimeout(settingsStatusAutoClearTimer);
    settingsStatusAutoClearTimer = null;
  }
  setSettingsStatus("");
}

function formatFeatureAdvisoryLine(item) {
  if (!item) return "";
  const parts = [];
  if (Array.isArray(item.missingRequired) && item.missingRequired.length) {
    parts.push(`缺少父功能：${item.missingRequired.map(featureSettingLabel).join("、")}`);
  }
  if (Array.isArray(item.missingRecommended) && item.missingRecommended.length) {
    parts.push(`建議一起開：${item.missingRecommended.map(featureSettingLabel).join("、")}`);
  }
  return parts.length ? `${item.feature}（${parts.join("；")}）` : item.feature;
}

function featureToggleValue(key) {
  return !!$(featureSettingInputId(key))?.checked;
}

function buildFeatureAdvisories() {
  return FEATURE_SETTING_KEYS.flatMap((key) => {
    if (!featureToggleValue(key)) return [];
    const rule = FEATURE_DEPENDENCY_RULES[key];
    if (!rule) return [];
    const missingRequired = (rule.required || []).filter((dep) => !featureToggleValue(dep));
    const missingRecommended = (rule.recommended || []).filter((dep) => !featureToggleValue(dep));
    if (!missingRequired.length && !missingRecommended.length) return [];
    return [{
      feature: featureSettingLabel(key),
      description: rule.description || "",
      missingRequired,
      missingRecommended,
    }];
  });
}

function renderFeatureAdvisories() {
  const wrap = $("feature-advisory-list");
  if (!wrap) return;
  const advisories = buildFeatureAdvisories();
  if (!advisories.length) {
    wrap.innerHTML = `<div class="settings-feature-advisory ok">目前已勾選的功能沒有缺少父功能；若要一次打開整套服務，可用上方快捷開關。</div>`;
    return;
  }
  wrap.innerHTML = advisories.map((item) => {
    const required = item.missingRequired.length
      ? `<div><strong>還缺父功能：</strong>${item.missingRequired.map(featureSettingLabel).join("、")}</div>`
      : "";
    const recommended = item.missingRecommended.length
      ? `<div><strong>完整服務建議一併開啟：</strong>${item.missingRecommended.map(featureSettingLabel).join("、")}</div>`
      : "";
    const tone = item.missingRequired.length ? "warn" : "info";
    return `
      <div class="settings-feature-advisory ${tone}">
        <div><strong>${sanitize(item.feature)}</strong></div>
        ${item.description ? `<div>${sanitize(item.description)}</div>` : ""}
        ${required}
        ${recommended}
      </div>
    `;
  }).join("");
}

function renderFeatureBundleToolbar() {
  const toolbar = $("feature-bundle-toolbar");
  if (!toolbar) return;
  toolbar.innerHTML = FEATURE_SERVICE_BUNDLES.map((bundle) => `
    <button class="btn btn-sm" type="button" data-feature-bundle="${sanitize(bundle.key)}" title="${sanitize(bundle.description)}">
      ${sanitize(bundle.label)}
    </button>
  `).join("");
  toolbar.querySelectorAll("[data-feature-bundle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const bundle = FEATURE_SERVICE_BUNDLES.find((item) => item.key === btn.dataset.featureBundle);
      if (!bundle) return;
      bundle.features.forEach((key) => {
        const el = $(featureSettingInputId(key));
        if (el) el.checked = true;
      });
      renderFeatureAdvisories();
      setSettingsStatus(`已套用「${bundle.label}」組合，記得再按「儲存設定」才會真正寫入。`, null);
    });
  });
}

function bindSettingsAssistants() {
  const serverModule = $("module-server");
  if (!serverModule || serverModule.dataset.settingsAssistantsBound === "1") return;
  serverModule.dataset.settingsAssistantsBound = "1";
  renderFeatureBundleToolbar();
  renderFeatureAdvisories();
  document.querySelectorAll("[id^='s-']").forEach((el) => {
    el.addEventListener("change", () => {
      clearSettingsStatus();
      if (FEATURE_SETTING_KEYS.includes(el.id.replace(/^s-/, "").replaceAll("-", "_"))) renderFeatureAdvisories();
    });
    if (el.matches("input[type='text'], input[type='number'], input[type='password'], input[type='url'], textarea")) {
      el.addEventListener("input", clearSettingsStatus);
    }
  });
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

const SECURITY_CONTROL_KEYS = [
  "maintenance_mode",
  "server_ssl_enabled",
  "audit_chain_enabled",
  "feature_audit_log_enabled",
  "ip_blocking_enabled",
  "login_violation_enabled",
  "rate_limit_violation_enabled",
  "root_ip_whitelist_enabled",
  "root_ip_whitelist",
  "browser_only_mode_enabled",
  "integrity_guard_enabled",
  "integrity_guard_strict_mode",
  "feature_economy_enabled"
];
const SECURITY_THRESHOLD_KEYS = [
  "max_login_failures",
  "block_duration_minutes",
  "security_pending_chat_reports_threshold",
  "security_pending_appeals_threshold",
  "security_pending_moderation_proposals_threshold",
  "security_quarantined_files_threshold",
  "security_unknown_encrypted_files_threshold",
  "security_log_tail_lines"
];
const SECURITY_FIELD_LABELS = {
  maintenance_mode: "維護模式",
  server_ssl_enabled: "HTTPS / SSL",
  audit_chain_enabled: "審計 hash chain",
  feature_audit_log_enabled: "Audit log 查詢頁",
  ip_blocking_enabled: "錯誤登入鎖 IP",
  login_violation_enabled: "登入失敗寫入違規",
  rate_limit_violation_enabled: "速率限制寫入違規",
  root_ip_whitelist_enabled: "root IP 白名單",
  root_ip_whitelist: "root IP 白名單內容",
  browser_only_mode_enabled: "Browser-only 模式",
  integrity_guard_enabled: "Integrity Guard",
  integrity_guard_strict_mode: "Integrity strict mode",
  feature_economy_enabled: "PointsChain / 積分私有鏈",
  feature_videos_enabled: "影音分享模組",
  max_login_failures: "登入失敗鎖定次數",
  block_duration_minutes: "封鎖時長（分鐘）",
  security_pending_chat_reports_threshold: "待審聊天室檢舉警戒",
  security_pending_appeals_threshold: "待審申覆警戒",
  security_pending_moderation_proposals_threshold: "待審治理提案警戒",
  security_quarantined_files_threshold: "隔離檔案警戒",
  security_unknown_encrypted_files_threshold: "未知加密檔案警戒",
  security_log_tail_lines: "log 顯示行數"
};
let securityProfiles = [];

function securityInputId(prefix, key) {
  return prefix + "-" + key.replaceAll("_", "-");
}

function findSecurityProfile(name) {
  const profileName = String(name || "");
  return securityProfiles.find((profile) => profile && profile.name === profileName) || null;
}

function profileKeysSummary(profile, key) {
  const data = profile && profile[key] && typeof profile[key] === "object" ? profile[key] : {};
  const keys = Object.keys(data);
  return keys.length
    ? keys.map((item) => `${SECURITY_FIELD_LABELS[item] || item}=${data[item] === true ? "開" : data[item] === false ? "關" : JSON.stringify(data[item])}`).join("，")
    : "未設定";
}

function collectSecurityProfileDraft(prefix = "security-profile") {
  const settings = {};
  SECURITY_CONTROL_KEYS.forEach((key) => {
    const el = $(securityInputId(prefix, key));
    if (!el) return;
    settings[key] = el.type === "checkbox" ? !!el.checked : el.value || "";
  });
  const thresholds = {};
  SECURITY_THRESHOLD_KEYS.forEach((key) => {
    const el = $(securityInputId(prefix, key));
    if (!el) return;
    const number = parseInt(el.value || "0", 10);
    thresholds[key] = Number.isFinite(number) ? number : 0;
  });
  return { settings, thresholds };
}

function fillSecurityProfileDraft(settings = {}, thresholds = {}, prefix = "security-profile") {
  SECURITY_CONTROL_KEYS.forEach((key) => {
    const el = $(securityInputId(prefix, key));
    if (!el) return;
    const value = Object.prototype.hasOwnProperty.call(settings, key) ? settings[key] : "";
    if (el.type === "checkbox") el.checked = !!value;
    else el.value = value ?? "";
  });
  SECURITY_THRESHOLD_KEYS.forEach((key) => {
    const el = $(securityInputId(prefix, key));
    if (!el) return;
    el.value = Object.prototype.hasOwnProperty.call(thresholds, key) ? thresholds[key] : 0;
  });
}

function renderSecurityProfilePreview(selectId, previewId) {
  const preview = $(previewId);
  const select = $(selectId);
  if (!preview || !select) return;
  const profile = findSecurityProfile(select.value);
  if (!profile) {
    preview.classList.remove("show");
    preview.innerHTML = "";
    return;
  }
  preview.classList.add("show");
  preview.innerHTML = `
    <div><strong>${sanitize(profile.label || profile.name || "")}</strong> ${profile.is_builtin ? "內建" : "自定義"}</div>
    <div>${sanitize(profile.description || "無描述")}</div>
    <div>安全開關：${sanitize(profileKeysSummary(profile, "settings"))}</div>
    <div>閾值：${sanitize(profileKeysSummary(profile, "thresholds"))}</div>
  `;
}

function applySecurityProfileDataToInputs(profile, prefix = "sc") {
  if (!profile) return;
  const settings = profile.settings && typeof profile.settings === "object" ? profile.settings : {};
  SECURITY_CONTROL_KEYS.forEach((key) => {
    if (!Object.prototype.hasOwnProperty.call(settings, key)) return;
    const el = $(securityInputId(prefix, key));
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!settings[key];
    else el.value = settings[key] ?? "";
  });
  SECURITY_THRESHOLD_KEYS.forEach((key) => {
    const source = Object.prototype.hasOwnProperty.call(settings, key)
      ? settings
      : (profile.thresholds && typeof profile.thresholds === "object" ? profile.thresholds : {});
    if (!Object.prototype.hasOwnProperty.call(source, key)) return;
    const el = $(securityInputId(prefix, key));
    if (el) el.value = source[key] ?? 0;
  });
}

function applySecurityProfileToInputs(profileName, prefix = "sc") {
  const profile = findSecurityProfile(profileName);
  applySecurityProfileDataToInputs(profile, prefix);
}

function previewSecurityProfileSelection(selectId, previewId, inputPrefix = "") {
  renderSecurityProfilePreview(selectId, previewId);
  if (inputPrefix) applySecurityProfileToInputs($(selectId)?.value, inputPrefix);
  const profile = findSecurityProfile($(selectId)?.value);
  const msg = selectId === "security-mode-select" ? $("security-controls-msg") : $("server-mode-status");
  if (msg && profile) {
    msg.textContent = `已預覽「${profile.label || profile.name}」的安全開關；按套用才會寫入伺服器。`;
    msg.style.color = "var(--muted)";
  }
}

function bindSecurityProfileSelect(selectId, previewId, inputPrefix = "") {
  const select = $(selectId);
  if (!select) return;
  select.onchange = () => previewSecurityProfileSelection(selectId, previewId, inputPrefix);
}

function populateProfileSelect(selectId, profiles, selectedMode) {
  const select = $(selectId);
  if (!select) return;
  const rows = Array.isArray(profiles) ? profiles : [];
  select.innerHTML = rows.map((profile) => `
    <option value="${sanitize(profile.name || "")}" ${profile.name === selectedMode ? "selected" : ""}>
      ${sanitize(profile.label || profile.name || "")}${profile.is_builtin ? " · builtin" : " · custom"}
    </option>
  `).join("");
  if (selectedMode && rows.some((profile) => profile.name === selectedMode)) {
    select.value = selectedMode;
  }
}

function renderSecuritySummary(sc) {
  const summary = $("security-center-summary");
  if (!summary) return;
  const anomaly = sc.anomaly || {};
  const readiness = sc.readiness || {};
  const audit = sc.audit_integrity || {};
  const mode = sc.mode || {};
  const settings = sc.settings || {};
  const signalCount = Array.isArray(anomaly.signals) ? anomaly.signals.length : 0;
  const cards = [
    ["Readiness", readiness.status || "-", readiness.status === "ok" ? "#4caf50" : "#ff4f6d"],
    ["Anomaly", anomaly.status || "ok", anomaly.status === "ok" ? "#4caf50" : anomaly.status === "critical" ? "#ff4f6d" : "#ffb74d"],
    ["Signals", String(signalCount), signalCount ? "#ffb74d" : "#4caf50"],
    ["Audit Chain", audit.enabled === false ? "停用" : audit.ok ? "完整" : "異常", audit.enabled === false ? "#9e9e9e" : audit.ok ? "#4caf50" : "#ff4f6d"],
    ["Server Mode", mode.current_mode || "dev_ready", mode.current_mode === "superweak" ? "#ff4f6d" : "#82b1ff"],
    ["Maintenance", settings.maintenance_mode ? "啟用" : "關閉", settings.maintenance_mode ? "#ff4f6d" : "#4caf50"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${sanitize(label)}</div>
      <div style="font-size:1rem;color:${color};font-weight:700;margin-top:.2rem;word-break:break-word;">${sanitize(value)}</div>
    </div>
  `).join("");
}

function renderServerOutput(output) {
  const box = $("security-server-output");
  if (!box) return;
  const rows = Array.isArray(output?.lines) ? output.lines : [];
  if (!rows.length) {
    box.textContent = "尚無伺服器輸出";
    return;
  }
  box.textContent = rows.map((row) => {
    const stream = row.stream || "stdout";
    const ts = row.timestamp || "";
    const line = row.line || "";
    return `[${ts}] ${stream}> ${line}`;
  }).join("\n");
  box.scrollTop = box.scrollHeight;
}

function securityTestMsg(text, ok = true) {
  const msg = $("security-test-msg");
  if (!msg) return;
  msg.textContent = text || "";
  msg.className = text ? `msg show ${ok ? "ok" : "err"}` : "msg";
}

function renderSecurityTestJobs(jobs) {
  const list = $("security-test-jobs");
  if (!list) return;
  const rows = Array.isArray(jobs) ? jobs : [];
  if (!rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無 root 啟動的測試任務</div>`;
    return;
  }
  const colorFor = (status) => status === "passed" ? "#4caf50" : status === "failed" ? "#ff4f6d" : "#ffb74d";
  const labelFor = (kind) => kind === "pentest" ? "滲透測試" : kind === "functional" ? "全功能測試" : kind === "stress" ? "壓力測試" : (kind || "-");
  list.innerHTML = rows.map((job) => `
    <div class="drive-file-row">
      <div style="min-width:0;flex:1;">
        <strong>${sanitize(labelFor(job.kind))} · <span style="color:${colorFor(job.status)};">${sanitize(job.status || "-")}</span></strong>
        <div class="drive-card-sub">${sanitize(job.started_at || "")}${job.finished_at ? " -> " + sanitize(job.finished_at) : ""}</div>
        <div class="economy-ledger-hash">${sanitize(job.job_id || "")}</div>
        <div class="drive-progress" aria-label="${sanitize(labelFor(job.kind))} progress">
          <div class="drive-progress-fill ${job.status === "running" ? "indeterminate" : ""}" style="width:${Math.max(0, Math.min(100, Number(job.progress_percent ?? 0)))}%;"></div>
        </div>
        <div class="drive-progress-label">${job.status === "running" ? "執行中" : "完成"} · ${Math.round(Number(job.progress_percent ?? 0))}%</div>
        <div class="drive-card-sub">report: ${sanitize(job.report_dir || (Array.isArray(job.report_artifacts) ? job.report_artifacts.join(", ") : "") || job.report_root || "-")}</div>
        <div class="drive-card-sub">log: ${sanitize(job.log_path || "-")}</div>
        <pre class="security-log-box security-log-pre" style="max-height:180px;margin-top:.45rem;">${sanitize((job.log_tail || []).join("\n") || "等待測試輸出...")}</pre>
      </div>
      <button class="btn" type="button" data-security-test-job="${sanitize(job.job_id || "")}">查詢</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-security-test-job]").forEach((btn) => {
    btn.addEventListener("click", () => loadSecurityTestJob(btn.dataset.securityTestJob || ""));
  });
}

async function loadSecurityTestJobs() {
  if (currentUser !== "root") return;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const target = $("security-pentest-target");
    if (target && !target.value) target.value = window.location.origin;
    const stressTarget = $("security-stress-target");
    if (stressTarget && !stressTarget.value) stressTarget.value = window.location.origin;
    const res = await apiFetch(API + "/root/security-tests", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) {
      securityTestMsg(json.msg || `測試任務讀取失敗（HTTP ${res.status}）`, false);
      return;
    }
    renderSecurityTestJobs(json.jobs || []);
    if ((json.jobs || []).some((job) => job.status === "running")) {
      clearTimeout(window.securityTestPollTimer);
      window.securityTestPollTimer = setTimeout(loadSecurityTestJobs, 2500);
    }
  } catch (err) {
    securityTestMsg(`測試任務讀取失敗：${err.message || "請檢查伺服器連線"}`, false);
  }
}

async function loadSecurityTestJob(jobId) {
  if (!jobId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/root/security-tests/${encodeURIComponent(jobId)}`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    securityTestMsg(json.msg || "任務查詢失敗", false);
    return;
  }
  renderSecurityTestJobs([json.job]);
}

async function startSecurityPentest() {
  if (currentUser !== "root") return;
  const target = $("security-pentest-target")?.value || window.location.origin;
  const payload = {
    target,
    only: $("security-pentest-only")?.value || "",
    skip: $("security-pentest-skip")?.value || "",
    tool_timeout_seconds: Number($("security-pentest-timeout")?.value || 180),
    i_own_this_target: !!$("security-pentest-own-target")?.checked,
  };
  securityTestMsg("滲透測試啟動中...", true);
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/root/security-tests/pentest", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload)
    });
    const json = await res.json().catch(() => ({}));
    const ok = res.ok && !!json.ok;
    securityTestMsg(ok ? `滲透測試已啟動：${json.job?.job_id || ""}` : (json.msg || `滲透測試啟動失敗（HTTP ${res.status}）`), ok);
    if (ok) await loadSecurityTestJobs();
  } catch (err) {
    securityTestMsg(`滲透測試啟動失敗：${err.message || "請檢查伺服器連線"}`, false);
  }
}

async function startSecurityFunctionalSmoke() {
  if (currentUser !== "root") return;
  const payload = {
    port: Number($("security-functional-port")?.value || 50741),
    keep_runtime: !!$("security-functional-keep-runtime")?.checked,
  };
  securityTestMsg("全功能測試啟動中...", true);
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/root/security-tests/functional", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload)
    });
    const json = await res.json().catch(() => ({}));
    const ok = res.ok && !!json.ok;
    securityTestMsg(ok ? `全功能測試已啟動：${json.job?.job_id || ""}` : (json.msg || `全功能測試啟動失敗（HTTP ${res.status}）`), ok);
    if (ok) await loadSecurityTestJobs();
  } catch (err) {
    securityTestMsg(`全功能測試啟動失敗：${err.message || "請檢查伺服器連線"}`, false);
  }
}

async function startSecurityStressTest() {
  if (currentUser !== "root") return;
  const payload = {
    target: $("security-stress-target")?.value || window.location.origin,
    requests: Number($("security-stress-requests")?.value || 200),
    concurrency: Number($("security-stress-concurrency")?.value || 20),
    paths: $("security-stress-paths")?.value || "",
  };
  securityTestMsg("壓力測試啟動中...", true);
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/root/security-tests/stress", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload)
    });
    const json = await res.json().catch(() => ({}));
    const ok = res.ok && !!json.ok;
    securityTestMsg(ok ? `壓力測試已啟動：${json.job?.job_id || ""}` : (json.msg || `壓力測試啟動失敗（HTTP ${res.status}）`), ok);
    if (ok) await loadSecurityTestJobs();
  } catch (err) {
    securityTestMsg(`壓力測試啟動失敗：${err.message || "請檢查伺服器連線"}`, false);
  }
}

async function loadServerOutput() {
  if (currentUser !== "root") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/server-output?limit=300", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  renderServerOutput(json.server_output || {});
}

function startServerOutputPoll() {
  if (currentUser !== "root" || currentModuleTab !== "server" || currentServerTab !== "security") return;
  if (serverOutputPollTimer) return;
  serverOutputPollTimer = setInterval(loadServerOutput, 2500);
}

function stopServerOutputPoll() {
  if (!serverOutputPollTimer) return;
  clearInterval(serverOutputPollTimer);
  serverOutputPollTimer = null;
}

function populateSecurityProfiles(profiles, selectedMode) {
  securityProfiles = Array.isArray(profiles) ? profiles : [];
  populateProfileSelect("security-mode-select", securityProfiles, selectedMode);
  populateProfileSelect("server-mode-select", securityProfiles, selectedMode);
  bindSecurityProfileSelect("security-mode-select", "security-mode-profile-preview", "sc");
  bindSecurityProfileSelect("server-mode-select", "server-mode-profile-preview", "s");
  renderSecurityProfilePreview("security-mode-select", "security-mode-profile-preview");
  renderSecurityProfilePreview("server-mode-select", "server-mode-profile-preview");
}

async function loadSecurityCenter() {
  if (currentUser !== "root") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/security-center", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const sc = json.security_center || {};
  if (!json.ok) {
    const summary = $("security-center-summary");
    if (summary) summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "安全中心讀取失敗")}</div>`;
    return;
  }
  renderSecuritySummary(sc);
  const settings = sc.settings || {};
  SECURITY_CONTROL_KEYS.forEach((key) => {
    const el = $(securityInputId("sc", key));
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!settings[key];
    else el.value = settings[key] || "";
  });
  const thresholds = sc.thresholds || {};
  SECURITY_THRESHOLD_KEYS.forEach((key) => {
    const el = $(securityInputId("sc", key));
    if (el) el.value = thresholds[key] ?? 0;
  });
  const mode = sc.mode || {};
  populateSecurityProfiles(sc.profiles || [], mode.current_mode || "dev_ready");
  const modeStatus = $("security-mode-status");
  if (modeStatus) {
    const previous = mode.previous_mode ? `，上一個模式：${mode.previous_mode}` : "";
    const snapshot = mode.active_snapshot_id ? `，active snapshot：${mode.active_snapshot_id}` : "";
    modeStatus.textContent = `目前模式：${mode.current_mode || "dev_ready"}${previous}${snapshot}`;
    modeStatus.style.color = mode.current_mode === "superweak" ? "#ff4f6d" : "var(--muted)";
  }
  const auditBox = $("security-audit-entries");
  if (auditBox) {
    const rows = sc.audit_entries || [];
    auditBox.innerHTML = rows.length ? rows.map((e) => `
      <div class="security-log-row">
        <span style="color:#888;">${sanitize(e.timestamp || "")}</span>
        <span style="color:${e.success ? "#4caf50" : "#ff4f6d"};">${e.success ? "OK" : "FAIL"}</span>
        <span style="color:#e0e0e0;">${sanitize(e.action || "")}</span>
        <span style="color:#82b1ff;">${sanitize(e.actor || "")}</span>
        <span style="color:#888;">${sanitize(e.details || "")}</span>
      </div>
    `).join("") : "<p style='color:var(--muted);'>暫無審計資料</p>";
  }
  const logBox = $("security-server-log");
  if (logBox) {
    const log = sc.server_log || {};
    logBox.textContent = log.exists ? (log.lines || []).join("\n") : `server log 不存在：${log.path || "-"}`;
  }
  renderServerOutput(sc.server_output || {});
  await loadSecurityTestJobs();
  startServerOutputPoll();
}

function setSecuritySaveStatus(message, ok = true, targetId = "") {
  const color = ok ? "#4caf50" : "#ff4f6d";
  ["security-save-status", targetId].filter(Boolean).forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.textContent = message || "";
    el.style.color = color;
  });
}

async function saveSecurityCenterControls() {
  const btn = $("security-controls-save-btn");
  if (btn) btn.disabled = true;
  setSecuritySaveStatus("正在儲存安全開關...", true, "security-controls-msg");
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const payload = {};
    SECURITY_CONTROL_KEYS.forEach((key) => {
      const el = $(securityInputId("sc", key));
      if (!el) return;
      payload[key] = el.type === "checkbox" ? !!el.checked : el.value || "";
    });
    const res = await apiFetch(API + "/admin/security-center/controls", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload)
    });
    const json = await res.json().catch(() => ({}));
    const message = json.ok ? (json.msg || "安全機制開關已儲存") : (json.msg || `安全開關儲存失敗（HTTP ${res.status}）`);
    setSecuritySaveStatus(message, !!json.ok, "security-controls-msg");
    if (json.ok) await loadSecurityCenter();
  } catch (err) {
    setSecuritySaveStatus(`安全開關儲存失敗：${err.message || "請求失敗"}`, false, "security-controls-msg");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveSecurityThresholds() {
  const btn = $("security-thresholds-save-btn");
  if (btn) btn.disabled = true;
  setSecuritySaveStatus("正在儲存安全閾值...", true, "security-thresholds-msg");
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const payload = {};
    SECURITY_THRESHOLD_KEYS.forEach((key) => {
      const el = $(securityInputId("sc", key));
      if (el) payload[key] = parseInt(el.value || "0", 10);
    });
    const res = await apiFetch(API + "/admin/security-center/thresholds", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify(payload)
    });
    const json = await res.json().catch(() => ({}));
    const message = json.ok ? (json.msg || "安全閾值已儲存") : (json.msg || `安全閾值儲存失敗（HTTP ${res.status}）`);
    setSecuritySaveStatus(message, !!json.ok, "security-thresholds-msg");
    if (json.ok) await loadSecurityCenter();
  } catch (err) {
    setSecuritySaveStatus(`安全閾值儲存失敗：${err.message || "請求失敗"}`, false, "security-thresholds-msg");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function applySecurityMode() {
  const target = $("security-mode-select")?.value || "dev_ready";
  const confirmText = $("security-mode-confirm")?.value || "";
  const notes = $("security-mode-notes")?.value || "";
  if (target === "production" && confirmText !== "GO_LIVE") {
    alert("進入 production 上線模式必須輸入 GO_LIVE");
    return;
  }
  if (target === "superweak" && confirmText !== "ENABLE_SUPERWEAK") {
    alert("進入 superweak 必須輸入 ENABLE_SUPERWEAK");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/server-mode", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ mode: target, confirm: confirmText, notes })
  });
  const json = await res.json().catch(() => ({}));
  const status = $("security-mode-status");
  if (status) {
    status.textContent = json.ok ? "伺服器模式 / 安全設定檔已套用" : (json.msg || "套用失敗");
    status.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) {
    if (json.profile) {
      applySecurityProfileDataToInputs(json.profile, "sc");
      applySecurityProfileDataToInputs(json.profile, "s");
    }
    if ($("security-mode-confirm")) $("security-mode-confirm").value = "";
    await loadSecurityCenter();
    await loadServerMode();
    await loadSettings();
  }
}

function loadCurrentSecurityProfileDraft() {
  const current = collectSecurityProfileDraft("sc");
  fillSecurityProfileDraft(current.settings, current.thresholds, "security-profile");
  const msg = $("security-profile-msg");
  if (msg) {
    msg.textContent = "已帶入目前安全開關與閾值；請填名稱後用表單調整並儲存。";
    msg.style.color = "var(--muted)";
  }
}

async function saveSecurityProfile() {
  const { settings, thresholds } = collectSecurityProfileDraft("security-profile");
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    name: $("security-profile-name")?.value || "",
    label: $("security-profile-label")?.value || "",
    description: $("security-profile-description")?.value || "",
    settings,
    thresholds
  };
  const res = await apiFetch(API + "/admin/security-center/profiles", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("security-profile-msg");
  if (msg) {
    msg.textContent = json.ok ? "自定義安全設定檔已儲存" : (json.msg || "儲存失敗");
    msg.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) {
    const savedName = json.profile?.name || payload.name;
    await loadSecurityCenter();
    await loadServerMode();
    ["security-mode-select", "server-mode-select"].forEach((id) => {
      const select = $(id);
      if (select && savedName) select.value = savedName;
    });
    renderSecurityProfilePreview("security-mode-select", "security-mode-profile-preview");
    renderSecurityProfilePreview("server-mode-select", "server-mode-profile-preview");
  }
}

function healthStatusColor(status) {
  if (status === "critical") return "#ff4f6d";
  if (status === "degraded" || status === "warning") return "#ffb74d";
  return "#4caf50";
}

function renderHealthMetric(label, value, color = "#82b1ff") {
  return `
    <div class="health-metric-card">
      <div class="health-metric-label">${sanitize(label)}</div>
      <div class="health-metric-value" style="color:${color};">${sanitize(value)}</div>
    </div>
  `;
}

function renderHealthRows(rows) {
  if (!rows.length) return `<p class="health-empty">目前沒有需要顯示的項目</p>`;
  return rows.map((row) => `
    <div class="health-row">
      <div class="health-row-main">
        <strong>${sanitize(row.label)}</strong>
        ${row.detail ? `<small>${sanitize(row.detail)}</small>` : ""}
      </div>
      <span class="health-row-value" style="color:${row.color || "#82b1ff"};">${sanitize(row.value)}</span>
    </div>
  `).join("");
}

async function loadServerHealth() {
  if (!currentUser || currentRole !== "super_admin") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/health", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const summary = $("server-health-summary");
  const details = $("server-health-details");
  const workqueue = $("server-health-workqueue");
  const countsBox = $("server-health-counts");
  const storageBox = $("server-health-storage");
  const auditBox = $("server-health-audit");
  if (!summary || !details || !workqueue || !countsBox || !storageBox || !auditBox) return;
  if (!json.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "健康度讀取失敗")}</div>`;
    details.textContent = "";
    workqueue.innerHTML = "";
    countsBox.innerHTML = "";
    storageBox.innerHTML = "";
    auditBox.innerHTML = "";
    return;
  }
  const c = json.counts || {};
  const s = json.storage || {};
  const capacity = s.capacity_audit || {};
  const auditOk = json.audit_integrity && json.audit_integrity.ok;
  const auditEnabled = !(json.audit_integrity && json.audit_integrity.enabled === false);
  const readiness = json.readiness || {};
  const anomaly = json.anomaly || {};
  const readinessChecks = Array.isArray(readiness.checks) ? readiness.checks : [];
  const failedChecks = readinessChecks.filter((item) => !item.ok);
  const anomalySignals = Array.isArray(anomaly.signals) ? anomaly.signals : [];
  const statusLabel = json.status === "critical" ? "Critical" : json.status === "degraded" ? "Degraded" : "OK";
  const cards = [
    ["整體狀態", statusLabel, healthStatusColor(json.status)],
    ["維護模式", json.maintenance_mode ? "啟用" : "關閉", json.maintenance_mode ? "#ff4f6d" : "#4caf50"],
    ["審計鏈", auditEnabled ? (auditOk ? "完整" : "異常") : "停用", auditEnabled ? (auditOk ? "#4caf50" : "#ff4f6d") : "#9e9e9e"],
    ["Readiness", readiness.status || "unknown", healthStatusColor(readiness.status)],
    ["Anomaly", anomaly.status || "ok", healthStatusColor(anomaly.status)],
    ["活躍 Session", String(c.active_sessions || 0), "#82b1ff"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => renderHealthMetric(label, value, color)).join("");
  details.textContent = `最後讀取：${new Date().toLocaleString()} · DB schema ${readiness.database?.schema_version ?? "-"} / ${readiness.database?.expected_schema_version ?? "-"}`;
  const queueRows = [
    ["待審檢舉", c.pending_reports ?? c.pending_chat_reports ?? 0],
    ["待審申覆", c.pending_appeals || 0],
    ["治理提案", c.pending_moderation_proposals || 0],
    ["看板審核", c.pending_board_reviews || 0],
    ["主題審核", c.pending_thread_reviews || 0],
    ["隔離檔案", c.quarantined_files || 0],
    ["未知加密檔", c.unknown_encrypted_files || 0],
  ].map(([label, value]) => ({
    label,
    value: String(value),
    color: Number(value) > 0 ? "#ffb74d" : "#4caf50",
  }));
  workqueue.innerHTML = renderHealthRows(queueRows);
  countsBox.innerHTML = renderHealthRows([
    { label: "使用者", value: `${c.active_users || 0}/${c.users_total || 0}`, detail: "active / total", color: "#82b1ff" },
    { label: "聊天訊息", value: String(c.chat_messages || 0), color: "#82b1ff" },
    { label: "上傳檔案", value: String(c.uploaded_files || 0), color: "#82b1ff" },
    { label: "違規紀錄", value: String(c.violations_total || 0), color: "#82b1ff" },
    { label: "審計紀錄", value: String(c.audit_entries || 0), color: "#82b1ff" },
  ]);
  storageBox.innerHTML = renderHealthRows([
    { label: "SQLite DB", value: formatBytes(s.database_bytes), color: "#82b1ff" },
    { label: "聊天檔案", value: `${s.chat_files || 0} / ${formatBytes(s.chat_bytes)}`, detail: s.chat_dir || "chats/", color: "#82b1ff" },
    { label: "Server logs", value: `${s.log_files || 0} / ${formatBytes(s.log_bytes)}`, color: "#82b1ff" },
    { label: "Anchor files", value: `${s.anchor_files || 0} / ${formatBytes(s.anchor_bytes)}`, color: "#82b1ff" },
    { label: "Storage root", value: `${s.storage_files || 0} / ${formatBytes(s.storage_bytes)}`, color: "#82b1ff" },
    {
      label: "會員雲端容量審計",
      value: capacity.status === "critical" ? "超額" : capacity.status === "warning" ? "接近上限" : "正常",
      detail: `會員總配額 ${formatBytes(capacity.committed_total_bytes)} / Host 安全可用 ${formatBytes(capacity.available_cloud_capacity_bytes ?? capacity.disk?.safe_free_bytes)}，剩餘承諾 ${formatBytes(capacity.committed_remaining_bytes)} / 安全剩餘 ${formatBytes(capacity.disk?.safe_free_bytes)}`,
      color: capacity.status === "critical" ? "#ff4f6d" : capacity.status === "warning" ? "#ffb74d" : "#4caf50",
    },
    {
      label: "Host 實際可用",
      value: formatBytes(capacity.disk?.free_bytes),
      detail: `storage root: ${capacity.disk?.path || "-"}`,
      color: "#82b1ff",
    },
  ]);
  const auditRows = [
    {
      label: "Audit chain",
      value: auditEnabled ? (auditOk ? "完整" : "異常") : "停用",
      detail: json.audit_integrity?.details || "",
      color: auditEnabled ? (auditOk ? "#4caf50" : "#ff4f6d") : "#9e9e9e",
    },
    ...failedChecks.map((item) => ({
      label: `Readiness: ${item.name || "-"}`,
      value: item.severity || "failed",
      detail: item.detail || "",
      color: item.severity === "critical" ? "#ff4f6d" : "#ffb74d",
    })),
    ...(capacity.status && capacity.status !== "ok" ? [{
      label: "Storage capacity audit",
      value: capacity.status,
      detail: (capacity.reasons || []).join(", ") || "會員容量承諾已超過 Host 安全容量",
      color: capacity.status === "critical" ? "#ff4f6d" : "#ffb74d",
    }] : []),
    ...anomalySignals.map((item) => ({
      label: `Anomaly: ${item.name || "-"}`,
      value: item.level || "-",
      detail: item.detail || `value=${item.value}, threshold=${item.threshold}`,
      color: item.level === "critical" ? "#ff4f6d" : item.level === "warning" ? "#ffb74d" : "#82b1ff",
    })),
  ];
  auditBox.innerHTML = renderHealthRows(auditRows);
  const repairBtn = $("integrity-repair-btn");
  if (repairBtn) {
    repairBtn.disabled = currentUser !== "root" || !auditEnabled || auditOk !== false;
  }
}

async function repairIntegrityChains() {
  if (currentUser !== "root") {
    alert("只有 root 可處理鏈異常");
    return;
  }
  if (!confirm("確定要重新封鏈並解除維護模式？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/integrity/repair", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "鏈異常已處理" : "處理失敗"));
  await loadServerHealth();
  if (currentServerTab === "audit") await loadAudit(auditPage);
  if (currentAdminTab === "violations") await loadViolations(violationsPage, violationTargetUser);
}

async function loadIntegrityGuard() {
  if (!currentUser || currentUser !== "root") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const [statusRes, findingsRes] = await Promise.all([
    apiFetch(API + "/root/integrity/status", { credentials: "same-origin", headers: { "X-CSRF-Token": csrf || "" } }),
    apiFetch(API + "/root/integrity/findings?status=pending", { credentials: "same-origin", headers: { "X-CSRF-Token": csrf || "" } })
  ]);
  const statusJson = await statusRes.json().catch(() => ({}));
  const findingsJson = await findingsRes.json().catch(() => ({}));
  const summary = $("integrity-summary");
  const warning = $("integrity-warning");
  const list = $("integrity-findings");
  if (!summary || !warning || !list) return;
  if (!statusJson.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(statusJson.msg || "Integrity Guard 狀態讀取失敗")}</div>`;
    warning.textContent = "";
    list.innerHTML = "";
    return;
  }
  const ig = statusJson.integrity || {};
  const s = ig.summary || {};
  const last = ig.last_scan || {};
  const cards = [
    ["受保護檔案", String(ig.protected_files || 0), "#82b1ff"],
    ["Pending", String(s.pending || 0), (s.pending || 0) ? "#ffb74d" : "#4caf50"],
    ["High Risk", String(s.high_risk_pending || 0), (s.high_risk_pending || 0) ? "#ff4f6d" : "#4caf50"],
    ["Modified", String(s.modified || 0), (s.modified || 0) ? "#ffb74d" : "#82b1ff"],
    ["Added", String(s.added || 0), (s.added || 0) ? "#ffb74d" : "#82b1ff"],
    ["Deleted", String(s.deleted || 0), (s.deleted || 0) ? "#ff4f6d" : "#82b1ff"],
    ["上次掃描", sanitize(last.finished_at || last.started_at || "-"), "#82b1ff"],
    ["Manifest 簽章", last.manifest_signature_valid === 1 ? "有效" : "未驗證/異常", last.manifest_signature_valid === 1 ? "#4caf50" : "#ff4f6d"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${label}</div>
      <div style="font-size:1rem;color:${color};font-weight:700;margin-top:.2rem;word-break:break-all;">${value}</div>
    </div>
  `).join("");
  if ((s.high_risk_pending || 0) > 0) {
    warning.innerHTML = `<span style="color:#ff4f6d;font-weight:700;">高風險警告：</span>此變更涉及安全核心、root、admin、auth、snapshot、storage 或 Integrity Guard 本身。pending finding 會顯示 24 小時，逾期自動 approve；rejected high risk finding 仍會阻止進入準上線模式。`;
  } else if ((s.pending || 0) > 0) {
    warning.innerHTML = `<span style="color:#ffb74d;font-weight:700;">待處理：</span>存在尚未審核的檔案完整性變更，請確認是否為合法部署；pending 超過 24 小時會自動 approve。`;
  } else {
    warning.innerHTML = `<span style="color:#4caf50;font-weight:700;">正常：</span>目前沒有 pending finding。`;
  }
  const findings = Array.isArray(findingsJson.findings) ? findingsJson.findings : [];
  if (!findings.length) {
    list.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>目前沒有 pending integrity finding</p>";
    return;
  }
  list.innerHTML = findings.map((f) => `
    <div style="border:1px solid ${f.risk_level === "high" ? "rgba(255,79,109,.45)" : "rgba(255,255,255,.1)"};border-radius:9px;padding:.65rem;margin-bottom:.55rem;background:rgba(0,0,0,.22);">
      <div style="display:flex;gap:.45rem;align-items:center;flex-wrap:wrap;">
        <label style="display:inline-flex;align-items:center;gap:.25rem;color:var(--muted);"><input type="checkbox" class="integrity-finding-check" value="${f.id}" /> 選取</label>
        <strong>#${f.id}</strong>
        <span style="color:${f.risk_level === "high" ? "#ff4f6d" : f.risk_level === "medium" ? "#ffb74d" : "#82b1ff"};">${sanitize(f.risk_level || "")}</span>
        <span style="color:#82b1ff;">${sanitize(f.change_type || "")}</span>
        <span style="word-break:break-all;">${sanitize(f.file_path || "")}</span>
        <span style="margin-left:auto;color:var(--muted);">${sanitize(f.detected_at || "")}</span>
      </div>
      <div style="color:var(--muted);margin-top:.35rem;word-break:break-all;">old=${sanitize(f.old_hash || "-")} · new=${sanitize(f.new_hash || "-")}</div>
      <div style="color:var(--muted);margin-top:.2rem;">size ${f.old_size ?? "-"} -> ${f.new_size ?? "-"} · category=${sanitize(f.category || "")}</div>
      <div class="admin-toolbar" style="display:flex;gap:.45rem;margin-top:.5rem;">
        <button class="btn btn-primary" data-integrity-action="approve" data-finding-id="${f.id}">approve</button>
        <button class="btn" data-integrity-action="reject" data-finding-id="${f.id}">reject</button>
        <button class="btn" data-integrity-action="ignore" data-finding-id="${f.id}">ignore</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll("[data-integrity-action]").forEach((btn) => {
    btn.addEventListener("click", () => reviewIntegrityFinding(btn.getAttribute("data-finding-id"), btn.getAttribute("data-integrity-action")));
  });
  updateIntegritySelectedCount();
}

function selectedIntegrityFindingIds() {
  return Array.from(document.querySelectorAll(".integrity-finding-check:checked"))
    .map((item) => Number(item.value))
    .filter((value) => Number.isInteger(value) && value > 0);
}

function updateIntegritySelectedCount() {
  const count = selectedIntegrityFindingIds().length;
  const total = document.querySelectorAll(".integrity-finding-check").length;
  const el = $("integrity-selected-count");
  if (el) el.textContent = total > 0 ? `已選取 ${count}/${total} 筆` : "";
  const selectAll = $("integrity-select-all");
  if (selectAll) selectAll.checked = count > 0 && count === total;
  if (selectAll) selectAll.indeterminate = count > 0 && count < total;
}

function setupIntegritySelectAll() {
  const selectAll = $("integrity-select-all");
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      const checked = selectAll.checked;
      document.querySelectorAll(".integrity-finding-check").forEach((cb) => { cb.checked = checked; });
      updateIntegritySelectedCount();
    });
  }
  // Delegate for dynamically rendered findings
  document.addEventListener("change", (e) => {
    if (e.target && e.target.classList.contains("integrity-finding-check")) {
      updateIntegritySelectedCount();
    }
  });
}

async function rescanIntegrityGuard() {
  if (!confirm("重新掃描會比對目前檔案與已核准 manifest，異常不會自動核准。")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/integrity/rescan", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.ok ? "Integrity Guard 掃描完成" : (json.msg || "掃描失敗"));
  await loadIntegrityGuard();
}

async function reviewIntegrityFinding(id, action) {
  if (!id || !action) return;
  let confirmText = "";
  let note = "";
  if (action === "approve") {
    alert("approve 代表你確認這些檔案變更是合法部署或可信修改，系統將更新 hash manifest。");
    confirmText = prompt("請輸入 APPROVE INTEGRITY UPDATE 以確認：") || "";
    if (confirmText !== "APPROVE INTEGRITY UPDATE") {
      alert("確認字串不正確，已取消 approve。");
      return;
    }
  } else {
    if (!confirm(`確定要 ${action} 這筆 integrity finding？`)) return;
  }
  note = prompt("審核備註（可留空）：") || "";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/root/integrity/findings/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ confirm: confirmText, note })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "操作完成" : "操作失敗"));
  await loadIntegrityGuard();
}

async function reviewSelectedIntegrityFindings(action) {
  const ids = selectedIntegrityFindingIds();
  if (!ids.length) {
    alert("請先勾選要處理的 integrity finding。");
    return;
  }
  let confirmText = "";
  if (action === "approve") {
    alert("approve 代表你確認這些檔案變更是合法部署或可信修改，系統將更新 hash manifest。");
    confirmText = prompt(`將批次 approve ${ids.length} 筆 finding，請輸入 APPROVE INTEGRITY UPDATE 以確認：`) || "";
    if (confirmText !== "APPROVE INTEGRITY UPDATE") {
      alert("確認字串不正確，已取消批次 approve。");
      return;
    }
  } else if (!confirm(`確定要 ${action} 選取的 ${ids.length} 筆 integrity finding？`)) {
    return;
  }
  const note = prompt("批次審核備註（可留空）：") || "";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/integrity/findings/bulk-review", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ action, finding_ids: ids, confirm: confirmText, note })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.ok ? `批次操作完成：${json.reviewed}/${json.total}` : (json.msg || `批次操作失敗：${json.reviewed || 0}/${json.total || ids.length}`));
  await loadIntegrityGuard();
}

async function exportIntegrityReport() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/integrity/report", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    alert(json.msg || "匯出失敗");
    return;
  }
  const blob = new Blob([JSON.stringify(json.report || {}, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "integrity_report.json";
  a.click();
  URL.revokeObjectURL(url);
}

async function saveSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const captchaMode = $("s-captcha-mode")?.value || "none";
  const comfyuiMode = $("s-comfyui-connection-mode")?.value || "remote";
  const payload = {
    maintenance_mode: !!$("s-maintenance-mode")?.checked,
    audit_chain_enabled: !!$("s-audit-chain-enabled")?.checked,
    ip_blocking_enabled: !!$("s-ip-blocking-enabled")?.checked,
    login_violation_enabled: !!$("s-login-violation-enabled")?.checked,
    rate_limit_violation_enabled: !!$("s-rate-limit-violation-enabled")?.checked,
    root_ip_whitelist_enabled: !!$("s-root-ip-whitelist-enabled")?.checked,
    root_ip_whitelist: $("s-root-ip-whitelist")?.value || "",
    browser_only_mode_enabled: !!$("s-browser-only-mode-enabled")?.checked,
    integrity_guard_enabled: !!$("s-integrity-guard-enabled")?.checked,
    integrity_guard_strict_mode: !!$("s-integrity-guard-strict-mode")?.checked,
    allow_register: !!$("s-allow-register")?.checked,
    require_email_verification: !!$("s-require-email")?.checked,
    password_reset_mode: $("s-password-reset-mode")?.value || "admin_review",
    captcha_mode: captchaMode,
    captcha_ttl_seconds: parseInt($("s-captcha-ttl-seconds")?.value || "300"),
    captcha_turnstile_site_key: ($("s-captcha-turnstile-site-key")?.value || "").trim(),
    max_login_failures: parseInt($("s-max-fail")?.value || "5"),
    block_duration_minutes: parseInt($("s-block-dur")?.value || "30"),
    session_ttl_hours: parseInt($("s-session-ttl")?.value || "24"),
    session_idle_timeout_minutes: parseInt($("s-session-idle-timeout")?.value || "0") || null,
    server_ssl_enabled: $("s-server-ssl-enabled") ? !!$("s-server-ssl-enabled").checked : true,
    server_listen_host: ($("s-server-listen-host")?.value || "").trim(),
    server_listen_port: parseInt($("s-server-listen-port")?.value || "0"),
    comfyui_connection_mode: comfyuiMode,
    comfyui_remote_api_url: ($("s-comfyui-remote-api-url")?.value || "").trim(),
    comfyui_base_dir: ($("s-comfyui-base-dir")?.value || "").trim(),
    comfyui_local_start_script: ($("s-comfyui-local-start-script")?.value || "").trim(),
    comfyui_api_host: ($("s-comfyui-api-host")?.value || "localhost").trim(),
    comfyui_api_port: parseInt($("s-comfyui-api-port")?.value || "8192"),
    comfyui_civitai_api_key: ($("s-comfyui-civitai-api-key")?.value || "").trim(),
    comfyui_max_batch_size: parseInt($("s-comfyui-max-batch-size")?.value || "1"),
    comfyui_default_width: parseInt($("s-comfyui-default-width")?.value || "1024"),
    comfyui_default_height: parseInt($("s-comfyui-default-height")?.value || "1024"),
    cloud_drive_storage_root: ($("s-cloud-drive-storage-root")?.value || "").trim(),
    cloud_drive_transfer_limits_enabled: !!$("s-cloud-drive-transfer-limits-enabled")?.checked,
    cloud_drive_transfer_limits_json: JSON.stringify(collectCloudDriveTransferLimits()),
    storage_maintenance_auto_enabled: !!$("s-storage-maintenance-auto-enabled")?.checked,
    storage_maintenance_daily_time: $("s-storage-maintenance-daily-time")?.value || "04:00",
    storage_trash_retention_days: parseInt($("s-storage-trash-retention-days")?.value || "30"),
    snapshot_daily_auto_enabled: !!$("s-snapshot-daily-auto-enabled")?.checked,
    snapshot_daily_time: $("s-snapshot-daily-time")?.value || "03:00",
    module_chat_min_role: $("s-module-chat-min-role")?.value || "user",
    module_community_min_role: $("s-module-community-min-role")?.value || "user",
    module_appeals_min_role: $("s-module-appeals-min-role")?.value || "user",
    module_accounts_min_role: $("s-module-accounts-min-role")?.value || "manager",
    module_comfyui_min_role: $("s-module-comfyui-min-role")?.value || "user",
    module_games_min_role: $("s-module-games-min-role")?.value || "user",
    module_videos_min_role: $("s-module-videos-min-role")?.value || "user",
    video_tip_fee_percent: Number($("s-video-tip-fee-percent")?.value || 5),
    video_tip_min_points: parseInt($("s-video-tip-min-points")?.value || "1"),
    site_bg: $("s-site-bg")?.value || "#0f0f1a",
    site_surface: $("s-site-surface")?.value || "#1a1a2e",
    site_accent: $("s-site-accent")?.value || "#6c63ff",
    site_accent2: $("s-site-accent2")?.value || "#00d4aa",
    site_text: $("s-site-text")?.value || "#e0e0f0",
    site_muted: $("s-site-muted")?.value || "#8888aa",
    site_layout_mode: $("s-site-layout-mode")?.value || "centered",
    site_density: $("s-site-density")?.value || "comfortable",
    site_radius_px: parseInt($("s-site-radius-px")?.value || "12", 10) || 12,
    site_font_scale: Number($("s-site-font-scale")?.value || 1) || 1,
    site_content_width: parseInt($("s-site-content-width")?.value || "1380", 10) || 1380,
    site_font_family: $("s-site-font-family")?.value || "system",
    site_background_style: $("s-site-background-style")?.value || "flat",
    site_panel_style: $("s-site-panel-style")?.value || "glass",
    site_sidebar_width: $("s-site-sidebar-width")?.value || "standard"
  };
  FEATURE_SETTING_KEYS.forEach((key) => {
    const el = $(featureSettingInputId(key));
    if (el) payload[key] = !!el.checked;
  });
  const res = await apiFetch(API + "/admin/settings", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const bind = json.server_bind || {};
  const ssl = json.server_ssl || {};
  const driveStorage = json.cloud_drive_storage || {};
  const restartParts = [];
  if (bind.restart_required) restartParts.push("listen IP/port");
  if (ssl.restart_required) restartParts.push("HTTPS 開關");
  if (driveStorage.restart_required) restartParts.push("雲端硬碟儲存位置");
  const restartHint = restartParts.length ? `，${restartParts.join("、")} 需重啟服務器後生效` : "";
  if (!json.ok) {
    setSettingsStatus(json.msg || "儲存失敗", false);
  }
  if (json.ok) {
    const activeModule = currentModuleTab;
    const activeServerTab = currentServerTab;
    const activeSettingsSection = currentSettingsSection;
    applySiteConfig(payload);
    const warnings = buildFeatureAdvisories().filter((item) => item.missingRequired.length);
    const warningHint = warnings.length ? `；仍有父功能未齊：${warnings.map(formatFeatureAdvisoryLine).join("、")}` : "";
    setSettingsStatus(
      `${warnings.length ? "設定已儲存，但功能組合仍未完整" : "✅ 設定已儲存"}${restartHint}${warningHint}`,
      warnings.length ? null : true,
      { autoClearMs: warnings.length ? 0 : 4000 }
    );
    renderFeatureAdvisories();
    const idleMinutes = Number(payload.session_idle_timeout_minutes ?? 10);
    inactivityLogoutMs = idleMinutes > 0 ? Math.max(1, idleMinutes) * 60 * 1000 : 0;
    if (inactivityLogoutMs > 0) resetInactivityTimer();
    if (typeof syncSidebarMenuVisibility === "function") syncSidebarMenuVisibility();
    if (activeModule && typeof switchModuleTab === "function") {
      suppressNextSettingsStatusClear = true;
      currentServerTab = activeServerTab;
      currentSettingsSection = activeSettingsSection;
      switchModuleTab(activeModule);
    }
  }
}

async function testComfyuiConnection() {
  const status = $("comfyui-test-connection-status");
  const button = $("comfyui-test-connection-btn");
  const mode = $("s-comfyui-connection-mode")?.value || "remote";
  const host = ($("s-comfyui-api-host")?.value || "localhost").trim();
  const port = parseInt($("s-comfyui-api-port")?.value || "8192", 10);
  const apiUrl = ($("s-comfyui-remote-api-url")?.value || "").trim();
  const baseDir = ($("s-comfyui-base-dir")?.value || "").trim();
  const startScript = ($("s-comfyui-local-start-script")?.value || "").trim();
  const targetLabel = mode === "local"
    ? `本地 http://${host || "localhost"}:${Number.isFinite(port) ? port : "-"}`
    : (apiUrl || "遠端 API");
  if (status) {
    status.dataset.userTouched = "1";
    status.textContent = `正在測試 ${targetLabel} ...`;
    status.style.color = "var(--muted)";
  }
  if (button) button.disabled = true;
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/comfyui/test-connection", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({
        mode,
        api_url: apiUrl,
        host,
        port,
        base_dir: baseDir,
        local_start_script: startScript
      })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 連線測試失敗（HTTP ${res.status}）`);
    if (status) {
      const script = json.local_script || {};
      const scriptText = mode === "local" && script.configured
        ? `；啟動腳本${script.exists ? "存在" : "缺失"}${script.syntax_ok === false ? "，語法檢查失敗" : (script.syntax_ok === true ? "，語法正常" : "")}`
        : "";
      const autostart = json.autostart || {};
      const startupLogTail = Array.isArray((json.local_runtime || {}).startup_log_tail)
        ? json.local_runtime.startup_log_tail.filter(Boolean)
        : (Array.isArray(autostart.start?.startup_log_tail) ? autostart.start.startup_log_tail.filter(Boolean) : []);
      const startupLogText = startupLogTail.length ? `；最近輸出：${startupLogTail.join(" / ")}` : "";
      const autostartText = mode === "local" && autostart.attempted
        ? `；${autostart.available ? "已成功自動啟動 ComfyUI" : (autostart.message || "已嘗試自動啟動 ComfyUI，仍未就緒")}${startupLogText}`
        : "";
      if (json.available) {
        status.textContent = `連線成功：${json.comfyui_url || targetLabel}${scriptText}${autostartText}`;
        status.style.color = "#4caf50";
      } else if (json.starting) {
        status.textContent = `啟動中：${json.msg || "ComfyUI 正在初始化"}（${json.comfyui_url || targetLabel}）${scriptText}${autostartText}`;
        status.style.color = "#f5b544";
      } else {
        status.textContent = `連線失敗：${json.msg || "ComfyUI 沒有回應"}（${json.comfyui_url || targetLabel}）${scriptText}${autostartText}`;
        status.style.color = "#ff4f6d";
      }
    }
  } catch (err) {
    if (status) {
      status.textContent = err.message || "ComfyUI 連線測試失敗";
      status.style.color = "#ff4f6d";
    }
  } finally {
    if (button) button.disabled = false;
  }
}

function setServerUpdateStatus(message, ok = true) {
  const el = $("server-update-status");
  if (!el) return;
  el.textContent = message || "";
  el.className = `msg show ${ok ? "ok" : "err"}`;
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function renderServerUpdateSummary(summary) {
  const box = $("server-update-summary");
  if (!box) return;
  box.textContent = summary || "尚未提供更新摘要。每次 push 前請更新 docs/UPDATE_SUMMARY.md。";
}

function renderServerUpdatePreview(preview) {
  const box = $("server-update-diff");
  if (!box) return;
  if (!preview || !preview.ok) {
    box.textContent = preview?.msg || "";
    renderServerUpdateSummary(preview?.release_summary || "");
    return;
  }
  renderServerUpdateSummary(preview.release_summary || preview.state?.release_summary || "");
  const state = preview.state || {};
  const summary = preview.summary || {};
  const files = (preview.changed_files || []).map((row) => `${row.status}\t${row.path}`).join("\n");
  box.textContent = [
    `目前分支：${state.current_branch || "-"} @ ${state.current_commit || "-"}`,
    `目標分支：${preview.remote_ref || "-"}`,
    `本地 ahead：${summary.ahead ?? "-"}，遠端 ahead：${summary.behind ?? "-"}`,
    `工作目錄：${state.dirty ? "有未提交變更（更新時將自動暫存）" : "乾淨"}`,
    "",
    "警告：",
    preview.warning || "此次更新未經驗證，請自行測試與 debug。",
    "",
    "Diff stat：",
    preview.diff_stat || "(無差異)",
    "",
    "Changed files：",
    files || "(無檔案變更)"
  ].join("\n");
}

async function loadServerUpdateStatus(fetchRemote = false) {
  if (currentUser !== "root") return;
  const branchSelect = $("server-update-branch-select");
  const refreshBtn = $("server-update-refresh-btn");
  if (refreshBtn) refreshBtn.disabled = true;
  setServerUpdateStatus(fetchRemote ? "正在從 GitHub 讀取分支..." : "正在讀取更新狀態...");
  try {
    const csrf = await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + `/root/server-update/status${fetchRemote ? "?fetch=1" : ""}`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || json.update?.msg || `更新狀態讀取失敗（HTTP ${res.status}）`);
    const update = json.update || {};
    const branches = update.branches || [];
    if (branchSelect) {
      const previous = branchSelect.value || update.current_branch || "";
      branchSelect.innerHTML = branches.length
        ? branches.map((branch) => `<option value="${sanitize(branch)}">${sanitize(branch)}</option>`).join("")
        : `<option value="${sanitize(update.current_branch || "main")}">${sanitize(update.current_branch || "main")}</option>`;
      branchSelect.value = branches.includes(previous) ? previous : (branches.includes(update.current_branch) ? update.current_branch : (branches[0] || update.current_branch || "main"));
    }
    setServerUpdateStatus(`目前 ${update.current_branch || "-"} @ ${update.current_commit || "-"}；${update.dirty ? "工作目錄有未提交變更，不能套用更新" : "工作目錄乾淨"}`, !update.dirty);
    renderServerUpdateSummary(update.release_summary || "");
    renderServerUpdatePreview({ ok: true, state: update, warning: json.warning, summary: {}, changed_files: [], diff_stat: "" });
  } catch (err) {
    setServerUpdateStatus(err.message || "更新狀態讀取失敗", false);
  } finally {
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

async function previewServerUpdate() {
  const branch = $("server-update-branch-select")?.value || "";
  const btn = $("server-update-preview-btn");
  if (!branch) {
    setServerUpdateStatus("請先選擇更新分支", false);
    return;
  }
  if (btn) btn.disabled = true;
  setServerUpdateStatus("正在 fetch GitHub 並產生 diff 預覽...");
  try {
    const csrf = await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/server-update/preview", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify({ branch })
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || json.preview?.msg || `diff 預覽失敗（HTTP ${res.status}）`);
    renderServerUpdatePreview(json.preview || {});
    setServerUpdateStatus("Diff 預覽完成。套用前請確認更新未經驗證，並輸入確認字串。");
  } catch (err) {
    setServerUpdateStatus(err.message || "diff 預覽失敗", false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function applyServerUpdate() {
  const branch = $("server-update-branch-select")?.value || "";
  const confirmText = $("server-update-confirm")?.value || "";
  const btn = $("server-update-apply-btn");
  if (!branch) {
    setServerUpdateStatus("請先選擇更新分支", false);
    return;
  }
  if (confirmText !== "APPLY_UNVERIFIED_UPDATE") {
    setServerUpdateStatus("請輸入 APPLY_UNVERIFIED_UPDATE 才能套用未驗證更新", false);
    return;
  }
  if (!confirm("此更新會從 GitHub 套用到目前伺服器程式碼，且尚未經本機測試驗證。確定繼續？")) return;
  if (btn) btn.disabled = true;
  setServerUpdateStatus("正在套用 GitHub 更新，請勿關閉頁面...");
  try {
    const csrf = await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/server-update/apply", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify({ branch, confirm: confirmText })
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || `更新套用失敗（HTTP ${res.status}）`);
    const preview = json.preview || {};
    const releaseSummary = json.release_summary || preview.release_summary || "";
    preview.release_summary = releaseSummary;
    renderServerUpdatePreview(preview);
    if (releaseSummary) renderServerUpdateSummary(releaseSummary);
    const integrity = json.integrity?.result?.summary || {};
    const snapshotId = json.recovery?.snapshot?.snapshot_id || "-";
    const backupId = json.recovery?.points_backup?.backup_id || "-";
    const restartMode = json.restart?.mode || "scheduled";
    setServerUpdateStatus(`更新已套用，已建立 snapshot=${snapshotId}、PointsChain backup=${backupId}，伺服器將自動重啟（${restartMode}）；Integrity pending=${integrity.pending ?? "-"}`);
    if (typeof loadIntegrityGuard === "function") await loadIntegrityGuard();
  } catch (err) {
    setServerUpdateStatus(err.message || "更新套用失敗", false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadServerEnv() {
  if (!currentUser || currentRole !== "super_admin") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/environment", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const summary = $("server-env-summary");
  const details = $("server-env-details");
  if (!summary || !details) return;
  if (!json.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "系統環境讀取失敗")}</div>`;
    details.textContent = "";
    return;
  }
  const env = json.environment || {};
  const cards = [
    ["作業平台", env.platform || "-", "#82b1ff"],
    ["Python", env.python_version || "-", "#82b1ff"],
    ["資料庫", formatBytes(env.database_bytes || 0), "#82b1ff"],
    ["程序 PID", String(env.pid || "-"), "#82b1ff"],
    ["Log 檔數", String(env.log_files || 0), "#82b1ff"],
    ["Anchor 檔數", String(env.anchor_files || 0), "#82b1ff"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${label}</div>
      <div style="font-size:1.05rem;color:${color};font-weight:700;margin-top:.2rem;">${sanitize(value)}</div>
    </div>
  `).join("");
  details.innerHTML = [
    `BASE_DIR：${sanitize(env.base_dir || ".")}`,
    `DB：${sanitize(env.database_path || "-")}`,
    `Log：${sanitize(env.log_dir || "-")}`,
    `Chat：${sanitize(env.chat_dir || "-")}`,
    `Anchor：${sanitize(env.anchor_dir || "-")}`,
    `聊天檔數：${sanitize(String(env.chat_files || 0))}`,
  ].join("<br>");
}

async function restartServer(event) {
  if (event && typeof event.preventDefault === "function") event.preventDefault();
  if (!confirm("⚠️ 確定要重啟伺服器？所有連線將中斷。")) return;
  const status = $("restart-server-status");
  const button = $("restart-server-btn");
  const previousStartedAt = serverMeta?.started_at || "";
  if (button) button.disabled = true;
  if (status) {
    status.textContent = "已送出重啟指令，等待伺服器離線...";
    status.className = "msg show";
  }
  try {
    if (status) status.textContent = "正在驗證操作權限...";
    const csrf = await fetchCsrfToken({ force: true });
    if (!csrf) throw new Error("安全驗證狀態失效，請重新整理頁面後再試。");
    if (status) status.textContent = "已送出重啟指令，等待伺服器離線...";
    const res = await apiFetch(API + "/admin/restart", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "重啟失敗");
    const wentOffline = await waitForRestartOffline(25000);
    if (!wentOffline) throw new Error("25 秒內沒有偵測到伺服器離線，重啟流程可能沒有真正執行。");
    if (status) status.textContent = "已偵測到離線，等待伺服器恢復...";
    const onlineMeta = await waitForRestartOnline(previousStartedAt, 180000);
    if (!onlineMeta) throw new Error("3 分鐘內未重新連線，請檢查 server log。");
    renderServerVersion(onlineMeta);
    if (status) {
      status.textContent = "伺服器已重啟完成，正在重新載入頁面...";
      status.className = "msg show ok";
    }
    setTimeout(() => location.reload(), 900);
  } catch (err) {
    if (status) {
      status.textContent = err.message || "重啟失敗";
      status.className = "msg show err";
    } else {
      alert(err.message || "重啟失敗");
    }
    if (button) button.disabled = false;
  }
}

async function probeRestartVersion(timeoutMs = 1500) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(API + "/version?restart_probe=" + Date.now(), {
      credentials: "same-origin",
      cache: "no-store",
      signal: ctrl.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    const json = await res.json().catch(() => ({}));
    return json && json.ok ? json : null;
  } catch (_) {
    clearTimeout(timer);
    return null;
  }
}

async function waitForRestartOffline(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const meta = await probeRestartVersion(1200);
    if (!meta) return true;
    await new Promise((resolve) => setTimeout(resolve, 650));
  }
  return false;
}

async function waitForRestartOnline(previousStartedAt, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const meta = await probeRestartVersion(1800);
    if (meta && (!previousStartedAt || meta.started_at !== previousStartedAt)) return meta;
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  return null;
}

// ── Snapshot / Reset Server ───────────────────────────────────

async function loadSnapshots() {
  const list = $("snapshot-list");
  const actions = $("snapshot-actions");
  if (!list || !actions) return;
  list.innerHTML = "<em>載入中…</em>";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/snapshots", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    list.innerHTML = `<span style="color:#ff4f6d;">${sanitize(json.msg || "載入失敗")}</span>`;
    actions.innerHTML = "";
    return;
  }
  const snapshots = json.snapshots || [];
  if (!snapshots.length) {
    list.innerHTML = "<em>目前沒有 snapshot</em>";
    actions.innerHTML = "";
    return;
  }
  list.innerHTML = snapshots.map((s) => `
    <div style="border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:.55rem;margin-bottom:.5rem;background:rgba(0,0,0,.2);">
      <div style="display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;">
        <strong style="color:#82b1ff;">${sanitize(s.snapshot_id || s.id || "")}</strong>
        <span style="color:${s.snapshot_type === "manual" ? "#4caf50" : s.snapshot_type === "daily" ? "#ffb74d" : "#9e9e9e"};">${sanitize(s.snapshot_type || "")}</span>
        <span style="color:var(--muted);font-size:.72rem;">${sanitize(s.created_at || s.ts || "")}</span>
        <span style="color:var(--muted);font-size:.72rem;">${sanitize(s.actor || "")}</span>
      </div>
      <div style="color:var(--muted);font-size:.7rem;margin-top:.2rem;">${sanitize(s.notes || "")}</div>
      <div style="display:flex;gap:.4rem;margin-top:.45rem;">
        <button class="btn btn-primary" type="button" data-snapshot-restore="${sanitize(s.snapshot_id || s.id || "")}" style="padding:.2rem .6rem;font-size:.72rem;">Restore</button>
        <button class="btn" type="button" data-snapshot-download="${sanitize(s.snapshot_id || s.id || "")}" style="padding:.2rem .6rem;font-size:.72rem;">下載</button>
        <button class="btn" type="button" data-snapshot-delete="${sanitize(s.snapshot_id || s.id || "")}" style="padding:.2rem .6rem;font-size:.72rem;">刪除</button>
      </div>
    </div>
  `).join("");
  actions.innerHTML = `
    <button class="btn btn-primary" type="button" id="btn-confirm-restore" disabled style="padding:.3rem .75rem;font-size:.78rem;">Restore 選取的 Snapshot</button>
    <span id="restore-hint" style="font-size:.72rem;color:var(--muted);margin-left:.4rem;">請先點選要 restore 的 snapshot</span>
  `;
  list.querySelectorAll("[data-snapshot-restore]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      document.querySelectorAll("[data-snapshot-restore]").forEach((b) => { b.classList.remove("btn-primary"); b.classList.add("btn"); });
      btn.classList.remove("btn"); btn.classList.add("btn-primary");
      window._selectedSnapshotId = btn.getAttribute("data-snapshot-restore");
      const confirmBtn = $("btn-confirm-restore");
      if (confirmBtn) { confirmBtn.disabled = false; }
      const hint = $("restore-hint");
      if (hint) hint.textContent = `已選取：${window._selectedSnapshotId}，確認後將執行 restore`;
    });
  });
  list.querySelectorAll("[data-snapshot-download]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const id = btn.getAttribute("data-snapshot-download");
      downloadSnapshot(id);
    });
  });
  list.querySelectorAll("[data-snapshot-delete]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const id = btn.getAttribute("data-snapshot-delete");
      if (!confirm(`確定刪除 snapshot ${id}？`)) return;
      await fetchCsrfToken({ force: true });
      const csrf = getCsrfToken();
      const r = await apiFetch(API + `/admin/snapshots/${encodeURIComponent(id)}?reason=admin_delete`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf || "" }
      });
      const j = await r.json().catch(() => ({}));
      alert(j.msg || (j.ok ? "已刪除" : "刪除失敗"));
      if (j.ok) await loadSnapshots();
    });
  });
  const confirmRestoreBtn = $("btn-confirm-restore");
  if (confirmRestoreBtn) {
    confirmRestoreBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const sid = window._selectedSnapshotId;
      if (!sid) { alert("請先選取要 restore 的 snapshot"); return; }
      const reason = prompt("請輸入 restore 原因：") || "";
      const confirmText = prompt(`確定要 restore 到 snapshot ${sid}？\n此操作會重啟服務，請輸入 RESTORE 確認：`) || "";
      if (confirmText !== "RESTORE") { alert("確認字串不正確，已取消"); return; }
      performRestore(sid, reason);
    });
  }
}

async function downloadSnapshot(snapshotId) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/admin/snapshots/${encodeURIComponent(snapshotId)}/download`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    alert(json.msg || "下載失敗");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  link.href = url;
  link.download = match ? match[1] : `${snapshotId}.snapshot.tar.gz`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function performRestore(snapshotId, reason) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/admin/snapshots/${encodeURIComponent(snapshotId)}/restore`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ confirm: "RESTORE", reason })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "Restore 請求已提交，系統將重啟" : "Restore 請求失敗"));
  if (json.ok) setTimeout(() => location.reload(), 3000);
}

async function uploadSnapshotRestore() {
  const input = $("snapshot-upload-file");
  const file = input?.files?.[0];
  if (!file) { alert("請先選擇 snapshot 封包"); return; }
  const reason = prompt("請輸入 restore 原因：") || "";
  const confirmText = prompt("確定要使用上傳的 snapshot 封包 restore？\n此操作會覆蓋目前 runtime 狀態，請輸入 RESTORE 確認：") || "";
  if (confirmText !== "RESTORE") { alert("確認字串不正確，已取消"); return; }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  form.append("file", file);
  form.append("confirm", "RESTORE");
  form.append("reason", reason);
  const res = await apiFetch(API + "/admin/snapshots/upload-restore", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "Upload restore 已完成" : "Upload restore 失敗"));
  if (json.ok) setTimeout(() => location.reload(), 3000);
}

async function createSnapshot() {
  const notes = prompt("Snapshot 備註（可留空）：") || "";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/snapshots", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ confirm: "CREATE_SNAPSHOT", notes })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "Snapshot 建立成功" : "建立失敗"));
  if (json.ok) await loadSnapshots();
}

async function resetServer() {
  const reason = $("s-reset-reason")?.value || "";
  const confirmText = $("s-reset-confirm")?.value || "";
  const status = $("reset-status");
  if (confirmText !== "RESET_RUNTIME_STATE") {
    if (status) { status.textContent = "確認字串錯誤，請輸入 RESET_RUNTIME_STATE"; status.style.color = "#ff4f6d"; }
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/system-reset", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ confirm: "RESET_RUNTIME_STATE", reason })
  });
  const json = await res.json().catch(() => ({}));
  if (status) {
    status.textContent = json.msg || (json.ok ? "Reset 請求已提交，系統將重啟" : "Reset 失敗");
    status.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) setTimeout(() => location.reload(), 4500);
}

// ── Integrity Guard quick-button handlers ──────────────────────

async function refreshIntegrityGuard() {
  await loadIntegrityGuard();
}

async function rescanIntegrityGuard() {
  if (!confirm("重新掃描會比對目前檔案與已核准 manifest，異常不會自動核准。")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/root/integrity/scan", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({})
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "掃描完成" : "掃描失敗"));
  if (json.ok) await loadIntegrityGuard();
}

async function exportIntegrityGuard() {
  await exportIntegrityReport();
}

// ── Platform Stats (traffic, active users, point balance) ─────

function platformStatNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function renderPlatformBarChart(title, rows, options = {}) {
  const maxValue = Math.max(1, ...rows.map((row) => Math.abs(platformStatNumber(row.value))));
  return `
    <div class="platform-stats-chart" style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.75rem;min-width:0;">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.6rem;">
        <strong style="color:#e0e0f0;">${sanitize(title)}</strong>
        ${options.caption ? `<small style="color:var(--muted);margin-left:auto;">${sanitize(options.caption)}</small>` : ""}
      </div>
      <div style="display:grid;gap:.48rem;">
        ${rows.map((row) => {
          const value = platformStatNumber(row.value);
          const percent = Math.max(3, Math.min(100, Math.round((Math.abs(value) / maxValue) * 100)));
          const color = row.color || "#82b1ff";
          return `
            <div class="platform-chart-row" style="display:grid;grid-template-columns:minmax(5.5rem,.72fr) minmax(8rem,1.6fr) minmax(3.2rem,.35fr);gap:.55rem;align-items:center;">
              <span style="color:var(--muted);font-size:.72rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${sanitize(row.label)}</span>
              <div style="height:.72rem;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden;">
                <div style="height:100%;width:${percent}%;background:${color};border-radius:999px;"></div>
              </div>
              <strong style="color:${color};font-size:.78rem;text-align:right;white-space:nowrap;">${sanitize(String(value))}</strong>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function renderPlatformNetChart(stats) {
  const earned = platformStatNumber(stats.points_earned_month);
  const spent = platformStatNumber(stats.points_spent_month);
  const net = platformStatNumber(stats.points_net_month);
  const maxValue = Math.max(1, earned, spent, Math.abs(net));
  const positiveWidth = net >= 0 ? Math.min(50, Math.round((net / maxValue) * 50)) : 0;
  const negativeWidth = net < 0 ? Math.min(50, Math.round((Math.abs(net) / maxValue) * 50)) : 0;
  const netColor = net >= 0 ? "#4caf50" : "#ff4f6d";
  return `
    <div class="platform-stats-chart" style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.75rem;min-width:0;">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.6rem;">
        <strong style="color:#e0e0f0;">本月積分淨值</strong>
        <small style="color:var(--muted);margin-left:auto;">收入 - 支出</small>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;align-items:center;margin:.9rem 0 .6rem;">
        <div style="height:1.05rem;background:rgba(255,255,255,.08);border-radius:999px 0 0 999px;display:flex;justify-content:flex-end;overflow:hidden;">
          <div style="height:100%;width:${negativeWidth}%;background:#ff4f6d;"></div>
        </div>
        <div style="height:1.05rem;background:rgba(255,255,255,.08);border-radius:0 999px 999px 0;overflow:hidden;">
          <div style="height:100%;width:${positiveWidth}%;background:#4caf50;"></div>
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;gap:.75rem;font-size:.75rem;color:var(--muted);">
        <span>支出 ${spent}</span>
        <strong style="color:${netColor};">淨值 ${net}</strong>
        <span>收入 ${earned}</span>
      </div>
      <div style="margin-top:.75rem;border-top:1px solid rgba(255,255,255,.08);padding-top:.65rem;color:#ce93d8;font-weight:700;">
        積分總庫存 ${sanitize(String(platformStatNumber(stats.total_points)))}
      </div>
    </div>
  `;
}

async function loadPlatformStats() {
  const container = $("platform-stats");
  if (!container) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/admin/platform-stats", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    container.innerHTML = `<span style="color:#ff4f6d;">${sanitize(json.msg || "讀取失敗")}</span>`;
    return;
  }
  const stats = json.stats || {};
  container.innerHTML = `
    ${renderPlatformBarChart("流量與使用者", [
      { label: "今日瀏覽量", value: stats.page_views_today, color: "#82b1ff" },
      { label: "同時在線", value: stats.active_sessions, color: "#4caf50" },
      { label: "本月新用戶", value: stats.new_users_month, color: "#ffb74d" },
      { label: "總用戶數", value: stats.total_users, color: "#82b1ff" },
    ], { caption: "人次 / 帳號" })}
    ${renderPlatformBarChart("本月積分收支", [
      { label: "收入", value: stats.points_earned_month, color: "#4caf50" },
      { label: "支出", value: stats.points_spent_month, color: "#ff4f6d" },
      { label: "淨值", value: stats.points_net_month, color: platformStatNumber(stats.points_net_month) >= 0 ? "#4caf50" : "#ff4f6d" },
    ], { caption: "points" })}
    ${renderPlatformNetChart(stats)}
  `;
}

 // ── Bind all UI events ───────────────────────────────────────
(function setupUIBindings() {
  // Snapshot / Reset
  const loadSnapBtn = document.getElementById("btn-load-snapshots");
  if (loadSnapBtn) loadSnapBtn.addEventListener("click", loadSnapshots);
  const createSnapBtn = document.getElementById("btn-create-snapshot");
  if (createSnapBtn) createSnapBtn.addEventListener("click", createSnapshot);
  const uploadRestoreBtn = document.getElementById("btn-upload-snapshot-restore");
  if (uploadRestoreBtn) uploadRestoreBtn.addEventListener("click", uploadSnapshotRestore);
  const resetBtn = document.getElementById("btn-reset-server");
  if (resetBtn) resetBtn.addEventListener("click", resetServer);

  // Platform Stats
  const psRefreshBtn = document.getElementById("platform-stats-refresh-btn");
  if (psRefreshBtn) psRefreshBtn.addEventListener("click", loadPlatformStats);

  // Init select-all after DOM ready
  setupIntegritySelectAll();
})();
