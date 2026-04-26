'use strict';

const API = "/api";
let _csrfToken = null;
let currentUser = null;
let currentUserId = null;
let currentRole = "user";
let canManageUsers = false;
let currentModuleTab = "chat";
let currentServerTab = "health";
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
let chatRooms = [];
let selectedChatRoomId = null;
let chatPollTimer = null;
const CHAT_POLL_MS = 2500;
const INACTIVITY_LOGOUT_MS = 3 * 60 * 1000;
let inactivityTimer = null;
let clockTimer = null;

function $(id) { return document.getElementById(id); }

function stopInactivityTimer() {
  if (inactivityTimer) {
    clearTimeout(inactivityTimer);
    inactivityTimer = null;
  }
}

function resetInactivityTimer() {
  if (!currentUser) return;
  stopInactivityTimer();
  inactivityTimer = setTimeout(async () => {
    alert("已超過 3 分鐘未操作，系統將自動登出。");
    await doLogout();
  }, INACTIVITY_LOGOUT_MS);
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
    btn.textContent = `#${r.id} ${r.name}`;
    btn.setAttribute("title", `聊天室持有者：${r.owner_username || "未知"}`);
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
    if (isSelf) cls.push("self");
    return `
      <div class="${cls.join(" ")}">
        <span class="meta">${sanitize(formatChatTime(m.created_at))} · ${sanitize(m.sender || "系統")}</span>
        ${sanitize(m.content || "")}
        ${!isSelf && m.id ? `<button class="chat-report-btn" type="button" data-report-message="${m.id}">檢舉</button>` : ""}
      </div>
    `;
  }).join("");
  list.querySelectorAll("button[data-report-message]").forEach((btn) => {
    btn.addEventListener("click", () => reportChatMessage(parseInt(btn.getAttribute("data-report-message"), 10)));
  });
  list.scrollTop = list.scrollHeight;
}

function hideUserEditDialog() {
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
  canManageUsers = currentRole === "super_admin";
  $("auth-card").style.display = "none";
  $("success-screen").classList.add("show");
  const loginHero = $("login-success-hero");
  if (loginHero) {
    loginHero.classList.toggle("show", !!showLoginHero);
    if (showLoginHero) {
      setTimeout(() => loginHero.classList.remove("show"), 2800);
    }
  }
  $("me-user").textContent = sanitize(currentUser || "-");
  $("me-role").textContent = sanitize(json.role_label || currentRole || "-");
  $("me-nickname").textContent = sanitize(json.nickname || "-");
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
  const tabModuleAppeals = $("tab-module-appeals");
  const appealsTab = $("tab-appeals");
  const reportsTab = $("tab-reports");
  if (tabModuleAccounts) tabModuleAccounts.style.display = (currentRole === "manager" || currentRole === "super_admin") ? "" : "none";
  if (tabModuleServer) tabModuleServer.style.display = currentRole === "super_admin" ? "" : "none";
  if (tabModuleChat) tabModuleChat.style.display = "";
  if (tabModuleAppeals) tabModuleAppeals.style.display = currentRole === "super_admin" ? "none" : "";
  if (appealsTab) appealsTab.style.display = currentRole === "super_admin" ? "" : "none";
  if (reportsTab) reportsTab.style.display = currentRole === "super_admin" ? "" : "none";
  const restartBtn = $("restart-server-btn");
  if (restartBtn) restartBtn.style.display = currentRole === "super_admin" ? "" : "none";

  if (currentRole === "manager" || currentRole === "super_admin") {
    loadUsers();
    if (currentRole === "super_admin") {
      loadAdminAppeals();
    }
  }
  loadChatRooms();
  if (currentRole !== "super_admin") {
    loadUserAppeals();
  }
  switchModuleTab(currentRole === "user" ? "chat" : "accounts");
  resetInactivityTimer();
}

function resetAuthState() {
  currentUser = null;
  currentUserId = null;
  currentRole = "user";
  canManageUsers = false;
  users = [];
  currentServerTab = "health";
  editingUserIsSelf = false;
  stopInactivityTimer();
  stopChatPoll();
  hideUserEditDialog();
  $("success-screen").classList.remove("show");
  const welcomeMsg = $("welcome-msg");
  if (welcomeMsg) {
    welcomeMsg.classList.remove("birthday-greeting");
    welcomeMsg.textContent = "歡迎回來！";
  }
  $("admin-wrap").className = "admin-wrap";
  const moduleChat = $("module-chat");
  const moduleAccounts = $("module-accounts");
  const moduleServer = $("module-server");
  const moduleAppeals = $("module-appeals");
  if (moduleChat) moduleChat.classList.remove("active");
  if (moduleAccounts) moduleAccounts.classList.remove("active");
  if (moduleServer) moduleServer.classList.remove("active");
  if (moduleAppeals) moduleAppeals.classList.remove("active");
  $("me-user").textContent = "-";
  $("me-role").textContent = "-";
  $("me-nickname").textContent = "-";
  $("auth-card").style.display = "";
  selectedChatRoomId = null;
  chatRooms = [];
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
