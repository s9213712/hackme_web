
(function() {
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

async function fetchCsrfToken({ force = false } = {}) {
  try {
    const res = await fetch(API + '/csrf-token', { credentials: 'same-origin' });
    const json = await res.json();
    if (json.ok) {
      _csrfToken = json.csrf_token;
      return;
    }
    const cookieToken = readCookie("csrf_token");
    _csrfToken = cookieToken || null;
  } catch (_) { _csrfToken = null; }
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
  if (!clock) return;
  const tick = () => {
    const now = new Date();
    clock.textContent = `⏰ ${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())} ${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`;
  };
  tick();
  setInterval(tick, 1000);
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

function renderUsers() {
  const tbody = $("user-table")?.querySelector("tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const u of users) {
    const blocked = u.blocked_until && new Date(u.blocked_until) > new Date();
    const isBlocked = blocked;
    const isSelf = String(u.username || "") === String(currentUser || "");
    const actionButtons = [];
    if ((currentRole === "manager" || currentRole === "super_admin") && u.status === "pending" && !isSelf) {
      const approveBtn = document.createElement("button");
      approveBtn.className = "btn btn-primary";
      approveBtn.type = "button";
      approveBtn.textContent = "核准";
      approveBtn.addEventListener("click", () => reviewRegistration(u.id, "approve"));
      actionButtons.push(approveBtn);

      const rejectBtn = document.createElement("button");
      rejectBtn.className = "btn";
      rejectBtn.type = "button";
      rejectBtn.textContent = "駁回";
      rejectBtn.style.color = "#ff8a80";
      rejectBtn.addEventListener("click", () => reviewRegistration(u.id, "reject"));
      actionButtons.push(rejectBtn);
    }
    if (currentRole === "manager" || currentRole === "super_admin") {
      if (u.role !== "super_admin" && !isSelf) {
        const blockBtn = document.createElement("button");
        blockBtn.className = "btn btn-primary";
        blockBtn.type = "button";
        blockBtn.textContent = isBlocked ? "解除封鎖" : "封鎖";
        blockBtn.dataset.userId = String(u.id);
        blockBtn.addEventListener("click", () => toggleBlock(u.id, isBlocked));
        actionButtons.push(blockBtn);
      }
    }
    // Promote button (manager/super_admin can promote user→manager)
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role === "user" && !isSelf) {
      const promBtn = document.createElement("button");
      promBtn.className = "btn";
      promBtn.type = "button";
      promBtn.textContent = "⬆ 升級";
      promBtn.style.color = "#82b1ff";
      promBtn.addEventListener("click", () => promoteUser(u.id, u.username));
      actionButtons.push(promBtn);
    }
    // Demote button (super_admin only: manager→user, user→delete)
    if (currentRole === "super_admin" && u.role === "manager" && !isSelf) {
      const demBtn = document.createElement("button");
      demBtn.className = "btn";
      demBtn.type = "button";
      demBtn.textContent = "⬇ 降級";
      demBtn.style.color = "#ff8a80";
      demBtn.addEventListener("click", () => demoteUser(u.id, u.username, u.role));
      actionButtons.push(demBtn);
    }
    // Violation controls (manager/super_admin)
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role !== "super_admin" && !isSelf) {
      const violCount = u.violation_count || 0;
      const violBtn = document.createElement("button");
      violBtn.className = "btn";
      violBtn.type = "button";
      violBtn.textContent = `⚠ ${violCount}`;
      violBtn.style.color = violCount > 0 ? "#ff4f6d" : "#888";
      violBtn.addEventListener("click", () => addViolation(u.id));
      actionButtons.push(violBtn);
      if (currentRole === "super_admin") {
        const detailBtn = document.createElement("button");
        detailBtn.className = "btn";
        detailBtn.type = "button";
        detailBtn.textContent = "明細";
        detailBtn.title = "查看違規原因";
        detailBtn.style.color = "#82b1ff";
        detailBtn.addEventListener("click", () => {
          switchAdminTab("violations");
          loadViolations(0, u.username);
        });
        actionButtons.push(detailBtn);
      }
      if (violCount > 0) {
        const resetBtn = document.createElement("button");
        resetBtn.className = "btn";
        resetBtn.type = "button";
        resetBtn.textContent = "↺";
        resetBtn.title = "歸零違規";
        resetBtn.style.color = "#4caf50";
        resetBtn.addEventListener("click", () => resetViolations(u.id));
        actionButtons.push(resetBtn);
      }
    }
    if (canManageUsers || isSelf) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn btn-primary";
      editBtn.type = "button";
      editBtn.textContent = isSelf ? "我的資料" : "修改";
      editBtn.addEventListener("click", () => editUser(u.id));
      editBtn.classList.add("action-edit-user");
      actionButtons.push(editBtn);
      if (canManageUsers && !isSelf) {
        const delBtn = document.createElement("button");
        delBtn.className = "btn btn-danger";
        delBtn.type = "button";
        delBtn.textContent = "刪除";
        delBtn.addEventListener("click", () => removeUser(u.id));
        delBtn.classList.add("action-remove-user");
        actionButtons.push(delBtn);
      }
    }
    const tr = document.createElement("tr");
    if (isBlocked) tr.style.opacity = "0.5";
    const actions = document.createElement("div");
    actions.className = "action";
    actionButtons.forEach((btn) => actions.appendChild(btn));
    let statusLabel = `<span style="color:#4caf50;">正常</span>`;
    if (u.status === "pending") statusLabel = `<span style="color:#ffb74d;">待審核</span>`;
    else if (u.status === "rejected") statusLabel = `<span style="color:#ff4f6d;">已駁回</span>`;
    else if (u.status === "inactive") statusLabel = `<span style="color:#9e9e9e;">停用</span>`;
    if (isBlocked) statusLabel = `<span style="color:#ff4f6d;">封鎖中</span>`;
    const violDisplay = (u.violation_count || 0) > 0 ? `<span style="color:#ff4f6d;font-weight:bold;">${u.violation_count}</span>` : "0";
    tr.innerHTML = `
      <td>${u.id}</td>
      <td>${sanitize(u.username || "")}</td>
      <td>${sanitize(u.nickname || "")}</td>
      <td>${sanitize(u.real_name || "")}</td>
      <td>${sanitize(u.role_label || u.role || "")}</td>
      <td>${statusLabel}</td>
      <td>${violDisplay}</td>
    `;
    const actionCell = document.createElement("td");
    actionCell.appendChild(actions);
    tr.appendChild(actionCell);
    tbody.appendChild(tr);
  }
  // Role quota info
  const managerCount = users.filter(u => u.role === "manager").length;
  const infoEl = $("role-limit-info");
  if (infoEl) {
    infoEl.textContent = `管理者 ${managerCount}/5 · 超級管理者 1/1`;
    infoEl.style.color = managerCount >= 5 ? "#ff4f6d" : "#888";
  }
}

async function loadUsers() {
  if (!currentUser) return;
  if (!["manager","super_admin"].includes(currentRole)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await fetch(API + "/admin/users", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json();
    if (!json.ok) return;
    users = Array.isArray(json.users) ? json.users : [];
    canManageUsers = !!json.can_manage;
    renderUsers();
  } catch (_) {}
}

async function loadChatRooms() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await fetch(API + "/chat/rooms", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json();
    if (!json.ok) {
      return;
    }
    chatRooms = Array.isArray(json.rooms) ? json.rooms : [];
    renderChatRooms();
    if (selectedChatRoomId) {
      const exists = chatRooms.some((r) => r.id === selectedChatRoomId);
      if (!exists) {
        selectedChatRoomId = null;
      }
    }
    if (!selectedChatRoomId && chatRooms.length) {
      await openChatRoom(chatRooms[0].id, true);
    }
    if (!selectedChatRoomId) {
      const roomTitle = $("chat-room-title");
      if (roomTitle) roomTitle.textContent = "請先建立或加入聊天室";
      const memberLabel = $("chat-room-member");
      if (memberLabel) memberLabel.textContent = "";
      const msgs = $("chat-room-messages");
      if (msgs) msgs.innerHTML = "<p style=\"color:var(--muted);\">尚未選擇聊天室</p>";
    }
  } catch (_) {}
}

async function openChatRoom(roomId, autoPoll = true) {
  const id = Number(roomId);
  if (!Number.isFinite(id) || id <= 0) return;
  const target = chatRooms.find((r) => Number(r.id) === id);
  if (!target) return;
  selectedChatRoomId = id;
  renderChatRooms();
  const roomTitle = $("chat-room-title");
  if (roomTitle) roomTitle.textContent = `${target.name}（#${target.id}）`;
  const member = $("chat-room-member");
  if (member) member.textContent = `持有者：${target.owner_username || "未知"}`;
  await loadChatMessages(id, false);
  if (autoPoll) startChatPoll();
  const msgInput = $("chat-message-input");
  if (msgInput) msgInput.focus();
}

async function loadChatMessages(roomId, silent = false) {
  if (!roomId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await fetch(API + `/chat/rooms/${roomId}/messages`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json();
    if (!json.ok) {
      if (!silent) {
        setChatMsg("chat-room-warn", json.msg || "讀取訊息失敗", false);
      }
      return;
    }
    if (json.room && json.room.id === roomId) {
      const title = $("chat-room-title");
      if (title) title.textContent = `${json.room.name}（#${json.room.id}）`;
    }
    renderChatMessages(Array.isArray(json.messages) ? json.messages : []);
    const warn = $("chat-room-warn");
    if (warn) warn.className = "msg";
  } catch (e) {
    if (!silent) {
      setChatMsg("chat-room-warn", "讀取訊息失敗", false);
    }
  }
}

async function createChatRoom() {
  const name = ($("chat-room-name")?.value || "").trim();
  const targetUser = ($("chat-room-target-user")?.value || "").trim();

  if (!name) {
    setChatMsg("chat-room-warn", "請輸入聊天室名稱", false);
    return;
  }
  if (targetUser && targetUser === currentUser) {
    setChatMsg("chat-room-warn", "不能指定自己為對象", false);
    return;
  }

  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/chat/rooms", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ name, target_user: targetUser || null })
  });
  const raw = await res.text().catch(() => "");
  const json = (() => {
    try { return raw ? JSON.parse(raw) : {}; } catch (_) { return {}; }
  })();
  if (res.ok && json && json.ok) {
    $("chat-room-name").value = "";
    if ($("chat-room-target-user")) $("chat-room-target-user").value = "";
    await loadChatRooms();
    if (json.room && json.room.id) {
      await openChatRoom(json.room.id, true);
      const inviteInfo = json.room.target_username ? `（邀請 ${sanitize(json.room.target_username)}）` : "";
      setChatMsg("chat-room-warn", `聊天室建立完成${inviteInfo}`, true);
    }
  } else {
    const fallback = (raw || "").split("\n")[0].trim();
    setChatMsg("chat-room-warn", `${res.ok ? "建立聊天室失敗" : "建立聊天室失敗（" + res.status + "）"} ${json.msg || fallback || "請稍後再試"}`, false);
  }
}

async function joinChatRoom() {
  const roomId = Number(($("chat-join-room-id")?.value || "").trim());
  if (!Number.isFinite(roomId) || roomId <= 0) {
    setChatMsg("chat-room-warn", "請輸入有效的聊天室 ID", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/chat/rooms/" + roomId + "/join", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" }
  });
  const raw = await res.text().catch(() => "");
  const json = (() => {
    try { return raw ? JSON.parse(raw) : {}; } catch (_) { return {}; }
  })();
  if (res.ok && json && json.ok) {
    if ($("chat-join-room-id")) $("chat-join-room-id").value = "";
    const roomExists = chatRooms.find((r) => r.id === roomId);
    await loadChatRooms();
    if (roomExists) {
      await openChatRoom(roomId, true);
    } else if (json.room && json.room.id) {
      await openChatRoom(json.room.id, true);
    }
    setChatMsg("chat-room-warn", "已加入聊天室", true);
  } else {
    const fallback = (raw || "").split("\n")[0].trim();
    setChatMsg("chat-room-warn", `${res.ok ? "加入聊天室失敗" : "加入聊天室失敗（" + res.status + "）"} ${json.msg || fallback || "請稍後再試"}`, false);
  }
}

async function sendChatMessage() {
  if (!selectedChatRoomId) {
    setChatMsg("chat-room-warn", "請先選擇聊天室", false);
    return;
  }
  const input = $("chat-message-input");
  const content = (input?.value || "").trim();
  if (!content) {
    setChatMsg("chat-room-warn", "訊息不可為空", false);
    return;
  }
  if (content.length > 500) {
    setChatMsg("chat-room-warn", "訊息過長，請少於 500 字", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/rooms/${selectedChatRoomId}/messages`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf || ""
    },
    body: JSON.stringify({ content, csrf_token: csrf || "" })
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    if (input) input.value = "";
    setChatMsg("chat-room-warn", "訊息已送出", true);
    await loadChatMessages(selectedChatRoomId, true);
    startChatPoll();
    return;
  }

  const reason = json.reason ? ` [${json.reason}]` : "";
  const suffix = json.violation_count ? `（違規計次：${json.violation_count}）` : "";
  const message = `${json.msg || "發送失敗"}${reason}${suffix}`;
  setChatMsg("chat-room-warn", message, false);
  if (json.warned || json.reason || json.violation_count) {
    alert(message);
  }
}

async function reportChatMessage(messageId) {
  if (!messageId) return;
  const reason = prompt("請輸入檢舉原因（200 字內）：", "違規留言");
  if (reason === null) return;
  const cleanReason = reason.trim();
  if (!cleanReason) {
    setChatMsg("chat-room-warn", "請填寫檢舉原因", false);
    return;
  }
  if (cleanReason.length > 200) {
    setChatMsg("chat-room-warn", "檢舉原因請控制在 200 字以內", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/messages/${messageId}/report`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ reason: cleanReason })
  });
  const json = await res.json().catch(() => ({}));
  setChatMsg("chat-room-warn", json.msg || (json.ok ? "檢舉已送出" : "檢舉失敗"), !!json.ok);
}

function appealCountdownText(totalSeconds) {
  const h = Math.max(0, Math.floor(totalSeconds / 3600));
  const m = Math.max(0, Math.floor((totalSeconds % 3600) / 60));
  const s = Math.max(0, totalSeconds % 60);
  return `${h} 小時 ${m} 分 ${s} 秒`;
}

async function loadUserAppeals() {
  const wrap = $("user-appeal-wrap");
  if (!wrap || !currentUser) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/appeals", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    const summaryEl = $("appeal-summary");
    if (summaryEl) summaryEl.textContent = json.msg || "申覆資料讀取失敗";
    return;
  }

  userAppeals = Array.isArray(json.appeals) ? json.appeals : [];
  const violations = Array.isArray(json.violations) ? json.violations : [];
  const activeViolations = violations.filter(v => !v.is_resolved);
  const resolvedViolations = violations.filter(v => v.is_resolved);
  const summaryEl = $("appeal-summary");
  if (summaryEl) {
    const appealableCount = activeViolations.filter(v => v.can_appeal).length;
    const currentPoints = parseInt(json.violation_count || 0, 10);
    if (!activeViolations.length) {
      summaryEl.textContent = "目前無可申覆違規記錄";
    } else if (appealableCount > 0) {
      summaryEl.textContent = `目前違規點數 ${currentPoints}，共有 ${activeViolations.length} 筆有效違規，其中 ${appealableCount} 筆仍可逐條申覆`;
    } else {
      summaryEl.textContent = `目前違規點數 ${currentPoints}，共有 ${activeViolations.length} 筆有效違規，目前沒有可提交的新申覆`;
    }
  }

  const listEl = $("appeal-entries");
  if (!listEl) return;
  if (!violations.length) {
    listEl.innerHTML = "<p style='color:var(--muted);'>尚無違規記錄</p>";
    return;
  }
  const statusText = {
    pending: "待審",
    approved: "已核准",
    rejected: "駁回"
  };
  function renderAppealViolation(v) {
    const appeal = v.appeal || null;
    const status = appeal ? appeal.status : "";
    const color = status === "approved" ? "#4caf50" : status === "rejected" ? "#ff4f6d" : "#ffb74d";
    const remaining = parseInt(v.remaining_seconds || 0, 10);
    const canAppeal = !!v.can_appeal;
    const appealStatus = appeal
      ? `<div style="color:${color};">申覆狀態：${statusText[status] || status}${appeal.review_note ? ` · 備註：${sanitize(appeal.review_note || "")}` : ""}</div>`
      : canAppeal
        ? `<div style="color:#82b1ff;">剩餘申覆時間：${appealCountdownText(remaining)}</div>`
        : `<div style="color:var(--muted);">不可申覆或已超過 24 小時</div>`;
    const controls = canAppeal
      ? `<textarea data-appeal-reason="${v.id}" rows="2" maxlength="200" placeholder="針對違規 #${v.id} 填寫申覆原因" style="margin-top:.45rem;"></textarea>
         <button class="btn btn-primary" type="button" data-appeal-submit="${v.id}" style="margin-top:.35rem;width:auto;padding:.45rem .75rem;">提交這筆申覆</button>`
      : "";
    return `
      <div style="border-bottom:1px solid #222;padding:.55rem .25rem;word-break:break-all;">
        <div><strong>違規 #${v.id}</strong> · ${sanitize(v.created_at || "")} · 懲罰 ${v.points || 0} 點</div>
        <div style="color:#ff8a80;">違規原因：${sanitize(v.reason || "")}</div>
        ${appealStatus}
        ${controls}
      </div>
    `;
  }
  const activeHtml = activeViolations.length
    ? `<div style="color:var(--muted);font-size:.75rem;margin:.25rem 0;">目前有效違規</div>${activeViolations.map(renderAppealViolation).join("")}`
    : "<p style='color:var(--muted);'>目前無有效違規</p>";
  const historyHtml = resolvedViolations.length
    ? `<div style="color:var(--muted);font-size:.75rem;margin:.75rem 0 .25rem;">已撤銷歷史</div>${resolvedViolations.map(renderAppealViolation).join("")}`
    : "";
  listEl.innerHTML = activeHtml + historyHtml;
  listEl.querySelectorAll("button[data-appeal-submit]").forEach((btn) => {
    btn.addEventListener("click", () => submitAppeal(parseInt(btn.getAttribute("data-appeal-submit"), 10)));
  });
}

async function submitAppeal(violationId) {
  const reasonEl = document.querySelector(`textarea[data-appeal-reason="${violationId}"]`);
  const reason = (reasonEl?.value || "").trim();
  if (!reason) {
    flash($("appeal-msg"), "請填寫申覆原因", false);
    return;
  }
  if (reason.length > 200) {
    flash($("appeal-msg"), "申覆原因請控制在 200 字以內", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/appeals", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ violation_id: violationId, reason })
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    if (reasonEl) reasonEl.value = "";
    flash($("appeal-msg"), json.msg || "申覆已提交", true);
    await loadUserAppeals();
  } else {
    flash($("appeal-msg"), json.msg || "提交失敗", false);
  }
}

async function loadAdminAppeals(page = 0, status = null) {
  if (!currentUser || currentRole !== "super_admin") return;
  const targetStatus = status || adminAppealStatus;
  adminAppealStatus = targetStatus;
  const targetPage = Math.max(1, parseInt(page || 1, 10));
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/appeals?status=" + encodeURIComponent(targetStatus) + "&page=" + targetPage + "&limit=20", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;

  adminAppealPage = targetPage;
  adminAppeals = Array.isArray(json.items) ? json.items : [];
  if ($("admin-appeals-total")) $("admin-appeals-total").textContent = json.total || 0;

  const list = $("admin-appeal-list");
  if (!list) return;
  if (!adminAppeals.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有符合條件的申覆</p>";
  } else {
    list.innerHTML = adminAppeals.map(a => {
      const statusColor = a.status === "pending" ? "#ffb74d" : a.status === "approved" ? "#4caf50" : "#ff4f6d";
      const action = a.status === "pending"
        ? `<div style=\"margin-top:.4rem;display:flex;gap:.4rem;\">
            <button class=\"btn\" data-appeal-action=\"approve\" data-appeal-id=\"${a.id}\" style=\"background:#1f9d57;color:#fff;border:1px solid #1f9d57;\">核准撤銷</button>
            <button class=\"btn\" data-appeal-action=\"reject\" data-appeal-id=\"${a.id}\" style=\"background:#ff5252;color:#fff;border:1px solid #ff5252;\">維持處分</button>
          </div>`
        : "";
      return `
        <div style="border-bottom:1px solid #222;padding:.45rem .25rem;word-break:break-all;">
          <div><strong>${sanitize(a.username || "")}</strong> · 違規 #${a.latest_violation_id || "-"}</div>
          <div style=\"color:${statusColor};font-size:.75rem;\">${a.status}</div>
          <div style=\"color:#aaa;font-size:.7rem;\">時間：${sanitize(a.created_at || "")} · 懲罰：${a.penalty_points || 0} 點</div>
          <div>原因：${sanitize(a.reason || "")}</div>
          ${a.review_note ? `<div style=\"color:#bbb;\">備註：${sanitize(a.review_note || "")}</div>` : ""}
          <div>${action}</div>
        </div>
      `;
    }).join("");
    list.querySelectorAll("button[data-appeal-id]").forEach((btn) => {
      const appealId = btn.getAttribute("data-appeal-id");
      const action = btn.getAttribute("data-appeal-action");
      btn.addEventListener("click", () => reviewAppeal(appealId, action));
    });
  }

  if ($("admin-appeals-prev")) $("admin-appeals-prev").disabled = targetPage <= 1;
  if ($("admin-appeals-next")) $("admin-appeals-next").disabled = (targetPage * 20) >= (json.total || 0);
}

async function reviewAppeal(appealId, action) {
  if (!currentUser || currentRole !== "super_admin") return;
  const note = prompt("審核備註（非必填）", "");
  if (note === null) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/appeals/" + parseInt(appealId, 10) + "/review", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ action, note: (note || "").trim() })
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    await Promise.all([loadAdminAppeals(adminAppealPage, adminAppealStatus), loadUsers()]);
  } else {
    alert(json.msg || "審核失敗");
  }
}

async function loadAdminReports(page = 0, status = null) {
  if (!currentUser || currentRole !== "super_admin") return;
  const targetStatus = status || adminReportStatus;
  adminReportStatus = targetStatus;
  const targetPage = Math.max(0, parseInt(page || 0, 10));
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/message-reports?status=" + encodeURIComponent(targetStatus) + "&page=" + targetPage + "&limit=30", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;

  adminReportPage = targetPage;
  adminReports = Array.isArray(json.items) ? json.items : [];
  if ($("admin-reports-total")) $("admin-reports-total").textContent = json.total || 0;
  const list = $("admin-report-list");
  if (!list) return;
  if (!adminReports.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有符合條件的訊息檢舉</p>";
  } else {
    list.innerHTML = adminReports.map(r => {
      const action = r.status === "pending"
        ? `<div style="margin-top:.4rem;display:flex;gap:.4rem;">
            <button class="btn" data-report-action="approve" data-report-id="${r.id}" style="background:#1f9d57;color:#fff;border:1px solid #1f9d57;">核准計點</button>
            <button class="btn" data-report-action="reject" data-report-id="${r.id}" style="background:#ff5252;color:#fff;border:1px solid #ff5252;">駁回</button>
          </div>`
        : "";
      return `
        <div style="border-bottom:1px solid #222;padding:.45rem .25rem;word-break:break-all;">
          <div><strong>檢舉 #${r.id}</strong> · 訊息 #${r.message_id} · room #${r.room_id}</div>
          <div style="color:#aaa;font-size:.7rem;">${sanitize(r.created_at || "")} · 檢舉者：${sanitize(r.reporter_username || "")} · 被檢舉：${sanitize(r.reported_username || "")}</div>
          <div style="color:#ff8a80;">訊息：${sanitize(r.content || "")}</div>
          <div>檢舉原因：${sanitize(r.reason || "")}</div>
          ${r.review_note ? `<div style="color:#bbb;">備註：${sanitize(r.review_note || "")}</div>` : ""}
          ${action}
        </div>
      `;
    }).join("");
    list.querySelectorAll("button[data-report-id]").forEach((btn) => {
      btn.addEventListener("click", () => reviewMessageReport(
        parseInt(btn.getAttribute("data-report-id"), 10),
        btn.getAttribute("data-report-action")
      ));
    });
  }
  if ($("admin-reports-prev")) $("admin-reports-prev").disabled = targetPage <= 0;
  if ($("admin-reports-next")) $("admin-reports-next").disabled = ((targetPage + 1) * 30) >= (json.total || 0);
}

async function reviewMessageReport(reportId, action) {
  if (!currentUser || currentRole !== "super_admin") return;
  const note = prompt("審核備註（非必填）", "");
  if (note === null) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/message-reports/" + reportId + "/review", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ action, note: (note || "").trim() })
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    await Promise.all([loadAdminReports(adminReportPage, adminReportStatus), loadUsers()]);
  } else {
    alert(json.msg || "審核失敗");
  }
}

async function doLogin() {
  const user = sanitize($("li-user").value.trim());
  const pw   = $("li-pw").value;
  if (!user || !pw) { flash($("li-msg"), "請填寫帳號與密碼", false); return; }

  await fetchCsrfToken({ force: false });
  const csrf = getCsrfToken();
  if (!csrf) {
    flash($("li-msg"), "無法取得 CSRF token，請重新整理頁面", false);
    return;
  }
  setLoading("li-btn", "li-spinner", true);
  clearMsg();

  try {
    const res = await fetch(API + "/login", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf || ""
      },
      body: JSON.stringify({ username: user, password: pw, csrf_token: csrf })
    });
    const json = await res.json();
    if (!json.ok) {
      _csrfToken = null;
      flash($("li-msg"), json.msg || "登入失敗", false);
      return;
    }
    _csrfToken = null;
    const meRes = await fetch(API + "/me", { credentials: "same-origin" });
    const me = await meRes.json();
    if (me.ok) setAuthState(me, true);
    else setAuthState({ username: user, role: "user", role_label: "一般用戶", nickname: "-" }, true);
  } catch (e) {
    flash($("li-msg"), "網路錯誤，請稍後再試", false);
  } finally {
    setLoading("li-btn", "li-spinner", false);
  }
}

async function doRegister() {
  const user = $("reg-user").value.trim();
  const pw   = $("reg-pw").value;
  const pwConfirm = $("reg-pw-confirm").value;
  const nickname = $("reg-nickname").value.trim();
  const realName = $("reg-realname").value.trim();
  const idNo = $("reg-idno").value.trim();
  const birth = $("reg-birthdate").value;
  const phone = $("reg-phone").value.trim();

  if (!user) { flash($("reg-msg"), "請填寫帳號", false); return; }
  if (user.length < 3) { flash($("reg-msg"), "帳號至少 3 字元", false); return; }
  if (!pw) { flash($("reg-msg"), "請輸入密碼", false); return; }
  if (!pwConfirm) { flash($("reg-msg"), "請再次輸入密碼", false); return; }
  if (pw !== pwConfirm) { flash($("reg-msg"), "兩次密碼輸入不一致", false); return; }
  if (!nickname) { flash($("reg-msg"), "暱稱不可為空", false); return; }
  if (!realName) { flash($("reg-msg"), "真實姓名不可為空", false); return; }
  if (!idNo) { flash($("reg-msg"), "身分證不可為空", false); return; }
  if (!birth) { flash($("reg-msg"), "請填寫生日", false); return; }
  if (!phone) { flash($("reg-msg"), "請填寫電話", false); return; }

  if (!/^[a-zA-Z0-9_\-]+$/.test(user)) {
    flash($("reg-msg"), "帳號只能包含英文、數字、底線、減號", false);
    return;
  }

  await fetchCsrfToken({ force: false });
  const csrf = getCsrfToken();
  if (!csrf) {
    flash($("reg-msg"), "無法取得 CSRF token，請重新整理頁面", false);
    setLoading("reg-btn", "reg-spinner", false);
    return;
  }
  setLoading("reg-btn", "reg-spinner", true);
  clearMsg();

  try {
    const res = await fetch(API + "/register", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify({
        username: user,
        password: pw,
        password_confirm: pwConfirm,
        nickname,
        real_name: realName,
        id_number: idNo,
        birthdate: birth,
        phone,
        csrf_token: csrf
      })
    });
    const json = await res.json();
    if (json.ok) {
      _csrfToken = null;
      flash($("reg-msg"), "✓ " + sanitize(json.msg), true);
      setTimeout(() => {
        $("reg-pw").value = "";
        $("reg-pw-confirm").value = "";
        $("reg-pw-hint").textContent = "";
        $("reg-pw-confirm-hint").textContent = "";
      }, 1500);
      setTimeout(() => showTab("login"), 2000);
    } else {
      _csrfToken = null;
      flash($("reg-msg"), json.msg || "註冊失敗", false);
    }
  } catch (e) {
    flash($("reg-msg"), "網路錯誤，請稍後再試", false);
  } finally {
    setLoading("reg-btn", "reg-spinner", false);
  }
}

async function doLogout() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await fetch(API + "/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    if (!res.ok) {
      flash($("li-msg"), "登出失敗，請稍後再試", false);
    }
  } catch (_) {}
  _csrfToken = null;
  resetAuthState();
}

async function toggleBlock(userId, isBlocked) {
  if (!currentUser) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const body = isBlocked ? { action: "unblock" } : { action: "block", minutes: 30 };
  const res = await fetch(API + `/admin/users/${userId}/block`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(body)
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    loadUsers();
  } else {
    flash($("li-msg"), json.msg || "操作失敗", false);
  }
}

async function editUser(userId) {
  const target = users.find((u) => String(u.id) === String(userId));
  if (!target && String(currentUserId || "") !== String(userId)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();

  let source = target || {};
  if (csrf) {
    const detailRes = await fetch(API + `/admin/users/${userId}`, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    }).then((r) => r.json().catch(() => ({})));
    if (detailRes && detailRes.ok && detailRes.user) {
      source = detailRes.user;
    }
  }

  editingUserIsSelf = String(currentUserId || "") === String(userId);
  const current = {
    username: source.username || currentUser || "",
    nickname: source.nickname || "",
    real_name: source.real_name || "",
    id_number: source.id_number || "",
    birthdate: source.birthdate || "",
    phone: source.phone || "",
    role: source.role || "user",
    status: source.status || "active"
  };

  editingUserId = userId;
  editingUserOriginal.nickname = current.nickname;
  editingUserOriginal.real_name = current.real_name;
  editingUserOriginal.id_number = current.id_number;
  editingUserOriginal.birthdate = current.birthdate;
  editingUserOriginal.phone = current.phone;
  editingUserOriginal.role = current.role;
  editingUserOriginal.status = current.status;

  const usernameEl = $("user-edit-username");
  if (usernameEl) usernameEl.textContent = current.username || String(userId);
  setUserEditField("edit-user-nickname", current.nickname);
  setUserEditField("edit-user-realname", current.real_name);
  setUserEditField("edit-user-idno", current.id_number);
  setUserEditField("edit-user-birthdate", current.birthdate);
  setUserEditField("edit-user-phone", current.phone);
  const editRole = $("edit-user-role");
  if (editRole) editRole.value = current.role;
  const editStatus = $("edit-user-status");
  if (editStatus) editStatus.value = current.status;
  const roleField = $("edit-user-role-field");
  const statusField = $("edit-user-status-field");
  if (roleField) roleField.style.display = editingUserIsSelf || !canManageUsers ? "none" : "";
  if (statusField) statusField.style.display = editingUserIsSelf || !canManageUsers ? "none" : "";
  setUserEditField("edit-user-pw", "");
  setUserEditField("edit-user-pw-confirm", "");
  setUserEditMsg("");

  const overlay = $("user-edit-overlay");
  if (overlay) overlay.classList.add("show");
  const firstField = $("edit-user-nickname");
  if (firstField) firstField.focus();
}

async function submitEditUser() {
  if (!editingUserId) return;

  const payload = {};
  const nickname = $("edit-user-nickname")?.value.trim() || "";
  const realName = $("edit-user-realname")?.value.trim() || "";
  const idNo = $("edit-user-idno")?.value.trim() || "";
  const birthdate = $("edit-user-birthdate")?.value || "";
  const phone = $("edit-user-phone")?.value.trim() || "";
  const role = $("edit-user-role")?.value || "";
  const status = $("edit-user-status")?.value || "";
  const password = $("edit-user-pw")?.value || "";
  const passwordConfirm = $("edit-user-pw-confirm")?.value || "";

  if (nickname !== editingUserOriginal.nickname) payload.nickname = nickname;
  if (realName !== editingUserOriginal.real_name) payload.real_name = realName;
  if (idNo !== editingUserOriginal.id_number) payload.id_number = idNo;
  if (birthdate !== editingUserOriginal.birthdate) payload.birthdate = birthdate;
  if (phone !== editingUserOriginal.phone) payload.phone = phone;
  if (!editingUserIsSelf && canManageUsers && role !== editingUserOriginal.role) payload.role = role;
  if (!editingUserIsSelf && canManageUsers && status !== editingUserOriginal.status) payload.status = status;

  if (password || passwordConfirm) {
    if (password !== passwordConfirm) {
      setUserEditMsg("兩次密碼輸入不一致", false);
      return;
    }
    if (!password) {
      setUserEditMsg("若要修改密碼，兩次都要輸入", false);
      return;
    }
    payload.password = password;
    payload.password_confirm = passwordConfirm;
  }

  if (!Object.keys(payload).length) {
    setUserEditMsg("未變更任何欄位", false);
    return;
  }

  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/admin/users/${editingUserId}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    hideUserEditDialog();
    if (["manager", "super_admin"].includes(currentRole)) loadUsers();
    return;
  }
  setUserEditMsg(json.msg || "修改失敗", false);
}

async function removeUser(userId) {
  if (!window.confirm("確定要刪除帳號？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/admin/users/${userId}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    loadUsers();
  } else {
    flash($("li-msg"), json.msg || "刪除失敗", false);
  }
}

async function createUserByAdmin() {
  const payload = {
    username: sanitize($("admin-add-user").value.trim()),
    password: $("admin-add-pw").value,
    password_confirm: $("admin-add-pw-confirm").value,
    nickname: $("admin-add-nickname").value.trim(),
    real_name: $("admin-add-realname").value.trim(),
    id_number: $("admin-add-idno").value.trim(),
    birthdate: $("admin-add-birthdate").value,
    phone: $("admin-add-phone").value.trim(),
    role: "user",
    status: "active"
  };
  if (!payload.username || !payload.password || !payload.password_confirm || !payload.nickname || !payload.real_name || !payload.id_number || !payload.birthdate || !payload.phone) {
    flash($("li-msg"), "請完整填寫新增欄位", false);
    return;
  }
  if (payload.password !== payload.password_confirm) {
    flash($("li-msg"), "兩次輸入的密碼不一致", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/users", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    ["admin-add-user", "admin-add-pw", "admin-add-pw-confirm", "admin-add-nickname", "admin-add-realname", "admin-add-idno", "admin-add-birthdate", "admin-add-phone"]
      .forEach((id) => { const el = $(id); if (el) el.value = ""; });
    const adminAddHint = $("admin-add-pw-confirm-hint");
    if (adminAddHint) adminAddHint.textContent = "";
    loadUsers();
  } else {
    flash($("li-msg"), json.msg || "建立帳號失敗", false);
  }
}

async function reviewRegistration(userId, action) {
  const label = action === "approve" ? "核准" : "駁回";
  if (!confirm(`確定要${label}這筆註冊申請？`)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/admin/users/${userId}/review-registration`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ action })
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    loadUsers();
  } else {
    alert(json.msg || "審核失敗");
  }
}

async function promoteUser(userId, username) {
  if (!confirm(`確定要將「${username}」升級為管理者？`)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/users/" + userId + "/promote", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    loadUsers();
  } else {
    alert(json.msg || "升級失敗");
  }
}

async function demoteUser(userId, username, currentRole) {
  const msg = currentRole === "manager"
    ? `確定要將「${username}」降級為一般用戶？`
    : `確定要刪除「${username}」（一般用戶，達違規上限）？`;
  if (!confirm(msg)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/users/" + userId + "/demote", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    loadUsers();
  } else {
    alert(json.msg || "降級失敗");
  }
}

// ── Module / admin tab switching ─────────────────────────────────────
let currentAdminTab = "users";
function switchServerTab(tab) {
  currentServerTab = tab;
  ["health", "settings", "env"].forEach((name) => {
    const sec = $("sec-server-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-server-health", "tab-server-settings", "tab-server-env"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-server-" + tab);
  });
  if (tab === "health") loadServerHealth();
  if (tab === "settings") loadSettings();
  if (tab === "env") loadServerEnv();
}

function switchModuleTab(tab) {
  const canAccessAccounts = currentRole === "manager" || currentRole === "super_admin";
  const canAccessServer = currentRole === "super_admin";
  const canAccessAppeals = currentRole !== "super_admin";

  let normTab = tab;
  if (tab === "accounts" && !canAccessAccounts) normTab = canAccessAppeals ? "appeals" : "chat";
  if (tab === "server" && !canAccessServer) normTab = canAccessAppeals ? "appeals" : "chat";
  if (tab === "appeals" && !canAccessAppeals) normTab = "chat";

  currentModuleTab = normTab;
  const modChat = $("module-chat");
  const modAccounts = $("module-accounts");
  const modServer = $("module-server");
  const modAppeals = $("module-appeals");
  const mChat = $("tab-module-chat");
  const mAccounts = $("tab-module-accounts");
  const mServer = $("tab-module-server");
  const mAppeals = $("tab-module-appeals");

  if (modChat) modChat.classList.toggle("active", normTab === "chat");
  if (modAccounts) modAccounts.classList.toggle("active", normTab === "accounts");
  if (modServer) modServer.classList.toggle("active", normTab === "server");
  if (modAppeals) modAppeals.classList.toggle("active", normTab === "appeals");
  if (mChat) mChat.classList.toggle("active", normTab === "chat");
  if (mAccounts) mAccounts.classList.toggle("active", normTab === "accounts");
  if (mServer) mServer.classList.toggle("active", normTab === "server");
  if (mAppeals) mAppeals.classList.toggle("active", normTab === "appeals");

  if (normTab === "server" && canAccessServer) {
    switchServerTab(currentServerTab || "health");
  }
  if (normTab === "appeals" && canAccessAppeals) {
    loadUserAppeals();
  }
  if (normTab === "accounts" && canAccessAccounts && currentAdminTab) {
    if (!$("sec-" + currentAdminTab)) switchAdminTab("users");
  }
}

function switchAdminTab(tab) {
  currentAdminTab = tab;
  ["users","audit","violations","appeals","reports"].forEach(t => {
    const sec = $("sec-" + t);
    if (sec) sec.classList.toggle("active", t === tab);
  });
  ["tab-users","tab-audit","tab-violations","tab-appeals","tab-reports"].forEach(id => {
    const btn = $(id);
    if (btn) btn.classList.toggle("active", id === "tab-" + tab);
  });
  if (tab === "audit") loadAudit(0);
  if (tab === "violations") loadViolations(0);
  if (tab === "appeals") loadAdminAppeals(1, adminAppealStatus);
  if (tab === "reports") loadAdminReports(0, adminReportStatus);
}

// ── Audit log ───────────────────────────────────────────────
let auditPage = 0;
const AUDIT_PAGE_SIZE = 20;

async function loadAudit(page) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/audit?page=" + page, {
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
    const chainOk = integrity && integrity.ok;
    integEl.textContent = chainOk ? "🔗 鏈完整" : "⚠️ 鏈已斷！";
    integEl.style.color = chainOk ? "#4caf50" : "#ff4f6d";
  }
  if (currentRole === "super_admin" && integrity && integrity.ok === false && integrity.broken_at) {
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
  const res = await fetch(API + "/admin/users/" + userId + "/violation", {
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
  const res = await fetch(API + "/admin/users/" + userId + "/reset-violations", {
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

// ── Settings & restart ───────────────────────────────────────
async function loadSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/settings", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  const s = json.settings || {};
  if ($("s-maintenance-mode")) $("s-maintenance-mode").checked = !!s.maintenance_mode;
  if ($("s-allow-register")) $("s-allow-register").checked = !!s.allow_register;
  if ($("s-require-email")) $("s-require-email").checked = !!s.require_email_verification;
  if ($("s-max-fail")) $("s-max-fail").value = s.max_login_failures || 5;
  if ($("s-block-dur")) $("s-block-dur").value = s.block_duration_minutes || 30;
  if ($("s-session-ttl")) $("s-session-ttl").value = s.session_ttl_hours || 24;
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

async function loadServerHealth() {
  if (!currentUser || currentRole !== "super_admin") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/health", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const summary = $("server-health-summary");
  const details = $("server-health-details");
  if (!summary || !details) return;
  if (!json.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "健康度讀取失敗")}</div>`;
    details.textContent = "";
    return;
  }
  const c = json.counts || {};
  const s = json.storage || {};
  const auditOk = json.audit_integrity && json.audit_integrity.ok;
  const cards = [
    ["整體狀態", json.status === "ok" ? "正常" : "異常", json.status === "ok" ? "#4caf50" : "#ff4f6d"],
    ["維護模式", json.maintenance_mode ? "啟用" : "關閉", json.maintenance_mode ? "#ff4f6d" : "#4caf50"],
    ["審計鏈", auditOk ? "完整" : "異常", auditOk ? "#4caf50" : "#ff4f6d"],
    ["待審檢舉", String(c.pending_reports || 0), (c.pending_reports || 0) ? "#ffb74d" : "#4caf50"],
    ["待審申覆", String(c.pending_appeals || 0), (c.pending_appeals || 0) ? "#ffb74d" : "#4caf50"],
    ["活躍 Session", String(c.active_sessions || 0), "#82b1ff"],
    ["聊天訊息", String(c.chat_messages || 0), "#82b1ff"],
    ["資料庫大小", formatBytes(s.database_bytes), "#82b1ff"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${label}</div>
      <div style="font-size:1.05rem;color:${color};font-weight:700;margin-top:.2rem;">${sanitize(value)}</div>
    </div>
  `).join("");
  details.innerHTML = `
    使用者：${c.active_users || 0}/${c.users_total || 0} active ·
    違規紀錄：${c.violations_total || 0} ·
    審計紀錄：${c.audit_entries || 0} ·
    聊天檔案：${s.chat_files || 0} 個 / ${formatBytes(s.chat_bytes)} ·
    ${json.audit_integrity && json.audit_integrity.details ? sanitize(json.audit_integrity.details) : ""}
  `;
}

async function saveSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    maintenance_mode: !!$("s-maintenance-mode")?.checked,
    allow_register: !!$("s-allow-register")?.checked,
    require_email_verification: !!$("s-require-email")?.checked,
    max_login_failures: parseInt($("s-max-fail")?.value || "5"),
    block_duration_minutes: parseInt($("s-block-dur")?.value || "30"),
    session_ttl_hours: parseInt($("s-session-ttl")?.value || "24")
  };
  const res = await fetch(API + "/admin/settings", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const el = $("settings-msg");
  if (el) {
    el.textContent = json.ok ? "✅ 設定已儲存" : (json.msg || "儲存失敗");
    el.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
}

async function loadServerEnv() {
  if (!currentUser || currentRole !== "super_admin") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/environment", {
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
  details.innerHTML = `BASE_DIR：${sanitize(env.base_dir || "-")}<br>DB：${sanitize(env.database_path || "-")}<br>聊天檔數：${sanitize(String(env.chat_files || 0))}`;
}

async function restartServer() {
  if (!confirm("⚠️ 確定要重啟伺服器？所有連線將中斷。")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/restart", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    setTimeout(() => location.reload(), 3000);
  } else {
    alert(json.msg || "重啟失敗");
  }
}

// ── Bind all UI events ───────────────────────────────────────
function bindUiEvents() {
  const tabLogin    = $("tab-login");
  const tabRegister = $("tab-register");
  const tabModuleChat = $("tab-module-chat");
  const tabModuleAccounts = $("tab-module-accounts");
  const tabModuleServer = $("tab-module-server");
  const tabModuleAppeals = $("tab-module-appeals");
  const tabServerHealth = $("tab-server-health");
  const tabServerSettings = $("tab-server-settings");
  const tabServerEnv = $("tab-server-env");
  const tabUsers    = $("tab-users");
  const tabAudit    = $("tab-audit");
  const tabViol     = $("tab-violations");
  const tabAppeals  = $("tab-appeals");
  const tabReports  = $("tab-reports");
  const liBtn       = $("li-btn");
  const regBtn      = $("reg-btn");
  const logoutBtn   = $("logout-btn");
  const selfEditBtn = $("self-edit-btn");
  const adminRefresh = $("admin-refresh");
  const adminAddBtn  = $("admin-add-btn");
  const auditRefresh = $("audit-refresh");
  const violRefresh  = $("violations-refresh");
  const appealSubmit = $("appeal-submit-btn");
  const appealRefresh = $("appeal-refresh-btn");
  const reportRefresh = $("admin-reports-refresh");
  const settingsSave = $("settings-save-btn");
  const healthRefresh = $("health-refresh-btn");
  const restartBtn   = $("restart-server-btn");
  const editSaveBtn = $("user-edit-save");
  const editCancelBtn = $("user-edit-cancel");
  const chatCreateBtn = $("chat-create-room-btn");
  const chatJoinBtn = $("chat-join-room-btn");
  const chatRefreshRoomBtn = $("chat-room-refresh-btn");
  const chatRefreshMsgBtn = $("chat-refresh-msg-btn");
  const chatSendBtn = $("chat-send-btn");
  const chatInput = $("chat-message-input");
  const userEditOverlay = $("user-edit-overlay");

  if (tabLogin)    tabLogin.addEventListener("click",    () => showTab("login"));
  if (tabRegister) tabRegister.addEventListener("click", () => showTab("register"));
  if (tabModuleChat) tabModuleChat.addEventListener("click", () => switchModuleTab("chat"));
  if (tabModuleAppeals) tabModuleAppeals.addEventListener("click", () => switchModuleTab("appeals"));
  if (tabModuleAccounts) tabModuleAccounts.addEventListener("click", () => switchModuleTab("accounts"));
  if (tabModuleServer) tabModuleServer.addEventListener("click", () => switchModuleTab("server"));
  if (tabServerHealth) tabServerHealth.addEventListener("click", () => switchServerTab("health"));
  if (tabServerSettings) tabServerSettings.addEventListener("click", () => switchServerTab("settings"));
  if (tabServerEnv) tabServerEnv.addEventListener("click", () => switchServerTab("env"));
  if (tabUsers)    tabUsers.addEventListener("click",    () => switchAdminTab("users"));
  if (tabAudit)    tabAudit.addEventListener("click",    () => switchAdminTab("audit"));
  if (tabViol)     tabViol.addEventListener("click",     () => switchAdminTab("violations"));
  if (tabAppeals)  tabAppeals.addEventListener("click",   () => switchAdminTab("appeals"));
  if (tabReports)  tabReports.addEventListener("click",   () => switchAdminTab("reports"));
  if (liBtn)       liBtn.addEventListener("click",        doLogin);
  if (regBtn)      regBtn.addEventListener("click",       doRegister);
  if (logoutBtn)  logoutBtn.addEventListener("click",    doLogout);
  if (selfEditBtn) selfEditBtn.addEventListener("click", () => {
    if (currentUserId) editUser(currentUserId);
  });
  if (adminRefresh) adminRefresh.addEventListener("click", loadUsers);
  if (adminAddBtn)  adminAddBtn.addEventListener("click",  createUserByAdmin);
  if (chatCreateBtn) chatCreateBtn.addEventListener("click", createChatRoom);
  if (chatJoinBtn) chatJoinBtn.addEventListener("click", joinChatRoom);
  if (chatRefreshRoomBtn) chatRefreshRoomBtn.addEventListener("click", loadChatRooms);
  if (chatRefreshMsgBtn) chatRefreshMsgBtn.addEventListener("click", () => {
    if (selectedChatRoomId) loadChatMessages(selectedChatRoomId, false);
  });
  if (chatSendBtn) chatSendBtn.addEventListener("click", sendChatMessage);
  if (editSaveBtn)   editSaveBtn.addEventListener("click", submitEditUser);
  if (editCancelBtn) editCancelBtn.addEventListener("click", hideUserEditDialog);
  if (userEditOverlay) userEditOverlay.addEventListener("click", (e) => {
    if (e.target === userEditOverlay) hideUserEditDialog();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideUserEditDialog();
    }
  });
  if (chatInput) chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  // Audit pagination
  if (auditRefresh) auditRefresh.addEventListener("click", () => loadAudit(auditPage));
  if ($("audit-prev")) $("audit-prev").addEventListener("click", () => loadAudit(Math.max(0, auditPage - 1)));
  if ($("audit-next")) $("audit-next").addEventListener("click", () => loadAudit(auditPage + 1));

  if (appealSubmit) appealSubmit.addEventListener("click", submitAppeal);
  if (appealRefresh) appealRefresh.addEventListener("click", loadUserAppeals);
  if ($("admin-appeal-status")) $("admin-appeal-status").addEventListener("change", (e) => {
    adminAppealStatus = e?.target?.value || "pending";
    loadAdminAppeals(1, adminAppealStatus);
  });
  if ($("admin-appeals-prev")) $("admin-appeals-prev").addEventListener("click", () => loadAdminAppeals(Math.max(1, adminAppealPage - 1), adminAppealStatus));
  if ($("admin-appeals-next")) $("admin-appeals-next").addEventListener("click", () => loadAdminAppeals(adminAppealPage + 1, adminAppealStatus));
  if ($("admin-appeals-refresh")) $("admin-appeals-refresh").addEventListener("click", () => loadAdminAppeals(adminAppealPage, adminAppealStatus));
  if ($("admin-report-status")) $("admin-report-status").addEventListener("change", (e) => {
    adminReportStatus = e?.target?.value || "pending";
    loadAdminReports(0, adminReportStatus);
  });
  if ($("admin-reports-prev")) $("admin-reports-prev").addEventListener("click", () => loadAdminReports(Math.max(0, adminReportPage - 1), adminReportStatus));
  if ($("admin-reports-next")) $("admin-reports-next").addEventListener("click", () => loadAdminReports(adminReportPage + 1, adminReportStatus));
  if (reportRefresh) reportRefresh.addEventListener("click", () => loadAdminReports(adminReportPage, adminReportStatus));

  // Violations
  if (violRefresh) violRefresh.addEventListener("click", () => loadViolations(violationsPage, violationTargetUser));
  if ($("violations-prev")) $("violations-prev").addEventListener("click", () => loadViolations(Math.max(0, violationsPage - 1), violationTargetUser));
  if ($("violations-next")) $("violations-next").addEventListener("click", () => loadViolations(violationsPage + 1, violationTargetUser));

  // Settings
  if (settingsSave) settingsSave.addEventListener("click", saveSettings);
  if (healthRefresh) healthRefresh.addEventListener("click", loadServerHealth);
  if (restartBtn)   restartBtn.addEventListener("click",   restartServer);
}

$("li-pw").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});
$("reg-pw").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doRegister();
});

(async function init() {
  startClock();
  setupInactivityTracking();
  _csrfToken = readCookie("csrf_token");
  bindUiEvents();
  // 帶 timeout 的 fetch，避免 server 無回應時 UI 卡死
  async function safeFetch(url, opts = {}) {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), 5000);
    try {
      const res = await fetch(url, { ...opts, signal: ctrl.signal });
      clearTimeout(id);
      return res;
    } catch (e) {
      clearTimeout(id);
      throw e;
    }
  }
  try {
    const res = await safeFetch(API + "/me", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (json.ok) setAuthState(json);
  } catch (_) { /* 網路問題或 timeout，不影響操作 */ }
})();

})();
