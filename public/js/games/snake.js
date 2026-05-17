'use strict';

(function () {
  const { makeCtx, registerScore } = window.HACKME_LOCAL_GAME_HELPERS;
  const SNAKE_ASSET_SOURCES = Object.freeze({
    platformer: {
      name: "Kenney New Platformer Pack",
      url: "https://kenney.nl/assets/new-platformer-pack",
      license: "Creative Commons CC0",
      usage: "bundled PNG terrain, rock, mushroom, coin and star-like pickup tiles with canvas fallback",
    },
  });
  const SNAKE_ASSET_BASE = "/assets/games/vendor/kenney/new-platformer-pack/";
  const SNAKE_IMAGE_ASSETS = Object.freeze({
    grass: `${SNAKE_ASSET_BASE}tiles/terrain_grass_center.png`,
    grassTop: `${SNAKE_ASSET_BASE}tiles/terrain_grass_top.png`,
    water: `${SNAKE_ASSET_BASE}tiles/water.png`,
    rock: `${SNAKE_ASSET_BASE}tiles/rock.png`,
    food: `${SNAKE_ASSET_BASE}tiles/mushroom_red.png`,
    powerup: `${SNAKE_ASSET_BASE}tiles/coin_gold.png`,
    head: `${SNAKE_ASSET_BASE}tiles/gem_blue.png`,
    body: `${SNAKE_ASSET_BASE}tiles/gem_red.png`,
  });
  const SNAKE_IMAGES = loadSnakeImages(SNAKE_IMAGE_ASSETS);

  function loadSnakeImages(assets) {
    if (typeof Image === "undefined") return {};
    return Object.entries(assets).reduce((images, [key, src]) => {
      const image = new Image();
      image.decoding = "async";
      image.src = src;
      images[key] = image;
      return images;
    }, {});
  }

  function snakeImageReady(image) {
    return Boolean(image?.complete && image.naturalWidth > 0);
  }

  function drawSnakeImage(ctx, key, x, y, w, h, options = {}) {
    const image = SNAKE_IMAGES[key];
    if (!snakeImageReady(image)) return false;
    ctx.save();
    ctx.globalAlpha = options.alpha ?? 1;
    ctx.translate(x + w / 2, y + h / 2);
    if (options.rotation) ctx.rotate(options.rotation);
    ctx.drawImage(image, -w / 2, -h / 2, w, h);
    ctx.restore();
    return true;
  }

  function drawSnakeTiledImage(ctx, key, x, y, w, h, tileSize = 20, options = {}) {
    const image = SNAKE_IMAGES[key];
    if (!snakeImageReady(image)) return false;
    ctx.save();
    ctx.globalAlpha = options.alpha ?? 1;
    for (let py = y; py < y + h; py += tileSize) {
      for (let px = x; px < x + w; px += tileSize) {
        ctx.drawImage(image, px, py, Math.min(tileSize, x + w - px), Math.min(tileSize, y + h - py));
      }
    }
    ctx.restore();
    return true;
  }

  function drawSnakeBackground(ctx) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 360);
    gradient.addColorStop(0, "#07111f");
    gradient.addColorStop(1, "#10291e");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 360, 360);
    drawSnakeTiledImage(ctx, "grass", 0, 0, 360, 360, 20, { alpha: 0.28 });
    for (let y = 0; y < 18; y += 1) {
      for (let x = 0; x < 18; x += 1) {
        ctx.fillStyle = (x + y) % 2 ? "rgba(34,197,94,.055)" : "rgba(34,197,94,.095)";
        ctx.fillRect(x * 20, y * 20, 20, 20);
      }
    }
  }

  function drawSnakeTile(ctx, x, y, fill, top = "rgba(255,255,255,.22)") {
    const px = x * 20 + 2;
    const py = y * 20 + 2;
    ctx.fillStyle = fill;
    ctx.fillRect(px, py, 16, 16);
    ctx.fillStyle = top;
    ctx.fillRect(px + 2, py + 2, 12, 3);
    ctx.fillStyle = "rgba(15,23,42,.22)";
    ctx.fillRect(px + 2, py + 13, 12, 2);
  }

  function drawSnakeRock(ctx, x, y) {
    if (drawSnakeImage(ctx, "rock", x * 20 + 1, y * 20 + 1, 18, 18)) return;
    const px = x * 20 + 10;
    const py = y * 20 + 10;
    ctx.fillStyle = "#64748b";
    ctx.beginPath();
    ctx.ellipse(px, py + 2, 8, 6, -0.25, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(226,232,240,.22)";
    ctx.beginPath();
    ctx.ellipse(px - 3, py, 3, 2, -0.4, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawSnakeFood(ctx, food) {
    if (drawSnakeImage(ctx, "food", food[0] * 20 + 1, food[1] * 20 + 1, 18, 18)) return;
    const x = food[0] * 20 + 10;
    const y = food[1] * 20 + 10;
    ctx.fillStyle = "#f97316";
    ctx.beginPath();
    ctx.arc(x, y + 1, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#86efac";
    ctx.beginPath();
    ctx.ellipse(x + 4, y - 6, 4, 2.5, -0.55, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawSnakePowerup(ctx, powerup, tick = 0) {
    const x = powerup[0] * 20 + 10;
    const y = powerup[1] * 20 + 10;
    ctx.fillStyle = `rgba(250,204,21,${0.16 + Math.sin(tick / 8) * 0.05})`;
    ctx.beginPath();
    ctx.arc(x, y, 13, 0, Math.PI * 2);
    ctx.fill();
    if (drawSnakeImage(ctx, "powerup", x - 9, y - 9, 18, 18, { rotation: tick / 18 })) return;
    ctx.fillStyle = "#facc15";
    ctx.beginPath();
    ctx.moveTo(x, y - 8);
    ctx.lineTo(x + 3, y - 2);
    ctx.lineTo(x + 9, y - 2);
    ctx.lineTo(x + 4, y + 2);
    ctx.lineTo(x + 6, y + 9);
    ctx.lineTo(x, y + 5);
    ctx.lineTo(x - 6, y + 9);
    ctx.lineTo(x - 4, y + 2);
    ctx.lineTo(x - 9, y - 2);
    ctx.lineTo(x - 3, y - 2);
    ctx.closePath();
    ctx.fill();
  }

  function snakeUnitVector(from, to) {
    if (!from || !to) return [0, 0];
    return [Math.sign(to[0] - from[0]), Math.sign(to[1] - from[1])];
  }

  function drawSnakeConnector(ctx, cx, cy, dir, fill) {
    if (!dir[0] && !dir[1]) return;
    ctx.fillStyle = fill;
    if (dir[0] > 0) ctx.fillRect(cx, cy - 6, 10, 12);
    if (dir[0] < 0) ctx.fillRect(cx - 10, cy - 6, 10, 12);
    if (dir[1] > 0) ctx.fillRect(cx - 6, cy, 12, 10);
    if (dir[1] < 0) ctx.fillRect(cx - 6, cy - 10, 12, 10);
  }

  function drawSnakeTail(ctx, cx, cy, dir) {
    const angle = Math.atan2(dir[1], dir[0]);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.fillStyle = "#15803d";
    ctx.beginPath();
    ctx.moveTo(-9, 0);
    ctx.quadraticCurveTo(-1, -7, 8, -5);
    ctx.quadraticCurveTo(5, 0, 8, 5);
    ctx.quadraticCurveTo(-1, 7, -9, 0);
    ctx.fill();
    ctx.fillStyle = "rgba(187,247,208,.28)";
    ctx.beginPath();
    ctx.ellipse(1, -2, 4, 1.8, -0.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawSnakeBody(ctx, segment, snake, index, tick) {
    const [x, y] = segment;
    const cx = x * 20 + 10;
    const cy = y * 20 + 10;
    const prev = snake[index - 1];
    const next = snake[index + 1];
    const fill = index % 2 ? "#16a34a" : "#22c55e";
    const toPrev = snakeUnitVector(segment, prev);
    const toNext = snakeUnitVector(segment, next);
    if (!next) {
      drawSnakeTail(ctx, cx, cy, toPrev[0] || toPrev[1] ? toPrev : [1, 0]);
      return;
    }
    drawSnakeConnector(ctx, cx, cy, toPrev, fill);
    drawSnakeConnector(ctx, cx, cy, toNext, fill);
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.arc(cx, cy, 8.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(20,83,45,.28)";
    ctx.beginPath();
    ctx.arc(cx, cy + 3, 5.4, 0, Math.PI);
    ctx.fill();
    ctx.strokeStyle = "rgba(187,247,208,.35)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(cx - 2 + Math.sin((tick + index) / 4) * 1.3, cy - 2, 2.3, 0.15, Math.PI * 1.15);
    ctx.stroke();
  }

  function drawSnakeHead(ctx, segment, dir, tick) {
    const [x, y] = segment;
    const cx = x * 20 + 10;
    const cy = y * 20 + 10;
    const angle = Math.atan2(dir[1], dir[0]);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    const headGradient = ctx.createLinearGradient(-7, -8, 10, 8);
    headGradient.addColorStop(0, "#bbf7d0");
    headGradient.addColorStop(0.55, "#4ade80");
    headGradient.addColorStop(1, "#15803d");
    ctx.fillStyle = headGradient;
    ctx.beginPath();
    ctx.moveTo(10, 0);
    ctx.bezierCurveTo(6, -8.6, -7, -9, -9, -2.8);
    ctx.quadraticCurveTo(-10, 0, -9, 2.8);
    ctx.bezierCurveTo(-7, 9, 6, 8.6, 10, 0);
    ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,.22)";
    ctx.beginPath();
    ctx.ellipse(-1, -4.8, 5, 1.7, -0.18, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#052e16";
    [[3.2, -3.7], [3.2, 3.7]].forEach(([ex, ey]) => {
      ctx.beginPath();
      ctx.arc(ex, ey, 1.8, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#dcfce7";
      ctx.beginPath();
      ctx.arc(ex + 0.45, ey - 0.45, 0.55, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#052e16";
    });
    if (tick % 28 < 12) {
      ctx.strokeStyle = "#fb7185";
      ctx.lineWidth = 1.4;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(9, 0);
      ctx.lineTo(14, 0);
      ctx.moveTo(14, 0);
      ctx.lineTo(17, -2.4);
      ctx.moveTo(14, 0);
      ctx.lineTo(17, 2.4);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawSnakeSegment(ctx, snake, index, dir, tick) {
    if (index === 0) drawSnakeHead(ctx, snake[index], dir, tick);
    else drawSnakeBody(ctx, snake[index], snake, index, tick);
  }

  window.registerHackmeLocalGameModule("snake", {
    mount(api) {
      makeCtx(api, "貪食蛇");
      const size = 18;
      const state = { startedAt: 0, dir: [1, 0], next: [1, 0], snake: [], food: [8, 8], powerup: [12, 6], obstacles: [], score: 0, timer: null, over: true, maxLength: 0, powerupsCollected: 0, speedZoneTouched: false, tick: 0, dailyChallenge: null };
      api.root.innerHTML = `<canvas class="arcade-canvas" width="360" height="360" aria-label="貪食蛇"></canvas>`;
      api.setControls(["左", "上", "下", "右"].map((t) => `<button class="btn game-mini-btn" data-dir="${t}">${t}</button>`).join(""));
      const canvas = api.root.querySelector("canvas");
      const ctx = canvas.getContext("2d");
      const draw = () => {
        drawSnakeBackground(ctx);
        if (!drawSnakeTiledImage(ctx, "water", 2 * 20, 2 * 20, 5 * 20, 3 * 20, 20, { alpha: 0.42 })) {
          ctx.fillStyle = "rgba(56,189,248,.18)";
          ctx.fillRect(2 * 20, 2 * 20, 5 * 20, 3 * 20);
        }
        ctx.strokeStyle = "rgba(103,232,249,.34)";
        ctx.strokeRect(2 * 20 + 2, 2 * 20 + 2, 5 * 20 - 4, 3 * 20 - 4);
        state.obstacles.forEach(([x, y]) => drawSnakeRock(ctx, x, y));
        for (let i = state.snake.length - 1; i >= 0; i -= 1) drawSnakeSegment(ctx, state.snake, i, state.dir, state.tick);
        drawSnakeFood(ctx, state.food);
        drawSnakePowerup(ctx, state.powerup, state.tick);
      };
      const drawGameOver = () => {
        ctx.fillStyle = "rgba(7,17,31,.78)";
        ctx.fillRect(38, 126, 284, 108);
        ctx.textAlign = "center";
        ctx.fillStyle = "#ff4f6d";
        ctx.font = "700 28px system-ui, sans-serif";
        ctx.fillText("GAME OVER", 180, 170);
        ctx.fillStyle = "rgba(226,232,240,.9)";
        ctx.font = "13px system-ui, sans-serif";
        ctx.fillText(`分數 ${Number(state.score || 0).toLocaleString()} · 長度 ${state.maxLength || 0}`, 180, 198);
        ctx.textAlign = "start";
      };
      const blocked = ([x, y]) => state.snake.some(([sx, sy]) => sx === x && sy === y) || state.obstacles.some(([ox, oy]) => ox === x && oy === y);
      const placeFood = () => {
        do state.food = [Math.floor(Math.random() * size), Math.floor(Math.random() * size)];
        while (blocked(state.food));
      };
      const placePowerup = () => {
        do state.powerup = [Math.floor(Math.random() * size), Math.floor(Math.random() * size)];
        while (blocked(state.powerup) || (state.food[0] === state.powerup[0] && state.food[1] === state.powerup[1]));
      };
      const tick = () => {
        state.tick += 1;
        state.dir = state.next;
        const head = state.snake[0];
        const next = [head[0] + state.dir[0], head[1] + state.dir[1]];
        if (next[0] < 0 || next[1] < 0 || next[0] >= size || next[1] >= size || state.snake.some(([x, y]) => x === next[0] && y === next[1]) || state.obstacles.some(([x, y]) => x === next[0] && y === next[1])) {
          state.over = true;
          clearInterval(state.timer);
          state.timer = null;
          api.sound?.("uiError", { volume: 0.16, throttleMs: 250 });
          draw();
          drawGameOver();
          registerScore(api, state.score, state, state.dailyChallenge?.difficulty || "standard");
          api.status(`遊戲結束 · 分數 ${state.score} · 最高長度 ${state.maxLength || state.snake.length}`);
          return;
        }
        state.snake.unshift(next);
        if (next[0] === state.food[0] && next[1] === state.food[1]) { state.score += 10; api.sound?.("uiTick", { volume: 0.1, throttleMs: 80 }); placeFood(); }
        else if (next[0] === state.powerup[0] && next[1] === state.powerup[1]) {
          state.score += 50;
          api.sound?.("uiDrop", { volume: 0.14, throttleMs: 140 });
          state.powerupsCollected += 1;
          api.achievement?.("powerup", "道具吞食", "吃到任務道具。");
          api.mission?.("powerup", state.powerupsCollected, 1, "吃到道具");
          placePowerup();
        }
        else state.snake.pop();
        state.maxLength = Math.max(state.maxLength, state.snake.length);
        if (state.maxLength >= 12) api.achievement?.("long-snake", "長蛇成形", "長度達 12。");
        if (next[0] >= 2 && next[0] <= 6 && next[1] >= 2 && next[1] <= 4) {
          state.score += 1;
          if (!state.speedZoneTouched) {
            state.speedZoneTouched = true;
            api.achievement?.("speed-zone", "加速區生還", "穿越加速區後繼續得分。");
          }
        }
        api.status(`分數 ${state.score} · 長度 ${state.snake.length} · 道具 ${state.powerupsCollected}`);
        draw();
      };
      const start = () => {
        clearInterval(state.timer);
        Object.assign(state, { startedAt: Date.now(), dir: [1, 0], next: [1, 0], snake: [[5, 9], [4, 9], [3, 9]], score: 0, over: false, maxLength: 3, powerupsCollected: 0, speedZoneTouched: false, tick: 0, dailyChallenge: api.dailyChallenge?.() || null });
        state.obstacles = [[9, 7], [10, 7], [11, 7], [7, 12], [7, 13], [13, 4], [14, 4]];
        placeFood(); placePowerup(); draw(); state.timer = setInterval(tick, 120);
      };
      const move = (name) => {
        const map = { "左": [-1, 0], "右": [1, 0], "上": [0, -1], "下": [0, 1] };
        const dir = map[name]; if (!dir) return;
        if (dir[0] + state.dir[0] || dir[1] + state.dir[1]) state.next = dir;
      };
      api.onAction = (action) => { if (action === "new") start(); };
      api.onControl = (target) => move(target.dataset.dir);
      api.onKey = (event, pressed) => {
        if (!pressed) return;
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) event.preventDefault?.();
        if (event.key === "ArrowLeft") move("左");
        if (event.key === "ArrowRight") move("右");
        if (event.key === "ArrowUp") move("上");
        if (event.key === "ArrowDown") move("下");
      };
      state.obstacles = [[9, 7], [10, 7], [11, 7], [7, 12], [7, 13], [13, 4], [14, 4]];
      draw();
      api.status("待機 · 按開始後才會計時與移動。");
      return () => clearInterval(state.timer);
    },
  });
}());
