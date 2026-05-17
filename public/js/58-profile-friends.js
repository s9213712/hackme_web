'use strict';

let currentProfileTab = "home";
let profilePanelCache = null;
let profileFriendsLoaded = false;
const targetOptionCache = new Map();

function profileSetMsg(text, bad = false) {
  const el = $("profile-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = text ? "msg show" + (bad ? " err" : " ok") : "msg";
  el.setAttribute("role", bad ? "alert" : "status");
  el.setAttribute("aria-live", bad ? "assertive" : "polite");
  el.setAttribute("aria-atomic", "true");
  if (typeof scheduleInlineMessageClear === "function") scheduleInlineMessageClear(el, text, !bad);
}

function profileConfirm(message, options = {}) {
  if (typeof showAppConfirm === "function") return showAppConfirm(message, options);
  return Promise.resolve(window.confirm(message));
}

async function profileReadJson(url, options = {}) {
  const res = await apiFetch(url, options);
  const json = await res.json().catch(() => ({}));
  if (!res.ok || json.ok === false) {
    const msg = json.msg || json.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return json;
}

function profileFriendStatusLabel(status) {
  return {
    self: "本人",
    none: "尚未成為好友",
    pending_outgoing: "等待對方同意",
    pending_incoming: "收到好友申請",
    accepted: "已成為好友",
    rejected: "已拒絕",
    blocked: "已封鎖",
    blocked_by_them: "無法互動",
    anonymous: "未登入",
  }[status] || status || "-";
}

function renderProfileAvatar(targetId, profile) {
  const el = $(targetId);
  if (!el) return;
  el.innerHTML = userAvatarInnerMarkup(profile?.id, profile?.username || "", profile?.avatar_file_id || "");
  bindAvatarFallbacks(el);
}

function renderProfileHome(profile) {
  renderProfileAvatar("profile-home-avatar", profile);
  const name = profile?.display_name || profile?.username || "-";
  const nameEl = $("profile-home-name");
  if (nameEl) nameEl.textContent = name;
  const meta = $("profile-home-meta");
  if (meta) {
    const role = profile?.role_label || profile?.role || "使用者";
    const level = profile?.member_level ? ` · ${profile.member_level}` : "";
    meta.textContent = `@${profile?.username || "-"} · ${role}${level}`;
  }
  const bio = $("profile-home-bio");
  if (bio) bio.textContent = profile?.bio || "尚未填寫個人簡介。";
  const signature = $("profile-home-signature");
  if (signature) signature.textContent = profile?.signature || "";
  const status = $("profile-home-friend-status");
  if (status) status.textContent = profileFriendStatusLabel(profile?.friend_status || "self");
  const visibility = $("profile-home-visibility");
  if (visibility) visibility.textContent = profile?.profile_visibility || "public";
  const code = $("profile-home-friend-code");
  if (code) code.textContent = profile?.friend_code || "只會顯示自己的代碼";
}

function fillProfileEdit(profile) {
  const fields = {
    "profile-edit-display-name": profile?.display_name || "",
    "profile-edit-location": profile?.location || "",
    "profile-edit-website": profile?.website || "",
    "profile-edit-bio": profile?.bio || "",
    "profile-edit-signature": profile?.signature || "",
    "profile-edit-visibility": profile?.profile_visibility || "public",
    "profile-friend-code": profile?.friend_code || "",
  };
  Object.entries(fields).forEach(([id, value]) => {
    const el = $(id);
    if (el) el.value = value;
  });
}

async function loadMyProfile({ quiet = false } = {}) {
  try {
    const json = await profileReadJson(API + "/users/me/profile");
    profilePanelCache = json.profile || {};
    renderProfileHome(profilePanelCache);
    fillProfileEdit(profilePanelCache);
    if (!quiet) profileSetMsg("");
    return profilePanelCache;
  } catch (err) {
    profileSetMsg(err.message || "個人資料讀取失敗", true);
    return null;
  }
}

async function saveMyProfile() {
  const payload = {
    display_name: $("profile-edit-display-name")?.value || "",
    location: $("profile-edit-location")?.value || "",
    website: $("profile-edit-website")?.value || "",
    bio: $("profile-edit-bio")?.value || "",
    signature: $("profile-edit-signature")?.value || "",
    profile_visibility: $("profile-edit-visibility")?.value || "public",
  };
  try {
    const json = await profileReadJson(API + "/users/me/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    profilePanelCache = json.profile || {};
    renderProfileHome(profilePanelCache);
    fillProfileEdit(profilePanelCache);
    profileSetMsg(json.msg || "個人資料已更新");
  } catch (err) {
    profileSetMsg(err.message || "個人資料更新失敗", true);
  }
}

function renderProfileFriendRows(containerId, rows, mode) {
  const el = $(containerId);
  if (!el) return;
  if (!rows || !rows.length) {
    el.innerHTML = `<div class="drive-empty">目前沒有資料</div>`;
    return;
  }
  el.innerHTML = rows.map((item) => {
    const badge = item.other_is_official ? `<span class="profile-official-badge">官方</span>` : "";
    const display = sanitize(item.other_display_name || item.other_username || "-");
    const username = sanitize(item.other_username || "-");
    let actions = "";
    if (mode === "friends") {
      actions = `
        <button class="btn chat-sticker-btn" type="button" data-profile-pm="${username}">私訊</button>
        <button class="btn chat-sticker-btn" type="button" data-profile-remove="${item.other_user_id}">解除</button>
        <button class="btn btn-danger chat-sticker-btn" type="button" data-profile-block="${item.other_user_id}">封鎖</button>
      `;
    } else if (mode === "incoming") {
      actions = `
        <button class="btn chat-sticker-btn" type="button" data-profile-review="${item.id}" data-decision="accept">接受</button>
        <button class="btn chat-sticker-btn" type="button" data-profile-review="${item.id}" data-decision="reject">拒絕</button>
      `;
    } else if (mode === "blocked") {
      actions = `<button class="btn chat-sticker-btn" type="button" data-profile-unblock="${item.other_user_id}">解除封鎖</button>`;
    } else {
      actions = `<span class="drive-card-sub">等待 ${username} 回覆</span>`;
    }
    return `
      <div class="profile-friend-row">
        <div>
          <strong>${display}</strong>
          ${badge}
          <span>@${username}</span>
        </div>
        <div class="profile-friend-actions">${actions}</div>
      </div>
    `;
  }).join("");
  el.querySelectorAll("[data-profile-pm]").forEach((btn) => {
    btn.addEventListener("click", () => openPmWithUser(btn.dataset.profilePm || ""));
  });
  el.querySelectorAll("[data-profile-remove]").forEach((btn) => {
    btn.addEventListener("click", () => removeProfileFriend(btn.dataset.profileRemove));
  });
  el.querySelectorAll("[data-profile-block]").forEach((btn) => {
    btn.addEventListener("click", () => blockProfileUser(btn.dataset.profileBlock));
  });
  el.querySelectorAll("[data-profile-unblock]").forEach((btn) => {
    btn.addEventListener("click", () => unblockProfileUser(btn.dataset.profileUnblock));
  });
  el.querySelectorAll("[data-profile-review]").forEach((btn) => {
    btn.addEventListener("click", () => reviewProfileFriend(btn.dataset.profileReview, btn.dataset.decision));
  });
}

async function loadProfileFriends({ quiet = false } = {}) {
  try {
    const json = await profileReadJson(API + "/friends");
    profileFriendsLoaded = true;
    renderProfileFriendRows("profile-friend-list", json.friends || [], "friends");
    renderProfileFriendRows("profile-incoming-list", json.incoming || [], "incoming");
    renderProfileFriendRows("profile-outgoing-list", json.outgoing || [], "outgoing");
    renderProfileFriendRows("profile-blocked-list", json.blocked || [], "blocked");
    if (!quiet) profileSetMsg("");
  } catch (err) {
    profileSetMsg(err.message || "好友資料讀取失敗", true);
  }
}

async function requestProfileFriend() {
  const raw = ($("profile-request-user-input")?.value || "").trim();
  if (!raw) {
    profileSetMsg("請輸入帳號或 user id", true);
    return;
  }
  const payload = /^\d+$/.test(raw) ? { user_id: Number(raw) } : { username: raw };
  try {
    const json = await profileReadJson(API + "/friends/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    profileSetMsg(json.msg || "好友邀請已送出");
    if ($("profile-request-user-input")) $("profile-request-user-input").value = "";
    await loadProfileFriends({ quiet: true });
    if (typeof loadChatFriends === "function") loadChatFriends();
  } catch (err) {
    profileSetMsg(err.message || "好友邀請失敗", true);
  }
}

async function addProfileFriendByCode() {
  const code = ($("profile-add-code-input")?.value || "").trim();
  if (!code) {
    profileSetMsg("請輸入好友代碼", true);
    return;
  }
  try {
    const json = await profileReadJson(API + "/friends/add-by-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ friend_code: code }),
    });
    profileSetMsg(json.msg || "已加入好友");
    if ($("profile-add-code-input")) $("profile-add-code-input").value = "";
    await loadProfileFriends({ quiet: true });
    if (typeof loadChatFriends === "function") loadChatFriends();
  } catch (err) {
    profileSetMsg(err.message || "加入好友失敗", true);
  }
}

async function reviewProfileFriend(requestId, decision) {
  if (!requestId || !decision) return;
  try {
    const json = await profileReadJson(API + `/friends/requests/${encodeURIComponent(requestId)}/${encodeURIComponent(decision)}`, {
      method: "POST",
    });
    profileSetMsg(json.msg || "好友申請已處理");
    await loadProfileFriends({ quiet: true });
    if (typeof loadChatFriends === "function") loadChatFriends();
  } catch (err) {
    profileSetMsg(err.message || "好友申請處理失敗", true);
  }
}

async function removeProfileFriend(friendUserId) {
  if (!friendUserId) return;
  if (!(await profileConfirm("確定要解除這位好友嗎？解除後需要重新申請才能恢復好友互動。", {
    title: "解除好友",
    confirmLabel: "解除",
    danger: true,
  }))) return;
  try {
    const json = await profileReadJson(API + `/friends/${encodeURIComponent(friendUserId)}`, { method: "DELETE" });
    profileSetMsg(json.msg || "已解除好友");
    await loadProfileFriends({ quiet: true });
    if (typeof loadChatFriends === "function") loadChatFriends();
  } catch (err) {
    profileSetMsg(err.message || "解除好友失敗", true);
  }
}

async function blockProfileUser(friendUserId) {
  if (!friendUserId) return;
  if (!(await profileConfirm("確定要封鎖這位使用者？封鎖後對方不能再與你私訊、邀請遊戲或重新送出好友申請。", {
    title: "封鎖使用者",
    confirmLabel: "封鎖",
    danger: true,
  }))) return;
  try {
    const json = await profileReadJson(API + `/friends/${encodeURIComponent(friendUserId)}/block`, { method: "POST" });
    profileSetMsg(json.msg || "已封鎖使用者");
    await loadProfileFriends({ quiet: true });
    if (typeof loadChatFriends === "function") loadChatFriends();
  } catch (err) {
    profileSetMsg(err.message || "封鎖失敗", true);
  }
}

async function unblockProfileUser(friendUserId) {
  if (!friendUserId) return;
  if (!(await profileConfirm("確定要解除封鎖？解除後不會自動恢復好友關係。", {
    title: "解除封鎖",
    confirmLabel: "解除封鎖",
  }))) return;
  try {
    const json = await profileReadJson(API + `/friends/${encodeURIComponent(friendUserId)}/block`, { method: "DELETE" });
    profileSetMsg(json.msg || "已解除封鎖");
    await loadProfileFriends({ quiet: true });
    if (typeof loadChatFriends === "function") loadChatFriends();
  } catch (err) {
    profileSetMsg(err.message || "解除封鎖失敗", true);
  }
}

async function rotateProfileFriendCode() {
  if (!(await profileConfirm("重新產生好友代碼後，舊代碼會失效。確定要繼續嗎？", {
    title: "重新產生好友代碼",
    confirmLabel: "重新產生",
  }))) return;
  try {
    const json = await profileReadJson(API + "/users/me/friend-code/rotate", { method: "POST" });
    profileSetMsg(json.msg || "好友代碼已重新產生");
    await loadMyProfile({ quiet: true });
  } catch (err) {
    profileSetMsg(err.message || "好友代碼更新失敗", true);
  }
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return false;
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return true;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  textarea.style.left = "-1000px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, value.length);
  try {
    return document.execCommand("copy");
  } finally {
    textarea.remove();
  }
}

function setProfileCopyButtonFeedback(button) {
  if (!button) return;
  const original = button.dataset.originalText || button.textContent || "複製";
  button.dataset.originalText = original;
  button.textContent = "已複製";
  button.disabled = true;
  setTimeout(() => {
    button.textContent = original;
    button.disabled = false;
  }, 1400);
}

async function copyProfileFriendCode(event) {
  const button = event?.currentTarget || $("profile-copy-code-btn");
  const code = $("profile-friend-code")?.value || profilePanelCache?.friend_code || "";
  if (!code) {
    profileSetMsg("目前沒有可複製的好友代碼", true);
    return;
  }
  try {
    const copied = await copyTextToClipboard(code);
    if (!copied) throw new Error("copy failed");
    setProfileCopyButtonFeedback(button);
    showActionFeedback(button || document.activeElement, "好友代碼已複製", true, { skipToast: true });
  } catch (err) {
    const input = $("profile-friend-code");
    if (input) {
      input.focus();
      input.select();
    }
    showActionFeedback(button || document.activeElement, "請手動複製好友代碼", false, { skipToast: true });
  }
}

function switchProfileTab(tab = "home") {
  const next = ["home", "edit", "friends"].includes(tab) ? tab : "home";
  currentProfileTab = next;
  document.querySelectorAll("[data-profile-tab]").forEach((btn) => {
    const active = btn.dataset.profileTab === next;
    btn.classList.toggle("btn-primary", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  ["home", "edit", "friends"].forEach((key) => {
    const pane = $("profile-pane-" + key);
    if (pane) pane.classList.toggle("active", key === next);
  });
  if (currentModuleTab === "profile") {
    if (next === "friends") {
      loadMyProfile({ quiet: true });
      loadProfileFriends();
    } else {
      loadMyProfile();
    }
  }
  if (typeof updateSidebarActiveState === "function") updateSidebarActiveState();
}

function loadProfilePanel() {
  if (currentProfileTab === "friends") {
    loadMyProfile({ quiet: true });
    loadProfileFriends({ quiet: !profileFriendsLoaded });
    return;
  }
  loadMyProfile();
}

function openMyProfilePanel(tab = "home") {
  if (typeof switchModuleTab === "function") switchModuleTab("profile");
  switchProfileTab(tab);
}

function bindProfileFriendsControls() {
  if (window.__profileFriendsBound) return;
  window.__profileFriendsBound = true;
  document.querySelectorAll("[data-profile-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchProfileTab(btn.dataset.profileTab || "home"));
  });
  const refresh = $("profile-refresh-btn");
  if (refresh) refresh.addEventListener("click", loadProfilePanel);
  const save = $("profile-save-btn");
  if (save) save.addEventListener("click", saveMyProfile);
  const account = $("profile-edit-account-btn");
  if (account) account.addEventListener("click", () => {
    if (currentUserId && typeof editUser === "function") editUser(currentUserId);
  });
  const addByCode = $("profile-add-code-btn");
  if (addByCode) addByCode.addEventListener("click", addProfileFriendByCode);
  const requestBtn = $("profile-request-user-btn");
  if (requestBtn) requestBtn.addEventListener("click", requestProfileFriend);
  const copyCode = $("profile-copy-code-btn");
  if (copyCode) copyCode.addEventListener("click", copyProfileFriendCode);
  const rotateCode = $("profile-rotate-code-btn");
  if (rotateCode) rotateCode.addEventListener("click", rotateProfileFriendCode);
  const sidebarCard = $("sidebar-user-card");
  if (sidebarCard) {
    sidebarCard.addEventListener("click", () => {
      if (currentUser) openMyProfilePanel("home");
    });
    sidebarCard.addEventListener("keydown", (event) => {
      if (!currentUser) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openMyProfilePanel("home");
      }
    });
  }
  document.addEventListener("hackme:module-changed", (event) => {
    if (event?.detail?.current === "profile") loadProfilePanel();
  });
  bindTargetUserOptionInputs();
}

function ensureTargetOptionsDatalist(context = "personal") {
  const safeContext = String(context || "personal").replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
  const id = safeContext === "personal" ? "target-options-personal" : `target-options-${safeContext}`;
  let el = $(id);
  if (!el) {
    el = document.createElement("datalist");
    el.id = id;
    document.body.appendChild(el);
  }
  return el;
}

function renderTargetOptions(context, users) {
  const datalist = ensureTargetOptionsDatalist(context);
  datalist.innerHTML = (Array.isArray(users) ? users : []).map((user) => {
    const value = sanitize(user.username || "");
    const label = sanitize(user.label || user.username || "");
    return value ? `<option value="${value}" label="${label}"></option>` : "";
  }).join("");
}

async function loadTargetUserOptions(context = "personal", { force = false } = {}) {
  const key = String(context || "personal");
  if (!force && targetOptionCache.has(key)) {
    renderTargetOptions(key, targetOptionCache.get(key));
    return targetOptionCache.get(key);
  }
  try {
    const json = await profileReadJson(API + `/users/target-options?context=${encodeURIComponent(key)}&limit=160`);
    const users = Array.isArray(json.users) ? json.users : [];
    targetOptionCache.set(key, users);
    renderTargetOptions(key, users);
    return users;
  } catch (err) {
    renderTargetOptions(key, []);
    return [];
  }
}

function bindTargetUserOptionInputs() {
  [
    ["chat-room-target-user", "pm"],
    ["chat-room-invite-users", "private_group"],
    ["chat-room-invite-more-users", "private_group"],
    ["drive-share-account", "cloud_drive_share"],
  ].forEach(([id, context]) => {
    const input = $(id);
    if (!input || input.dataset.targetOptionsBound === "1") return;
    input.dataset.targetOptionsBound = "1";
    input.setAttribute("list", ensureTargetOptionsDatalist(context).id);
    input.addEventListener("focus", () => loadTargetUserOptions(context));
    input.addEventListener("input", () => loadTargetUserOptions(context));
  });
}
