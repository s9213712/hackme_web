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

function renderCaptchaChallenge(captcha) {
  const field = $("captcha-field");
  const question = $("captcha-question");
  const image = $("captcha-image");
  const answer = $("captcha-answer");
  const idInput = $("captcha-id");
  const hint = $("captcha-hint");
  if (!field) return;
  const mode = captcha?.mode || "none";
  if (!captcha?.required || mode === "none") {
    field.style.display = "none";
    if (idInput) idInput.value = "";
    if (answer) answer.value = "";
    return;
  }
  field.style.display = "block";
  if (idInput) idInput.value = captcha.captcha_id || "";
  if (answer) answer.value = "";
  if (question) {
    if (mode === "turnstile") question.textContent = "Turnstile 驗證已啟用，請使用部署的 Turnstile widget 完成驗證。";
    else question.textContent = captcha.question || "請完成驗證";
  }
  if (image) {
    if (captcha.image_data_uri) {
      image.src = captcha.image_data_uri;
      image.style.display = "block";
    } else {
      image.removeAttribute("src");
      image.style.display = "none";
    }
  }
  if (hint) {
    if (mode === "turnstile") {
      hint.textContent = captcha.site_key ? "服務端仍需 TURNSTILE_SECRET_KEY；未設定時註冊會提示 root 調整。" : "尚未設定 Turnstile site key。";
    } else {
      hint.textContent = captcha.expires_at ? "驗證碼會過期，送出前若失敗請重新取得。" : "";
    }
  }
}

async function loadCaptchaChallenge() {
  try {
    const res = await fetch(API + "/captcha/challenge", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (json.ok) renderCaptchaChallenge(json.captcha || { required: false, mode: "none" });
  } catch (_) {
    const hint = $("captcha-hint");
    if (hint) hint.textContent = "目前無法取得驗證碼，請稍後重試。";
  }
}

async function forceDefaultPasswordChange() {
  if (!currentUserId) return;
  forcedPasswordChangeMode = true;
  await editUser(currentUserId);
  setUserEditMsg("此預設帳號初次登入必須先變更密碼。請輸入目前密碼與新密碼，變更完成後請用新密碼重新登入。", false);
  const cancelBtn = $("user-edit-cancel");
  if (cancelBtn) cancelBtn.style.display = "none";
  const currentPasswordInput = $("edit-user-current-pw");
  if (currentPasswordInput) currentPasswordInput.focus();
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
        captcha_id: $("captcha-id")?.value || "",
        captcha_answer: $("captcha-answer")?.value || "",
        captcha_turnstile_token: $("captcha-turnstile-token")?.value || "",
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
      loadCaptchaChallenge();
    }
  } catch (e) {
    flash($("reg-msg"), "網路錯誤，請稍後再試", false);
    loadCaptchaChallenge();
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
    avatar_file_id: source.avatar_file_id || "",
    avatar_crop: source.avatar_crop || {},
    role: source.role || "user",
    status: source.status || "active",
    base_level: source.base_level || source.member_level || "normal",
    effective_level: source.effective_level || source.base_level || source.member_level || "normal",
    sanction_status: source.sanction_status || "none",
    sanction_until: source.sanction_until || ""
  };

  editingUserId = userId;
  editingUserOriginal.nickname = current.nickname;
  editingUserOriginal.real_name = current.real_name;
  editingUserOriginal.id_number = current.id_number;
  editingUserOriginal.birthdate = current.birthdate;
  editingUserOriginal.phone = current.phone;
  editingUserOriginal.role = current.role;
  editingUserOriginal.status = current.status;
  editingUserOriginal.base_level = current.base_level;
  editingUserOriginal.sanction_status = current.sanction_status;
  editingUserOriginal.sanction_until = current.sanction_until;

  const usernameEl = $("user-edit-username");
  if (usernameEl) usernameEl.textContent = current.username || String(userId);
  const memberLevelEl = $("user-edit-member-level");
  if (memberLevelEl) {
    memberLevelEl.textContent = current.base_level === current.effective_level
      ? current.effective_level
      : `${current.effective_level}（原始等級：${current.base_level}）`;
  }
  setUserEditField("edit-user-nickname", current.nickname);
  setUserEditField("edit-user-realname", current.real_name);
  setUserEditField("edit-user-idno", current.id_number);
  setUserEditField("edit-user-birthdate", current.birthdate);
  setUserEditField("edit-user-phone", current.phone);
  setUserEditField("edit-avatar-crop-x", current.avatar_crop.x ?? 0);
  setUserEditField("edit-avatar-crop-y", current.avatar_crop.y ?? 0);
  setUserEditField("edit-avatar-crop-width", current.avatar_crop.width ?? 0);
  setUserEditField("edit-avatar-crop-height", current.avatar_crop.height ?? 0);
  setUserEditField("edit-user-avatar-file", "");
  const avatarStatus = $("edit-user-avatar-status");
  if (avatarStatus) avatarStatus.textContent = current.avatar_file_id ? `目前頭像 file_id: ${current.avatar_file_id}` : "尚未設定頭像";
  const editRole = $("edit-user-role");
  if (editRole) editRole.value = current.role;
  const editStatus = $("edit-user-status");
  if (editStatus) editStatus.value = current.status;
  const roleField = $("edit-user-role-field");
  const statusField = $("edit-user-status-field");
  const currentPwField = $("edit-user-current-pw-field");
  if (roleField) roleField.style.display = editingUserIsSelf || !canManageUsers ? "none" : "";
  if (statusField) statusField.style.display = editingUserIsSelf || !canManageUsers ? "none" : "";
  if (currentPwField) currentPwField.style.display = editingUserIsSelf ? "" : "none";
  const memberFields = $("edit-user-member-level-fields");
  if (memberFields) memberFields.style.display = editingUserIsSelf || currentUser !== "root" ? "none" : "";
  setUserEditField("edit-user-base-level", current.base_level);
  setUserEditField("edit-user-sanction-status", current.sanction_status);
  setUserEditField("edit-user-sanction-until", current.sanction_until ? current.sanction_until.slice(0, 16) : "");
  setUserEditField("edit-user-level-reason", "");
  const cancelBtn = $("user-edit-cancel");
  if (cancelBtn) cancelBtn.style.display = forcedPasswordChangeMode ? "none" : "";
  setUserEditField("edit-user-current-pw", "");
  setUserEditField("edit-user-pw", "");
  setUserEditField("edit-user-pw-confirm", "");
  setUserEditMsg("");

  const overlay = $("user-edit-overlay");
  if (overlay) overlay.classList.add("show");
  const firstField = $("edit-user-nickname");
  if (firstField) firstField.focus();
}

async function uploadUserAvatar() {
  if (!editingUserId) return;
  const input = $("edit-user-avatar-file");
  const file = input?.files?.[0];
  if (!file) {
    setUserEditMsg("請先選擇頭像檔案", false);
    return;
  }
  const crop = {
    x: parseInt($("edit-avatar-crop-x")?.value || "0", 10) || 0,
    y: parseInt($("edit-avatar-crop-y")?.value || "0", 10) || 0,
    width: parseInt($("edit-avatar-crop-width")?.value || "0", 10) || 0,
    height: parseInt($("edit-avatar-crop-height")?.value || "0", 10) || 0,
  };
  const form = new FormData();
  form.append("file", file);
  form.append("crop_json", JSON.stringify(crop));
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/admin/users/${editingUserId}/avatar`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  const status = $("edit-user-avatar-status");
  if (json && json.ok) {
    if (status) status.textContent = `頭像已更新 file_id: ${json.avatar_file_id}`;
    setUserEditMsg("頭像已更新", true);
    if (["manager", "super_admin"].includes(currentRole)) loadUsers();
  } else {
    setUserEditMsg(json.msg || "頭像上傳失敗", false);
  }
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
  const baseLevel = $("edit-user-base-level")?.value || "";
  const sanctionStatus = $("edit-user-sanction-status")?.value || "none";
  const sanctionUntil = $("edit-user-sanction-until")?.value || "";
  const levelReason = $("edit-user-level-reason")?.value.trim() || "";
  const currentPassword = $("edit-user-current-pw")?.value || "";
  const password = $("edit-user-pw")?.value || "";
  const passwordConfirm = $("edit-user-pw-confirm")?.value || "";

  if (nickname !== editingUserOriginal.nickname) payload.nickname = nickname;
  if (realName !== editingUserOriginal.real_name) payload.real_name = realName;
  if (idNo !== editingUserOriginal.id_number) payload.id_number = idNo;
  if (birthdate !== editingUserOriginal.birthdate) payload.birthdate = birthdate;
  if (phone !== editingUserOriginal.phone) payload.phone = phone;
  if (!editingUserIsSelf && canManageUsers && role !== editingUserOriginal.role) payload.role = role;
  if (!editingUserIsSelf && canManageUsers && status !== editingUserOriginal.status) payload.status = status;
  if (!editingUserIsSelf && currentUser === "root") {
    if (baseLevel && baseLevel !== editingUserOriginal.base_level) payload.base_level = baseLevel;
    if (sanctionStatus !== editingUserOriginal.sanction_status) payload.sanction_status = sanctionStatus;
    const normalizedOriginalUntil = (editingUserOriginal.sanction_until || "").slice(0, 16);
    if (sanctionUntil !== normalizedOriginalUntil) payload.sanction_until = sanctionUntil ? new Date(sanctionUntil).toISOString() : "";
    if (payload.base_level || payload.sanction_status || Object.prototype.hasOwnProperty.call(payload, "sanction_until")) {
      payload.level_update_reason = levelReason || "root manual member level update";
    }
  }

  if (password || passwordConfirm) {
    if (password !== passwordConfirm) {
      setUserEditMsg("兩次密碼輸入不一致", false);
      return;
    }
    if (!password) {
      setUserEditMsg("若要修改密碼，兩次都要輸入", false);
      return;
    }
    if (editingUserIsSelf && !currentPassword) {
      setUserEditMsg("修改自己的密碼時必須輸入目前密碼", false);
      return;
    }
    payload.password = password;
    payload.password_confirm = passwordConfirm;
    if (editingUserIsSelf) payload.current_password = currentPassword;
  }

  if (forcedPasswordChangeMode && !payload.password) {
    setUserEditMsg("初次登入必須設定新密碼", false);
    return;
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
    if (forcedPasswordChangeMode) {
      forcedPasswordChangeMode = false;
      currentMustChangePassword = false;
      alert("密碼已更新，請使用新密碼重新登入。");
      resetAuthState();
      return;
    }
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
    hideAdminAddDialog();
    loadUsers();
  } else {
    flash($("li-msg"), json.msg || "建立帳號失敗", false);
  }
}

function showAdminAddDialog() {
  const overlay = $("admin-add-overlay");
  if (!overlay) return;
  overlay.classList.add("show");
  const firstField = $("admin-add-user");
  if (firstField) firstField.focus();
}

function hideAdminAddDialog() {
  const overlay = $("admin-add-overlay");
  if (!overlay) return;
  overlay.classList.remove("show");
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

async function bulkReviewRegistrations(action) {
  const ids = [...selectedPendingUserIds];
  if (!ids.length) return;
  const label = action === "approve" ? "核准" : "駁回";
  if (!confirm(`確定要${label}這 ${ids.length} 筆註冊申請？`)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  let success = 0;
  let failed = 0;
  for (const userId of ids) {
    try {
      const res = await fetch(API + `/admin/users/${userId}/review-registration`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
        body: JSON.stringify({ action })
      });
      const json = await res.json().catch(() => ({}));
      if (json && json.ok) success += 1;
      else failed += 1;
    } catch (_) {
      failed += 1;
    }
  }
  selectedPendingUserIds.clear();
  await loadUsers();
  if (failed === 0) {
    flash($("li-msg"), `${label}完成，共 ${success} 筆`, true);
  } else {
    flash($("li-msg"), `${label}完成 ${success} 筆，失敗 ${failed} 筆`, false);
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

async function updateUserMemberLevel(userId, username) {
  const select = $(`member-level-select-${userId}`);
  const level = select?.value || "";
  if (!["newbie", "normal", "trusted", "vip"].includes(level)) {
    alert("請選擇有效的一般會員等級");
    return;
  }
  if (!confirm(`確定要將「${username}」的會員等級調整為 ${level}？`)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/admin/users/${userId}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({
      base_level: level,
      level_update_reason: `admin member level change to ${level}`
    })
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    await loadUsers();
    return;
  }
  alert(json.msg || "會員等級更新失敗");
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
