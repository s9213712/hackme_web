
(function() {
'use strict';

const API = "/api";
let _csrfToken = null;
let currentUser = null;
let currentRole = "user";
let canManageUsers = false;
let users = [];

function $(id) { return document.getElementById(id); }

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
  if (!force) {
    const cookieToken = readCookie("csrf_token");
    if (cookieToken) {
      _csrfToken = cookieToken;
      return;
    }
  }

  try {
    const res = await fetch(API + '/csrf-token', { credentials: 'same-origin' });
    const json = await res.json();
    if (json.ok) _csrfToken = json.csrf_token;
    else _csrfToken = null;
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

function setAuthState(json) {
  currentUser = json.username || null;
  currentRole = json.role || "user";
  canManageUsers = currentRole === "super_admin";
  $("auth-card").style.display = "none";
  $("success-screen").classList.add("show");
  $("me-user").textContent = sanitize(currentUser || "-");
  $("me-role").textContent = sanitize(json.role_label || currentRole || "-");
  $("me-nickname").textContent = sanitize(json.nickname || "-");
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

  // Super admin: show settings tab + system tools
  const settingsTab = $("tab-settings");
  if (settingsTab) settingsTab.style.display = currentRole === "super_admin" ? "" : "none";
  const restartBtn = $("restart-server-btn");
  if (restartBtn) restartBtn.style.display = currentRole === "super_admin" ? "" : "none";

  if (currentRole === "manager" || currentRole === "super_admin") {
    loadUsers();
  }
}

function resetAuthState() {
  currentUser = null;
  currentRole = "user";
  canManageUsers = false;
  users = [];
  $("success-screen").classList.remove("show");
  $("admin-wrap").className = "admin-wrap";
  $("me-user").textContent = "-";
  $("me-role").textContent = "-";
  $("me-nickname").textContent = "-";
  $("auth-card").style.display = "";
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
    const actionButtons = [];
    if (currentRole === "manager" || currentRole === "super_admin") {
      if (u.role !== "super_admin") {
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
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role === "user") {
      const promBtn = document.createElement("button");
      promBtn.className = "btn";
      promBtn.type = "button";
      promBtn.textContent = "⬆ 升級";
      promBtn.style.color = "#82b1ff";
      promBtn.addEventListener("click", () => promoteUser(u.id, u.username));
      actionButtons.push(promBtn);
    }
    // Demote button (super_admin only: manager→user, user→delete)
    if (currentRole === "super_admin" && (u.role === "manager" || u.role === "user")) {
      const demBtn = document.createElement("button");
      demBtn.className = "btn";
      demBtn.type = "button";
      demBtn.textContent = "⬇ 降級";
      demBtn.style.color = "#ff8a80";
      demBtn.addEventListener("click", () => demoteUser(u.id, u.username, u.role));
      actionButtons.push(demBtn);
    }
    // Violation controls (manager/super_admin)
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role !== "super_admin") {
      const violCount = u.violation_count || 0;
      const violBtn = document.createElement("button");
      violBtn.className = "btn";
      violBtn.type = "button";
      violBtn.textContent = `⚠ ${violCount}`;
      violBtn.style.color = violCount > 0 ? "#ff4f6d" : "#888";
      violBtn.addEventListener("click", () => addViolation(u.id));
      actionButtons.push(violBtn);
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
    if (canManageUsers) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn btn-primary";
      editBtn.type = "button";
      editBtn.textContent = "修改";
      editBtn.addEventListener("click", () => editUser(u.id));
      editBtn.classList.add("action-edit-user");
      actionButtons.push(editBtn);
      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger";
      delBtn.type = "button";
      delBtn.textContent = "刪除";
      delBtn.addEventListener("click", () => removeUser(u.id));
      delBtn.classList.add("action-remove-user");
      actionButtons.push(delBtn);
    }
    const tr = document.createElement("tr");
    if (isBlocked) tr.style.opacity = "0.5";
    const actions = document.createElement("div");
    actions.className = "action";
    actionButtons.forEach((btn) => actions.appendChild(btn));
    const statusLabel = isBlocked ? `<span style="color:#ff4f6d;">封鎖中</span>` : `<span style="color:#4caf50;">正常</span>`;
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
    if (me.ok) setAuthState(me);
    else setAuthState({ username: user, role: "user", role_label: "一般用戶", nickname: "-" });
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
  if (!target) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  let source = target;
  const detailRes = await fetch(API + `/admin/users/${userId}`, {
    method: "GET",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  }).then((r) => r.json().catch(() => ({})));
  if (detailRes && detailRes.ok && detailRes.user) {
    source = detailRes.user;
  }
  const current = {
    nickname: source.nickname || "",
    real_name: source.real_name || "",
    id_number: source.id_number || "",
    birthdate: source.birthdate || "",
    phone: source.phone || ""
  };

  const nickname = window.prompt("修改暱稱", current.nickname);
  if (nickname === null) return;
  const realName = window.prompt("修改真實姓名", current.real_name);
  if (realName === null) return;
  const idNumber = window.prompt("修改身分證", current.id_number);
  if (idNumber === null) return;
  const birthDate = window.prompt("修改生日（YYYY-MM-DD）", current.birthdate);
  if (birthDate === null) return;
  const phone = window.prompt("修改電話", current.phone);
  if (phone === null) return;

  const normalized = {
    nickname: (nickname || "").trim(),
    real_name: (realName || "").trim(),
    id_number: (idNumber || "").trim(),
    birthdate: (birthDate || "").trim(),
    phone: (phone || "").trim()
  };

  const password = window.prompt("修改密碼（留空則不改）");
  if (password === null) return;
  let passwordConfirm = "";
  if (password) {
    passwordConfirm = window.prompt("再次輸入新密碼");
    if (passwordConfirm === null) return;
    if (password !== passwordConfirm) {
      flash($("li-msg"), "兩次密碼輸入不一致", false);
      return;
    }
  }

  await fetchCsrfToken({ force: true });
  const payload = {
    nickname: (normalized.nickname === current.nickname ? null : normalized.nickname),
    real_name: (normalized.real_name === current.real_name ? null : normalized.real_name),
    id_number: (normalized.id_number === current.id_number ? null : normalized.id_number),
    birthdate: (normalized.birthdate === current.birthdate ? null : normalized.birthdate),
    phone: (normalized.phone === current.phone ? null : normalized.phone)
  };
  Object.keys(payload).forEach((k) => {
    if (payload[k] === null) delete payload[k];
  });
  if (!Object.keys(payload).length && !password) {
    flash($("li-msg"), "未變更任何欄位", false);
    return;
  }
  if (password) {
    payload.password = password;
    payload.password_confirm = passwordConfirm;
  }
  const res = await fetch(API + `/admin/users/${userId}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    loadUsers();
  } else {
    flash($("li-msg"), json.msg || "修改失敗", false);
  }
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

// ── Admin tab switching ─────────────────────────────────────
let currentTab = "users";
function switchTab(tab) {
  currentTab = tab;
  ["users","audit","violations","settings"].forEach(t => {
    const sec = $("sec-" + t);
    if (sec) sec.classList.toggle("active", t === tab);
  });
  ["tab-users","tab-audit","tab-violations","tab-settings"].forEach(id => {
    const btn = $(id);
    if (btn) btn.classList.toggle("active", id === "tab-" + tab);
  });
  if (tab === "audit") loadAudit(0);
  if (tab === "violations") loadViolations(0);
  if (tab === "settings") loadSettings();
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
    const detail = isObj && e.details ? JSON.stringify(e.details) : "";
    const chain = isObj && e._chain_hash ? `<span style="color:#4caf50;">█</span>` : "·";
    return `<div style="border-bottom:1px solid #222;padding:.35rem .25rem;word-break:break-all;">
      <span style="color:#888;">${ts}</span> ${chain}
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
    integEl.textContent = json.integrity === true ? "🔗 鏈完整" : json.integrity === false ? "⚠️ 鏈已斷！" : "";
    integEl.style.color = json.integrity === true ? "#4caf50" : json.integrity === false ? "#ff4f6d" : "var(--muted)";
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
    const actor = isObj ? e.actor || "" : "";
    const chain = isObj && e._chain_hash ? `<span style="color:#4caf50;">█</span>` : "·";
    return `<div style="border-bottom:1px solid #222;padding:.35rem .25rem;word-break:break-all;">
      <span style="color:#888;">${ts}</span> ${chain}
      <span style="color:#ff8a80;">${sanitize(reason)}</span>
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
  if ($("s-allow-register")) $("s-allow-register").checked = !!s.allow_register;
  if ($("s-require-email")) $("s-require-email").checked = !!s.require_email;
  if ($("s-max-fail")) $("s-max-fail").value = s.max_login_fail || 5;
  if ($("s-block-dur")) $("s-block-dur").value = s.block_duration_minutes || 30;
  if ($("s-session-ttl")) $("s-session-ttl").value = s.session_ttl_hours || 24;
}

async function saveSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    allow_register: !!$("s-allow-register")?.checked,
    require_email: !!$("s-require-email")?.checked,
    max_login_fail: parseInt($("s-max-fail")?.value || "5"),
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
  const tabUsers    = $("tab-users");
  const tabAudit    = $("tab-audit");
  const tabViol     = $("tab-violations");
  const tabSettings = $("tab-settings");
  const liBtn       = $("li-btn");
  const regBtn      = $("reg-btn");
  const logoutBtn   = $("logout-btn");
  const adminRefresh = $("admin-refresh");
  const adminAddBtn  = $("admin-add-btn");
  const auditRefresh = $("audit-refresh");
  const violRefresh  = $("violations-refresh");
  const settingsSave = $("settings-save-btn");
  const restartBtn   = $("restart-server-btn");

  if (tabLogin)    tabLogin.addEventListener("click",    () => showTab("login"));
  if (tabRegister) tabRegister.addEventListener("click", () => showTab("register"));
  if (tabUsers)    tabUsers.addEventListener("click",    () => switchTab("users"));
  if (tabAudit)    tabAudit.addEventListener("click",    () => switchTab("audit"));
  if (tabViol)     tabViol.addEventListener("click",     () => switchTab("violations"));
  if (tabSettings) tabSettings.addEventListener("click", () => switchTab("settings"));
  if (liBtn)       liBtn.addEventListener("click",        doLogin);
  if (regBtn)      regBtn.addEventListener("click",       doRegister);
  if (logoutBtn)  logoutBtn.addEventListener("click",    doLogout);
  if (adminRefresh) adminRefresh.addEventListener("click", loadUsers);
  if (adminAddBtn)  adminAddBtn.addEventListener("click",  createUserByAdmin);

  // Audit pagination
  if (auditRefresh) auditRefresh.addEventListener("click", () => loadAudit(auditPage));
  if ($("audit-prev")) $("audit-prev").addEventListener("click", () => loadAudit(Math.max(0, auditPage - 1)));
  if ($("audit-next")) $("audit-next").addEventListener("click", () => loadAudit(auditPage + 1));

  // Violations
  if (violRefresh) violRefresh.addEventListener("click", () => loadViolations(violationsPage, violationTargetUser));
  if ($("violations-prev")) $("violations-prev").addEventListener("click", () => loadViolations(Math.max(0, violationsPage - 1), violationTargetUser));
  if ($("violations-next")) $("violations-next").addEventListener("click", () => loadViolations(violationsPage + 1, violationTargetUser));

  // Settings
  if (settingsSave) settingsSave.addEventListener("click", saveSettings);
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
