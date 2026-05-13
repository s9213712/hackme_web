'use strict';

(function () {
  const { clamp } = window.HACKME_LOCAL_GAME_HELPERS;
  const WIDTH = 360;
  const HEIGHT = 560;
  const CELL = 28;
  const HALF = CELL / 2;
  const LEFT = 40;
  const RIGHT = LEFT + CELL * 10;
  const FLOOR = 528;
  const TOP = 24;
  const GRAVITY = 1180;
  const RELAXED_LINE_FILL = 0.78;
  const LINE_TOLERANCE = CELL * 0.68;
  const BLOCK_COLORS = {
    I: "#28c7fa",
    O: "#ffd166",
    T: "#b779ff",
    S: "#22c79a",
    Z: "#ff4f6d",
    J: "#4d7dff",
    L: "#ff9f43",
  };
  const PIECES = {
    I: [[-1.5, 0], [-0.5, 0], [0.5, 0], [1.5, 0]],
    O: [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]],
    T: [[-1, 0], [0, 0], [1, 0], [0, -1]],
    S: [[-0.5, 0], [0.5, 0], [0.5, -1], [1.5, -1]],
    Z: [[-0.5, -1], [0.5, -1], [0.5, 0], [1.5, 0]],
    J: [[-1, -1], [-1, 0], [0, 0], [1, 0]],
    L: [[1, -1], [-1, 0], [0, 0], [1, 0]],
  };

  function centerRealTetrisCells(cells) {
    const centerX = cells.reduce((sum, cell) => sum + cell[0], 0) / cells.length;
    const centerY = cells.reduce((sum, cell) => sum + cell[1], 0) / cells.length;
    return cells.map(([x, y]) => [x - centerX, y - centerY]);
  }

  function realTetrisPieceCenters(body) {
    const sin = Math.sin(body.angle);
    const cos = Math.cos(body.angle);
    return body.cells.map(([gx, gy]) => {
      const x = gx * CELL;
      const y = gy * CELL;
      return {
        x: body.x + x * cos - y * sin,
        y: body.y + x * sin + y * cos,
        rx: x * cos - y * sin,
        ry: x * sin + y * cos,
      };
    });
  }

  function drawRealTetrisBlock(ctx, x, y, angle, type, alpha = 1) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.globalAlpha = alpha;
    ctx.fillStyle = BLOCK_COLORS[type] || "#e5e7eb";
    ctx.strokeStyle = "rgba(255,255,255,.34)";
    ctx.lineWidth = 1.4;
    ctx.shadowColor = "rgba(56,189,248,.18)";
    ctx.shadowBlur = 10;
    ctx.fillRect(-HALF + 1.5, -HALF + 1.5, CELL - 3, CELL - 3);
    ctx.shadowBlur = 0;
    ctx.strokeRect(-HALF + 1.5, -HALF + 1.5, CELL - 3, CELL - 3);
    ctx.fillStyle = "rgba(255,255,255,.16)";
    ctx.fillRect(-HALF + 4, -HALF + 4, CELL - 8, 4);
    ctx.restore();
  }

  function createRealTetrisBody() {
    const names = Object.keys(PIECES);
    const type = names[Math.floor(Math.random() * names.length)];
    return {
      type,
      cells: centerRealTetrisCells(PIECES[type]),
      x: (LEFT + RIGHT) / 2,
      y: TOP + CELL * 1.6,
      angle: (Math.random() - 0.5) * 0.18,
      vx: (Math.random() - 0.5) * 26,
      vy: 0,
      omega: (Math.random() - 0.5) * 0.55,
      settledFrames: 0,
      touching: false,
    };
  }

  function pushRealTetrisBody(body, nx, ny, penetration, rx, ry) {
    body.x += nx * penetration;
    body.y += ny * penetration;
    const vn = body.vx * nx + body.vy * ny;
    if (vn < 0) {
      body.vx -= (1.18 * vn) * nx;
      body.vy -= (1.18 * vn) * ny;
    }
    const tangentX = -ny;
    const tangentY = nx;
    const vt = body.vx * tangentX + body.vy * tangentY;
    body.vx -= vt * tangentX * 0.18;
    body.vy -= vt * tangentY * 0.18;
    body.omega += (rx * ny - ry * nx) * penetration * 0.0009;
    body.omega *= 0.94;
  }

  function resolveRealTetrisCollisions(state) {
    const body = state.active;
    if (!body) return;
    body.touching = false;
    for (let iteration = 0; iteration < 3; iteration += 1) {
      const centers = realTetrisPieceCenters(body);
      for (const point of centers) {
        if (point.x - HALF < LEFT) {
          pushRealTetrisBody(body, 1, 0, LEFT - (point.x - HALF), point.rx, point.ry);
        }
        if (point.x + HALF > RIGHT) {
          pushRealTetrisBody(body, -1, 0, (point.x + HALF) - RIGHT, point.rx, point.ry);
        }
        if (point.y + HALF > FLOOR) {
          body.touching = true;
          pushRealTetrisBody(body, 0, -1, (point.y + HALF) - FLOOR, point.rx, point.ry);
        }
        for (const block of state.blocks) {
          if (Math.abs(point.x - block.x) > CELL * 1.15 || Math.abs(point.y - block.y) > CELL * 1.15) continue;
          let dx = point.x - block.x;
          let dy = point.y - block.y;
          let dist = Math.hypot(dx, dy);
          if (dist < 0.001) {
            dx = 0;
            dy = -1;
            dist = 1;
          }
          const minDist = CELL * 0.92;
          if (dist >= minDist) continue;
          const nx = dx / dist;
          const ny = dy / dist;
          body.touching = true;
          pushRealTetrisBody(body, nx, ny, minDist - dist, point.rx, point.ry);
        }
      }
    }
  }

  function integrateRealTetrisPhysics(state, dt) {
    const body = state.active;
    if (!body || state.status !== "active" || state.paused) return;
    const input = state.input;
    if (input.left) body.vx -= 860 * dt;
    if (input.right) body.vx += 860 * dt;
    if (input.down) body.vy += 760 * dt;
    if (input.rotate) body.omega += (input.rotate > 0 ? 7.2 : -7.2) * dt;
    body.vy += GRAVITY * dt;
    body.vx *= 0.992;
    body.vy *= 0.998;
    body.omega *= 0.992;
    body.vx = clamp(body.vx, -360, 360);
    body.vy = clamp(body.vy, -280, 900);
    body.omega = clamp(body.omega, -7.5, 7.5);
    body.x += body.vx * dt;
    body.y += body.vy * dt;
    body.angle += body.omega * dt;
    resolveRealTetrisCollisions(state);
    const speed = Math.hypot(body.vx, body.vy) + Math.abs(body.omega) * 28;
    body.settledFrames = body.touching && speed < 86 ? body.settledFrames + 1 : 0;
    if (body.settledFrames > 24) lockRealTetrisBody(state);
  }

  function rowCoverageForRealTetris(blocks, rowY) {
    const segments = [];
    for (const block of blocks) {
      if (Math.abs(block.y - rowY) > LINE_TOLERANCE) continue;
      const widthBoost = 1 + Math.max(0, 1 - Math.abs(block.y - rowY) / LINE_TOLERANCE) * 0.18;
      const halfWidth = HALF * 0.94 * widthBoost;
      segments.push([clamp(block.x - halfWidth, LEFT, RIGHT), clamp(block.x + halfWidth, LEFT, RIGHT)]);
    }
    segments.sort((a, b) => a[0] - b[0]);
    let covered = 0;
    let end = LEFT;
    for (const [from, to] of segments) {
      if (to <= end) continue;
      covered += Math.max(0, to - Math.max(from, end));
      end = Math.max(end, to);
    }
    return covered / (RIGHT - LEFT);
  }

  function clearRealTetrisRelaxedLines(state) {
    const rows = [];
    for (let row = 0; row < 18; row += 1) {
      const y = FLOOR - HALF - row * CELL;
      const coverage = rowCoverageForRealTetris(state.blocks, y);
      if (coverage >= RELAXED_LINE_FILL) rows.push({ row, y, coverage });
    }
    if (!rows.length) return 0;
    const remove = new Set();
    rows.forEach(({ y }) => {
      state.blocks.forEach((block, index) => {
        if (Math.abs(block.y - y) <= LINE_TOLERANCE) remove.add(index);
      });
    });
    state.blocks = state.blocks.filter((_block, index) => !remove.has(index));
    for (const block of state.blocks) {
      const clearedBelow = rows.filter(({ y }) => block.y < y - LINE_TOLERANCE * 0.28).length;
      if (clearedBelow) block.y += clearedBelow * CELL;
    }
    state.lines += rows.length;
    state.score += rows.length * 180 + Math.round(rows.reduce((sum, row) => sum + row.coverage, 0) * 80);
    return rows.length;
  }

  function realTetrisGameOver(state) {
    return state.blocks.some((block) => block.y < TOP + CELL * 1.4);
  }

  function lockRealTetrisBody(state) {
    const body = state.active;
    if (!body) return;
    realTetrisPieceCenters(body).forEach((point) => {
      state.blocks.push({
        x: clamp(point.x, LEFT + HALF * 0.35, RIGHT - HALF * 0.35),
        y: clamp(point.y, TOP - CELL, FLOOR - HALF * 0.25),
        angle: body.angle,
        type: body.type,
      });
    });
    state.score += 12;
    state.active = null;
    clearRealTetrisRelaxedLines(state);
    if (realTetrisGameOver(state)) {
      finishRealTetrisGame(state.api);
      return;
    }
    state.active = createRealTetrisBody();
  }

  function drawRealTetris(state, canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "#08111f";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "rgba(15,23,42,.92)";
    ctx.fillRect(LEFT, TOP, RIGHT - LEFT, FLOOR - TOP);
    ctx.strokeStyle = "rgba(148,163,184,.16)";
    ctx.lineWidth = 1;
    for (let x = LEFT; x <= RIGHT; x += CELL) {
      ctx.beginPath();
      ctx.moveTo(x, TOP);
      ctx.lineTo(x, FLOOR);
      ctx.stroke();
    }
    for (let y = FLOOR; y >= TOP; y -= CELL) {
      ctx.beginPath();
      ctx.moveTo(LEFT, y);
      ctx.lineTo(RIGHT, y);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(248,113,113,.56)";
    ctx.setLineDash([7, 7]);
    ctx.beginPath();
    ctx.moveTo(LEFT, TOP + CELL * 1.35);
    ctx.lineTo(RIGHT, TOP + CELL * 1.35);
    ctx.stroke();
    ctx.setLineDash([]);
    state.blocks.forEach((block) => drawRealTetrisBlock(ctx, block.x, block.y, block.angle, block.type));
    if (state.active) {
      realTetrisPieceCenters(state.active).forEach((point) => {
        drawRealTetrisBlock(ctx, point.x, point.y, state.active.angle, state.active.type, 0.98);
      });
    }
    ctx.fillStyle = "rgba(226,232,240,.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`relaxed line ${Math.round(RELAXED_LINE_FILL * 100)}%`, LEFT + 8, FLOOR + 20);
    if (state.status === "finished") {
      ctx.fillStyle = "rgba(7,17,31,.76)";
      ctx.fillRect(LEFT, 178, RIGHT - LEFT, 126);
      ctx.fillStyle = "#ff4f6d";
      ctx.font = "700 24px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("PHYSICS OVER", WIDTH / 2, 225);
      ctx.fillStyle = "rgba(226,232,240,.9)";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText(`分數 ${Number(state.score || 0).toLocaleString()} · 消除 ${state.lines || 0} 行`, WIDTH / 2, 252);
      ctx.textAlign = "start";
    }
  }

  function updateRealTetrisStatus(api, state, prefix = "") {
    const elapsed = window.soloElapsedMs ? window.formatSoloGameTime(window.soloElapsedMs(state)) : "";
    const mode = state.paused ? "暫停中" : state.status === "finished" ? "已結束" : "物理模擬中";
    api.status(`${prefix ? `${prefix} ` : ""}${mode} · 分數 ${Number(state.score || 0).toLocaleString()} · 放寬消線 ${state.lines} 行 · ${elapsed}`);
  }

  function finishRealTetrisGame(api) {
    const state = api._realTetrisState;
    if (!state || state.status === "finished") return;
    state.status = "finished";
    state.completedAt = Date.now();
    cancelAnimationFrame(state.raf);
    state.raf = null;
    drawRealTetris(state, state.canvas);
    updateRealTetrisStatus(api, state);
    if (Number(state.score || 0) > 0) {
      api.submitScore({
        score: Math.round(state.score),
        difficulty: "physics",
        puzzle_id: "real-tetris-physics",
        raw_elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
        elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
        penalty_seconds: 0,
        guess_count: 0,
      });
    }
  }

  function startRealTetris(api) {
    const canvas = api.root.querySelector("canvas");
    const state = {
      api,
      canvas,
      active: createRealTetrisBody(),
      blocks: [],
      input: { left: false, right: false, down: false, rotate: 0 },
      score: 0,
      lines: 0,
      status: "active",
      paused: false,
      startedAt: Date.now(),
      completedAt: null,
      lastFrame: performance.now(),
      raf: null,
    };
    api._realTetrisState = state;
    const loop = (now) => {
      const current = api._realTetrisState;
      if (!current || current.status !== "active") return;
      const dt = Math.min(0.035, Math.max(0.001, (now - current.lastFrame) / 1000));
      current.lastFrame = now;
      if (!current.paused) {
        integrateRealTetrisPhysics(current, dt);
        if (current.status !== "active") {
          drawRealTetris(current, current.canvas);
          updateRealTetrisStatus(api, current);
          return;
        }
        current.score += dt * 0.9;
      }
      drawRealTetris(current, current.canvas);
      updateRealTetrisStatus(api, current);
      current.raf = requestAnimationFrame(loop);
    };
    drawRealTetris(state, canvas);
    updateRealTetrisStatus(api, state, "真實物理引擎啟動。");
    state.raf = requestAnimationFrame(loop);
  }

  function hardDropRealTetris(api) {
    const state = api._realTetrisState;
    if (!state?.active || state.status !== "active" || state.paused) return;
    state.active.vy += 1900;
    state.active.omega += (Math.random() - 0.5) * 2.2;
    state.score += 6;
  }

  function setRealTetrisInput(api, name, pressed) {
    const state = api._realTetrisState;
    if (!state) return;
    if (name === "left") state.input.left = pressed;
    if (name === "right") state.input.right = pressed;
    if (name === "down") state.input.down = pressed;
    if (name === "rotate") state.input.rotate = pressed ? 1 : 0;
    if (name === "rotate-left") state.input.rotate = pressed ? -1 : 0;
  }

  window.registerHackmeLocalGameModule("real_tetris", {
    mount(api) {
      api.setTitle("真實版俄羅斯方塊");
      api.root.innerHTML = `
        <div class="real-tetris-shell">
          <canvas class="real-tetris-canvas" width="${WIDTH}" height="${HEIGHT}" aria-label="真實版俄羅斯方塊"></canvas>
        </div>
      `;
      api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>
        <button class="btn game-mini-btn" type="button" data-action="pause">暫停</button>
        <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
      `);
      api.setControls(`
        <button class="btn game-mini-btn" type="button" data-hold="left">左推</button>
        <button class="btn game-mini-btn" type="button" data-hold="rotate-left">逆轉</button>
        <button class="btn game-mini-btn" type="button" data-hold="rotate">順轉</button>
        <button class="btn game-mini-btn" type="button" data-hold="right">右推</button>
        <button class="btn game-mini-btn" type="button" data-hold="down">加重</button>
        <button class="btn game-mini-btn btn-primary" type="button" data-drop="1">墜落</button>
      `);
      api.onAction = (action) => {
        if (action === "new") {
          if (api._realTetrisState?.raf) cancelAnimationFrame(api._realTetrisState.raf);
          startRealTetris(api);
        }
        if (action === "pause" && api._realTetrisState?.status === "active") {
          api._realTetrisState.paused = !api._realTetrisState.paused;
          updateRealTetrisStatus(api, api._realTetrisState);
        }
        if (action === "finish") finishRealTetrisGame(api);
      };
      api.onControl = (target, pressed) => {
        if (target.dataset.drop) hardDropRealTetris(api);
        setRealTetrisInput(api, target.dataset.hold || "", pressed);
      };
      api.onKey = (event, pressed) => {
        if (["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", " ", "z", "Z"].includes(event.key)) event.preventDefault?.();
        if (event.key === "ArrowLeft") setRealTetrisInput(api, "left", pressed);
        if (event.key === "ArrowRight") setRealTetrisInput(api, "right", pressed);
        if (event.key === "ArrowDown") setRealTetrisInput(api, "down", pressed);
        if (event.key === "ArrowUp") setRealTetrisInput(api, "rotate", pressed);
        if (event.key === "z" || event.key === "Z") setRealTetrisInput(api, "rotate-left", pressed);
        if (event.key === " " && pressed) hardDropRealTetris(api);
      };
      startRealTetris(api);
      return () => {
        if (api._realTetrisState?.raf) cancelAnimationFrame(api._realTetrisState.raf);
        api._realTetrisState = null;
      };
    },
  });
}());
