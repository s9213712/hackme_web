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
  const RELAXED_LINE_FILL = 0.9;
  const LINE_TOLERANCE = CELL * 0.68;
  const ACTIVE_LOCK_MIN_SECONDS = 0.82;
  const ACTIVE_LOCK_MAX_SECONDS = 1.55;
  const REAL_TETRIS_MODES = {
    standard: {
      label: "一般",
      gravity: GRAVITY,
      rebound: 1.18,
      friction: 0.18,
      velocityDamping: 0.992,
      verticalDamping: 0.998,
      angularDamping: 0.94,
      freeAngularDamping: 0.992,
      minDist: CELL * 0.92,
      settleSpeed: 86,
      settleFrames: 24,
      lineFill: RELAXED_LINE_FILL,
      lineTolerance: LINE_TOLERANCE,
      scoreMultiplier: 1,
      stackSupportMargin: CELL * 0.18,
      stackWakeThreshold: CELL * 0.08,
      stackTorque: 34,
      stackDamping: 0.985,
    },
    sticky: {
      label: "黏性",
      gravity: 1260,
      rebound: 0.72,
      friction: 0.46,
      velocityDamping: 0.986,
      verticalDamping: 0.994,
      angularDamping: 0.82,
      freeAngularDamping: 0.986,
      minDist: CELL * 0.98,
      settleSpeed: 118,
      settleFrames: 12,
      lineFill: RELAXED_LINE_FILL,
      lineTolerance: CELL * 0.78,
      scoreMultiplier: 0.9,
      stackSupportMargin: CELL * 0.32,
      stackWakeThreshold: CELL * 0.16,
      stackTorque: 18,
      stackDamping: 0.955,
      sticky: true,
    },
    smooth: {
      label: "光滑",
      gravity: 1100,
      rebound: 1.34,
      friction: 0.055,
      velocityDamping: 0.997,
      verticalDamping: 0.999,
      angularDamping: 0.985,
      freeAngularDamping: 0.997,
      minDist: CELL * 0.88,
      settleSpeed: 58,
      settleFrames: 36,
      lineFill: RELAXED_LINE_FILL,
      lineTolerance: CELL * 0.56,
      scoreMultiplier: 1.2,
      stackSupportMargin: CELL * 0.1,
      stackWakeThreshold: CELL * 0.04,
      stackTorque: 52,
      stackDamping: 0.993,
    },
    wind: {
      label: "風場",
      gravity: 1140,
      rebound: 1.08,
      friction: 0.16,
      velocityDamping: 0.994,
      verticalDamping: 0.998,
      angularDamping: 0.92,
      freeAngularDamping: 0.993,
      minDist: CELL * 0.9,
      settleSpeed: 74,
      settleFrames: 26,
      lineFill: RELAXED_LINE_FILL,
      lineTolerance: CELL * 0.64,
      scoreMultiplier: 1.25,
      stackSupportMargin: CELL * 0.12,
      stackWakeThreshold: CELL * 0.06,
      stackTorque: 46,
      stackDamping: 0.988,
      wind: true,
    },
    magnet: {
      label: "磁力",
      gravity: 1180,
      rebound: 1.0,
      friction: 0.22,
      velocityDamping: 0.99,
      verticalDamping: 0.997,
      angularDamping: 0.88,
      freeAngularDamping: 0.989,
      minDist: CELL * 0.94,
      settleSpeed: 92,
      settleFrames: 18,
      lineFill: RELAXED_LINE_FILL,
      lineTolerance: CELL * 0.7,
      scoreMultiplier: 1.15,
      stackSupportMargin: CELL * 0.2,
      stackWakeThreshold: CELL * 0.1,
      stackTorque: 40,
      stackDamping: 0.976,
      magnet: true,
    },
  };
  const REAL_TETRIS_MODE_ORDER = ["standard", "sticky", "smooth", "wind", "magnet"];
  const REAL_TETRIS_ROOT_PHYSICS_KEY = "hackme.realTetris.physicsParams.v1";
  const BLOCK_COLORS = {
    I: "#28c7fa",
    O: "#ffd166",
    T: "#b779ff",
    S: "#22c79a",
    Z: "#ff4f6d",
    J: "#4d7dff",
    L: "#ff9f43",
  };
  const REAL_TETRIS_ASSET_SOURCES = Object.freeze({
    puzzlePack: {
      name: "Kenney Puzzle Pack 2",
      url: "https://kenney.nl/assets/puzzle-pack-2",
      license: "Creative Commons CC0",
      usage: "bundled PNG rigid block bevels with canvas fallback",
    },
  });
  const REAL_TETRIS_ASSET_BASE = "/assets/games/vendor/kenney/puzzle-pack-2/tiles/";
  const REAL_TETRIS_IMAGE_ASSETS = Object.freeze({
    I: `${REAL_TETRIS_ASSET_BASE}blue_01.png`,
    O: `${REAL_TETRIS_ASSET_BASE}yellow_01.png`,
    T: `${REAL_TETRIS_ASSET_BASE}grey_01.png`,
    S: `${REAL_TETRIS_ASSET_BASE}green_01.png`,
    Z: `${REAL_TETRIS_ASSET_BASE}red_01.png`,
    J: `${REAL_TETRIS_ASSET_BASE}blue_01.png`,
    L: `${REAL_TETRIS_ASSET_BASE}yellow_01.png`,
  });
  const REAL_TETRIS_IMAGES = {};
  const PIECES = {
    I: [[-1.5, 0], [-0.5, 0], [0.5, 0], [1.5, 0]],
    O: [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]],
    T: [[-1, 0], [0, 0], [1, 0], [0, -1]],
    S: [[-0.5, 0], [0.5, 0], [0.5, -1], [1.5, -1]],
    Z: [[-0.5, -1], [0.5, -1], [0.5, 0], [1.5, 0]],
    J: [[-1, -1], [-1, 0], [0, 0], [1, 0]],
    L: [[1, -1], [-1, 0], [0, 0], [1, 0]],
  };
  const STACK_CONNECT_DIST = CELL * 1.18;
  const STACK_CHECK_INTERVAL = 7;

  function realTetrisModeConfig(mode) {
    return REAL_TETRIS_MODES[mode] || REAL_TETRIS_MODES.standard;
  }

  function realTetrisModeLabel(mode) {
    return realTetrisModeConfig(mode).label;
  }

  function nextRealTetrisMode(mode) {
    const index = REAL_TETRIS_MODE_ORDER.indexOf(mode);
    return REAL_TETRIS_MODE_ORDER[(index + 1) % REAL_TETRIS_MODE_ORDER.length] || "standard";
  }

  function realTetrisImageFor(type) {
    const src = REAL_TETRIS_IMAGE_ASSETS[type];
    if (!src || typeof Image === "undefined") return null;
    if (!REAL_TETRIS_IMAGES[type]) {
      const image = new Image();
      image.decoding = "async";
      image.src = src;
      REAL_TETRIS_IMAGES[type] = image;
    }
    return REAL_TETRIS_IMAGES[type];
  }

  function realTetrisImageReady(image) {
    return Boolean(image?.complete && image.naturalWidth > 0);
  }

  function realTetrisRootUser() {
    return typeof currentUser !== "undefined" && currentUser === "root";
  }

  function realTetrisDefaultPhysicsParams(mode) {
    const config = realTetrisModeConfig(mode);
    return {
      gravity: config.gravity,
      elasticity: clamp(config.rebound - 0.35, 0.05, 1.4),
      friction: config.friction,
      stackTorque: config.stackTorque,
      stackDamping: config.stackDamping,
    };
  }

  function readRealTetrisStoredParams() {
    try {
      const raw = window.localStorage?.getItem(REAL_TETRIS_ROOT_PHYSICS_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function writeRealTetrisStoredParams(mode, params) {
    try {
      const stored = readRealTetrisStoredParams();
      stored[mode] = params;
      window.localStorage?.setItem(REAL_TETRIS_ROOT_PHYSICS_KEY, JSON.stringify(stored));
    } catch (err) {
      // Physics tuning is runtime-only when localStorage is unavailable.
    }
  }

  function loadRealTetrisPhysicsParams(mode) {
    const defaults = realTetrisDefaultPhysicsParams(mode);
    const stored = readRealTetrisStoredParams()[mode] || {};
    const params = { ...defaults };
    Object.keys(params).forEach((key) => {
      const value = Number(stored[key]);
      if (Number.isFinite(value)) params[key] = value;
    });
    return params;
  }

  function realTetrisRootControlsHtml(mode) {
    if (!realTetrisRootUser()) return "";
    const params = loadRealTetrisPhysicsParams(mode);
    return `
      <div class="real-tetris-root-controls" aria-label="root 物理參數">
        <label>重力 <input type="range" min="650" max="1800" step="10" value="${params.gravity}" data-real-tetris-param="gravity" /><span data-real-tetris-value="gravity">${Math.round(params.gravity)}</span></label>
        <label>彈性 <input type="range" min="0.05" max="1.45" step="0.01" value="${params.elasticity}" data-real-tetris-param="elasticity" /><span data-real-tetris-value="elasticity">${params.elasticity.toFixed(2)}</span></label>
        <label>摩擦 <input type="range" min="0.01" max="0.75" step="0.01" value="${params.friction}" data-real-tetris-param="friction" /><span data-real-tetris-value="friction">${params.friction.toFixed(2)}</span></label>
        <label>倒塌力矩 <input type="range" min="0" max="96" step="1" value="${params.stackTorque}" data-real-tetris-param="stackTorque" /><span data-real-tetris-value="stackTorque">${Math.round(params.stackTorque)}</span></label>
        <label>阻尼 <input type="range" min="0.920" max="0.999" step="0.001" value="${params.stackDamping}" data-real-tetris-param="stackDamping" /><span data-real-tetris-value="stackDamping">${params.stackDamping.toFixed(3)}</span></label>
        <button class="btn game-mini-btn" type="button" data-real-tetris-reset="1">重設物理</button>
      </div>
    `;
  }

  function renderRealTetrisRoot(api) {
    const mode = api._realTetrisMode || "standard";
    api.root.innerHTML = `
      <div class="real-tetris-shell">
        <canvas class="real-tetris-canvas" width="${WIDTH}" height="${HEIGHT}" aria-label="真實版俄羅斯方塊"></canvas>
        ${realTetrisRootControlsHtml(mode)}
      </div>
    `;
  }

  function syncRealTetrisRootControls(api, state) {
    const root = api.root;
    if (!root || !state?.physicsParams) return;
    Object.entries(state.physicsParams).forEach(([key, value]) => {
      const input = root.querySelector(`[data-real-tetris-param="${key}"]`);
      const label = root.querySelector(`[data-real-tetris-value="${key}"]`);
      if (input) input.value = String(value);
      if (label) label.textContent = key === "gravity" || key === "stackTorque" ? String(Math.round(value)) : key === "stackDamping" ? Number(value).toFixed(3) : Number(value).toFixed(2);
    });
  }

  function setRealTetrisActions(api) {
    const mode = api._realTetrisMode || "standard";
    api.setActions(`
      <button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>
      <button class="btn game-mini-btn" type="button" data-action="pause">暫停</button>
      <button class="btn game-mini-btn" type="button" data-action="mode">模式：${realTetrisModeLabel(mode)}</button>
      <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
    `);
  }

  function showRealTetrisReady(api) {
    if (api._realTetrisState?.raf) cancelAnimationFrame(api._realTetrisState.raf);
    const mode = api._realTetrisMode || "standard";
    const state = {
      canvas: api.root.querySelector("canvas"),
      mode,
      physicsParams: loadRealTetrisPhysicsParams(mode),
      active: null,
      blocks: [],
      input: { left: false, right: false, down: false, rotate: 0 },
      score: 0,
      lines: 0,
      collapseEvents: 0,
      tick: 0,
      status: "ready",
      paused: false,
      startedAt: Date.now(),
      completedAt: null,
      dailyChallenge: null,
      raf: null,
    };
    api._realTetrisState = null;
    syncRealTetrisRootControls(api, state);
    if (state.canvas) {
      drawRealTetris(state, state.canvas);
      const ctx = state.canvas.getContext("2d");
      ctx.fillStyle = "rgba(7,17,31,.68)";
      ctx.fillRect(LEFT, 190, RIGHT - LEFT, 86);
      ctx.textAlign = "center";
      ctx.fillStyle = "#e2e8f0";
      ctx.font = "700 22px system-ui, sans-serif";
      ctx.fillText("真實版俄羅斯方塊", WIDTH / 2, 226);
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillStyle = "rgba(226,232,240,.84)";
      ctx.fillText("按開始後才會啟動物理模擬與計時", WIDTH / 2, 252);
      ctx.textAlign = "start";
    }
    api.status(`待機 · ${realTetrisModeLabel(mode)} · 按開始啟動物理模擬。`);
  }

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

  function realTetrisBodyBounds(body) {
    const centers = realTetrisPieceCenters(body);
    return {
      minX: Math.min(...centers.map((point) => point.x - HALF)),
      maxX: Math.max(...centers.map((point) => point.x + HALF)),
      minY: Math.min(...centers.map((point) => point.y - HALF)),
      maxY: Math.max(...centers.map((point) => point.y + HALF)),
      centers,
    };
  }

  function realTetrisBodiesCellContact(a, b, minDist) {
    const aCenters = realTetrisPieceCenters(a);
    const bCenters = realTetrisPieceCenters(b);
    let best = null;
    for (const aPoint of aCenters) {
      for (const bPoint of bCenters) {
        if (Math.abs(aPoint.x - bPoint.x) > minDist || Math.abs(aPoint.y - bPoint.y) > minDist) continue;
        let dx = aPoint.x - bPoint.x;
        let dy = aPoint.y - bPoint.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.001) {
          dx = 0;
          dy = -1;
          dist = 1;
        }
        if (dist >= minDist) continue;
        const penetration = minDist - dist;
        if (!best || penetration > best.penetration) {
          best = {
            nx: dx / dist,
            ny: dy / dist,
            penetration,
            aPoint,
            bPoint,
          };
        }
      }
    }
    return best;
  }

  function realTetrisActiveLockDelay(config) {
    return clamp((config.settleFrames / 60) * 2.4, ACTIVE_LOCK_MIN_SECONDS, ACTIVE_LOCK_MAX_SECONDS);
  }

  function updateRealTetrisActiveLock(body, dt) {
    if (body.supporting) {
      body.supportFrames = (body.supportFrames || 0) + 1;
      body.supportEver = true;
    } else {
      body.supportFrames = Math.max(0, (body.supportFrames || 0) - 1);
    }
    if (body.supportEver) body.supportLockAge = (body.supportLockAge || 0) + dt;
  }

  function shouldLockRealTetrisBody(body, speed, config) {
    if (!body.supporting) return false;
    if (speed < config.settleSpeed && body.settledFrames > config.settleFrames) return true;
    return Number(body.supportLockAge || 0) >= realTetrisActiveLockDelay(config);
  }

  function drawRealTetrisBlock(ctx, x, y, angle, type, alpha = 1) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.globalAlpha = alpha;
    const color = BLOCK_COLORS[type] || "#e5e7eb";
    const gradient = ctx.createLinearGradient(-HALF, -HALF, HALF, HALF);
    gradient.addColorStop(0, "rgba(255,255,255,.34)");
    gradient.addColorStop(0.18, color);
    gradient.addColorStop(1, "rgba(15,23,42,.42)");
    ctx.fillStyle = gradient;
    ctx.strokeStyle = "rgba(255,255,255,.34)";
    ctx.lineWidth = 1.4;
    ctx.shadowColor = "rgba(56,189,248,.18)";
    ctx.shadowBlur = 10;
    const image = realTetrisImageFor(type);
    if (realTetrisImageReady(image)) {
      ctx.drawImage(image, -HALF + 1.5, -HALF + 1.5, CELL - 3, CELL - 3);
      ctx.fillStyle = "rgba(255,255,255,.16)";
      ctx.fillRect(-HALF + 3, -HALF + 3, CELL - 6, 4);
    } else {
      ctx.fillRect(-HALF + 1.5, -HALF + 1.5, CELL - 3, CELL - 3);
    }
    ctx.shadowBlur = 0;
    ctx.strokeRect(-HALF + 1.5, -HALF + 1.5, CELL - 3, CELL - 3);
    ctx.fillStyle = "rgba(255,255,255,.16)";
    ctx.fillRect(-HALF + 4, -HALF + 4, CELL - 8, 4);
    ctx.fillStyle = "rgba(15,23,42,.18)";
    ctx.fillRect(-HALF + 5, HALF - 8, CELL - 10, 3);
    ctx.restore();
  }

  function createRealTetrisBody(state) {
    const names = Object.keys(PIECES);
    const type = names[Math.floor(Math.random() * names.length)];
    const config = realTetrisModeConfig(state?.mode);
    const spinScale = state?.mode === "smooth" ? 1.25 : state?.mode === "sticky" ? 0.72 : 1;
    return {
      type,
      cells: centerRealTetrisCells(PIECES[type]),
      x: (LEFT + RIGHT) / 2,
      y: TOP + CELL * 1.6,
      angle: (Math.random() - 0.5) * 0.18,
      vx: (Math.random() - 0.5) * 26 * (state?.mode === "smooth" ? 1.35 : 1),
      vy: 0,
      omega: (Math.random() - 0.5) * 0.55 * spinScale,
      settledFrames: 0,
      supportFrames: 0,
      supportLockAge: 0,
      supportEver: false,
      touching: false,
      supporting: false,
      friction: config.friction,
      mass: 4,
    };
  }

  function realTetrisBlockSpeed(block) {
    return Math.hypot(block.vx || 0, block.vy || 0) + Math.abs(block.omega || 0) * CELL;
  }

  function wakeRealTetrisBlock(block, impulseX = 0, impulseY = 0, torque = 0) {
    block.vx = clamp((block.vx || 0) + impulseX, -360, 360);
    block.vy = clamp((block.vy || 0) + impulseY, -520, 720);
    block.omega = clamp((block.omega || 0) + torque, -7.5, 7.5);
    block.unstable = true;
    block.settledFrames = 0;
  }

  function blockHasVerticalSupport(block, blocks) {
    const centers = realTetrisPieceCenters(block);
    if (centers.some((point) => point.y + HALF >= FLOOR - CELL * 0.12)) return true;
    return blocks.some((other) => {
      if (other === block) return false;
      const otherCenters = realTetrisPieceCenters(other);
      return centers.some((point) => otherCenters.some((otherPoint) => (
        otherPoint.y > point.y
        && otherPoint.y - point.y < CELL * 1.12
        && Math.abs(otherPoint.x - point.x) < CELL * 0.74
      )));
    });
  }

  function realTetrisBlocksTouch(a, b, dist = STACK_CONNECT_DIST) {
    if (Math.abs(a.x - b.x) > dist * 4 || Math.abs(a.y - b.y) > dist * 4) return false;
    return Boolean(realTetrisBodiesCellContact(a, b, dist));
  }

  function collectRealTetrisStacks(blocks) {
    const visited = new Set();
    const stacks = [];
    blocks.forEach((block, index) => {
      if (visited.has(index)) return;
      const stack = [];
      const queue = [index];
      visited.add(index);
      while (queue.length) {
        const currentIndex = queue.shift();
        const current = blocks[currentIndex];
        stack.push(current);
        blocks.forEach((candidate, candidateIndex) => {
          if (visited.has(candidateIndex)) return;
          if (!realTetrisBlocksTouch(current, candidate)) return;
          visited.add(candidateIndex);
          queue.push(candidateIndex);
        });
      }
      stacks.push(stack);
    });
    return stacks;
  }

  function wakeRealTetrisStack(state, stack, pivotX, direction, excess) {
    const config = realTetrisModeConfig(state.mode);
    const params = state.physicsParams || realTetrisDefaultPhysicsParams(state.mode);
    const strength = clamp((Math.abs(excess) + CELL * 0.1) / CELL, 0.18, 2.6) * Number(params.stackTorque || config.stackTorque);
    stack.forEach((block) => {
      const heightFactor = clamp((FLOOR - block.y) / (CELL * 9), 0.18, 1.45);
      const lever = clamp((block.x - pivotX) / CELL, -2.4, 2.4);
      const lateral = direction * strength * (0.36 + heightFactor * 0.55);
      const torque = direction * strength * 0.018 * (0.7 + heightFactor) + lever * strength * 0.006;
      wakeRealTetrisBlock(block, lateral, -Math.abs(lateral) * 0.08, torque);
    });
    state.collapseEvents = (state.collapseEvents || 0) + 1;
    state.lastCollapseAt = state.tick || 0;
  }

  function applyRealTetrisStackStability(state, force = false) {
    if (!state.blocks.length) return;
    state.stabilityFrame = (state.stabilityFrame || 0) + 1;
    if (!force && state.stabilityFrame % STACK_CHECK_INTERVAL !== 0) return;
    const config = realTetrisModeConfig(state.mode);
    for (const stack of collectRealTetrisStacks(state.blocks)) {
      const mass = stack.reduce((sum, block) => sum + (block.mass || 1), 0) || 1;
      const comX = stack.reduce((sum, block) => sum + block.x * (block.mass || 1), 0) / mass;
      const floorContacts = stack.flatMap((block) => (
        realTetrisPieceCenters(block).filter((point) => point.y + HALF >= FLOOR - CELL * 0.18)
      ));
      if (!floorContacts.length) {
        stack.forEach((block) => {
          if (!blockHasVerticalSupport(block, state.blocks)) wakeRealTetrisBlock(block, 0, 20, 0);
        });
        continue;
      }
      const supportMin = Math.min(...floorContacts.map((point) => point.x - HALF * 0.62)) - config.stackSupportMargin;
      const supportMax = Math.max(...floorContacts.map((point) => point.x + HALF * 0.62)) + config.stackSupportMargin;
      const supportCenter = (supportMin + supportMax) / 2;
      const supportHalf = Math.max(CELL * 0.35, (supportMax - supportMin) / 2);
      const outside = comX < supportMin ? comX - supportMin : comX > supportMax ? comX - supportMax : 0;
      const edgeBias = (comX - supportCenter) / supportHalf;
      const overload = Math.abs(outside) > config.stackWakeThreshold || Math.abs(edgeBias) > 0.82;
      if (!overload) continue;
      const direction = Math.sign(outside || edgeBias) || 1;
      const pivotX = direction > 0 ? supportMax : supportMin;
      const excess = outside || (edgeBias * config.stackWakeThreshold);
      wakeRealTetrisStack(state, stack, pivotX, direction, excess);
    }
  }

  function realTetrisBlockElasticImpulse(state, a, b, nx, ny, penetration) {
    const config = realTetrisModeConfig(state.mode);
    const restitution = clamp(Number(state.physicsParams?.elasticity ?? (config.rebound - 0.35)), 0, 1.8);
    const tangentX = -ny;
    const tangentY = nx;
    const aDynamic = a.unstable || realTetrisBlockSpeed(a) > 8;
    const bDynamic = b.unstable || realTetrisBlockSpeed(b) > 8;
    if (!aDynamic && !bDynamic) return;
    const totalMass = (a.mass || 1) + (b.mass || 1);
    const aShare = bDynamic ? (b.mass || 1) / totalMass : 1;
    const bShare = aDynamic ? (a.mass || 1) / totalMass : 1;
    const rvx = (a.vx || 0) - (b.vx || 0);
    const rvy = (a.vy || 0) - (b.vy || 0);
    const normalVelocity = rvx * nx + rvy * ny;
    const tangentVelocity = rvx * tangentX + rvy * tangentY;
    const impulse = normalVelocity < 0 ? -(1 + restitution) * normalVelocity : penetration * 8;
    if (aDynamic) {
      a.x += nx * penetration * aShare;
      a.y += ny * penetration * aShare;
      a.vx = (a.vx || 0) + nx * impulse * aShare;
      a.vy = (a.vy || 0) + ny * impulse * aShare;
      a.omega = (a.omega || 0) + tangentVelocity * 0.0025 * aShare;
    }
    if (bDynamic) {
      b.x -= nx * penetration * bShare;
      b.y -= ny * penetration * bShare;
      b.vx = (b.vx || 0) - nx * impulse * bShare;
      b.vy = (b.vy || 0) - ny * impulse * bShare;
      b.omega = (b.omega || 0) - tangentVelocity * 0.0025 * bShare;
    }
    if (Math.abs(impulse) > 42 || penetration > CELL * 0.16) {
      a.unstable = true;
      b.unstable = true;
      a.settledFrames = 0;
      b.settledFrames = 0;
    }
  }

  function resolveRealTetrisSettledBlockCollisions(state) {
    const config = realTetrisModeConfig(state.mode);
    const minDist = config.minDist * 0.96;
    for (let i = 0; i < state.blocks.length; i += 1) {
      for (let j = i + 1; j < state.blocks.length; j += 1) {
        const a = state.blocks[i];
        const b = state.blocks[j];
        if (Math.abs(a.x - b.x) > CELL * 5 || Math.abs(a.y - b.y) > CELL * 5) continue;
        const contact = realTetrisBodiesCellContact(a, b, minDist);
        if (!contact) continue;
        realTetrisBlockElasticImpulse(state, a, b, contact.nx, contact.ny, contact.penetration);
      }
    }
  }

  function integrateRealTetrisSettledBlocks(state, dt) {
    if (!state.blocks.length) return;
    const config = realTetrisModeConfig(state.mode);
    const gravity = Number(state.physicsParams?.gravity || config.gravity);
    const friction = Number(state.physicsParams?.friction ?? config.friction);
    const damping = Number(state.physicsParams?.stackDamping ?? config.stackDamping);
    let anyDynamic = false;
    state.blocks.forEach((block) => {
      if (!block.unstable && realTetrisBlockSpeed(block) < 8) return;
      anyDynamic = true;
      block.unstable = true;
      block.vy = (block.vy || 0) + gravity * 0.86 * dt;
      block.vx = clamp((block.vx || 0) * damping, -420, 420);
      block.vy = clamp((block.vy || 0) * config.verticalDamping, -520, 940);
      block.omega = clamp((block.omega || 0) * config.freeAngularDamping, -7.5, 7.5);
      block.x += block.vx * dt;
      block.y += block.vy * dt;
      block.angle += block.omega * dt;
      let bounds = realTetrisBodyBounds(block);
      if (bounds.minX < LEFT) {
        block.x += LEFT - bounds.minX;
        block.vx = Math.abs(block.vx || 0) * 0.42;
        block.omega *= -0.45;
      }
      bounds = realTetrisBodyBounds(block);
      if (bounds.maxX > RIGHT) {
        block.x -= bounds.maxX - RIGHT;
        block.vx = -Math.abs(block.vx || 0) * 0.42;
        block.omega *= -0.45;
      }
      bounds = realTetrisBodyBounds(block);
      if (bounds.maxY > FLOOR) {
        block.y -= bounds.maxY - FLOOR;
        if ((block.vy || 0) > 0) block.vy = -Math.abs(block.vy || 0) * clamp(Number(state.physicsParams?.elasticity ?? 0.42), 0.05, 0.72);
        block.vx *= Math.max(0.24, 1 - friction * 1.7);
        block.omega *= Math.max(0.35, 1 - friction * 1.4);
      }
    });
    if (!anyDynamic) return;
    for (let iteration = 0; iteration < 3; iteration += 1) resolveRealTetrisSettledBlockCollisions(state);
    state.blocks.forEach((block) => {
      const speed = realTetrisBlockSpeed(block);
      const supported = blockHasVerticalSupport(block, state.blocks);
      block.settledFrames = supported && speed < config.settleSpeed * 0.42 ? (block.settledFrames || 0) + 1 : 0;
      if (block.settledFrames > config.settleFrames) {
        block.unstable = false;
        block.vx = 0;
        block.vy = 0;
        block.omega = 0;
      }
    });
  }

  function pushRealTetrisBody(state, body, nx, ny, penetration, rx, ry) {
    const config = realTetrisModeConfig(state.mode);
    const params = state.physicsParams || realTetrisDefaultPhysicsParams(state.mode);
    const rebound = 1 + clamp(Number(params.elasticity), 0, 1.8);
    const friction = clamp(Number(params.friction), 0, 0.9);
    body.x += nx * penetration;
    body.y += ny * penetration;
    const vn = body.vx * nx + body.vy * ny;
    if (vn < 0) {
      body.vx -= (rebound * vn) * nx;
      body.vy -= (rebound * vn) * ny;
    }
    const tangentX = -ny;
    const tangentY = nx;
    const vt = body.vx * tangentX + body.vy * tangentY;
    body.vx -= vt * tangentX * friction;
    body.vy -= vt * tangentY * friction;
    body.omega += (rx * ny - ry * nx) * penetration * 0.0009;
    body.omega *= config.angularDamping;
    if (config.sticky) {
      body.vx *= 0.94;
      body.vy *= 0.92;
    }
  }

  function resolveRealTetrisCollisions(state) {
    const body = state.active;
    if (!body) return;
    const config = realTetrisModeConfig(state.mode);
    body.touching = false;
    body.supporting = false;
    for (let iteration = 0; iteration < 3; iteration += 1) {
      const centers = realTetrisPieceCenters(body);
      for (const point of centers) {
        if (point.x - HALF < LEFT) {
          pushRealTetrisBody(state, body, 1, 0, LEFT - (point.x - HALF), point.rx, point.ry);
        }
        if (point.x + HALF > RIGHT) {
          pushRealTetrisBody(state, body, -1, 0, (point.x + HALF) - RIGHT, point.rx, point.ry);
        }
        if (point.y + HALF > FLOOR) {
          body.touching = true;
          body.supporting = true;
          pushRealTetrisBody(state, body, 0, -1, (point.y + HALF) - FLOOR, point.rx, point.ry);
        }
        for (const block of state.blocks) {
          if (Math.abs(point.x - block.x) > CELL * 5 || Math.abs(point.y - block.y) > CELL * 5) continue;
          for (const settledPoint of realTetrisPieceCenters(block)) {
            if (Math.abs(point.x - settledPoint.x) > CELL * 1.15 || Math.abs(point.y - settledPoint.y) > CELL * 1.15) continue;
            let dx = point.x - settledPoint.x;
            let dy = point.y - settledPoint.y;
            let dist = Math.hypot(dx, dy);
            if (dist < 0.001) {
              dx = 0;
              dy = -1;
              dist = 1;
            }
            const minDist = config.minDist;
            if (dist >= minDist) continue;
            const nx = dx / dist;
            const ny = dy / dist;
            body.touching = true;
            if (ny < -0.35) body.supporting = true;
            pushRealTetrisBody(state, body, nx, ny, minDist - dist, point.rx, point.ry);
            if (Math.abs(body.vx) + Math.abs(body.vy) > 90 || minDist - dist > CELL * 0.12) {
              wakeRealTetrisBlock(block, -nx * (18 + Math.abs(body.vx) * 0.04), -ny * 18, (point.rx * ny - point.ry * nx) * 0.0018);
            }
          }
        }
      }
    }
  }

  function integrateRealTetrisPhysics(state, dt) {
    const body = state.active;
    if (!body || state.status !== "active" || state.paused) return;
    const config = realTetrisModeConfig(state.mode);
    const params = state.physicsParams || realTetrisDefaultPhysicsParams(state.mode);
    const input = state.input;
    state.tick = (state.tick || 0) + 1;
    integrateRealTetrisSettledBlocks(state, dt);
    applyRealTetrisStackStability(state);
    if (input.left) body.vx -= 860 * dt;
    if (input.right) body.vx += 860 * dt;
    if (input.down) body.vy += 760 * dt;
    if (input.rotate) body.omega += (input.rotate > 0 ? 7.2 : -7.2) * dt;
    if (config.wind) {
      const gust = Math.sin((state.tick || 0) * 0.028) * 520 + Math.sin((state.tick || 0) * 0.011) * 280;
      body.vx += gust * dt;
      body.omega += Math.sin((state.tick || 0) * 0.019) * 1.2 * dt;
    }
    if (config.magnet && state.blocks.length) {
      const nearest = state.blocks.reduce((best, block) => {
        const dist = Math.hypot(block.x - body.x, block.y - body.y);
        return !best || dist < best.dist ? { block, dist } : best;
      }, null);
      if (nearest?.block && nearest.dist < CELL * 5.5) {
        body.vx += clamp(nearest.block.x - body.x, -CELL * 2, CELL * 2) * 2.2 * dt;
        body.omega += clamp(nearest.block.x - body.x, -CELL, CELL) * 0.015 * dt;
      }
    }
    body.vy += Number(params.gravity || config.gravity) * dt;
    body.vx *= config.velocityDamping;
    body.vy *= config.verticalDamping;
    body.omega *= config.freeAngularDamping;
    body.vx = clamp(body.vx, -360, 360);
    body.vy = clamp(body.vy, -280, 900);
    body.omega = clamp(body.omega, -7.5, 7.5);
    body.x += body.vx * dt;
    body.y += body.vy * dt;
    body.angle += body.omega * dt;
    resolveRealTetrisCollisions(state);
    const speed = Math.hypot(body.vx, body.vy) + Math.abs(body.omega) * 28;
    updateRealTetrisActiveLock(body, dt);
    body.settledFrames = body.touching && speed < config.settleSpeed ? body.settledFrames + 1 : 0;
    if (shouldLockRealTetrisBody(body, speed, config)) lockRealTetrisBody(state);
  }

  function rowCoverageForRealTetris(blocks, rowY, config) {
    const segments = [];
    for (const body of blocks) {
      for (const block of realTetrisPieceCenters(body)) {
        if (Math.abs(block.y - rowY) > config.lineTolerance) continue;
        const widthBoost = 1 + Math.max(0, 1 - Math.abs(block.y - rowY) / config.lineTolerance) * 0.18;
        const halfWidth = HALF * 0.94 * widthBoost;
        segments.push([clamp(block.x - halfWidth, LEFT, RIGHT), clamp(block.x + halfWidth, LEFT, RIGHT)]);
      }
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
    const config = realTetrisModeConfig(state.mode);
    const rows = [];
    for (let row = 0; row < 18; row += 1) {
      const y = FLOOR - HALF - row * CELL;
      const coverage = rowCoverageForRealTetris(state.blocks, y, config);
      if (coverage >= config.lineFill) rows.push({ row, y, coverage });
    }
    if (!rows.length) return 0;
    const remove = new Set();
    rows.forEach(({ y }) => {
      state.blocks.forEach((body, index) => {
        if (realTetrisPieceCenters(body).some((block) => Math.abs(block.y - y) <= config.lineTolerance)) remove.add(index);
      });
    });
    state.blocks = state.blocks.filter((_block, index) => !remove.has(index));
    for (const block of state.blocks) {
      const clearedBelow = rows.filter(({ y }) => block.y < y - config.lineTolerance * 0.28).length;
      if (clearedBelow) {
        block.y += clearedBelow * CELL;
        wakeRealTetrisBlock(block, 0, 24 * clearedBelow, 0);
      }
    }
    state.lines += rows.length;
    state.score += (rows.length * 180 + Math.round(rows.reduce((sum, row) => sum + row.coverage, 0) * 80)) * config.scoreMultiplier;
    return rows.length;
  }

  function realTetrisGameOver(state) {
    return state.blocks.some((block) => realTetrisPieceCenters(block).some((point) => point.y < TOP + CELL * 1.4));
  }

  function lockRealTetrisBody(state) {
    const body = state.active;
    if (!body) return;
    let bounds = realTetrisBodyBounds(body);
    if (bounds.minX < LEFT) body.x += LEFT - bounds.minX;
    bounds = realTetrisBodyBounds(body);
    if (bounds.maxX > RIGHT) body.x -= bounds.maxX - RIGHT;
    bounds = realTetrisBodyBounds(body);
    if (bounds.maxY > FLOOR) body.y -= bounds.maxY - FLOOR;
    state.blocks.push({
      x: clamp(body.x, LEFT + HALF * 0.35, RIGHT - HALF * 0.35),
      y: clamp(body.y, TOP - CELL, FLOOR - HALF * 0.25),
      angle: body.angle,
      cells: body.cells.map((cell) => [...cell]),
      type: body.type,
      vx: 0,
      vy: 0,
      omega: 0,
      mass: body.cells.length || 4,
      unstable: false,
      settledFrames: 0,
    });
    state.score += 12;
    state.active = null;
    clearRealTetrisRelaxedLines(state);
    applyRealTetrisStackStability(state, true);
    if (realTetrisGameOver(state)) {
      finishRealTetrisGame(state.api);
      return;
    }
    state.active = createRealTetrisBody(state);
  }

  function drawRealTetris(state, canvas) {
    const ctx = canvas.getContext("2d");
    const config = realTetrisModeConfig(state.mode);
    canvas.dataset.assetTheme = "kenney-puzzle-pack";
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    const backdrop = ctx.createLinearGradient(0, 0, 0, HEIGHT);
    backdrop.addColorStop(0, "#08111f");
    backdrop.addColorStop(0.6, "#111827");
    backdrop.addColorStop(1, "#07111f");
    ctx.fillStyle = backdrop;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "rgba(15,23,42,.9)";
    ctx.fillRect(LEFT, TOP, RIGHT - LEFT, FLOOR - TOP);
    ctx.fillStyle = "rgba(255,255,255,.035)";
    for (let y = TOP + CELL; y < FLOOR; y += CELL * 2) ctx.fillRect(LEFT, y, RIGHT - LEFT, CELL);
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
    state.blocks.forEach((block) => {
      realTetrisPieceCenters(block).forEach((point) => {
        drawRealTetrisBlock(ctx, point.x, point.y, block.angle, block.type);
      });
    });
    if (state.active) {
      realTetrisPieceCenters(state.active).forEach((point) => {
        drawRealTetrisBlock(ctx, point.x, point.y, state.active.angle, state.active.type, 0.98);
      });
    }
    ctx.fillStyle = "rgba(226,232,240,.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`${realTetrisModeLabel(state.mode)} line ${Math.round(config.lineFill * 100)}%`, LEFT + 8, FLOOR + 20);
    if (config.wind) ctx.fillText("wind gust", LEFT + 8, FLOOR + 38);
    if (config.magnet) ctx.fillText("magnet pull", LEFT + 8, FLOOR + 38);
    if (state.collapseEvents) ctx.fillText(`collapse ${state.collapseEvents}`, RIGHT - 92, FLOOR + 20);
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
    api.status(`${prefix ? `${prefix} ` : ""}${realTetrisModeLabel(state.mode)} · ${mode} · 分數 ${Number(state.score || 0).toLocaleString()} · 90% 消線 ${state.lines} 行 · 倒塌 ${state.collapseEvents || 0} · ${elapsed}`);
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
        // Fallback weekly ranking difficulty: `physics-${state.mode}`.
        difficulty: state.dailyChallenge?.difficulty || `physics-${state.mode}`,
        puzzle_id: state.dailyChallenge?.key || `real-tetris-${state.mode}`,
        raw_elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
        elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
        penalty_seconds: 0,
        guess_count: 0,
        lines: Number(state.lines || 0),
        collapse: Number(state.collapseEvents || 0),
      });
    }
  }

  function startRealTetris(api) {
    const canvas = api.root.querySelector("canvas");
    const state = {
      api,
      canvas,
      mode: api._realTetrisMode || "standard",
      physicsParams: loadRealTetrisPhysicsParams(api._realTetrisMode || "standard"),
      active: null,
      blocks: [],
      input: { left: false, right: false, down: false, rotate: 0 },
      score: 0,
      lines: 0,
      collapseEvents: 0,
      tick: 0,
      status: "active",
      paused: false,
      startedAt: Date.now(),
      completedAt: null,
      dailyChallenge: api.dailyChallenge?.() || null,
      lastFrame: performance.now(),
      raf: null,
    };
    syncRealTetrisRootControls(api, state);
    state.active = createRealTetrisBody(state);
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

  function handleRealTetrisRootParamInput(api, target) {
    if (!realTetrisRootUser() || !target?.dataset?.realTetrisParam) return;
    const state = api._realTetrisState;
    const mode = api._realTetrisMode || state?.mode || "standard";
    const params = state?.physicsParams || loadRealTetrisPhysicsParams(mode);
    const key = target.dataset.realTetrisParam;
    const value = Number(target.value);
    if (!Number.isFinite(value) || !(key in params)) return;
    params[key] = value;
    if (state) state.physicsParams = params;
    writeRealTetrisStoredParams(mode, params);
    syncRealTetrisRootControls(api, { physicsParams: params });
    if (state) {
      applyRealTetrisStackStability(state, true);
      updateRealTetrisStatus(api, state, "root 物理參數已更新。");
    }
  }

  function resetRealTetrisRootParams(api) {
    if (!realTetrisRootUser()) return;
    const mode = api._realTetrisMode || api._realTetrisState?.mode || "standard";
    const params = realTetrisDefaultPhysicsParams(mode);
    writeRealTetrisStoredParams(mode, params);
    if (api._realTetrisState) {
      api._realTetrisState.physicsParams = params;
      applyRealTetrisStackStability(api._realTetrisState, true);
      updateRealTetrisStatus(api, api._realTetrisState, "root 物理參數已重設。");
    }
    syncRealTetrisRootControls(api, { physicsParams: params });
  }

  window.registerHackmeLocalGameModule("real_tetris", {
    mount(api) {
      api.setTitle("真實版俄羅斯方塊");
      api.setSwipeMode?.("hold");
      api._realTetrisMode = api._realTetrisMode || "standard";
      renderRealTetrisRoot(api);
      setRealTetrisActions(api);
      const rootInputHandler = (event) => handleRealTetrisRootParamInput(api, event.target);
      const rootClickHandler = (event) => {
        if (event.target?.closest?.("[data-real-tetris-reset]")) resetRealTetrisRootParams(api);
      };
      api.root.addEventListener("input", rootInputHandler);
      api.root.addEventListener("click", rootClickHandler);
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
        if (action === "mode") {
          api._realTetrisMode = nextRealTetrisMode(api._realTetrisMode || "standard");
          setRealTetrisActions(api);
          if (api._realTetrisState?.raf) cancelAnimationFrame(api._realTetrisState.raf);
          renderRealTetrisRoot(api);
          showRealTetrisReady(api);
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
      showRealTetrisReady(api);
      return () => {
        api.root.removeEventListener("input", rootInputHandler);
        api.root.removeEventListener("click", rootClickHandler);
        if (api._realTetrisState?.raf) cancelAnimationFrame(api._realTetrisState.raf);
        api._realTetrisState = null;
      };
    },
  });
}());
