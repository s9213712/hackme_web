'use strict';

let webTerminalSocket = null;
let webTerminalPollTimer = null;
let webTerminalActiveSessionId = "";
let webTerminalXterm = null;

function webTerminalWrite(text) {
  if (webTerminalXterm) {
    webTerminalXterm.write(String(text || "").replaceAll("\n", "\r\n"));
    return;
  }
  const out = $("web-terminal-output");
  if (!out) return;
  out.textContent += String(text || "");
  out.scrollTop = out.scrollHeight;
}

function webTerminalSetMessage(message, ok = true) {
  const msg = $("web-terminal-msg");
  if (!msg) return;
  msg.textContent = message || "";
  msg.style.color = ok ? "var(--muted)" : "#ff6b7a";
}

function webTerminalRenderHealth(health) {
  const box = $("web-terminal-health");
  if (!box) return;
  const rows = (health && health.checks) || [];
  if (!rows.length) {
    box.innerHTML = '<div class="drive-empty">尚無環境檢查資料</div>';
    return;
  }
  box.innerHTML = rows.map((row) => `
    <div class="drive-file-row">
      <div style="min-width:0;">
        <strong>${escapeHtml(row.name || "-")}</strong>
        <div class="drive-card-sub">${escapeHtml(row.message || "")}</div>
      </div>
      <span class="pill ${row.ok ? "pill-ok" : "pill-danger"}">${row.ok ? "ok" : "fail"}</span>
    </div>
  `).join("");
}

function webTerminalRenderSessions(sessions) {
  const select = $("web-terminal-session-select");
  if (!select) return;
  const active = webTerminalActiveSessionId || select.value || "";
  select.innerHTML = '<option value="">尚無 session</option>' + (sessions || []).map((session) => `
    <option value="${escapeHtml(session.session_id)}">${escapeHtml(session.vm_name)} · ${escapeHtml(session.status)}</option>
  `).join("");
  if (active && Array.from(select.options).some((opt) => opt.value === active)) select.value = active;
}

async function loadWebTerminalQemu() {
  if (currentUser !== "root") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const status = $("web-terminal-status");
  if (status) status.textContent = "檢查中...";
  try {
    const res = await fetch(API + "/root/web-terminal/qemu/health", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" },
    });
    const json = await res.json().catch(() => ({}));
    webTerminalRenderHealth(json.health);
    if (status) {
      status.textContent = json.ok ? "環境可用" : "環境未完成";
      status.style.color = json.ok ? "#66d37e" : "#ffbd5a";
    }
    if (!json.ok) webTerminalSetMessage("WebTerminal 尚不能啟動，請依檢查結果執行安裝腳本或修正權限。", false);
  } catch (err) {
    if (status) status.textContent = "環境檢查失敗";
    webTerminalSetMessage("Web Terminal 環境檢查失敗：" + err.message, false);
  }
  await refreshWebTerminalSessions();
}

async function refreshWebTerminalSessions() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/root/web-terminal/qemu/sessions", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) webTerminalRenderSessions(json.sessions || []);
}

async function startWebTerminalQemu() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const out = $("web-terminal-output");
  if (out) out.textContent = "";
  webTerminalWrite("正在建立隔離 VM session...\n");
  const res = await fetch(API + "/root/web-terminal/qemu/sessions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({}),
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    webTerminalRenderHealth(json.health);
    webTerminalSetMessage(json.msg || `啟動失敗（HTTP ${res.status}）`, false);
    return;
  }
  webTerminalActiveSessionId = json.session.session_id;
  webTerminalSetMessage("VM 建立中，等待 ready 後會自動連線。");
  await refreshWebTerminalSessions();
  pollWebTerminalSession(webTerminalActiveSessionId);
}

function pollWebTerminalSession(sessionId) {
  clearInterval(webTerminalPollTimer);
  webTerminalPollTimer = setInterval(async () => {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await fetch(API + "/root/web-terminal/qemu/sessions/" + encodeURIComponent(sessionId), {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" },
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok || !json.session) return;
    webTerminalWrite(`[${json.session.status}] ${json.session.message || ""}\n`);
    await refreshWebTerminalSessions();
    if (json.session.status === "ready") {
      clearInterval(webTerminalPollTimer);
      if (json.session.ip_address) connectWebTerminalSocket(sessionId);
      else webTerminalSetMessage("VM 已啟動，但目前網路模式無 IP；請改用 NAT 模式後重開 session。", false);
    }
    if (json.session.status === "failed" || json.session.status === "closed") {
      clearInterval(webTerminalPollTimer);
      webTerminalSetMessage(json.session.message || "Session 已結束", false);
    }
  }, 2500);
}

function connectWebTerminalSocket(sessionId) {
  if (webTerminalSocket) webTerminalSocket.close();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  webTerminalSocket = new WebSocket(`${proto}//${location.host}/api/root/web-terminal/qemu/sessions/${encodeURIComponent(sessionId)}/ws`);
  webTerminalSocket.onopen = () => webTerminalSetMessage("Terminal 已連線。");
  webTerminalSocket.onmessage = (event) => webTerminalWrite(event.data || "");
  webTerminalSocket.onclose = () => webTerminalSetMessage("Web Terminal session 已關閉", false);
}

async function closeWebTerminalQemu() {
  const sessionId = $("web-terminal-session-select")?.value || webTerminalActiveSessionId;
  if (!sessionId) return webTerminalSetMessage("沒有可關閉的 session。", false);
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/root/web-terminal/qemu/sessions/" + encodeURIComponent(sessionId), {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return webTerminalSetMessage(json.msg || `關閉失敗（HTTP ${res.status}）`, false);
  if (webTerminalSocket) webTerminalSocket.close();
  webTerminalActiveSessionId = "";
  webTerminalSetMessage("Session 已關閉。");
  await refreshWebTerminalSessions();
}

function setupWebTerminalInput() {
  const box = $("web-terminal-box");
  if (!box) return;
  if (window.Terminal) {
    webTerminalXterm = new window.Terminal({ cursorBlink: true, convertEol: true, fontSize: 13 });
    box.innerHTML = "";
    webTerminalXterm.open(box);
    webTerminalXterm.onData((data) => {
      if (webTerminalSocket && webTerminalSocket.readyState === WebSocket.OPEN) webTerminalSocket.send(data);
    });
    return;
  }
  box.tabIndex = 0;
  box.addEventListener("keydown", (event) => {
    if (!webTerminalSocket || webTerminalSocket.readyState !== WebSocket.OPEN) return;
    if (event.key.length === 1) webTerminalSocket.send(event.key);
    if (event.key === "Enter") webTerminalSocket.send("\r");
    if (event.key === "Backspace") webTerminalSocket.send("\x7f");
    event.preventDefault();
  });
}

