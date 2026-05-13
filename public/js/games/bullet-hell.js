'use strict';

(function () {
  const { clamp, registerScore } = window.HACKME_LOCAL_GAME_HELPERS;
  const WIDTH = 360;
  const HEIGHT = 520;
  const PLAYER_Y = 438;
  const PLAYER_SPEED = 4.6;
  const FOCUS_SPEED = 2.35;
  const BULLET_LIMIT = 360;

  function distSq(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return dx * dx + dy * dy;
  }

  function bulletHellRandom(state) {
    return typeof state?.rng === "function" ? state.rng() : Math.random();
  }

  function addBulletHellParticles(state, x, y, color, count = 12) {
    for (let i = 0; i < count; i += 1) {
      const angle = bulletHellRandom(state) * Math.PI * 2;
      const speed = 1.2 + bulletHellRandom(state) * 3.4;
      state.particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 20 + bulletHellRandom(state) * 18,
        color,
      });
    }
  }

  function spawnBulletHellEnemy(state) {
    const patternPhase = (state.tick + state.wave * 83) % 420;
    const pattern = patternPhase < 150 ? "fan" : patternPhase < 290 ? "ring" : "spiral";
    state.enemies.push({
      x: 42 + bulletHellRandom(state) * (WIDTH - 84),
      y: -24,
      vx: (bulletHellRandom(state) - 0.5) * (1.4 + state.wave * 0.08),
      vy: 0.55 + Math.min(1.35, (state.score + state.wave * 120) / 4500),
      hp: (pattern === "ring" ? 4 : 3) + Math.floor(state.wave / 5),
      phase: bulletHellRandom(state) * Math.PI * 2,
      fireAt: state.tick + 24,
      pattern,
    });
  }

  function emitBulletHellPattern(state, enemy) {
    const speed = 1.75 + Math.min(1.35, state.score / 9000) + state.wave * 0.025;
    if (enemy.pattern === "ring") {
      const count = 12 + Math.min(6, Math.floor(state.score / 3200));
      for (let i = 0; i < count; i += 1) {
        const angle = (Math.PI * 2 * i) / count + state.tick * 0.018;
        state.bullets.push({
          x: enemy.x,
          y: enemy.y + 12,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          r: 4.6,
          color: "#f97316",
        });
      }
      return;
    }
    if (enemy.pattern === "spiral") {
      for (let i = 0; i < 4; i += 1) {
        const angle = enemy.phase + i * (Math.PI / 2) + state.tick * 0.04;
        state.bullets.push({
          x: enemy.x,
          y: enemy.y + 12,
          vx: Math.cos(angle) * speed * 0.95,
          vy: Math.sin(angle) * speed * 0.95 + 0.72,
          r: 4,
          color: "#a78bfa",
        });
      }
      return;
    }
    const toPlayer = Math.atan2(state.player.y - enemy.y, state.player.x - enemy.x);
    for (let i = -2; i <= 2; i += 1) {
      const angle = toPlayer + i * 0.19;
      state.bullets.push({
        x: enemy.x,
        y: enemy.y + 12,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        r: 4.2,
        color: "#fb7185",
      });
    }
  }

  function fireBulletHellPlayerShots(state) {
    const level = Math.max(1, Math.min(4, Number(state.shotLevel || 1)));
    state.shots.push({ x: state.player.x - 7, y: state.player.y - 14, vx: -0.1, vy: -8.8 });
    state.shots.push({ x: state.player.x + 7, y: state.player.y - 14, vx: 0.1, vy: -8.8 });
    if (level >= 2) state.shots.push({ x: state.player.x, y: state.player.y - 18, vx: 0, vy: -9.4 });
    if (level >= 3) {
      state.shots.push({ x: state.player.x - 13, y: state.player.y - 10, vx: -0.9, vy: -8.4 });
      state.shots.push({ x: state.player.x + 13, y: state.player.y - 10, vx: 0.9, vy: -8.4 });
    }
    if (level >= 4) {
      state.shots.push({ x: state.player.x - 20, y: state.player.y - 6, vx: -1.35, vy: -8.1 });
      state.shots.push({ x: state.player.x + 20, y: state.player.y - 6, vx: 1.35, vy: -8.1 });
    }
  }

  function spawnBulletHellPowerup(state, x, y, type = "") {
    const roll = bulletHellRandom(state);
    const powerType = type || (roll < 0.62 ? "power" : roll < 0.86 ? "bomb" : "life");
    state.powerups.push({
      x,
      y,
      vx: (bulletHellRandom(state) - 0.5) * 0.8,
      vy: 1.1 + bulletHellRandom(state) * 0.6,
      phase: bulletHellRandom(state) * Math.PI * 2,
      type: powerType,
    });
  }

  function collectBulletHellPowerup(api, state, powerup) {
    if (powerup.type === "power") {
      state.shotLevel = Math.min(4, Number(state.shotLevel || 1) + 1);
      state.score += 80;
      if (state.shotLevel >= 4) api.achievement?.("max-power", "彈幕滿火力", "取得火力升級到最高階。");
      return;
    }
    if (powerup.type === "bomb") {
      state.bombs = Math.min(6, state.bombs + 1);
      state.score += 55;
      return;
    }
    state.lives = Math.min(5, state.lives + 1);
    state.score += 120;
  }

  function spawnBulletHellBoss(state) {
    if (state.boss) return;
    const maxHp = 58 + state.wave * 18;
    state.boss = {
      x: WIDTH / 2,
      y: 72,
      vx: 1.05 + Math.min(1.4, state.wave * 0.09),
      hp: maxHp,
      maxHp,
      phase: 0,
      fireAt: state.tick + 36,
    };
  }

  function emitBulletHellBossPattern(state, boss) {
    const count = 18 + Math.min(14, state.wave * 2);
    const speed = 1.55 + Math.min(1.35, state.wave * 0.08);
    for (let i = 0; i < count; i += 1) {
      const angle = (Math.PI * 2 * i) / count + boss.phase;
      state.bullets.push({
        x: boss.x,
        y: boss.y + 24,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed + 0.55,
        r: 4.4,
        color: i % 2 ? "#f472b6" : "#38bdf8",
      });
    }
    const toPlayer = Math.atan2(state.player.y - boss.y, state.player.x - boss.x);
    for (let i = -1; i <= 1; i += 1) {
      const angle = toPlayer + i * 0.16;
      state.bullets.push({
        x: boss.x,
        y: boss.y + 28,
        vx: Math.cos(angle) * (speed + 0.55),
        vy: Math.sin(angle) * (speed + 0.55),
        r: 5,
        color: "#fde047",
      });
    }
  }

  function finishBulletHell(api) {
    const state = api._bulletHellState;
    if (!state || state.status === "finished") return;
    state.status = "finished";
    state.completedAt = Date.now();
    clearInterval(state.timer);
    state.timer = null;
    drawBulletHell(state);
    api.status(`結束 · 分數 ${Number(state.score || 0).toLocaleString()} · 擦彈 ${state.graze}`);
    if (Number(state.score || 0) > 0) api.achievement?.("score-posted", "彈幕出擊", "完成一局彈幕挑戰。");
    registerScore(api, Math.round(state.score || 0), state, state.dailyChallenge?.difficulty || "standard");
  }

  function bombBulletHell(state) {
    if (state.bombs <= 0 || state.status !== "active") return;
    state.bombs -= 1;
    state.score += Math.min(900, state.bullets.length * 5);
    state.bullets = [];
    state.invulnerableUntil = state.tick + 105;
    addBulletHellParticles(state, state.player.x, state.player.y, "#93c5fd", 38);
  }

  function updateBulletHell(api) {
    const state = api._bulletHellState;
    if (!state || state.status !== "active" || state.paused) return;
    state.tick += 1;
    state.score += 0.12;

    const focus = state.keys.focus;
    const speed = focus ? FOCUS_SPEED : PLAYER_SPEED;
    const dx = (state.keys.left ? -1 : 0) + (state.keys.right ? 1 : 0);
    const dy = (state.keys.up ? -1 : 0) + (state.keys.down ? 1 : 0);
    const length = Math.hypot(dx, dy) || 1;
    state.player.x = clamp(state.player.x + (dx / length) * speed, 14, WIDTH - 14);
    state.player.y = clamp(state.player.y + (dy / length) * speed, 44, HEIGHT - 24);

    if (state.tick % Math.max(4, 6 - Math.floor((state.shotLevel || 1) / 2)) === 0) fireBulletHellPlayerShots(state);
    if (state.tick % 720 === 0) {
      state.wave += 1;
      if (state.wave >= 5) api.achievement?.("wave-five", "第五波生還", "撐到第 5 波彈幕。");
    }
    if (!state.boss && state.wave >= state.nextBossWave) spawnBulletHellBoss(state);
    if (!state.boss && state.tick % Math.max(28, 82 - Math.floor(state.score / 900) - state.wave * 2) === 0) spawnBulletHellEnemy(state);

    state.shots.forEach((shot) => {
      shot.x += shot.vx || 0;
      shot.y += shot.vy;
    });
    state.bullets.forEach((bullet) => {
      bullet.x += bullet.vx;
      bullet.y += bullet.vy;
    });
    state.enemies.forEach((enemy) => {
      enemy.phase += 0.035;
      enemy.x += enemy.vx + Math.sin(enemy.phase) * 0.7;
      enemy.y += enemy.vy;
      if (enemy.x < 24 || enemy.x > WIDTH - 24) enemy.vx *= -1;
      if (state.tick >= enemy.fireAt) {
        emitBulletHellPattern(state, enemy);
        enemy.fireAt = state.tick + Math.max(34, 68 - Math.floor(state.score / 1000));
      }
    });
    if (state.boss) {
      const boss = state.boss;
      boss.phase += 0.045;
      boss.x += boss.vx;
      if (boss.x < 58 || boss.x > WIDTH - 58) boss.vx *= -1;
      if (state.tick >= boss.fireAt) {
        emitBulletHellBossPattern(state, boss);
        boss.fireAt = state.tick + Math.max(30, 62 - state.wave * 2);
      }
    }

    for (const shot of state.shots) {
      if (state.boss && shot.y > -20 && distSq(shot, state.boss) < 44 * 44) {
        shot.y = -100;
        state.boss.hp -= 1;
        state.score += 18;
        addBulletHellParticles(state, shot.x, shot.y, "#bae6fd", 2);
        continue;
      }
      for (const enemy of state.enemies) {
        if (shot.y < -20 || distSq(shot, enemy) > 26 * 26) continue;
        shot.y = -100;
        enemy.hp -= 1;
        state.score += 24;
        addBulletHellParticles(state, enemy.x, enemy.y, "#22c55e", 3);
      }
    }
    if (state.boss?.hp <= 0) {
      const defeated = state.boss;
      state.score += 900 + state.wave * 120;
      state.nextBossWave = state.wave + 3;
      state.boss = null;
      state.bossDefeated = Number(state.bossDefeated || 0) + 1;
      api.achievement?.("boss-down", "Boss 擊破", "擊破彈幕 Boss。");
      addBulletHellParticles(state, defeated.x, defeated.y, "#fde047", 54);
      spawnBulletHellPowerup(state, defeated.x - 26, defeated.y + 14, "power");
      spawnBulletHellPowerup(state, defeated.x, defeated.y + 20, "bomb");
      spawnBulletHellPowerup(state, defeated.x + 26, defeated.y + 14, "power");
    }
    state.enemies = state.enemies.filter((enemy) => {
      if (enemy.hp > 0 && enemy.y < HEIGHT + 36) return true;
      state.score += enemy.hp <= 0 ? 120 : 0;
      addBulletHellParticles(state, enemy.x, enemy.y, enemy.hp <= 0 ? "#facc15" : "#64748b", 18);
      if (enemy.hp <= 0 && bulletHellRandom(state) < 0.15) spawnBulletHellPowerup(state, enemy.x, enemy.y);
      return false;
    });

    state.powerups.forEach((powerup) => {
      powerup.phase += 0.08;
      powerup.x = clamp(powerup.x + powerup.vx, 18, WIDTH - 18);
      powerup.y += powerup.vy;
    });
    state.powerups = state.powerups.filter((powerup) => {
      if (distSq(powerup, state.player) < 22 * 22) {
        collectBulletHellPowerup(api, state, powerup);
        addBulletHellParticles(state, powerup.x, powerup.y, "#d9f99d", 12);
        return false;
      }
      return powerup.y < HEIGHT + 26;
    });

    const hitRadius = focus ? 4.2 : 6.2;
    for (const bullet of state.bullets) {
      const range = Math.sqrt(distSq(bullet, state.player));
      if (range < hitRadius + bullet.r && state.tick > state.invulnerableUntil) {
        state.lives -= 1;
        state.invulnerableUntil = state.tick + 150;
        addBulletHellParticles(state, state.player.x, state.player.y, "#ff4f6d", 28);
        if (state.lives <= 0) {
          finishBulletHell(api);
          return;
        }
      } else if (!bullet.grazed && range < 22) {
        bullet.grazed = true;
        state.graze += 1;
        state.score += 6;
      }
    }

    if (state.bullets.length > BULLET_LIMIT) state.bullets.splice(0, state.bullets.length - BULLET_LIMIT);
    state.bullets = state.bullets.filter((bullet) => bullet.x > -24 && bullet.x < WIDTH + 24 && bullet.y > -32 && bullet.y < HEIGHT + 32);
    state.shots = state.shots.filter((shot) => shot.y > -30 && shot.x > -30 && shot.x < WIDTH + 30);
    state.particles.forEach((particle) => {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.035;
      particle.life -= 1;
    });
    state.particles = state.particles.filter((particle) => particle.life > 0);
    drawBulletHell(state);
    api.status(`Wave ${state.wave} · 分數 ${Number(Math.round(state.score)).toLocaleString()} · 生命 ${state.lives} · Bomb ${state.bombs} · 火力 ${state.shotLevel} · 擦彈 ${state.graze}`);
  }

  function drawBulletHell(state) {
    const ctx = state.ctx;
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "#06111f";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "rgba(148,163,184,.16)";
    for (let i = 0; i < 70; i += 1) {
      const x = (i * 47 + state.tick * 0.8) % WIDTH;
      const y = (i * 61 + state.tick * 1.35) % HEIGHT;
      ctx.fillRect(x, y, 2, 2);
    }
    ctx.strokeStyle = "rgba(56,189,248,.2)";
    ctx.strokeRect(14, 28, WIDTH - 28, HEIGHT - 42);

    state.shots.forEach((shot) => {
      ctx.fillStyle = "#86efac";
      ctx.fillRect(shot.x - 2, shot.y - 12, 4, 15);
    });
    state.enemies.forEach((enemy) => {
      ctx.save();
      ctx.translate(enemy.x, enemy.y);
      ctx.rotate(Math.sin(enemy.phase) * 0.16);
      ctx.fillStyle = enemy.pattern === "ring" ? "#f97316" : enemy.pattern === "spiral" ? "#a78bfa" : "#fb7185";
      ctx.beginPath();
      ctx.moveTo(0, 18);
      ctx.lineTo(-18, -12);
      ctx.lineTo(18, -12);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    });
    if (state.boss) {
      const boss = state.boss;
      ctx.save();
      ctx.translate(boss.x, boss.y);
      ctx.rotate(Math.sin(boss.phase) * 0.08);
      ctx.fillStyle = "#db2777";
      ctx.beginPath();
      ctx.moveTo(0, 30);
      ctx.lineTo(-44, 0);
      ctx.lineTo(-24, -26);
      ctx.lineTo(24, -26);
      ctx.lineTo(44, 0);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "#fef3c7";
      ctx.fillRect(-16, -4, 32, 8);
      ctx.restore();
      ctx.fillStyle = "rgba(15,23,42,.74)";
      ctx.fillRect(50, 34, WIDTH - 100, 8);
      ctx.fillStyle = "#f472b6";
      ctx.fillRect(50, 34, (WIDTH - 100) * Math.max(0, boss.hp / boss.maxHp), 8);
    }
    state.powerups.forEach((powerup) => {
      ctx.save();
      ctx.translate(powerup.x, powerup.y);
      ctx.rotate(powerup.phase);
      ctx.fillStyle = powerup.type === "power" ? "#86efac" : powerup.type === "bomb" ? "#93c5fd" : "#fef08a";
      ctx.beginPath();
      ctx.arc(0, 0, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.7)";
      ctx.strokeRect(-6, -6, 12, 12);
      ctx.restore();
    });
    state.bullets.forEach((bullet) => {
      ctx.beginPath();
      ctx.arc(bullet.x, bullet.y, bullet.r, 0, Math.PI * 2);
      ctx.fillStyle = bullet.color;
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.44)";
      ctx.stroke();
    });
    state.particles.forEach((particle) => {
      ctx.globalAlpha = Math.max(0, Math.min(1, particle.life / 24));
      ctx.fillStyle = particle.color;
      ctx.fillRect(particle.x - 2, particle.y - 2, 4, 4);
      ctx.globalAlpha = 1;
    });

    const flicker = state.tick < state.invulnerableUntil && state.tick % 10 < 5;
    if (!flicker) {
      ctx.save();
      ctx.translate(state.player.x, state.player.y);
      ctx.fillStyle = "#38bdf8";
      ctx.beginPath();
      ctx.moveTo(0, -18);
      ctx.lineTo(-13, 16);
      ctx.lineTo(0, 9);
      ctx.lineTo(13, 16);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "#f8fafc";
      ctx.beginPath();
      ctx.arc(0, 0, state.keys.focus ? 4.2 : 6.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    ctx.fillStyle = "rgba(226,232,240,.86)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`wave ${state.wave} score ${Number(Math.round(state.score)).toLocaleString()}`, 18, 20);
    ctx.fillText(`life ${state.lives} bomb ${state.bombs} power ${state.shotLevel}`, 184, 20);
    if (state.status === "finished") {
      ctx.fillStyle = "rgba(7,17,31,.76)";
      ctx.fillRect(34, 196, WIDTH - 68, 112);
      ctx.fillStyle = "#ff4f6d";
      ctx.font = "700 28px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("BULLET OVER", WIDTH / 2, 238);
      ctx.fillStyle = "rgba(226,232,240,.9)";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText(`分數 ${Number(Math.round(state.score)).toLocaleString()} · 擦彈 ${state.graze}`, WIDTH / 2, 266);
      ctx.textAlign = "start";
    }
  }

  function startBulletHell(api) {
    if (api._bulletHellState?.timer) clearInterval(api._bulletHellState.timer);
    const canvas = api.root.querySelector("canvas");
    const dailyChallenge = api.dailyChallenge?.() || null;
    const state = {
      canvas,
      ctx: canvas.getContext("2d"),
      status: "active",
      paused: false,
      startedAt: Date.now(),
      completedAt: null,
      score: 0,
      lives: 3,
      bombs: 3,
      graze: 0,
      wave: 1,
      nextBossWave: 3,
      shotLevel: 1,
      tick: 0,
      invulnerableUntil: 120,
      player: { x: WIDTH / 2, y: PLAYER_Y },
      keys: { left: false, right: false, up: false, down: false, focus: false },
      bullets: [],
      shots: [],
      enemies: [],
      powerups: [],
      particles: [],
      boss: null,
      bossDefeated: 0,
      dailyChallenge,
      rng: dailyChallenge?.seed ? window.createHackmeGameSeededRandom?.(dailyChallenge.seed) : null,
      timer: null,
    };
    api._bulletHellState = state;
    drawBulletHell(state);
    api.status(`${dailyChallenge?.label || "彈幕開始"}。方向鍵/WASD 移動，Shift 精密移動，X 使用 Bomb。`);
    state.timer = setInterval(() => updateBulletHell(api), 16);
  }

  function showBulletHellReady(api) {
    if (api._bulletHellState?.timer) clearInterval(api._bulletHellState.timer);
    api._bulletHellState = null;
    const canvas = api.root.querySelector("canvas");
    const ctx = canvas?.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#06111f";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.strokeStyle = "rgba(56,189,248,.2)";
    ctx.strokeRect(14, 28, WIDTH - 28, HEIGHT - 42);
    for (let i = 0; i < 80; i += 1) {
      ctx.fillStyle = i % 3 ? "rgba(56,189,248,.22)" : "rgba(244,114,182,.28)";
      ctx.beginPath();
      ctx.arc(22 + (i * 47) % (WIDTH - 44), 50 + (i * 61) % (HEIGHT - 92), 2 + (i % 4), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.textAlign = "center";
    ctx.fillStyle = "#e2e8f0";
    ctx.font = "700 26px system-ui, sans-serif";
    ctx.fillText("彈幕遊戲", WIDTH / 2, HEIGHT / 2 - 14);
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillStyle = "rgba(226,232,240,.82)";
    ctx.fillText("按開始後才會生成彈幕、計時與送成績", WIDTH / 2, HEIGHT / 2 + 16);
    ctx.textAlign = "start";
    api.status("待機 · 按開始進入彈幕挑戰。");
  }

  function setBulletHellInput(state, name, pressed) {
    if (!state) return;
    if (name === "left") state.keys.left = pressed;
    if (name === "right") state.keys.right = pressed;
    if (name === "up") state.keys.up = pressed;
    if (name === "down") state.keys.down = pressed;
    if (name === "focus") state.keys.focus = pressed;
  }

  function handleBulletHellKey(api, event, pressed) {
    const state = api._bulletHellState;
    if (!state || state.status !== "active") return;
    const key = event.key;
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "a", "A", "d", "D", "w", "W", "s", "S", "Shift", "x", "X"].includes(key)) {
      event.preventDefault?.();
    }
    if (key === "ArrowLeft" || key === "a" || key === "A") setBulletHellInput(state, "left", pressed);
    if (key === "ArrowRight" || key === "d" || key === "D") setBulletHellInput(state, "right", pressed);
    if (key === "ArrowUp" || key === "w" || key === "W") setBulletHellInput(state, "up", pressed);
    if (key === "ArrowDown" || key === "s" || key === "S") setBulletHellInput(state, "down", pressed);
    if (key === "Shift") setBulletHellInput(state, "focus", pressed);
    if ((key === "x" || key === "X") && pressed) bombBulletHell(state);
  }

  window.registerHackmeLocalGameModule("bullet_hell", {
    mount(api) {
      api.setTitle("彈幕遊戲");
      api.setSwipeMode?.("hold");
      api.root.innerHTML = `<canvas class="arcade-canvas tall bullet-hell-canvas" width="${WIDTH}" height="${HEIGHT}" aria-label="彈幕遊戲"></canvas>`;
      api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>
        <button class="btn game-mini-btn" type="button" data-action="pause">暫停</button>
        <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
      `);
      api.setControls(`
        <button class="btn game-mini-btn" type="button" data-hold="left">左</button>
        <button class="btn game-mini-btn" type="button" data-hold="up">上</button>
        <button class="btn game-mini-btn" type="button" data-hold="down">下</button>
        <button class="btn game-mini-btn" type="button" data-hold="right">右</button>
        <button class="btn game-mini-btn" type="button" data-hold="focus">精密</button>
        <button class="btn game-mini-btn btn-primary" type="button" data-bomb="1">Bomb</button>
      `);
      api.onAction = (action) => {
        if (action === "new") startBulletHell(api);
        if (action === "pause" && api._bulletHellState?.status === "active") {
          api._bulletHellState.paused = !api._bulletHellState.paused;
          api.status(api._bulletHellState.paused ? "暫停中。" : "繼續。");
        }
        if (action === "finish") finishBulletHell(api);
      };
      api.onControl = (target, pressed) => {
        const state = api._bulletHellState;
        if (target.dataset.bomb && pressed) bombBulletHell(state);
        setBulletHellInput(state, target.dataset.hold || "", pressed);
      };
      api.onKey = (event, pressed) => handleBulletHellKey(api, event, pressed);
      showBulletHellReady(api);
      return () => {
        if (api._bulletHellState?.timer) clearInterval(api._bulletHellState.timer);
        api._bulletHellState = null;
      };
    },
  });
}());
