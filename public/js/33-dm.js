'use strict';

function setDmMsg(text, ok) {
  const el = $("dm-warn");
  if (!el) return;
  el.textContent = text;
  el.className = "msg show " + (ok ? "ok" : "err");
}

function currentDmThread() {
  return dmThreads.find((thread) => Number(thread.id) === Number(selectedDmThreadId)) || null;
}

function renderDmThreads() {
  const wrap = $("dm-thread-list");
  if (!wrap) return;
  if (!dmThreads.length) {
    wrap.innerHTML = "<p style='color:var(--muted);'>尚無站內信</p>";
    return;
  }
  wrap.innerHTML = "";
  dmThreads.forEach((thread) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-room-item" + (Number(thread.id) === Number(selectedDmThreadId) ? " active" : "");
    const unread = Number(thread.unread_count || 0);
    btn.textContent = `${unread ? `(${unread}) ` : ""}${thread.other_username || "unknown"}`;
    btn.setAttribute("title", thread.last_message ? (thread.last_message.body || "") : "尚無訊息");
    btn.addEventListener("click", () => openDmThread(thread.id));
    wrap.appendChild(btn);
  });
}

function renderDmMessages(messages) {
  const list = $("dm-message-list");
  if (!list) return;
  const current = currentDmThread();
  const title = $("dm-thread-title");
  const blockBtn = $("dm-block-user-btn");
  if (title) title.textContent = current ? `與 ${current.other_username || "unknown"} 的站內信` : "請先選擇或建立私訊串";
  if (blockBtn) blockBtn.style.display = current ? "" : "none";
  if (!messages.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有訊息</p>";
    return;
  }
  list.innerHTML = messages.map((m) => {
    const cls = "chat-msg" + (m.is_self ? " self" : "");
    return `
      <div class="${cls}">
        <span class="meta">${sanitize(formatChatTime(m.created_at || ""))} · ${m.is_self ? "我" : sanitize(current?.other_username || "對方")}</span>
        ${sanitize(m.body || "")}
        <button class="chat-delete-btn" type="button" data-dm-delete="${m.id}">刪除</button>
      </div>
    `;
  }).join("");
  list.querySelectorAll("button[data-dm-delete]").forEach((btn) => {
    btn.addEventListener("click", () => deleteDmMessage(parseInt(btn.getAttribute("data-dm-delete"), 10)));
  });
  list.scrollTop = list.scrollHeight;
}

async function loadDmThreads() {
  if (!currentUser || !canAccessModule("dm")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/dm/threads", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    setDmMsg(json.msg || "站內信讀取失敗", false);
    return;
  }
  dmThreads = Array.isArray(json.threads) ? json.threads : [];
  if (selectedDmThreadId && !dmThreads.some((thread) => Number(thread.id) === Number(selectedDmThreadId))) {
    selectedDmThreadId = null;
  }
  renderDmThreads();
  if (selectedDmThreadId) loadDmMessages(selectedDmThreadId);
}

async function createDmThread() {
  const input = $("dm-target-user");
  const target = (input?.value || "").trim();
  if (!target) {
    setDmMsg("請輸入收件人帳號", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/dm/threads", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ target_username: target })
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    setDmMsg(json.msg || "建立站內信失敗", false);
    return;
  }
  if (input) input.value = "";
  selectedDmThreadId = json.thread?.id || null;
  setDmMsg("站內信已開啟", true);
  await loadDmThreads();
  if (selectedDmThreadId) await loadDmMessages(selectedDmThreadId);
}

async function openDmThread(threadId) {
  selectedDmThreadId = threadId;
  renderDmThreads();
  await loadDmMessages(threadId);
}

async function loadDmMessages(threadId) {
  if (!currentUser || !threadId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/dm/threads/${encodeURIComponent(threadId)}/messages`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    setDmMsg(json.msg || "訊息讀取失敗", false);
    return;
  }
  renderDmMessages(Array.isArray(json.messages) ? json.messages : []);
  await markDmThreadRead(threadId);
}

async function sendDmMessage() {
  if (!selectedDmThreadId) {
    setDmMsg("請先選擇站內信串", false);
    return;
  }
  const input = $("dm-message-input");
  const body = (input?.value || "").trim();
  if (!body) {
    setDmMsg("訊息不可為空", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/dm/threads/${encodeURIComponent(selectedDmThreadId)}/messages`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ body })
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    setDmMsg(json.msg || "送出失敗", false);
    return;
  }
  if (input) input.value = "";
  setDmMsg("已送出", true);
  await Promise.all([loadDmThreads(), loadDmMessages(selectedDmThreadId)]);
}

async function markDmThreadRead(threadId) {
  if (!threadId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  await fetch(API + `/dm/threads/${encodeURIComponent(threadId)}/read`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  }).catch(() => null);
}

async function deleteDmMessage(messageId) {
  if (!messageId || !confirm("確定要從你的視角刪除這則站內信？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/dm/messages/${encodeURIComponent(messageId)}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    setDmMsg(json.msg || "刪除失敗", false);
    return;
  }
  await loadDmMessages(selectedDmThreadId);
}

async function blockSelectedDmUser() {
  const thread = currentDmThread();
  if (!thread) return;
  if (!confirm(`確定要封鎖 ${thread.other_username}？封鎖後雙方無法新增站內信。`)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/dm/blocks", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ target_username: thread.other_username, reason: "user blocked from DM UI" })
  });
  const json = await res.json().catch(() => ({}));
  setDmMsg(json.msg || (json.ok ? "已封鎖" : "封鎖失敗"), !!json.ok);
}
