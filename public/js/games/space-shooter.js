'use strict';

let spaceShooterState = null;
let spaceShooterLoopTimer = null;

function clearSpaceShooterLoop() {
  if (spaceShooterLoopTimer) {
    clearInterval(spaceShooterLoopTimer);
    spaceShooterLoopTimer = null;
  }
}

function spaceShooterRandom() {
  return typeof spaceShooterState?.rng === "function" ? spaceShooterState.rng() : Math.random();
}

function recordSpaceShooterAchievement(id, label, detail = "") {
  const result = window.recordHackmeGameAchievement?.("space_shooter", id, label, detail);
  if (result?.unlocked && typeof setGameMsg === "function") setGameMsg(`成就解鎖：${result.label}`, true);
  return result || { unlocked: false };
}

function damageSpaceShooterPlayer(state) {
  if (state.shield > 0) {
    state.shield -= 1;
    recordSpaceShooterAchievement("shield-save", "護盾救援", "用護盾擋下一次傷害。");
    return;
  }
  state.lives -= 1;
}

function fireSpaceShooterShots(state) {
  const level = Math.max(1, Math.min(4, Number(state.weaponLevel || 1)));
  const spreads = level === 1
    ? [{ x: 0, vx: 0 }]
    : level === 2
      ? [{ x: -7, vx: -0.35 }, { x: 7, vx: 0.35 }]
      : level === 3
        ? [{ x: -11, vx: -0.55 }, { x: 0, vx: 0 }, { x: 11, vx: 0.55 }]
        : [{ x: -15, vx: -0.8 }, { x: -5, vx: -0.25 }, { x: 5, vx: 0.25 }, { x: 15, vx: 0.8 }];
  spreads.forEach((shot) => {
    state.bullets.push({ x: state.playerX + shot.x, y: 448, vx: shot.vx, vy: -12.5, damage: 1 });
  });
}

function spawnSpaceShooterPowerup(state, x, y, type = "") {
  const roll = spaceShooterRandom();
  state.powerups.push({
    x,
    y,
    type: type || (roll < 0.62 ? "weapon" : roll < 0.86 ? "shield" : "life"),
    vy: 2.5,
    phase: spaceShooterRandom() * Math.PI * 2,
  });
}

function collectSpaceShooterPowerup(state, powerup) {
  if (powerup.type === "weapon") {
    state.weaponLevel = Math.min(4, state.weaponLevel + 1);
    state.score += 75;
    if (state.weaponLevel >= 4) recordSpaceShooterAchievement("weapon-max", "滿載火力", "宇宙戰機武器升級到最高階。");
    return;
  }
  if (powerup.type === "shield") {
    state.shield = Math.min(3, state.shield + 1);
    state.score += 50;
    return;
  }
  state.lives = Math.min(5, state.lives + 1);
  state.score += 100;
}

function spawnSpaceShooterBoss(state) {
  if (state.boss) return;
  const maxHp = 26 + state.bossCount * 10;
  state.boss = {
    x: 180,
    y: 70,
    vx: 3.1 + Math.min(2, state.bossCount * 0.35),
    hp: maxHp,
    maxHp,
    fireAt: state.tick + 12,
  };
  state.bossCount += 1;
  state.nextBossScore += 850 + state.bossCount * 180;
}

function startSpaceShooterGame() {
  clearSpaceShooterLoop();
  const dailyChallenge = window.hackmeGameDailyChallenge?.("space_shooter") || null;
  spaceShooterState = {
    status: "active",
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: dailyChallenge?.difficulty || "standard",
    puzzleId: dailyChallenge?.key || "space-shooter-standard",
    dailyChallenge,
    rng: dailyChallenge?.seed ? window.createHackmeGameSeededRandom?.(dailyChallenge.seed) : null,
    score: 0,
    lives: 3,
    shield: 0,
    weaponLevel: 1,
    tick: 0,
    playerX: 180,
    bullets: [],
    enemies: [],
    enemyBullets: [],
    powerups: [],
    boss: null,
    bossCount: 0,
    bossDefeated: 0,
    nextBossScore: 450,
    keys: {},
    lastShotTick: -20,
  };
  renderSpaceShooterBoard();
  ensureSoloGameTimer();
  spaceShooterLoopTimer = setInterval(tickSpaceShooterGame, 50);
  updateSpaceShooterStatus(`${dailyChallenge?.label || "出擊"}。方向鍵或 A/D 移動，空白鍵射擊。`);
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
    recordSpaceShooterAchievement("score-posted", "完成出擊", "完成一局宇宙戰機。");
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
    fireSpaceShooterShots(state);
    state.lastShotTick = state.tick;
  }
  if (!state.boss && state.score >= state.nextBossScore) spawnSpaceShooterBoss(state);
  if (state.tick % Math.max(12, 34 - Math.floor(state.score / 250)) === 0) {
    state.enemies.push({ x: 24 + spaceShooterRandom() * 312, y: -18, hp: state.score > 900 ? 2 : 1 });
  }
  state.bullets.forEach((bullet) => {
    bullet.x += bullet.vx || 0;
    bullet.y += bullet.vy || -12;
  });
  state.enemies.forEach((enemy) => { enemy.y += 3.2 + Math.min(3, state.score / 600); });
  if (state.boss) {
    state.boss.x += state.boss.vx;
    if (state.boss.x < 54 || state.boss.x > 306) state.boss.vx *= -1;
    if (state.tick >= state.boss.fireAt) {
      const toPlayer = Math.atan2(446 - state.boss.y, state.playerX - state.boss.x);
      for (let i = -1; i <= 1; i += 1) {
        const angle = toPlayer + i * 0.24;
        state.enemyBullets.push({
          x: state.boss.x,
          y: state.boss.y + 30,
          vx: Math.cos(angle) * 4.2,
          vy: Math.sin(angle) * 4.2,
        });
      }
      state.boss.fireAt = state.tick + Math.max(10, 18 - state.bossCount);
    }
  }
  state.enemyBullets.forEach((bullet) => {
    bullet.x += bullet.vx;
    bullet.y += bullet.vy;
  });
  state.powerups.forEach((powerup) => {
    powerup.phase += 0.12;
    powerup.y += powerup.vy;
  });
  state.bullets = state.bullets.filter((bullet) => bullet.y > -12 && bullet.x > -18 && bullet.x < 378);
  if (state.boss) {
    state.bullets.forEach((bullet) => {
      if (bullet.y < -20 || Math.abs(bullet.x - state.boss.x) > 48 || Math.abs(bullet.y - state.boss.y) > 34) return;
      bullet.y = -100;
      state.boss.hp -= bullet.damage || 1;
      state.score += 12;
    });
    if (state.boss.hp <= 0) {
      const defeated = state.boss;
      state.score += 650 + state.bossCount * 120;
      state.boss = null;
      state.bossDefeated += 1;
      recordSpaceShooterAchievement("boss-down", "旗艦擊破", "擊破宇宙戰機 Boss。");
      spawnSpaceShooterPowerup(state, defeated.x - 22, defeated.y + 22, "weapon");
      spawnSpaceShooterPowerup(state, defeated.x + 22, defeated.y + 22, "shield");
    }
  }
  const remainingEnemies = [];
  state.enemies.forEach((enemy) => {
    let destroyed = false;
    state.bullets.forEach((bullet) => {
      if (destroyed || bullet.y < -20) return;
      if (Math.abs(bullet.x - enemy.x) < 18 && Math.abs(bullet.y - enemy.y) < 18) {
        bullet.y = -100;
        enemy.hp -= bullet.damage || 1;
        state.score += 10;
        if (enemy.hp <= 0) {
          destroyed = true;
          state.score += 25;
          if (spaceShooterRandom() < 0.12) spawnSpaceShooterPowerup(state, enemy.x, enemy.y);
        }
      }
    });
    if (destroyed) return;
    if (Math.abs(state.playerX - enemy.x) < 24 && enemy.y > 420) {
      damageSpaceShooterPlayer(state);
      return;
    }
    if (enemy.y > 540) {
      damageSpaceShooterPlayer(state);
      return;
    }
    remainingEnemies.push(enemy);
  });
  state.enemies = remainingEnemies;
  state.enemyBullets = state.enemyBullets.filter((bullet) => {
    if (Math.abs(bullet.x - state.playerX) < 16 && Math.abs(bullet.y - 450) < 22) {
      damageSpaceShooterPlayer(state);
      return false;
    }
    return bullet.x > -20 && bullet.x < 380 && bullet.y > -20 && bullet.y < 540;
  });
  state.powerups = state.powerups.filter((powerup) => {
    if (Math.abs(powerup.x - state.playerX) < 26 && Math.abs(powerup.y - 448) < 30) {
      collectSpaceShooterPowerup(state, powerup);
      return false;
    }
    return powerup.y < 540;
  });
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
  fireSpaceShooterShots(state);
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
  if (state.shield > 0) {
    ctx.strokeStyle = "rgba(147,197,253,.7)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(state.playerX, 452, 28 + Math.sin(state.tick * 0.18) * 2, 0, Math.PI * 2);
    ctx.stroke();
    ctx.lineWidth = 1;
  }
  ctx.fillStyle = "#4d7dff";
  ctx.beginPath();
  ctx.moveTo(state.playerX, 430);
  ctx.lineTo(state.playerX - 18, 470);
  ctx.lineTo(state.playerX + 18, 470);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = "#22c79a";
  state.bullets.forEach((bullet) => ctx.fillRect(bullet.x - 2, bullet.y - 10, 4, 12));
  ctx.fillStyle = "#facc15";
  state.enemyBullets.forEach((bullet) => {
    ctx.beginPath();
    ctx.arc(bullet.x, bullet.y, 4.5, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = "#ff4f6d";
  state.enemies.forEach((enemy) => {
    ctx.beginPath();
    ctx.moveTo(enemy.x, enemy.y + 18);
    ctx.lineTo(enemy.x - 16, enemy.y - 12);
    ctx.lineTo(enemy.x + 16, enemy.y - 12);
    ctx.closePath();
    ctx.fill();
  });
  if (state.boss) {
    ctx.fillStyle = "#db2777";
    ctx.beginPath();
    ctx.moveTo(state.boss.x, state.boss.y + 34);
    ctx.lineTo(state.boss.x - 48, state.boss.y - 8);
    ctx.lineTo(state.boss.x - 24, state.boss.y - 30);
    ctx.lineTo(state.boss.x + 24, state.boss.y - 30);
    ctx.lineTo(state.boss.x + 48, state.boss.y - 8);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "rgba(15,23,42,.78)";
    ctx.fillRect(52, 28, canvas.width - 104, 8);
    ctx.fillStyle = "#fb7185";
    ctx.fillRect(52, 28, (canvas.width - 104) * Math.max(0, state.boss.hp / state.boss.maxHp), 8);
  }
  state.powerups.forEach((powerup) => {
    ctx.save();
    ctx.translate(powerup.x, powerup.y);
    ctx.rotate(powerup.phase);
    ctx.fillStyle = powerup.type === "weapon" ? "#86efac" : powerup.type === "shield" ? "#93c5fd" : "#fef08a";
    ctx.beginPath();
    ctx.arc(0, 0, 9, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,.72)";
    ctx.strokeRect(-6, -6, 12, 12);
    ctx.restore();
  });
  ctx.fillStyle = "rgba(226,232,240,.84)";
  ctx.font = "12px sans-serif";
  ctx.textAlign = "start";
  ctx.fillText(`weapon ${state.weaponLevel} shield ${state.shield}`, 12, 18);
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
    status.textContent = `任務結束 · 分數 ${score} · 武器 ${spaceShooterState.weaponLevel} · 時間 ${time}`;
  } else {
    status.textContent = `${prefix ? `${prefix} ` : ""}分數 ${score} · 生命 ${spaceShooterState.lives} · 護盾 ${spaceShooterState.shield} · 武器 ${spaceShooterState.weaponLevel} · 時間 ${time}`;
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
