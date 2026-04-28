'use strict';

const API = "/api";
let _csrfToken = null;
let currentUser = null;
let currentUserId = null;
let currentRole = "user";
let currentRoleLabel = "user";
let currentMustChangePassword = false;
let forcedPasswordChangeMode = false;
let canManageUsers = false;
let currentModuleTab = "chat";
let currentServerTab = "security";
let users = [];
let editingUserId = null;
let editingUserIsSelf = false;
let userAppeals = [];
let adminAppeals = [];
let adminAppealPage = 1;
let adminAppealStatus = "pending";
let adminReports = [];
let adminReportPage = 0;
let adminReportStatus = "pending";
const editingUserOriginal = {};
let selectedPendingUserIds = new Set();
let selectedAppealIds = new Set();
let selectedReportIds = new Set();
let chatRooms = [];
let selectedChatRoomId = null;
let chatPollTimer = null;
let dmThreads = [];
let selectedDmThreadId = null;
const CHAT_POLL_MS = 2500;
const DEFAULT_INACTIVITY_LOGOUT_MS = 3 * 60 * 1000;
let inactivityLogoutMs = DEFAULT_INACTIVITY_LOGOUT_MS;
let inactivityTimer = null;
let inactivityCountdownTimer = null;
let inactivityDeadline = null;
let inactivityWarned = false;
let clockTimer = null;
let siteConfig = {};
let serverMeta = {};
let currentSettingsSection = "security";
let serverConnectionFailures = 0;
let serverConnectionTimer = null;
let notificationPollTimer = null;
let notificationsOpen = false;

function clientRoleRank(role) {
  if (role === "super_admin") return 3;
  if (role === "manager") return 2;
  return 1;
}

function getModuleMinRole(moduleKey, fallbackRole) {
  const key = `module_${moduleKey}_min_role`;
  const value = siteConfig && typeof siteConfig[key] === "string" ? siteConfig[key] : fallbackRole;
  return ["user", "manager", "super_admin"].includes(value) ? value : fallbackRole;
}

function canAccessModule(moduleKey, role = currentRole) {
  const featureKey = `feature_${moduleKey}_enabled`;
  if (siteConfig && siteConfig[featureKey] === false) return false;
  const fallback = moduleKey === "accounts" ? "manager" : "user";
  return clientRoleRank(role || "user") >= clientRoleRank(getModuleMinRole(moduleKey, fallback));
}

function $(id) { return document.getElementById(id); }

const SIDEBAR_COLLAPSED_STORAGE_KEY = "hackme_web.sidebar.collapsed";
const SIDEBAR_ICON_PATHS = {
  chat: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7A2.5 2.5 0 0 1 17.5 15H9l-5 4v-4.5A2.5 2.5 0 0 1 4 12.5z"/>',
  mail: '<path d="M4 6h16v12H4z"/><path d="m4 7 8 6 8-6"/>',
  bell: '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 19a2 2 0 0 0 4 0"/>',
  forum: '<path d="M5 5h14v9H8l-3 3z"/><path d="M8 8h8M8 11h5"/>',
  drive: '<path d="M4 8h16l-2 10H6z"/><path d="m7 8 2-3h6l2 3"/>',
  image: '<path d="M5 5h14v14H5z"/><path d="m7 16 4-4 3 3 2-2 2 3"/><path d="M8.5 8.5h.01"/>',
  spark: '<path d="M12 3 9.5 9.5 3 12l6.5 2.5L12 21l2.5-6.5L21 12l-6.5-2.5z"/>',
  appeal: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><path d="M9.5 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  shield: '<path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="m9 12 2 2 4-5"/>',
};
const SIDEBAR_MENU_CONFIG = [
  { tabId: "tab-module-chat", module: "chat", tab: "chat", icon: "chat", label: "聊天", group: "日常" },
  { tabId: "tab-module-dm", module: "dm", tab: "dm", icon: "mail", label: "站內信", group: "日常" },
  { tabId: "tab-module-announcements", module: "community", tab: "announcements", icon: "bell", label: "公告", group: "社群" },
  {
    tabId: "tab-module-community",
    module: "community",
    tab: "community",
    icon: "forum",
    label: "討論區",
    group: "社群",
    submenu: [
      { label: "看板清單", action: "module:community" },
      { label: "主題審核", action: "community:review" },
    ],
  },
  {
    tabId: "tab-module-drive",
    module: "privacy_uploads",
    tab: "drive",
    icon: "drive",
    label: "雲端硬碟",
    group: "工具",
    submenu: [
      { label: "檔案清單", action: "module:drive" },
      { label: "相簿", action: "module:albums" },
    ],
  },
  { tabId: "tab-module-albums", module: "privacy_uploads", tab: "albums", icon: "image", label: "相簿", group: "工具" },
  { tabId: "tab-module-comfyui", module: "comfyui", tab: "comfyui", icon: "spark", label: "AI 產圖", group: "工具" },
  { tabId: "tab-module-appeals", module: "appeals", tab: "appeals", icon: "appeal", label: "申覆", group: "支援", hideForSuperAdmin: true },
  {
    tabId: "tab-module-accounts",
    module: "accounts",
    tab: "accounts",
    icon: "users",
    label: "帳號管理",
    group: "管理",
    submenu: [
      { label: "帳號", action: "admin:users" },
      { label: "違規計次", action: "admin:violations" },
      { label: "會員治理", action: "admin:governance" },
      { label: "申覆審核", action: "admin:appeals" },
      { label: "訊息檢舉", action: "admin:reports" },
    ],
  },
  {
    tabId: "tab-module-server",
    role: "super_admin",
    tab: "server",
    icon: "shield",
    label: "安全中心",
    group: "管理",
    submenu: [
      { label: "總覽", action: "server:security" },
      { label: "審計日誌", action: "server:audit" },
      { label: "健康度", action: "server:health" },
      { label: "Integrity Guard", action: "server:integrity" },
      { label: "伺服器設定", action: "server:settings" },
      { label: "系統環境", action: "server:env" },
    ],
  },
];

function sidebarIconSvg(icon) {
  const paths = SIDEBAR_ICON_PATHS[icon] || SIDEBAR_ICON_PATHS.chat;
  return `<svg class="sidebar-icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths}</svg>`;
}

function sidebarItemForTab(tabId) {
  return SIDEBAR_MENU_CONFIG.find((item) => item.tabId === tabId);
}

function canShowSidebarItem(item) {
  if (!item || !currentUser) return false;
  if (item.hideForSuperAdmin && currentRole === "super_admin") return false;
  if (item.role === "super_admin") return currentRole === "super_admin";
  return canAccessModule(item.module);
}

function decorateSidebarMenu() {
  SIDEBAR_MENU_CONFIG.forEach((item) => {
    const button = $(item.tabId);
    if (!button || button.dataset.sidebarDecorated === "1") return;
    if (item.group && !$("sidebar-group-" + item.group)) {
      const group = document.createElement("div");
      group.className = "sidebar-group";
      group.id = "sidebar-group-" + item.group;
      group.dataset.sidebarGroup = item.group;
      group.textContent = item.group;
      button.insertAdjacentElement("beforebegin", group);
    }
    button.dataset.sidebarDecorated = "1";
    button.dataset.sidebarTab = item.tab;
    button.dataset.sidebarGroup = item.group || "";
    button.title = item.label;
    button.innerHTML = `<span class="sidebar-icon">${sidebarIconSvg(item.icon)}</span><span class="sidebar-label">${sanitize(item.label)}</span>${item.submenu ? '<span class="sidebar-caret">›</span>' : ""}`;
    if (item.submenu && !$(item.tabId + "-submenu")) {
      const submenu = document.createElement("div");
      submenu.className = "sidebar-submenu";
      submenu.id = item.tabId + "-submenu";
      submenu.dataset.parentTab = item.tab;
      submenu.dataset.sidebarGroup = item.group || "";
      submenu.innerHTML = item.submenu.map((sub) => `<button class="sidebar-subitem" type="button" data-sidebar-action="${sanitize(sub.action)}">${sanitize(sub.label)}</button>`).join("");
      button.insertAdjacentElement("afterend", submenu);
    }
  });
}

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", !!collapsed);
  const toggle = $("sidebar-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.setAttribute("aria-label", collapsed ? "展開側邊欄" : "收合側邊欄");
  }
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
  } catch (err) {}
  updateSidebarActiveState();
}

function restoreSidebarState() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "1";
  } catch (err) {}
  setSidebarCollapsed(collapsed);
}

function syncSidebarMenuVisibility() {
  decorateSidebarMenu();
  const visibleGroups = new Set();
  SIDEBAR_MENU_CONFIG.forEach((item) => {
    const button = $(item.tabId);
    const submenu = $(item.tabId + "-submenu");
    const visible = canShowSidebarItem(item);
    if (button) button.style.display = visible ? "" : "none";
    if (submenu) submenu.style.display = visible ? "" : "none";
    if (visible && item.group) visibleGroups.add(item.group);
  });
  document.querySelectorAll("[data-sidebar-group]").forEach((group) => {
    if (!group.classList.contains("sidebar-group")) return;
    group.style.display = visibleGroups.has(group.dataset.sidebarGroup || "") ? "" : "none";
  });
  updateSidebarIdentity();
  updateSidebarActiveState();
}

function updateSidebarIdentity() {
  const user = $("sidebar-current-user");
  const role = $("sidebar-current-role");
  const level = $("sidebar-current-level");
  const avatar = $("sidebar-user-avatar");
  if (user) user.textContent = currentUser || "未登入";
  if (role) role.textContent = currentRoleLabel || currentRole || "-";
  if (level) level.textContent = currentUser ? (level.dataset.memberLevel || "-") : "-";
  if (avatar) avatar.textContent = currentUser ? String(currentUser).slice(0, 1).toUpperCase() : "-";
}

function updateSidebarActiveState() {
  const collapsed = document.body.classList.contains("sidebar-collapsed");
  SIDEBAR_MENU_CONFIG.forEach((item) => {
    const submenu = $(item.tabId + "-submenu");
    const button = $(item.tabId);
    if (!submenu || !button) return;
    const isActive = button.classList.contains("active");
    submenu.classList.toggle("show", isActive && !collapsed);
    submenu.querySelectorAll("[data-sidebar-action]").forEach((sub) => {
      const action = sub.dataset.sidebarAction || "";
      let active = false;
      if (action.startsWith("server:")) active = currentModuleTab === "server" && currentServerTab === action.split(":")[1];
      if (action.startsWith("admin:")) active = currentModuleTab === "accounts" && typeof currentAdminTab !== "undefined" && currentAdminTab === action.split(":")[1];
      if (action === "module:" + currentModuleTab) active = true;
      if (action === "community:review") active = currentModuleTab === "community" && typeof communityMode !== "undefined" && communityMode === "review";
      sub.classList.toggle("active", active);
    });
  });
}

function runSidebarAction(action) {
  if (!action) return;
  const [scope, value] = action.split(":");
  if (scope === "module" && value && typeof switchModuleTab === "function") {
    switchModuleTab(value);
    return;
  }
  if (scope === "server" && value && typeof switchModuleTab === "function" && typeof switchServerTab === "function") {
    switchModuleTab("server");
    switchServerTab(value);
    return;
  }
  if (scope === "admin" && value && typeof switchModuleTab === "function" && typeof switchAdminTab === "function") {
    switchModuleTab("accounts");
    switchAdminTab(value);
    return;
  }
  if (action === "community:review" && typeof switchModuleTab === "function") {
    switchModuleTab("community");
    if (typeof switchCommunityMode === "function") switchCommunityMode("review");
  }
}

function stopInactivityTimer() {
  if (inactivityTimer) {
    clearTimeout(inactivityTimer);
    inactivityTimer = null;
  }
  if (inactivityCountdownTimer) {
    clearInterval(inactivityCountdownTimer);
    inactivityCountdownTimer = null;
  }
  inactivityDeadline = null;
  inactivityWarned = false;
  const label = $("session-countdown-label");
  if (label) {
    label.textContent = currentUser ? "閒置登出：--:--" : "未登入";
    label.style.color = "var(--muted)";
  }
}

function resetInactivityTimer() {
  if (!currentUser) return;
  stopInactivityTimer();
  inactivityDeadline = Date.now() + inactivityLogoutMs;
  updateInactivityCountdown();
  inactivityCountdownTimer = setInterval(updateInactivityCountdown, 1000);
  inactivityTimer = setTimeout(async () => {
    alert("已超過 3 分鐘未操作，系統將自動登出。");
    await doLogout();
  }, inactivityLogoutMs);
}

function updateInactivityCountdown() {
  const label = $("session-countdown-label");
  if (!label) return;
  if (!currentUser || !inactivityDeadline) {
    label.textContent = currentUser ? "閒置登出：--:--" : "未登入";
    label.style.color = "var(--muted)";
    return;
  }
  const remaining = Math.max(0, inactivityDeadline - Date.now());
  const seconds = Math.ceil(remaining / 1000);
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  label.textContent = `閒置登出：${mm}:${ss}`;
  if (seconds <= 30) {
    label.style.color = "#ff4f6d";
    if (!inactivityWarned) {
      inactivityWarned = true;
      const msg = $("li-msg") || $("settings-msg");
      if (msg) {
        msg.textContent = "即將因閒置自動登出，請移動滑鼠或按鍵延長登入狀態。";
        msg.style.color = "#ffb74d";
      }
    }
  } else if (seconds <= 60) {
    label.style.color = "#ffb74d";
  } else {
    label.style.color = "var(--muted)";
  }
}

function setupInactivityTracking() {
  ["click", "keydown", "mousemove", "touchstart", "scroll"].forEach((eventName) => {
    window.addEventListener(eventName, resetInactivityTimer, { passive: true });
  });
}

// ── Sanitization (XSS defense — defense in depth) ────────────
function sanitize(str) {
  if (typeof str !== 'string') return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;')
    .replace(/\//g, '&#x2F;');
}

function readCookie(name) {
  const cookie = document.cookie || "";
  const prefix = `${name}=`;
  const item = cookie.split('; ').find((v) => v.startsWith(prefix));
  return item ? decodeURIComponent(item.substring(prefix.length)) : "";
}

function applySiteConfig(config) {
  if (!config || typeof config !== "object") return;
  siteConfig = { ...siteConfig, ...config };
  const root = document.documentElement;
  const mappings = {
    site_bg: "--bg",
    site_surface: "--surface",
    site_accent: "--accent",
    site_accent2: "--accent2",
    site_text: "--text",
    site_muted: "--muted",
  };
  Object.entries(mappings).forEach(([key, cssVar]) => {
    const value = siteConfig[key];
    if (typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)) {
      root.style.setProperty(cssVar, value);
    }
  });
  const layoutMode = typeof siteConfig.site_layout_mode === "string" ? siteConfig.site_layout_mode : "centered";
  const density = typeof siteConfig.site_density === "string" ? siteConfig.site_density : "comfortable";
  document.body.dataset.layoutMode = layoutMode;
  document.body.dataset.density = density;
}

function renderServerVersion(meta) {
  if (!meta || typeof meta !== "object") return;
  serverMeta = { ...serverMeta, ...meta };
  const releaseId = typeof serverMeta.release_id === "string" && serverMeta.release_id
    ? serverMeta.release_id
    : (typeof serverMeta.version === "string" && serverMeta.version ? serverMeta.version : "unknown");
  const startedAt = typeof serverMeta.started_at === "string" && serverMeta.started_at ? formatChatTime(serverMeta.started_at) : "";
  const text = startedAt ? `發佈號: ${releaseId} · 啟動 ${startedAt}` : `發佈號: ${releaseId}`;
  document.querySelectorAll("[data-server-version-badge]").forEach((el) => {
    el.textContent = text;
  });
}

async function loadSiteConfig() {
  try {
    const res = await fetch(API + "/site-config", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (json && json.ok && json.site_config) {
      applySiteConfig(json.site_config);
    }
    if (json && json.ok && json.server_meta) {
      renderServerVersion(json.server_meta);
    }
  } catch (err) {
    console.error("site config load failed", err);
  }
}

function setServerConnectionState(state, label) {
  const dots = [$("sidebar-server-dot")].filter(Boolean);
  const labels = [$("sidebar-server-label")].filter(Boolean);
  if (!dots.length || !labels.length) return;
  const colors = {
    online: ["#4caf50", "rgba(76,175,80,.75)"],
    unstable: ["#ffb74d", "rgba(255,183,77,.75)"],
    offline: ["#ff4f6d", "rgba(255,79,109,.75)"],
  };
  const [color, glow] = colors[state] || colors.unstable;
  dots.forEach((dot) => {
    dot.style.background = color;
    dot.style.boxShadow = `0 0 10px ${glow}`;
  });
  labels.forEach((text) => {
    text.textContent = label;
  });
}

async function checkServerConnection() {
  const started = Date.now();
  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 3500);
  try {
    const res = await fetch(API + "/version", {
      credentials: "same-origin",
      cache: "no-store",
      signal: ctrl.signal
    });
    clearTimeout(timeout);
    const latency = Date.now() - started;
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error("bad status");
    serverConnectionFailures = 0;
    if (json.maintenance_mode) {
      setServerConnectionState("unstable", "維護模式");
    } else if (latency > 1800) {
      setServerConnectionState("unstable", `連線不穩 ${latency}ms`);
    } else {
      setServerConnectionState("online", "伺服器正常");
    }
  } catch (_) {
    clearTimeout(timeout);
    serverConnectionFailures += 1;
    if (serverConnectionFailures >= 2) {
      setServerConnectionState("offline", "伺服器離線");
    } else {
      setServerConnectionState("unstable", "連線不穩");
    }
  }
}

function startServerConnectionMonitor() {
  if (serverConnectionTimer) clearInterval(serverConnectionTimer);
  checkServerConnection();
  serverConnectionTimer = setInterval(checkServerConnection, 8000);
}

function getCsrfToken() { return _csrfToken; }

let _csrfTokenRequest = null;

async function fetchCsrfToken({ force = false } = {}) {
  const cookieToken = readCookie("csrf_token");
  if (!force && (_csrfToken || cookieToken)) {
    _csrfToken = _csrfToken || cookieToken || null;
    return _csrfToken;
  }
  if (_csrfTokenRequest) {
    await _csrfTokenRequest;
    return _csrfToken;
  }
  _csrfTokenRequest = (async () => {
    try {
      const res = await fetch(API + '/csrf-token', { credentials: 'same-origin' });
      const json = await res.json().catch(() => ({}));
      if (json && json.ok && typeof json.csrf_token === "string" && json.csrf_token) {
        _csrfToken = json.csrf_token;
        return;
      }
    } catch (_) {}
    const latestCookieToken = readCookie("csrf_token");
    _csrfToken = latestCookieToken || null;
  })();
  try {
    await _csrfTokenRequest;
  } finally {
    _csrfTokenRequest = null;
  }
  return _csrfToken;
}

function flash(el, text, ok) {
  if (!el) return;
  el.textContent = text;
  el.className = "msg show " + (ok ? "ok" : "err");
}

function clearMsg() {
  $("li-msg").className = "msg";
  $("reg-msg").className = "msg";
}

function setUserEditMsg(text, ok) {
  const el = $("user-edit-msg");
  if (!el) return;
  el.textContent = text;
  el.className = ok === true ? "msg show ok" : ok === false ? "msg show err" : "msg";
}

function setChatMsg(elId, text, ok) {
  const el = $(elId);
  if (!el) return;
  el.textContent = text;
  el.className = "msg show " + (ok ? "ok" : "err");
}

function stopChatPoll() {
  if (chatPollTimer) {
    clearInterval(chatPollTimer);
    chatPollTimer = null;
  }
}

function startChatPoll() {
  stopChatPoll();
  if (!selectedChatRoomId) return;
  chatPollTimer = setInterval(() => {
    loadChatMessages(selectedChatRoomId, true);
  }, CHAT_POLL_MS);
}

function formatChatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd} ${hh}:${mi}`;
}

function renderChatRooms() {
  const wrap = $("chat-room-list");
  if (!wrap) return;
  if (!chatRooms.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">尚未加入任何聊天室</p>";
    return;
  }
  const prevId = selectedChatRoomId;
  wrap.innerHTML = "";
  chatRooms.forEach((r) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-room-item" + (Number(prevId) === Number(r.id) ? " active" : "");
    const lock = r.is_private ? "🔒 " : "";
    btn.textContent = `${lock}#${r.id} ${r.name}`;
    btn.setAttribute("title", `聊天室持有者：${r.owner_username || "未知"}${r.is_private ? " · 私人訊息" : ""}`);
    btn.addEventListener("click", () => openChatRoom(r.id, true));
    wrap.appendChild(btn);
  });
}

function renderChatMessages(messages) {
  const list = $("chat-room-messages");
  if (!list) return;
  if (!messages.length) {
    list.innerHTML = "<p style=\"color:var(--muted);\">目前還沒有訊息</p>";
    return;
  }
  list.innerHTML = messages.map((m) => {
    const isSelf = String(m.sender || "") === String(currentUser || "");
    const cls = ["chat-msg"];
    const actions = [];
    if (isSelf) cls.push("self");
    if (!isSelf && m.id) actions.push(`<button class="chat-report-btn" type="button" data-report-message="${m.id}">檢舉</button>`);
    if (canDeleteChatMessage(m)) actions.push(`<button class="chat-delete-btn" type="button" data-delete-message="${m.id}">刪除</button>`);
    return `
      <div class="${cls.join(" ")}">
        <span class="meta">${sanitize(formatChatTime(m.created_at))} · ${sanitize(m.sender || "系統")}</span>
        ${sanitize(m.content || "")}
        ${actions.join("")}
      </div>
    `;
  }).join("");
  list.querySelectorAll("button[data-report-message]").forEach((btn) => {
    btn.addEventListener("click", () => reportChatMessage(parseInt(btn.getAttribute("data-report-message"), 10)));
  });
  list.querySelectorAll("button[data-delete-message]").forEach((btn) => {
    btn.addEventListener("click", () => deleteChatMessage(parseInt(btn.getAttribute("data-delete-message"), 10)));
  });
  list.scrollTop = list.scrollHeight;
}

function hideUserEditDialog() {
  if (forcedPasswordChangeMode) return;
  const overlay = $("user-edit-overlay");
  if (overlay) {
    overlay.classList.remove("show");
  }
  editingUserId = null;
}

function isBirthdayToday(birthdate) {
  if (typeof birthdate !== "string") return false;
  const normalized = birthdate.trim();
  if (!normalized) return false;

  const m = normalized.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return false;

  const month = Number(m[2]);
  const day = Number(m[3]);
  const today = new Date();
  return today.getMonth() + 1 === month && today.getDate() === day;
}

function setUserEditField(id, value) {
  const el = $(id);
  if (!el) return;
  el.value = value || "";
}

function setLoading(btnId, spinnerId, on) {
  const btn = $(btnId);
  const sp  = $(spinnerId);
  if (!btn || !sp) return;
  btn.classList.toggle("loading", on);
  sp.style.display = on ? "block" : "none";
}

function showTab(tab) {
  $("sec-login").classList.toggle("active",    tab === "login");
  $("sec-register").classList.toggle("active", tab === "register");
  $("tab-login").classList.toggle("active",    tab === "login");
  $("tab-register").classList.toggle("active",tab === "register");
  clearMsg();
}

function setupPwToggle(inputId, btnId) {
  const input = $(inputId);
  const btn   = $(btnId);
  if (!input || !btn) return;
  btn.addEventListener("mousedown", () => {
    input.type = "text";
    btn.textContent = "🙈";
  });
  btn.addEventListener("mouseup", () => {
    input.type = "password";
    btn.textContent = "👁";
  });
  btn.addEventListener("mouseleave", () => {
    input.type = "password";
    btn.textContent = "👁";
  });
  btn.addEventListener("touchstart", (e) => {
    e.preventDefault();
    input.type = "text";
    btn.textContent = "🙈";
  }, { passive: false });
  btn.addEventListener("touchend", (e) => {
    e.preventDefault();
    input.type = "password";
    btn.textContent = "👁";
  }, { passive: false });
}

function pad2(v) { return String(v).padStart(2, "0"); }
function startClock() {
  const clock = $("clock");
  if (!clock) return false;
  const tick = () => {
    try {
      const now = new Date();
      clock.textContent = `⏰ ${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())} ${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`;
    } catch (err) {
      if (clockTimer) {
        clearInterval(clockTimer);
        clockTimer = null;
      }
      clock.textContent = "⏰ 時間載入失敗";
      console.error("clock update failed", err);
    }
  };
  try {
    tick();
    if (clockTimer) clearInterval(clockTimer);
    clockTimer = setInterval(tick, 1000);
    return true;
  } catch (err) {
    clock.textContent = "⏰ 時間載入失敗";
    console.error("clock init failed", err);
    return false;
  }
}

setupPwToggle("li-pw", "li-pw-toggle");
setupPwToggle("reg-pw", "reg-pw-toggle");
setupPwToggle("reg-pw-confirm", "reg-pw-confirm-toggle");
setupPwToggle("admin-add-pw", "admin-add-pw-toggle");
setupPwToggle("admin-add-pw-confirm", "admin-add-pw-confirm-toggle");
setupPwToggle("edit-user-current-pw", "edit-user-current-pw-toggle");
setupPwToggle("edit-user-pw", "edit-user-pw-toggle");
setupPwToggle("edit-user-pw-confirm", "edit-user-pw-confirm-toggle");

$("reg-pw").addEventListener("input", function () {
  const v = this.value;
  const hints = [];
  if (v.length < 8)                      hints.push("至少 8 字");
  if (!/[A-Z]/.test(v))                 hints.push("需大寫");
  if (!/[a-z]/.test(v))                 hints.push("需小寫");
  if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(v)) hints.push("需符號");
  $("reg-pw-hint").textContent = hints.length ? "❌ " + hints.join(" · ") : "✓ 符合強度要求";
});
function updateRegPwMatchHint() {
  const pw = $("reg-pw").value;
  const confirmPw = $("reg-pw-confirm").value;
  const hintEl = $("reg-pw-confirm-hint");
  if (!hintEl) return;
  if (!confirmPw) {
    hintEl.textContent = "";
    return;
  }
  if (pw !== confirmPw) {
    hintEl.textContent = "❌ 兩次輸入的密碼不一致";
    return;
  }
  hintEl.textContent = "✓ 密碼一致";
}
$("reg-pw-confirm").addEventListener("input", updateRegPwMatchHint);

function updateAdminPwMatchHint() {
  const pw = $("admin-add-pw").value;
  const confirmPw = $("admin-add-pw-confirm").value;
  const hintEl = $("admin-add-pw-confirm-hint");
  if (!hintEl) return;
  if (!confirmPw) {
    hintEl.textContent = "";
    return;
  }
  if (pw !== confirmPw) {
    hintEl.textContent = "❌ 兩次輸入的密碼不一致";
    return;
  }
  hintEl.textContent = "✓ 密碼一致";
}
$("admin-add-pw-confirm").addEventListener("input", updateAdminPwMatchHint);

function setAuthState(json, showLoginHero = false) {
  currentUser = json.username || null;
  currentUserId = json.id || null;
  currentRole = json.role || "user";
  currentRoleLabel = json.role_label || currentRole || "user";
  currentMustChangePassword = !!json.must_change_password;
  const idleMinutes = Number(json.session_idle_timeout_minutes ?? 10);
  inactivityLogoutMs = idleMinutes > 0 ? Math.max(1, idleMinutes) * 60 * 1000 : 0;
  if (inactivityLogoutMs > 0) resetInactivityTimer();
  canManageUsers = currentRole === "super_admin";
  $("auth-card").style.display = "none";
  document.body.classList.add("app-authenticated");
  $("success-screen").classList.add("show");
  const loginHero = $("login-success-hero");
  if (loginHero) {
    loginHero.classList.toggle("show", !!showLoginHero);
    if (showLoginHero) {
      setTimeout(() => loginHero.classList.remove("show"), 2800);
    }
  }
  if ($("me-user")) $("me-user").textContent = sanitize(currentUser || "-");
  if ($("me-role")) $("me-role").textContent = sanitize(json.role_label || currentRole || "-");
  const levelEl = $("me-level");
  if (levelEl) levelEl.textContent = sanitize(json.effective_level || json.member_level || "-");
  if ($("me-nickname")) $("me-nickname").textContent = sanitize(json.nickname || "-");
  const sidebarLevel = $("sidebar-current-level");
  if (sidebarLevel) {
    sidebarLevel.dataset.memberLevel = json.effective_level || json.member_level || "-";
    sidebarLevel.textContent = sidebarLevel.dataset.memberLevel;
  }
  updateSidebarIdentity();
  const selfEditBtn = $("self-edit-btn");
  if (selfEditBtn) selfEditBtn.style.display = currentUser ? "" : "none";
  const welcomeMsg = $("welcome-msg");
  if (welcomeMsg) {
    welcomeMsg.classList.remove("birthday-greeting");
    if (isBirthdayToday(json.birthdate)) {
      const name = json.nickname || currentUser || "";
      const label = name ? `，${name}` : "";
      welcomeMsg.textContent = `🎉 生日快樂${label}！今天也是你的生日！`;
      void welcomeMsg.offsetWidth;
      welcomeMsg.classList.add("birthday-greeting");
    } else {
      welcomeMsg.textContent = "歡迎回來！";
    }
  }
  const adminWrap = $("admin-wrap");
  if (adminWrap) {
    if (currentRole === "manager" || currentRole === "super_admin") {
      adminWrap.classList.add("show");
    } else {
      adminWrap.classList.remove("show");
    }
  }
  const addPanel = $("admin-manager-view");
  if (addPanel) addPanel.style.display = canManageUsers ? "block" : "none";

  // Module access controls
  const tabModuleAccounts = $("tab-module-accounts");
  const tabModuleServer = $("tab-module-server");
  const tabModuleChat = $("tab-module-chat");
  const tabModuleDm = $("tab-module-dm");
  const tabModuleAnnouncements = $("tab-module-announcements");
  const tabModuleCommunity = $("tab-module-community");
  const tabModuleDrive = $("tab-module-drive");
  const tabModuleAlbums = $("tab-module-albums");
  const tabModuleComfyui = $("tab-module-comfyui");
  const tabModuleAppeals = $("tab-module-appeals");
  const appealsTab = $("tab-appeals");
  const reportsTab = $("tab-reports");
  const governanceTab = $("tab-governance");
  if (tabModuleAccounts) tabModuleAccounts.style.display = canAccessModule("accounts") ? "" : "none";
  if (tabModuleServer) tabModuleServer.style.display = currentRole === "super_admin" ? "" : "none";
  if (tabModuleChat) tabModuleChat.style.display = canAccessModule("chat") ? "" : "none";
  if (tabModuleDm) tabModuleDm.style.display = canAccessModule("dm") ? "" : "none";
  if (tabModuleAnnouncements) tabModuleAnnouncements.style.display = canAccessModule("community") ? "" : "none";
  if (tabModuleCommunity) tabModuleCommunity.style.display = canAccessModule("community") ? "" : "none";
  if (tabModuleDrive) tabModuleDrive.style.display = canAccessModule("privacy_uploads") ? "" : "none";
  if (tabModuleAlbums) tabModuleAlbums.style.display = canAccessModule("privacy_uploads") ? "" : "none";
  if (tabModuleComfyui) tabModuleComfyui.style.display = canAccessModule("comfyui") ? "" : "none";
  if (tabModuleAppeals) tabModuleAppeals.style.display = (currentRole !== "super_admin" && canAccessModule("appeals")) ? "" : "none";
  if (typeof syncSidebarMenuVisibility === "function") {
    syncSidebarMenuVisibility();
    restoreSidebarState();
  }
  if (appealsTab) appealsTab.style.display = currentRole === "super_admin" ? "" : "none";
  if (reportsTab) reportsTab.style.display = currentRole === "super_admin" ? "" : "none";
  if (governanceTab) governanceTab.style.display = (currentRole === "manager" || currentRole === "super_admin") ? "" : "none";
  const restartBtn = $("restart-server-btn");
  if (restartBtn) restartBtn.style.display = currentRole === "super_admin" ? "" : "none";

  if (currentMustChangePassword) {
    resetInactivityTimer();
    setTimeout(() => forceDefaultPasswordChange(), 0);
    return;
  }

  if (currentRole === "manager" || currentRole === "super_admin") {
    loadUsers();
    if (currentRole === "super_admin") {
      loadAdminAppeals();
    }
  }
  if (typeof startNotificationPoll === "function") startNotificationPoll();
  loadChatRooms();
  if (currentRole !== "super_admin") {
    loadUserAppeals();
  }
  const initialModule = canAccessModule("accounts")
    ? "accounts"
    : canAccessModule("chat")
      ? "chat"
      : canAccessModule("dm")
        ? "dm"
        : canAccessModule("community")
          ? "community"
          : canAccessModule("privacy_uploads")
            ? "drive"
            : canAccessModule("comfyui")
              ? "comfyui"
              : (currentRole !== "super_admin" && canAccessModule("appeals")) ? "appeals" : "chat";
  switchModuleTab(initialModule);
  if (typeof updateSidebarActiveState === "function") updateSidebarActiveState();
  if (typeof refreshComfyuiStatus === "function" && canAccessModule("comfyui")) {
    refreshComfyuiStatus({ switchAway: true });
  }
  resetInactivityTimer();
}

function resetAuthState() {
  currentUser = null;
  currentUserId = null;
  currentRole = "user";
  currentRoleLabel = "user";
  currentMustChangePassword = false;
  inactivityLogoutMs = DEFAULT_INACTIVITY_LOGOUT_MS;
  forcedPasswordChangeMode = false;
  canManageUsers = false;
  users = [];
  currentServerTab = "security";
  editingUserIsSelf = false;
  updateSidebarIdentity();
  stopInactivityTimer();
  stopChatPoll();
  if (typeof stopNotificationPoll === "function") stopNotificationPoll();
  hideUserEditDialog();
  document.body.classList.remove("app-authenticated");
  $("success-screen").classList.remove("show");
  const welcomeMsg = $("welcome-msg");
  if (welcomeMsg) {
    welcomeMsg.classList.remove("birthday-greeting");
    welcomeMsg.textContent = "歡迎回來！";
  }
  $("admin-wrap").className = "admin-wrap";
  const moduleChat = $("module-chat");
  const moduleDm = $("module-dm");
  const moduleAnnouncements = $("module-announcements");
  const moduleCommunity = $("module-community");
  const moduleDrive = $("module-drive");
  const moduleAlbums = $("module-albums");
  const moduleComfyui = $("module-comfyui");
  const moduleAccounts = $("module-accounts");
  const moduleServer = $("module-server");
  const moduleAppeals = $("module-appeals");
  if (moduleChat) moduleChat.classList.remove("active");
  if (moduleDm) moduleDm.classList.remove("active");
  if (moduleAnnouncements) moduleAnnouncements.classList.remove("active");
  if (moduleCommunity) moduleCommunity.classList.remove("active");
  if (moduleDrive) moduleDrive.classList.remove("active");
  if (moduleAlbums) moduleAlbums.classList.remove("active");
  if (moduleComfyui) moduleComfyui.classList.remove("active");
  if (moduleAccounts) moduleAccounts.classList.remove("active");
  if (moduleServer) moduleServer.classList.remove("active");
  if (moduleAppeals) moduleAppeals.classList.remove("active");
  if (typeof setComfyuiTabAvailability === "function") setComfyuiTabAvailability(null);
  if (typeof syncSidebarMenuVisibility === "function") syncSidebarMenuVisibility();
  $("me-user").textContent = "-";
  $("me-role").textContent = "-";
  $("me-nickname").textContent = "-";
  $("auth-card").style.display = "";
  selectedChatRoomId = null;
  chatRooms = [];
  selectedDmThreadId = null;
  dmThreads = [];
  const chatWarn = $("chat-room-warn");
  if (chatWarn) chatWarn.className = "msg";
  const chatRoomList = $("chat-room-list");
  if (chatRoomList) chatRoomList.innerHTML = "<p style=\"color:var(--muted);\">尚未登入</p>";
  const chatRoomTitle = $("chat-room-title");
  if (chatRoomTitle) chatRoomTitle.textContent = "請先建立或加入聊天室";
  const chatRoomMessages = $("chat-room-messages");
  if (chatRoomMessages) chatRoomMessages.innerHTML = "<p style=\"color:var(--muted);\">尚未登入</p>";
  userAppeals = [];
  adminAppeals = [];
  adminAppealPage = 1;
  adminAppealStatus = "pending";
  const tb = $("user-table")?.querySelector("tbody");
  if (tb) tb.innerHTML = "";
}
