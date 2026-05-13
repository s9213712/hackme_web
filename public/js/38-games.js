'use strict';

let gameSelectedMatchId = null;
let gameSelectedSquare = null;
let gameSelectedKey = gameInitialSelectedKey();
let chessMoveInFlight = false;
let gameState = { matches: [], invites: [], leaderboard: [] };
let soloGameTimer = null;
let localGameModuleCleanup = null;
let localGameModuleActiveApi = null;
let localGameModuleMountedKey = "";
let localGameModuleTouchStart = null;
let localGameModulePressedControl = null;
let localGameModuleSwipeMode = "tap";

function localGameCatalogKeys() {
  const catalog = Array.isArray(window.HACKME_GAME_CATALOG) ? window.HACKME_GAME_CATALOG : [];
  return new Set(catalog.filter((game) => !game.legacy).map((game) => game.key));
}

function isLocalGameCatalogKey(key) {
  return localGameCatalogKeys().has(key);
}

function isLocalGameModuleAvailable(key) {
  return Boolean(window.HACKME_GAME_MODULES?.[key]?.mount);
}

function filterAvailableGameCatalog(games) {
  const rows = Array.isArray(games) ? games : [];
  return rows.filter((game) => !isLocalGameCatalogKey(game.key) || isLocalGameModuleAvailable(game.key));
}

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
    dailyChallenge(gameKey = gameSelectedKey) {
      return window.hackmeGameDailyChallenge?.(gameKey) || null;
    },
    dailyMissions(gameKey = gameSelectedKey) {
      return window.listHackmeGameDailyMissions?.(gameKey) || [];
    },
    achievement(gameKey, id, label, detail = "") {
      const result = window.recordHackmeGameAchievement?.(gameKey, id, label, detail);
      if (result?.unlocked) setGameMsg(`成就解鎖：${result.label}`, true);
      renderGameMetaPanels();
      return result || { unlocked: false };
    },
    mission(gameKey, id, progress, target, label = "") {
      const result = window.recordHackmeGameMissionProgress?.(gameKey, id, progress, target, label);
      renderGameMetaPanels();
      return result || null;
    },
    replay(gameKey, payload) {
      const result = window.recordHackmeGameReplay?.(gameKey, payload);
      renderGameMetaPanels();
      return result;
    },
    renderGameMetaPanels,
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
  if (key === "real_tetris") return "▧";
  if (key === "space_shooter") return "▲";
  if (key === "fps_arena") return "◎";
  if (key === "bullet_hell") return "✦";
  if (key === "stickman_shooter") return "人";
  return "♟";
}

function gameSubtitle(game) {
  if (game.key === "snake") return "手機滑動 / 鍵盤皆可玩";
  if (game.key === "game_2048") return "手機滑動合併數字";
  if (game.key === "brick_breaker") return "手機按鍵控制擋板";
  if (game.key === "reversi") return "AI 練習 / 本機雙人黑白棋";
  if (game.key === "go") return "9 路 AI 練習 / 本機雙人圍棋";
  if (game.key === "gomoku") return "15 路 AI 練習 / 本機雙人五子棋";
  if (game.key === "sudoku") return "單人邏輯解題";
  if (game.key === "minesweeper") return "單人推理挑戰";
  if (game.key === "1a2b") return "單人猜數字";
  if (game.key === "tetris") return "高分消除挑戰";
  if (game.key === "real_tetris") return "剛體物理與放寬消線";
  if (game.key === "space_shooter") return "高分射擊挑戰";
  if (game.key === "fps_arena") return "四模式 3D 射擊訓練";
  if (game.key === "bullet_hell") return "閃避密集彈幕並反擊";
  if (game.key === "stickman_shooter") return "2D 側捲平台射擊挑戰";
  return game.supports_computer ? "玩家對戰 / 電腦練習" : "玩家對戰";
}

function switchGameView(key) {
  setGameMsg("", true);
  gameSelectedKey = key || "chess";
  const select = $("game-select");
  if (select && select.value !== gameSelectedKey) select.value = gameSelectedKey;
  const isLocalGameModule = isLocalGameModuleAvailable(gameSelectedKey);
  const selectedViewModule = activeGameViewModule();
  Object.values(gameViewModules()).forEach((module) => {
    (module.panelIds || []).forEach((id) => {
      const panel = $(id);
      if (panel) panel.style.display = module.key === gameSelectedKey ? "" : "none";
    });
  });
  const localGameModulePanel = $("local-module-game-panel");
  if (localGameModulePanel) localGameModulePanel.style.display = isLocalGameModule ? "" : "none";
  document.querySelectorAll("[data-game-key]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-game-key") === gameSelectedKey);
  });
  if (isLocalGameModule) {
    mountLocalGameModule(gameSelectedKey);
  } else {
    cleanupLocalGameModule();
  }
  if (!isLocalGameModule && selectedViewModule?.ensure) selectedViewModule.ensure(legacyGameRuntime());
  updateGameFullscreenButtons();
  loadSelectedGameLeaderboard().catch((err) => setGameMsg(err.message || "排行榜讀取失敗", false));
}

function gameFullscreenTarget() {
  return document.querySelector("#module-games .game-board-panel");
}

function updateGameFullscreenButtons() {
  const target = gameFullscreenTarget();
  const active = Boolean(target && document.fullscreenElement === target);
  document.querySelectorAll("#game-fullscreen-btn, #fps-arena-fullscreen-btn").forEach((button) => {
    button.textContent = active ? "離開全螢幕" : (button.id === "fps-arena-fullscreen-btn" ? "全螢幕" : "全螢幕遊戲");
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

async function toggleGameFullscreen() {
  const target = gameFullscreenTarget();
  if (!target) return;
  try {
    if (document.fullscreenElement === target) {
      await document.exitFullscreen?.();
    } else {
      await target.requestFullscreen?.();
    }
    updateGameFullscreenButtons();
  } catch (err) {
    setGameMsg("此瀏覽器無法切換全螢幕", false);
  }
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

function cleanupLocalGameModule() {
  if (localGameModuleCleanup) localGameModuleCleanup();
  localGameModuleCleanup = null;
  localGameModuleActiveApi = null;
  localGameModuleMountedKey = "";
  localGameModuleTouchStart = null;
  localGameModulePressedControl = null;
  localGameModuleSwipeMode = "tap";
  const root = $("local-module-game-root");
  if (root) {
    root.onclick = null;
    root.innerHTML = "";
  }
  const actions = $("local-module-game-actions");
  if (actions) actions.innerHTML = "";
  const controls = $("local-module-game-controls");
  if (controls) controls.innerHTML = "";
}

function normalizeSoloScoreTiming(body = {}) {
  const payload = { ...body };
  const penaltySeconds = Math.max(0, Math.round(Number(payload.penalty_seconds || 0)));
  const rawFromPayload = Number(payload.raw_elapsed_ms || 0);
  const elapsedFromPayload = Number(payload.elapsed_ms || 0);
  const rawElapsed = Math.max(1, Math.round(rawFromPayload > 0 ? rawFromPayload : elapsedFromPayload - penaltySeconds * 1000));
  payload.raw_elapsed_ms = rawElapsed;
  payload.penalty_seconds = penaltySeconds;
  payload.elapsed_ms = rawElapsed + penaltySeconds * 1000;
  return payload;
}

async function submitLocalGameModuleScore(key, body) {
  const payload = normalizeSoloScoreTiming(body);
  try {
    const json = await gameRequest(`/games/${encodeURIComponent(key)}/solo-scores`, { method: "POST", body: payload });
    recordGameOutcome(key, payload, json);
    showGameDailyRewardFeedback(json, "成績已送出");
    await loadSelectedGameLeaderboard();
    return json;
  } catch (err) {
    setGameMsg(err.message || "成績送出失敗", false);
    return null;
  }
}

function showGameDailyRewardFeedback(json, fallback) {
  const reward = json?.daily_reward;
  if (reward?.wallet && typeof renderEconomyWallet === "function") renderEconomyWallet(reward.wallet);
  if (reward?.awarded) {
    setGameMsg(`每日任務完成，獲得 ${Number(reward.reward_points || 0).toLocaleString()} 積分`, true);
    return;
  }
  if (reward?.already_claimed) {
    setGameMsg("成績已送出，每日任務獎勵今日已領取", true);
    return;
  }
  if (reward?.error) {
    setGameMsg(`成績已送出；每日任務積分暫時未入帳：${reward.error}`, false);
    return;
  }
  setGameMsg(fallback || "成績已送出", true);
}

function currentGameDailyChallenge(key = gameSelectedKey) {
  return window.hackmeGameDailyChallenge?.(key) || null;
}

function scoreOutcomeFromBody(body = {}, json = {}) {
  const score = Number(body.score || 0);
  const elapsed = Number(body.elapsed_ms || body.raw_elapsed_ms || 0);
  const guessCount = Number(body.guess_count || 0);
  const accuracy = Number(body.accuracy || 0);
  return {
    ...body,
    score,
    elapsed_ms: elapsed,
    guess_count: guessCount,
    accuracy,
    completed: true,
    clean: !Number(body.penalty_seconds || 0),
    ranked: json?.ranked !== false,
  };
}

function recordGameOutcome(gameKey, body = {}, json = {}) {
  const outcome = scoreOutcomeFromBody(body, json);
  window.completeHackmeGameMissionsForResult?.(gameKey, outcome);
  const shareText = window.buildHackmeGameShareText?.(gameKey, outcome) || "";
  window.recordHackmeGameReplay?.(gameKey, {
    ...outcome,
    summary: shareText,
    title: window.hackmeGameByKey?.(gameKey)?.title || gameKey,
  });
  renderGameMetaPanels();
}

function createLocalGameModuleApi(key) {
  const root = $("local-module-game-root");
  const actions = $("local-module-game-actions");
  const controls = $("local-module-game-controls");
  return {
    key,
    root,
    actions,
    controls,
    onAction: null,
    onControl: null,
    onKey: null,
    setTitle(text) { $("local-module-game-title").textContent = text || ""; },
    status(text) { $("local-module-game-status").textContent = text || ""; },
    setActions(html) { actions.innerHTML = html || ""; },
    setControls(html) { controls.innerHTML = html || ""; },
    setSwipeMode(mode) { localGameModuleSwipeMode = mode === "hold" ? "hold" : "tap"; },
    dailyChallenge() { return window.hackmeGameDailyChallenge?.(key) || null; },
    dailyMissions() { return window.listHackmeGameDailyMissions?.(key) || []; },
    achievement(id, label, detail = "") {
      const result = window.recordHackmeGameAchievement?.(key, id, label, detail);
      if (result?.unlocked) setGameMsg(`成就解鎖：${result.label}`, true);
      renderGameMetaPanels();
      return result || { unlocked: false };
    },
    mission(id, progress, target, label = "") {
      const result = window.recordHackmeGameMissionProgress?.(key, id, progress, target, label);
      renderGameMetaPanels();
      return result || null;
    },
    recordReplay(payload) {
      const result = window.recordHackmeGameReplay?.(key, payload);
      renderGameMetaPanels();
      return result;
    },
    shareSummary(payload) {
      return window.buildHackmeGameShareText?.(key, payload) || "";
    },
    request(path, options) { return gameRequest(path, options); },
    submitScore(body) { return submitLocalGameModuleScore(key, body); },
  };
}

function mountLocalGameModule(key) {
  if (localGameModuleMountedKey === key && localGameModuleActiveApi) return;
  cleanupLocalGameModule();
  const game = window.hackmeGameByKey?.(key) || {};
  const module = window.HACKME_GAME_MODULES?.[key];
  $("local-module-game-title").textContent = game.title || "遊戲";
  $("local-module-game-status").textContent = game.subtitle || "準備中";
  if (!module?.mount) {
    $("local-module-game-root").innerHTML = "<div class=\"game-page-empty\"><strong>遊戲模組尚未載入</strong></div>";
    return;
  }
  const api = createLocalGameModuleApi(key);
  localGameModuleActiveApi = api;
  localGameModuleMountedKey = key;
  localGameModuleCleanup = module.mount(api) || null;
}

function renderGameCatalog(games) {
  const wrap = $("game-catalog-list");
  if (!wrap) return;
  const rows = filterAvailableGameCatalog(games);
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

function gameMetricText(value, target) {
  const current = Number(value || 0);
  const goal = Number(target || 1);
  if (goal >= 10000) return `${formatSoloGameTime(Math.min(current, goal))} / ${formatSoloGameTime(goal)}`;
  return `${Math.min(current, goal).toLocaleString()} / ${goal.toLocaleString()}`;
}

function renderGameDailyPanel() {
  const wrap = $("game-daily-panel");
  if (!wrap) return;
  const key = gameSelectedKey || "chess";
  const challenge = currentGameDailyChallenge(key);
  const missions = window.listHackmeGameDailyMissions?.(key, challenge) || [];
  wrap.innerHTML = `
    <div class="drive-card-sub">${sanitize(challenge?.label || "每日挑戰")} · 完成可領每日積分</div>
    <div class="game-daily-missions">
      ${missions.map((mission) => `
        <div class="game-mission-row ${mission.complete ? "complete" : ""}">
          <span>${mission.complete ? "✓" : mission.dailyIndex || "·"}</span>
          <div><strong>${sanitize(mission.label || mission.id)}</strong><small>${gameMetricText(mission.progress, mission.target)}</small></div>
        </div>
      `).join("") || "<p style=\"color:var(--muted);\">今日沒有任務</p>"}
    </div>
  `;
}

function renderGameAchievementsPanel() {
  const wrap = $("game-achievement-list");
  if (!wrap) return;
  const rows = window.listHackmeGameAchievements?.(gameSelectedKey || "") || [];
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">尚未解鎖成就</p>";
    return;
  }
  wrap.innerHTML = rows.slice(0, 8).map((row) => `
    <div class="game-achievement-row ${row.unlocked || row.unlockedAt ? "unlocked" : ""}">
      <span>${row.unlocked || row.unlockedAt ? "✓" : "○"}</span>
      <div><strong>${sanitize(row.label || row.id)}</strong><small>${sanitize(row.detail || (row.unlockedAt ? formatChatTime(row.unlockedAt) : "尚未解鎖"))}</small></div>
    </div>
  `).join("");
}

function renderGameReplaysPanel() {
  const wrap = $("game-replay-list");
  if (!wrap) return;
  const rows = window.listHackmeGameReplays?.(gameSelectedKey || "") || [];
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">完成一局後會保留最近回放摘要</p>";
    return;
  }
  wrap.innerHTML = rows.slice(0, 5).map((row) => {
    const share = window.buildHackmeGameShareText?.(row.gameKey, row) || row.summary || "";
    return `
      <div class="drive-file-row game-list-row">
        <div><strong>${sanitize(row.title || row.gameKey)}</strong><small>${sanitize(row.summary || share)} · ${sanitize(formatChatTime(row.createdAt))}</small></div>
        <button class="btn game-mini-btn" type="button" data-game-share-text="${sanitize(share)}">分享</button>
      </div>
    `;
  }).join("");
}

function renderGameMetaPanels() {
  renderGameDailyPanel();
  renderGameAchievementsPanel();
  renderGameReplaysPanel();
}

async function loadSelectedGameDailyLeaderboard() {
  const wrap = $("game-daily-leaderboard-list");
  if (!wrap) return null;
  const key = gameSelectedKey || "chess";
  if (key === "chess") {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">西洋棋以週排行榜與對局分析為主</p>";
    return null;
  }
  const challenge = currentGameDailyChallenge(key);
  if (!challenge?.key) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">今日挑戰尚未產生</p>";
    return null;
  }
  try {
    const data = await gameRequest(`/games/${encodeURIComponent(key)}/solo-leaderboard?puzzle_id=${encodeURIComponent(challenge.key)}`);
    const rows = Array.isArray(data?.leaderboard) ? data.leaderboard : [];
    if (!rows.length) {
      wrap.innerHTML = "<p style=\"color:var(--muted);\">今日尚無挑戰成績</p>";
    } else {
      wrap.innerHTML = rows.slice(0, 5).map((row) => `
        <div class="drive-file-row game-list-row">
          <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${row.attempts || 1} 次挑戰 · ${formatSoloGameTime(row.elapsed_ms || 0)}</small></div>
          <strong>${data.rank_mode === "score_desc" ? Number(row.score || 0).toLocaleString() : formatSoloGameTime(row.elapsed_ms || 0)}</strong>
        </div>
      `).join("");
    }
    return data;
  } catch (err) {
    wrap.innerHTML = `<p style="color:var(--danger);">${sanitize(err.message || "每日排行榜讀取失敗")}</p>`;
    return null;
  }
}


async function loadSelectedGameLeaderboard() {
  const key = gameSelectedKey || "chess";
  const viewModule = activeGameViewModule();
  let path = viewModule?.leaderboardPath ? viewModule.leaderboardPath(legacyGameRuntime()) : "/games/chess/leaderboard";
  if (isLocalGameModuleAvailable(key)) {
    path = `/games/${encodeURIComponent(key)}/solo-leaderboard`;
  }
  const data = await gameRequest(path);
  gameState.leaderboard = data.leaderboard || [];
  renderGameLeaderboard(data);
  const awardBtn = $("game-award-btn");
  if (awardBtn) awardBtn.style.display = currentUser === "root" && key === "chess" ? "" : "none";
  await loadChessRootDashboard().catch(() => {});
  renderGameMetaPanels();
  await loadSelectedGameDailyLeaderboard();
  return data;
}

async function submitSoloGameScore(gameKey, state) {
  if (!state || state.scoreSubmitted) return;
  state.scoreSubmitted = true;
  const rawElapsed = soloRawElapsedMs(state);
  const elapsed = soloElapsedMs(state);
  try {
    const json = await gameRequest(`/games/${encodeURIComponent(gameKey)}/solo-scores`, {
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
    recordGameOutcome(gameKey, {
      raw_elapsed_ms: rawElapsed,
      penalty_seconds: Number(state.penaltySeconds || 0),
      elapsed_ms: elapsed,
      difficulty: state.difficulty || "standard",
      puzzle_id: state.puzzleId || "",
      guess_count: Array.isArray(state.guesses) ? state.guesses.length : Number(state.guessCount || 0),
      score: Number(state.score || 0),
      lines: Number(state.lines || 0),
      combo: Number(state.maxCombo || state.combo || 0),
      boss: Number(state.bossDefeated || state.bossCount || 0),
      weapon: Number(state.weaponLevel || 0),
      graze: Number(state.graze || 0),
      wave: Number(state.wave || 0),
      accuracy: Number(state.shots ? Math.round((Number(state.hits || 0) / Number(state.shots || 1)) * 100) : 0),
      survive: Number(state.health || state.lives || 0) > 0 ? 1 : 0,
      clean: !Number(state.penaltySeconds || 0) && !Number(state.mistakes || 0),
      maxTile: Number(state.maxTile || 0),
      moves: Number(state.moves || 0),
      length: Number(state.maxLength || state.snake?.length || 0),
      powerup: Number(state.powerupsCollected || 0),
    }, json);
    showGameDailyRewardFeedback(json, "成績已送出");
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
  if (event.target?.closest?.("#game-fullscreen-btn, #fps-arena-fullscreen-btn")) {
    toggleGameFullscreen();
    return;
  }
  const shareBtn = event.target?.closest?.("[data-game-share-text]");
  if (shareBtn) {
    const text = shareBtn.dataset.gameShareText || "";
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(
        () => setGameMsg("分享文字已複製", true),
        () => setGameMsg(text, true),
      );
    } else {
      setGameMsg(text, true);
    }
    return;
  }
  const localGameModuleAction = event.target?.closest?.("#local-module-game-panel [data-action]");
  if (localGameModuleAction && localGameModuleActiveApi?.onAction) {
    localGameModuleActiveApi.onAction(localGameModuleAction.dataset.action || "");
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
  const control = event.target?.closest?.("#local-module-game-controls button");
  if (!control || !localGameModuleActiveApi?.onControl) return;
  event.preventDefault();
  localGameModulePressedControl = control;
  localGameModuleActiveApi.onControl(control, true);
});

document.addEventListener("pointerup", () => {
  if (!localGameModulePressedControl || !localGameModuleActiveApi?.onControl) {
    localGameModulePressedControl = null;
    return;
  }
  if (localGameModulePressedControl.dataset.hold) {
    localGameModuleActiveApi.onControl(localGameModulePressedControl, false);
  }
  localGameModulePressedControl = null;
});

document.addEventListener("pointercancel", () => {
  if (localGameModulePressedControl?.dataset.hold && localGameModuleActiveApi?.onControl) {
    localGameModuleActiveApi.onControl(localGameModulePressedControl, false);
  }
  localGameModulePressedControl = null;
});

document.addEventListener("touchstart", (event) => {
  const root = event.target?.closest?.("#local-module-game-root");
  if (!root) return;
  const touch = event.changedTouches[0];
  localGameModuleTouchStart = touch ? { x: touch.clientX, y: touch.clientY } : null;
}, { passive: true });

document.addEventListener("touchend", (event) => {
  const root = event.target?.closest?.("#local-module-game-root");
  if (!root || !localGameModuleTouchStart || !localGameModuleActiveApi?.onKey) return;
  const touch = event.changedTouches[0];
  if (!touch) return;
  const dx = touch.clientX - localGameModuleTouchStart.x;
  const dy = touch.clientY - localGameModuleTouchStart.y;
  localGameModuleTouchStart = null;
  if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
  const key = Math.abs(dx) > Math.abs(dy)
    ? (dx > 0 ? "ArrowRight" : "ArrowLeft")
    : (dy > 0 ? "ArrowDown" : "ArrowUp");
  localGameModuleActiveApi.onKey({ key, preventDefault() {} }, true);
  if (localGameModuleSwipeMode === "hold") {
    window.setTimeout(() => {
      if (!localGameModuleActiveApi?.onKey) return;
      localGameModuleActiveApi.onKey({ key, preventDefault() {} }, false);
    }, 90);
  }
}, { passive: false });

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
  if (!editing && isLocalGameModuleAvailable(gameSelectedKey) && localGameModuleActiveApi?.onKey) {
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " "].includes(event.key)) event.preventDefault();
    localGameModuleActiveApi.onKey(event, true);
  }
});

document.addEventListener("keyup", (event) => {
  if (dispatchActiveGameViewEvent("keyup", event)) {
    return;
  }
  if (isLocalGameModuleAvailable(gameSelectedKey) && localGameModuleActiveApi?.onKey) {
    localGameModuleActiveApi.onKey(event, false);
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

document.addEventListener("fullscreenchange", updateGameFullscreenButtons);
