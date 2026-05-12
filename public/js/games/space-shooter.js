'use strict';

let spaceShooterState = null;
let spaceShooterLoopTimer = null;

function clearSpaceShooterLoop() {
  if (spaceShooterLoopTimer) {
    clearInterval(spaceShooterLoopTimer);
    spaceShooterLoopTimer = null;
  }
}

function startSpaceShooterGame() {
  clearSpaceShooterLoop();
  spaceShooterState = {
    status: "active",
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: "standard",
    puzzleId: "space-shooter-standard",
    score: 0,
    lives: 3,
    tick: 0,
    playerX: 180,
    bullets: [],
    enemies: [],
    keys: {},
    lastShotTick: -20,
  };
  renderSpaceShooterBoard();
  ensureSoloGameTimer();
  spaceShooterLoopTimer = setInterval(tickSpaceShooterGame, 50);
  updateSpaceShooterStatus("出擊。方向鍵或 A/D 移動，空白鍵射擊。");
}

function finishSpaceShooterGame() {
  if (!spaceShooterState || spaceShooterState.status === "finished") return;
  spaceShooterState.status = "finished";
  spaceShooterState.completedAt = Date.now();
  clearSpaceShooterLoop();
  renderSpaceShooterBoard();
  updateSpaceShooterStatus();
  stopSoloGameTimerIfIdle();
  if (Number(spaceShooterState.score || 0) > 0) {
    submitSoloGameScore("space_shooter", spaceShooterState);
  }
  setGameMsg(`宇宙戰機結束，分數 ${Number(spaceShooterState.score || 0).toLocaleString()}`, true);
}

function tickSpaceShooterGame() {
  const state = spaceShooterState;
  if (!state || state.status !== "active") return;
  state.tick += 1;
  const movingLeft = state.keys.ArrowLeft || state.keys.a || state.keys.A;
  const movingRight = state.keys.ArrowRight || state.keys.d || state.keys.D;
  if (movingLeft) state.playerX = Math.max(18, state.playerX - 7);
  if (movingRight) state.playerX = Math.min(342, state.playerX + 7);
  if ((state.keys[" "] || state.keys.Spacebar) && state.tick - state.lastShotTick >= 5) {
    state.bullets.push({ x: state.playerX, y: 448 });
    state.lastShotTick = state.tick;
  }
  if (state.tick % Math.max(14, 34 - Math.floor(state.score / 250)) === 0) {
    state.enemies.push({ x: 24 + Math.random() * 312, y: -18, hp: 1 });
  }
  state.bullets.forEach((bullet) => { bullet.y -= 12; });
  state.enemies.forEach((enemy) => { enemy.y += 3.2 + Math.min(3, state.score / 600); });
  state.bullets = state.bullets.filter((bullet) => bullet.y > -12);
  const remainingEnemies = [];
  state.enemies.forEach((enemy) => {
    let hit = false;
    state.bullets.forEach((bullet) => {
      if (hit) return;
      if (Math.abs(bullet.x - enemy.x) < 18 && Math.abs(bullet.y - enemy.y) < 18) {
        bullet.y = -100;
        hit = true;
        state.score += 25;
      }
    });
    if (hit) return;
    if (Math.abs(state.playerX - enemy.x) < 24 && enemy.y > 420) {
      state.lives -= 1;
      return;
    }
    if (enemy.y > 540) {
      state.lives -= 1;
      return;
    }
    remainingEnemies.push(enemy);
  });
  state.enemies = remainingEnemies;
  if (state.lives <= 0) {
    finishSpaceShooterGame();
    return;
  }
  renderSpaceShooterBoard();
  updateSpaceShooterStatus();
}

function nudgeSpaceShooter(dx) {
  const state = spaceShooterState;
  if (!state || state.status !== "active") return;
  state.playerX = Math.max(18, Math.min(342, state.playerX + dx));
  renderSpaceShooterBoard();
}

function shootSpaceShooter() {
  const state = spaceShooterState;
  if (!state || state.status !== "active") return;
  if (state.tick - state.lastShotTick < 2) return;
  state.bullets.push({ x: state.playerX, y: 448 });
  state.lastShotTick = state.tick;
  renderSpaceShooterBoard();
}

function renderSpaceShooterBoard() {
  const canvas = $("space-shooter-board");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#07111f";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "rgba(255,255,255,.18)";
  for (let i = 0; i < 54; i += 1) {
    const x = (i * 67 + (spaceShooterState?.tick || 0) * 2) % canvas.width;
    const y = (i * 41 + (spaceShooterState?.tick || 0) * 3) % canvas.height;
    ctx.fillRect(x, y, 2, 2);
  }
  if (!spaceShooterState) {
    ctx.fillStyle = "rgba(214,226,240,.75)";
    ctx.font = "16px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("按「開始」後出擊", canvas.width / 2, canvas.height / 2);
    return;
  }
  const state = spaceShooterState;
  ctx.fillStyle = "#4d7dff";
  ctx.beginPath();
  ctx.moveTo(state.playerX, 430);
  ctx.lineTo(state.playerX - 18, 470);
  ctx.lineTo(state.playerX + 18, 470);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = "#22c79a";
  state.bullets.forEach((bullet) => ctx.fillRect(bullet.x - 2, bullet.y - 10, 4, 12));
  ctx.fillStyle = "#ff4f6d";
  state.enemies.forEach((enemy) => {
    ctx.beginPath();
    ctx.moveTo(enemy.x, enemy.y + 18);
    ctx.lineTo(enemy.x - 16, enemy.y - 12);
    ctx.lineTo(enemy.x + 16, enemy.y - 12);
    ctx.closePath();
    ctx.fill();
  });
  if (state.status === "finished") {
    ctx.fillStyle = "rgba(7,17,31,.72)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ff4f6d";
    ctx.font = "bold 36px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("GAME OVER", canvas.width / 2, canvas.height / 2 - 18);
    ctx.fillStyle = "rgba(214,226,240,.85)";
    ctx.font = "15px sans-serif";
    ctx.fillText(`分數 ${Number(state.score || 0).toLocaleString()}`, canvas.width / 2, canvas.height / 2 + 18);
  }
}

function updateSpaceShooterStatus(prefix = "") {
  const status = $("space-shooter-status");
  if (!status) return;
  if (!spaceShooterState) {
    status.textContent = "按開始後出擊，最高分列入排行榜。";
    return;
  }
  const score = Number(spaceShooterState.score || 0).toLocaleString();
  const time = formatSoloGameTime(soloElapsedMs(spaceShooterState));
  if (spaceShooterState.status === "finished") {
    status.textContent = `任務結束 · 分數 ${score} · 時間 ${time}`;
  } else {
    status.textContent = `${prefix ? `${prefix} ` : ""}分數 ${score} · 生命 ${spaceShooterState.lives} · 時間 ${time}`;
  }
}

(function () {
  window.registerHackmeGameViewModule?.({
    key: "space_shooter",
    panelIds: ["space-shooter-game-panel"],
    ensure() {
      if (!spaceShooterState) {
        renderSpaceShooterBoard();
        updateSpaceShooterStatus();
      }
    },
    updateStatus() {
      updateSpaceShooterStatus();
    },
    isActive() {
      return !!spaceShooterState && spaceShooterState.status === "active";
    },
    leaderboardPath() {
      return "/games/space_shooter/solo-leaderboard";
    },
    dispatch(type, event) {
      if (type === "click" && event.target?.closest?.("#space-shooter-new-btn")) {
        startSpaceShooterGame();
        return true;
      }
      const touchBtn = type === "click" ? event.target?.closest?.("[data-game-touch]") : null;
      const action = touchBtn?.dataset.gameTouch || "";
      if (action === "shooter-left") { nudgeSpaceShooter(-34); return true; }
      if (action === "shooter-right") { nudgeSpaceShooter(34); return true; }
      if (action === "shooter-fire") { shootSpaceShooter(); return true; }
      if (type === "keydown" && spaceShooterState?.status === "active" && ["ArrowLeft", "ArrowRight", " ", "a", "A", "d", "D"].includes(event.key)) {
        event.preventDefault();
        spaceShooterState.keys[event.key] = true;
        return true;
      }
      if (type === "keyup" && spaceShooterState?.keys && ["ArrowLeft", "ArrowRight", " ", "a", "A", "d", "D"].includes(event.key)) {
        spaceShooterState.keys[event.key] = false;
        return true;
      }
      return false;
    },
  });
}());
