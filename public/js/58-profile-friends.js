'use strict';

let currentProfileTab = "home";
let profilePanelCache = null;
let profileFriendsLoaded = false;
const targetOptionCache = new Map();
const PROFILE_AVATAR_CROPPER_MIN_ZOOM = 1;
const PROFILE_AVATAR_CROPPER_MAX_ZOOM = 3;
const profileAvatarCropState = {
  objectUrl: "",
  hasImage: false,
  naturalWidth: 0,
  naturalHeight: 0,
  baseScale: 1,
  zoom: 1,
  offsetX: 0,
  offsetY: 0,
  dragging: false,
  pointerId: null,
  startX: 0,
  startY: 0,
  startOffsetX: 0,
  startOffsetY: 0,
};

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

function profileAvatarSetMsg(text, bad = false) {
  const el = $("profile-avatar-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = text ? "msg show" + (bad ? " err" : " ok") : "msg";
  el.setAttribute("role", bad ? "alert" : "status");
  el.setAttribute("aria-live", bad ? "assertive" : "polite");
  if (text && typeof scheduleInlineMessageClear === "function") {
    scheduleInlineMessageClear(el, text, !bad, { duration: bad ? 4200 : 2200 });
  }
}

function profileAvatarCropperElements() {
  return {
    overlay: $("profile-avatar-overlay"),
    cropper: $("profile-avatar-cropper"),
    stage: $("profile-avatar-crop-stage"),
    image: $("profile-avatar-crop-image"),
    box: $("profile-avatar-crop-box"),
    zoom: $("profile-avatar-crop-zoom"),
    center: $("profile-avatar-crop-center"),
    file: $("profile-avatar-file"),
  };
}

function profileAvatarClamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function setProfileAvatarCropHidden(crop = {}) {
  const fields = {
    "profile-avatar-crop-x": crop.x || 0,
    "profile-avatar-crop-y": crop.y || 0,
    "profile-avatar-crop-width": crop.width || 0,
    "profile-avatar-crop-height": crop.height || 0,
  };
  Object.entries(fields).forEach(([id, value]) => {
    const el = $(id);
    if (el) el.value = String(value);
  });
}

function resetProfileAvatarCropper({ keepFile = false } = {}) {
  const els = profileAvatarCropperElements();
  if (profileAvatarCropState.objectUrl) URL.revokeObjectURL(profileAvatarCropState.objectUrl);
  profileAvatarCropState.objectUrl = "";
  profileAvatarCropState.hasImage = false;
  profileAvatarCropState.naturalWidth = 0;
  profileAvatarCropState.naturalHeight = 0;
  profileAvatarCropState.baseScale = 1;
  profileAvatarCropState.zoom = 1;
  profileAvatarCropState.offsetX = 0;
  profileAvatarCropState.offsetY = 0;
  profileAvatarCropState.dragging = false;
  profileAvatarCropState.pointerId = null;
  if (!keepFile && els.file) els.file.value = "";
  if (els.cropper) els.cropper.hidden = true;
  if (els.image) {
    els.image.removeAttribute("src");
    els.image.style.left = "";
    els.image.style.top = "";
    els.image.style.width = "";
    els.image.style.height = "";
  }
  if (els.stage) els.stage.classList.remove("is-dragging");
  if (els.zoom) els.zoom.value = "1";
  setProfileAvatarCropHidden();
}

function profileAvatarStageMetrics() {
  const { stage } = profileAvatarCropperElements();
  if (!stage) return null;
  const rect = stage.getBoundingClientRect();
  const width = Math.max(0, rect.width || 0);
  const height = Math.max(0, rect.height || 0);
  if (!width || !height) return null;
  const cropSize = Math.max(96, Math.min(width, height) * 0.72);
  return {
    width,
    height,
    cropSize,
    cropLeft: (width - cropSize) / 2,
    cropTop: (height - cropSize) / 2,
  };
}

function clampProfileAvatarOffsets(metrics = profileAvatarStageMetrics()) {
  if (!metrics || !profileAvatarCropState.hasImage) return;
  const scale = profileAvatarCropState.baseScale * profileAvatarCropState.zoom;
  const imageWidth = profileAvatarCropState.naturalWidth * scale;
  const imageHeight = profileAvatarCropState.naturalHeight * scale;
  const maxX = Math.max(0, (imageWidth - metrics.cropSize) / 2);
  const maxY = Math.max(0, (imageHeight - metrics.cropSize) / 2);
  profileAvatarCropState.offsetX = profileAvatarClamp(profileAvatarCropState.offsetX, -maxX, maxX);
  profileAvatarCropState.offsetY = profileAvatarClamp(profileAvatarCropState.offsetY, -maxY, maxY);
}

function currentProfileAvatarCropPayload() {
  const metrics = profileAvatarStageMetrics();
  if (!metrics || !profileAvatarCropState.hasImage || !profileAvatarCropState.naturalWidth || !profileAvatarCropState.naturalHeight) {
    return {
      x: parseInt($("profile-avatar-crop-x")?.value || "0", 10) || 0,
      y: parseInt($("profile-avatar-crop-y")?.value || "0", 10) || 0,
      width: parseInt($("profile-avatar-crop-width")?.value || "0", 10) || 0,
      height: parseInt($("profile-avatar-crop-height")?.value || "0", 10) || 0,
    };
  }
  const scale = profileAvatarCropState.baseScale * profileAvatarCropState.zoom;
  const imageWidth = profileAvatarCropState.naturalWidth * scale;
  const imageHeight = profileAvatarCropState.naturalHeight * scale;
  const imageLeft = (metrics.width / 2 + profileAvatarCropState.offsetX) - imageWidth / 2;
  const imageTop = (metrics.height / 2 + profileAvatarCropState.offsetY) - imageHeight / 2;
  let cropX = Math.round((metrics.cropLeft - imageLeft) / scale);
  let cropY = Math.round((metrics.cropTop - imageTop) / scale);
  let cropSide = Math.round(metrics.cropSize / scale);
  cropSide = profileAvatarClamp(cropSide, 1, Math.min(profileAvatarCropState.naturalWidth, profileAvatarCropState.naturalHeight));
  cropX = profileAvatarClamp(cropX, 0, Math.max(0, profileAvatarCropState.naturalWidth - cropSide));
  cropY = profileAvatarClamp(cropY, 0, Math.max(0, profileAvatarCropState.naturalHeight - cropSide));
  const crop = { x: cropX, y: cropY, width: cropSide, height: cropSide };
  setProfileAvatarCropHidden(crop);
  return crop;
}

function renderProfileAvatarCropper() {
  const els = profileAvatarCropperElements();
  const metrics = profileAvatarStageMetrics();
  if (!els.image || !els.box || !metrics || !profileAvatarCropState.hasImage) return;
  profileAvatarCropState.baseScale = Math.max(
    metrics.width / profileAvatarCropState.naturalWidth,
    metrics.height / profileAvatarCropState.naturalHeight
  );
  profileAvatarCropState.zoom = profileAvatarClamp(Number(profileAvatarCropState.zoom) || 1, PROFILE_AVATAR_CROPPER_MIN_ZOOM, PROFILE_AVATAR_CROPPER_MAX_ZOOM);
  clampProfileAvatarOffsets(metrics);
  const scale = profileAvatarCropState.baseScale * profileAvatarCropState.zoom;
  const imageWidth = profileAvatarCropState.naturalWidth * scale;
  const imageHeight = profileAvatarCropState.naturalHeight * scale;
  els.image.style.width = `${imageWidth}px`;
  els.image.style.height = `${imageHeight}px`;
  els.image.style.left = `${(metrics.width / 2 + profileAvatarCropState.offsetX) - imageWidth / 2}px`;
  els.image.style.top = `${(metrics.height / 2 + profileAvatarCropState.offsetY) - imageHeight / 2}px`;
  els.box.style.width = `${metrics.cropSize}px`;
  els.box.style.height = `${metrics.cropSize}px`;
  els.box.style.left = `${metrics.cropLeft}px`;
  els.box.style.top = `${metrics.cropTop}px`;
  currentProfileAvatarCropPayload();
}

function loadProfileAvatarFile(file) {
  if (!file) {
    resetProfileAvatarCropper({ keepFile: true });
    return;
  }
  if (!/^image\/(png|jpe?g|gif)$/i.test(file.type || "")) {
    resetProfileAvatarCropper();
    profileAvatarSetMsg("頭像僅支援 JPEG / PNG / GIF", true);
    return;
  }
  const els = profileAvatarCropperElements();
  if (!els.cropper || !els.image) return;
  const nextUrl = URL.createObjectURL(file);
  if (profileAvatarCropState.objectUrl) URL.revokeObjectURL(profileAvatarCropState.objectUrl);
  profileAvatarCropState.objectUrl = nextUrl;
  profileAvatarCropState.hasImage = false;
  els.image.onload = () => {
    profileAvatarCropState.naturalWidth = els.image.naturalWidth || 1;
    profileAvatarCropState.naturalHeight = els.image.naturalHeight || 1;
    profileAvatarCropState.zoom = 1;
    profileAvatarCropState.offsetX = 0;
    profileAvatarCropState.offsetY = 0;
    profileAvatarCropState.hasImage = true;
    if (els.zoom) els.zoom.value = "1";
    els.cropper.hidden = false;
    requestAnimationFrame(renderProfileAvatarCropper);
  };
  els.image.onerror = () => {
    resetProfileAvatarCropper();
    profileAvatarSetMsg("無法讀取頭像預覽，請換一張圖片", true);
  };
  els.image.src = nextUrl;
}

function closeProfileAvatarUploader() {
  const { overlay } = profileAvatarCropperElements();
  if (overlay) {
    overlay.classList.remove("show");
    overlay.setAttribute("aria-hidden", "true");
  }
  resetProfileAvatarCropper();
  profileAvatarSetMsg("");
}

function openProfileAvatarUploader({ pickFile = false } = {}) {
  const els = profileAvatarCropperElements();
  if (!els.overlay) return;
  resetProfileAvatarCropper();
  profileAvatarSetMsg("");
  els.overlay.classList.add("show");
  els.overlay.setAttribute("aria-hidden", "false");
  if (pickFile && els.file && typeof els.file.click === "function") {
    els.file.click();
  } else if (els.file) {
    els.file.focus();
  }
}

function handleProfileAvatarPointerStart(event) {
  const { stage } = profileAvatarCropperElements();
  if (!stage || !profileAvatarCropState.hasImage) return;
  event.preventDefault();
  profileAvatarCropState.dragging = true;
  profileAvatarCropState.pointerId = event.pointerId;
  profileAvatarCropState.startX = event.clientX;
  profileAvatarCropState.startY = event.clientY;
  profileAvatarCropState.startOffsetX = profileAvatarCropState.offsetX;
  profileAvatarCropState.startOffsetY = profileAvatarCropState.offsetY;
  stage.classList.add("is-dragging");
  if (typeof stage.setPointerCapture === "function") stage.setPointerCapture(event.pointerId);
}

function handleProfileAvatarPointerMove(event) {
  if (!profileAvatarCropState.dragging || event.pointerId !== profileAvatarCropState.pointerId) return;
  event.preventDefault();
  profileAvatarCropState.offsetX = profileAvatarCropState.startOffsetX + (event.clientX - profileAvatarCropState.startX);
  profileAvatarCropState.offsetY = profileAvatarCropState.startOffsetY + (event.clientY - profileAvatarCropState.startY);
  renderProfileAvatarCropper();
}

function handleProfileAvatarPointerEnd(event) {
  const { stage } = profileAvatarCropperElements();
  if (!profileAvatarCropState.dragging || event.pointerId !== profileAvatarCropState.pointerId) return;
  profileAvatarCropState.dragging = false;
  profileAvatarCropState.pointerId = null;
  if (stage) stage.classList.remove("is-dragging");
}

async function uploadProfileAvatar() {
  const file = $("profile-avatar-file")?.files?.[0] || null;
  if (!currentUserId) {
    profileAvatarSetMsg("尚未登入，無法更新頭像", true);
    return;
  }
  if (!file) {
    profileAvatarSetMsg("請先選擇頭像圖片", true);
    return;
  }
  const button = $("profile-avatar-upload-btn");
  const previousText = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "上傳中...";
  }
  try {
    const crop = currentProfileAvatarCropPayload();
    const form = new FormData();
    form.append("file", file);
    form.append("crop_json", JSON.stringify(crop));
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + `/admin/users/${encodeURIComponent(currentUserId)}/avatar`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" },
      body: form,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    if (profilePanelCache) profilePanelCache.avatar_file_id = json.avatar_file_id || "";
    if (typeof markUserAvatarUpdated === "function") markUserAvatarUpdated(currentUserId, json.avatar_file_id || "");
    profileAvatarSetMsg("頭像已更新");
    await loadMyProfile({ quiet: true });
    closeProfileAvatarUploader();
    profileSetMsg("頭像已更新");
  } catch (err) {
    profileAvatarSetMsg(err.message || "頭像上傳失敗", true);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = previousText || "上傳頭像";
    }
  }
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
  if (targetId === "profile-home-avatar") {
    el.title = "點擊上傳或更換頭像";
    el.setAttribute("aria-label", "上傳或更換頭像");
  }
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

function bindProfileAvatarUploaderControls() {
  if (window.__profileAvatarUploaderBound) return;
  window.__profileAvatarUploaderBound = true;
  const els = profileAvatarCropperElements();
  if (els.file) {
    els.file.addEventListener("change", () => loadProfileAvatarFile(els.file.files?.[0] || null));
  }
  if (els.stage) {
    els.stage.addEventListener("pointerdown", handleProfileAvatarPointerStart);
    els.stage.addEventListener("pointermove", handleProfileAvatarPointerMove);
    els.stage.addEventListener("pointerup", handleProfileAvatarPointerEnd);
    els.stage.addEventListener("pointercancel", handleProfileAvatarPointerEnd);
  }
  if (els.zoom) {
    els.zoom.addEventListener("input", () => {
      profileAvatarCropState.zoom = profileAvatarClamp(parseFloat(els.zoom.value || "1") || 1, PROFILE_AVATAR_CROPPER_MIN_ZOOM, PROFILE_AVATAR_CROPPER_MAX_ZOOM);
      renderProfileAvatarCropper();
    });
  }
  if (els.center) {
    els.center.addEventListener("click", () => {
      profileAvatarCropState.zoom = 1;
      profileAvatarCropState.offsetX = 0;
      profileAvatarCropState.offsetY = 0;
      if (els.zoom) els.zoom.value = "1";
      renderProfileAvatarCropper();
    });
  }
  const upload = $("profile-avatar-upload-btn");
  if (upload) upload.addEventListener("click", uploadProfileAvatar);
  const cancel = $("profile-avatar-cancel-btn");
  if (cancel) cancel.addEventListener("click", closeProfileAvatarUploader);
  if (els.overlay) {
    els.overlay.addEventListener("click", (event) => {
      if (event.target === els.overlay) closeProfileAvatarUploader();
    });
  }
  window.addEventListener("resize", () => {
    if (profileAvatarCropState.hasImage) requestAnimationFrame(renderProfileAvatarCropper);
  }, { passive: true });
  window.addEventListener("keydown", (event) => {
    const overlay = $("profile-avatar-overlay");
    if (event.key === "Escape" && overlay && overlay.classList.contains("show")) {
      closeProfileAvatarUploader();
    }
  });
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
  const avatarButton = $("profile-home-avatar");
  if (avatarButton) avatarButton.addEventListener("click", () => openProfileAvatarUploader({ pickFile: true }));
  bindProfileAvatarUploaderControls();
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
