'use strict';

(function () {
  const { clamp } = window.HACKME_LOCAL_GAME_HELPERS;
  const WIDTH = 720;
  const HEIGHT = 360;
  const GRAVITY = 0.72;
  const PLAYER_W = 22;
  const PLAYER_H = 46;
  const WORLD_ROOMS = 4;
  const ROOM_WIDTH = WIDTH;
  const WORLD_WIDTH = ROOM_WIDTH * WORLD_ROOMS;
  const MAG_SIZE = 9;
  const RELOAD_TICKS = 54;

  const MODES = [
    { key: "standard", label: "標準", enemyHp: 0, enemyShots: 0, reserve: 45 },
    { key: "rush", label: "突襲", enemyHp: 1, enemyShots: 10, reserve: 36 },
    { key: "survival", label: "生存", enemyHp: 2, enemyShots: 18, reserve: 30 },
  ];

  function stickmanRandom(state) {
    return typeof state?.rng === "function" ? state.rng() : Math.random();
  }

  function rectsOverlap(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  }

  function addStickmanParticles(state, x, y, color, count = 10) {
    for (let i = 0; i < count; i += 1) {
      const angle = stickmanRandom(state) * Math.PI * 2;
      const speed = 0.8 + stickmanRandom(state) * 2.8;
      state.particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 0.4,
        life: 16 + stickmanRandom(state) * 18,
        color,
      });
    }
  }

  function makeStickmanWorld() {
    return [
      { x: 0, y: 318, w: WORLD_WIDTH, h: 42, type: "ground" },
      { x: 130, y: 265, w: 126, h: 12 },
      { x: 344, y: 236, w: 112, h: 12 },
      { x: 570, y: 278, w: 118, h: 12 },
      { x: 802, y: 274, w: 136, h: 12 },
      { x: 1012, y: 232, w: 128, h: 12 },
      { x: 1216, y: 276, w: 132, h: 12 },
      { x: 1502, y: 258, w: 118, h: 12 },
      { x: 1710, y: 220, w: 118, h: 12 },
      { x: 1888, y: 282, w: 160, h: 12 },
      { x: 2206, y: 266, w: 150, h: 12 },
      { x: 2474, y: 230, w: 136, h: 12 },
      { x: 2660, y: 286, w: 150, h: 12 },
    ];
  }

  function makeStickmanCover() {
    return [
      { x: 412, y: 282, w: 24, h: 36 },
      { x: 910, y: 238, w: 28, h: 36 },
      { x: 1260, y: 240, w: 30, h: 36 },
      { x: 1836, y: 184, w: 26, h: 36 },
      { x: 2354, y: 230, w: 32, h: 36 },
    ];
  }

  function groundYAt(state, x) {
    const candidates = state.platforms.filter((platform) => x >= platform.x - 10 && x <= platform.x + platform.w + 10);
    const best = candidates.sort((a, b) => a.y - b.y).find((platform) => platform.y > 90);
    return best ? best.y : 318;
  }

  function spawnStickmanRoom(state, room) {
    if (state.spawnedRooms.has(room)) return;
    state.spawnedRooms.add(room);
    const mode = MODES[state.modeIndex] || MODES[0];
    const baseX = (room - 1) * ROOM_WIDTH;
    const enemyCount = room === WORLD_ROOMS ? 2 : 2 + Math.min(2, room);
    for (let i = 0; i < enemyCount; i += 1) {
      const x = baseX + 245 + i * 132 + stickmanRandom(state) * 44;
      const y = groundYAt(state, x) - 42;
      state.enemies.push({
        x,
        y,
        w: 22,
        h: 42,
        vx: i % 2 ? -0.78 : 0.78,
        baseSpeed: 0.78 + room * 0.04,
        facing: i % 2 ? -1 : 1,
        patrolMin: Math.max(baseX + 90, x - 82),
        patrolMax: Math.min(baseX + ROOM_WIDTH - 90, x + 96),
        hp: 3 + Math.floor(room / 2) + mode.enemyHp,
        maxHp: 3 + Math.floor(room / 2) + mode.enemyHp,
        fireAt: 42 + Math.floor(stickmanRandom(state) * 52),
        hurt: 0,
        aiState: "patrol",
        walkCycle: stickmanRandom(state) * Math.PI * 2,
        kind: "grunt",
      });
    }
    if (room === WORLD_ROOMS && !state.bossSpawned) {
      state.bossSpawned = true;
      state.enemies.push({
        x: baseX + 445,
        y: 318 - 64,
        w: 38,
        h: 64,
        vx: -0.72,
        baseSpeed: 0.72,
        facing: -1,
        patrolMin: baseX + 232,
        patrolMax: baseX + 650,
        hp: 22 + mode.enemyHp * 3,
        maxHp: 22 + mode.enemyHp * 3,
        fireAt: 24,
        hurt: 0,
        aiState: "patrol",
        walkCycle: stickmanRandom(state) * Math.PI * 2,
        kind: "boss",
      });
    }
  }

  function setStickmanStatus(api, state) {
    const accuracy = state.shots ? Math.round((state.hits / state.shots) * 100) : 0;
    const reload = state.reloadTicks > 0 ? " · 換彈中" : "";
    api.status(`${state.dailyChallenge?.label || MODES[state.modeIndex].label} · Room ${state.room}/${WORLD_ROOMS} · 分數 ${Math.round(state.score).toLocaleString()} · HP ${state.player.hp} · 彈藥 ${state.ammo}/${state.reserve} · 命中 ${accuracy}%${reload}`);
  }

  function playerRect(state) {
    const p = state.player;
    return { x: p.x, y: p.y, w: PLAYER_W, h: PLAYER_H };
  }

  function applyStickmanPhysics(state) {
    const p = state.player;
    const prevY = p.y;
    p.vy += GRAVITY;
    p.x = clamp(p.x + p.vx, 8, WORLD_WIDTH - PLAYER_W - 8);
    p.y += p.vy;
    p.grounded = false;

    const body = playerRect(state);
    for (const platform of state.platforms) {
      const wasAbove = prevY + PLAYER_H <= platform.y + 2;
      if (p.vy >= 0 && wasAbove && rectsOverlap(body, platform)) {
        p.y = platform.y - PLAYER_H;
        p.vy = 0;
        p.grounded = true;
        body.y = p.y;
      }
    }
    if (p.y > HEIGHT + 80) {
      p.hp = 0;
    }
  }

  function startStickmanReload(state) {
    if (state.reloadTicks > 0 || state.ammo >= MAG_SIZE || state.reserve <= 0) return;
    state.reloadTicks = RELOAD_TICKS;
  }

  function finishStickmanReload(state) {
    const needed = MAG_SIZE - state.ammo;
    const taken = Math.min(needed, state.reserve);
    state.ammo += taken;
    state.reserve -= taken;
    state.reloadTicks = 0;
    return taken > 0;
  }

  function fireStickmanShot(state) {
    if (state.status !== "active" || state.paused) return;
    if (state.reloadTicks > 0) return;
    if (state.ammo <= 0) {
      state.emptyReload = true;
      startStickmanReload(state);
      return;
    }
    if (state.tick < state.nextShotAt) return;
    state.nextShotAt = state.tick + 8;
    state.ammo -= 1;
    state.shots += 1;
    const p = state.player;
    const dir = p.facing || 1;
    state.playerShots.push({
      x: p.x + (dir > 0 ? PLAYER_W + 3 : -3),
      y: p.y + 19,
      vx: dir * 12.5,
      vy: (stickmanRandom(state) - 0.5) * 0.18,
      w: 8,
      h: 3,
      life: 70,
    });
    addStickmanParticles(state, p.x + (dir > 0 ? PLAYER_W + 5 : -5), p.y + 19, "#fef08a", 4);
  }

  function enemyFireStickmanShot(state, enemy) {
    const p = state.player;
    const fromX = enemy.x + enemy.w / 2;
    const fromY = enemy.y + enemy.h * 0.42;
    const toX = p.x + PLAYER_W / 2;
    const toY = p.y + PLAYER_H * 0.45;
    const angle = Math.atan2(toY - fromY, toX - fromX);
    const speed = enemy.kind === "boss" ? 5.8 : 4.8;
    const spread = enemy.kind === "boss" ? [-0.12, 0, 0.12] : [0];
    spread.forEach((offset) => {
      state.enemyShots.push({
        x: fromX,
        y: fromY,
        vx: Math.cos(angle + offset) * speed,
        vy: Math.sin(angle + offset) * speed,
        r: enemy.kind === "boss" ? 4 : 3,
        life: 118,
      });
    });
    addStickmanParticles(state, fromX, fromY, "#fb7185", 3);
  }

  function updateStickmanEnemies(state) {
    const mode = MODES[state.modeIndex] || MODES[0];
    const p = state.player;
    state.enemies.forEach((enemy) => {
      if (enemy.hurt > 0) enemy.hurt -= 1;
      const oldX = enemy.x;
      const dxToPlayer = (p.x + PLAYER_W / 2) - (enemy.x + enemy.w / 2);
      const distance = Math.abs(dxToPlayer);
      const sameLane = Math.abs(p.y - enemy.y) < 118;
      const seesPlayer = sameLane && distance < (enemy.kind === "boss" ? 620 : 470);
      const moveDir = dxToPlayer === 0 ? enemy.facing : Math.sign(dxToPlayer);
      const baseSpeed = enemy.baseSpeed || (enemy.kind === "boss" ? 0.72 : 0.78);
      const maxSpeed = enemy.kind === "boss" ? 1.38 : 1.18;
      if (seesPlayer) {
        enemy.aiState = distance < 92 ? "retreat" : distance > 235 ? "chase" : "hold";
        if (enemy.aiState === "retreat") enemy.vx -= moveDir * 0.065;
        if (enemy.aiState === "chase") enemy.vx += moveDir * 0.055;
        if (enemy.aiState === "hold") enemy.vx *= 0.86;
      } else {
        enemy.aiState = "patrol";
        const patrolDir = enemy.vx < 0 ? -1 : 1;
        enemy.vx += patrolDir * 0.018;
      }
      enemy.vx = clamp(enemy.vx, -maxSpeed, maxSpeed);
      if (enemy.aiState === "patrol" && Math.abs(enemy.vx) < baseSpeed) {
        enemy.vx = (enemy.vx < 0 ? -1 : 1) * baseSpeed;
      }
      enemy.x += enemy.vx;
      if (enemy.x < enemy.patrolMin) {
        enemy.x = enemy.patrolMin;
        enemy.vx = Math.abs(enemy.vx || baseSpeed);
      }
      if (enemy.x > enemy.patrolMax) {
        enemy.x = enemy.patrolMax;
        enemy.vx = -Math.abs(enemy.vx || baseSpeed);
      }
      enemy.y = groundYAt(state, enemy.x + enemy.w / 2) - enemy.h;
      enemy.facing = dxToPlayer < 0 ? -1 : 1;
      enemy.walkCycle += Math.max(0.08, Math.abs(enemy.x - oldX) * 0.28 + Math.abs(enemy.vx) * 0.06);
      enemy.fireAt -= 1;
      const fireGap = Math.max(34, (enemy.kind === "boss" ? 66 : 92) - mode.enemyShots - state.room * 2);
      if (enemy.fireAt <= 0 && Math.abs(p.x - enemy.x) < 520 && Math.abs(p.y - enemy.y) < 145) {
        enemyFireStickmanShot(state, enemy);
        enemy.fireAt = fireGap + Math.floor(stickmanRandom(state) * 26);
      }
    });
  }

  function updateStickmanBullets(api, state) {
    state.playerShots.forEach((shot) => {
      shot.x += shot.vx;
      shot.y += shot.vy;
      shot.life -= 1;
    });
    state.enemyShots.forEach((shot) => {
      shot.x += shot.vx;
      shot.y += shot.vy;
      shot.life -= 1;
    });

    for (const shot of state.playerShots) {
      if (shot.life <= 0) continue;
      for (const cover of state.cover) {
        if (rectsOverlap({ x: shot.x, y: shot.y, w: shot.w, h: shot.h }, cover)) {
          shot.life = 0;
          addStickmanParticles(state, shot.x, shot.y, "#94a3b8", 5);
        }
      }
      for (const enemy of state.enemies) {
        if (enemy.hp <= 0 || !rectsOverlap({ x: shot.x, y: shot.y, w: shot.w, h: shot.h }, enemy)) continue;
        shot.life = 0;
        enemy.hp -= 1;
        enemy.hurt = 9;
        state.hits += 1;
        state.score += enemy.kind === "boss" ? 42 : 28;
        addStickmanParticles(state, shot.x, shot.y, enemy.kind === "boss" ? "#f97316" : "#facc15", enemy.kind === "boss" ? 9 : 6);
        if (enemy.hp <= 0) {
          state.score += enemy.kind === "boss" ? 950 : 150;
          if (enemy.kind === "boss") {
            state.bossDefeated = 1;
            api.achievement?.("boss-down", "側捲 Boss 擊破", "擊破關卡 Boss。");
          }
          addStickmanParticles(state, enemy.x + enemy.w / 2, enemy.y + enemy.h / 2, "#38bdf8", enemy.kind === "boss" ? 48 : 22);
        }
      }
    }

    const pRect = playerRect(state);
    for (const shot of state.enemyShots) {
      if (shot.life <= 0) continue;
      for (const cover of state.cover) {
        if (shot.x > cover.x && shot.x < cover.x + cover.w && shot.y > cover.y && shot.y < cover.y + cover.h) {
          shot.life = 0;
          addStickmanParticles(state, shot.x, shot.y, "#94a3b8", 5);
        }
      }
      if (
        shot.life > 0 &&
        shot.x > pRect.x &&
        shot.x < pRect.x + pRect.w &&
        shot.y > pRect.y &&
        shot.y < pRect.y + pRect.h &&
        state.tick > state.invulnerableUntil
      ) {
        shot.life = 0;
        state.player.hp -= 1;
        state.invulnerableUntil = state.tick + 72;
        addStickmanParticles(state, state.player.x + PLAYER_W / 2, state.player.y + 20, "#fb7185", 18);
      }
    }
    state.playerShots = state.playerShots.filter((shot) => shot.life > 0 && shot.x > state.cameraX - 60 && shot.x < state.cameraX + WIDTH + 120);
    state.enemyShots = state.enemyShots.filter((shot) => shot.life > 0 && shot.x > state.cameraX - 90 && shot.x < state.cameraX + WIDTH + 130 && shot.y > 0 && shot.y < HEIGHT + 30);
    state.enemies = state.enemies.filter((enemy) => enemy.hp > 0);
  }

  function updateStickmanPlayer(state) {
    const p = state.player;
    const left = state.keys.left ? -1 : 0;
    const right = state.keys.right ? 1 : 0;
    const moving = left + right;
    const sprinting = state.keys.sprint && state.stamina > 8 && moving !== 0;
    const speed = sprinting ? 4.5 : 3.15;
    p.vx += moving * 0.82;
    p.vx *= p.grounded ? 0.76 : 0.91;
    p.vx = clamp(p.vx, -speed, speed);
    if (moving !== 0) p.facing = moving > 0 ? 1 : -1;
    p.walkCycle = Number(p.walkCycle || 0) + Math.abs(p.vx) * 0.22;
    if (sprinting) state.stamina = Math.max(0, state.stamina - 0.5);
    else state.stamina = Math.min(100, state.stamina + 0.28);
  }

  function jumpStickman(state) {
    if (!state || state.status !== "active" || state.paused) return;
    if (!state.player.grounded) return;
    state.player.vy = -12.2;
    state.player.grounded = false;
  }

  function advanceStickmanRoom(state) {
    const nextRoom = Math.min(WORLD_ROOMS, Math.floor((state.player.x + PLAYER_W / 2) / ROOM_WIDTH) + 1);
    if (nextRoom > state.room) {
      state.room = nextRoom;
      state.wave = nextRoom;
      state.score += 110;
      spawnStickmanRoom(state, nextRoom);
    }
  }

  function finishStickmanShooter(api, reason = "complete") {
    const state = api._stickmanShooterState;
    if (!state || state.status === "finished") return;
    state.status = "finished";
    state.completedAt = Date.now();
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    const accuracy = state.shots ? Math.round((state.hits / state.shots) * 100) : 0;
    const survived = state.player.hp > 0 ? 1 : 0;
    drawStickmanShooter(state);
    api.status(`結束 · 分數 ${Math.round(state.score).toLocaleString()} · 命中 ${accuracy}% · ${reason === "complete" ? "通關" : "任務失敗"}`);
    if (state.score > 0) api.achievement?.("first-clear", "火柴人出擊", "完成一局側捲射擊。");
    api.mission?.("score-1600", state.score, 1600, "火柴人 1600 分");
    api.mission?.("boss", state.bossDefeated, 1, "擊破側捲 Boss");
    api.mission?.("accuracy-40", accuracy, 40, "命中率 40%");
    const penaltySeconds = survived ? 0 : 5;
    const rawElapsedMs = Math.max(1, Date.now() - state.startedAt);
    api.submitScore({
      score: Math.max(1, Math.round(state.score)),
      difficulty: state.dailyChallenge?.difficulty || MODES[state.modeIndex].key,
      puzzle_id: state.dailyChallenge?.key || api.key,
      raw_elapsed_ms: rawElapsedMs,
      elapsed_ms: rawElapsedMs + penaltySeconds * 1000,
      penalty_seconds: penaltySeconds,
      guess_count: 0,
      accuracy,
      survive: survived,
      wave: state.wave,
      boss: state.bossDefeated,
    });
  }

  function updateStickmanShooter(api) {
    const state = api._stickmanShooterState;
    if (!state || state.status !== "active" || state.paused) return;
    state.tick += 1;
    state.score += 0.08;
    updateStickmanPlayer(state);
    if (state.keys.fire) fireStickmanShot(state);
    if (state.reloadTicks > 0) {
      state.reloadTicks -= 1;
      if (state.reloadTicks <= 0 && finishStickmanReload(state) && state.emptyReload) {
        state.emptyReload = false;
        api.achievement?.("reload-discipline", "冷靜換彈", "彈匣耗盡後完成換彈。");
      }
    }
    applyStickmanPhysics(state);
    advanceStickmanRoom(state);
    updateStickmanEnemies(state);
    updateStickmanBullets(api, state);
    state.cameraX = clamp(state.player.x - WIDTH * 0.38, 0, WORLD_WIDTH - WIDTH);
    state.particles.forEach((particle) => {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.05;
      particle.life -= 1;
    });
    state.particles = state.particles.filter((particle) => particle.life > 0);
    if (state.player.hp <= 0) {
      finishStickmanShooter(api, "down");
      return;
    }
    if (state.bossDefeated && state.player.x > WORLD_WIDTH - 100) {
      state.score += 500 + state.player.hp * 120 + state.reserve * 3;
      finishStickmanShooter(api, "complete");
      return;
    }
    drawStickmanShooter(state);
    setStickmanStatus(api, state);
  }

  function drawStickmanFigure(ctx, x, y, facing, color, accent, hurt = false, scale = 1, walkCycle = 0) {
    const stride = Math.sin(walkCycle || 0);
    const counter = Math.sin((walkCycle || 0) + Math.PI);
    const legA = stride * 7;
    const legB = counter * 7;
    const armSwing = counter * 4;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);
    ctx.strokeStyle = hurt ? "#fef3c7" : color;
    ctx.fillStyle = accent;
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(0, 7, 7, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, 15);
    ctx.lineTo(0, 35);
    ctx.moveTo(0, 21);
    ctx.lineTo(facing * 17, 18 + armSwing * 0.25);
    ctx.moveTo(facing * 17, 18 + armSwing * 0.25);
    ctx.lineTo(facing * 27, 18 + armSwing * 0.2);
    ctx.moveTo(0, 25);
    ctx.lineTo(-facing * (12 + armSwing * 0.22), 31 - armSwing * 0.25);
    ctx.moveTo(0, 35);
    ctx.lineTo(-9 + legA, 51);
    ctx.moveTo(0, 35);
    ctx.lineTo(10 + legB, 51);
    ctx.stroke();
    ctx.fillRect(facing * 20, 14, facing * 16, 7);
    ctx.restore();
  }

  function drawStickmanShooter(state) {
    const ctx = state.ctx;
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    const cam = state.cameraX;
    const gradient = ctx.createLinearGradient(0, 0, 0, HEIGHT);
    gradient.addColorStop(0, "#07111f");
    gradient.addColorStop(0.56, "#132134");
    gradient.addColorStop(1, "#111827");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    ctx.fillStyle = "rgba(56,189,248,.12)";
    for (let i = 0; i < 34; i += 1) {
      const x = ((i * 93 - cam * 0.25) % (WIDTH + 80)) - 40;
      const h = 52 + (i % 6) * 14;
      ctx.fillRect(x, 318 - h, 42, h);
    }
    ctx.strokeStyle = "rgba(148,163,184,.18)";
    for (let i = 0; i < 12; i += 1) {
      const y = 66 + i * 22;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(WIDTH, y + Math.sin((state.tick + i * 30) / 50) * 5);
      ctx.stroke();
    }

    state.platforms.forEach((platform) => {
      const x = platform.x - cam;
      if (x > WIDTH + 80 || x + platform.w < -80) return;
      ctx.fillStyle = platform.type === "ground" ? "#263244" : "#334155";
      ctx.fillRect(x, platform.y, platform.w, platform.h);
      ctx.fillStyle = "rgba(125,211,252,.18)";
      ctx.fillRect(x, platform.y, platform.w, 3);
    });
    state.cover.forEach((cover) => {
      const x = cover.x - cam;
      if (x > WIDTH + 50 || x + cover.w < -50) return;
      ctx.fillStyle = "#475569";
      ctx.fillRect(x, cover.y, cover.w, cover.h);
      ctx.fillStyle = "rgba(255,255,255,.12)";
      ctx.fillRect(x + 4, cover.y + 5, cover.w - 8, 4);
    });

    state.playerShots.forEach((shot) => {
      ctx.fillStyle = "#fef08a";
      ctx.fillRect(shot.x - cam, shot.y, shot.w, shot.h);
    });
    state.enemyShots.forEach((shot) => {
      ctx.beginPath();
      ctx.arc(shot.x - cam, shot.y, shot.r, 0, Math.PI * 2);
      ctx.fillStyle = "#fb7185";
      ctx.fill();
    });
    state.enemies.forEach((enemy) => {
      const x = enemy.x - cam;
      if (x > WIDTH + 60 || x + enemy.w < -60) return;
      const scale = enemy.kind === "boss" ? 1.34 : 1;
      drawStickmanFigure(ctx, x + enemy.w / 2, enemy.y - 6, enemy.facing || 1, enemy.kind === "boss" ? "#f97316" : "#fda4af", enemy.kind === "boss" ? "#7c2d12" : "#7f1d1d", enemy.hurt > 0, scale, enemy.walkCycle || 0);
      ctx.fillStyle = "rgba(15,23,42,.72)";
      ctx.fillRect(x - 4, enemy.y - 12, enemy.w + 8, 4);
      ctx.fillStyle = enemy.kind === "boss" ? "#f97316" : "#fb7185";
      ctx.fillRect(x - 4, enemy.y - 12, (enemy.w + 8) * Math.max(0, enemy.hp / enemy.maxHp), 4);
    });

    state.particles.forEach((particle) => {
      ctx.globalAlpha = clamp(particle.life / 22, 0, 1);
      ctx.fillStyle = particle.color;
      ctx.fillRect(particle.x - cam - 2, particle.y - 2, 4, 4);
      ctx.globalAlpha = 1;
    });

    const flicker = state.tick < state.invulnerableUntil && state.tick % 10 < 5;
    if (!flicker) {
      drawStickmanFigure(ctx, state.player.x - cam + PLAYER_W / 2, state.player.y - 6, state.player.facing || 1, "#e2e8f0", "#38bdf8", false, 1, state.player.walkCycle || 0);
    }
    ctx.fillStyle = "rgba(15,23,42,.72)";
    ctx.fillRect(14, 14, 286, 36);
    ctx.fillStyle = "#e2e8f0";
    ctx.font = "12px system-ui, sans-serif";
    const accuracy = state.shots ? Math.round((state.hits / state.shots) * 100) : 0;
    ctx.fillText(`score ${Math.round(state.score).toLocaleString()}  hp ${state.player.hp}  ammo ${state.ammo}/${state.reserve}`, 24, 29);
    ctx.fillText(`room ${state.room}/${WORLD_ROOMS}  accuracy ${accuracy}%  stamina ${Math.round(state.stamina)}`, 24, 44);
    ctx.fillStyle = "rgba(148,163,184,.26)";
    ctx.fillRect(332, 24, 170, 8);
    ctx.fillStyle = "#38bdf8";
    ctx.fillRect(332, 24, 170 * (state.stamina / 100), 8);

    if (state.status === "finished") {
      ctx.fillStyle = "rgba(7,17,31,.78)";
      ctx.fillRect(126, 126, WIDTH - 252, 112);
      ctx.textAlign = "center";
      ctx.fillStyle = state.bossDefeated ? "#86efac" : "#fb7185";
      ctx.font = "700 28px system-ui, sans-serif";
      ctx.fillText(state.bossDefeated ? "MISSION CLEAR" : "MISSION FAILED", WIDTH / 2, 170);
      ctx.fillStyle = "rgba(226,232,240,.9)";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText(`分數 ${Math.round(state.score).toLocaleString()} · 命中 ${accuracy}%`, WIDTH / 2, 198);
      ctx.textAlign = "start";
    }
  }

  function startStickmanShooter(api) {
    if (api._stickmanShooterState?.timer) clearInterval(api._stickmanShooterState.timer);
    const canvas = api.root.querySelector("canvas");
    const dailyChallenge = api.dailyChallenge?.() || null;
    const mode = MODES[api._stickmanModeIndex || 0] || MODES[0];
    const state = {
      canvas,
      ctx: canvas.getContext("2d"),
      status: "active",
      paused: false,
      startedAt: Date.now(),
      completedAt: null,
      tick: 0,
      score: 0,
      shots: 0,
      hits: 0,
      wave: 1,
      room: 1,
      modeIndex: api._stickmanModeIndex || 0,
      cameraX: 0,
      stamina: 100,
      ammo: MAG_SIZE,
      reserve: mode.reserve,
      reloadTicks: 0,
      emptyReload: false,
      nextShotAt: 0,
      invulnerableUntil: 80,
      bossSpawned: false,
      bossDefeated: 0,
      player: { x: 38, y: 318 - PLAYER_H, vx: 0, vy: 0, hp: 5, grounded: true, facing: 1, walkCycle: 0 },
      keys: { left: false, right: false, fire: false, sprint: false },
      platforms: makeStickmanWorld(),
      cover: makeStickmanCover(),
      spawnedRooms: new Set(),
      enemies: [],
      playerShots: [],
      enemyShots: [],
      particles: [],
      dailyChallenge,
      rng: dailyChallenge?.seed ? window.createHackmeGameSeededRandom?.(dailyChallenge.seed) : null,
      timer: null,
    };
    api._stickmanShooterState = state;
    spawnStickmanRoom(state, 1);
    drawStickmanShooter(state);
    setStickmanStatus(api, state);
    state.timer = setInterval(() => updateStickmanShooter(api), 16);
  }

  function showStickmanShooterReady(api) {
    if (api._stickmanShooterState?.timer) clearInterval(api._stickmanShooterState.timer);
    api._stickmanShooterState = null;
    const canvas = api.root.querySelector("canvas");
    const ctx = canvas?.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#07111f";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    const gradient = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT);
    gradient.addColorStop(0, "rgba(56,189,248,.18)");
    gradient.addColorStop(1, "rgba(249,115,22,.16)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "rgba(148,163,184,.16)";
    for (let i = 0; i < 18; i += 1) ctx.fillRect(i * 44, 250 - (i % 5) * 18, 28, 72 + (i % 4) * 12);
    ctx.fillStyle = "#263244";
    ctx.fillRect(0, 318, WIDTH, 42);
    drawStickmanFigure(ctx, 120, 266, 1, "#e2e8f0", "#38bdf8");
    drawStickmanFigure(ctx, 520, 266, -1, "#fda4af", "#7f1d1d");
    ctx.textAlign = "center";
    ctx.fillStyle = "#e2e8f0";
    ctx.font = "700 28px system-ui, sans-serif";
    ctx.fillText("火柴人橫向射擊", WIDTH / 2, 132);
    ctx.font = "14px system-ui, sans-serif";
    ctx.fillStyle = "rgba(226,232,240,.82)";
    ctx.fillText("按開始後才會計時、生成敵人與送成績", WIDTH / 2, 160);
    ctx.textAlign = "start";
    const mode = MODES[api._stickmanModeIndex || 0] || MODES[0];
    api.status(`待機 · 模式：${mode.label} · 按開始進入任務。`);
  }

  function setStickmanInput(state, name, pressed) {
    if (!state) return;
    if (name === "left") state.keys.left = pressed;
    if (name === "right") state.keys.right = pressed;
    if (name === "fire") state.keys.fire = pressed;
    if (name === "sprint") state.keys.sprint = pressed;
  }

  function handleStickmanKey(api, event, pressed) {
    const state = api._stickmanShooterState;
    const key = event.key;
    if (["ArrowLeft", "ArrowRight", "ArrowUp", " ", "a", "A", "d", "D", "w", "W", "j", "J", "r", "R", "Shift"].includes(key)) {
      event.preventDefault?.();
    }
    if (key === "ArrowLeft" || key === "a" || key === "A") setStickmanInput(state, "left", pressed);
    if (key === "ArrowRight" || key === "d" || key === "D") setStickmanInput(state, "right", pressed);
    if (key === "Shift") setStickmanInput(state, "sprint", pressed);
    if ((key === "ArrowUp" || key === "w" || key === "W" || key === " ") && pressed) jumpStickman(state);
    if (key === "j" || key === "J") setStickmanInput(state, "fire", pressed);
    if ((key === "r" || key === "R") && pressed) startStickmanReload(state);
  }

  function updateStickmanActions(api) {
    const mode = MODES[api._stickmanModeIndex || 0] || MODES[0];
    api.setActions(`
      <button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>
      <button class="btn game-mini-btn" type="button" data-action="pause">暫停</button>
      <button class="btn game-mini-btn" type="button" data-action="mode">模式：${mode.label}</button>
      <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
    `);
  }

  window.registerHackmeLocalGameModule("stickman_shooter", {
    mount(api) {
      api._stickmanModeIndex = api._stickmanModeIndex || 0;
      api.setTitle("火柴人橫向射擊");
      api.setSwipeMode?.("hold");
      api.root.innerHTML = `<div class="stickman-shooter-shell"><canvas class="stickman-shooter-canvas" width="${WIDTH}" height="${HEIGHT}" aria-label="火柴人橫向射擊"></canvas></div>`;
      updateStickmanActions(api);
      api.setControls(`
        <button class="btn game-mini-btn" type="button" data-hold="left">左</button>
        <button class="btn game-mini-btn" type="button" data-hold="right">右</button>
        <button class="btn game-mini-btn" type="button" data-jump="1">跳</button>
        <button class="btn game-mini-btn btn-primary" type="button" data-hold="fire">射擊</button>
        <button class="btn game-mini-btn" type="button" data-reload="1">換彈</button>
        <button class="btn game-mini-btn" type="button" data-hold="sprint">衝刺</button>
      `);
      api.onAction = (action) => {
        if (action === "new") startStickmanShooter(api);
        if (action === "pause" && api._stickmanShooterState?.status === "active") {
          api._stickmanShooterState.paused = !api._stickmanShooterState.paused;
          api.status(api._stickmanShooterState.paused ? "暫停中。" : "繼續。");
        }
        if (action === "mode") {
          if (api._stickmanShooterState?.timer) clearInterval(api._stickmanShooterState.timer);
          api._stickmanModeIndex = ((api._stickmanModeIndex || 0) + 1) % MODES.length;
          updateStickmanActions(api);
          showStickmanShooterReady(api);
        }
        if (action === "finish") finishStickmanShooter(api, "manual");
      };
      api.onControl = (target, pressed) => {
        const state = api._stickmanShooterState;
        if (target.dataset.jump && pressed) jumpStickman(state);
        if (target.dataset.reload && pressed) startStickmanReload(state);
        setStickmanInput(state, target.dataset.hold || "", pressed);
      };
      api.onKey = (event, pressed) => handleStickmanKey(api, event, pressed);
      showStickmanShooterReady(api);
      return () => {
        if (api._stickmanShooterState?.timer) clearInterval(api._stickmanShooterState.timer);
        api._stickmanShooterState = null;
      };
    },
  });
}());
