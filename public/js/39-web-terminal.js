'use strict';

let webTerminalSocket = null;
let webTerminalTerm = null;
let webTerminalStatusCache = null;
let webTerminalAssetsPromise = null;
let webTerminalAssetError = "";

function loadWebTerminalAssets() {
  if (typeof window.Terminal === "function") return Promise.resolve(true);
  if (webTerminalAssetsPromise) return webTerminalAssetsPromise;
  webTerminalAssetsPromise = new Promise((resolve) => {
    const existingCss = document.querySelector('link[data-web-terminal-asset="xterm-css"]');
    if (!existingCss) {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "/vendor/xterm/xterm.css?v=20260429-web-terminal";
      css.dataset.webTerminalAsset = "xterm-css";
      document.head.appendChild(css);
    }
    const existingScript = document.querySelector('script[data-web-terminal-asset="xterm-js"]');
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(typeof window.Terminal === "function"), { once: true });
      existingScript.addEventListener("error", () => {
        webTerminalAssetError = "xterm.js 靜態檔載入失敗";
        resolve(false);
      }, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "/vendor/xterm/xterm.js?v=20260429-web-terminal";
    script.defer = true;
    script.dataset.webTerminalAsset = "xterm-js";
    script.onload = () => resolve(typeof window.Terminal === "function");
    script.onerror = () => {
      webTerminalAssetError = "xterm.js 靜態檔載入失敗";
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return webTerminalAssetsPromise;
}

function setWebTerminalMessage(text, ok) {
  const el = $("web-terminal-msg");
  if (!el) return;
  if (!text) {
    el.className = "msg";
    el.textContent = "";
    return;
  }
  el.textContent = text;
  el.className = "msg show " + (ok ? "ok" : "err");
}

function webTerminalCheckItems(payload) {
  const term = payload && payload.terminal ? payload.terminal : {};
  const proc = term.process || {};
  const sock = proc.docker_sock || {};
  const processGroups = Array.isArray(proc.groups) ? proc.groups : [];
  const socketGroupMissing = sock.group && processGroups.length && !processGroups.includes(sock.group);
  const groupHint = socketGroupMissing
    ? `Docker socket 屬於 ${sock.group} 群組，但目前 server process（${proc.user || "-"}）的有效群組沒有 ${sock.group}。請重新登入後重開 server，或用 sg ${sock.group} -c 'scripts/run_prod.sh' 啟動。`
    : "";
  const runtimeHint = term.runtime_error
    ? `${term.runtime_error}；${groupHint || "Web 後端目前無法連 Docker daemon。請用啟動 server 的同一個使用者執行 docker info，修好權限後重開 server。"}`
    : "找不到 Docker 或目前帳號無法使用 Docker，請執行 ./install_web_terminal_dependencies.sh --doctor --venv .venv 後依照修復指令處理。";
  const imageHint = term.runtime_available
    ? `${term.image_error ? term.image_error + "；" : ""}找不到 ${term.image || "hackme-web-terminal:base"}，請執行 ./install_web_terminal_dependencies.sh --image。`
    : "Docker daemon 權限尚未通過，暫時無法確認 image。先修 Docker 權限並重開 server，不要只用 sudo check。";
  return [
    {
      key: "enabled",
      label: "root 功能開關",
      ok: !!term.enabled,
      hint: "Web Terminal 已在 root 設定中關閉，請到安全中心的伺服器設定啟用。",
    },
    {
      key: "websocket",
      label: "WebSocket 後端",
      ok: !!term.websocket_available,
      hint: "缺少 flask-sock / simple-websocket，請執行 ./install_web_terminal_dependencies.sh --python。",
    },
    {
      key: "runtime",
      label: "Docker runtime",
      ok: !!term.runtime_available,
      hint: runtimeHint,
    },
    {
      key: "image",
      label: "Terminal container image",
      ok: !!term.image_available,
      hint: imageHint,
    },
    {
      key: "xterm",
      label: "xterm.js 前端資源",
      ok: typeof window.Terminal === "function",
      hint: `${webTerminalAssetError ? webTerminalAssetError + "；" : ""}缺少 public/vendor/xterm 靜態檔，請執行 ./install_web_terminal_dependencies.sh --xterm。`,
    },
  ];
}

function renderWebTerminalStatus(payload) {
  webTerminalStatusCache = payload || null;
  const term = payload && payload.terminal ? payload.terminal : {};
  const status = $("web-terminal-status");
  const checks = $("web-terminal-checks");
  const openBtn = $("web-terminal-open-btn");
  const closeBtn = $("web-terminal-close-btn");
  const items = webTerminalCheckItems(payload);
  const failures = items.filter((item) => !item.ok);
  if (status) {
    status.textContent = failures.length
      ? `環境檢查未通過：${failures.map((item) => item.label).join("、")}`
      : `環境正常，掛載路徑會指向 root 的 Cloud Drive。Image: ${term.image || "-"}`;
  }
  if (checks) {
    checks.innerHTML = items.map((item) => `
      <div class="web-terminal-check ${item.ok ? "ok" : "err"}">
        <span class="web-terminal-check-dot"></span>
        <div>
          <strong>${sanitize(item.label)}</strong>
          <small>${sanitize(item.ok ? "通過" : item.hint)}</small>
        </div>
      </div>
    `).join("");
  }
  if (openBtn) openBtn.disabled = failures.length > 0 || !!webTerminalSocket;
  if (closeBtn) closeBtn.disabled = !webTerminalSocket;
  return failures;
}

async function loadWebTerminalStatus({ notify = false } = {}) {
  if (!currentUser || currentUser !== "root") return null;
  await loadWebTerminalAssets();
  const csrf = await fetchCsrfToken();
  let payload = null;
  try {
    const res = await fetch(API + "/root/web-terminal/status", {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "X-CSRF-Token": csrf || "" },
    });
    payload = await res.json().catch(() => ({}));
    if (!res.ok || !payload.ok) {
      const msg = payload.msg || `Web Terminal 環境檢查失敗（HTTP ${res.status}）`;
      setWebTerminalMessage(msg, false);
      renderWebTerminalStatus({ ok: false, terminal: {} });
      return null;
    }
    const failures = renderWebTerminalStatus(payload);
    if (notify) {
      if (failures.length) {
        setWebTerminalMessage(failures[0].hint, false);
      } else {
        setWebTerminalMessage("環境檢查通過，可以開啟隔離 terminal session。", true);
      }
    }
    return payload;
  } catch (err) {
    setWebTerminalMessage(`Web Terminal 環境檢查失敗：${err.message || err}`, false);
    renderWebTerminalStatus({ ok: false, terminal: {} });
    return null;
  }
}

async function ensureWebTerminalReady() {
  const payload = await loadWebTerminalStatus({ notify: false });
  const failures = renderWebTerminalStatus(payload || { ok: false, terminal: {} });
  if (failures.length) {
    setWebTerminalMessage(failures[0].hint, false);
    return false;
  }
  return true;
}

function webTerminalSocketUrl(csrf) {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = encodeURIComponent(csrf || "");
  return `${scheme}//${window.location.host}/api/root/web-terminal/session?csrf_token=${token}`;
}

async function openWebTerminalSession() {
  if (webTerminalSocket) return;
  if (!(await ensureWebTerminalReady())) return;
  const screen = $("web-terminal-screen");
  if (!screen) return;
  screen.innerHTML = "";
  webTerminalTerm = new window.Terminal({
    cursorBlink: true,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: 13,
    theme: { background: "#05070b", foreground: "#dce7ff" },
  });
  webTerminalTerm.open(screen);
  webTerminalTerm.focus();

  const csrf = await fetchCsrfToken();
  webTerminalSocket = new WebSocket(webTerminalSocketUrl(csrf));
  const openBtn = $("web-terminal-open-btn");
  const closeBtn = $("web-terminal-close-btn");
  if (openBtn) openBtn.disabled = true;
  if (closeBtn) closeBtn.disabled = false;
  webTerminalTerm.onData((data) => {
    if (webTerminalSocket && webTerminalSocket.readyState === WebSocket.OPEN) {
      webTerminalSocket.send(data);
    }
  });
  webTerminalSocket.onopen = () => setWebTerminalMessage("Web Terminal session 已建立。", true);
  webTerminalSocket.onmessage = (event) => {
    if (webTerminalTerm) webTerminalTerm.write(String(event.data || ""));
  };
  webTerminalSocket.onerror = () => setWebTerminalMessage("Web Terminal WebSocket 連線失敗。", false);
  webTerminalSocket.onclose = () => {
    webTerminalSocket = null;
    if (closeBtn) closeBtn.disabled = true;
    renderWebTerminalStatus(webTerminalStatusCache || { ok: false, terminal: {} });
    setWebTerminalMessage("Web Terminal session 已關閉。", true);
  };
}

function closeWebTerminalSession() {
  if (webTerminalSocket) {
    try { webTerminalSocket.close(); } catch (_) {}
    webTerminalSocket = null;
  }
  if (webTerminalTerm) {
    try { webTerminalTerm.dispose(); } catch (_) {}
    webTerminalTerm = null;
  }
  const screen = $("web-terminal-screen");
  if (screen) screen.innerHTML = '<div class="drive-empty">terminal session 已關閉。</div>';
  renderWebTerminalStatus(webTerminalStatusCache || { ok: false, terminal: {} });
}
