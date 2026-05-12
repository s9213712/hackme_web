'use strict';

let gameSelectedMatchId = null;
let gameSelectedSquare = null;
let gameSelectedKey = gameInitialSelectedKey();
let chessMoveInFlight = false;
let gameState = { matches: [], invites: [], leaderboard: [] };
let soloGameTimer = null;
let inlineModuleCleanup = null;
let inlineModuleActiveApi = null;
let inlineModuleMountedKey = "";
let inlineModuleTouchStart = null;
let inlineModulePressedControl = null;
const INLINE_MODULE_GAME_KEYS = new Set(["snake", "game_2048", "brick_breaker", "reversi", "go", "gomoku"]);

function gameUrlParams() {
  try {
    return new URLSearchParams(window.location.search || "");
  } catch (err) {
    return new URLSearchParams("");
  }
}

function gameInitialSelectedKey() {
  return String(gameUrlParams().get("game") || "chess").trim() || "chess";
}

function gameViewModules() {
  return window.HACKME_GAME_VIEW_MODULES || {};
}

function activeGameViewModule() {
  return gameViewModules()[gameSelectedKey] || null;
}

function legacyGameRuntime() {
  return {
    setGameMsg,
    gameRequest,
    loadSelectedGameLeaderboard,
    submitSoloGameScore,
    ensureSoloGameTimer,
    stopSoloGameTimerIfIdle,
    formatSoloGameTime,
    soloRawElapsedMs,
    soloElapsedMs,
  };
}

function dispatchActiveGameViewEvent(type, event) {
  const module = activeGameViewModule();
  if (!module?.dispatch) return false;
  return Boolean(module.dispatch(type, event, legacyGameRuntime()));
}

function formatSoloGameTime(ms) {
  const totalMs = Math.max(0, Number(ms || 0));
  const totalSeconds = Math.floor(totalMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const tenths = Math.floor((totalMs % 1000) / 100);
  return `${minutes}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function soloRawElapsedMs(state) {
  if (!state?.startedAt) return 0;
  const end = state.completedAt || Date.now();
  return Math.max(1, Math.floor(end - state.startedAt));
}

function soloElapsedMs(state) {
  return soloRawElapsedMs(state) + Number(state?.penaltySeconds || 0) * 1000;
}

function ensureSoloGameTimer() {
  if (soloGameTimer) return;
  soloGameTimer = setInterval(() => {
    const module = activeGameViewModule();
    if (module?.updateStatus) module.updateStatus(legacyGameRuntime());
  }, 250);
}

function stopSoloGameTimerIfIdle() {
  const anyActive = Object.values(gameViewModules()).some((module) => (
    typeof module?.isActive === "function" && module.isActive()
  ));
  if (!anyActive && soloGameTimer) {
    clearInterval(soloGameTimer);
    soloGameTimer = null;
  }
}

function setGameMsg(text, ok) {
  const el = $("game-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = text ? "msg show " + (ok ? "ok" : "err") : "msg";
}

function gameIcon(key) {
  if (key === "snake") return "S";
  if (key === "game_2048") return "2";
  if (key === "brick_breaker") return "▤";
  if (key === "reversi") return "●";
  if (key === "go") return "○";
  if (key === "gomoku") return "五";
  if (key === "sudoku") return "9";
  if (key === "minesweeper") return "!";
  if (key === "1a2b") return "A";
  if (key === "tetris") return "▦";
  if (key === "space_shooter") return "▲";
  if (key === "fps_arena") return "◎";
  return "♟";
}

function gameSubtitle(game) {
  if (game.key === "snake") return "手機滑動 / 鍵盤皆可玩";
  if (game.key === "game_2048") return "手機滑動合併數字";
  if (game.key === "brick_breaker") return "手機按鍵控制擋板";
  if (game.key === "reversi") return "本機雙人黑白棋";
  if (game.key === "go") return "9 路本機雙人圍棋";
  if (game.key === "gomoku") return "15 路本機雙人五子棋";
  if (game.key === "sudoku") return "單人邏輯解題";
  if (game.key === "minesweeper") return "單人推理挑戰";
  if (game.key === "1a2b") return "單人猜數字";
  if (game.key === "tetris") return "高分消除挑戰";
  if (game.key === "space_shooter") return "高分射擊挑戰";
  if (game.key === "fps_arena") return "四模式 3D 射擊訓練";
  return game.supports_computer ? "玩家對戰 / 電腦練習" : "玩家對戰";
}

function switchGameView(key) {
  setGameMsg("", true);
  gameSelectedKey = key || "chess";
  const select = $("game-select");
  if (select && select.value !== gameSelectedKey) select.value = gameSelectedKey;
  const isInlineModule = INLINE_MODULE_GAME_KEYS.has(gameSelectedKey);
  const selectedViewModule = activeGameViewModule();
  Object.values(gameViewModules()).forEach((module) => {
    (module.panelIds || []).forEach((id) => {
      const panel = $(id);
      if (panel) panel.style.display = module.key === gameSelectedKey ? "" : "none";
    });
  });
  const inlineModulePanel = $("inline-module-game-panel");
  if (inlineModulePanel) inlineModulePanel.style.display = isInlineModule ? "" : "none";
  document.querySelectorAll("[data-game-key]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-game-key") === gameSelectedKey);
  });
  if (isInlineModule) {
    mountInlineModuleGame(gameSelectedKey);
  } else {
    cleanupInlineModuleGame();
  }
  if (!isInlineModule && selectedViewModule?.ensure) selectedViewModule.ensure(legacyGameRuntime());
  loadSelectedGameLeaderboard().catch((err) => setGameMsg(err.message || "排行榜讀取失敗", false));
}

function gameRequestNeedsFreshCsrf(json, res) {
  return res.status === 403 && String(json?.msg || "").toUpperCase().includes("CSRF");
}

async function gameRequest(path, { method = "GET", body = null } = {}) {
  const upperMethod = String(method || "GET").toUpperCase();
  const mutates = upperMethod !== "GET";
  const buildOptions = async () => {
    const csrf = await fetchCsrfToken({ force: mutates });
    const headers = { "X-CSRF-Token": csrf || "" };
    if (mutates) headers["Content-Type"] = "application/json";
    return {
      method: upperMethod,
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: body ? JSON.stringify(body) : undefined,
    };
  };

  let res = await apiFetch(API + path, await buildOptions());
  let json = await res.json().catch(() => ({}));
  if (gameRequestNeedsFreshCsrf(json, res)) {
    await fetchCsrfToken({ force: true });
    res = await apiFetch(API + path, await buildOptions());
    json = await res.json().catch(() => ({}));
  }
  if (!res.ok || !json.ok) {
    throw new Error(json.msg || `HTTP ${res.status}`);
  }
  if (mutates && typeof _csrfToken !== "undefined") {
    setCsrfToken(null);
  }
  return json;
}

function cleanupInlineModuleGame() {
  if (inlineModuleCleanup) inlineModuleCleanup();
  inlineModuleCleanup = null;
  inlineModuleActiveApi = null;
  inlineModuleMountedKey = "";
  inlineModuleTouchStart = null;
  inlineModulePressedControl = null;
  const root = $("inline-module-game-root");
  if (root) {
    root.onclick = null;
    root.innerHTML = "";
  }
  const actions = $("inline-module-game-actions");
  if (actions) actions.innerHTML = "";
  const controls = $("inline-module-game-controls");
  if (controls) controls.innerHTML = "";
}

async function submitInlineModuleScore(key, body) {
  try {
    await gameRequest(`/games/${encodeURIComponent(key)}/solo-scores`, { method: "POST", body });
    setGameMsg("成績已送出", true);
    await loadSelectedGameLeaderboard();
  } catch (err) {
    setGameMsg(err.message || "成績送出失敗", false);
  }
}

function createInlineModuleApi(key) {
  const root = $("inline-module-game-root");
  const actions = $("inline-module-game-actions");
  const controls = $("inline-module-game-controls");
  return {
    key,
    root,
    actions,
    controls,
    onAction: null,
    onControl: null,
    onKey: null,
    setTitle(text) { $("inline-module-game-title").textContent = text || ""; },
    status(text) { $("inline-module-game-status").textContent = text || ""; },
    setActions(html) { actions.innerHTML = html || ""; },
    setControls(html) { controls.innerHTML = html || ""; },
    submitScore(body) { return submitInlineModuleScore(key, body); },
  };
}

function mountInlineModuleGame(key) {
  if (inlineModuleMountedKey === key && inlineModuleActiveApi) return;
  cleanupInlineModuleGame();
  const game = window.hackmeGameByKey?.(key) || {};
  const module = window.HACKME_GAME_MODULES?.[key];
  $("inline-module-game-title").textContent = game.title || "遊戲";
  $("inline-module-game-status").textContent = game.subtitle || "準備中";
  if (!module?.mount) {
    $("inline-module-game-root").innerHTML = "<div class=\"game-page-empty\"><strong>遊戲模組尚未載入</strong></div>";
    return;
  }
  const api = createInlineModuleApi(key);
  inlineModuleActiveApi = api;
  inlineModuleMountedKey = key;
  inlineModuleCleanup = module.mount(api) || null;
}

function renderGameCatalog(games) {
  const wrap = $("game-catalog-list");
  if (!wrap) return;
  const rows = Array.isArray(games) ? games : [];
  if (typeof renderChessPracticeDifficultyOptions === "function") renderChessPracticeDifficultyOptions(rows);
  wrap.innerHTML = rows.length ? `
    <div class="game-select-panel">
      <label for="game-select">選擇遊戲</label>
      <select id="game-select" aria-label="選擇遊戲">
        ${rows.map((game) => `<option value="${sanitize(game.key || "chess")}" ${game.key === gameSelectedKey ? "selected" : ""}>${sanitize(game.title || "西洋棋")} · ${sanitize(gameSubtitle(game))}</option>`).join("")}
      </select>
    </div>
  ` : "<p style=\"color:var(--muted);\">尚未開放遊戲</p>";
  if (!rows.some((game) => game.key === gameSelectedKey)) gameSelectedKey = "chess";
  switchGameView(gameSelectedKey);
}

function renderGameUsers(users) {
  const select = $("game-invite-user");
  if (!select) return;
  const rows = Array.isArray(users) ? users : [];
  if (!rows.length) {
    select.innerHTML = '<option value="">目前沒有可邀請玩家</option>';
    return;
  }
  select.innerHTML = '<option value="">選擇玩家</option>' + rows.map((user) => (
    `<option value="${sanitize(user.username || "")}">${sanitize(user.username || "")} · ${sanitize(user.role || "user")}</option>`
  )).join("");
}

function renderGameInvites(invites) {
  const wrap = $("game-invite-list");
  if (!wrap) return;
  const rows = Array.isArray(invites) ? invites : [];
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">目前沒有邀請</p>";
    return;
  }
  wrap.innerHTML = rows.map((invite) => {
    const incoming = invite.opponent_username === currentUser;
    const title = incoming ? `${invite.inviter_username} 邀請你對戰` : `邀請 ${invite.opponent_username}`;
    const actions = invite.status === "pending" && incoming
      ? `<button class="btn game-mini-btn btn-primary" type="button" data-game-invite="${invite.id}" data-game-invite-action="accept">接受</button>
         <button class="btn game-mini-btn" type="button" data-game-invite="${invite.id}" data-game-invite-action="reject">拒絕</button>`
      : invite.status === "pending"
        ? `<button class="btn game-mini-btn" type="button" data-game-invite="${invite.id}" data-game-invite-action="cancel">取消</button>`
        : "";
    return `
      <div class="drive-file-row game-list-row">
        <div><strong>${sanitize(title)}</strong><small>${sanitize(invite.status)} · ${sanitize(formatChatTime(invite.created_at))}</small></div>
        <div class="drive-file-actions">${actions}</div>
      </div>
    `;
  }).join("");
}


function renderGameLeaderboard(data) {
  const wrap = $("game-leaderboard-list");
  if (!wrap) return;
  const rows = Array.isArray(data?.leaderboard) ? data.leaderboard : [];
  if (!rows.length) {
    const empty = data?.rank_mode === "score_desc"
      ? "本週尚無高分紀錄"
      : data?.rank_mode === "time_asc"
        ? "本週尚無完成時間紀錄"
        : "本週尚無玩家對戰成績";
    wrap.innerHTML = `<p style="color:var(--muted);">${empty}</p>`;
    return;
  }
  if (data?.rank_mode === "score_desc") {
    wrap.innerHTML = rows.map((row) => `
      <div class="drive-file-row game-list-row">
        <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${sanitize(data.difficulty || "standard")} · ${row.attempts || 1} 次挑戰 · ${formatSoloGameTime(row.elapsed_ms || 0)}</small></div>
        <strong>${Number(row.score || 0).toLocaleString()}</strong>
      </div>
    `).join("");
    return;
  }
  if (data?.rank_mode === "guesses_then_time") {
    wrap.innerHTML = rows.map((row) => `
      <div class="drive-file-row game-list-row">
        <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>猜 ${row.guess_count || 0} 次 · 完成 ${row.attempts || 1} 次</small></div>
        <strong>${formatSoloGameTime(row.elapsed_ms || 0)}</strong>
      </div>
    `).join("");
    return;
  }
  if (data?.rank_mode === "time_asc") {
    wrap.innerHTML = rows.map((row) => `
      <div class="drive-file-row game-list-row">
        <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${sanitize(data.difficulty || "standard")} · ${row.attempts || 1} 次完成${row.penalty_seconds ? ` · 加時 ${row.penalty_seconds} 秒` : ""}</small></div>
        <strong>${formatSoloGameTime(row.elapsed_ms || 0)}</strong>
      </div>
    `).join("");
    return;
  }
  wrap.innerHTML = rows.map((row) => `
    <div class="drive-file-row game-list-row">
      <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${row.wins || 0} 勝 · ${row.draws || 0} 和 · ${row.losses || 0} 敗</small></div>
      <strong>${row.score || 0}</strong>
    </div>
  `).join("");
}


async function loadSelectedGameLeaderboard() {
  const key = gameSelectedKey || "chess";
  const viewModule = activeGameViewModule();
  let path = viewModule?.leaderboardPath ? viewModule.leaderboardPath(legacyGameRuntime()) : "/games/chess/leaderboard";
  if (INLINE_MODULE_GAME_KEYS.has(key)) {
    path = `/games/${encodeURIComponent(key)}/solo-leaderboard`;
  }
  const data = await gameRequest(path);
  gameState.leaderboard = data.leaderboard || [];
  renderGameLeaderboard(data);
  const awardBtn = $("game-award-btn");
  if (awardBtn) awardBtn.style.display = currentUser === "root" && key === "chess" ? "" : "none";
  await loadChessRootDashboard().catch(() => {});
  return data;
}

async function submitSoloGameScore(gameKey, state) {
  if (!state || state.scoreSubmitted) return;
  state.scoreSubmitted = true;
  const rawElapsed = soloRawElapsedMs(state);
  const elapsed = soloElapsedMs(state);
  try {
    await gameRequest(`/games/${encodeURIComponent(gameKey)}/solo-scores`, {
      method: "POST",
      body: {
        raw_elapsed_ms: rawElapsed,
        penalty_seconds: Number(state.penaltySeconds || 0),
        elapsed_ms: elapsed,
        difficulty: state.difficulty || "standard",
        puzzle_id: state.puzzleId || "",
        guess_count: Array.isArray(state.guesses) ? state.guesses.length : 0,
        score: Number(state.score || 0),
      },
    });
    await loadSelectedGameLeaderboard();
  } catch (err) {
    state.scoreSubmitted = false;
    setGameMsg(err.message || "成績送出失敗", false);
  }
}


async function loadGameZone() {
  try {
    await fetchCsrfToken({ force: true });
    const [catalog, usersJson, invitesJson, matchesJson] = await Promise.all([
      gameRequest("/games/catalog"),
      gameRequest("/games/users"),
      gameRequest("/games/chess/invites"),
      gameRequest("/games/chess/matches"),
    ]);
    gameState = {
      matches: matchesJson.matches || [],
      invites: invitesJson.invites || [],
      leaderboard: [],
    };
    renderGameCatalog(catalog.games || []);
    renderGameUsers(usersJson.users || []);
    renderGameInvites(invitesJson.invites || []);
    renderGameMatches(matchesJson.matches || []);
    await loadSelectedGameLeaderboard();
    setGameMsg("", true);
  } catch (err) {
    setGameMsg(err.message || "遊戲區讀取失敗", false);
  }
}

async function refreshGameZoneAfterMutation(successMessage) {
  try {
    await loadGameZone();
    if (successMessage) setGameMsg(successMessage, true);
  } catch (err) {
    if (successMessage) setGameMsg(successMessage, true);
  }
}


document.addEventListener("click", (event) => {
  const inlineModuleAction = event.target?.closest?.("#inline-module-game-panel [data-action]");
  if (inlineModuleAction && inlineModuleActiveApi?.onAction) {
    inlineModuleActiveApi.onAction(inlineModuleAction.dataset.action || "");
    return;
  }
  const catalogBtn = event.target?.closest?.("[data-game-key]");
  if (catalogBtn) {
    switchGameView(catalogBtn.dataset.gameKey || "chess");
    return;
  }
  if (dispatchActiveGameViewEvent("click", event)) {
    return;
  }
  const rootRefreshBtn = event.target?.closest?.("#game-root-chess-refresh-btn");
  if (rootRefreshBtn) {
    loadChessRootDashboard().catch((err) => setGameMsg(err.message || "dashboard 讀取失敗", false));
    return;
  }
  const rootWarmStartBtn = event.target?.closest?.("#game-root-chess-warm-start-btn");
  if (rootWarmStartBtn) {
    warmStartChessModels();
    return;
  }
  const rootStageBtn = event.target?.closest?.("#game-root-chess-stage-btn");
  if (rootStageBtn) {
    stageChessCandidate();
    return;
  }
  const rootPromoteBtn = event.target?.closest?.("#game-root-chess-promote-btn");
  if (rootPromoteBtn) {
    promoteChessCandidate();
    return;
  }
  const deleteMatchBtn = event.target?.closest?.("[data-game-delete-match]");
  if (deleteMatchBtn) {
    deleteFinishedGame(deleteMatchBtn.dataset.gameDeleteMatch);
    return;
  }
  const offerDrawBtn = event.target?.closest?.("#game-offer-draw-btn");
  if (offerDrawBtn) {
    offerChessDraw();
    return;
  }
  const acceptDrawBtn = event.target?.closest?.("#game-accept-draw-btn");
  if (acceptDrawBtn) {
    respondChessDraw("accept");
    return;
  }
  const rejectDrawBtn = event.target?.closest?.("#game-reject-draw-btn");
  if (rejectDrawBtn) {
    respondChessDraw("reject");
    return;
  }
  const claimDrawBtn = event.target?.closest?.("#game-claim-draw-btn");
  if (claimDrawBtn) {
    claimChessDraw();
    return;
  }
  const inviteBtn = event.target?.closest?.("[data-game-invite]");
  if (inviteBtn) {
    reviewGameInvite(inviteBtn.dataset.gameInvite, inviteBtn.dataset.gameInviteAction || "accept");
    return;
  }
  const matchBtn = event.target?.closest?.("[data-game-match-id]");
  if (matchBtn) {
    gameSelectedMatchId = Number(matchBtn.dataset.gameMatchId || 0);
    gameSelectedSquare = null;
    renderGameMatches(gameState.matches || []);
    return;
  }
  const squareBtn = event.target?.closest?.("[data-chess-square]");
  if (squareBtn) {
    selectChessSquare(squareBtn.dataset.chessSquare || "");
  }
});

document.addEventListener("pointerdown", (event) => {
  const control = event.target?.closest?.("#inline-module-game-controls button");
  if (!control || !inlineModuleActiveApi?.onControl) return;
  event.preventDefault();
  inlineModulePressedControl = control;
  inlineModuleActiveApi.onControl(control, true);
});

document.addEventListener("pointerup", () => {
  if (!inlineModulePressedControl || !inlineModuleActiveApi?.onControl) {
    inlineModulePressedControl = null;
    return;
  }
  if (inlineModulePressedControl.dataset.hold) {
    inlineModuleActiveApi.onControl(inlineModulePressedControl, false);
  }
  inlineModulePressedControl = null;
});

document.addEventListener("pointercancel", () => {
  if (inlineModulePressedControl?.dataset.hold && inlineModuleActiveApi?.onControl) {
    inlineModuleActiveApi.onControl(inlineModulePressedControl, false);
  }
  inlineModulePressedControl = null;
});

document.addEventListener("touchstart", (event) => {
  const root = event.target?.closest?.("#inline-module-game-root");
  if (!root) return;
  const touch = event.changedTouches[0];
  inlineModuleTouchStart = touch ? { x: touch.clientX, y: touch.clientY } : null;
}, { passive: true });

document.addEventListener("touchend", (event) => {
  const root = event.target?.closest?.("#inline-module-game-root");
  if (!root || !inlineModuleTouchStart || !inlineModuleActiveApi?.onKey) return;
  const touch = event.changedTouches[0];
  if (!touch) return;
  const dx = touch.clientX - inlineModuleTouchStart.x;
  const dy = touch.clientY - inlineModuleTouchStart.y;
  inlineModuleTouchStart = null;
  if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
  const key = Math.abs(dx) > Math.abs(dy)
    ? (dx > 0 ? "ArrowRight" : "ArrowLeft")
    : (dy > 0 ? "ArrowDown" : "ArrowUp");
  inlineModuleActiveApi.onKey({ key, preventDefault() {} }, true);
}, { passive: true });

document.addEventListener("submit", (event) => {
  const uciForm = event.target?.closest?.("#game-chess-uci-form");
  if (!uciForm) return;
  event.preventDefault();
  submitChessUciMove();
});

document.addEventListener("input", (event) => {
  if (dispatchActiveGameViewEvent("input", event)) {
    return;
  }
  const chessUciInput = event.target?.closest?.("#game-chess-uci-input");
  if (chessUciInput) {
    chessUciInput.value = normalizeChessUciInput(chessUciInput.value || "");
  }
});

document.addEventListener("keydown", (event) => {
  const tag = String(event.target?.tagName || "").toLowerCase();
  const editing = ["input", "textarea", "select"].includes(tag);
  if ((!editing || gameSelectedKey === "1a2b") && dispatchActiveGameViewEvent("keydown", event)) {
    return;
  }
  if (!editing && INLINE_MODULE_GAME_KEYS.has(gameSelectedKey) && inlineModuleActiveApi?.onKey) {
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " "].includes(event.key)) event.preventDefault();
    inlineModuleActiveApi.onKey(event, true);
  }
});

document.addEventListener("keyup", (event) => {
  if (dispatchActiveGameViewEvent("keyup", event)) {
    return;
  }
  if (INLINE_MODULE_GAME_KEYS.has(gameSelectedKey) && inlineModuleActiveApi?.onKey) {
    inlineModuleActiveApi.onKey(event, false);
  }
});

document.addEventListener("change", (event) => {
  const gameSelect = event.target?.closest?.("#game-select");
  if (gameSelect) {
    const key = gameSelect.value || "chess";
    switchGameView(key);
    return;
  }
  dispatchActiveGameViewEvent("change", event);
});

document.addEventListener("contextmenu", (event) => {
  dispatchActiveGameViewEvent("contextmenu", event);
});
