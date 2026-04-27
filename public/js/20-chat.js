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
  if (roomTitle) {
    const lock = target.is_private ? "🔒 " : "";
    roomTitle.textContent = `${lock}${target.name}（#${target.id}）`;
  }
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

async function deleteChatMessage(messageId) {
  if (!messageId) return;
  if (!confirm("確定要刪除此留言嗎？")) return;
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
