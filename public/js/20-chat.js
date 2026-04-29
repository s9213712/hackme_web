const CHAT_STICKER_LABELS = {
  smile: "微笑 :)",
  thanks: "感謝 THX",
  ok: "了解 OK",
  wow: "驚訝 WOW",
  cheer: "加油 GO",
  sad: "難過 :("
};
let pendingChatAttachments = [];

function chatStickerLabel(key, sticker) {
  return (sticker && (sticker.label || sticker.glyph)) || CHAT_STICKER_LABELS[key] || "表情包";
}

function chatAttachmentName(item) {
  return item?.original_filename_plain_for_public || item?.display_name || item?.file_id || "附件";
}

function renderPendingChatAttachments() {
  const list = $("chat-pending-attachment-list");
  if (!list) return;
  if (!pendingChatAttachments.length) {
    list.innerHTML = `<div class="drive-empty">尚未選擇要隨訊息送出的附件</div>`;
    return;
  }
  list.innerHTML = pendingChatAttachments.map((item) => `
    <div class="chat-pending-attachment">
      <span>${sanitize(chatAttachmentName(item))}</span>
      <button class="btn btn-danger chat-sticker-btn" type="button" data-remove-chat-pending-attachment="${sanitize(item.file_id || "")}">刪除</button>
    </div>
  `).join("");
}

function removePendingChatAttachment(fileId) {
  const target = String(fileId || "");
  if (!target) return;
  pendingChatAttachments = pendingChatAttachments.filter((item) => String(item.file_id || "") !== target);
  renderPendingChatAttachments();
}

function handlePendingChatAttachmentClick(event) {
  const btn = event.target?.closest?.("[data-remove-chat-pending-attachment]");
  if (!btn) return;
  event.preventDefault();
  event.stopPropagation();
  removePendingChatAttachment(btn.getAttribute("data-remove-chat-pending-attachment") || "");
}

function addPendingChatAttachment(file) {
  const fileId = file?.file_id || file?.id || "";
  if (!fileId) return;
  if (pendingChatAttachments.some((item) => item.file_id === fileId)) {
    renderPendingChatAttachments();
    return;
  }
  pendingChatAttachments.push({ ...file, file_id: fileId });
  renderPendingChatAttachments();
}

document.addEventListener("click", (event) => {
  const list = $("chat-pending-attachment-list");
  if (list?.contains(event.target)) handlePendingChatAttachmentClick(event);
});

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
    loadChatFriends().catch(() => {});
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

function renderChatFriends(data) {
  const list = $("chat-friend-list");
  if (!list) return;
  const friends = Array.isArray(data?.friends) ? data.friends : [];
  const incoming = Array.isArray(data?.incoming) ? data.incoming : [];
  const outgoing = Array.isArray(data?.outgoing) ? data.outgoing : [];
  const rows = [];
  incoming.forEach((item) => {
    rows.push(`
      <div class="chat-friend-row">
        <span>邀請：<strong>${sanitize(item.other_username || "-")}</strong></span>
        <span>
          <button class="btn chat-sticker-btn" type="button" data-friend-review="${item.id}" data-decision="accept">接受</button>
          <button class="btn chat-sticker-btn" type="button" data-friend-review="${item.id}" data-decision="reject">拒絕</button>
        </span>
      </div>
    `);
  });
  friends.forEach((item) => {
    rows.push(`
      <div class="chat-friend-row">
        <strong>${sanitize(item.other_username || "-")}</strong>
        <span>
          <button class="btn chat-sticker-btn" type="button" data-friend-pm="${sanitize(item.other_username || "")}">私訊</button>
          <button class="btn chat-sticker-btn" type="button" data-friend-remove="${item.other_user_id}">解除</button>
        </span>
      </div>
    `);
  });
  outgoing.forEach((item) => {
    rows.push(`<div class="chat-friend-row"><span>等待 ${sanitize(item.other_username || "-")} 回覆</span><span></span></div>`);
  });
  list.innerHTML = rows.length ? rows.join("") : `<div class="drive-card-sub">尚無好友</div>`;
  list.querySelectorAll("[data-friend-review]").forEach((btn) => {
    btn.addEventListener("click", () => reviewChatFriendRequest(btn.dataset.friendReview, btn.dataset.decision));
  });
  list.querySelectorAll("[data-friend-pm]").forEach((btn) => {
    btn.addEventListener("click", () => openPmWithUser(btn.dataset.friendPm || ""));
  });
  list.querySelectorAll("[data-friend-remove]").forEach((btn) => {
    btn.addEventListener("click", () => removeChatFriend(btn.dataset.friendRemove));
  });
}

async function loadChatFriends() {
  if (!currentUser) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/chat/friends", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) renderChatFriends(json);
}

async function addChatFriend() {
  const input = $("chat-friend-username");
  const username = (input?.value || "").trim();
  if (!username) {
    setChatMsg("chat-room-warn", "請輸入好友帳號", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/chat/friends/requests", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ username })
  });
  const json = await res.json().catch(() => ({}));
  setChatMsg("chat-room-warn", json.msg || (json.ok ? "好友邀請已送出" : "好友邀請失敗"), !!json.ok);
  if (json.ok) {
    if (input) input.value = "";
    await loadChatFriends();
  }
}

async function reviewChatFriendRequest(requestId, decision) {
  if (!requestId || !decision) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/friends/requests/${encodeURIComponent(requestId)}/${encodeURIComponent(decision)}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  setChatMsg("chat-room-warn", json.msg || "好友邀請已處理", !!json.ok);
  if (json.ok) await loadChatFriends();
}

async function removeChatFriend(friendUserId) {
  if (!friendUserId) return;
  if (!confirm("確定解除好友？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/friends/${encodeURIComponent(friendUserId)}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  setChatMsg("chat-room-warn", json.msg || "好友已更新", !!json.ok);
  if (json.ok) await loadChatFriends();
}

async function openChatRoom(roomId, autoPoll = true) {
  const id = Number(roomId);
  if (!Number.isFinite(id) || id <= 0) return;
  const target = chatRooms.find((r) => Number(r.id) === id);
  if (!target) return;
  selectedChatRoomId = id;
  renderChatRooms();
  const roomTitle = $("chat-room-title");
  if (roomTitle) {
    const lock = target.is_private ? "🔒 " : "";
    roomTitle.textContent = `${lock}${target.name}（#${target.id}）`;
  }
  const member = $("chat-room-member");
  if (member) member.textContent = `持有者：${target.owner_username || "未知"}`;
  await loadChatMessages(id, false);
  if (typeof loadContextAttachments === "function") {
    await loadContextAttachments("group_chat", id, "chat-attachment-list");
  }
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
      if (title) {
        const lock = json.room.is_private ? "🔒 " : "";
        title.textContent = `${lock}${json.room.name}（#${json.room.id}）`;
      }
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

  if (!name && !targetUser) {
    setChatMsg("chat-room-warn", "請輸入聊天室名稱或指定對象", false);
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
    body: JSON.stringify({ name: name || null, target_user: targetUser || null })
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
      const inviteInfo = json.room.target_username ? `（與 ${sanitize(json.room.target_username)} 的私訊）` : "";
      const roomType = json.room.is_private ? "私人訊息聊天室" : "聊天室";
      setChatMsg("chat-room-warn", `${roomType}建立完成${inviteInfo}`, true);
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
  const attachmentFileIds = pendingChatAttachments.map((item) => item.file_id).filter(Boolean);
  if (!content && !attachmentFileIds.length) {
    setChatMsg("chat-room-warn", "訊息或附件不可為空", false);
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
    body: JSON.stringify({ content, attachment_file_ids: attachmentFileIds, csrf_token: csrf || "" })
  });
  const json = await res.json().catch(() => ({}));
  if (json && json.ok) {
    if (input) input.value = "";
    pendingChatAttachments = [];
    renderPendingChatAttachments();
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

async function sendChatSticker(stickerKey) {
  if (!selectedChatRoomId) {
    setChatMsg("chat-room-warn", "請先選擇聊天室", false);
    return;
  }
  if (!CHAT_STICKER_LABELS[stickerKey]) {
    setChatMsg("chat-room-warn", "不支援的表情包", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/rooms/${selectedChatRoomId}/messages`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ message_type: "sticker", sticker_key: stickerKey, csrf_token: csrf || "" })
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    setChatMsg("chat-room-warn", "表情包已送出", true);
    await loadChatMessages(selectedChatRoomId, true);
    startChatPoll();
    return;
  }
  setChatMsg("chat-room-warn", json.msg || "表情包發送失敗", false);
}

async function openPmWithUser(targetUsername) {
  // Switch to chat tab first
  const chatTab = $("tab-module-chat");
  if (chatTab) chatTab.click();
  // Fill in target and optionally auto-create PM room
  const targetInput = $("chat-room-target-user");
  const nameInput = $("chat-room-name");
  if (targetInput) targetInput.value = targetUsername;
  if (nameInput) nameInput.value = "";
  // Trigger create immediately (backend auto-finds or creates 1on1 room)
  await createChatRoom();
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

function canDeleteChatMessage(message) {
  if (!message || !message.id) return false;
  if (String(message.sender || "") === String(currentUser || "")) return true;
  const currentRoom = chatRooms.find((room) => Number(room.id) === Number(selectedChatRoomId));
  if (currentRoom && Number(currentRoom.owner_user_id) === Number(currentUserId)) return true;
  return clientRoleRank(currentRole || "user") >= clientRoleRank("manager");
}

function canDeleteChatRoom(room) {
  if (!room || !room.id) return false;
  if (String(currentUser || "") === "root") return true;
  if (Number(room.owner_user_id) === Number(currentUserId)) return true;
  if (String(room.owner_username || "") === "root") return false;
  return clientRoleRank(currentRole || "user") >= clientRoleRank("manager");
}

async function deleteChatRoom(roomId) {
  if (!roomId) return;
  const room = chatRooms.find((item) => Number(item.id) === Number(roomId));
  const label = room ? `${room.name}（#${room.id}）` : `#${roomId}`;
  if (!confirm(`確定要刪除此聊天室 ${label}？歷史資料會保留在資料庫與審計紀錄中。`)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/rooms/${encodeURIComponent(roomId)}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    setChatMsg("chat-room-warn", json.msg || "聊天室已刪除", true);
    if (Number(selectedChatRoomId) === Number(roomId)) {
      selectedChatRoomId = null;
      stopChatPoll();
      const memberLabel = $("chat-room-member");
      if (memberLabel) memberLabel.textContent = "";
      const title = $("chat-room-title");
      if (title) title.textContent = "請先建立或加入聊天室";
      const msgs = $("chat-room-messages");
      if (msgs) msgs.innerHTML = "<p style=\"color:var(--muted);\">尚未選擇聊天室</p>";
      const attachments = $("chat-attachment-list");
      if (attachments) attachments.innerHTML = "";
    }
    await loadChatRooms();
    return;
  }
  setChatMsg("chat-room-warn", json.msg || "刪除聊天室失敗", false);
}

async function deleteChatMessage(messageId, recall = false) {
  if (!messageId) return;
  if (!confirm(recall ? "確定要收回這則留言嗎？" : "確定要刪除此留言嗎？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/chat/messages/${messageId}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    setChatMsg("chat-room-warn", json.msg || "訊息已刪除", true);
    if (selectedChatRoomId) await loadChatMessages(selectedChatRoomId, true);
    return;
  }
  setChatMsg("chat-room-warn", json.msg || "刪除訊息失敗", false);
}
