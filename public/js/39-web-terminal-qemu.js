'use strict';

let webTerminalSocket = null;
let webTerminalPollTimer = null;
let webTerminalActiveSessionId = "";
let webTerminalXterm = null;
let webTerminalFitAddon = null;
let webTerminalCols = 80;
let webTerminalRows = 24;
let webTerminalLastPollLine = "";
let webTerminalConfiguredRows = 51;
let webTerminalConfiguredCols = 209;
const WEB_TERMINAL_SIZE_KEY = "hackme_web_terminal_height";
const WEB_TERMINAL_RESIZE_PREFIX = "__hackme_terminal_resize__:";

function applyWebTerminalSize(value) {
  const box = $("web-terminal-box");
  if (!box) return;
  const selected = value || localStorage.getItem(WEB_TERMINAL_SIZE_KEY) || "420";
  const nextHeight = selected === "viewport" ? "calc(100vh - 220px)" : `${Math.max(280, parseInt(selected || "420", 10) || 420)}px`;
  box.style.height = nextHeight;
  box.style.minHeight = selected === "viewport" ? "520px" : "280px";
  box.style.maxHeight = selected === "viewport" ? "calc(100vh - 120px)" : "";
  box.style.overflow = "hidden";
  localStorage.setItem(WEB_TERMINAL_SIZE_KEY, selected);
  const select = $("web-terminal-size-select");
  if (select && select.value !== selected) select.value = selected;
  const fallback = $("web-terminal-output");
  if (fallback) {
    fallback.style.height = "100%";
    fallback.style.boxSizing = "border-box";
    fallback.style.overflow = "auto";
  }
  window.requestAnimationFrame(() => resizeWebTerminalViewport());
}

function scheduleWebTerminalResize() {
  resizeWebTerminalViewport();
  window.requestAnimationFrame(() => resizeWebTerminalViewport());
  window.setTimeout(() => resizeWebTerminalViewport(), 120);
  window.setTimeout(() => resizeWebTerminalViewport(), 500);
}

function applyConfiguredTerminalBoxSize(box, rows, cols) {
  if (!box || !rows) return;
  const styles = window.getComputedStyle(box);
  const measure = measureWebTerminalCell(box, styles);
  const fontSize = parseFloat(styles.fontSize || "13") || 13;
  const lineHeight = Math.max(14, Math.ceil(measure.height || fontSize * 1.35));
  const neededHeight = Math.max(280, Math.ceil(rows * lineHeight + 20));
  box.style.height = `${neededHeight}px`;
  box.style.minHeight = `${neededHeight}px`;
  box.style.maxHeight = "";
  box.style.overflow = "auto";
}

function resizeWebTerminalViewport() {
  const box = $("web-terminal-box");
  if (!box || !webTerminalXterm) return;
  if (webTerminalConfiguredRows && webTerminalConfiguredCols) {
    const rows = Math.max(12, Math.min(200, parseInt(webTerminalConfiguredRows, 10) || 51));
    const cols = Math.max(80, Math.min(400, parseInt(webTerminalConfiguredCols, 10) || 209));
    applyConfiguredTerminalBoxSize(box, rows, cols);
    webTerminalRows = rows;
    webTerminalCols = cols;
    if (typeof webTerminalXterm.resize === "function") {
      try {
        webTerminalXterm.resize(cols, rows);
      } catch (err) {}
    }
    applyConfiguredTerminalBoxSize(box, rows, cols);
    sendWebTerminalResize();
    return;
  }
  if (webTerminalFitAddon && typeof webTerminalFitAddon.fit === "function") {
    try {
      webTerminalFitAddon.fit();
      webTerminalCols = webTerminalXterm.cols || webTerminalCols;
      webTerminalRows = webTerminalXterm.rows || webTerminalRows;
      sendWebTerminalResize();
      return;
    } catch (err) {}
  }
  const styles = window.getComputedStyle(box);
  const measure = measureWebTerminalCell(box, styles);
  const fontSize = parseFloat(styles.fontSize || "13") || 13;
  const lineHeight = Math.max(14, Math.ceil(measure.height || fontSize * 1.45));
  const charWidth = Math.max(7, Math.ceil(measure.width || fontSize * 0.62));
  const boxWidth = Math.max(box.clientWidth, box.getBoundingClientRect().width || 0);
  const boxHeight = Math.max(box.clientHeight, box.getBoundingClientRect().height || 0);
  const cols = Math.max(80, Math.floor((boxWidth - 24) / charWidth));
  const rows = Math.max(12, Math.floor((boxHeight - 16) / lineHeight));
  webTerminalCols = cols;
  webTerminalRows = rows;
  if (typeof webTerminalXterm.resize === "function") {
    try {
      webTerminalXterm.resize(cols, rows);
    } catch (err) {}
  }
  if (typeof webTerminalXterm.refresh === "function") {
    try {
      webTerminalXterm.refresh(0, Math.max(0, webTerminalXterm.rows - 1));
    } catch (err) {}
  }
  sendWebTerminalResize();
}

function applyWebTerminalSessionConfig(session) {
  if (!session) return;
  if (session.terminal_rows) webTerminalConfiguredRows = session.terminal_rows;
  if (session.terminal_cols) webTerminalConfiguredCols = session.terminal_cols;
  scheduleWebTerminalResize();
}

function measureWebTerminalCell(box, boxStyles) {
  const xtermElement = box.querySelector(".xterm") || box;
  const charMeasure = box.querySelector(".xterm-char-measure-element");
  const charRect = charMeasure ? charMeasure.getBoundingClientRect() : null;
  if (charRect && charRect.width > 0 && charRect.height > 0) {
    return { width: charRect.width, height: charRect.height };
  }
  const span = document.createElement("span");
  const styles = window.getComputedStyle(xtermElement);
  span.textContent = "00000000000000000000";
  span.style.position = "absolute";
  span.style.visibility = "hidden";
  span.style.whiteSpace = "pre";
  span.style.fontFamily = styles.fontFamily || boxStyles.fontFamily || "monospace";
  span.style.fontSize = styles.fontSize || boxStyles.fontSize || "13px";
  span.style.fontWeight = styles.fontWeight || boxStyles.fontWeight || "400";
  span.style.lineHeight = styles.lineHeight || boxStyles.lineHeight || "normal";
  box.appendChild(span);
  const rect = span.getBoundingClientRect();
  span.remove();
  return {
    width: rect.width > 0 ? rect.width / span.textContent.length : 0,
    height: rect.height || 0,
  };
}

function sendWebTerminalResize() {
  if (!webTerminalSocket || webTerminalSocket.readyState !== WebSocket.OPEN) return;
  const rows = webTerminalXterm && webTerminalXterm.rows ? webTerminalXterm.rows : webTerminalRows;
  const cols = webTerminalXterm && webTerminalXterm.cols ? webTerminalXterm.cols : webTerminalCols;
  try {
    webTerminalSocket.send(WEB_TERMINAL_RESIZE_PREFIX + JSON.stringify({ rows, cols }));
  } catch (err) {}
}

function bindWebTerminalSizeControl() {
  const select = $("web-terminal-size-select");
  if (!select || select.dataset.webTerminalSizeBound === "1") return;
  select.dataset.webTerminalSizeBound = "1";
  select.addEventListener("change", () => applyWebTerminalSize(select.value));
  window.addEventListener("resize", () => scheduleWebTerminalResize());
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleWebTerminalResize();
  });
}

function webTerminalWrite(text) {
  if (webTerminalXterm) {
    webTerminalXterm.write(String(text || ""));
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
  const config = (health && health.config) || {};
  if (!rows.length) {
    box.innerHTML = '<div class="drive-empty">尚無環境檢查資料</div>';
    return;
  }
  if (health && health.ok) {
    box.innerHTML = '<div class="drive-empty">所有 WebTerminal 環境檢查已通過。</div>';
    return;
  }
  const configHtml = `
    <div class="drive-file-row" style="align-items:flex-start;">
      <div style="min-width:0;">
        <strong>目前檢查設定</strong>
        <div class="drive-card-sub">
          distro=${sanitize(config.distro || "-")} · network=${sanitize(config.network_mode || "-")} ·
          image=${sanitize(config.base_image || "-")} · vm_root=${sanitize(config.vm_root || "-")}
        </div>
      </div>
    </div>
  `;
  box.innerHTML = configHtml + rows.map((row) => {
    const message = row.message ? `<div class="drive-card-sub">${sanitize(row.message)}</div>` : "";
    const why = row.why ? `<div class="drive-card-sub"><strong>用途：</strong>${sanitize(row.why)}</div>` : "";
    const repair = !row.ok && row.repair ? `<div class="drive-card-sub" style="color:#ffd166;"><strong>修復：</strong><code>${sanitize(row.repair)}</code></div>` : "";
    return `
      <div class="drive-file-row" style="align-items:flex-start;">
        <div style="min-width:0;">
          <strong>${sanitize(row.label || row.name || "-")}</strong>
          <div class="drive-card-sub">${sanitize(row.name || "")}</div>
          ${message}
          ${why}
          ${repair}
        </div>
        <span class="pill ${row.ok ? "pill-ok" : "pill-danger"}">${row.ok ? "ok" : "fail"}</span>
      </div>
    `;
  }).join("");
}

function webTerminalRenderRequestFailure(error) {
  const box = $("web-terminal-health");
  if (!box) return;
  const target = `${location.origin}${API}/root/web-terminal/qemu/health`;
  const versionUrl = `${location.origin}${API}/version`;
  box.innerHTML = `
    <div class="drive-file-row" style="align-items:flex-start;">
      <div style="min-width:0;">
        <strong>Health API 請求沒有成功送達或沒有收到可讀回應</strong>
        <div class="drive-card-sub"><strong>目前頁面：</strong><code>${sanitize(location.href)}</code></div>
        <div class="drive-card-sub"><strong>檢查目標：</strong><code>${sanitize(target)}</code></div>
        <div class="drive-card-sub"><strong>錯誤：</strong>${sanitize(error && error.message ? error.message : String(error || "unknown error"))}</div>
      </div>
      <span class="pill pill-danger">fail</span>
    </div>
    <div class="drive-file-row" style="align-items:flex-start;">
      <div style="min-width:0;">
        <strong>常見原因</strong>
        <div class="drive-card-sub">1. server 沒在同一個網址/port 上運作，或剛好重啟中。</div>
        <div class="drive-card-sub">2. 瀏覽器仍載入舊 JS 快取，請用 <code>Ctrl + F5</code> 或開無痕視窗測試。</div>
        <div class="drive-card-sub">3. 登入 session / CSRF 狀態過期，請登出後重新登入 root。</div>
        <div class="drive-card-sub">4. 目前頁面是 HTTPS，但 server/API 是 HTTP，瀏覽器會擋 mixed content。</div>
        <div class="drive-card-sub">5. 瀏覽器外掛或代理阻擋了 <code>/api/root/web-terminal/qemu/health</code>。</div>
      </div>
    </div>
    <div class="drive-file-row" style="align-items:flex-start;">
      <div style="min-width:0;">
        <strong>手動確認</strong>
        <div class="drive-card-sub">先在同一個瀏覽器分頁打開：<code>${sanitize(versionUrl)}</code></div>
        <div class="drive-card-sub">若版本 API 打不開，就是 server/網址/port 問題；若版本 API 可開但 health 不行，請重新登入 root 後再試。</div>
      </div>
    </div>
  `;
}

function webTerminalRenderSessions(sessions) {
  const select = $("web-terminal-session-select");
  if (!select) return;
  const active = webTerminalActiveSessionId || select.value || "";
  select.innerHTML = '<option value="">尚無 session</option>' + (sessions || []).map((session) => `
    <option value="${sanitize(session.session_id)}">${sanitize(session.vm_name)} · ${sanitize(session.status)}</option>
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
    const rawText = await res.text();
    let json = {};
    try {
      json = rawText ? JSON.parse(rawText) : {};
    } catch (parseErr) {
      const preview = rawText ? rawText.slice(0, 500) : "(empty response)";
      if (status) {
        status.textContent = `環境檢查回應格式錯誤（HTTP ${res.status}）`;
        status.style.color = "#ff6b7a";
      }
      webTerminalRenderHealth(null);
      webTerminalSetMessage(`後端沒有回 JSON。HTTP ${res.status}。回應前 500 字：${preview}`, false);
      return;
    }
    webTerminalRenderHealth(json.health);
    const failed = json.health && Array.isArray(json.health.failed_checks) ? json.health.failed_checks : [];
    if (status) {
      status.textContent = json.ok ? "環境可用" : `環境未完成：${failed.length || "多"} 項需處理（HTTP ${res.status}）`;
      status.style.color = json.ok ? "#66d37e" : "#ffbd5a";
    }
    if (!json.ok) {
      const summary = json.health && json.health.summary ? json.health.summary : (json.msg || "WebTerminal 尚不能啟動");
      const failedText = failed.length ? `失敗項目：${failed.join(", ")}。` : "";
      webTerminalSetMessage(`${summary}。${failedText}請查看上方紅色項目的「修復」指令。`, false);
    }
  } catch (err) {
    if (status) {
      status.textContent = "環境檢查請求失敗";
      status.style.color = "#ff6b7a";
    }
    webTerminalRenderRequestFailure(err);
    webTerminalSetMessage("Web Terminal health API 沒有成功完成請求。請依上方「常見原因」與「手動確認」逐項排除。", false);
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
  if (json.ok) {
    webTerminalRenderSessions(json.sessions || []);
    if (!json.sessions || !json.sessions.some((session) => session.session_id === webTerminalActiveSessionId)) {
      webTerminalActiveSessionId = "";
    }
  }
}

async function startWebTerminalQemu() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const out = $("web-terminal-output");
  if (out) out.textContent = "";
  if (webTerminalSocket) {
    webTerminalSocket.close();
    webTerminalSocket = null;
  }
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
  applyWebTerminalSessionConfig(json.session);
  webTerminalSetMessage("VM 建立中，等待 ready 後會自動連線。");
  await refreshWebTerminalSessions();
  pollWebTerminalSession(webTerminalActiveSessionId);
}

function pollWebTerminalSession(sessionId) {
  clearInterval(webTerminalPollTimer);
  webTerminalLastPollLine = "";
  webTerminalPollTimer = setInterval(async () => {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await fetch(API + "/root/web-terminal/qemu/sessions/" + encodeURIComponent(sessionId), {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" },
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok || !json.session) return;
    applyWebTerminalSessionConfig(json.session);
    const pollLine = `[${json.session.status}] ${json.session.message || ""}`;
    if (pollLine !== webTerminalLastPollLine) {
      webTerminalLastPollLine = pollLine;
      webTerminalWrite(`${pollLine}\n`);
    } else {
      webTerminalSetMessage(pollLine || "VM 建立中...");
    }
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
  webTerminalSocket.onopen = () => {
    webTerminalSetMessage("Terminal 已連線。");
    scheduleWebTerminalResize();
  };
  webTerminalSocket.onmessage = (event) => webTerminalWrite(event.data || "");
  webTerminalSocket.onclose = async () => {
    webTerminalSetMessage("Web Terminal session 已關閉，VM 已排程清理。", false);
    webTerminalActiveSessionId = "";
    await refreshWebTerminalSessions();
  };
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
  bindWebTerminalSizeControl();
  applyWebTerminalSize();
  if (window.Terminal) {
    webTerminalXterm = new window.Terminal({
      cursorBlink: true,
      convertEol: false,
      fontFamily: "'Cascadia Mono', 'Cascadia Code', Consolas, 'Liberation Mono', Menlo, monospace",
      fontSize: 13,
      letterSpacing: 0,
      lineHeight: 1,
      termName: "xterm-256color",
      windowsMode: false,
    });
    if (window.FitAddon && typeof window.FitAddon.FitAddon === "function") {
      webTerminalFitAddon = new window.FitAddon.FitAddon();
      webTerminalXterm.loadAddon(webTerminalFitAddon);
    }
    box.innerHTML = "";
    webTerminalXterm.open(box);
    scheduleWebTerminalResize();
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
